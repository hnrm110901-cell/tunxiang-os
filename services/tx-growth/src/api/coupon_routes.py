"""优惠券发放 API — prefix /api/v1/growth/coupons

端点:
1. GET  /api/v1/growth/coupons/available          可领取优惠券列表
2. POST /api/v1/growth/coupons/claim              领取优惠券（幂等）
3. POST /api/v1/growth/coupons/verify             核销验证
4. GET  /api/v1/growth/coupons/my                 我的优惠券（重定向到 tx-member）
5. POST /api/v1/growth/coupons/{coupon_id}/apply  核销优惠券（收银员确认后）
"""
import asyncio
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import CampaignEventType
from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/growth/coupons", tags=["growth-coupons"])

_TABLE_NOT_READY_TABLES = {"coupons", "customer_coupons"}


# ---------------------------------------------------------------------------
# 统一响应
# ---------------------------------------------------------------------------

def ok_response(data: Any) -> dict:
    return {"ok": True, "data": data}


def error_response(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------

class ClaimCouponRequest(BaseModel):
    coupon_id: str
    customer_id: str


class VerifyCouponRequest(BaseModel):
    customer_coupon_id: str
    customer_id: str
    verify_code: Optional[str] = None


class ApplyCouponRequest(BaseModel):
    order_id: str
    store_id: str
    order_amount_fen: int   # 订单金额（分）
    operator_id: str


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------

async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _is_table_missing(exc: SQLAlchemyError) -> bool:
    """判断是否为表不存在的 TABLE_NOT_READY 错误"""
    msg = str(exc).lower()
    return "does not exist" in msg or "relation" in msg and "exist" in msg


def _row_to_coupon(row) -> dict:
    return {
        "id": str(row.id),
        "name": row.name,
        "coupon_type": row.coupon_type,
        "discount_rate": row.discount_rate,
        "cash_amount_fen": row.cash_amount_fen,
        "min_order_fen": row.min_order_fen,
        "max_claim_per_user": row.max_claim_per_user,
        "total_quantity": row.total_quantity,
        "claimed_count": row.claimed_count,
        "expiry_days": row.expiry_days,
        "start_date": row.start_date.isoformat() if row.start_date else None,
        "end_date": row.end_date.isoformat() if row.end_date else None,
    }


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------

@router.get("/available")
async def list_available_coupons(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """可领取优惠券列表：is_active=true，在有效期内，且库存未耗尽"""
    try:
        await _set_tenant(db, x_tenant_id)
        today = date.today()
        result = await db.execute(
            text("""
                SELECT id, name, coupon_type, discount_rate, cash_amount_fen,
                       min_order_fen, max_claim_per_user, total_quantity,
                       claimed_count, expiry_days, start_date, end_date
                FROM coupons
                WHERE tenant_id = :tid
                  AND is_active = true
                  AND is_deleted = false
                  AND start_date <= :today
                  AND end_date >= :today
                  AND (total_quantity IS NULL OR claimed_count < total_quantity)
                ORDER BY created_at DESC
            """),
            {"tid": uuid.UUID(x_tenant_id), "today": today},
        )
        rows = result.fetchall()
        items = [_row_to_coupon(r) for r in rows]
        return ok_response({"items": items, "total": len(items)})
    except SQLAlchemyError as exc:
        if _is_table_missing(exc):
            logger.warning("coupon.table_not_ready", error=str(exc))
            return ok_response({"items": [], "total": 0, "_note": "TABLE_NOT_READY"})
        logger.error("coupon.list_available_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "查询优惠券失败")


@router.post("/claim")
async def claim_coupon(
    req: ClaimCouponRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """领取优惠券（幂等）

    逻辑：
    1. 检查优惠券是否可领取（active、有效期、库存）
    2. 检查用户已领数量是否达上限
    3. 创建 customer_coupon 记录（status=unused）
    4. 原子递增 claimed_count
    """
    try:
        await _set_tenant(db, x_tenant_id)
        tid = uuid.UUID(x_tenant_id)
        coupon_id = uuid.UUID(req.coupon_id)
        customer_id = uuid.UUID(req.customer_id)
        today = date.today()

        # ① 幂等检查：是否已领取
        dup_result = await db.execute(
            text("""
                SELECT id FROM customer_coupons
                WHERE tenant_id = :tid
                  AND coupon_id = :cid
                  AND customer_id = :uid
                  AND is_deleted = false
                LIMIT 1
            """),
            {"tid": tid, "cid": coupon_id, "uid": customer_id},
        )
        if dup_result.fetchone():
            return {"ok": False, "error": {"code": "ALREADY_CLAIMED", "message": "该优惠券已领取"}}

        # ② 查询优惠券基础信息
        coupon_result = await db.execute(
            text("""
                SELECT id, name, coupon_type, discount_rate, cash_amount_fen,
                       min_order_fen, max_claim_per_user, total_quantity,
                       claimed_count, expiry_days, start_date, end_date, is_active
                FROM coupons
                WHERE id = :cid AND tenant_id = :tid AND is_deleted = false
                LIMIT 1
            """),
            {"cid": coupon_id, "tid": tid},
        )
        coupon = coupon_result.fetchone()
        if not coupon:
            return error_response("COUPON_NOT_FOUND", "优惠券不存在")

        if not coupon.is_active:
            return error_response("COUPON_INACTIVE", "优惠券已下架")

        if coupon.start_date and coupon.start_date > today:
            return error_response("COUPON_NOT_STARTED", "优惠券活动尚未开始")

        if coupon.end_date and coupon.end_date < today:
            return error_response("COUPON_EXPIRED", "优惠券已过期")

        # ③ 库存检查
        if coupon.total_quantity is not None and coupon.claimed_count >= coupon.total_quantity:
            return error_response("OUT_OF_STOCK", "优惠券已被领完")

        # ④ 单用户领取上限检查
        if coupon.max_claim_per_user:
            user_claim_result = await db.execute(
                text("""
                    SELECT COUNT(*) FROM customer_coupons
                    WHERE tenant_id = :tid AND coupon_id = :cid AND customer_id = :uid
                      AND is_deleted = false
                """),
                {"tid": tid, "cid": coupon_id, "uid": customer_id},
            )
            user_count = user_claim_result.scalar() or 0
            if user_count >= coupon.max_claim_per_user:
                return {"ok": False, "error": {"code": "ALREADY_CLAIMED", "message": "已达领取上限"}}

        # ⑤ 计算有效期
        now = datetime.now(timezone.utc)
        expire_at = None
        if coupon.expiry_days:
            from datetime import timedelta
            expire_at = now + timedelta(days=coupon.expiry_days)

        # ⑥ 创建 customer_coupon
        new_id = uuid.uuid4()
        await db.execute(
            text("""
                INSERT INTO customer_coupons
                    (id, tenant_id, coupon_id, customer_id, status,
                     claimed_at, expire_at, created_at, updated_at)
                VALUES
                    (:id, :tid, :cid, :uid, 'unused',
                     :now, :expire_at, :now, :now)
            """),
            {
                "id": new_id,
                "tid": tid,
                "cid": coupon_id,
                "uid": customer_id,
                "now": now,
                "expire_at": expire_at,
            },
        )

        # ⑦ 原子递增 claimed_count
        await db.execute(
            text("""
                UPDATE coupons
                SET claimed_count = claimed_count + 1, updated_at = NOW()
                WHERE id = :cid AND tenant_id = :tid
            """),
            {"cid": coupon_id, "tid": tid},
        )

        await db.commit()
        logger.info(
            "coupon.claimed",
            customer_coupon_id=str(new_id),
            coupon_id=str(coupon_id),
            customer_id=str(customer_id),
            tenant_id=x_tenant_id,
        )
        return ok_response({
            "customer_coupon_id": str(new_id),
            "coupon_id": str(coupon_id),
            "coupon_name": coupon.name,
            "status": "unused",
            "expire_at": expire_at.isoformat() if expire_at else None,
        })

    except ValueError as exc:
        logger.warning("coupon.claim_invalid_param", error=str(exc))
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        await db.rollback()
        if _is_table_missing(exc):
            logger.warning("coupon.table_not_ready", error=str(exc))
            return error_response("TABLE_NOT_READY", "优惠券功能尚未初始化，请联系管理员")
        logger.error("coupon.claim_db_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "领取失败，请稍后重试")


@router.post("/verify")
async def verify_coupon(
    req: VerifyCouponRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """核销优惠券

    逻辑：
    1. 查找 customer_coupon 记录（status=unused）
    2. 校验归属与有效期
    3. 将 status 更新为 used，记录核销时间
    """
    try:
        await _set_tenant(db, x_tenant_id)
        tid = uuid.UUID(x_tenant_id)
        cc_id = uuid.UUID(req.customer_coupon_id)
        customer_id = uuid.UUID(req.customer_id)
        now = datetime.now(timezone.utc)

        # ① 查找持有券记录
        result = await db.execute(
            text("""
                SELECT cc.id, cc.coupon_id, cc.customer_id, cc.status, cc.expire_at,
                       c.name AS coupon_name, c.cash_amount_fen, c.discount_rate, c.coupon_type
                FROM customer_coupons cc
                JOIN coupons c ON c.id = cc.coupon_id AND c.tenant_id = cc.tenant_id
                WHERE cc.id = :cc_id
                  AND cc.tenant_id = :tid
                  AND cc.is_deleted = false
                LIMIT 1
            """),
            {"cc_id": cc_id, "tid": tid},
        )
        row = result.fetchone()
        if not row:
            return error_response("COUPON_NOT_FOUND", "优惠券记录不存在")

        # ② 归属校验
        if row.customer_id != customer_id:
            return error_response("NOT_OWNER", "该券不属于当前用户")

        # ③ 状态校验
        if row.status == "used":
            return error_response("ALREADY_USED", "该券已被使用")
        if row.status != "unused":
            return error_response("INVALID_STATUS", f"券状态异常: {row.status}")

        # ④ 有效期校验
        if row.expire_at and row.expire_at < now:
            return error_response("COUPON_EXPIRED", "该券已过期")

        # ⑤ 更新状态为 used
        await db.execute(
            text("""
                UPDATE customer_coupons
                SET status = 'used', used_at = :now, updated_at = :now
                WHERE id = :cc_id AND tenant_id = :tid
            """),
            {"cc_id": cc_id, "tid": tid, "now": now},
        )

        await db.commit()
        logger.info(
            "coupon.verified",
            customer_coupon_id=str(cc_id),
            coupon_id=str(row.coupon_id),
            customer_id=str(customer_id),
            tenant_id=x_tenant_id,
        )
        return ok_response({
            "customer_coupon_id": str(cc_id),
            "coupon_name": row.coupon_name,
            "status": "used",
            "used_at": now.isoformat(),
        })

    except ValueError as exc:
        logger.warning("coupon.verify_invalid_param", error=str(exc))
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        await db.rollback()
        if _is_table_missing(exc):
            logger.warning("coupon.table_not_ready", error=str(exc))
            return error_response("TABLE_NOT_READY", "优惠券功能尚未初始化，请联系管理员")
        logger.error("coupon.verify_db_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "核销失败，请稍后重试")


@router.get("/my")
async def my_coupons(
    customer_id: Optional[str] = None,
    status: Optional[str] = None,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """我的优惠券 — 重定向提示前端到 tx-member

    tx-member 已实现 GET /api/v1/member/coupons/stats 及核销逻辑。
    消费者券包管理（已领/已用/已过期列表）统一由 tx-member 维护，
    此处返回重定向提示，前端应调用 /api/v1/member/coupons。
    """
    return ok_response({
        "redirect": "/api/v1/member/coupons",
        "_note": (
            "客户优惠券列表由 tx-member 统一管理。"
            "请携带相同 X-Tenant-ID 和 customer_id 调用 /api/v1/member/coupons"
        ),
    })


@router.post("/{coupon_id}/apply")
async def apply_coupon(
    coupon_id: str,
    req: ApplyCouponRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """核销优惠券（收银员确认后调用）

    逻辑：
    1. 查询 customer_coupons 中该券（status=unused，即已领取未使用）
    2. 校验有效期
    3. 校验订单金额是否达到使用门槛
    4. 更新状态为 used，记录 order_id / used_at / store_id
    5. 旁路发射 campaign.coupon_applied 事件
    """
    try:
        await _set_tenant(db, x_tenant_id)
        tid = uuid.UUID(x_tenant_id)
        cid = uuid.UUID(coupon_id)
        now = datetime.now(timezone.utc)

        # ① 查询该优惠券（联表取折扣金额与门槛）
        result = await db.execute(
            text("""
                SELECT cc.id AS cc_id,
                       cc.customer_id,
                       cc.status,
                       cc.expire_at,
                       c.name AS coupon_name,
                       c.cash_amount_fen,
                       c.discount_rate,
                       c.coupon_type,
                       c.min_order_fen AS minimum_amount_fen
                FROM customer_coupons cc
                JOIN coupons c ON c.id = cc.coupon_id AND c.tenant_id = cc.tenant_id
                WHERE cc.coupon_id = :cid
                  AND cc.tenant_id = :tid
                  AND cc.is_deleted = false
                ORDER BY cc.created_at DESC
                LIMIT 1
            """),
            {"cid": cid, "tid": tid},
        )
        row = result.fetchone()
        if not row:
            return error_response("COUPON_NOT_FOUND", "优惠券不存在或未被领取")

        # ② 状态校验：必须是 unused（已领取未使用）
        if row.status == "used":
            return {"ok": False, "error": {"code": "COUPON_ALREADY_USED", "message": "该券已使用，不可重复核销"}}, 409
        if row.status != "unused":
            return {"ok": False, "error": {"code": "INVALID_COUPON_STATUS", "message": f"券状态不可核销: {row.status}"}}, 409

        # ③ 有效期校验
        if row.expire_at and row.expire_at < now:
            return error_response("COUPON_EXPIRED", "该券已过期，无法核销")

        # ④ 订单金额门槛校验
        minimum_amount_fen: int = row.minimum_amount_fen or 0
        if minimum_amount_fen > 0 and req.order_amount_fen < minimum_amount_fen:
            return error_response(
                "ORDER_AMOUNT_TOO_LOW",
                f"订单金额不足，需满 {minimum_amount_fen} 分才可使用此券",
            )

        # ⑤ 计算折扣金额（分）
        if row.coupon_type == "cash" and row.cash_amount_fen:
            discount_amount_fen = min(row.cash_amount_fen, req.order_amount_fen)
        elif row.coupon_type == "discount" and row.discount_rate:
            # discount_rate 存储为折扣比例（如 0.88 表示 88 折）
            discount_amount_fen = int(req.order_amount_fen * (1 - row.discount_rate))
        else:
            discount_amount_fen = row.cash_amount_fen or 0

        # ⑥ 更新 customer_coupon 状态为 used
        try:
            store_id = uuid.UUID(req.store_id)
        except ValueError:
            store_id = None

        await db.execute(
            text("""
                UPDATE customer_coupons
                SET status = 'used',
                    used_at = :now,
                    updated_at = :now,
                    order_id = :order_id,
                    store_id = :store_id
                WHERE id = :cc_id AND tenant_id = :tid
            """),
            {
                "cc_id": row.cc_id,
                "tid": tid,
                "now": now,
                "order_id": req.order_id,
                "store_id": store_id,
            },
        )

        await db.commit()

        logger.info(
            "coupon.applied",
            customer_coupon_id=str(row.cc_id),
            coupon_id=coupon_id,
            order_id=req.order_id,
            store_id=req.store_id,
            discount_amount_fen=discount_amount_fen,
            tenant_id=x_tenant_id,
        )

        # ⑦ 旁路发射事件（失败不影响主流程）
        asyncio.create_task(emit_event(
            event_type=CampaignEventType.COUPON_APPLIED,
            tenant_id=x_tenant_id,
            stream_id=coupon_id,
            payload={
                "customer_coupon_id": str(row.cc_id),
                "coupon_id": coupon_id,
                "order_id": req.order_id,
                "store_id": req.store_id,
                "operator_id": req.operator_id,
                "discount_amount_fen": discount_amount_fen,
                "order_amount_fen": req.order_amount_fen,
                "used_at": now.isoformat(),
            },
            store_id=req.store_id,
            source_service="tx-growth",
            metadata={"operator_id": req.operator_id},
        ))

        return ok_response({
            "customer_coupon_id": str(row.cc_id),
            "coupon_id": coupon_id,
            "coupon_name": row.coupon_name,
            "order_id": req.order_id,
            "store_id": req.store_id,
            "status": "used",
            "used_at": now.isoformat(),
            "discount_amount_fen": discount_amount_fen,
        })

    except ValueError as exc:
        logger.warning("coupon.apply_invalid_param", error=str(exc))
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        await db.rollback()
        if _is_table_missing(exc):
            logger.warning("coupon.table_not_ready", error=str(exc))
            return error_response("TABLE_NOT_READY", "优惠券功能尚未初始化，请联系管理员"), 503
        logger.error("coupon.apply_db_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "核销失败，请稍后重试")
