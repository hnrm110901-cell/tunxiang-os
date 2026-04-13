"""券权益中心 API 路由

前缀: /api/v1/member

端点:
  GET  /coupons                — 优惠券列表
  POST /coupons                — 创建优惠券
  GET  /stored-value/plans     — 储值方案列表
  GET  /gift-cards             — 礼品卡列表
  GET  /points/config          — 积分规则
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/member", tags=["coupon-benefit"])


# ─── 请求模型 ────────────────────────────────────────────────

class CreateCouponRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="优惠券名称")
    type: str = Field(..., description="类型: full_reduction/discount/free/gift")
    threshold_fen: int = Field(0, ge=0, description="使用门槛（分）")
    discount_fen: Optional[int] = Field(None, ge=0, description="减免金额（分）")
    discount_rate: Optional[float] = Field(None, gt=0, le=1, description="折扣率 0-1")
    max_discount_fen: Optional[int] = Field(None, ge=0, description="最大优惠金额（分）")
    total_quota: int = Field(..., gt=0, description="发行总量")
    start_date: str = Field(..., description="开始日期 YYYY-MM-DD")
    end_date: str = Field(..., description="结束日期 YYYY-MM-DD")
    scope: str = Field("all_stores", description="适用范围: all_stores/selected_stores")
    store_ids: list[str] = Field(default_factory=list, description="指定门店ID列表")
    target_segment: Optional[str] = Field(None, description="目标人群")


# ─── 辅助函数 ────────────────────────────────────────────────

def _require_tenant(x_tenant_id: Optional[str]) -> uuid.UUID:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    try:
        return uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-ID must be a valid UUID")


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ─── 端点 ────────────────────────────────────────────────────

@router.get("/coupons")
async def list_coupons(
    status: Optional[str] = Query(None, description="状态筛选: active/paused/expired"),
    coupon_type: Optional[str] = Query(None, alias="type", description="类型筛选"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """优惠券列表"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("list_coupons", tenant_id=str(tenant_id))

    await _set_rls(db, str(tenant_id))
    try:
        # Build dynamic WHERE clauses
        filters = [
            "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid",
            "is_deleted = false",
        ]
        params: dict = {"limit": size, "offset": (page - 1) * size}

        if status:
            # Map status values: active → is_active=true, paused/expired → is_active=false
            if status == "active":
                filters.append("is_active = true")
            else:
                filters.append("is_active = false")
        if coupon_type:
            filters.append("coupon_type = :coupon_type")
            params["coupon_type"] = coupon_type

        where_clause = " AND ".join(filters)

        count_result = await db.execute(
            text(f"SELECT COUNT(*) AS total FROM coupons WHERE {where_clause}"),
            params,
        )
        total = count_result.scalar() or 0

        rows_result = await db.execute(
            text(f"""
                SELECT
                    id::TEXT            AS coupon_id,
                    name,
                    coupon_type         AS type,
                    min_order_fen       AS threshold_fen,
                    cash_amount_fen     AS discount_fen,
                    discount_rate,
                    NULL::INT           AS max_discount_fen,
                    CASE WHEN is_active THEN 'active' ELSE 'paused' END AS status,
                    claimed_count       AS total_issued,
                    0                   AS total_used,
                    0.0                 AS use_rate,
                    start_date,
                    end_date,
                    applicable_scope    AS scope,
                    description         AS target_segment,
                    created_at
                FROM coupons
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = []
        for r in rows_result.mappings():
            item = dict(r)
            if item.get("created_at"):
                item["created_at"] = item["created_at"].isoformat()
            if item.get("start_date"):
                item["start_date"] = str(item["start_date"])
            if item.get("end_date"):
                item["end_date"] = str(item["end_date"])
            items.append(item)

        # Summary stats
        summary_result = await db.execute(
            text("""
                SELECT
                    COUNT(*) FILTER (WHERE is_active = true AND is_deleted = false)  AS total_active,
                    COALESCE(SUM(claimed_count) FILTER (WHERE is_deleted = false), 0) AS total_issued
                FROM coupons
                WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
            """),
        )
        summary_row = summary_result.mappings().first()
        summary = {
            "total_active": summary_row["total_active"] if summary_row else 0,
            "total_issued": summary_row["total_issued"] if summary_row else 0,
            "total_used": 0,
            "avg_use_rate": 0.0,
        }

        return {
            "ok": True,
            "data": {
                "items": items,
                "total": total,
                "page": page,
                "size": size,
                "summary": summary,
            },
        }
    except SQLAlchemyError as exc:
        logger.error("list_coupons_db_error", error=str(exc))
        return {
            "ok": True,
            "data": {
                "items": [],
                "total": 0,
                "page": page,
                "size": size,
                "summary": {"total_active": 0, "total_issued": 0, "total_used": 0, "avg_use_rate": 0.0},
            },
        }


@router.post("/coupons")
async def create_coupon(
    body: CreateCouponRequest,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """创建优惠券"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("create_coupon", tenant_id=str(tenant_id), name=body.name, coupon_type=body.type)

    await _set_rls(db, str(tenant_id))
    try:
        coupon_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        await db.execute(
            text("""
                INSERT INTO coupons (
                    id, tenant_id, name, coupon_type,
                    min_order_fen, cash_amount_fen, discount_rate,
                    total_quantity, start_date, end_date,
                    applicable_scope, applicable_ids,
                    description, is_active, created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :name, :coupon_type,
                    :min_order_fen, :cash_amount_fen, :discount_rate,
                    :total_quantity, :start_date, :end_date,
                    :applicable_scope, :applicable_ids::jsonb,
                    :description, true, :created_at, :created_at
                )
            """),
            {
                "id": coupon_id,
                "tenant_id": str(tenant_id),
                "name": body.name,
                "coupon_type": body.type,
                "min_order_fen": body.threshold_fen,
                "cash_amount_fen": body.discount_fen,
                "discount_rate": body.discount_rate,
                "total_quantity": body.total_quota,
                "start_date": body.start_date,
                "end_date": body.end_date,
                "applicable_scope": body.scope,
                "applicable_ids": str(body.store_ids) if body.store_ids else "[]",
                "description": body.target_segment,
                "created_at": now,
            },
        )
        await db.commit()

        return {
            "ok": True,
            "data": {
                "coupon_id": coupon_id,
                "name": body.name,
                "type": body.type,
                "threshold_fen": body.threshold_fen,
                "discount_fen": body.discount_fen,
                "discount_rate": body.discount_rate,
                "max_discount_fen": body.max_discount_fen,
                "status": "active",
                "total_issued": 0,
                "total_used": 0,
                "use_rate": 0.0,
                "total_quota": body.total_quota,
                "start_date": body.start_date,
                "end_date": body.end_date,
                "scope": body.scope,
                "store_ids": body.store_ids,
                "target_segment": body.target_segment,
                "created_at": now.isoformat(),
            },
        }
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("create_coupon_db_error", error=str(exc))
        raise HTTPException(status_code=500, detail="创建优惠券失败，请稍后重试")


@router.get("/stored-value/plans")
async def list_stored_value_plans(
    status: Optional[str] = Query(None, description="状态筛选: active/paused"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """储值方案列表"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("list_stored_value_plans", tenant_id=str(tenant_id))

    await _set_rls(db, str(tenant_id))
    try:
        filters = [
            "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid",
            "is_deleted = false",
        ]
        params: dict = {}

        if status == "active":
            filters.append("is_active = true")
        elif status == "paused":
            filters.append("is_active = false")

        where_clause = " AND ".join(filters)

        rows_result = await db.execute(
            text(f"""
                SELECT
                    id::TEXT                AS plan_id,
                    name,
                    recharge_amount_fen     AS charge_fen,
                    gift_amount_fen         AS gift_fen,
                    CASE
                        WHEN recharge_amount_fen > 0
                        THEN ROUND(gift_amount_fen::NUMERIC / recharge_amount_fen, 4)
                        ELSE 0
                    END                     AS gift_rate,
                    CASE WHEN is_active THEN 'active' ELSE 'paused' END AS status,
                    0                       AS total_sold,
                    0                       AS total_charge_fen,
                    valid_from::TEXT        AS start_date,
                    valid_until::TEXT       AS end_date
                FROM stored_value_recharge_plans
                WHERE {where_clause}
                ORDER BY sort_order ASC, recharge_amount_fen ASC
            """),
            params,
        )
        items = [dict(r) for r in rows_result.mappings()]

        # Summary totals
        summary_result = await db.execute(
            text("""
                SELECT COUNT(*) AS total_plans
                FROM stored_value_recharge_plans
                WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                  AND is_deleted = false
            """),
        )
        summary_row = summary_result.mappings().first()
        total_plans = summary_row["total_plans"] if summary_row else 0

        return {
            "ok": True,
            "data": {
                "items": items,
                "total": len(items),
                "summary": {
                    "total_balance_fen": 0,
                    "total_plans": total_plans,
                    "total_customers": 0,
                },
            },
        }
    except SQLAlchemyError as exc:
        logger.error("list_stored_value_plans_db_error", error=str(exc))
        return {
            "ok": True,
            "data": {
                "items": [],
                "total": 0,
                "summary": {"total_balance_fen": 0, "total_plans": 0, "total_customers": 0},
            },
        }


@router.get("/gift-cards")
async def list_gift_cards(
    status: Optional[str] = Query(None, description="状态筛选: active/paused"),
    card_type: Optional[str] = Query(None, alias="type", description="类型: fixed/custom"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """礼品卡列表（gift_cards 表尚未建立时返回空列表）"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("list_gift_cards", tenant_id=str(tenant_id))

    await _set_rls(db, str(tenant_id))
    try:
        filters = [
            "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid",
            "is_deleted = false",
        ]
        params: dict = {"limit": size, "offset": (page - 1) * size}

        if status:
            params["status"] = status
            filters.append("status = :status")
        if card_type:
            params["card_type"] = card_type
            filters.append("card_type = :card_type")

        where_clause = " AND ".join(filters)

        count_result = await db.execute(
            text(f"SELECT COUNT(*) AS total FROM gift_cards WHERE {where_clause}"),
            params,
        )
        total = count_result.scalar() or 0

        rows_result = await db.execute(
            text(f"""
                SELECT
                    id::TEXT            AS card_id,
                    name,
                    face_value_fen,
                    price_fen,
                    card_type           AS type,
                    status,
                    0                   AS total_sold,
                    0                   AS total_redeemed,
                    design_theme,
                    created_at
                FROM gift_cards
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = []
        for r in rows_result.mappings():
            item = dict(r)
            if item.get("created_at"):
                item["created_at"] = item["created_at"].isoformat()
            items.append(item)

        return {
            "ok": True,
            "data": {
                "items": items,
                "total": total,
                "page": page,
                "size": size,
            },
        }
    except SQLAlchemyError as exc:
        logger.warning("list_gift_cards_db_error", error=str(exc))
        # gift_cards table may not exist yet — return empty gracefully
        return {
            "ok": True,
            "data": {
                "items": [],
                "total": 0,
                "page": page,
                "size": size,
            },
        }


@router.get("/points/config")
async def get_points_config(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """积分规则配置"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("get_points_config", tenant_id=str(tenant_id))

    await _set_rls(db, str(tenant_id))
    try:
        # Fetch earn rules from points_rules
        earn_result = await db.execute(
            text("""
                SELECT
                    rule_name       AS action,
                    earn_type,
                    points_per_100fen,
                    fixed_points,
                    multiplier
                FROM points_rules
                WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                  AND is_active = true
                  AND is_deleted = false
                ORDER BY earn_type
            """),
        )
        earn_rows = list(earn_result.mappings())

        earn_rules = []
        for r in earn_rows:
            rule: dict = {
                "action": r["action"] or r["earn_type"],
                "earn_type": r["earn_type"],
            }
            if r["fixed_points"] and r["fixed_points"] > 0:
                rule["fixed_points"] = r["fixed_points"]
                rule["rule"] = f"{rule['action']} {r['fixed_points']}分"
            elif r["multiplier"] and float(r["multiplier"]) != 1.0:
                rule["multiplier"] = float(r["multiplier"])
                rule["rule"] = f"{rule['action']}积分x{r['multiplier']}"
            else:
                rate = float(r["points_per_100fen"])
                rule["rate"] = rate
                rule["unit"] = "元/分"
                rule["rule"] = f"每消费1元积{rate}分"
            earn_rules.append(rule)

        # Fetch tier multipliers from member_level_configs
        tier_result = await db.execute(
            text("""
                SELECT
                    level_name,
                    birthday_bonus_multiplier AS multiplier
                FROM member_level_configs
                WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                  AND is_active = true
                  AND is_deleted = false
                ORDER BY sort_order ASC
            """),
        )
        tier_rows = list(tier_result.mappings())
        tier_multiplier = [
            {"tier": r["level_name"], "multiplier": float(r["multiplier"])}
            for r in tier_rows
        ]

        # Aggregate points balance stats
        stats_result = await db.execute(
            text("""
                SELECT
                    COALESCE(SUM(points), 0) AS total_points_balance
                FROM member_points_balance
                WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
            """),
        )
        stats_row = stats_result.mappings().first()
        total_balance = int(stats_row["total_points_balance"]) if stats_row else 0

        return {
            "ok": True,
            "data": {
                "earn_rules": earn_rules,
                "redeem_rules": [
                    {"type": "cash_deduction", "label": "积分抵现", "rate": 100,
                     "description": "100积分抵1元", "max_deduction_ratio": 0.5},
                    {"type": "gift_exchange", "label": "积分换礼", "description": "指定礼品兑换"},
                    {"type": "coupon_exchange", "label": "积分换券", "description": "积分兑换优惠券"},
                ],
                "expiry_rule": {
                    "type": "annual_clear",
                    "description": "每年12月31日清零当年1月1日前获取的积分",
                    "advance_notice_days": 30,
                },
                "tier_multiplier": tier_multiplier,
                "total_points_balance": total_balance,
            },
        }
    except SQLAlchemyError as exc:
        logger.error("get_points_config_db_error", error=str(exc))
        return {
            "ok": True,
            "data": {
                "earn_rules": [],
                "redeem_rules": [],
                "expiry_rule": {},
                "tier_multiplier": [],
                "total_points_balance": 0,
            },
        }
