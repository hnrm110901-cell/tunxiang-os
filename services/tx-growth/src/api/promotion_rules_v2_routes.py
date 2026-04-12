"""营销促销规则引擎 V2 — prefix /api/v1/promotions

五类促销方案 + 互斥组/优先级/叠加开关 + 毛利底线硬约束

端点（7个）:
1. GET    /api/v1/promotions/rules                — 规则列表（分页+状态筛选）
2. POST   /api/v1/promotions/rules                — 创建规则（含互斥组/优先级字段）
3. PUT    /api/v1/promotions/rules/{rule_id}      — 更新规则
4. DELETE /api/v1/promotions/rules/{rule_id}      — 停用（软删除）
5. POST   /api/v1/promotions/calculate            — 结账时计算适用规则（输入order_items，返回折扣明细）
6. POST   /api/v1/promotions/voucher/verify       — 券码核销验证
7. GET    /api/v1/promotions/effect-report        — 促销效果报表

三条硬约束（calculate 端点强制校验）：
  毛利底线：折扣后毛利 ≥ gross_margin_threshold（可按规则配置）

方案类型枚举（PromotionType）：
  TIME_DISCOUNT    — 时段折扣（仅午市11:00-14:00/仅周末）
  ITEM_DISCOUNT    — 品项指定折扣（单品不打折/指定特价）
  BUY_GIFT         — 买赠（买主菜送凉菜，指定赠品SKU）
  FULL_REDUCE      — 满减（满200减30，可叠加开关）
  VOUCHER_VERIFY   — 团购券/美团券核销（输入券码验证）

RLS: NULLIF(current_setting('app.tenant_id', true), '')::uuid
统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header
"""
from __future__ import annotations

import uuid
from datetime import datetime, time, timezone
from enum import Enum
from typing import Any, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/promotions", tags=["promotion-rules-v2"])

# ─── 枚举 ────────────────────────────────────────────────────────────────────


class PromotionType(str, Enum):
    TIME_DISCOUNT = "TIME_DISCOUNT"      # 时段折扣
    ITEM_DISCOUNT = "ITEM_DISCOUNT"      # 品项指定折扣
    BUY_GIFT = "BUY_GIFT"               # 买赠
    FULL_REDUCE = "FULL_REDUCE"         # 满减
    VOUCHER_VERIFY = "VOUCHER_VERIFY"   # 团购券/美团券核销


class PromotionStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    EXPIRED = "expired"


# ─── 工具函数 ────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: int = 400) -> None:
    raise HTTPException(
        status_code=code,
        detail={"ok": False, "data": None, "error": {"message": msg}},
    )


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ─── DDL（首次调用时自动建表） ──────────────────────────────────────────────

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS promotion_rules_v2 (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID NOT NULL,
    name             TEXT NOT NULL,
    promotion_type   TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'active',

    -- 互斥与优先级
    exclusion_group  TEXT,                 -- 同组规则互斥，取优先级最高的生效
    priority         INTEGER NOT NULL DEFAULT 100,  -- 数字越小优先级越高
    stack_allowed    BOOLEAN NOT NULL DEFAULT FALSE, -- 是否允许与其他规则叠加

    -- 时段折扣参数
    time_start       TIME,                 -- 如 11:00
    time_end         TIME,                 -- 如 14:00
    weekdays         INTEGER[],            -- 0=周日,1=周一...6=周六，NULL=每天
    discount_pct     INTEGER,              -- 折扣百分比，如 85 表示85折（8.5折）

    -- 品项折扣参数
    item_skus        TEXT[],              -- 适用SKU列表
    item_price_fen   INTEGER,             -- 指定特价（分），NULL=不特价

    -- 买赠参数
    buy_sku          TEXT,                -- 主菜SKU
    gift_sku         TEXT,                -- 赠品SKU
    gift_qty         INTEGER DEFAULT 1,

    -- 满减参数
    full_reduce_threshold_fen  INTEGER,   -- 满减门槛（分），如 20000 = 200元
    full_reduce_amount_fen     INTEGER,   -- 减免金额（分），如 3000 = 30元

    -- 团购券参数
    voucher_platform TEXT,               -- 如 meituan/douyin/custom
    voucher_face_value_fen INTEGER,      -- 券面值（分）
    voucher_cost_fen       INTEGER,      -- 商家承担成本（分）

    -- 毛利底线硬约束
    gross_margin_threshold_pct INTEGER DEFAULT 20,  -- 折扣后毛利率不低于此值（%）

    -- 有效期
    valid_from       TIMESTAMPTZ,
    valid_to         TIMESTAMPTZ,

    -- 通用字段
    description      TEXT,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW(),
    is_deleted       BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_promo_rules_v2_tenant
    ON promotion_rules_v2 (tenant_id)
    WHERE is_deleted = FALSE;

-- RLS
ALTER TABLE promotion_rules_v2 ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'promotion_rules_v2'
          AND policyname = 'tenant_isolation'
    ) THEN
        CREATE POLICY tenant_isolation ON promotion_rules_v2
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::uuid);
    END IF;
END
$$;

-- 团购券核销日志表
CREATE TABLE IF NOT EXISTS promotion_voucher_logs (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL,
    rule_id        UUID REFERENCES promotion_rules_v2(id),
    voucher_code   TEXT NOT NULL,
    order_id       UUID,
    store_id       UUID,
    verified_at    TIMESTAMPTZ DEFAULT NOW(),
    is_used        BOOLEAN DEFAULT FALSE,
    used_at        TIMESTAMPTZ,
    face_value_fen INTEGER NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_voucher_logs_tenant
    ON promotion_voucher_logs (tenant_id, voucher_code);

ALTER TABLE promotion_voucher_logs ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'promotion_voucher_logs'
          AND policyname = 'tenant_isolation'
    ) THEN
        CREATE POLICY tenant_isolation ON promotion_voucher_logs
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::uuid);
    END IF;
END
$$;
"""

_TABLE_INITIALIZED = False


async def _ensure_tables(db: AsyncSession) -> None:
    global _TABLE_INITIALIZED
    if _TABLE_INITIALIZED:
        return
    try:
        await db.execute(text(_CREATE_TABLE_SQL))
        await db.commit()
        _TABLE_INITIALIZED = True
        logger.info("promotion_rules_v2_tables_initialized")
    except SQLAlchemyError as exc:
        logger.warning("promotion_rules_v2_tables_init_warning", error=str(exc))


# ─── 请求/响应 Pydantic 模型 ─────────────────────────────────────────────────


class PromotionRuleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    promotion_type: PromotionType
    exclusion_group: Optional[str] = None
    priority: int = Field(default=100, ge=1, le=9999)
    stack_allowed: bool = False
    gross_margin_threshold_pct: int = Field(default=20, ge=0, le=100)

    # 有效期
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    description: Optional[str] = None

    # 时段折扣参数
    time_start: Optional[str] = Field(None, description="HH:MM格式，如 11:00")
    time_end: Optional[str] = Field(None, description="HH:MM格式，如 14:00")
    weekdays: Optional[List[int]] = Field(None, description="0=周日,1=周一...6=周六，None=每天")
    discount_pct: Optional[int] = Field(None, ge=1, le=100, description="折扣百分比，如85=8.5折")

    # 品项折扣参数
    item_skus: Optional[List[str]] = None
    item_price_fen: Optional[int] = Field(None, ge=0)

    # 买赠参数
    buy_sku: Optional[str] = None
    gift_sku: Optional[str] = None
    gift_qty: Optional[int] = Field(None, ge=1)

    # 满减参数
    full_reduce_threshold_fen: Optional[int] = Field(None, ge=0)
    full_reduce_amount_fen: Optional[int] = Field(None, ge=0)

    # 团购券参数
    voucher_platform: Optional[str] = None
    voucher_face_value_fen: Optional[int] = Field(None, ge=0)
    voucher_cost_fen: Optional[int] = Field(None, ge=0)

    @field_validator("weekdays")
    @classmethod
    def validate_weekdays(cls, v: Optional[List[int]]) -> Optional[List[int]]:
        if v is not None:
            for d in v:
                if d < 0 or d > 6:
                    raise ValueError("weekdays 每个值必须在 0-6 之间")
        return v

    @field_validator("time_start", "time_end")
    @classmethod
    def validate_time_format(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            try:
                hour, minute = v.split(":")
                if not (0 <= int(hour) <= 23 and 0 <= int(minute) <= 59):
                    raise ValueError
            except (ValueError, AttributeError):
                raise ValueError("时间格式必须为 HH:MM，如 11:00")
        return v


class PromotionRuleUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    status: Optional[PromotionStatus] = None
    exclusion_group: Optional[str] = None
    priority: Optional[int] = Field(None, ge=1, le=9999)
    stack_allowed: Optional[bool] = None
    gross_margin_threshold_pct: Optional[int] = Field(None, ge=0, le=100)
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    description: Optional[str] = None
    time_start: Optional[str] = None
    time_end: Optional[str] = None
    weekdays: Optional[List[int]] = None
    discount_pct: Optional[int] = Field(None, ge=1, le=100)
    item_skus: Optional[List[str]] = None
    item_price_fen: Optional[int] = Field(None, ge=0)
    buy_sku: Optional[str] = None
    gift_sku: Optional[str] = None
    gift_qty: Optional[int] = Field(None, ge=1)
    full_reduce_threshold_fen: Optional[int] = Field(None, ge=0)
    full_reduce_amount_fen: Optional[int] = Field(None, ge=0)
    voucher_platform: Optional[str] = None
    voucher_face_value_fen: Optional[int] = Field(None, ge=0)
    voucher_cost_fen: Optional[int] = Field(None, ge=0)


class OrderItemIn(BaseModel):
    sku: str
    name: str
    qty: int = Field(..., ge=1)
    unit_price_fen: int = Field(..., ge=0, description="单价（分）")
    cost_price_fen: int = Field(default=0, ge=0, description="成本价（分），用于毛利校验")


class CalculateRequest(BaseModel):
    order_items: List[OrderItemIn]
    store_id: Optional[str] = None
    order_time: Optional[datetime] = None  # 用于时段折扣校验，None=当前时间


class VoucherVerifyRequest(BaseModel):
    voucher_code: str
    order_id: Optional[str] = None
    store_id: Optional[str] = None


# ─── 内部计算逻辑 ────────────────────────────────────────────────────────────


def _is_time_in_range(order_time: datetime, time_start: str, time_end: str) -> bool:
    """检查订单时间是否在时段范围内。"""
    try:
        sh, sm = map(int, time_start.split(":"))
        eh, em = map(int, time_end.split(":"))
        t_start = time(sh, sm)
        t_end = time(eh, em)
        t_order = order_time.time()
        if t_start <= t_end:
            return t_start <= t_order <= t_end
        # 跨午夜情况
        return t_order >= t_start or t_order <= t_end
    except (ValueError, AttributeError):
        return False


def _is_weekday_match(order_time: datetime, weekdays: Optional[List[int]]) -> bool:
    """检查订单星期是否匹配。"""
    if not weekdays:
        return True
    # Python weekday(): 0=周一...6=周日，转换为0=周日,1=周一...6=周六
    py_weekday = order_time.weekday()  # 0=Mon...6=Sun
    converted = (py_weekday + 1) % 7   # 0=Sun,1=Mon...6=Sat
    return converted in weekdays


def _apply_rule(
    rule: dict,
    items: List[OrderItemIn],
    order_time: datetime,
    original_total_fen: int,
) -> Optional[dict]:
    """
    根据规则类型计算折扣明细。
    返回 None 表示规则不适用；返回 dict 包含 discount_fen 和 detail。
    """
    ptype = rule["promotion_type"]

    if ptype == PromotionType.TIME_DISCOUNT:
        # 检查时段和星期
        ts = rule.get("time_start")
        te = rule.get("time_end")
        weekdays = rule.get("weekdays")
        discount_pct = rule.get("discount_pct")
        if not ts or not te or not discount_pct:
            return None
        if not _is_time_in_range(order_time, ts, te):
            return None
        if not _is_weekday_match(order_time, weekdays):
            return None
        # 按比例计算折扣
        discount_fen = original_total_fen - int(original_total_fen * discount_pct / 100)
        return {
            "rule_id": str(rule["id"]),
            "rule_name": rule["name"],
            "promotion_type": ptype,
            "discount_fen": discount_fen,
            "detail": f"时段折扣 {discount_pct}折，时段 {ts}-{te}",
        }

    elif ptype == PromotionType.ITEM_DISCOUNT:
        item_skus = rule.get("item_skus") or []
        item_price_fen = rule.get("item_price_fen")
        discount_pct = rule.get("discount_pct")
        if not item_skus:
            return None
        matched_items = [it for it in items if it.sku in item_skus]
        if not matched_items:
            return None
        total_discount = 0
        detail_parts = []
        for it in matched_items:
            if item_price_fen is not None:
                # 指定特价
                if it.unit_price_fen > item_price_fen:
                    diff = (it.unit_price_fen - item_price_fen) * it.qty
                    total_discount += diff
                    detail_parts.append(f"{it.name} 特价 {item_price_fen/100:.2f}元")
            elif discount_pct is not None:
                # 指定折扣
                item_total = it.unit_price_fen * it.qty
                disc = item_total - int(item_total * discount_pct / 100)
                total_discount += disc
                detail_parts.append(f"{it.name} {discount_pct}折")
        if total_discount <= 0:
            return None
        return {
            "rule_id": str(rule["id"]),
            "rule_name": rule["name"],
            "promotion_type": ptype,
            "discount_fen": total_discount,
            "detail": "；".join(detail_parts) if detail_parts else "品项折扣",
        }

    elif ptype == PromotionType.BUY_GIFT:
        buy_sku = rule.get("buy_sku")
        gift_sku = rule.get("gift_sku")
        gift_qty = rule.get("gift_qty") or 1
        if not buy_sku or not gift_sku:
            return None
        has_buy = any(it.sku == buy_sku for it in items)
        if not has_buy:
            return None
        # 找赠品价格（若订单中已有则以订单中价格为基准）
        gift_items = [it for it in items if it.sku == gift_sku]
        gift_unit_price = gift_items[0].unit_price_fen if gift_items else 0
        discount_fen = gift_unit_price * gift_qty
        return {
            "rule_id": str(rule["id"]),
            "rule_name": rule["name"],
            "promotion_type": ptype,
            "discount_fen": discount_fen,
            "detail": f"买赠：购买 {buy_sku} 赠送 {gift_sku} x{gift_qty}",
            "gift_items": [{"sku": gift_sku, "qty": gift_qty}],
        }

    elif ptype == PromotionType.FULL_REDUCE:
        threshold = rule.get("full_reduce_threshold_fen") or 0
        amount = rule.get("full_reduce_amount_fen") or 0
        if original_total_fen < threshold:
            return None
        return {
            "rule_id": str(rule["id"]),
            "rule_name": rule["name"],
            "promotion_type": ptype,
            "discount_fen": amount,
            "detail": f"满{threshold//100}减{amount//100}",
        }

    # VOUCHER_VERIFY 不在 calculate 端点中自动适用，需通过 verify 端点
    return None


def _check_gross_margin(
    items: List[OrderItemIn],
    total_discount_fen: int,
    threshold_pct: int,
) -> tuple[bool, float]:
    """
    毛利底线硬约束校验。
    返回 (passed, actual_margin_pct)。
    """
    total_revenue = sum(it.unit_price_fen * it.qty for it in items)
    total_cost = sum(it.cost_price_fen * it.qty for it in items)

    if total_revenue <= 0:
        return True, 0.0

    net_revenue = total_revenue - total_discount_fen
    gross_profit = net_revenue - total_cost
    margin_pct = gross_profit / net_revenue * 100 if net_revenue > 0 else 0.0

    return margin_pct >= threshold_pct, round(margin_pct, 2)


# ─── API 端点 ────────────────────────────────────────────────────────────────


@router.get("/rules")
async def list_rules(
    request: Request,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    status: Optional[str] = Query(default=None),
    promotion_type: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """规则列表（分页 + 状态/类型筛选）。"""
    tenant_id = _get_tenant_id(request)
    await _ensure_tables(db)
    await _set_rls(db, tenant_id)

    conditions = ["is_deleted = FALSE", "tenant_id = :tid"]
    params: dict[str, Any] = {"tid": tenant_id, "offset": (page - 1) * size, "limit": size}

    if status:
        conditions.append("status = :status")
        params["status"] = status
    if promotion_type:
        conditions.append("promotion_type = :ptype")
        params["ptype"] = promotion_type

    where = " AND ".join(conditions)

    try:
        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM promotion_rules_v2 WHERE {where}"),
            params,
        )
        total = count_result.scalar() or 0

        rows = await db.execute(
            text(
                f"""
                SELECT id, name, promotion_type, status, exclusion_group, priority,
                       stack_allowed, discount_pct, time_start, time_end, weekdays,
                       item_skus, item_price_fen, buy_sku, gift_sku, gift_qty,
                       full_reduce_threshold_fen, full_reduce_amount_fen,
                       voucher_platform, voucher_face_value_fen, voucher_cost_fen,
                       gross_margin_threshold_pct, valid_from, valid_to,
                       description, created_at, updated_at
                FROM promotion_rules_v2
                WHERE {where}
                ORDER BY priority ASC, created_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
        items = [dict(r._mapping) for r in rows.fetchall()]
        # 转换 uuid 和 time 为字符串
        for item in items:
            item["id"] = str(item["id"])
        return _ok({"items": items, "total": total, "page": page, "size": size})
    except SQLAlchemyError as exc:
        logger.error("list_promotion_rules_db_error", error=str(exc), exc_info=True)
        _err("数据库查询失败", 500)


@router.post("/rules")
async def create_rule(
    request: Request,
    body: PromotionRuleCreate,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建促销规则。"""
    tenant_id = _get_tenant_id(request)
    await _ensure_tables(db)
    await _set_rls(db, tenant_id)

    rule_id = uuid.uuid4()

    try:
        await db.execute(
            text(
                """
                INSERT INTO promotion_rules_v2 (
                    id, tenant_id, name, promotion_type, status,
                    exclusion_group, priority, stack_allowed,
                    gross_margin_threshold_pct,
                    time_start, time_end, weekdays, discount_pct,
                    item_skus, item_price_fen,
                    buy_sku, gift_sku, gift_qty,
                    full_reduce_threshold_fen, full_reduce_amount_fen,
                    voucher_platform, voucher_face_value_fen, voucher_cost_fen,
                    valid_from, valid_to, description
                ) VALUES (
                    :id, :tenant_id, :name, :promotion_type, 'active',
                    :exclusion_group, :priority, :stack_allowed,
                    :gross_margin_threshold_pct,
                    :time_start, :time_end, :weekdays, :discount_pct,
                    :item_skus, :item_price_fen,
                    :buy_sku, :gift_sku, :gift_qty,
                    :full_reduce_threshold_fen, :full_reduce_amount_fen,
                    :voucher_platform, :voucher_face_value_fen, :voucher_cost_fen,
                    :valid_from, :valid_to, :description
                )
                """
            ),
            {
                "id": rule_id,
                "tenant_id": tenant_id,
                "name": body.name,
                "promotion_type": body.promotion_type.value,
                "exclusion_group": body.exclusion_group,
                "priority": body.priority,
                "stack_allowed": body.stack_allowed,
                "gross_margin_threshold_pct": body.gross_margin_threshold_pct,
                "time_start": body.time_start,
                "time_end": body.time_end,
                "weekdays": body.weekdays,
                "discount_pct": body.discount_pct,
                "item_skus": body.item_skus,
                "item_price_fen": body.item_price_fen,
                "buy_sku": body.buy_sku,
                "gift_sku": body.gift_sku,
                "gift_qty": body.gift_qty,
                "full_reduce_threshold_fen": body.full_reduce_threshold_fen,
                "full_reduce_amount_fen": body.full_reduce_amount_fen,
                "voucher_platform": body.voucher_platform,
                "voucher_face_value_fen": body.voucher_face_value_fen,
                "voucher_cost_fen": body.voucher_cost_fen,
                "valid_from": body.valid_from,
                "valid_to": body.valid_to,
                "description": body.description,
            },
        )
        await db.commit()
        logger.info("promotion_rule_created", rule_id=str(rule_id), tenant_id=tenant_id)
        return _ok({"id": str(rule_id), "message": "规则创建成功"})
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("create_promotion_rule_db_error", error=str(exc), exc_info=True)
        _err("规则创建失败", 500)


@router.put("/rules/{rule_id}")
async def update_rule(
    rule_id: str,
    request: Request,
    body: PromotionRuleUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新促销规则。"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    # 构建动态 SET 子句
    update_fields: dict[str, Any] = {"rule_id": rule_id, "tid": tenant_id}
    set_parts = ["updated_at = NOW()"]

    field_map = {
        "name": body.name,
        "status": body.status.value if body.status else None,
        "exclusion_group": body.exclusion_group,
        "priority": body.priority,
        "stack_allowed": body.stack_allowed,
        "gross_margin_threshold_pct": body.gross_margin_threshold_pct,
        "valid_from": body.valid_from,
        "valid_to": body.valid_to,
        "description": body.description,
        "time_start": body.time_start,
        "time_end": body.time_end,
        "weekdays": body.weekdays,
        "discount_pct": body.discount_pct,
        "item_skus": body.item_skus,
        "item_price_fen": body.item_price_fen,
        "buy_sku": body.buy_sku,
        "gift_sku": body.gift_sku,
        "gift_qty": body.gift_qty,
        "full_reduce_threshold_fen": body.full_reduce_threshold_fen,
        "full_reduce_amount_fen": body.full_reduce_amount_fen,
        "voucher_platform": body.voucher_platform,
        "voucher_face_value_fen": body.voucher_face_value_fen,
        "voucher_cost_fen": body.voucher_cost_fen,
    }

    for field, val in field_map.items():
        if val is not None:
            set_parts.append(f"{field} = :{field}")
            update_fields[field] = val

    if len(set_parts) <= 1:
        _err("请至少提供一个更新字段")

    try:
        result = await db.execute(
            text(
                f"""
                UPDATE promotion_rules_v2
                SET {', '.join(set_parts)}
                WHERE id = :rule_id
                  AND tenant_id = :tid
                  AND is_deleted = FALSE
                """
            ),
            update_fields,
        )
        if result.rowcount == 0:
            _err("规则不存在或无权限", 404)
        await db.commit()
        return _ok({"id": rule_id, "message": "规则更新成功"})
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("update_promotion_rule_db_error", error=str(exc), exc_info=True)
        _err("规则更新失败", 500)


@router.delete("/rules/{rule_id}")
async def delete_rule(
    rule_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """停用规则（软删除）。"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    try:
        result = await db.execute(
            text(
                """
                UPDATE promotion_rules_v2
                SET is_deleted = TRUE, status = 'inactive', updated_at = NOW()
                WHERE id = :rule_id
                  AND tenant_id = :tid
                  AND is_deleted = FALSE
                """
            ),
            {"rule_id": rule_id, "tid": tenant_id},
        )
        if result.rowcount == 0:
            _err("规则不存在或无权限", 404)
        await db.commit()
        return _ok({"id": rule_id, "message": "规则已停用"})
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("delete_promotion_rule_db_error", error=str(exc), exc_info=True)
        _err("规则停用失败", 500)


@router.post("/calculate")
async def calculate_promotions(
    request: Request,
    body: CalculateRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    结账时计算适用促销规则，返回折扣明细。

    三条硬约束：毛利底线 — 折扣后毛利率 ≥ gross_margin_threshold_pct。
    互斥规则：同 exclusion_group 中取 priority 最高（数字最小）的规则生效。
    叠加规则：stack_allowed=False 的规则不与其他规则叠加（取最大优惠）。
    """
    tenant_id = _get_tenant_id(request)
    await _ensure_tables(db)
    await _set_rls(db, tenant_id)

    order_time = body.order_time or datetime.now(timezone.utc)
    original_total_fen = sum(it.unit_price_fen * it.qty for it in body.order_items)

    # 1. 查询所有激活规则（按优先级排序）
    try:
        rows = await db.execute(
            text(
                """
                SELECT id, name, promotion_type, exclusion_group, priority,
                       stack_allowed, discount_pct, time_start, time_end, weekdays,
                       item_skus, item_price_fen, buy_sku, gift_sku, gift_qty,
                       full_reduce_threshold_fen, full_reduce_amount_fen,
                       gross_margin_threshold_pct
                FROM promotion_rules_v2
                WHERE tenant_id = :tid
                  AND status = 'active'
                  AND is_deleted = FALSE
                  AND promotion_type != 'VOUCHER_VERIFY'
                  AND (valid_from IS NULL OR valid_from <= NOW())
                  AND (valid_to IS NULL OR valid_to >= NOW())
                ORDER BY priority ASC
                """
            ),
            {"tid": tenant_id},
        )
        all_rules = [dict(r._mapping) for r in rows.fetchall()]
    except SQLAlchemyError as exc:
        logger.error("calculate_promotions_fetch_rules_error", error=str(exc), exc_info=True)
        _err("查询规则失败", 500)

    # 2. 互斥组处理：同组只保留优先级最高（priority最小）的规则
    exclusion_seen: dict[str, bool] = {}
    eligible_rules = []
    for rule in all_rules:
        eg = rule.get("exclusion_group")
        if eg:
            if eg in exclusion_seen:
                continue  # 同组中已有更高优先级的规则
            exclusion_seen[eg] = True
        eligible_rules.append(rule)

    # 3. 计算每条规则的折扣
    applied_discounts = []
    total_discount_fen = 0
    has_non_stackable = False

    for rule in eligible_rules:
        result = _apply_rule(rule, body.order_items, order_time, original_total_fen)
        if result is None:
            continue

        stack_allowed = rule.get("stack_allowed", False)
        if not stack_allowed and has_non_stackable:
            # 已有不可叠加规则生效，跳过
            continue
        if not stack_allowed:
            has_non_stackable = True

        applied_discounts.append(result)
        total_discount_fen += result["discount_fen"]

    # 若有多个非叠加规则，取折扣最大的一个
    non_stackable = [d for d in applied_discounts if not any(
        r["id"] == d["rule_id"] and r.get("stack_allowed") for r in eligible_rules
    )]
    if len(non_stackable) > 1:
        best = max(non_stackable, key=lambda x: x["discount_fen"])
        stackable = [d for d in applied_discounts if d["rule_id"] != best["rule_id"]
                     and any(r["id"] == d["rule_id"] and r.get("stack_allowed")
                             for r in eligible_rules)]
        applied_discounts = [best] + stackable
        total_discount_fen = sum(d["discount_fen"] for d in applied_discounts)

    # 4. 毛利底线硬约束校验
    min_margin_threshold = min(
        (r.get("gross_margin_threshold_pct") or 20 for r in eligible_rules),
        default=20,
    )
    margin_ok, actual_margin = _check_gross_margin(
        body.order_items, total_discount_fen, min_margin_threshold
    )

    if not margin_ok:
        # 毛利不达标：尝试截断折扣直到达标
        logger.warning(
            "promotion_gross_margin_constraint_triggered",
            actual_margin=actual_margin,
            threshold=min_margin_threshold,
            tenant_id=tenant_id,
        )
        # 逐步移除折扣直到毛利达标
        applied_discounts_filtered = []
        acc_discount = 0
        for disc in sorted(applied_discounts, key=lambda x: x["discount_fen"]):
            test_discount = acc_discount + disc["discount_fen"]
            ok_test, margin_test = _check_gross_margin(
                body.order_items, test_discount, min_margin_threshold
            )
            if ok_test:
                applied_discounts_filtered.append(disc)
                acc_discount = test_discount
        applied_discounts = applied_discounts_filtered
        total_discount_fen = acc_discount
        _, actual_margin = _check_gross_margin(
            body.order_items, total_discount_fen, min_margin_threshold
        )

    final_total_fen = original_total_fen - total_discount_fen

    return _ok({
        "original_total_fen": original_total_fen,
        "total_discount_fen": total_discount_fen,
        "final_total_fen": final_total_fen,
        "applied_rules": applied_discounts,
        "gross_margin_pct": actual_margin,
        "gross_margin_threshold_pct": min_margin_threshold,
        "margin_constraint_passed": margin_ok,
    })


@router.post("/voucher/verify")
async def verify_voucher(
    request: Request,
    body: VoucherVerifyRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    团购券/美团券核销验证。
    1. 查询 promotion_rules_v2 中 VOUCHER_VERIFY 类型的有效规则
    2. 检查券码是否已使用
    3. 返回验证结果和面值
    """
    tenant_id = _get_tenant_id(request)
    await _ensure_tables(db)
    await _set_rls(db, tenant_id)

    voucher_code = body.voucher_code.strip()
    if not voucher_code:
        _err("券码不能为空")

    try:
        # 查找是否已核销过
        existing = await db.execute(
            text(
                """
                SELECT id, is_used, used_at, face_value_fen
                FROM promotion_voucher_logs
                WHERE tenant_id = :tid
                  AND voucher_code = :code
                ORDER BY verified_at DESC
                LIMIT 1
                """
            ),
            {"tid": tenant_id, "code": voucher_code},
        )
        existing_row = existing.fetchone()
        if existing_row and existing_row.is_used:
            return _ok({
                "valid": False,
                "reason": "券码已使用",
                "used_at": existing_row.used_at.isoformat() if existing_row.used_at else None,
            })

        # 查找激活的 VOUCHER_VERIFY 规则
        rule_rows = await db.execute(
            text(
                """
                SELECT id, name, voucher_platform, voucher_face_value_fen, voucher_cost_fen
                FROM promotion_rules_v2
                WHERE tenant_id = :tid
                  AND status = 'active'
                  AND is_deleted = FALSE
                  AND promotion_type = 'VOUCHER_VERIFY'
                  AND (valid_from IS NULL OR valid_from <= NOW())
                  AND (valid_to IS NULL OR valid_to >= NOW())
                ORDER BY priority ASC
                LIMIT 1
                """
            ),
            {"tid": tenant_id},
        )
        rule_row = rule_rows.fetchone()
        if not rule_row:
            return _ok({
                "valid": False,
                "reason": "无可用的团购券核销规则",
            })

        face_value_fen = rule_row.voucher_face_value_fen or 0

        # 记录验证日志（未标记为已使用，下单后再标记）
        log_id = uuid.uuid4()
        await db.execute(
            text(
                """
                INSERT INTO promotion_voucher_logs (
                    id, tenant_id, rule_id, voucher_code, order_id,
                    store_id, is_used, face_value_fen
                ) VALUES (
                    :id, :tid, :rule_id, :code, :order_id,
                    :store_id, FALSE, :face_value_fen
                )
                ON CONFLICT DO NOTHING
                """
            ),
            {
                "id": log_id,
                "tid": tenant_id,
                "rule_id": rule_row.id,
                "code": voucher_code,
                "order_id": body.order_id,
                "store_id": body.store_id,
                "face_value_fen": face_value_fen,
            },
        )
        await db.commit()

        return _ok({
            "valid": True,
            "voucher_code": voucher_code,
            "rule_id": str(rule_row.id),
            "rule_name": rule_row.name,
            "platform": rule_row.voucher_platform,
            "face_value_fen": face_value_fen,
            "face_value_yuan": face_value_fen / 100,
            "log_id": str(log_id),
        })
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("verify_voucher_db_error", error=str(exc), exc_info=True)
        _err("券码验证失败", 500)


@router.get("/effect-report")
async def promotion_effect_report(
    request: Request,
    start_date: Optional[str] = Query(default=None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(default=None, description="结束日期 YYYY-MM-DD"),
    promotion_type: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    促销效果报表：各规则的触发次数、总折扣金额、平均折扣。
    数据来源：未来接入 events 表的 DISCOUNT.APPLIED 事件；
    当前版本从 promotion_voucher_logs 统计券码核销数据，规则维度统计占位。
    """
    tenant_id = _get_tenant_id(request)
    await _ensure_tables(db)
    await _set_rls(db, tenant_id)

    try:
        # 券码核销统计
        voucher_stats = await db.execute(
            text(
                """
                SELECT
                    r.id AS rule_id,
                    r.name AS rule_name,
                    r.promotion_type,
                    COUNT(vl.id) AS total_uses,
                    SUM(vl.face_value_fen) AS total_discount_fen,
                    AVG(vl.face_value_fen)::INTEGER AS avg_discount_fen
                FROM promotion_rules_v2 r
                LEFT JOIN promotion_voucher_logs vl
                    ON vl.rule_id = r.id AND vl.is_used = TRUE
                WHERE r.tenant_id = :tid
                  AND r.is_deleted = FALSE
                  AND (:ptype IS NULL OR r.promotion_type = :ptype)
                  AND (:start_date IS NULL OR vl.used_at >= :start_date::date OR vl.used_at IS NULL)
                  AND (:end_date IS NULL OR vl.used_at <= :end_date::date + interval '1 day' OR vl.used_at IS NULL)
                GROUP BY r.id, r.name, r.promotion_type
                ORDER BY total_uses DESC NULLS LAST
                """
            ),
            {
                "tid": tenant_id,
                "ptype": promotion_type,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        rows = [dict(r._mapping) for r in voucher_stats.fetchall()]
        for row in rows:
            row["rule_id"] = str(row["rule_id"])
            row["total_discount_fen"] = row["total_discount_fen"] or 0
            row["avg_discount_fen"] = row["avg_discount_fen"] or 0
            row["total_uses"] = row["total_uses"] or 0

        return _ok({
            "items": rows,
            "period": {"start_date": start_date, "end_date": end_date},
            "note": "规则触发次数将在 events 表 DISCOUNT.APPLIED 事件接入后完整统计",
        })
    except SQLAlchemyError as exc:
        logger.error("promotion_effect_report_db_error", error=str(exc), exc_info=True)
        _err("报表查询失败", 500)
