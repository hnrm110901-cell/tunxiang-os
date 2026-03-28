"""财务分析 API 端点 (D5)

5 个端点：营收构成、折扣结构、优惠券成本、门店利润、财务稽核
"""
from fastapi import APIRouter, Header, Query

router = APIRouter(prefix="/api/v1/finance/analytics", tags=["finance-analytics"])


# ── 1. 营收构成分析 ──────────────────────────────────────────

@router.get("/revenue-composition")
async def get_revenue_composition(
    store_id: str = Query(..., description="门店 ID"),
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """营收构成分析 — 按来源(堂食/外卖/宴席)、按支付方式(微信/支付宝/现金/会员/挂账)"""
    # TODO: 注入真实 DB session 后调用 finance_analytics.revenue_composition
    return {
        "ok": True,
        "data": {
            "by_source": [],
            "by_payment": [],
            "total_revenue_fen": 0,
            "date_range": [start_date, end_date],
        },
    }


# ── 2. 折扣结构分析 ──────────────────────────────────────────

@router.get("/discount-structure")
async def get_discount_structure(
    store_id: str = Query(..., description="门店 ID"),
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """折扣结构分析 — 会员折扣/活动/赠菜/员工餐"""
    return {
        "ok": True,
        "data": {
            "total_discount_fen": 0,
            "gross_amount_fen": 0,
            "net_amount_fen": 0,
            "discount_rate": 0.0,
            "by_type": [],
            "gift_cost_fen": 0,
            "date_range": [start_date, end_date],
        },
    }


# ── 3. 优惠券成本分析 ────────────────────────────────────────

@router.get("/coupon-cost")
async def get_coupon_cost_analysis(
    store_id: str = Query(..., description="门店 ID"),
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """优惠券成本与 ROI 分析"""
    return {
        "ok": True,
        "data": {
            "total_coupon_cost_fen": 0,
            "coupon_revenue_fen": 0,
            "coupon_order_count": 0,
            "roi": 0.0,
            "by_campaign": [],
            "date_range": [start_date, end_date],
        },
    }


# ── 4. 门店利润分析 ──────────────────────────────────────────

@router.get("/store-profit")
async def get_store_profit_analysis(
    store_id: str = Query(..., description="门店 ID"),
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """门店利润分析 — 营收、食材成本、人力、租金、利润率"""
    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "revenue_fen": 0,
            "food_cost_fen": 0,
            "labor_cost_fen": 0,
            "rent_fen": 0,
            "other_fen": 0,
            "gross_profit_fen": 0,
            "gross_margin": 0.0,
            "profit_fen": 0,
            "profit_rate": 0.0,
            "date_range": [start_date, end_date],
        },
    }


# ── 5. 财务稽核视图 ──────────────────────────────────────────

@router.get("/audit-view")
async def get_financial_audit_view(
    store_id: str = Query(..., description="门店 ID"),
    date: str = Query(..., description="稽核日期 YYYY-MM-DD"),
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """财务稽核视图 — 当日收支明细、退菜、赠菜、异常订单"""
    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "audit_date": date,
            "summary": {
                "order_count": 0,
                "gross_revenue_fen": 0,
                "total_discount_fen": 0,
                "net_revenue_fen": 0,
            },
            "returns": {"return_count": 0, "return_amount_fen": 0},
            "gifts": {"gift_count": 0, "gift_amount_fen": 0},
            "alerts": {"abnormal_order_count": 0, "margin_alert_count": 0},
            "hourly_breakdown": [],
        },
    }
