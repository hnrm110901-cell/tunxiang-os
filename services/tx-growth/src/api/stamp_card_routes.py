"""集章卡活动 API 路由 — 真实 DB 版
────────────────────────
GET  /api/v1/growth/stamp-card/my       — 我的集章卡状态
POST /api/v1/growth/stamp-card/stamp    — 盖章（消费后调用）
GET  /api/v1/growth/stamp-card/prizes   — 奖品列表（模板的奖励配置）
POST /api/v1/growth/stamp-card/exchange — 兑换奖品

v102 表：stamp_card_templates / stamp_card_instances / stamp_card_stamps
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/growth/stamp-card", tags=["stamp-card"])


# ---------------------------------------------------------------------------
# 统一响应
# ---------------------------------------------------------------------------


def ok_response(data: Any) -> dict:
    return {"ok": True, "data": data}


def error_response(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _is_table_missing(exc: SQLAlchemyError) -> bool:
    msg = str(exc).lower()
    return "does not exist" in msg or ("relation" in msg and "exist" in msg)


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class StampRequest(BaseModel):
    order_id: str
    customer_id: str
    amount_fen: int = 0
    store_id: Optional[str] = None


class ExchangeRequest(BaseModel):
    card_id: str  # stamp_card_instances.id
    customer_id: str


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


@router.get("/my")
async def get_my_stamp_card(
    customer_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """我的集章卡状态

    查询 stamp_card_instances（status=active）+ 关联模板信息。
    """
    try:
        await _set_tenant(db, x_tenant_id)
        tid = uuid.UUID(x_tenant_id)
        cid = uuid.UUID(customer_id)

        result = await db.execute(
            text("""
                SELECT i.id, i.template_id, i.stamp_count, i.target_stamps,
                       i.status, i.expired_at, i.completed_at, i.reward_issued,
                       t.name, t.description, t.reward_type, t.reward_config,
                       t.min_order_fen
                FROM stamp_card_instances i
                JOIN stamp_card_templates t ON t.id = i.template_id AND t.tenant_id = i.tenant_id
                WHERE i.tenant_id = :tid
                  AND i.customer_id = :cid
                  AND i.is_deleted = false
                ORDER BY
                    CASE WHEN i.status = 'active' THEN 0
                         WHEN i.status = 'completed' THEN 1
                         ELSE 2 END,
                    i.created_at DESC
                LIMIT 1
            """),
            {"tid": tid, "cid": cid},
        )
        row = result.fetchone()
        if not row:
            return ok_response({"card": None, "_note": "该客户暂无集章卡"})

        # 获取盖章记录
        stamps_result = await db.execute(
            text("""
                SELECT stamp_no, order_id, store_id, stamped_at
                FROM stamp_card_stamps
                WHERE tenant_id = :tid AND instance_id = :iid AND is_deleted = false
                ORDER BY stamp_no ASC
            """),
            {"tid": tid, "iid": row.id},
        )
        stamps = [
            {
                "stamp_no": s.stamp_no,
                "order_id": str(s.order_id) if s.order_id else None,
                "store_id": str(s.store_id) if s.store_id else None,
                "stamped_at": s.stamped_at.isoformat() if s.stamped_at else None,
            }
            for s in stamps_result.fetchall()
        ]

        card = {
            "id": str(row.id),
            "template_id": str(row.template_id),
            "activity_name": row.name,
            "description": row.description,
            "total_slots": row.target_stamps,
            "current_stamps": row.stamp_count,
            "status": row.status,
            "expired_at": row.expired_at.isoformat() if row.expired_at else None,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            "reward_issued": row.reward_issued,
            "reward_type": row.reward_type,
            "reward_config": row.reward_config or {},
            "stamp_condition": f"单笔消费满{row.min_order_fen // 100}元自动盖章" if row.min_order_fen else "消费即盖章",
            "stamps": stamps,
        }
        return ok_response(card)

    except ValueError as exc:
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        if _is_table_missing(exc):
            logger.warning("stamp_card.table_not_ready", error=str(exc))
            return ok_response({"card": None, "_note": "TABLE_NOT_READY"})
        logger.error("stamp_card.my_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "查询集章卡失败")


@router.post("/stamp")
async def stamp(
    req: StampRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """盖章（消费后调用）

    逻辑：
    1. 找到该客户 active 的集章卡实例
    2. 检查最低消费门槛
    3. 原子递增 stamp_count + 写入盖章记录
    4. 若达到目标章数，自动更新 status=completed
    """
    try:
        await _set_tenant(db, x_tenant_id)
        tid = uuid.UUID(x_tenant_id)
        cid = uuid.UUID(req.customer_id)
        order_id = uuid.UUID(req.order_id)
        store_id = uuid.UUID(req.store_id) if req.store_id else None

        # ① 找到 active 的实例（未过期）
        now = datetime.now(timezone.utc)
        instance_result = await db.execute(
            text("""
                SELECT i.id, i.stamp_count, i.target_stamps, t.min_order_fen, t.name
                FROM stamp_card_instances i
                JOIN stamp_card_templates t ON t.id = i.template_id AND t.tenant_id = i.tenant_id
                WHERE i.tenant_id = :tid
                  AND i.customer_id = :cid
                  AND i.status = 'active'
                  AND i.expired_at > :now
                  AND i.is_deleted = false
                ORDER BY i.created_at ASC
                LIMIT 1
                FOR UPDATE
            """),
            {"tid": tid, "cid": cid, "now": now},
        )
        instance = instance_result.fetchone()
        if not instance:
            return error_response("NO_ACTIVE_CARD", "该客户没有进行中的集章卡")

        # ② 最低消费检查
        if instance.min_order_fen and req.amount_fen < instance.min_order_fen:
            return error_response(
                "BELOW_MINIMUM",
                f"消费金额不足，需满{instance.min_order_fen // 100}元",
            )

        # ③ 已满章检查
        if instance.stamp_count >= instance.target_stamps:
            return error_response("CARD_FULL", "集章卡已集满")

        new_stamp_no = instance.stamp_count + 1

        # ④ 写入盖章记录
        await db.execute(
            text("""
                INSERT INTO stamp_card_stamps
                    (id, tenant_id, instance_id, order_id, store_id, stamp_no, stamped_at)
                VALUES
                    (:id, :tid, :iid, :oid, :sid, :stamp_no, :now)
            """),
            {
                "id": uuid.uuid4(),
                "tid": tid,
                "iid": instance.id,
                "oid": order_id,
                "sid": store_id,
                "stamp_no": new_stamp_no,
                "now": now,
            },
        )

        # ⑤ 原子递增 stamp_count
        new_status = "active"
        completed_at_val = None
        if new_stamp_no >= instance.target_stamps:
            new_status = "completed"
            completed_at_val = now

        await db.execute(
            text("""
                UPDATE stamp_card_instances
                SET stamp_count = stamp_count + 1,
                    status = :status,
                    completed_at = COALESCE(:completed_at, completed_at),
                    updated_at = NOW()
                WHERE id = :iid AND tenant_id = :tid
            """),
            {
                "iid": instance.id,
                "tid": tid,
                "status": new_status,
                "completed_at": completed_at_val,
            },
        )

        await db.commit()

        logger.info(
            "stamp_card.stamped",
            instance_id=str(instance.id),
            stamp_no=new_stamp_no,
            customer_id=str(cid),
            tenant_id=x_tenant_id,
        )
        return ok_response(
            {
                "stamp_count": 1,
                "current_stamps": new_stamp_no,
                "total_slots": instance.target_stamps,
                "status": new_status,
                "card_name": instance.name,
            }
        )

    except ValueError as exc:
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        await db.rollback()
        if _is_table_missing(exc):
            logger.warning("stamp_card.table_not_ready", error=str(exc))
            return error_response("TABLE_NOT_READY", "集章卡功能尚未初始化")
        logger.error("stamp_card.stamp_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "盖章失败，请稍后重试")


@router.get("/prizes")
async def get_prizes(
    template_id: Optional[str] = None,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """奖品列表（读取 stamp_card_templates 的奖励配置）"""
    try:
        await _set_tenant(db, x_tenant_id)
        tid = uuid.UUID(x_tenant_id)

        where = "tenant_id = :tid AND is_deleted = false AND status = 'active'"
        params: dict = {"tid": tid}
        if template_id:
            where += " AND id = :tmpl_id"
            params["tmpl_id"] = uuid.UUID(template_id)

        result = await db.execute(
            text(f"""
                SELECT id, name, description, target_stamps, reward_type,
                       reward_config, min_order_fen
                FROM stamp_card_templates
                WHERE {where}
                ORDER BY created_at DESC
            """),
            params,
        )
        rows = result.fetchall()
        items = [
            {
                "template_id": str(r.id),
                "name": r.name,
                "description": r.description,
                "stamps_required": r.target_stamps,
                "reward_type": r.reward_type,
                "reward_config": r.reward_config or {},
                "min_order_fen": r.min_order_fen,
            }
            for r in rows
        ]
        return ok_response({"items": items, "total": len(items)})

    except ValueError as exc:
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        if _is_table_missing(exc):
            logger.warning("stamp_card.table_not_ready", error=str(exc))
            return ok_response({"items": [], "total": 0, "_note": "TABLE_NOT_READY"})
        logger.error("stamp_card.prizes_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "查询奖品失败")


@router.post("/exchange")
async def exchange_prize(
    req: ExchangeRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """兑换奖品

    逻辑：
    1. 查找 completed 且 reward_issued=false 的实例
    2. 标记 reward_issued=true
    3. 返回兑换凭证（redeem_code）
    """
    try:
        await _set_tenant(db, x_tenant_id)
        tid = uuid.UUID(x_tenant_id)
        card_id = uuid.UUID(req.card_id)
        cid = uuid.UUID(req.customer_id)

        # ① 查找实例
        result = await db.execute(
            text("""
                SELECT i.id, i.status, i.reward_issued, i.customer_id,
                       t.name, t.reward_type, t.reward_config
                FROM stamp_card_instances i
                JOIN stamp_card_templates t ON t.id = i.template_id AND t.tenant_id = i.tenant_id
                WHERE i.id = :iid AND i.tenant_id = :tid AND i.is_deleted = false
                FOR UPDATE
            """),
            {"iid": card_id, "tid": tid},
        )
        row = result.fetchone()
        if not row:
            return error_response("CARD_NOT_FOUND", "集章卡不存在")

        if row.customer_id != cid:
            return error_response("NOT_OWNER", "该卡不属于当前客户")

        if row.status != "completed":
            return error_response("NOT_COMPLETED", "集章卡尚未集满，无法兑换")

        if row.reward_issued:
            return error_response("ALREADY_EXCHANGED", "奖品已兑换")

        # ② 标记已兑换
        now = datetime.now(timezone.utc)
        await db.execute(
            text("""
                UPDATE stamp_card_instances
                SET reward_issued = true, updated_at = :now
                WHERE id = :iid AND tenant_id = :tid
            """),
            {"iid": card_id, "tid": tid, "now": now},
        )

        # ③ 递增模板 completed_count
        await db.execute(
            text("""
                UPDATE stamp_card_templates
                SET completed_count = completed_count + 1, updated_at = NOW()
                WHERE id = (
                    SELECT template_id FROM stamp_card_instances WHERE id = :iid
                ) AND tenant_id = :tid
            """),
            {"iid": card_id, "tid": tid},
        )

        await db.commit()

        code = uuid.uuid4().hex[:8].upper()
        redeem_code = code[:4] + "-" + code[4:]
        expire_time = (now + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M")

        logger.info(
            "stamp_card.exchanged",
            card_id=str(card_id),
            customer_id=str(cid),
            reward_type=row.reward_type,
            tenant_id=x_tenant_id,
        )
        return ok_response(
            {
                "redeem_code": redeem_code,
                "expire_time": expire_time,
                "card_id": str(card_id),
                "card_name": row.name,
                "reward_type": row.reward_type,
                "reward_config": row.reward_config or {},
            }
        )

    except ValueError as exc:
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        await db.rollback()
        if _is_table_missing(exc):
            logger.warning("stamp_card.table_not_ready", error=str(exc))
            return error_response("TABLE_NOT_READY", "集章卡功能尚未初始化")
        logger.error("stamp_card.exchange_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "兑换失败，请稍后重试")
