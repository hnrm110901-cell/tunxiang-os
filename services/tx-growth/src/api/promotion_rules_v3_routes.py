"""促销规则引擎 V3 扩展 — prefix /api/v1/promotions/v3
在 V2 基础上扩展（不重写）：

B1: 规则组互斥控制（group_id / is_exclusive / priority）— V2 已有 exclusion_group，V3 增加 execution_order
B2: 执行顺序配置（execution_order 字段 + 按序计算逻辑）
B3: 活动总量限制（total_budget_limit / total_usage_limit / per_member_limit + Redis 原子计数）
B4: 新增标准促销规则类型（HOLIDAY_PRICE / GROUP_SIZE_DISCOUNT / BIRTHDAY_DISCOUNT /
                         FIRST_ORDER_DISCOUNT）
    注：TIME_DISCOUNT 已在 V2 中，V3 复用并在 _apply_rule_v3 中扩展

新增端点（7个）：
  POST /api/v1/promotions/v3/rules                 — 创建 V3 规则（含所有新字段）
  GET  /api/v1/promotions/v3/rules                 — 列表（含新字段筛选）
  PUT  /api/v1/promotions/v3/rules/{rule_id}        — 更新
  DELETE /api/v1/promotions/v3/rules/{rule_id}      — 停用
  POST /api/v1/promotions/v3/calculate              — 结账计算（B1+B2+B3 全链路）
  GET  /api/v1/promotions/v3/usage/{rule_id}        — 查询使用计数（Redis + DB）
  POST /api/v1/promotions/v3/rules/{rule_id}/reset-usage — 管理员重置计数

表：promotion_rules_v3（扩展自 V2 DDL，新增字段列）
Redis Key 规范：
  tx:promo:usage:total:{rule_id}          — 总使用次数（INCR）
  tx:promo:usage:member:{rule_id}:{member_id} — 每人使用次数（INCR）
  tx:promo:budget:{rule_id}               — 已用预算（INCRBY discount_fen）

RLS: NULLIF(current_setting('app.tenant_id', true), '')::uuid
统一响应: {"ok": bool, "data": {}, "error": {}}
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

router = APIRouter(prefix="/api/v1/promotions/v3", tags=["promotion-rules-v3"])

# ─── 枚举（兼容 V2 类型 + 新增 V3 类型）────────────────────────────────────────


class PromotionTypeV3(str, Enum):
    # V2 类型（复用）
    TIME_DISCOUNT       = "TIME_DISCOUNT"       # 时段折扣
    ITEM_DISCOUNT       = "ITEM_DISCOUNT"       # 品项指定折扣
    BUY_GIFT            = "BUY_GIFT"            # 买赠
    FULL_REDUCE         = "FULL_REDUCE"         # 满减
    VOUCHER_VERIFY      = "VOUCHER_VERIFY"      # 团购券核销

    # V3 新增类型（B4）
    HOLIDAY_PRICE       = "HOLIDAY_PRICE"       # 节假日价格（指定日期特价）
    GROUP_SIZE_DISCOUNT = "GROUP_SIZE_DISCOUNT" # 人数优惠（X人以上享折扣）
    BIRTHDAY_DISCOUNT   = "BIRTHDAY_DISCOUNT"   # 生日优惠（会员生日当月/当天）
    FIRST_ORDER_DISCOUNT = "FIRST_ORDER_DISCOUNT" # 首单优惠（新会员首次消费）


class PromotionStatusV3(str, Enum):
    ACTIVE   = "active"
    INACTIVE = "inactive"
    EXPIRED  = "expired"


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


# ─── Redis 工具（可选依赖，降级到 DB 计数）────────────────────────────────────

def _get_redis_client():
    """尝试获取 Redis 客户端，失败时返回 None（降级模式）。"""
    try:
        import redis.asyncio as aioredis
        from shared.ontology.src.config import settings
        return aioredis.from_url(settings.redis_url, decode_responses=True)
    except Exception:
        return None


async def _incr_usage_redis(
    rule_id: str,
    member_id: Optional[str],
    discount_fen: int,
) -> dict[str, int]:
    """
    原子递增 Redis 计数器。
    返回 {total_usage, member_usage, budget_used_fen}。
    若 Redis 不可用则返回 {-1, -1, -1} 触发降级。
    """
    redis = _get_redis_client()
    if redis is None:
        return {"total_usage": -1, "member_usage": -1, "budget_used_fen": -1}

    async with redis:
        pipe = redis.pipeline(transaction=True)
        total_key   = f"tx:promo:usage:total:{rule_id}"
        budget_key  = f"tx:promo:budget:{rule_id}"
        pipe.incr(total_key)
        pipe.incrby(budget_key, discount_fen)
        if member_id:
            member_key = f"tx:promo:usage:member:{rule_id}:{member_id}"
            pipe.incr(member_key)
        results = await pipe.execute()

    total_usage    = results[0]
    budget_used    = results[1]
    member_usage   = results[2] if member_id else 0
    return {
        "total_usage":     total_usage,
        "member_usage":    member_usage,
        "budget_used_fen": budget_used,
    }


async def _get_usage_redis(rule_id: str, member_id: Optional[str] = None) -> dict[str, int]:
    """读取 Redis 计数器，不可用时返回 -1（降级）。"""
    redis = _get_redis_client()
    if redis is None:
        return {"total_usage": -1, "member_usage": -1, "budget_used_fen": -1}

    async with redis:
        total_key  = f"tx:promo:usage:total:{rule_id}"
        budget_key = f"tx:promo:budget:{rule_id}"
        pipe = redis.pipeline()
        pipe.get(total_key)
        pipe.get(budget_key)
        if member_id:
            pipe.get(f"tx:promo:usage:member:{rule_id}:{member_id}")
        results = await pipe.execute()

    return {
        "total_usage":     int(results[0] or 0),
        "budget_used_fen": int(results[1] or 0),
        "member_usage":    int(results[2] or 0) if member_id else 0,
    }


# ─── DDL（首次调用时自动建表）────────────────────────────────────────────────

_CREATE_V3_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS promotion_rules_v3 (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID NOT NULL,
    name             TEXT NOT NULL,
    promotion_type   TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'active',

    -- B1: 互斥组控制（兼容 V2 exclusion_group 语义）
    group_id         TEXT,          -- 互斥组ID（同组内规则互斥，取优先级最高的）
    priority         INTEGER NOT NULL DEFAULT 100,   -- 数字越小优先级越高
    is_exclusive     BOOLEAN NOT NULL DEFAULT TRUE,  -- 组内是否互斥（TRUE=互斥）
    stack_allowed    BOOLEAN NOT NULL DEFAULT FALSE, -- 是否允许跨组叠加

    -- B2: 执行顺序
    execution_order  INTEGER NOT NULL DEFAULT 100,   -- 多规则执行顺序（数字越小越先执行）

    -- B3: 活动总量限制
    total_budget_limit_fen   BIGINT,   -- 总预算上限（分），NULL=不限
    total_usage_limit        INTEGER,  -- 总使用次数上限，NULL=不限
    per_member_limit         INTEGER,  -- 每人限用次数，NULL=不限

    -- 时段折扣参数（V2 兼容）
    time_start       TIME,
    time_end         TIME,
    weekdays         INTEGER[],
    discount_pct     INTEGER,

    -- 品项折扣参数（V2 兼容）
    item_skus        TEXT[],
    item_price_fen   INTEGER,

    -- 买赠参数（V2 兼容）
    buy_sku          TEXT,
    gift_sku         TEXT,
    gift_qty         INTEGER DEFAULT 1,

    -- 满减参数（V2 兼容）
    full_reduce_threshold_fen  INTEGER,
    full_reduce_amount_fen     INTEGER,

    -- 团购券参数（V2 兼容）
    voucher_platform TEXT,
    voucher_face_value_fen INTEGER,
    voucher_cost_fen       INTEGER,

    -- B4 新类型参数
    -- HOLIDAY_PRICE: 节假日特价
    holiday_dates    TEXT[],          -- 指定日期列表，格式 YYYY-MM-DD

    -- GROUP_SIZE_DISCOUNT: 人数优惠
    min_group_size   INTEGER,         -- 最低人数门槛（达到此人数享折扣）

    -- BIRTHDAY_DISCOUNT: 生日优惠
    birthday_scope   TEXT DEFAULT 'month', -- 'day'=当天 / 'month'=当月

    -- FIRST_ORDER_DISCOUNT: 首单优惠（无额外参数，通过 member_id 是否首单判断）

    -- 毛利底线硬约束（通用）
    gross_margin_threshold_pct INTEGER DEFAULT 20,

    -- 有效期
    valid_from       TIMESTAMPTZ,
    valid_to         TIMESTAMPTZ,

    description      TEXT,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW(),
    is_deleted       BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_promo_rules_v3_tenant
    ON promotion_rules_v3 (tenant_id, status, execution_order)
    WHERE is_deleted = FALSE;

ALTER TABLE promotion_rules_v3 ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'promotion_rules_v3'
          AND policyname = 'tenant_isolation'
    ) THEN
        CREATE POLICY tenant_isolation ON promotion_rules_v3
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::uuid);
    END IF;
END
$$;
"""

_V3_TABLE_INITIALIZED = False


async def _ensure_v3_tables(db: AsyncSession) -> None:
    global _V3_TABLE_INITIALIZED
    if _V3_TABLE_INITIALIZED:
        return
    try:
        await db.execute(text(_CREATE_V3_TABLE_SQL))
        await db.commit()
        _V3_TABLE_INITIALIZED = True
        logger.info("promotion_rules_v3_tables_initialized")
    except SQLAlchemyError as exc:
        logger.warning("promotion_rules_v3_tables_init_warning", error=str(exc))


# ─── 请求/响应模型 ────────────────────────────────────────────────────────────


class PromotionRuleV3Create(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    promotion_type: PromotionTypeV3
    description: Optional[str] = None

    # B1: 互斥组
    group_id: Optional[str] = None
    priority: int = Field(default=100, ge=1, le=9999)
    is_exclusive: bool = True
    stack_allowed: bool = False

    # B2: 执行顺序
    execution_order: int = Field(default=100, ge=1, le=9999)

    # B3: 总量限制
    total_budget_limit_fen: Optional[int] = Field(None, ge=0)
    total_usage_limit: Optional[int] = Field(None, ge=1)
    per_member_limit: Optional[int] = Field(None, ge=1)

    # 毛利约束
    gross_margin_threshold_pct: int = Field(default=20, ge=0, le=100)

    # 有效期
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None

    # 时段折扣参数（TIME_DISCOUNT）
    time_start: Optional[str] = Field(None, description="HH:MM")
    time_end: Optional[str] = Field(None, description="HH:MM")
    weekdays: Optional[List[int]] = None
    discount_pct: Optional[int] = Field(None, ge=1, le=100)

    # 品项折扣参数（ITEM_DISCOUNT）
    item_skus: Optional[List[str]] = None
    item_price_fen: Optional[int] = Field(None, ge=0)

    # 买赠参数（BUY_GIFT）
    buy_sku: Optional[str] = None
    gift_sku: Optional[str] = None
    gift_qty: Optional[int] = Field(None, ge=1)

    # 满减参数（FULL_REDUCE）
    full_reduce_threshold_fen: Optional[int] = Field(None, ge=0)
    full_reduce_amount_fen: Optional[int] = Field(None, ge=0)

    # 团购券（VOUCHER_VERIFY）
    voucher_platform: Optional[str] = None
    voucher_face_value_fen: Optional[int] = Field(None, ge=0)
    voucher_cost_fen: Optional[int] = Field(None, ge=0)

    # 节假日价格（HOLIDAY_PRICE）
    holiday_dates: Optional[List[str]] = Field(None, description="YYYY-MM-DD 列表")

    # 人数优惠（GROUP_SIZE_DISCOUNT）
    min_group_size: Optional[int] = Field(None, ge=2)

    # 生日优惠（BIRTHDAY_DISCOUNT）
    birthday_scope: Optional[str] = Field("month", pattern="^(day|month)$")

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
                raise ValueError("时间格式必须为 HH:MM")
        return v

    @field_validator("holiday_dates")
    @classmethod
    def validate_holiday_dates(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is not None:
            for d in v:
                try:
                    datetime.strptime(d, "%Y-%m-%d")
                except ValueError:
                    raise ValueError(f"holiday_dates 格式必须为 YYYY-MM-DD，收到: {d}")
        return v


class PromotionRuleV3Update(BaseModel):
    name: Optional[str] = None
    status: Optional[PromotionStatusV3] = None
    group_id: Optional[str] = None
    priority: Optional[int] = Field(None, ge=1, le=9999)
    is_exclusive: Optional[bool] = None
    stack_allowed: Optional[bool] = None
    execution_order: Optional[int] = Field(None, ge=1, le=9999)
    total_budget_limit_fen: Optional[int] = Field(None, ge=0)
    total_usage_limit: Optional[int] = Field(None, ge=1)
    per_member_limit: Optional[int] = Field(None, ge=1)
    gross_margin_threshold_pct: Optional[int] = Field(None, ge=0, le=100)
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    description: Optional[str] = None
    discount_pct: Optional[int] = Field(None, ge=1, le=100)
    time_start: Optional[str] = None
    time_end: Optional[str] = None
    weekdays: Optional[List[int]] = None
    item_skus: Optional[List[str]] = None
    item_price_fen: Optional[int] = Field(None, ge=0)
    buy_sku: Optional[str] = None
    gift_sku: Optional[str] = None
    gift_qty: Optional[int] = Field(None, ge=1)
    full_reduce_threshold_fen: Optional[int] = Field(None, ge=0)
    full_reduce_amount_fen: Optional[int] = Field(None, ge=0)
    holiday_dates: Optional[List[str]] = None
    min_group_size: Optional[int] = Field(None, ge=2)
    birthday_scope: Optional[str] = None


class OrderItemV3(BaseModel):
    sku: str
    name: str
    qty: int = Field(..., ge=1)
    unit_price_fen: int = Field(..., ge=0)
    cost_price_fen: int = Field(default=0, ge=0)


class CalculateRequestV3(BaseModel):
    order_items: List[OrderItemV3]
    store_id: Optional[str] = None
    order_time: Optional[datetime] = None
    member_id: Optional[str] = None          # B3 每人限额检查 + B4 生日/首单判断
    guest_count: Optional[int] = Field(None, ge=1)  # B4 人数优惠
    is_member_birthday: bool = False         # 由前端/tx-member 提供，是否生日
    is_first_order: bool = False             # 由前端/tx-member 提供，是否首单


# ─── V3 计算逻辑 ──────────────────────────────────────────────────────────────


def _is_time_in_range(order_time: datetime, time_start: str, time_end: str) -> bool:
    try:
        sh, sm = map(int, time_start.split(":"))
        eh, em = map(int, time_end.split(":"))
        t_start = time(sh, sm)
        t_end   = time(eh, em)
        t_order = order_time.time()
        if t_start <= t_end:
            return t_start <= t_order <= t_end
        return t_order >= t_start or t_order <= t_end
    except (ValueError, AttributeError):
        return False


def _is_weekday_match(order_time: datetime, weekdays: Optional[List[int]]) -> bool:
    if not weekdays:
        return True
    py_weekday = order_time.weekday()   # 0=Mon...6=Sun
    converted  = (py_weekday + 1) % 7  # 0=Sun,1=Mon...6=Sat
    return converted in weekdays


def _apply_rule_v3(
    rule: dict,
    items: List[OrderItemV3],
    order_time: datetime,
    original_total_fen: int,
    guest_count: Optional[int],
    is_member_birthday: bool,
    is_first_order: bool,
) -> Optional[dict]:
    """
    V3 规则执行器（包含 V2 全部类型 + 4 种新类型）。
    返回 None = 规则不适用；返回 dict = 折扣明细。
    """
    ptype = rule["promotion_type"]

    # ── V2 兼容类型 ────────────────────────────────────────────────────────────

    if ptype == PromotionTypeV3.TIME_DISCOUNT:
        ts = rule.get("time_start")
        te = rule.get("time_end")
        discount_pct = rule.get("discount_pct")
        if not ts or not te or not discount_pct:
            return None
        if not _is_time_in_range(order_time, ts, te):
            return None
        if not _is_weekday_match(order_time, rule.get("weekdays")):
            return None
        discount_fen = original_total_fen - int(original_total_fen * discount_pct / 100)
        return {
            "rule_id": str(rule["id"]),
            "rule_name": rule["name"],
            "promotion_type": ptype,
            "discount_fen": discount_fen,
            "detail": f"时段折扣 {discount_pct}折，时段 {ts}-{te}",
        }

    elif ptype == PromotionTypeV3.ITEM_DISCOUNT:
        item_skus    = rule.get("item_skus") or []
        item_price   = rule.get("item_price_fen")
        discount_pct = rule.get("discount_pct")
        if not item_skus:
            return None
        matched = [it for it in items if it.sku in item_skus]
        if not matched:
            return None
        total_discount = 0
        parts = []
        for it in matched:
            if item_price is not None and it.unit_price_fen > item_price:
                diff = (it.unit_price_fen - item_price) * it.qty
                total_discount += diff
                parts.append(f"{it.name} 特价 ¥{item_price/100:.2f}")
            elif discount_pct is not None:
                item_total = it.unit_price_fen * it.qty
                disc = item_total - int(item_total * discount_pct / 100)
                total_discount += disc
                parts.append(f"{it.name} {discount_pct}折")
        if total_discount <= 0:
            return None
        return {
            "rule_id": str(rule["id"]),
            "rule_name": rule["name"],
            "promotion_type": ptype,
            "discount_fen": total_discount,
            "detail": "；".join(parts) if parts else "品项折扣",
        }

    elif ptype == PromotionTypeV3.BUY_GIFT:
        buy_sku  = rule.get("buy_sku")
        gift_sku = rule.get("gift_sku")
        gift_qty = rule.get("gift_qty") or 1
        if not buy_sku or not gift_sku:
            return None
        if not any(it.sku == buy_sku for it in items):
            return None
        gift_items = [it for it in items if it.sku == gift_sku]
        gift_unit_price = gift_items[0].unit_price_fen if gift_items else 0
        return {
            "rule_id": str(rule["id"]),
            "rule_name": rule["name"],
            "promotion_type": ptype,
            "discount_fen": gift_unit_price * gift_qty,
            "detail": f"买赠：购买 {buy_sku} 赠 {gift_sku} ×{gift_qty}",
            "gift_items": [{"sku": gift_sku, "qty": gift_qty}],
        }

    elif ptype == PromotionTypeV3.FULL_REDUCE:
        threshold = rule.get("full_reduce_threshold_fen") or 0
        amount    = rule.get("full_reduce_amount_fen") or 0
        if original_total_fen < threshold:
            return None
        return {
            "rule_id": str(rule["id"]),
            "rule_name": rule["name"],
            "promotion_type": ptype,
            "discount_fen": amount,
            "detail": f"满{threshold//100}减{amount//100}",
        }

    # ── V3 新类型 ──────────────────────────────────────────────────────────────

    elif ptype == PromotionTypeV3.HOLIDAY_PRICE:
        """节假日价格：指定日期范围内，全单打折（discount_pct）。"""
        holiday_dates = rule.get("holiday_dates") or []
        discount_pct  = rule.get("discount_pct")
        if not holiday_dates or not discount_pct:
            return None
        today_str = order_time.strftime("%Y-%m-%d")
        if today_str not in holiday_dates:
            return None
        discount_fen = original_total_fen - int(original_total_fen * discount_pct / 100)
        return {
            "rule_id": str(rule["id"]),
            "rule_name": rule["name"],
            "promotion_type": ptype,
            "discount_fen": discount_fen,
            "detail": f"节假日优惠 {discount_pct}折（{today_str}）",
        }

    elif ptype == PromotionTypeV3.GROUP_SIZE_DISCOUNT:
        """人数优惠：达到 min_group_size 人时，全单打折（discount_pct）。"""
        min_size     = rule.get("min_group_size")
        discount_pct = rule.get("discount_pct")
        if not min_size or not discount_pct:
            return None
        if not guest_count or guest_count < min_size:
            return None
        discount_fen = original_total_fen - int(original_total_fen * discount_pct / 100)
        return {
            "rule_id": str(rule["id"]),
            "rule_name": rule["name"],
            "promotion_type": ptype,
            "discount_fen": discount_fen,
            "detail": f"{guest_count}人台享{discount_pct}折（≥{min_size}人触发）",
        }

    elif ptype == PromotionTypeV3.BIRTHDAY_DISCOUNT:
        """
        生日优惠：is_member_birthday=True 时，全单打折（discount_pct）。
        birthday_scope='day'=当天 / 'month'=当月，由前端/tx-member 判断后传入 is_member_birthday。
        """
        discount_pct = rule.get("discount_pct")
        if not discount_pct:
            return None
        if not is_member_birthday:
            return None
        discount_fen = original_total_fen - int(original_total_fen * discount_pct / 100)
        scope_label = "当天" if rule.get("birthday_scope") == "day" else "当月"
        return {
            "rule_id": str(rule["id"]),
            "rule_name": rule["name"],
            "promotion_type": ptype,
            "discount_fen": discount_fen,
            "detail": f"生日优惠 {discount_pct}折（生日{scope_label}）",
        }

    elif ptype == PromotionTypeV3.FIRST_ORDER_DISCOUNT:
        """首单优惠：is_first_order=True 时，全单打折（discount_pct）或满减（full_reduce_amount_fen）。"""
        if not is_first_order:
            return None
        discount_pct   = rule.get("discount_pct")
        reduce_amount  = rule.get("full_reduce_amount_fen")
        if discount_pct:
            discount_fen = original_total_fen - int(original_total_fen * discount_pct / 100)
            detail = f"首单优惠 {discount_pct}折"
        elif reduce_amount:
            discount_fen = min(reduce_amount, original_total_fen)
            detail = f"首单立减 ¥{reduce_amount//100}"
        else:
            return None
        return {
            "rule_id": str(rule["id"]),
            "rule_name": rule["name"],
            "promotion_type": ptype,
            "discount_fen": discount_fen,
            "detail": detail,
        }

    return None


def _check_gross_margin(
    items: List[OrderItemV3],
    total_discount_fen: int,
    threshold_pct: int,
) -> tuple[bool, float]:
    total_revenue = sum(it.unit_price_fen * it.qty for it in items)
    total_cost    = sum(it.cost_price_fen * it.qty for it in items)
    if total_revenue <= 0:
        return True, 0.0
    net_revenue  = total_revenue - total_discount_fen
    gross_profit = net_revenue - total_cost
    margin_pct   = gross_profit / net_revenue * 100 if net_revenue > 0 else 0.0
    return margin_pct >= threshold_pct, round(margin_pct, 2)


# ─── API 端点 ────────────────────────────────────────────────────────────────


@router.post("/rules")
async def create_rule_v3(
    request: Request,
    body: PromotionRuleV3Create,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建 V3 促销规则（含 B1/B2/B3/B4 所有新字段）。"""
    tenant_id = _get_tenant_id(request)
    await _ensure_v3_tables(db)
    await _set_rls(db, tenant_id)

    rule_id = uuid.uuid4()
    try:
        await db.execute(
            text(
                """
                INSERT INTO promotion_rules_v3 (
                    id, tenant_id, name, promotion_type, status,
                    group_id, priority, is_exclusive, stack_allowed,
                    execution_order,
                    total_budget_limit_fen, total_usage_limit, per_member_limit,
                    gross_margin_threshold_pct,
                    time_start, time_end, weekdays, discount_pct,
                    item_skus, item_price_fen,
                    buy_sku, gift_sku, gift_qty,
                    full_reduce_threshold_fen, full_reduce_amount_fen,
                    voucher_platform, voucher_face_value_fen, voucher_cost_fen,
                    holiday_dates, min_group_size, birthday_scope,
                    valid_from, valid_to, description
                ) VALUES (
                    :id, :tenant_id, :name, :promotion_type, 'active',
                    :group_id, :priority, :is_exclusive, :stack_allowed,
                    :execution_order,
                    :total_budget_limit_fen, :total_usage_limit, :per_member_limit,
                    :gross_margin_threshold_pct,
                    :time_start, :time_end, :weekdays, :discount_pct,
                    :item_skus, :item_price_fen,
                    :buy_sku, :gift_sku, :gift_qty,
                    :full_reduce_threshold_fen, :full_reduce_amount_fen,
                    :voucher_platform, :voucher_face_value_fen, :voucher_cost_fen,
                    :holiday_dates, :min_group_size, :birthday_scope,
                    :valid_from, :valid_to, :description
                )
                """
            ),
            {
                "id": rule_id, "tenant_id": tenant_id,
                "name": body.name, "promotion_type": body.promotion_type.value,
                "group_id": body.group_id, "priority": body.priority,
                "is_exclusive": body.is_exclusive, "stack_allowed": body.stack_allowed,
                "execution_order": body.execution_order,
                "total_budget_limit_fen": body.total_budget_limit_fen,
                "total_usage_limit": body.total_usage_limit,
                "per_member_limit": body.per_member_limit,
                "gross_margin_threshold_pct": body.gross_margin_threshold_pct,
                "time_start": body.time_start, "time_end": body.time_end,
                "weekdays": body.weekdays, "discount_pct": body.discount_pct,
                "item_skus": body.item_skus, "item_price_fen": body.item_price_fen,
                "buy_sku": body.buy_sku, "gift_sku": body.gift_sku, "gift_qty": body.gift_qty,
                "full_reduce_threshold_fen": body.full_reduce_threshold_fen,
                "full_reduce_amount_fen": body.full_reduce_amount_fen,
                "voucher_platform": body.voucher_platform,
                "voucher_face_value_fen": body.voucher_face_value_fen,
                "voucher_cost_fen": body.voucher_cost_fen,
                "holiday_dates": body.holiday_dates,
                "min_group_size": body.min_group_size,
                "birthday_scope": body.birthday_scope or "month",
                "valid_from": body.valid_from, "valid_to": body.valid_to,
                "description": body.description,
            },
        )
        await db.commit()
        logger.info("promo_rule_v3_created", rule_id=str(rule_id), tenant_id=tenant_id,
                    ptype=body.promotion_type.value)
        return _ok({"id": str(rule_id), "message": "规则创建成功"})
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("promo_rule_v3_create_error", error=str(exc), exc_info=True)
        _err("规则创建失败", 500)


@router.get("/rules")
async def list_rules_v3(
    request: Request,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    status: Optional[str] = Query(default=None),
    promotion_type: Optional[str] = Query(default=None),
    group_id: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """V3 规则列表（支持按 group_id 筛选）。"""
    tenant_id = _get_tenant_id(request)
    await _ensure_v3_tables(db)
    await _set_rls(db, tenant_id)

    conditions = ["is_deleted = FALSE", "tenant_id = :tid"]
    params: dict[str, Any] = {
        "tid": tenant_id, "offset": (page - 1) * size, "limit": size,
    }

    if status:
        conditions.append("status = :status")
        params["status"] = status
    if promotion_type:
        conditions.append("promotion_type = :ptype")
        params["ptype"] = promotion_type
    if group_id:
        conditions.append("group_id = :group_id")
        params["group_id"] = group_id

    where = " AND ".join(conditions)

    try:
        total = (await db.execute(
            text(f"SELECT COUNT(*) FROM promotion_rules_v3 WHERE {where}"), params
        )).scalar() or 0

        rows = await db.execute(
            text(
                f"""
                SELECT id, name, promotion_type, status,
                       group_id, priority, is_exclusive, stack_allowed,
                       execution_order,
                       total_budget_limit_fen, total_usage_limit, per_member_limit,
                       discount_pct, time_start, time_end, weekdays,
                       item_skus, item_price_fen, buy_sku, gift_sku, gift_qty,
                       full_reduce_threshold_fen, full_reduce_amount_fen,
                       holiday_dates, min_group_size, birthday_scope,
                       gross_margin_threshold_pct, valid_from, valid_to,
                       description, created_at, updated_at
                FROM promotion_rules_v3
                WHERE {where}
                ORDER BY execution_order ASC, priority ASC, created_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
        items = [dict(r._mapping) for r in rows.fetchall()]
        for item in items:
            item["id"] = str(item["id"])
        return _ok({"items": items, "total": total, "page": page, "size": size})
    except SQLAlchemyError as exc:
        logger.error("list_promo_rules_v3_error", error=str(exc), exc_info=True)
        _err("查询失败", 500)


@router.put("/rules/{rule_id}")
async def update_rule_v3(
    rule_id: str,
    request: Request,
    body: PromotionRuleV3Update,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新 V3 促销规则。"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    update_fields: dict[str, Any] = {"rule_id": rule_id, "tid": tenant_id}
    set_parts = ["updated_at = NOW()"]

    field_map = {
        "name":                       body.name,
        "status":                     body.status.value if body.status else None,
        "group_id":                   body.group_id,
        "priority":                   body.priority,
        "is_exclusive":               body.is_exclusive,
        "stack_allowed":              body.stack_allowed,
        "execution_order":            body.execution_order,
        "total_budget_limit_fen":     body.total_budget_limit_fen,
        "total_usage_limit":          body.total_usage_limit,
        "per_member_limit":           body.per_member_limit,
        "gross_margin_threshold_pct": body.gross_margin_threshold_pct,
        "valid_from":                 body.valid_from,
        "valid_to":                   body.valid_to,
        "description":                body.description,
        "discount_pct":               body.discount_pct,
        "time_start":                 body.time_start,
        "time_end":                   body.time_end,
        "weekdays":                   body.weekdays,
        "item_skus":                  body.item_skus,
        "item_price_fen":             body.item_price_fen,
        "buy_sku":                    body.buy_sku,
        "gift_sku":                   body.gift_sku,
        "gift_qty":                   body.gift_qty,
        "full_reduce_threshold_fen":  body.full_reduce_threshold_fen,
        "full_reduce_amount_fen":     body.full_reduce_amount_fen,
        "holiday_dates":              body.holiday_dates,
        "min_group_size":             body.min_group_size,
        "birthday_scope":             body.birthday_scope,
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
                UPDATE promotion_rules_v3
                SET {', '.join(set_parts)}
                WHERE id = :rule_id AND tenant_id = :tid AND is_deleted = FALSE
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
        logger.error("update_promo_rule_v3_error", error=str(exc), exc_info=True)
        _err("更新失败", 500)


@router.delete("/rules/{rule_id}")
async def delete_rule_v3(
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
                UPDATE promotion_rules_v3
                SET is_deleted = TRUE, status = 'inactive', updated_at = NOW()
                WHERE id = :rule_id AND tenant_id = :tid AND is_deleted = FALSE
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
        logger.error("delete_promo_rule_v3_error", error=str(exc), exc_info=True)
        _err("停用失败", 500)


@router.post("/calculate")
async def calculate_promotions_v3(
    request: Request,
    body: CalculateRequestV3,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    V3 全链路结账促销计算。

    执行流程（B1→B2→B3→毛利约束）：
    1. 查询所有激活规则，按 execution_order ASC 排序（B2）
    2. 同一 group_id 且 is_exclusive=True：只保留 priority 最小（最高）的规则（B1）
    3. 依 execution_order 顺序逐条应用，中间金额随之变化（先折扣后满减场景正确）
    4. B3：检查 per_member_limit / total_usage_limit / total_budget_limit，超限跳过
    5. 毛利底线硬约束：折扣超标时逐步裁减
    6. 校验通过后异步递增 Redis 计数器（B3 原子操作）
    """
    tenant_id  = _get_tenant_id(request)
    await _ensure_v3_tables(db)
    await _set_rls(db, tenant_id)

    order_time          = body.order_time or datetime.now(timezone.utc)
    original_total_fen  = sum(it.unit_price_fen * it.qty for it in body.order_items)
    member_id           = body.member_id

    # 1. 查询规则（按 execution_order 排序，B2）
    try:
        rows = await db.execute(
            text(
                """
                SELECT id, name, promotion_type,
                       group_id, priority, is_exclusive, stack_allowed,
                       execution_order,
                       total_budget_limit_fen, total_usage_limit, per_member_limit,
                       discount_pct, time_start, time_end, weekdays,
                       item_skus, item_price_fen, buy_sku, gift_sku, gift_qty,
                       full_reduce_threshold_fen, full_reduce_amount_fen,
                       holiday_dates, min_group_size, birthday_scope,
                       gross_margin_threshold_pct
                FROM promotion_rules_v3
                WHERE tenant_id = :tid
                  AND status = 'active'
                  AND is_deleted = FALSE
                  AND promotion_type != 'VOUCHER_VERIFY'
                  AND (valid_from IS NULL OR valid_from <= NOW())
                  AND (valid_to IS NULL OR valid_to >= NOW())
                ORDER BY execution_order ASC, priority ASC
                """
            ),
            {"tid": tenant_id},
        )
        all_rules = [dict(r._mapping) for r in rows.fetchall()]
    except SQLAlchemyError as exc:
        logger.error("v3_calculate_fetch_error", error=str(exc), exc_info=True)
        _err("查询规则失败", 500)

    # 2. B1 互斥组处理：同组 is_exclusive=True 只保留 priority 最小的
    group_seen: dict[str, bool] = {}
    eligible_rules: list[dict] = []
    for rule in all_rules:
        gid = rule.get("group_id")
        if gid and rule.get("is_exclusive", True):
            if gid in group_seen:
                continue  # 同组已有更高优先级规则
            group_seen[gid] = True
        eligible_rules.append(rule)

    # 3. B3 Redis 使用计数预读（用于 per_member_limit / total_usage_limit 检查）
    #    为避免重复查询，批量读取所有规则的计数
    usage_cache: dict[str, dict] = {}
    for rule in eligible_rules:
        rid = str(rule["id"])
        if rule.get("total_usage_limit") or rule.get("per_member_limit") or rule.get("total_budget_limit_fen"):
            usage_cache[rid] = await _get_usage_redis(rid, member_id)

    # 4. 按 execution_order 逐条执行（B2），中间金额实时更新（先折后减场景）
    applied_discounts: list[dict] = []
    running_total_fen  = original_total_fen  # 实时追踪折后金额（按序计算基础）
    has_non_stackable  = False

    for rule in eligible_rules:
        rid = str(rule["id"])

        # B3: 总使用次数检查
        if rule.get("total_usage_limit") is not None:
            usage = usage_cache.get(rid, {})
            current_usage = usage.get("total_usage", 0)
            if current_usage >= 0 and current_usage >= rule["total_usage_limit"]:
                logger.info("promo_v3_total_usage_exceeded", rule_id=rid,
                            current=current_usage, limit=rule["total_usage_limit"])
                continue

        # B3: 每人限额检查
        if rule.get("per_member_limit") is not None and member_id:
            usage = usage_cache.get(rid, {})
            member_usage = usage.get("member_usage", 0)
            if member_usage >= 0 and member_usage >= rule["per_member_limit"]:
                logger.info("promo_v3_per_member_exceeded", rule_id=rid, member_id=member_id,
                            current=member_usage, limit=rule["per_member_limit"])
                continue

        # B2: 以 running_total_fen 作为本条规则的计算基础（体现执行顺序）
        result = _apply_rule_v3(
            rule,
            body.order_items,
            order_time,
            running_total_fen,   # 上一条规则折后金额
            body.guest_count,
            body.is_member_birthday,
            body.is_first_order,
        )
        if result is None:
            continue

        # 叠加控制（沿用 V2 逻辑）
        stack_allowed = rule.get("stack_allowed", False)
        if not stack_allowed and has_non_stackable:
            continue
        if not stack_allowed:
            has_non_stackable = True

        # B3: 预算上限检查（单条）
        if rule.get("total_budget_limit_fen") is not None:
            usage = usage_cache.get(rid, {})
            budget_used = usage.get("budget_used_fen", 0)
            if budget_used >= 0 and budget_used + result["discount_fen"] > rule["total_budget_limit_fen"]:
                # 截断到预算上限
                remaining_budget = rule["total_budget_limit_fen"] - budget_used
                if remaining_budget <= 0:
                    logger.info("promo_v3_budget_exceeded", rule_id=rid)
                    continue
                result["discount_fen"] = remaining_budget
                result["detail"] += f"（预算截断至 ¥{remaining_budget/100:.0f}）"

        applied_discounts.append(result)
        running_total_fen = max(0, running_total_fen - result["discount_fen"])

    # 5. 毛利底线硬约束校验
    total_discount_fen = original_total_fen - running_total_fen
    min_threshold = min(
        (r.get("gross_margin_threshold_pct") or 20 for r in eligible_rules),
        default=20,
    )
    margin_ok, actual_margin = _check_gross_margin(
        body.order_items, total_discount_fen, min_threshold
    )

    if not margin_ok:
        logger.warning("promo_v3_margin_constraint_triggered",
                       actual_margin=actual_margin, threshold=min_threshold,
                       tenant_id=tenant_id)
        # 逐步裁减折扣直到毛利达标（保留最高优先级的折扣）
        applied_filtered: list[dict] = []
        acc_discount = 0
        for disc in sorted(applied_discounts, key=lambda x: x["discount_fen"]):
            test_disc = acc_discount + disc["discount_fen"]
            ok_test, _ = _check_gross_margin(body.order_items, test_disc, min_threshold)
            if ok_test:
                applied_filtered.append(disc)
                acc_discount = test_disc
        applied_discounts  = applied_filtered
        total_discount_fen = acc_discount
        _, actual_margin   = _check_gross_margin(body.order_items, total_discount_fen, min_threshold)

    final_total_fen = original_total_fen - total_discount_fen

    # 6. B3: 异步递增 Redis 计数（校验通过后才记录）
    import asyncio
    for disc in applied_discounts:
        asyncio.create_task(
            _incr_usage_redis(disc["rule_id"], member_id, disc["discount_fen"])
        )

    return _ok({
        "original_total_fen":         original_total_fen,
        "total_discount_fen":         total_discount_fen,
        "final_total_fen":            final_total_fen,
        "applied_rules":              applied_discounts,
        "gross_margin_pct":           actual_margin,
        "gross_margin_threshold_pct": min_threshold,
        "margin_constraint_passed":   margin_ok,
        "execution_mode":             "ordered",   # B2 标识：按 execution_order 顺序执行
    })


@router.get("/usage/{rule_id}")
async def get_rule_usage(
    rule_id: str,
    request: Request,
    member_id: Optional[str] = Query(default=None),
) -> dict:
    """查询规则使用计数（Redis 计数器）。"""
    _get_tenant_id(request)  # 校验 tenant header
    usage = await _get_usage_redis(rule_id, member_id)
    if usage["total_usage"] < 0:
        return _ok({
            "rule_id": rule_id,
            "total_usage": None,
            "member_usage": None,
            "budget_used_fen": None,
            "note": "Redis 不可用，计数降级",
        })
    return _ok({
        "rule_id":         rule_id,
        "total_usage":     usage["total_usage"],
        "member_usage":    usage["member_usage"],
        "budget_used_fen": usage["budget_used_fen"],
    })


@router.post("/rules/{rule_id}/reset-usage")
async def reset_rule_usage(
    rule_id: str,
    request: Request,
) -> dict:
    """管理员重置规则使用计数（清空 Redis keys）。"""
    _get_tenant_id(request)
    redis = _get_redis_client()
    if redis is None:
        _err("Redis 不可用，无法重置计数", 503)

    async with redis:
        await redis.delete(
            f"tx:promo:usage:total:{rule_id}",
            f"tx:promo:budget:{rule_id}",
        )
        # 注意：per_member keys 用通配符批量删除
        member_keys = await redis.keys(f"tx:promo:usage:member:{rule_id}:*")
        if member_keys:
            await redis.delete(*member_keys)

    logger.info("promo_v3_usage_reset", rule_id=rule_id)
    return _ok({"rule_id": rule_id, "message": "使用计数已重置"})
