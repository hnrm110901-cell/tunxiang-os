"""财务结算 API — 连接真实计算引擎

所有金额单位：分（fen）。展示时 /100 转元。
"""
import uuid as _uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text

from shared.ontology.src.database import get_db_with_tenant
from shared.ontology.src.entities import Order, OrderItem, Store

from services.store_pnl import StorePnLService
from services.voucher_service import generate_voucher_from_settlement, format_for_kingdee
from ..services.budget_service import BudgetService

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/finance", tags=["finance"])
pnl_service = StorePnLService()
budget_service = BudgetService()


def _parse_date(d: str) -> date:
    if d == "today":
        return date.today()
    return date.fromisoformat(d)


async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    """从 header 提取 tenant_id 并返回带 RLS 的 DB session"""
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ── 日利润快报 ────────────────────────────────────────────────

@router.get("/daily-profit")
async def get_daily_profit(
    store_id: str,
    date: str = "today",
    db: AsyncSession = Depends(_get_tenant_db),
):
    """每日利润快报 — 从订单表实时聚合"""
    biz_date = _parse_date(date)
    start_dt = datetime.combine(biz_date, datetime.min.time()).replace(tzinfo=timezone.utc)
    end_dt = datetime.combine(biz_date, datetime.max.time()).replace(tzinfo=timezone.utc)
    sid = _uuid.UUID(store_id)

    revenue_row = await db.execute(
        select(
            func.coalesce(func.sum(Order.final_amount_fen), 0).label("revenue"),
            func.coalesce(func.sum(Order.original_amount_fen - Order.final_amount_fen), 0).label("discount"),
            func.count(Order.id).label("order_count"),
        )
        .where(Order.store_id == sid)
        .where(Order.status.in_(["completed", "settled"]))
        .where(Order.created_at >= start_dt)
        .where(Order.created_at <= end_dt)
    )
    row = revenue_row.one()
    revenue_fen = int(row.revenue)
    discount_fen = int(row.discount)
    order_count = int(row.order_count)

    cost_row = await db.execute(
        select(
            func.coalesce(func.sum(OrderItem.cost_fen * OrderItem.quantity), 0).label("cost"),
        )
        .join(Order, OrderItem.order_id == Order.id)
        .where(Order.store_id == sid)
        .where(Order.status.in_(["completed", "settled"]))
        .where(Order.created_at >= start_dt)
        .where(Order.created_at <= end_dt)
    )
    cost_fen = int(cost_row.scalar_one())

    profit_fen = revenue_fen - cost_fen
    gross_margin = round(profit_fen / revenue_fen, 4) if revenue_fen > 0 else 0.0

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "biz_date": str(biz_date),
            "revenue_fen": revenue_fen,
            "cost_fen": cost_fen,
            "profit_fen": profit_fen,
            "discount_fen": discount_fen,
            "gross_margin": gross_margin,
            "order_count": order_count,
        },
    }


# ── 成本率 ────────────────────────────────────────────────────

@router.get("/cost-rate")
async def get_cost_rate(
    store_id: str,
    period: str = "month",
    db: AsyncSession = Depends(_get_tenant_db),
):
    """成本率分析 — 食材成本 / 营收"""
    sid = _uuid.UUID(store_id)
    today = date.today()

    if period == "week":
        start = today - timedelta(days=7)
    elif period == "month":
        start = today.replace(day=1)
    elif period == "quarter":
        q_month = ((today.month - 1) // 3) * 3 + 1
        start = today.replace(month=q_month, day=1)
    else:
        start = today.replace(month=1, day=1)

    start_dt = datetime.combine(start, datetime.min.time()).replace(tzinfo=timezone.utc)
    end_dt = datetime.combine(today, datetime.max.time()).replace(tzinfo=timezone.utc)

    rev_result = await db.execute(
        select(func.coalesce(func.sum(Order.final_amount_fen), 0))
        .where(Order.store_id == sid)
        .where(Order.status.in_(["completed", "settled"]))
        .where(Order.created_at >= start_dt)
        .where(Order.created_at <= end_dt)
    )
    revenue_fen = int(rev_result.scalar_one())

    cost_result = await db.execute(
        select(func.coalesce(func.sum(OrderItem.cost_fen * OrderItem.quantity), 0))
        .join(Order, OrderItem.order_id == Order.id)
        .where(Order.store_id == sid)
        .where(Order.status.in_(["completed", "settled"]))
        .where(Order.created_at >= start_dt)
        .where(Order.created_at <= end_dt)
    )
    cost_fen = int(cost_result.scalar_one())

    cost_rate = round(cost_fen / revenue_fen, 4) if revenue_fen > 0 else 0.0

    daily_result = await db.execute(
        select(
            func.date_trunc("day", Order.created_at).label("day"),
            func.sum(Order.final_amount_fen).label("rev"),
        )
        .where(Order.store_id == sid)
        .where(Order.status.in_(["completed", "settled"]))
        .where(Order.created_at >= start_dt)
        .where(Order.created_at <= end_dt)
        .group_by(text("1"))
        .order_by(text("1"))
    )
    trend = [
        {"date": str(r.day.date()) if r.day else "", "revenue_fen": int(r.rev or 0)}
        for r in daily_result.all()
    ]

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "period": period,
            "revenue_fen": revenue_fen,
            "cost_fen": cost_fen,
            "cost_rate": cost_rate,
            "trend": trend,
        },
    }


@router.get("/cost-rate/ranking")
async def get_cost_rate_ranking(
    brand_id: Optional[str] = None,
    db: AsyncSession = Depends(_get_tenant_db),
):
    """跨店成本率排名"""
    today = date.today()
    start = today.replace(day=1)
    start_dt = datetime.combine(start, datetime.min.time()).replace(tzinfo=timezone.utc)
    end_dt = datetime.combine(today, datetime.max.time()).replace(tzinfo=timezone.utc)

    query = (
        select(
            Order.store_id,
            func.sum(Order.final_amount_fen).label("revenue"),
            func.sum(OrderItem.cost_fen * OrderItem.quantity).label("cost"),
        )
        .join(OrderItem, OrderItem.order_id == Order.id)
        .where(Order.status.in_(["completed", "settled"]))
        .where(Order.created_at >= start_dt)
        .where(Order.created_at <= end_dt)
        .group_by(Order.store_id)
    )

    rows = await db.execute(query)
    rankings = []
    for r in rows.all():
        rev = int(r.revenue or 0)
        cost = int(r.cost or 0)
        rate = round(cost / rev, 4) if rev > 0 else 0.0
        rankings.append({
            "store_id": str(r.store_id),
            "revenue_fen": rev,
            "cost_fen": cost,
            "cost_rate": rate,
        })
    rankings.sort(key=lambda x: x["cost_rate"])

    return {"ok": True, "data": {"rankings": rankings, "period": f"{start} ~ {today}"}}


# ── P&L 报表 ──────────────────────────────────────────────────

@router.get("/pnl/{store_id}")
async def get_store_pnl(
    store_id: str,
    date: str = "today",
    db: AsyncSession = Depends(_get_tenant_db),
):
    """门店日度 P&L — 调用 StorePnLService 真实计算"""
    sid = _uuid.UUID(store_id)
    biz_date = _parse_date(date)
    start_dt = datetime.combine(biz_date, datetime.min.time()).replace(tzinfo=timezone.utc)
    end_dt = datetime.combine(biz_date, datetime.max.time()).replace(tzinfo=timezone.utc)

    rev_by_type = await db.execute(
        select(
            Order.order_type,
            func.coalesce(func.sum(Order.final_amount_fen), 0).label("amount"),
        )
        .where(Order.store_id == sid)
        .where(Order.status.in_(["completed", "settled"]))
        .where(Order.created_at >= start_dt)
        .where(Order.created_at <= end_dt)
        .group_by(Order.order_type)
    )
    revenue_data = {}
    type_map = {"dine_in": "dine_in", "takeaway": "takeaway", "delivery": "delivery", "banquet": "banquet"}
    for r in rev_by_type.all():
        key = type_map.get(r.order_type, "other")
        revenue_data[key] = revenue_data.get(key, 0) + int(r.amount or 0)

    cost_result = await db.execute(
        select(func.coalesce(func.sum(OrderItem.cost_fen * OrderItem.quantity), 0))
        .join(Order, OrderItem.order_id == Order.id)
        .where(Order.store_id == sid)
        .where(Order.status.in_(["completed", "settled"]))
        .where(Order.created_at >= start_dt)
        .where(Order.created_at <= end_dt)
    )
    food_cost = int(cost_result.scalar_one())

    store_row = await db.execute(
        select(Store.seats, Store.config).where(Store.id == sid)
    )
    store = store_row.first()
    seats = store.seats if store else 0
    config = store.config if store else {}
    operating_hours = config.get("operating_hours", 12) if isinstance(config, dict) else 12

    pnl_data = {
        "revenue": revenue_data,
        "cogs": {"food_cost": food_cost, "beverage_cost": 0, "waste_spoilage": 0},
        "opex": config.get("fixed_costs", {}) if isinstance(config, dict) else {},
        "other": {},
        "meta": {"seats": seats or 0, "operating_hours": operating_hours},
    }

    pnl = pnl_service.generate_daily_pnl(store_id, str(biz_date), pnl_data)
    return {"ok": True, "data": pnl}


# ── 预算 Pydantic 请求模型 ───────────────────────────────────

class CreateBudgetRequest(BaseModel):
    store_id: str
    department: str
    period: str = Field(..., description="monthly / quarterly / yearly")
    period_start: date
    period_end: date
    category: str = Field(..., description="revenue / cost / labor / material / marketing / overhead")
    budget_amount_fen: int = Field(..., ge=0)
    note: Optional[str] = None


class RecordExecutionRequest(BaseModel):
    budget_id: str
    actual_amount_fen: int
    recorded_date: date
    source_type: str = Field(..., description="order / purchase / payroll / expense")
    description: Optional[str] = None


class ApproveBudgetRequest(BaseModel):
    budget_id: str


# ── 预算 ──────────────────────────────────────────────────────

@router.get("/budget")
async def list_budgets(
    store_id: str,
    department: Optional[str] = None,
    period: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(_get_tenant_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """预算列表查询 — 按门店/部门/期间/类别筛选"""
    tid = _uuid.UUID(x_tenant_id)
    sid = _uuid.UUID(store_id)
    result = await budget_service.list_budgets(
        db=db,
        tenant_id=tid,
        store_id=sid,
        department=department,
        period=period,
        category=category,
        status=status,
        page=page,
        size=size,
    )
    items_data = [
        {
            "id": str(b.id),
            "store_id": str(b.store_id),
            "department": b.department,
            "period": b.period,
            "period_start": str(b.period_start),
            "period_end": str(b.period_end),
            "category": b.category,
            "budget_amount_fen": b.budget_amount_fen,
            "status": b.status,
            "note": b.note,
            "created_at": b.created_at.isoformat() if b.created_at else None,
        }
        for b in result["items"]
    ]
    return {
        "ok": True,
        "data": {
            "items": items_data,
            "total": result["total"],
            "page": result["page"],
            "size": result["size"],
        },
    }


@router.post("/budget")
async def create_budget(
    body: CreateBudgetRequest,
    db: AsyncSession = Depends(_get_tenant_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """创建预算"""
    tid = _uuid.UUID(x_tenant_id)
    sid = _uuid.UUID(body.store_id)
    budget = await budget_service.create_budget(
        db=db,
        tenant_id=tid,
        store_id=sid,
        department=body.department,
        period=body.period,
        period_start=body.period_start,
        period_end=body.period_end,
        category=body.category,
        budget_amount_fen=body.budget_amount_fen,
        note=body.note,
    )
    await db.commit()
    return {
        "ok": True,
        "data": {
            "id": str(budget.id),
            "store_id": str(budget.store_id),
            "category": budget.category,
            "budget_amount_fen": budget.budget_amount_fen,
            "status": budget.status,
        },
    }


@router.post("/budget/approve")
async def approve_budget(
    body: ApproveBudgetRequest,
    db: AsyncSession = Depends(_get_tenant_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """审批预算：draft → approved"""
    tid = _uuid.UUID(x_tenant_id)
    bid = _uuid.UUID(body.budget_id)
    budget = await budget_service.approve_budget(db=db, tenant_id=tid, budget_id=bid)
    await db.commit()
    return {
        "ok": True,
        "data": {"id": str(budget.id), "status": budget.status},
    }


@router.get("/budget/execution")
async def get_budget_execution(
    store_id: str,
    category: Optional[str] = None,
    db: AsyncSession = Depends(_get_tenant_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """获取预算执行情况 — 预算 vs 实际，偏差率"""
    tid = _uuid.UUID(x_tenant_id)
    sid = _uuid.UUID(store_id)
    summaries = await budget_service.get_budget_execution(
        db=db, tenant_id=tid, store_id=sid, category=category,
    )
    return {"ok": True, "data": {"execution": summaries}}


@router.post("/budget/execution")
async def record_budget_execution(
    body: RecordExecutionRequest,
    db: AsyncSession = Depends(_get_tenant_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """记录预算执行（实际发生金额）"""
    tid = _uuid.UUID(x_tenant_id)
    bid = _uuid.UUID(body.budget_id)
    execution = await budget_service.record_execution(
        db=db,
        tenant_id=tid,
        budget_id=bid,
        actual_amount_fen=body.actual_amount_fen,
        recorded_date=body.recorded_date,
        source_type=body.source_type,
        description=body.description,
    )
    await db.commit()
    return {
        "ok": True,
        "data": {
            "id": str(execution.id),
            "budget_id": str(execution.budget_id),
            "actual_amount_fen": execution.actual_amount_fen,
            "variance_fen": execution.variance_fen,
            "variance_pct": execution.variance_pct,
        },
    }


# ── 现金流 ────────────────────────────────────────────────────

@router.get("/cashflow/forecast")
async def forecast_cashflow(
    store_id: str,
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(_get_tenant_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """现金流预测 — 基于预算+历史趋势"""
    tid = _uuid.UUID(x_tenant_id)
    sid = _uuid.UUID(store_id)
    forecast = await budget_service.get_cashflow_forecast(
        db=db, tenant_id=tid, store_id=sid, days=days,
    )
    return {"ok": True, "data": {"forecast": forecast, "days": days, "store_id": store_id}}


# ── 月度报告 ──────────────────────────────────────────────────

@router.get("/reports/monthly/{store_id}")
async def get_monthly_report(
    store_id: str,
    month: Optional[str] = None,
    db: AsyncSession = Depends(_get_tenant_db),
):
    """月度经营报告 — 聚合日度 P&L"""
    sid = _uuid.UUID(store_id)
    today = date.today()
    if month:
        year, mon = int(month[:4]), int(month[5:7])
    else:
        year, mon = today.year, today.month

    start = date(year, mon, 1)
    if mon == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, mon + 1, 1) - timedelta(days=1)

    start_dt = datetime.combine(start, datetime.min.time()).replace(tzinfo=timezone.utc)
    end_dt = datetime.combine(end, datetime.max.time()).replace(tzinfo=timezone.utc)

    result = await db.execute(
        select(
            func.coalesce(func.sum(Order.final_amount_fen), 0).label("revenue"),
            func.count(Order.id).label("orders"),
        )
        .where(Order.store_id == sid)
        .where(Order.status.in_(["completed", "settled"]))
        .where(Order.created_at >= start_dt)
        .where(Order.created_at <= end_dt)
    )
    row = result.one()
    revenue_fen = int(row.revenue)
    order_count = int(row.orders)
    avg_ticket = revenue_fen // order_count if order_count > 0 else 0

    cost_result = await db.execute(
        select(func.coalesce(func.sum(OrderItem.cost_fen * OrderItem.quantity), 0))
        .join(Order, OrderItem.order_id == Order.id)
        .where(Order.store_id == sid)
        .where(Order.status.in_(["completed", "settled"]))
        .where(Order.created_at >= start_dt)
        .where(Order.created_at <= end_dt)
    )
    cost_fen = int(cost_result.scalar_one())
    gross_profit = revenue_fen - cost_fen
    gross_margin = round(gross_profit / revenue_fen, 4) if revenue_fen > 0 else 0.0

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "month": f"{year}-{mon:02d}",
            "revenue_fen": revenue_fen,
            "cost_fen": cost_fen,
            "gross_profit_fen": gross_profit,
            "gross_margin": gross_margin,
            "order_count": order_count,
            "avg_ticket_fen": avg_ticket,
            "days_in_period": (end - start).days + 1,
        },
    }


@router.get("/reports/monthly/{store_id}/html")
async def get_monthly_report_html(store_id: str, month: Optional[str] = None):
    """HTML 月报（浏览器打印 PDF）— 规划中"""
    return {"ok": True, "data": {"html": "", "note": "HTML report planned for Phase 1.1.4"}}


# ── 凭证 ──────────────────────────────────────────────────────

@router.post("/voucher/generate")
async def generate_voucher(settlement: dict):
    """从日结数据生成会计凭证"""
    voucher = generate_voucher_from_settlement(settlement, settlement.get("store_name", ""))
    return {"ok": True, "data": voucher}


@router.post("/voucher/kingdee")
async def export_kingdee_voucher(settlement: dict):
    """生成金蝶 K3 Cloud 格式凭证"""
    voucher = generate_voucher_from_settlement(settlement, settlement.get("store_name", ""))
    kingdee_format = format_for_kingdee(voucher)
    return {"ok": True, "data": {"voucher": voucher, "kingdee_format": kingdee_format}}


# ── 电子发票 ──────────────────────────────────────────────────

@router.post("/invoice")
async def create_invoice(order_id: str, buyer_info: dict):
    """电子发票开具 — 调用诺诺 Adapter"""
    return {"ok": True, "data": {"invoice_id": "new", "note": "Nuonuo adapter integration pending"}}
