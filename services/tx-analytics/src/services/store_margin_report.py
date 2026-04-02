"""门店毛利日报 — 营收/成本/毛利综合报表

汇总门店日度毛利数据，包含理论成本、实际成本、成本偏差、
TOP 成本菜品、异常预警等。

金额单位: 分(fen), int
毛利率: 百分比, Decimal(5,2)
"""
import uuid
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

import structlog

log = structlog.get_logger()

# ─── 默认配置 ───
COST_VARIANCE_WARNING_PCT = Decimal("5.00")    # 成本偏差 >5% 预警
COST_VARIANCE_CRITICAL_PCT = Decimal("10.00")  # 成本偏差 >10% 严重
TARGET_MARGIN_RATE = Decimal("60.00")          # 目标毛利率 60%
TOP_COST_DISH_COUNT = 5                        # TOP 成本菜品数量


# ─── 纯函数 ───

def compute_margin_rate(revenue_fen: int, cost_fen: int) -> Decimal:
    """计算毛利率（百分比）"""
    if revenue_fen <= 0:
        return Decimal("0.00")
    return ((Decimal(revenue_fen - cost_fen) / Decimal(revenue_fen)) * 100).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def compute_cost_variance(
    theoretical_cost_fen: int,
    actual_cost_fen: int,
) -> dict:
    """计算成本偏差

    Returns:
        {
            "variance_fen": int,         -- 实际 - 理论（正=超支）
            "variance_rate": Decimal,    -- 偏差百分比
            "status": str,               -- ok / warning / critical
        }
    """
    variance_fen = actual_cost_fen - theoretical_cost_fen

    if theoretical_cost_fen > 0:
        variance_rate = (
            Decimal(abs(variance_fen)) / Decimal(theoretical_cost_fen) * 100
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        variance_rate = Decimal("0.00")

    if variance_rate >= COST_VARIANCE_CRITICAL_PCT:
        status = "critical"
    elif variance_rate >= COST_VARIANCE_WARNING_PCT:
        status = "warning"
    else:
        status = "ok"

    return {
        "variance_fen": variance_fen,
        "variance_rate": variance_rate,
        "status": status,
    }


def build_daily_report(
    store_id: str,
    report_date: str,
    revenue_fen: int,
    theoretical_cost_fen: int,
    actual_cost_fen: int,
    top_cost_dishes: list[dict],
) -> dict:
    """纯函数：组装日报数据结构"""
    theoretical_margin_rate = compute_margin_rate(revenue_fen, theoretical_cost_fen)
    actual_margin_rate = compute_margin_rate(revenue_fen, actual_cost_fen)
    variance = compute_cost_variance(theoretical_cost_fen, actual_cost_fen)

    # 生成预警
    alerts = []
    if actual_margin_rate < TARGET_MARGIN_RATE:
        alerts.append({
            "type": "low_margin",
            "message": f"实际毛利率 {actual_margin_rate}% 低于目标 {TARGET_MARGIN_RATE}%",
            "severity": "warning" if actual_margin_rate >= TARGET_MARGIN_RATE - 10 else "critical",
        })
    if variance["status"] != "ok":
        alerts.append({
            "type": "cost_variance",
            "message": f"成本偏差 {variance['variance_rate']}%（{variance['status']}）",
            "severity": variance["status"],
        })

    return {
        "store_id": store_id,
        "date": report_date,
        "revenue_fen": revenue_fen,
        "theoretical_cost_fen": theoretical_cost_fen,
        "actual_cost_fen": actual_cost_fen,
        "theoretical_margin_rate": theoretical_margin_rate,
        "actual_margin_rate": actual_margin_rate,
        "cost_variance_fen": variance["variance_fen"],
        "cost_variance_rate": variance["variance_rate"],
        "cost_variance_status": variance["status"],
        "top_cost_dishes": top_cost_dishes[:TOP_COST_DISH_COUNT],
        "alerts": alerts,
    }


# ─── 业务函数 ───

def generate_daily_margin_report(
    store_id: uuid.UUID,
    report_date: date,
    tenant_id: uuid.UUID,
    db,
) -> dict:
    """生成门店毛利日报

    Returns:
        {
            "store_id", "date",
            "revenue_fen", "theoretical_cost_fen", "actual_cost_fen",
            "theoretical_margin_rate", "actual_margin_rate",
            "cost_variance_fen", "cost_variance_rate", "cost_variance_status",
            "top_cost_dishes", "alerts",
        }
    """
    # 1. 查询当日营收
    revenue_fen = _get_daily_revenue(store_id, report_date, tenant_id, db)

    # 2. 查询理论成本（从 tx-supply 获取）
    theoretical_cost_fen = _get_daily_theoretical_cost(store_id, report_date, tenant_id, db)

    # 3. 查询实际成本
    actual_cost_fen = _get_daily_actual_cost(store_id, report_date, tenant_id, db)

    # 4. TOP 成本菜品
    top_cost_dishes = _get_top_cost_dishes(store_id, report_date, tenant_id, db)

    report = build_daily_report(
        store_id=str(store_id),
        report_date=str(report_date),
        revenue_fen=revenue_fen,
        theoretical_cost_fen=theoretical_cost_fen,
        actual_cost_fen=actual_cost_fen,
        top_cost_dishes=top_cost_dishes,
    )

    log.info(
        "store_margin_report.daily_generated",
        store_id=str(store_id),
        date=str(report_date),
        revenue_fen=revenue_fen,
        theoretical_margin=str(report["theoretical_margin_rate"]),
        actual_margin=str(report["actual_margin_rate"]),
        alert_count=len(report["alerts"]),
    )
    return report


def generate_period_margin_trend(
    store_id: uuid.UUID,
    start_date: date,
    end_date: date,
    tenant_id: uuid.UUID,
    db,
) -> dict:
    """生成门店毛利趋势数据

    Returns:
        {
            "store_id": str,
            "start_date": str,
            "end_date": str,
            "daily_data": [
                {"date", "revenue_fen", "cost_fen", "margin_rate"}
            ],
            "summary": {
                "total_revenue_fen", "total_cost_fen",
                "avg_margin_rate", "min_margin_rate", "max_margin_rate",
                "trend_direction",  -- up / down / stable
            },
        }
    """
    daily_data = []
    current = start_date

    while current <= end_date:
        revenue = _get_daily_revenue(store_id, current, tenant_id, db)
        cost = _get_daily_actual_cost(store_id, current, tenant_id, db)
        margin_rate = compute_margin_rate(revenue, cost)

        daily_data.append({
            "date": str(current),
            "revenue_fen": revenue,
            "cost_fen": cost,
            "margin_rate": margin_rate,
        })
        current += timedelta(days=1)

    # 汇总
    total_revenue = sum(d["revenue_fen"] for d in daily_data)
    total_cost = sum(d["cost_fen"] for d in daily_data)
    rates = [d["margin_rate"] for d in daily_data if d["revenue_fen"] > 0]

    avg_rate = (sum(rates) / len(rates)).quantize(Decimal("0.01")) if rates else Decimal("0.00")
    min_rate = min(rates) if rates else Decimal("0.00")
    max_rate = max(rates) if rates else Decimal("0.00")

    # 简单趋势判断：比较前半段和后半段均值
    trend = "stable"
    if len(rates) >= 4:
        mid = len(rates) // 2
        first_half_avg = sum(rates[:mid]) / mid
        second_half_avg = sum(rates[mid:]) / (len(rates) - mid)
        diff = second_half_avg - first_half_avg
        if diff > Decimal("2.00"):
            trend = "up"
        elif diff < Decimal("-2.00"):
            trend = "down"

    result = {
        "store_id": str(store_id),
        "start_date": str(start_date),
        "end_date": str(end_date),
        "daily_data": daily_data,
        "summary": {
            "total_revenue_fen": total_revenue,
            "total_cost_fen": total_cost,
            "avg_margin_rate": avg_rate,
            "min_margin_rate": min_rate,
            "max_margin_rate": max_rate,
            "trend_direction": trend,
        },
    }

    log.info(
        "store_margin_report.trend_generated",
        store_id=str(store_id),
        days=len(daily_data),
        avg_margin=str(avg_rate),
        trend=trend,
    )
    return result


# ─── DB 访问桩 ───

def _get_daily_revenue(
    store_id: uuid.UUID,
    target_date: date,
    tenant_id: uuid.UUID,
    db,
) -> int:
    """查询门店当日营收（分）"""
    if db is None:
        return 0
    try:
        from sqlalchemy import text
        result = db.execute(text("""
            SELECT COALESCE(SUM(final_amount_fen), 0)
            FROM orders
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND DATE(order_time) = :target_date
              AND status IN ('completed', 'paid')
              AND is_deleted = FALSE
        """), {"store_id": store_id, "tenant_id": tenant_id, "target_date": target_date})
        return result.scalar_one_or_none() or 0
    except (ImportError, AttributeError):
        return 0


def _get_daily_theoretical_cost(
    store_id: uuid.UUID,
    target_date: date,
    tenant_id: uuid.UUID,
    db,
) -> int:
    """查询门店当日理论成本（通过跨服务调用 tx-supply）

    实际项目中通过 HTTP 调用 tx-supply 的 batch_calculate_daily_costs。
    此处直接查询 order_items.food_cost_fen 作为近似。
    """
    if db is None:
        return 0
    try:
        from sqlalchemy import text
        result = db.execute(text("""
            SELECT COALESCE(SUM(oi.food_cost_fen * oi.quantity), 0)
            FROM order_items oi
            JOIN orders o ON oi.order_id = o.id
            WHERE o.store_id = :store_id
              AND o.tenant_id = :tenant_id
              AND DATE(o.order_time) = :target_date
              AND o.status IN ('completed', 'paid')
              AND o.is_deleted = FALSE
              AND oi.is_deleted = FALSE
              AND oi.food_cost_fen IS NOT NULL
        """), {"store_id": store_id, "tenant_id": tenant_id, "target_date": target_date})
        return result.scalar_one_or_none() or 0
    except (ImportError, AttributeError):
        return 0


def _get_daily_actual_cost(
    store_id: uuid.UUID,
    target_date: date,
    tenant_id: uuid.UUID,
    db,
) -> int:
    """查询门店当日实际成本（从库存消耗流水汇总）"""
    if db is None:
        return 0
    try:
        from sqlalchemy import text
        result = db.execute(text("""
            SELECT COALESCE(SUM(ABS(total_cost_fen)), 0)
            FROM ingredient_transactions
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND transaction_type = 'usage'
              AND DATE(transaction_time) = :target_date
              AND is_deleted = FALSE
        """), {"store_id": store_id, "tenant_id": tenant_id, "target_date": target_date})
        return result.scalar_one_or_none() or 0
    except (ImportError, AttributeError):
        return 0


def _get_top_cost_dishes(
    store_id: uuid.UUID,
    target_date: date,
    tenant_id: uuid.UUID,
    db,
    limit: int = TOP_COST_DISH_COUNT,
) -> list[dict]:
    """查询当日成本最高的菜品"""
    if db is None:
        return []
    try:
        from sqlalchemy import text
        result = db.execute(text("""
            SELECT oi.dish_id, d.dish_name,
                   SUM(oi.quantity) as qty,
                   SUM(COALESCE(oi.food_cost_fen, 0) * oi.quantity) as total_cost_fen,
                   SUM(oi.subtotal_fen) as total_revenue_fen
            FROM order_items oi
            JOIN orders o ON oi.order_id = o.id
            JOIN dishes d ON oi.dish_id = d.id
            WHERE o.store_id = :store_id
              AND o.tenant_id = :tenant_id
              AND DATE(o.order_time) = :target_date
              AND o.status IN ('completed', 'paid')
              AND o.is_deleted = FALSE
              AND oi.is_deleted = FALSE
            GROUP BY oi.dish_id, d.dish_name
            ORDER BY total_cost_fen DESC
            LIMIT :limit
        """), {
            "store_id": store_id,
            "tenant_id": tenant_id,
            "target_date": target_date,
            "limit": limit,
        })
        return [dict(row) for row in result.mappings().all()]
    except (ImportError, AttributeError):
        return []
