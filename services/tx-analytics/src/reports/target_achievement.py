"""门店经营目标达成报表

比对门店经营目标（stores 表 7 个 target 字段）与实际经营数据，
返回各 KPI 的目标值、实际值、达成率、同比趋势。

端点：GET /api/v1/analytics/reports/target-achievement
参数：store_id (必填), period=day|week|month (默认 month)

KPI 计算口径：
  1. 月营收  — SUM(orders.final_amount_fen) WHERE status IN ('completed','paid')
  2. 日客流  — COUNT(DISTINCT orders.id) per day (均值)
  3. 成本率  — ingredient_transactions(purchase) / revenue * 100
  4. 人工成本率 — payroll_records.gross_pay_fen / revenue * 100
  5. 翻台率  — completed_orders / table_count / business_days
  6. 损耗率  — ingredient_transactions(waste) / ingredient_transactions(purchase) * 100
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

# ── 常量 ─────────────────────────────────────────────────────────────────────

REPORT_ID = "target_achievement"
REPORT_NAME = "门店经营目标达成"
CATEGORY = "kpi"

# 用于注册表兼容（report_engine 会读取这些属性）
DIMENSIONS = ["kpi_name"]
METRICS = ["target", "actual", "achievement_rate", "trend"]
FILTERS = ["store_id", "period"]

# 完成态订单状态
_COMPLETED_STATUSES = ("completed", "paid")


# ── SQL 片段 ─────────────────────────────────────────────────────────────────

_SQL_REVENUE = """
SELECT COALESCE(SUM(o.final_amount_fen), 0) AS revenue_fen
  FROM orders o
 WHERE o.tenant_id = :tenant_id
   AND o.store_id  = :store_id::UUID
   AND o.is_deleted = FALSE
   AND o.status IN ('completed', 'paid')
   AND DATE(o.order_time) BETWEEN :start_date AND :end_date
"""

_SQL_DAILY_CUSTOMERS = """
SELECT DATE(o.order_time) AS biz_date,
       COUNT(*) AS order_count
  FROM orders o
 WHERE o.tenant_id = :tenant_id
   AND o.store_id  = :store_id::UUID
   AND o.is_deleted = FALSE
   AND o.status IN ('completed', 'paid')
   AND DATE(o.order_time) BETWEEN :start_date AND :end_date
 GROUP BY DATE(o.order_time)
"""

_SQL_INGREDIENT_COST = """
SELECT COALESCE(SUM(CASE WHEN it.transaction_type = 'purchase'
                         THEN ABS(COALESCE(it.total_cost_fen, 0)) ELSE 0 END), 0) AS purchase_fen,
       COALESCE(SUM(CASE WHEN it.transaction_type = 'waste'
                         THEN ABS(COALESCE(it.total_cost_fen, 0)) ELSE 0 END), 0) AS waste_fen
  FROM ingredient_transactions it
 WHERE it.tenant_id = :tenant_id
   AND it.store_id  = :store_id::UUID
   AND DATE(it.transaction_time) BETWEEN :start_date AND :end_date
"""

_SQL_LABOR_COST = """
SELECT COALESCE(SUM(pr.gross_pay_fen), 0) AS labor_cost_fen
  FROM payroll_records pr
 WHERE pr.tenant_id = :tenant_id
   AND pr.store_id  = :store_id::UUID
   AND pr.is_deleted = FALSE
   AND pr.status != 'voided'
   AND pr.pay_period_start <= :end_date
   AND pr.pay_period_end   >= :start_date
"""

_SQL_TABLE_COUNT = """
SELECT COUNT(DISTINCT o.table_number) AS table_count
  FROM orders o
 WHERE o.tenant_id = :tenant_id
   AND o.store_id  = :store_id::UUID
   AND o.is_deleted = FALSE
   AND o.status IN ('completed', 'paid')
   AND o.table_number IS NOT NULL
   AND DATE(o.order_time) BETWEEN :start_date AND :end_date
"""

_SQL_STORE_TARGETS = """
SELECT s.monthly_revenue_target_fen,
       s.daily_customer_target,
       s.cost_ratio_target,
       s.labor_cost_ratio_target,
       s.turnover_rate_target,
       s.waste_rate_target,
       s.seats
  FROM stores s
 WHERE s.tenant_id = :tenant_id
   AND s.id = :store_id::UUID
   AND s.is_deleted = FALSE
"""


# ── 数据模型 ─────────────────────────────────────────────────────────────────

@dataclass
class KPIItem:
    name: str
    label: str
    target: float | None
    actual: float
    achievement_rate: float | None  # actual / target * 100, None when no target
    trend: float | None             # vs previous period (%), None when no prev data
    unit: str                       # "fen" | "%" | "次/桌/日"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "target": self.target,
            "actual": round(self.actual, 2),
            "achievement_rate": round(self.achievement_rate, 2) if self.achievement_rate is not None else None,
            "trend": round(self.trend, 2) if self.trend is not None else None,
            "unit": self.unit,
        }


# ── 核心报表函数 ─────────────────────────────────────────────────────────────

def _period_range(period: str, base_date: date) -> tuple[date, date]:
    """Return (start_date, end_date) for the given period ending at base_date."""
    if period == "month":
        return base_date.replace(day=1), base_date
    if period == "week":
        return base_date - timedelta(days=6), base_date
    # day
    return base_date, base_date


def _prev_period_range(period: str, start: date, end: date) -> tuple[date, date]:
    """Return the equivalent previous period for trend comparison."""
    span = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=span - 1)
    return prev_start, prev_end


async def target_achievement_report(
    store_id: str,
    period: str,
    tenant_id: str,
    db: AsyncSession,
    base_date: date | None = None,
) -> dict[str, Any]:
    """Compare store targets vs actual performance.

    Returns for each KPI:
      - target value (from stores table)
      - actual value (calculated from orders/payments/ingredients)
      - achievement_rate (actual/target * 100)
      - trend (vs previous period)

    Args:
        store_id: UUID string of the store.
        period: "day", "week", or "month".
        tenant_id: Tenant UUID for RLS.
        db: Async SQLAlchemy session.
        base_date: Reference date (defaults to today).

    Returns:
        {"kpis": [...], "overall_rate": float, "period": {...}}
    """
    if base_date is None:
        base_date = date.today()

    start_date, end_date = _period_range(period, base_date)
    prev_start, prev_end = _prev_period_range(period, start_date, end_date)
    business_days = (end_date - start_date).days + 1

    params: dict[str, Any] = {
        "tenant_id": tenant_id,
        "store_id": store_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    prev_params: dict[str, Any] = {
        **params,
        "start_date": prev_start,
        "end_date": prev_end,
    }

    # ── 1. Fetch store targets ───────────────────────────────────────────
    row = (await db.execute(text(_SQL_STORE_TARGETS), params)).mappings().first()
    if row is None:
        log.warning("target_achievement_store_not_found", store_id=store_id)
        return {"kpis": [], "overall_rate": None, "period": {"start": str(start_date), "end": str(end_date)}}

    targets = dict(row)

    # ── 2. Fetch current-period actuals ──────────────────────────────────
    revenue_fen = (await db.execute(text(_SQL_REVENUE), params)).scalar() or 0

    daily_rows = (await db.execute(text(_SQL_DAILY_CUSTOMERS), params)).mappings().all()
    daily_order_counts = [r["order_count"] for r in daily_rows]
    avg_daily_customers = (
        sum(daily_order_counts) / len(daily_order_counts) if daily_order_counts else 0
    )
    total_orders = sum(daily_order_counts)

    ing_row = (await db.execute(text(_SQL_INGREDIENT_COST), params)).mappings().first()
    purchase_fen = ing_row["purchase_fen"] if ing_row else 0
    waste_fen = ing_row["waste_fen"] if ing_row else 0

    labor_row = (await db.execute(text(_SQL_LABOR_COST), params)).mappings().first()
    labor_cost_fen = labor_row["labor_cost_fen"] if labor_row else 0

    table_row = (await db.execute(text(_SQL_TABLE_COUNT), params)).mappings().first()
    table_count = table_row["table_count"] if table_row else 0
    # Fallback: use store.seats if no distinct tables found
    if table_count == 0 and targets.get("seats"):
        table_count = targets["seats"]

    # ── 3. Fetch previous-period actuals for trend ───────────────────────
    prev_revenue = (await db.execute(text(_SQL_REVENUE), prev_params)).scalar() or 0

    prev_daily = (await db.execute(text(_SQL_DAILY_CUSTOMERS), prev_params)).mappings().all()
    prev_daily_counts = [r["order_count"] for r in prev_daily]
    prev_avg_daily = sum(prev_daily_counts) / len(prev_daily_counts) if prev_daily_counts else 0
    prev_total_orders = sum(prev_daily_counts)

    prev_ing = (await db.execute(text(_SQL_INGREDIENT_COST), prev_params)).mappings().first()
    prev_purchase = prev_ing["purchase_fen"] if prev_ing else 0
    prev_waste = prev_ing["waste_fen"] if prev_ing else 0

    prev_labor = (await db.execute(text(_SQL_LABOR_COST), prev_params)).mappings().first()
    prev_labor_cost = prev_labor["labor_cost_fen"] if prev_labor else 0

    # ── 4. Compute KPIs ──────────────────────────────────────────────────
    kpis: list[KPIItem] = []

    # 4a. 月营收目标 (fen)
    rev_target = targets.get("monthly_revenue_target_fen")
    # For non-month periods, pro-rate the monthly target
    if rev_target is not None and period != "month":
        # Approximate: monthly target / 30 * business_days
        rev_target = int(rev_target / 30 * business_days)
    kpis.append(KPIItem(
        name="monthly_revenue",
        label="营收目标",
        target=rev_target,
        actual=revenue_fen,
        achievement_rate=_rate(revenue_fen, rev_target),
        trend=_trend(revenue_fen, prev_revenue),
        unit="fen",
    ))

    # 4b. 日客流目标
    cust_target = targets.get("daily_customer_target")
    kpis.append(KPIItem(
        name="daily_customers",
        label="日客流目标",
        target=cust_target,
        actual=avg_daily_customers,
        achievement_rate=_rate(avg_daily_customers, cust_target),
        trend=_trend(avg_daily_customers, prev_avg_daily),
        unit="单/日",
    ))

    # 4c. 成本率 (%)
    cost_ratio = (purchase_fen / revenue_fen * 100) if revenue_fen > 0 else 0.0
    prev_cost_ratio = (prev_purchase / prev_revenue * 100) if prev_revenue > 0 else 0.0
    cost_target = targets.get("cost_ratio_target")
    # For ratio targets, lower is better: achievement = target / actual * 100
    kpis.append(KPIItem(
        name="cost_ratio",
        label="成本率",
        target=cost_target,
        actual=cost_ratio,
        achievement_rate=_rate_inverse(cost_ratio, cost_target),
        trend=_trend_delta(cost_ratio, prev_cost_ratio),
        unit="%",
    ))

    # 4d. 人工成本率 (%)
    labor_ratio = (labor_cost_fen / revenue_fen * 100) if revenue_fen > 0 else 0.0
    prev_labor_ratio = (prev_labor_cost / prev_revenue * 100) if prev_revenue > 0 else 0.0
    labor_target = targets.get("labor_cost_ratio_target")
    kpis.append(KPIItem(
        name="labor_cost_ratio",
        label="人工成本率",
        target=labor_target,
        actual=labor_ratio,
        achievement_rate=_rate_inverse(labor_ratio, labor_target),
        trend=_trend_delta(labor_ratio, prev_labor_ratio),
        unit="%",
    ))

    # 4e. 翻台率 (次/桌/日)
    turnover = (total_orders / table_count / business_days) if table_count > 0 and business_days > 0 else 0.0
    prev_biz_days = (prev_end - prev_start).days + 1
    prev_turnover = (prev_total_orders / table_count / prev_biz_days) if table_count > 0 and prev_biz_days > 0 else 0.0
    turnover_target = targets.get("turnover_rate_target")
    kpis.append(KPIItem(
        name="turnover_rate",
        label="翻台率",
        target=turnover_target,
        actual=turnover,
        achievement_rate=_rate(turnover, turnover_target),
        trend=_trend(turnover, prev_turnover),
        unit="次/桌/日",
    ))

    # 4f. 损耗率 (%)
    waste_ratio = (waste_fen / purchase_fen * 100) if purchase_fen > 0 else 0.0
    prev_waste_ratio = (prev_waste / prev_purchase * 100) if prev_purchase > 0 else 0.0
    waste_target = targets.get("waste_rate_target")
    kpis.append(KPIItem(
        name="waste_rate",
        label="损耗率",
        target=waste_target,
        actual=waste_ratio,
        achievement_rate=_rate_inverse(waste_ratio, waste_target),
        trend=_trend_delta(waste_ratio, prev_waste_ratio),
        unit="%",
    ))

    # ── 5. Overall achievement ───────────────────────────────────────────
    rates = [k.achievement_rate for k in kpis if k.achievement_rate is not None]
    overall = sum(rates) / len(rates) if rates else None

    log.info(
        "target_achievement_computed",
        store_id=store_id,
        period=period,
        start=str(start_date),
        end=str(end_date),
        overall_rate=overall,
    )

    return {
        "kpis": [k.to_dict() for k in kpis],
        "overall_rate": round(overall, 2) if overall is not None else None,
        "period": {
            "start": str(start_date),
            "end": str(end_date),
            "business_days": business_days,
        },
    }


# ── 辅助计算 ─────────────────────────────────────────────────────────────────

def _rate(actual: float, target: float | None) -> float | None:
    """Achievement rate: actual / target * 100.  Higher is better."""
    if target is None or target == 0:
        return None
    return actual / target * 100


def _rate_inverse(actual: float, target: float | None) -> float | None:
    """Achievement rate for 'lower is better' KPIs: target / actual * 100.

    E.g. cost_ratio target=30%, actual=25% → 120% (beating target).
    If actual is 0, treat as perfect (return 100 if target > 0).
    """
    if target is None:
        return None
    if actual == 0:
        return 100.0 if target > 0 else None
    return target / actual * 100


def _trend(current: float, previous: float) -> float | None:
    """Percentage change vs previous period.  Returns None if no baseline."""
    if previous == 0:
        return None
    return (current - previous) / previous * 100


def _trend_delta(current: float, previous: float) -> float | None:
    """Absolute delta for ratio KPIs (percentage-point change).

    Negative means improvement for cost/waste ratios.
    """
    if previous == 0 and current == 0:
        return None
    return current - previous
