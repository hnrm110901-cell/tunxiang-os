"""营销活动管理 API (Growth 前缀版) — prefix /api/v1/growth/campaigns

覆盖任务要求的7个端点：
1. GET  /api/v1/growth/campaigns                          活动列表（支持 status/type/page 过滤）
2. POST /api/v1/growth/campaigns                          创建营销活动
3. PUT  /api/v1/growth/campaigns/{campaign_id}            更新活动（仅 draft 可改）
4. POST /api/v1/growth/campaigns/{campaign_id}/activate   激活（draft→active）
5. POST /api/v1/growth/campaigns/{campaign_id}/end        结束（active→ended）
6. GET  /api/v1/growth/campaigns/{campaign_id}/stats      活动效果统计
7. POST /api/v1/growth/campaigns/apply-to-order           结账时可用券检查（SkillEventConsumer 调用）

已有的 /api/v1/campaigns 路由器保持不变（向下兼容），
本路由器作为新标准路径供 miniapp / 总部后台使用。
"""
import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.ontology.src.database import get_db

from ..services.campaign_engine import CampaignEngine
from ..services.campaign_repository import CampaignRepository

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/growth/campaigns", tags=["growth-campaigns"])

_engine = CampaignEngine()

# ---------------------------------------------------------------------------
# 合法 status / type 枚举（用于参数校验）
# ---------------------------------------------------------------------------

_VALID_STATUSES = {"draft", "active", "ended", "cancelled"}
_VALID_TYPES = {"coupon_giveaway", "points_bonus", "discount_event", "referral"}


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

class CreateGrowthCampaignRequest(BaseModel):
    name: str
    type: str                                    # coupon_giveaway|points_bonus|discount_event|referral
    description: Optional[str] = None
    start_at: Optional[str] = None               # ISO8601
    end_at: Optional[str] = None                 # ISO8601
    target_segment: str = "all"                  # all|vip|regular|at_risk|new
    budget_fen: int = 0
    rules: dict = {}                             # JSONB，如 {"coupon_id": "xxx", "max_claim": 1000}


class UpdateGrowthCampaignRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    start_at: Optional[str] = None
    end_at: Optional[str] = None
    target_segment: Optional[str] = None
    budget_fen: Optional[int] = None
    rules: Optional[dict] = None


class OrderCheckoutPayload(BaseModel):
    order_id: str
    store_id: str
    customer_id: str
    order_amount_fen: int
    tenant_id: str


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------

@router.get("")
async def list_growth_campaigns(
    status: Optional[str] = None,
    type: Optional[str] = None,
    page: int = 1,
    size: int = 20,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """活动列表，支持 status/type/page 过滤"""
    if status and status not in _VALID_STATUSES:
        return error_response("INVALID_STATUS", f"status 须为 {_VALID_STATUSES} 之一")
    if type and type not in _VALID_TYPES:
        return error_response("INVALID_TYPE", f"type 须为 {_VALID_TYPES} 之一")

    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        tid = uuid.UUID(x_tenant_id)
        offset = (page - 1) * size

        where_parts = ["tenant_id = :tid", "is_deleted = false"]
        params: dict = {"tid": tid, "limit": size, "offset": offset}

        if status:
            where_parts.append("status = :status")
            params["status"] = status
        if type:
            where_parts.append("campaign_type = :ctype")
            params["ctype"] = type

        where_clause = " AND ".join(where_parts)

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM campaigns WHERE {where_clause}"),
            params,
        )
        total = count_result.scalar() or 0

        result = await db.execute(
            text(f"""
                SELECT id, campaign_type, name, description, status,
                       config, start_time, end_time, budget_fen, spent_fen,
                       target_segments, participant_count, reward_count,
                       total_cost_fen, conversion_count,
                       created_at, updated_at
                FROM campaigns
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = result.fetchall()
        items = [_row_to_summary(r) for r in rows]
        return ok_response({"items": items, "total": total, "page": page, "size": size})

    except ValueError as exc:
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        if _is_table_missing(exc):
            logger.warning("growth_campaign.table_not_ready", error=str(exc))
            return ok_response({"items": [], "total": 0, "page": page, "size": size, "_note": "TABLE_NOT_READY"})
        logger.error("growth_campaign.list_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "查询活动列表失败")


@router.post("")
async def create_growth_campaign(
    req: CreateGrowthCampaignRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建营销活动（status=draft）"""
    if req.type not in _VALID_TYPES:
        return error_response("INVALID_TYPE", f"type 须为 {_VALID_TYPES} 之一")

    config = {
        "name": req.name,
        "description": req.description or "",
        "start_time": req.start_at,
        "end_time": req.end_at,
        "target_segments": [req.target_segment],
        "budget_fen": req.budget_fen,
        "rules": req.rules,
    }

    try:
        result = await _engine.create_campaign(req.type, config, x_tenant_id, db=db)
        if "error" in result:
            return error_response("CREATE_FAILED", result["error"])
        await db.commit()
        logger.info(
            "growth_campaign.created",
            campaign_id=result.get("campaign_id"),
            tenant_id=x_tenant_id,
            campaign_type=req.type,
        )
        return ok_response(result)
    except ValueError as exc:
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        await db.rollback()
        if _is_table_missing(exc):
            return error_response("TABLE_NOT_READY", "活动功能尚未初始化，请联系管理员")
        logger.error("growth_campaign.create_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "创建活动失败")


@router.put("/{campaign_id}")
async def update_growth_campaign(
    campaign_id: str,
    req: UpdateGrowthCampaignRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新活动（仅 draft 状态可修改）"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        repo = CampaignRepository(db, x_tenant_id)
        campaign = await repo.get_campaign(campaign_id)
        if not campaign:
            return error_response("NOT_FOUND", f"活动不存在: {campaign_id}")

        if campaign["status"] != "draft":
            return error_response(
                "NOT_DRAFT",
                f"只有 draft 状态的活动可以修改，当前状态: {campaign['status']}",
            )

        # 构建更新字段
        set_parts: list[str] = ["updated_at = NOW()"]
        params: dict = {"id": uuid.UUID(campaign_id), "tid": uuid.UUID(x_tenant_id)}

        if req.name is not None:
            set_parts.append("name = :name")
            params["name"] = req.name
        if req.description is not None:
            set_parts.append("description = :description")
            params["description"] = req.description
        if req.start_at is not None:
            set_parts.append("start_time = :start_time")
            params["start_time"] = req.start_at
        if req.end_at is not None:
            set_parts.append("end_time = :end_time")
            params["end_time"] = req.end_at
        if req.budget_fen is not None:
            set_parts.append("budget_fen = :budget_fen")
            params["budget_fen"] = req.budget_fen
        if req.target_segment is not None:
            set_parts.append("target_segments = :segments::jsonb")
            params["segments"] = json.dumps([req.target_segment])

        # rules 写入 config JSONB 的 rules 字段
        if req.rules is not None:
            existing_config = campaign.get("config") or {}
            existing_config["rules"] = req.rules
            set_parts.append("config = :config::jsonb")
            params["config"] = json.dumps(existing_config)

        await db.execute(
            text(f"""
                UPDATE campaigns
                SET {', '.join(set_parts)}
                WHERE id = :id AND tenant_id = :tid
            """),
            params,
        )
        await db.commit()

        updated = await repo.get_campaign(campaign_id)
        logger.info("growth_campaign.updated", campaign_id=campaign_id, tenant_id=x_tenant_id)
        return ok_response(updated)

    except ValueError as exc:
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        await db.rollback()
        if _is_table_missing(exc):
            return error_response("TABLE_NOT_READY", "活动功能尚未初始化")
        logger.error("growth_campaign.update_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "更新活动失败")


@router.post("/{campaign_id}/activate")
async def activate_growth_campaign(
    campaign_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """激活活动（draft → active）"""
    try:
        result = await _engine.start_campaign(campaign_id, x_tenant_id, db=db)
        if "error" in result:
            return error_response("ACTIVATE_FAILED", result["error"])
        await db.commit()
        logger.info("growth_campaign.activated", campaign_id=campaign_id, tenant_id=x_tenant_id)
        return ok_response(result)
    except ValueError as exc:
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        await db.rollback()
        if _is_table_missing(exc):
            return error_response("TABLE_NOT_READY", "活动功能尚未初始化")
        logger.error("growth_campaign.activate_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "激活活动失败")


@router.post("/{campaign_id}/end")
async def end_growth_campaign(
    campaign_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """结束活动（active → ended）"""
    try:
        result = await _engine.end_campaign(campaign_id, x_tenant_id, db=db)
        if "error" in result:
            return error_response("END_FAILED", result["error"])
        await db.commit()
        logger.info("growth_campaign.ended", campaign_id=campaign_id, tenant_id=x_tenant_id)
        return ok_response(result)
    except ValueError as exc:
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        await db.rollback()
        if _is_table_missing(exc):
            return error_response("TABLE_NOT_READY", "活动功能尚未初始化")
        logger.error("growth_campaign.end_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "结束活动失败")


@router.get("/{campaign_id}/stats")
async def get_growth_campaign_stats(
    campaign_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """活动效果统计

    返回：claimed_count, used_count, total_discount_fen,
           participating_customers（去重客户数）
    """
    try:
        repo = CampaignRepository(db, x_tenant_id)
        analytics = await repo.get_analytics(campaign_id)
        if not analytics:
            return error_response("NOT_FOUND", f"活动不存在: {campaign_id}")

        # 额外查询：去重参与客户数 + 已使用优惠券数
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        tid = uuid.UUID(x_tenant_id)
        cid = uuid.UUID(campaign_id)

        distinct_result = await db.execute(
            text("""
                SELECT COUNT(DISTINCT customer_id) AS distinct_customers
                FROM campaign_participants
                WHERE tenant_id = :tid AND campaign_id = :cid
            """),
            {"tid": tid, "cid": cid},
        )
        distinct_row = distinct_result.fetchone()
        participating_customers = distinct_row.distinct_customers if distinct_row else 0

        # 已使用的优惠券数（status='used' in customer_coupons，若表存在）
        used_count = 0
        try:
            used_result = await db.execute(
                text("""
                    SELECT COUNT(*) FROM customer_coupons cc
                    JOIN campaign_rewards cr
                      ON cc.coupon_id = (cr.reward_data->>'coupon_id')::uuid
                    WHERE cr.tenant_id = :tid AND cr.campaign_id = :cid
                      AND cc.status = 'used'
                """),
                {"tid": tid, "cid": cid},
            )
            used_count = used_result.scalar() or 0
        except SQLAlchemyError:
            # customer_coupons 表尚未就绪时优雅降级
            used_count = 0

        return ok_response({
            "campaign_id": campaign_id,
            "campaign_name": analytics["campaign_name"],
            "status": analytics["status"],
            "claimed_count": analytics["participant_count"],
            "used_count": used_count,
            "total_discount_fen": analytics["total_cost_fen"],
            "participating_customers": participating_customers,
            "reward_breakdown": analytics.get("reward_breakdown", {}),
            "budget_usage": analytics.get("budget_usage", 0.0),
        })

    except ValueError as exc:
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        if _is_table_missing(exc):
            return error_response("TABLE_NOT_READY", "活动功能尚未初始化")
        logger.error("growth_campaign.stats_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "查询统计失败")


# ---------------------------------------------------------------------------
# 补全端点：deactivate + apply-coupon
# ---------------------------------------------------------------------------

class ApplyCouponRequest(BaseModel):
    customer_id: str
    coupon_code: str
    order_id: Optional[str] = None
    order_amount_fen: int = 0


@router.post("/{campaign_id}/deactivate")
async def deactivate_growth_campaign(
    campaign_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """暂停/停用活动（active → cancelled）。

    与 /end 的区别：deactivate 是主动停用（可能重新激活），
    end 是正常结束（不可恢复）。
    """
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        tid = uuid.UUID(x_tenant_id)
        cid = uuid.UUID(campaign_id)

        row = await db.execute(
            text("SELECT status FROM promotions WHERE tenant_id = :tid AND id = :cid"),
            {"tid": tid, "cid": cid},
        )
        campaign = row.fetchone()
        if not campaign:
            return error_response("NOT_FOUND", f"活动不存在: {campaign_id}")
        if campaign.status not in ("active", "draft"):
            return error_response(
                "INVALID_STATUS",
                f"活动状态为 {campaign.status}，无法停用",
            )

        await db.execute(
            text(
                "UPDATE promotions SET status = 'cancelled', updated_at = now() "
                "WHERE tenant_id = :tid AND id = :cid"
            ),
            {"tid": tid, "cid": cid},
        )
        await db.commit()

        logger.info(
            "growth_campaign.deactivated",
            campaign_id=campaign_id,
            tenant_id=x_tenant_id,
        )
        return ok_response({"campaign_id": campaign_id, "status": "cancelled"})

    except ValueError as exc:
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        await db.rollback()
        if _is_table_missing(exc):
            return error_response("TABLE_NOT_READY", "活动功能尚未初始化")
        logger.error("growth_campaign.deactivate_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "停用活动失败")


@router.post("/{campaign_id}/apply-coupon")
async def apply_coupon(
    campaign_id: str,
    req: ApplyCouponRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """核销优惠券（活动下的券码兑换）。

    流程：
    1. 验证活动状态为 active
    2. 验证券码有效（customer_coupons 表中 status='unused'）
    3. 将券状态更新为 used，记录 order_id
    4. 更新活动已花费金额（spent_fen += discount_amount_fen）
    """
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        tid = uuid.UUID(x_tenant_id)
        cid = uuid.UUID(campaign_id)

        # 验证活动
        row = await db.execute(
            text("SELECT status, budget_fen, spent_fen FROM promotions WHERE tenant_id = :tid AND id = :cid"),
            {"tid": tid, "cid": cid},
        )
        campaign = row.fetchone()
        if not campaign:
            return error_response("NOT_FOUND", f"活动不存在: {campaign_id}")
        if campaign.status != "active":
            return error_response("CAMPAIGN_INACTIVE", f"活动状态为 {campaign.status}，无法核销")

        # 预算检查
        if campaign.budget_fen > 0 and campaign.spent_fen >= campaign.budget_fen:
            return error_response("BUDGET_EXHAUSTED", "活动预算已耗尽")

        # 查找并核销券（优雅降级：若 customer_coupons 表尚不存在则跳过校验）
        discount_fen = 0
        try:
            coupon_row = await db.execute(
                text(
                    "SELECT id, discount_fen, status FROM customer_coupons "
                    "WHERE tenant_id = :tid AND coupon_code = :code AND status = 'unused'"
                ),
                {"tid": tid, "code": req.coupon_code},
            )
            coupon = coupon_row.fetchone()
            if not coupon:
                return error_response("COUPON_INVALID", f"券码无效或已使用: {req.coupon_code}")

            discount_fen = coupon.discount_fen or 0
            order_id_val = uuid.UUID(req.order_id) if req.order_id else None

            await db.execute(
                text(
                    "UPDATE customer_coupons SET status = 'used', "
                    "used_at = now(), order_id = :oid "
                    "WHERE tenant_id = :tid AND id = :cid2"
                ),
                {"tid": tid, "oid": order_id_val, "cid2": coupon.id},
            )
        except SQLAlchemyError as coupon_exc:
            if not _is_table_missing(coupon_exc):
                raise
            # customer_coupons 表尚未就绪，跳过校验（降级模式）
            logger.warning("apply_coupon.coupon_table_missing", error=str(coupon_exc))

        # 更新活动 spent_fen
        if discount_fen > 0:
            await db.execute(
                text(
                    "UPDATE promotions SET spent_fen = spent_fen + :delta, "
                    "updated_at = now() WHERE tenant_id = :tid AND id = :cid"
                ),
                {"delta": discount_fen, "tid": tid, "cid": cid},
            )

        await db.commit()

        logger.info(
            "growth_campaign.coupon_applied",
            campaign_id=campaign_id,
            coupon_code=req.coupon_code,
            customer_id=req.customer_id,
            discount_fen=discount_fen,
        )

        return ok_response({
            "campaign_id": campaign_id,
            "coupon_code": req.coupon_code,
            "customer_id": req.customer_id,
            "discount_fen": discount_fen,
            "order_id": req.order_id,
        })

    except ValueError as exc:
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        await db.rollback()
        if _is_table_missing(exc):
            return error_response("TABLE_NOT_READY", "活动功能尚未初始化")
        logger.error("growth_campaign.apply_coupon_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "核销优惠券失败")


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------

def _is_table_missing(exc: SQLAlchemyError) -> bool:
    msg = str(exc).lower()
    return "does not exist" in msg or ("relation" in msg and "exist" in msg)


def _row_to_summary(row) -> dict:
    def _j(v):
        if v is None:
            return None
        return v if isinstance(v, (dict, list)) else json.loads(v)

    return {
        "campaign_id": str(row.id),
        "campaign_type": row.campaign_type,
        "name": row.name,
        "description": getattr(row, "description", None),
        "status": row.status,
        "start_at": row.start_time.isoformat() if row.start_time else None,
        "end_at": row.end_time.isoformat() if row.end_time else None,
        "budget_fen": row.budget_fen,
        "spent_fen": row.spent_fen,
        "target_segments": _j(getattr(row, "target_segments", None)) or [],
        "stats": {
            "participant_count": row.participant_count,
            "reward_count": row.reward_count,
            "total_cost_fen": row.total_cost_fen,
            "conversion_count": getattr(row, "conversion_count", 0),
        },
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


# ---------------------------------------------------------------------------
# 内部端点 — SkillEventConsumer 消费 order.checkout.completed 事件时调用
# ---------------------------------------------------------------------------

@router.post("/apply-to-order")
async def apply_coupon_to_order(
    req: OrderCheckoutPayload,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """结账时活动检查（内部端点，由 SkillEventConsumer 处理 order.checkout.completed 事件触发）

    逻辑：
    1. 查询该客户在当前租户下已领取但未使用、且未过期的优惠券
    2. 查询当前有效活动（status=active，且在活动期内）
    3. 筛选满足订单金额门槛的优惠券
    4. 如有可用券，旁路发射 campaign.checkout_eligible 事件（前端弹出提示）
    5. 返回可用券列表，不自动核销（由收银员确认后调用 /coupons/{coupon_id}/apply）
    """
    try:
        tid = uuid.UUID(x_tenant_id)
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        now = datetime.now(timezone.utc)

        # ① 查询该客户已领取未使用、未过期的优惠券（联表取折扣信息和门槛）
        try:
            coupon_result = await db.execute(
                text("""
                    SELECT cc.id AS cc_id,
                           cc.coupon_id,
                           cc.expire_at,
                           c.name AS coupon_name,
                           c.coupon_type,
                           c.cash_amount_fen,
                           c.discount_rate,
                           c.min_order_fen AS minimum_amount_fen
                    FROM customer_coupons cc
                    JOIN coupons c ON c.id = cc.coupon_id AND c.tenant_id = cc.tenant_id
                    WHERE cc.tenant_id = :tid
                      AND cc.customer_id = :customer_id
                      AND cc.status = 'unused'
                      AND cc.is_deleted = false
                      AND (cc.expire_at IS NULL OR cc.expire_at > :now)
                      AND c.is_active = true
                      AND c.is_deleted = false
                    ORDER BY cc.created_at ASC
                """),
                {
                    "tid": tid,
                    "customer_id": uuid.UUID(req.customer_id),
                    "now": now,
                },
            )
            claimed_rows = coupon_result.fetchall()
        except SQLAlchemyError as exc:
            if _is_table_missing(exc):
                logger.warning("campaign.apply_to_order.table_not_ready", error=str(exc))
                return ok_response({
                    "eligible_coupons": [],
                    "auto_applicable": False,
                    "message": "优惠券功能尚未初始化",
                    "_note": "TABLE_NOT_READY",
                })
            raise

        # ② 查询当前有效活动（status=active，且在活动期内）
        try:
            campaign_result = await db.execute(
                text("""
                    SELECT id, name, campaign_type
                    FROM campaigns
                    WHERE tenant_id = :tid
                      AND status = 'active'
                      AND is_deleted = false
                      AND (start_time IS NULL OR start_time <= :now)
                      AND (end_time IS NULL OR end_time >= :now)
                """),
                {"tid": tid, "now": now},
            )
            active_campaigns = campaign_result.fetchall()
        except SQLAlchemyError as exc:
            if _is_table_missing(exc):
                logger.warning("campaign.apply_to_order.campaigns_table_not_ready", error=str(exc))
                active_campaigns = []
            else:
                raise

        active_campaign_count = len(active_campaigns)

        # ③ 筛选满足订单金额门槛的优惠券
        eligible_coupons = []
        for row in claimed_rows:
            minimum_amount_fen: int = row.minimum_amount_fen or 0
            if minimum_amount_fen > 0 and req.order_amount_fen < minimum_amount_fen:
                continue  # 不满足门槛，跳过

            eligible_coupons.append({
                "customer_coupon_id": str(row.cc_id),
                "coupon_id": str(row.coupon_id),
                "coupon_name": row.coupon_name,
                "coupon_type": row.coupon_type,
                "cash_amount_fen": row.cash_amount_fen,
                "discount_rate": row.discount_rate,
                "minimum_amount_fen": minimum_amount_fen,
                "expire_at": row.expire_at.isoformat() if row.expire_at else None,
            })

        # ④ 旁路发射事件（仅当有可用券时）
        if eligible_coupons:
            asyncio.create_task(emit_event(
                event_type="campaign.checkout_eligible",
                tenant_id=x_tenant_id,
                stream_id=req.order_id,
                payload={
                    "order_id": req.order_id,
                    "store_id": req.store_id,
                    "customer_id": req.customer_id,
                    "order_amount_fen": req.order_amount_fen,
                    "eligible_coupon_count": len(eligible_coupons),
                    "eligible_coupon_ids": [c["coupon_id"] for c in eligible_coupons],
                },
                store_id=req.store_id,
                source_service="tx-growth",
                metadata={"active_campaign_count": active_campaign_count},
            ))

        coupon_count = len(eligible_coupons)
        message = f"发现{coupon_count}张可用优惠券" if coupon_count > 0 else "暂无可用优惠券"

        logger.info(
            "campaign.checkout_checked",
            order_id=req.order_id,
            store_id=req.store_id,
            customer_id=req.customer_id,
            order_amount_fen=req.order_amount_fen,
            eligible_coupon_count=coupon_count,
            tenant_id=x_tenant_id,
        )

        return ok_response({
            "eligible_coupons": eligible_coupons,
            "auto_applicable": False,   # 预留字段，当前不自动核销
            "message": message,
        })

    except ValueError as exc:
        logger.warning("campaign.apply_to_order.invalid_param", error=str(exc))
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        await db.rollback()
        if _is_table_missing(exc):
            logger.warning("campaign.apply_to_order.table_not_ready", error=str(exc))
            return error_response("TABLE_NOT_READY", "优惠券功能尚未初始化，请联系管理员")
        logger.error("campaign.apply_to_order.db_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "查询可用优惠券失败")
