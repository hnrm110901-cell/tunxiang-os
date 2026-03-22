"""财务结算 API"""
from typing import Optional
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/finance", tags=["finance"])


# 日利润快报
@router.get("/daily-profit")
async def get_daily_profit(store_id: str, date: str = "today"):
    """每日利润快报（含¥金额）"""
    return {"ok": True, "data": {"revenue_fen": 0, "cost_fen": 0, "profit_fen": 0}}

# 成本率
@router.get("/cost-rate")
async def get_cost_rate(store_id: str, period: str = "month"):
    return {"ok": True, "data": {"cost_rate": 0, "trend": []}}

@router.get("/cost-rate/ranking")
async def get_cost_rate_ranking(brand_id: Optional[str] = None):
    """跨店成本率排名"""
    return {"ok": True, "data": {"rankings": []}}

# FCT 报表
@router.get("/fct/report")
async def get_fct_report(store_id: str, report_type: str = "period_summary"):
    """7种报表：period_summary/aggregate/trend/by_entity/by_region/comparison/plan_vs_actual"""
    return {"ok": True, "data": {"report": {}}}

@router.get("/fct/dashboard")
async def get_fct_dashboard(store_id: str):
    return {"ok": True, "data": {"cash_flow": {}, "tax": {}, "budget": {}}}

# 预算
@router.get("/budget")
async def get_budget(store_id: str, month: Optional[str] = None):
    return {"ok": True, "data": {"budget": {}}}

@router.get("/budget/execution")
async def get_budget_execution(store_id: str):
    return {"ok": True, "data": {"execution": {}}}

# 现金流
@router.get("/cashflow/forecast")
async def forecast_cashflow(store_id: str, days: int = 30):
    return {"ok": True, "data": {"forecast": []}}

# 月度报告
@router.get("/reports/monthly/{store_id}")
async def get_monthly_report(store_id: str, month: Optional[str] = None):
    return {"ok": True, "data": {"report": {}}}

@router.get("/reports/monthly/{store_id}/html")
async def get_monthly_report_html(store_id: str):
    """HTML 月报（浏览器打印 PDF）"""
    return {"ok": True, "data": {"html": "<h1>Monthly Report</h1>"}}

# 电子发票
@router.post("/invoice")
async def create_invoice(order_id: str, buyer_info: dict):
    return {"ok": True, "data": {"invoice_id": "new"}}
