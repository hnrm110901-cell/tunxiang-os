"""营销活动引擎 — DB持久化版（v193 扩展字段）

提供完整的活动生命周期管理接口，包含：
  - 活动 CRUD（持久化到 campaigns 表）
  - 状态机（draft/scheduled/active/paused/ended/cancelled）
  - 活动核销（检查 target_audience/rules → 写 campaign_participants）
  - 活动统计（参与人次/已用预算/折扣总额）
  - 冲突检测（同类型同时间段活动重叠检查）

DB不可用时自动降级返回 Mock 数据。
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/growth/campaigns-v2", tags=["campaigns-engine-db"])

# ---------------------------------------------------------------------------
# 状态机
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["scheduled", "active", "cancelled"],
    "scheduled": ["active", "cancelled"],
    "active": ["paused", "ended", "cancelled"],
    "paused": ["active", "ended", "cancelled"],
    "ended": [],  # 终态
    "cancelled": [],  # 终态
}

# ---------------------------------------------------------------------------
# 降级兜底（DB不可用时返回空列表，避免返回过期的硬编码数据）
# ---------------------------------------------------------------------------

_FALLBACK_CAMPAIGNS: list[dict] = []

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


class CreateCampaignRequest(BaseModel):
    name: str
    campaign_type: str  # discount/gift/points/combo/flash_sale/buy_x_get_y
    start_at: str  # ISO8601
    end_at: str  # ISO8601
    budget_fen: Optional[int] = None
    target_audience: dict = {}
    rules: dict = {}
    applicable_stores: list = []
    priority: int = 0
    max_per_member: Optional[int] = None


class UpdateCampaignRequest(BaseModel):
    name: Optional[str] = None
    start_at: Optional[str] = None
    end_at: Optional[str] = None
    budget_fen: Optional[int] = None
    target_audience: Optional[dict] = None
    rules: Optional[dict] = None
    applicable_stores: Optional[list] = None
    priority: Optional[int] = None
    max_per_member: Optional[int] = None
    status: Optional[str] = None  # 状态流转（受状态机约束）


class ApplyCampaignRequest(BaseModel):
    member_id: str
    order_amount_fen: int
    store_id: Optional[str] = None
    order_id: Optional[str] = None


# ---------------------------------------------------------------------------
# DB 辅助
# ---------------------------------------------------------------------------


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _parse_dt(iso: Optional[str]) -> Optional[datetime]:
    if not iso:
        return None
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _row_to_dict(row: Any) -> dict:
    """将 SQLAlchemy Row 转为 dict"""
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    return dict(row)


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------


@router.get("")
async def list_campaigns(
    status: Optional[str] = Query(None, description="状态过滤"),
    campaign_type: Optional[str] = Query(None, alias="type", description="类型过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """活动列表（支持 status/type 过滤，分页）"""
    try:
        await _set_tenant(db, x_tenant_id)
        conditions = ["is_deleted = false"]
        params: dict = {"tenant_id": uuid.UUID(x_tenant_id), "limit": size, "offset": (page - 1) * size}

        if status:
            conditions.append("status = :status")
            params["status"] = status
        if campaign_type:
            conditions.append("campaign_type = :campaign_type")
            params["campaign_type"] = campaign_type

        where_clause = " AND ".join(conditions)
        result = await db.execute(
            text(f"""
                SELECT id, tenant_id, name, campaign_type, status,
                       start_at, end_at, budget_fen, used_fen,
                       target_audience, rules, applicable_stores,
                       priority, max_per_member, total_participants,
                       created_by, created_at, updated_at
                FROM campaigns
                WHERE {where_clause}
                ORDER BY priority DESC, created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = [_row_to_dict(r) for r in result.fetchall()]

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM campaigns WHERE {where_clause}"),
            {k: v for k, v in params.items() if k not in ("limit", "offset")},
        )
        total = count_result.scalar() or 0

        return ok_response({"items": rows, "total": total, "page": page, "size": size})

    except SQLAlchemyError:
        logger.warning("list_campaigns_db_error_fallback", tenant_id=x_tenant_id)
        items = _FALLBACK_CAMPAIGNS
        if status:
            items = [c for c in items if c["status"] == status]
        if campaign_type:
            items = [c for c in items if c["campaign_type"] == campaign_type]
        page_items = items[(page - 1) * size : page * size]
        return ok_response({"items": page_items, "total": len(items), "page": page, "size": size})


@router.get("/check-conflicts")
async def check_conflicts(
    campaign_type: str = Query(..., alias="type"),
    start_at: str = Query(...),
    end_at: str = Query(...),
    exclude_id: Optional[str] = Query(None),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """检测活动冲突（同类型同时间段活动重叠）"""
    try:
        await _set_tenant(db, x_tenant_id)
        start_dt = _parse_dt(start_at)
        end_dt = _parse_dt(end_at)

        params: dict = {
            "tenant_id": uuid.UUID(x_tenant_id),
            "campaign_type": campaign_type,
            "start_at": start_dt,
            "end_at": end_dt,
        }
        extra_cond = ""
        if exclude_id:
            extra_cond = " AND id != :exclude_id"
            params["exclude_id"] = uuid.UUID(exclude_id)

        result = await db.execute(
            text(f"""
                SELECT id, name, status, start_at, end_at
                FROM campaigns
                WHERE is_deleted = false
                  AND campaign_type = :campaign_type
                  AND status NOT IN ('ended', 'cancelled')
                  AND start_at < :end_at
                  AND end_at > :start_at
                  {extra_cond}
                ORDER BY start_at
            """),
            params,
        )
        conflicts = [_row_to_dict(r) for r in result.fetchall()]
        return ok_response({"conflict": len(conflicts) > 0, "conflicts": conflicts})

    except SQLAlchemyError:
        logger.warning("check_conflicts_db_error_fallback", tenant_id=x_tenant_id)
        return ok_response({"conflict": False, "conflicts": []})


@router.get("/{campaign_id}")
async def get_campaign(
    campaign_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """活动详情"""
    try:
        await _set_tenant(db, x_tenant_id)
        result = await db.execute(
            text("""
                SELECT id, tenant_id, name, campaign_type, status,
                       start_at, end_at, budget_fen, used_fen,
                       target_audience, rules, applicable_stores,
                       priority, max_per_member, total_participants,
                       created_by, created_at, updated_at
                FROM campaigns
                WHERE id = :id AND is_deleted = false
            """),
            {"id": uuid.UUID(campaign_id)},
        )
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=error_response("NOT_FOUND", f"活动不存在: {campaign_id}"))
        return ok_response(_row_to_dict(row))

    except HTTPException:
        raise
    except SQLAlchemyError:
        logger.warning("get_campaign_db_error_fallback", campaign_id=campaign_id, tenant_id=x_tenant_id)
        for c in _FALLBACK_CAMPAIGNS:
            if c["id"] == campaign_id:
                return ok_response(c)
        raise HTTPException(status_code=404, detail=error_response("NOT_FOUND", f"活动不存在: {campaign_id}"))


@router.post("")
async def create_campaign(
    req: CreateCampaignRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建活动（写入 campaigns 表，status=draft）"""
    import json as _json

    try:
        await _set_tenant(db, x_tenant_id)
        start_dt = _parse_dt(req.start_at)
        end_dt = _parse_dt(req.end_at)

        if start_dt and end_dt and start_dt >= end_dt:
            raise HTTPException(status_code=400, detail=error_response("INVALID_TIME", "end_at 必须晚于 start_at"))

        campaign_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        await db.execute(
            text("""
                INSERT INTO campaigns (
                    id, tenant_id, name, campaign_type, status,
                    start_at, end_at, budget_fen, used_fen,
                    target_audience, rules, applicable_stores,
                    priority, max_per_member, total_participants,
                    created_at, updated_at, is_deleted
                ) VALUES (
                    :id, :tenant_id, :name, :campaign_type, 'draft',
                    :start_at, :end_at, :budget_fen, 0,
                    :target_audience::jsonb, :rules::jsonb, :applicable_stores::jsonb,
                    :priority, :max_per_member, 0,
                    :now, :now, false
                )
            """),
            {
                "id": campaign_id,
                "tenant_id": uuid.UUID(x_tenant_id),
                "name": req.name,
                "campaign_type": req.campaign_type,
                "start_at": start_dt,
                "end_at": end_dt,
                "budget_fen": req.budget_fen,
                "target_audience": _json.dumps(req.target_audience, ensure_ascii=False),
                "rules": _json.dumps(req.rules, ensure_ascii=False),
                "applicable_stores": _json.dumps(req.applicable_stores, ensure_ascii=False),
                "priority": req.priority,
                "max_per_member": req.max_per_member,
                "now": now,
            },
        )
        await db.commit()

        logger.info("campaign.created", campaign_id=str(campaign_id), tenant_id=x_tenant_id)
        return ok_response(
            {
                "id": str(campaign_id),
                "name": req.name,
                "campaign_type": req.campaign_type,
                "status": "draft",
                "start_at": req.start_at,
                "end_at": req.end_at,
                "budget_fen": req.budget_fen,
                "used_fen": 0,
                "target_audience": req.target_audience,
                "rules": req.rules,
                "applicable_stores": req.applicable_stores,
                "priority": req.priority,
                "max_per_member": req.max_per_member,
                "total_participants": 0,
                "created_at": now.isoformat(),
            }
        )

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("campaign.create_failed", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail=error_response("DB_ERROR", "创建活动失败，请稍后重试"))


@router.put("/{campaign_id}")
async def update_campaign(
    campaign_id: str,
    req: UpdateCampaignRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新活动（含状态机验证）"""
    import json as _json

    try:
        await _set_tenant(db, x_tenant_id)

        # 先取当前状态
        cur = await db.execute(
            text("SELECT status FROM campaigns WHERE id = :id AND is_deleted = false"),
            {"id": uuid.UUID(campaign_id)},
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=error_response("NOT_FOUND", f"活动不存在: {campaign_id}"))

        current_status = row[0]

        # 如果请求变更状态，校验状态机
        if req.status and req.status != current_status:
            if req.status not in VALID_TRANSITIONS.get(current_status, []):
                raise HTTPException(
                    status_code=400,
                    detail=error_response(
                        "INVALID_TRANSITION",
                        f"状态 {current_status} → {req.status} 不合法，允许: {VALID_TRANSITIONS.get(current_status, [])}",
                    ),
                )

        # 构建 SET 子句
        updates: dict[str, Any] = {"id": uuid.UUID(campaign_id), "now": datetime.now(timezone.utc)}
        set_parts: list[str] = ["updated_at = :now"]

        if req.name is not None:
            set_parts.append("name = :name")
            updates["name"] = req.name
        if req.status is not None:
            set_parts.append("status = :status")
            updates["status"] = req.status
        if req.start_at is not None:
            set_parts.append("start_at = :start_at")
            updates["start_at"] = _parse_dt(req.start_at)
        if req.end_at is not None:
            set_parts.append("end_at = :end_at")
            updates["end_at"] = _parse_dt(req.end_at)
        if req.budget_fen is not None:
            set_parts.append("budget_fen = :budget_fen")
            updates["budget_fen"] = req.budget_fen
        if req.target_audience is not None:
            set_parts.append("target_audience = :target_audience::jsonb")
            updates["target_audience"] = _json.dumps(req.target_audience, ensure_ascii=False)
        if req.rules is not None:
            set_parts.append("rules = :rules::jsonb")
            updates["rules"] = _json.dumps(req.rules, ensure_ascii=False)
        if req.applicable_stores is not None:
            set_parts.append("applicable_stores = :applicable_stores::jsonb")
            updates["applicable_stores"] = _json.dumps(req.applicable_stores, ensure_ascii=False)
        if req.priority is not None:
            set_parts.append("priority = :priority")
            updates["priority"] = req.priority
        if req.max_per_member is not None:
            set_parts.append("max_per_member = :max_per_member")
            updates["max_per_member"] = req.max_per_member

        await db.execute(
            text(f"UPDATE campaigns SET {', '.join(set_parts)} WHERE id = :id"),
            updates,
        )
        await db.commit()

        logger.info("campaign.updated", campaign_id=campaign_id, tenant_id=x_tenant_id)
        return ok_response({"id": campaign_id, "updated": True})

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("campaign.update_failed", campaign_id=campaign_id, error=str(exc))
        raise HTTPException(status_code=500, detail=error_response("DB_ERROR", "更新活动失败，请稍后重试"))


@router.post("/{campaign_id}/activate")
async def activate_campaign(
    campaign_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """激活活动（draft/scheduled → active）"""
    try:
        await _set_tenant(db, x_tenant_id)

        cur = await db.execute(
            text("SELECT status FROM campaigns WHERE id = :id AND is_deleted = false"),
            {"id": uuid.UUID(campaign_id)},
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=error_response("NOT_FOUND", f"活动不存在: {campaign_id}"))

        current_status = row[0]
        if "active" not in VALID_TRANSITIONS.get(current_status, []):
            raise HTTPException(
                status_code=400,
                detail=error_response(
                    "INVALID_TRANSITION",
                    f"状态 {current_status} 不允许激活，允许转换: {VALID_TRANSITIONS.get(current_status, [])}",
                ),
            )

        await db.execute(
            text("UPDATE campaigns SET status = 'active', updated_at = NOW() WHERE id = :id"),
            {"id": uuid.UUID(campaign_id)},
        )
        await db.commit()
        logger.info("campaign.activated", campaign_id=campaign_id, tenant_id=x_tenant_id)
        return ok_response({"id": campaign_id, "status": "active"})

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("campaign.activate_failed", campaign_id=campaign_id, error=str(exc))
        raise HTTPException(status_code=500, detail=error_response("DB_ERROR", "激活活动失败，请稍后重试"))


@router.post("/{campaign_id}/pause")
async def pause_campaign(
    campaign_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """暂停活动（active → paused）"""
    try:
        await _set_tenant(db, x_tenant_id)

        cur = await db.execute(
            text("SELECT status FROM campaigns WHERE id = :id AND is_deleted = false"),
            {"id": uuid.UUID(campaign_id)},
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=error_response("NOT_FOUND", f"活动不存在: {campaign_id}"))

        current_status = row[0]
        if "paused" not in VALID_TRANSITIONS.get(current_status, []):
            raise HTTPException(
                status_code=400,
                detail=error_response(
                    "INVALID_TRANSITION",
                    f"状态 {current_status} 不允许暂停，允许转换: {VALID_TRANSITIONS.get(current_status, [])}",
                ),
            )

        await db.execute(
            text("UPDATE campaigns SET status = 'paused', updated_at = NOW() WHERE id = :id"),
            {"id": uuid.UUID(campaign_id)},
        )
        await db.commit()
        logger.info("campaign.paused", campaign_id=campaign_id, tenant_id=x_tenant_id)
        return ok_response({"id": campaign_id, "status": "paused"})

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("campaign.pause_failed", campaign_id=campaign_id, error=str(exc))
        raise HTTPException(status_code=500, detail=error_response("DB_ERROR", "暂停活动失败，请稍后重试"))


@router.post("/{campaign_id}/end")
async def end_campaign(
    campaign_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """结束活动（active → ended）"""
    try:
        await _set_tenant(db, x_tenant_id)

        cur = await db.execute(
            text("SELECT status FROM campaigns WHERE id = :id AND is_deleted = false"),
            {"id": uuid.UUID(campaign_id)},
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=error_response("NOT_FOUND", f"活动不存在: {campaign_id}"))

        current_status = row[0]
        if "ended" not in VALID_TRANSITIONS.get(current_status, []):
            raise HTTPException(
                status_code=400,
                detail=error_response(
                    "INVALID_TRANSITION",
                    f"状态 {current_status} 不允许结束，允许转换: {VALID_TRANSITIONS.get(current_status, [])}",
                ),
            )

        await db.execute(
            text("UPDATE campaigns SET status = 'ended', updated_at = NOW() WHERE id = :id"),
            {"id": uuid.UUID(campaign_id)},
        )
        await db.commit()
        logger.info("campaign.ended", campaign_id=campaign_id, tenant_id=x_tenant_id)
        return ok_response({"id": campaign_id, "status": "ended"})

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("campaign.end_failed", campaign_id=campaign_id, error=str(exc))
        raise HTTPException(status_code=500, detail=error_response("DB_ERROR", "结束活动失败，请稍后重试"))


@router.post("/{campaign_id}/apply")
async def apply_campaign(
    campaign_id: str,
    req: ApplyCampaignRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """核销活动（会员下单时检查并应用活动规则）

    逻辑：
    1. 查找 active 活动
    2. 检查 target_audience / rules（threshold_fen、discount_rate）
    3. 计算折扣
    4. 写 campaign_participants 记录
    返回：{applicable_campaigns, total_discount_fen, applied_campaign_id}
    """
    import json as _json

    try:
        await _set_tenant(db, x_tenant_id)

        cur = await db.execute(
            text("""
                SELECT id, status, rules, target_audience, budget_fen, used_fen,
                       max_per_member, campaign_type
                FROM campaigns
                WHERE id = :id AND is_deleted = false
            """),
            {"id": uuid.UUID(campaign_id)},
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=error_response("NOT_FOUND", f"活动不存在: {campaign_id}"))

        camp = _row_to_dict(row)

        if camp["status"] != "active":
            return ok_response(
                {
                    "applicable_campaigns": [],
                    "total_discount_fen": 0,
                    "applied_campaign_id": None,
                    "reason": f"活动未在进行中（当前: {camp['status']}）",
                }
            )

        rules = camp["rules"] if isinstance(camp["rules"], dict) else _json.loads(camp["rules"] or "{}")
        threshold_fen: int = rules.get("threshold_fen", 0)

        if req.order_amount_fen < threshold_fen:
            return ok_response(
                {
                    "applicable_campaigns": [],
                    "total_discount_fen": 0,
                    "applied_campaign_id": None,
                    "reason": f"订单金额 {req.order_amount_fen} 分不满足最低门槛 {threshold_fen} 分",
                }
            )

        # 检查预算
        budget_fen = camp["budget_fen"]
        used_fen: int = camp["used_fen"] or 0
        if budget_fen is not None and used_fen >= budget_fen:
            return ok_response(
                {
                    "applicable_campaigns": [],
                    "total_discount_fen": 0,
                    "applied_campaign_id": None,
                    "reason": "活动预算已用完",
                }
            )

        # 检查每会员参与上限
        max_per_member = camp["max_per_member"]
        if max_per_member is not None:
            count_result = await db.execute(
                text("""
                    SELECT COUNT(*) FROM campaign_participants
                    WHERE campaign_id = :cid
                      AND (member_id = :mid OR customer_id = :mid_uuid)
                """),
                {"cid": uuid.UUID(campaign_id), "mid": req.member_id, "mid_uuid": _try_uuid(req.member_id)},
            )
            participation_count = count_result.scalar() or 0
            if participation_count >= max_per_member:
                return ok_response(
                    {
                        "applicable_campaigns": [],
                        "total_discount_fen": 0,
                        "applied_campaign_id": None,
                        "reason": "已达每会员参与上限",
                    }
                )

        # 计算折扣
        discount_fen = _calc_discount(req.order_amount_fen, rules)

        # 写参与记录
        participant_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        member_uuid = _try_uuid(req.member_id)
        order_uuid = _try_uuid(req.order_id) if req.order_id else None
        store_uuid = _try_uuid(req.store_id) if req.store_id else None

        await db.execute(
            text("""
                INSERT INTO campaign_participants (
                    id, tenant_id, campaign_id, customer_id,
                    member_id, order_id, participation_type,
                    discount_applied_fen, points_earned, store_id,
                    participated_at
                ) VALUES (
                    :id, :tenant_id, :campaign_id, :customer_id,
                    :member_id, :order_id, 'used',
                    :discount_applied_fen, 0, :store_id,
                    :now
                )
            """),
            {
                "id": participant_id,
                "tenant_id": uuid.UUID(x_tenant_id),
                "campaign_id": uuid.UUID(campaign_id),
                "customer_id": member_uuid or uuid.uuid4(),
                "member_id": member_uuid,
                "order_id": order_uuid,
                "discount_applied_fen": discount_fen,
                "store_id": store_uuid,
                "now": now,
            },
        )

        # 原子更新 used_fen / total_participants
        await db.execute(
            text("""
                UPDATE campaigns
                SET used_fen = used_fen + :discount,
                    total_participants = total_participants + 1,
                    participant_count = participant_count + 1,
                    updated_at = NOW()
                WHERE id = :id
            """),
            {"discount": discount_fen, "id": uuid.UUID(campaign_id)},
        )

        await db.commit()
        logger.info(
            "campaign.applied",
            campaign_id=campaign_id,
            member_id=req.member_id,
            discount_fen=discount_fen,
            tenant_id=x_tenant_id,
        )

        return ok_response(
            {
                "applicable_campaigns": [campaign_id],
                "total_discount_fen": discount_fen,
                "applied_campaign_id": campaign_id,
                "participant_record_id": str(participant_id),
            }
        )

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("campaign.apply_failed", campaign_id=campaign_id, error=str(exc))
        raise HTTPException(status_code=500, detail=error_response("DB_ERROR", "活动核销失败，请稍后重试"))


@router.get("/{campaign_id}/stats")
async def get_campaign_stats(
    campaign_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """活动统计（参与人次/已用预算/折扣总额）"""
    try:
        await _set_tenant(db, x_tenant_id)

        cur = await db.execute(
            text("""
                SELECT id, name, status, budget_fen, used_fen, total_participants,
                       participant_count, total_cost_fen
                FROM campaigns
                WHERE id = :id AND is_deleted = false
            """),
            {"id": uuid.UUID(campaign_id)},
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=error_response("NOT_FOUND", f"活动不存在: {campaign_id}"))

        camp = _row_to_dict(row)

        # 从 campaign_participants 汇总实际折扣总额
        agg = await db.execute(
            text("""
                SELECT
                    COUNT(*) AS participant_count,
                    COALESCE(SUM(discount_applied_fen), 0) AS total_discount_fen,
                    COALESCE(SUM(points_earned), 0) AS total_points_earned
                FROM campaign_participants
                WHERE campaign_id = :cid
            """),
            {"cid": uuid.UUID(campaign_id)},
        )
        agg_row = _row_to_dict(agg.fetchone())

        return ok_response(
            {
                "campaign_id": campaign_id,
                "name": camp["name"],
                "status": camp["status"],
                "budget_fen": camp["budget_fen"],
                "used_fen": camp["used_fen"],
                "budget_utilization_pct": (
                    round(camp["used_fen"] / camp["budget_fen"] * 100, 2) if camp["budget_fen"] else None
                ),
                "total_participants": camp["total_participants"],
                "participant_count_from_records": agg_row["participant_count"],
                "total_discount_fen": agg_row["total_discount_fen"],
                "total_points_earned": agg_row["total_points_earned"],
            }
        )

    except HTTPException:
        raise
    except SQLAlchemyError:
        logger.warning("get_stats_db_error_fallback", campaign_id=campaign_id, tenant_id=x_tenant_id)
        for c in _FALLBACK_CAMPAIGNS:
            if c["id"] == campaign_id:
                return ok_response(
                    {
                        "campaign_id": campaign_id,
                        "name": c["name"],
                        "status": c["status"],
                        "budget_fen": c.get("budget_fen"),
                        "used_fen": c["used_fen"],
                        "total_participants": c["total_participants"],
                        "total_discount_fen": c["used_fen"],
                        "total_points_earned": 0,
                    }
                )
        raise HTTPException(status_code=404, detail=error_response("NOT_FOUND", f"活动不存在: {campaign_id}"))


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _try_uuid(value: Optional[str]) -> Optional[uuid.UUID]:
    """尝试将字符串转为 UUID，失败返回 None"""
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _calc_discount(order_amount_fen: int, rules: dict) -> int:
    """根据活动规则计算折扣金额（分）"""
    discount_fen = 0

    # 按比例折扣（discount_rate: 0.9 表示打9折）
    discount_rate: Optional[float] = rules.get("discount_rate")
    if discount_rate is not None and 0 < discount_rate < 1:
        discount_fen = int(order_amount_fen * (1 - discount_rate))

    # 满减（discount_fen: 直接减免金额，单位分）
    flat_discount: Optional[int] = rules.get("discount_fen")
    if flat_discount and flat_discount > 0:
        discount_fen = max(discount_fen, flat_discount)

    # 最大折扣上限
    max_discount: Optional[int] = rules.get("max_discount_fen")
    if max_discount and discount_fen > max_discount:
        discount_fen = max_discount

    return max(0, discount_fen)
