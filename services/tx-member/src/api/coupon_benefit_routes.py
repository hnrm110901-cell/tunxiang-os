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
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/member", tags=["coupon-benefit"])


# ─── Mock 数据 ───────────────────────────────────────────────

_MOCK_COUPONS = [
    {
        "coupon_id": "c001",
        "name": "新客满100减20",
        "type": "full_reduction",
        "threshold_fen": 10000,
        "discount_fen": 2000,
        "discount_rate": None,
        "max_discount_fen": None,
        "status": "active",
        "total_issued": 5000,
        "total_used": 3200,
        "use_rate": 0.64,
        "start_date": "2026-03-01",
        "end_date": "2026-06-30",
        "scope": "all_stores",
        "target_segment": "新客",
        "created_at": "2026-02-28T10:00:00Z",
    },
    {
        "coupon_id": "c002",
        "name": "会员日8折券",
        "type": "discount",
        "threshold_fen": 0,
        "discount_fen": None,
        "discount_rate": 0.8,
        "max_discount_fen": 5000,
        "status": "active",
        "total_issued": 12000,
        "total_used": 8800,
        "use_rate": 0.733,
        "start_date": "2026-01-01",
        "end_date": "2026-12-31",
        "scope": "all_stores",
        "target_segment": "全部会员",
        "created_at": "2025-12-25T10:00:00Z",
    },
    {
        "coupon_id": "c003",
        "name": "午市特惠满50减10",
        "type": "full_reduction",
        "threshold_fen": 5000,
        "discount_fen": 1000,
        "discount_rate": None,
        "max_discount_fen": None,
        "status": "active",
        "total_issued": 8000,
        "total_used": 5600,
        "use_rate": 0.70,
        "start_date": "2026-03-15",
        "end_date": "2026-05-15",
        "scope": "all_stores",
        "target_segment": "午餐党",
        "created_at": "2026-03-10T10:00:00Z",
    },
    {
        "coupon_id": "c004",
        "name": "生日专享免单券",
        "type": "free",
        "threshold_fen": 0,
        "discount_fen": 8800,
        "discount_rate": None,
        "max_discount_fen": 8800,
        "status": "active",
        "total_issued": 1200,
        "total_used": 680,
        "use_rate": 0.567,
        "start_date": "2026-01-01",
        "end_date": "2026-12-31",
        "scope": "all_stores",
        "target_segment": "生日会员",
        "created_at": "2025-12-20T10:00:00Z",
    },
    {
        "coupon_id": "c005",
        "name": "沉默唤醒满80减30",
        "type": "full_reduction",
        "threshold_fen": 8000,
        "discount_fen": 3000,
        "discount_rate": None,
        "max_discount_fen": None,
        "status": "paused",
        "total_issued": 3000,
        "total_used": 450,
        "use_rate": 0.15,
        "start_date": "2026-02-01",
        "end_date": "2026-04-30",
        "scope": "all_stores",
        "target_segment": "沉默预警",
        "created_at": "2026-01-28T10:00:00Z",
    },
    {
        "coupon_id": "c006",
        "name": "抖音专属7折券",
        "type": "discount",
        "threshold_fen": 0,
        "discount_fen": None,
        "discount_rate": 0.7,
        "max_discount_fen": 8000,
        "status": "expired",
        "total_issued": 20000,
        "total_used": 14500,
        "use_rate": 0.725,
        "start_date": "2026-01-15",
        "end_date": "2026-03-15",
        "scope": "selected_stores",
        "target_segment": "抖音新客",
        "created_at": "2026-01-10T10:00:00Z",
    },
]

_MOCK_STORED_VALUE_PLANS = [
    {
        "plan_id": "sv001",
        "name": "充500送50",
        "charge_fen": 50000,
        "gift_fen": 5000,
        "gift_rate": 0.10,
        "status": "active",
        "total_sold": 2800,
        "total_charge_fen": 140000000,
        "start_date": "2026-01-01",
        "end_date": None,
    },
    {
        "plan_id": "sv002",
        "name": "充1000送150",
        "charge_fen": 100000,
        "gift_fen": 15000,
        "gift_rate": 0.15,
        "status": "active",
        "total_sold": 1500,
        "total_charge_fen": 150000000,
        "start_date": "2026-01-01",
        "end_date": None,
    },
    {
        "plan_id": "sv003",
        "name": "充2000送400",
        "charge_fen": 200000,
        "gift_fen": 40000,
        "gift_rate": 0.20,
        "status": "active",
        "total_sold": 680,
        "total_charge_fen": 136000000,
        "start_date": "2026-01-01",
        "end_date": None,
    },
    {
        "plan_id": "sv004",
        "name": "充5000送1200",
        "charge_fen": 500000,
        "gift_fen": 120000,
        "gift_rate": 0.24,
        "status": "active",
        "total_sold": 220,
        "total_charge_fen": 110000000,
        "start_date": "2026-02-01",
        "end_date": None,
    },
]

_MOCK_GIFT_CARDS = [
    {
        "card_id": "gc001",
        "name": "心意卡·200元",
        "face_value_fen": 20000,
        "price_fen": 20000,
        "type": "fixed",
        "status": "active",
        "total_sold": 850,
        "total_redeemed": 620,
        "design_theme": "经典红",
        "created_at": "2026-01-01T10:00:00Z",
    },
    {
        "card_id": "gc002",
        "name": "心意卡·500元",
        "face_value_fen": 50000,
        "price_fen": 50000,
        "type": "fixed",
        "status": "active",
        "total_sold": 420,
        "total_redeemed": 310,
        "design_theme": "经典红",
        "created_at": "2026-01-01T10:00:00Z",
    },
    {
        "card_id": "gc003",
        "name": "企业团购卡·1000元",
        "face_value_fen": 100000,
        "price_fen": 95000,
        "type": "fixed",
        "status": "active",
        "total_sold": 1200,
        "total_redeemed": 880,
        "design_theme": "商务蓝",
        "created_at": "2026-02-01T10:00:00Z",
    },
    {
        "card_id": "gc004",
        "name": "自选金额卡",
        "face_value_fen": None,
        "price_fen": None,
        "type": "custom",
        "min_fen": 10000,
        "max_fen": 500000,
        "status": "active",
        "total_sold": 180,
        "total_redeemed": 95,
        "design_theme": "节日特别版",
        "created_at": "2026-03-01T10:00:00Z",
    },
]

_MOCK_POINTS_CONFIG = {
    "earn_rules": [
        {"action": "消费", "rule": "每消费1元积1分", "rate": 1, "unit": "元/分"},
        {"action": "签到", "rule": "每日签到5分", "fixed_points": 5},
        {"action": "评价", "rule": "消费后评价10分", "fixed_points": 10},
        {"action": "生日", "rule": "生日当天双倍积分", "multiplier": 2},
        {"action": "推荐新客", "rule": "成功推荐100分", "fixed_points": 100},
    ],
    "redeem_rules": [
        {"type": "cash_deduction", "label": "积分抵现", "rate": 100, "description": "100积分抵1元", "max_deduction_ratio": 0.5},
        {"type": "gift_exchange", "label": "积分换礼", "description": "指定礼品兑换"},
        {"type": "coupon_exchange", "label": "积分换券", "description": "积分兑换优惠券"},
    ],
    "expiry_rule": {
        "type": "annual_clear",
        "description": "每年12月31日清零当年1月1日前获取的积分",
        "advance_notice_days": 30,
    },
    "tier_multiplier": [
        {"tier": "普通会员", "multiplier": 1.0},
        {"tier": "银卡会员", "multiplier": 1.2},
        {"tier": "金卡会员", "multiplier": 1.5},
        {"tier": "钻石会员", "multiplier": 2.0},
    ],
    "total_points_issued": 52680000,
    "total_points_redeemed": 31200000,
    "total_points_expired": 8500000,
    "current_liability_fen": 12980000,
}


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


# ─── 端点 ────────────────────────────────────────────────────

@router.get("/coupons")
async def list_coupons(
    status: Optional[str] = Query(None, description="状态筛选: active/paused/expired"),
    coupon_type: Optional[str] = Query(None, alias="type", description="类型筛选"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """优惠券列表"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("list_coupons", tenant_id=str(tenant_id))

    filtered = list(_MOCK_COUPONS)
    if status:
        filtered = [c for c in filtered if c["status"] == status]
    if coupon_type:
        filtered = [c for c in filtered if c["type"] == coupon_type]

    total = len(filtered)
    offset = (page - 1) * size
    items = filtered[offset: offset + size]

    # 汇总统计
    summary = {
        "total_active": sum(1 for c in _MOCK_COUPONS if c["status"] == "active"),
        "total_issued": sum(c["total_issued"] for c in _MOCK_COUPONS),
        "total_used": sum(c["total_used"] for c in _MOCK_COUPONS),
        "avg_use_rate": round(
            sum(c["use_rate"] for c in _MOCK_COUPONS) / len(_MOCK_COUPONS), 3
        ),
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


@router.post("/coupons")
async def create_coupon(
    body: CreateCouponRequest,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """创建优惠券"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("create_coupon", tenant_id=str(tenant_id), name=body.name, coupon_type=body.type)

    coupon_id = str(uuid.uuid4())
    new_coupon = {
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
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    return {
        "ok": True,
        "data": new_coupon,
    }


@router.get("/stored-value/plans")
async def list_stored_value_plans(
    status: Optional[str] = Query(None, description="状态筛选: active/paused"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """储值方案列表"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("list_stored_value_plans", tenant_id=str(tenant_id))

    filtered = list(_MOCK_STORED_VALUE_PLANS)
    if status:
        filtered = [p for p in filtered if p["status"] == status]

    total_balance_fen = sum(p["total_charge_fen"] for p in _MOCK_STORED_VALUE_PLANS)

    return {
        "ok": True,
        "data": {
            "items": filtered,
            "total": len(filtered),
            "summary": {
                "total_balance_fen": total_balance_fen,
                "total_plans": len(_MOCK_STORED_VALUE_PLANS),
                "total_customers": sum(p["total_sold"] for p in _MOCK_STORED_VALUE_PLANS),
            },
        },
    }


@router.get("/gift-cards")
async def list_gift_cards(
    status: Optional[str] = Query(None, description="状态筛选: active/paused"),
    card_type: Optional[str] = Query(None, alias="type", description="类型: fixed/custom"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """礼品卡列表"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("list_gift_cards", tenant_id=str(tenant_id))

    filtered = list(_MOCK_GIFT_CARDS)
    if status:
        filtered = [g for g in filtered if g["status"] == status]
    if card_type:
        filtered = [g for g in filtered if g["type"] == card_type]

    total = len(filtered)
    offset = (page - 1) * size
    items = filtered[offset: offset + size]

    return {
        "ok": True,
        "data": {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
        },
    }


@router.get("/points/config")
async def get_points_config(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """积分规则配置"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("get_points_config", tenant_id=str(tenant_id))

    return {
        "ok": True,
        "data": _MOCK_POINTS_CONFIG,
    }
