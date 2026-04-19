"""门店经营分析服务 — 营收/翻台深度/桌均客单/高峰时段/班次/多店对比

为 tx-analytics 域G 提供门店经营深度分析能力。
金额单位统一为分(fen)，比率为百分比 Decimal(5,2)。

复用 table_analytics.py 翻台基础能力。
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .table_analytics import calculate_turnover_rate

logger = structlog.get_logger()


# ─── 辅助函数 ───


def _date_range_to_timestamps(
    date_range: tuple[date, date],
) -> tuple[datetime, datetime]:
    """将日期范围转为 UTC datetime 区间 [start, end)"""
    start_date, end_date = date_range
    day_start = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)
    day_end = datetime(end_date.year, end_date.month, end_date.day, tzinfo=timezone.utc) + timedelta(days=1)
    return day_start, day_end


def _safe_avg_fen(total_fen: int, count: int) -> int:
    """安全计算平均值(分)，count=0 时返回 0"""
    return total_fen // count if count > 0 else 0


def _pct(numerator: float, denominator: float) -> Decimal:
    """计算百分比，保留两位小数"""
    if denominator <= 0:
        return Decimal("0.00")
    return Decimal(str(numerator / denominator * 100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _determine_meal_period(hour: int) -> str:
    """根据小时判断餐段"""
    if 6 <= hour < 10:
        return "breakfast"
    if 10 <= hour < 14:
        return "lunch"
    if 14 <= hour < 17:
        return "afternoon_tea"
    if 17 <= hour < 21:
        return "dinner"
    return "late_night"


# ─── 1. 营收分析 ───


async def revenue_analysis(
    store_id: uuid.UUID,
    date_range: tuple[date, date],
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> dict:
    """营收分析

    Args:
        store_id: 门店ID
        date_range: (start_date, end_date) 含首尾
        tenant_id: 租户ID
        db: 异步数据库会话

    Returns:
        {
            "store_id": str,
            "date_range": [str, str],
            "daily_revenue": [{"date": str, "revenue_fen": int, "order_count": int}],
            "by_channel": [{"channel": str, "revenue_fen": int, "pct": Decimal}],
            "by_meal_period": [{"period": str, "revenue_fen": int, "pct": Decimal}],
            "trend": {"direction": str, "avg_daily_fen": int, "total_fen": int},
        }
    """
    start_date, end_date = date_range
    day_start, day_end = _date_range_to_timestamps(date_range)
    params = {
        "store_id": store_id,
        "tenant_id": tenant_id,
        "day_start": day_start,
        "day_end": day_end,
    }

    # 每日营收
    daily_result = await db.execute(
        text("""
            SELECT DATE(created_at) AS d,
                   COALESCE(SUM(total_amount_fen), 0) AS revenue_fen,
                   COUNT(*) AS order_count
            FROM orders
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND created_at >= :day_start
              AND created_at < :day_end
              AND status = 'paid'
              AND is_deleted = false
            GROUP BY DATE(created_at)
            ORDER BY d
        """),
        params,
    )
    daily_rows = daily_result.mappings().all()
    daily_revenue = [
        {
            "date": str(r["d"]),
            "revenue_fen": int(r["revenue_fen"]),
            "order_count": int(r["order_count"]),
        }
        for r in daily_rows
    ]

    total_fen = sum(d["revenue_fen"] for d in daily_revenue)
    total_days = max((end_date - start_date).days + 1, 1)
    avg_daily_fen = total_fen // total_days

    # 趋势判断：前半段 vs 后半段
    mid = len(daily_revenue) // 2
    if len(daily_revenue) >= 4:
        first_half_avg = sum(d["revenue_fen"] for d in daily_revenue[:mid]) / mid
        second_half_avg = sum(d["revenue_fen"] for d in daily_revenue[mid:]) / (len(daily_revenue) - mid)
        if second_half_avg > first_half_avg * 1.02:
            direction = "up"
        elif second_half_avg < first_half_avg * 0.98:
            direction = "down"
        else:
            direction = "flat"
    else:
        direction = "flat"

    # 按渠道
    channel_result = await db.execute(
        text("""
            SELECT COALESCE(channel, 'dine_in') AS channel,
                   COALESCE(SUM(total_amount_fen), 0) AS revenue_fen
            FROM orders
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND created_at >= :day_start
              AND created_at < :day_end
              AND status = 'paid'
              AND is_deleted = false
            GROUP BY COALESCE(channel, 'dine_in')
            ORDER BY revenue_fen DESC
        """),
        params,
    )
    channel_rows = channel_result.mappings().all()
    by_channel = [
        {
            "channel": r["channel"],
            "revenue_fen": int(r["revenue_fen"]),
            "pct": _pct(int(r["revenue_fen"]), total_fen),
        }
        for r in channel_rows
    ]

    # 按餐段
    meal_result = await db.execute(
        text("""
            SELECT EXTRACT(HOUR FROM created_at)::int AS hour,
                   COALESCE(SUM(total_amount_fen), 0) AS revenue_fen
            FROM orders
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND created_at >= :day_start
              AND created_at < :day_end
              AND status = 'paid'
              AND is_deleted = false
            GROUP BY EXTRACT(HOUR FROM created_at)::int
        """),
        params,
    )
    meal_rows = meal_result.mappings().all()
    period_map: dict[str, int] = {}
    for r in meal_rows:
        period = _determine_meal_period(int(r["hour"]))
        period_map[period] = period_map.get(period, 0) + int(r["revenue_fen"])

    by_meal_period = [
        {"period": p, "revenue_fen": v, "pct": _pct(v, total_fen)}
        for p, v in sorted(period_map.items(), key=lambda x: x[1], reverse=True)
    ]

    logger.info(
        "revenue_analysis_completed",
        store_id=str(store_id),
        tenant_id=str(tenant_id),
        total_fen=total_fen,
        days=total_days,
    )

    return {
        "store_id": str(store_id),
        "date_range": [str(start_date), str(end_date)],
        "daily_revenue": daily_revenue,
        "by_channel": by_channel,
        "by_meal_period": by_meal_period,
        "trend": {
            "direction": direction,
            "avg_daily_fen": avg_daily_fen,
            "total_fen": total_fen,
        },
    }


# ─── 2. 翻台深度分析 ───


async def turnover_deep_analysis(
    store_id: uuid.UUID,
    date_range: tuple[date, date],
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> dict:
    """翻台深度分析

    复用 table_analytics.calculate_turnover_rate 基础能力，
    增加区域维度、工作日/周末拆分、高峰时段翻台。

    Returns:
        {
            "store_id": str,
            "date_range": [str, str],
            "rate": float,
            "avg_duration_minutes": float,
            "by_area": [{"area": str, "rate": float, "avg_duration_minutes": float}],
            "by_day_type": {"weekday": float, "weekend": float},
            "peak_slots": [{"hour": int, "rate": float}],
        }
    """
    start_date, end_date = date_range
    day_start, day_end = _date_range_to_timestamps(date_range)
    params = {
        "store_id": store_id,
        "tenant_id": tenant_id,
        "day_start": day_start,
        "day_end": day_end,
    }

    # 整体翻台率：逐日计算后取平均
    total_days = (end_date - start_date).days + 1
    rate_sum = 0.0
    duration_sum = 0.0
    valid_days = 0
    weekday_rates: list[float] = []
    weekend_rates: list[float] = []

    current = start_date
    while current <= end_date:
        day_result = await calculate_turnover_rate(store_id, current, tenant_id, db)
        day_rate = day_result["rate"]
        if day_rate > 0:
            rate_sum += day_rate
            duration_sum += day_result["avg_duration_minutes"]
            valid_days += 1
        # 周末: 5=Saturday, 6=Sunday
        if current.weekday() >= 5:
            weekend_rates.append(day_rate)
        else:
            weekday_rates.append(day_rate)
        current += timedelta(days=1)

    avg_rate = round(rate_sum / valid_days, 2) if valid_days > 0 else 0.0
    avg_duration = round(duration_sum / valid_days, 1) if valid_days > 0 else 0.0

    weekday_avg = round(sum(weekday_rates) / len(weekday_rates), 2) if weekday_rates else 0.0
    weekend_avg = round(sum(weekend_rates) / len(weekend_rates), 2) if weekend_rates else 0.0

    # 按区域分析
    area_result = await db.execute(
        text("""
            SELECT t.area,
                   COUNT(o.id) AS order_count,
                   COUNT(DISTINCT t.id) AS table_count,
                   AVG(EXTRACT(EPOCH FROM (o.updated_at - o.created_at)) / 60) AS avg_dur
            FROM orders o
            JOIN tables t ON t.id = o.table_id AND t.tenant_id = o.tenant_id
            WHERE o.store_id = :store_id
              AND o.tenant_id = :tenant_id
              AND o.created_at >= :day_start
              AND o.created_at < :day_end
              AND o.status IN ('paid', 'pending_payment')
              AND o.is_deleted = false
              AND t.is_deleted = false
            GROUP BY t.area
            ORDER BY order_count DESC
        """),
        params,
    )
    area_rows = area_result.mappings().all()

    # 查询各区域桌台总数
    area_tables_result = await db.execute(
        text("""
            SELECT area, COUNT(*) AS cnt
            FROM tables
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND is_deleted = false
              AND is_active = true
            GROUP BY area
        """),
        {"store_id": store_id, "tenant_id": tenant_id},
    )
    area_table_counts = {r["area"]: int(r["cnt"]) for r in area_tables_result.mappings().all()}

    by_area = []
    for r in area_rows:
        area_name = r["area"] or "default"
        table_count = area_table_counts.get(area_name, 1)
        area_rate = round(int(r["order_count"]) / (table_count * total_days), 2) if table_count > 0 else 0.0
        by_area.append(
            {
                "area": area_name,
                "rate": area_rate,
                "avg_duration_minutes": round(float(r["avg_dur"] or 0), 1),
            }
        )

    # 高峰时段翻台
    peak_result = await db.execute(
        text("""
            SELECT EXTRACT(HOUR FROM o.created_at)::int AS hour,
                   COUNT(o.id) AS order_count
            FROM orders o
            WHERE o.store_id = :store_id
              AND o.tenant_id = :tenant_id
              AND o.created_at >= :day_start
              AND o.created_at < :day_end
              AND o.status IN ('paid', 'pending_payment')
              AND o.is_deleted = false
            GROUP BY EXTRACT(HOUR FROM o.created_at)::int
            ORDER BY order_count DESC
            LIMIT 5
        """),
        params,
    )
    # 获取门店总桌台数
    total_tables_result = await db.execute(
        text("""
            SELECT COUNT(*) AS cnt
            FROM tables
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND is_deleted = false
              AND is_active = true
        """),
        {"store_id": store_id, "tenant_id": tenant_id},
    )
    total_tables = total_tables_result.scalar() or 1

    peak_slots = [
        {
            "hour": int(r["hour"]),
            "rate": round(int(r["order_count"]) / (total_tables * total_days), 2),
        }
        for r in peak_result.mappings().all()
    ]

    logger.info(
        "turnover_deep_analysis_completed",
        store_id=str(store_id),
        tenant_id=str(tenant_id),
        rate=avg_rate,
        total_days=total_days,
    )

    return {
        "store_id": str(store_id),
        "date_range": [str(start_date), str(end_date)],
        "rate": avg_rate,
        "avg_duration_minutes": avg_duration,
        "by_area": by_area,
        "by_day_type": {"weekday": weekday_avg, "weekend": weekend_avg},
        "peak_slots": peak_slots,
    }


# ─── 3. 桌均客单分析 ───


async def ticket_analysis(
    store_id: uuid.UUID,
    date_range: tuple[date, date],
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> dict:
    """桌均客单价分析

    Returns:
        {
            "store_id": str,
            "date_range": [str, str],
            "avg_ticket_fen": int,
            "per_capita_fen": int,
            "distribution": [{"range_label": str, "count": int, "pct": Decimal}],
            "by_table_size": [{"seats": int, "avg_ticket_fen": int, "order_count": int}],
        }
    """
    start_date, end_date = date_range
    day_start, day_end = _date_range_to_timestamps(date_range)
    params = {
        "store_id": store_id,
        "tenant_id": tenant_id,
        "day_start": day_start,
        "day_end": day_end,
    }

    # 整体客单
    overall_result = await db.execute(
        text("""
            SELECT COALESCE(AVG(total_amount_fen), 0) AS avg_ticket_fen,
                   COALESCE(SUM(total_amount_fen), 0) AS total_fen,
                   COALESCE(SUM(guest_count), 0) AS total_guests,
                   COUNT(*) AS order_count
            FROM orders
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND created_at >= :day_start
              AND created_at < :day_end
              AND status = 'paid'
              AND is_deleted = false
        """),
        params,
    )
    overall = overall_result.mappings().first()
    avg_ticket_fen = int(overall["avg_ticket_fen"]) if overall else 0
    total_guests = int(overall["total_guests"]) if overall else 0
    total_fen = int(overall["total_fen"]) if overall else 0
    per_capita_fen = total_fen // total_guests if total_guests > 0 else 0
    order_count = int(overall["order_count"]) if overall else 0

    # 客单价分布（分段统计）
    dist_result = await db.execute(
        text("""
            SELECT
                CASE
                    WHEN total_amount_fen < 5000 THEN '0-50'
                    WHEN total_amount_fen < 10000 THEN '50-100'
                    WHEN total_amount_fen < 20000 THEN '100-200'
                    WHEN total_amount_fen < 50000 THEN '200-500'
                    ELSE '500+'
                END AS range_label,
                COUNT(*) AS cnt
            FROM orders
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND created_at >= :day_start
              AND created_at < :day_end
              AND status = 'paid'
              AND is_deleted = false
            GROUP BY range_label
            ORDER BY MIN(total_amount_fen)
        """),
        params,
    )
    dist_rows = dist_result.mappings().all()
    distribution = [
        {
            "range_label": r["range_label"],
            "count": int(r["cnt"]),
            "pct": _pct(int(r["cnt"]), order_count),
        }
        for r in dist_rows
    ]

    # 按桌台规格
    by_size_result = await db.execute(
        text("""
            SELECT t.seats,
                   COALESCE(AVG(o.total_amount_fen), 0) AS avg_ticket_fen,
                   COUNT(o.id) AS order_count
            FROM orders o
            JOIN tables t ON t.id = o.table_id AND t.tenant_id = o.tenant_id
            WHERE o.store_id = :store_id
              AND o.tenant_id = :tenant_id
              AND o.created_at >= :day_start
              AND o.created_at < :day_end
              AND o.status = 'paid'
              AND o.is_deleted = false
              AND t.is_deleted = false
            GROUP BY t.seats
            ORDER BY t.seats
        """),
        params,
    )
    by_table_size = [
        {
            "seats": int(r["seats"]),
            "avg_ticket_fen": int(r["avg_ticket_fen"]),
            "order_count": int(r["order_count"]),
        }
        for r in by_size_result.mappings().all()
    ]

    logger.info(
        "ticket_analysis_completed",
        store_id=str(store_id),
        tenant_id=str(tenant_id),
        avg_ticket_fen=avg_ticket_fen,
        per_capita_fen=per_capita_fen,
    )

    return {
        "store_id": str(store_id),
        "date_range": [str(start_date), str(end_date)],
        "avg_ticket_fen": avg_ticket_fen,
        "per_capita_fen": per_capita_fen,
        "distribution": distribution,
        "by_table_size": by_table_size,
    }


# ─── 4. 高峰时段分析 ───


async def peak_hour_analysis(
    store_id: uuid.UUID,
    date_range: tuple[date, date],
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> dict:
    """高峰时段分析

    Returns:
        {
            "store_id": str,
            "date_range": [str, str],
            "hourly_revenue": [{"hour": int, "revenue_fen": int}],
            "hourly_orders": [{"hour": int, "order_count": int}],
            "peak_lunch": {"hour": int, "revenue_fen": int},
            "peak_dinner": {"hour": int, "revenue_fen": int},
            "idle_slots": [int],
        }
    """
    start_date, end_date = date_range
    day_start, day_end = _date_range_to_timestamps(date_range)
    params = {
        "store_id": store_id,
        "tenant_id": tenant_id,
        "day_start": day_start,
        "day_end": day_end,
    }

    hourly_result = await db.execute(
        text("""
            SELECT EXTRACT(HOUR FROM created_at)::int AS hour,
                   COALESCE(SUM(total_amount_fen), 0) AS revenue_fen,
                   COUNT(*) AS order_count
            FROM orders
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND created_at >= :day_start
              AND created_at < :day_end
              AND status = 'paid'
              AND is_deleted = false
            GROUP BY EXTRACT(HOUR FROM created_at)::int
            ORDER BY hour
        """),
        params,
    )
    hourly_rows = hourly_result.mappings().all()

    hourly_revenue = [{"hour": int(r["hour"]), "revenue_fen": int(r["revenue_fen"])} for r in hourly_rows]
    hourly_orders = [{"hour": int(r["hour"]), "order_count": int(r["order_count"])} for r in hourly_rows]

    # 构建 hour -> revenue_fen 映射
    hour_rev_map = {int(r["hour"]): int(r["revenue_fen"]) for r in hourly_rows}

    # 午餐高峰 (10-14)
    lunch_hours = {h: v for h, v in hour_rev_map.items() if 10 <= h < 14}
    if lunch_hours:
        peak_lunch_hour = max(lunch_hours, key=lunch_hours.get)
        peak_lunch = {"hour": peak_lunch_hour, "revenue_fen": lunch_hours[peak_lunch_hour]}
    else:
        peak_lunch = {"hour": 12, "revenue_fen": 0}

    # 晚餐高峰 (17-21)
    dinner_hours = {h: v for h, v in hour_rev_map.items() if 17 <= h < 21}
    if dinner_hours:
        peak_dinner_hour = max(dinner_hours, key=dinner_hours.get)
        peak_dinner = {"hour": peak_dinner_hour, "revenue_fen": dinner_hours[peak_dinner_hour]}
    else:
        peak_dinner = {"hour": 18, "revenue_fen": 0}

    # 空闲时段：营业时间内(9-22)无订单或极低
    active_hours = set(hour_rev_map.keys())
    operating_hours = set(range(9, 22))
    idle_slots = sorted(operating_hours - active_hours)

    # 补充：有订单但极少的时段也算空闲（低于平均值 20%）
    if hour_rev_map:
        avg_hourly = sum(hour_rev_map.values()) / len(hour_rev_map)
        threshold = avg_hourly * 0.2
        for h in operating_hours & active_hours:
            if hour_rev_map[h] < threshold and h not in idle_slots:
                idle_slots.append(h)
        idle_slots.sort()

    logger.info(
        "peak_hour_analysis_completed",
        store_id=str(store_id),
        tenant_id=str(tenant_id),
        peak_lunch_hour=peak_lunch["hour"],
        peak_dinner_hour=peak_dinner["hour"],
        idle_count=len(idle_slots),
    )

    return {
        "store_id": str(store_id),
        "date_range": [str(start_date), str(end_date)],
        "hourly_revenue": hourly_revenue,
        "hourly_orders": hourly_orders,
        "peak_lunch": peak_lunch,
        "peak_dinner": peak_dinner,
        "idle_slots": idle_slots,
    }


# ─── 5. 班次分析 ───


async def shift_analysis(
    store_id: uuid.UUID,
    date_range: tuple[date, date],
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> dict:
    """班次经营分析

    班次定义：早班 06:00-14:00 / 晚班 14:00-22:00 / 夜班 22:00-06:00

    Returns:
        {
            "store_id": str,
            "date_range": [str, str],
            "by_shift": [
                {
                    "shift": str,
                    "revenue_fen": int,
                    "orders": int,
                    "avg_ticket_fen": int,
                    "staff_count": int,
                    "per_capita_revenue_fen": int,
                }
            ],
        }
    """
    start_date, end_date = date_range
    day_start, day_end = _date_range_to_timestamps(date_range)
    params = {
        "store_id": store_id,
        "tenant_id": tenant_id,
        "day_start": day_start,
        "day_end": day_end,
    }

    # 按班次查询营收
    shift_revenue_result = await db.execute(
        text("""
            SELECT
                CASE
                    WHEN EXTRACT(HOUR FROM created_at) >= 6
                         AND EXTRACT(HOUR FROM created_at) < 14 THEN 'morning'
                    WHEN EXTRACT(HOUR FROM created_at) >= 14
                         AND EXTRACT(HOUR FROM created_at) < 22 THEN 'evening'
                    ELSE 'night'
                END AS shift,
                COALESCE(SUM(total_amount_fen), 0) AS revenue_fen,
                COUNT(*) AS orders
            FROM orders
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND created_at >= :day_start
              AND created_at < :day_end
              AND status = 'paid'
              AND is_deleted = false
            GROUP BY shift
            ORDER BY MIN(EXTRACT(HOUR FROM created_at))
        """),
        params,
    )
    shift_rows = shift_revenue_result.mappings().all()

    # 查询班次排班人数
    staff_result = await db.execute(
        text("""
            SELECT
                CASE
                    WHEN shift_type = 'morning' THEN 'morning'
                    WHEN shift_type = 'evening' THEN 'evening'
                    WHEN shift_type = 'night' THEN 'night'
                    ELSE 'morning'
                END AS shift,
                COUNT(DISTINCT employee_id) AS staff_count
            FROM schedules
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND schedule_date >= :day_start
              AND schedule_date < :day_end
              AND is_deleted = false
            GROUP BY shift
        """),
        params,
    )
    staff_map = {r["shift"]: int(r["staff_count"]) for r in staff_result.mappings().all()}

    by_shift = []
    for r in shift_rows:
        shift_name = r["shift"]
        revenue_fen = int(r["revenue_fen"])
        orders = int(r["orders"])
        avg_ticket = _safe_avg_fen(revenue_fen, orders)
        staff_count = staff_map.get(shift_name, 0)
        per_capita_revenue = revenue_fen // staff_count if staff_count > 0 else 0

        by_shift.append(
            {
                "shift": shift_name,
                "revenue_fen": revenue_fen,
                "orders": orders,
                "avg_ticket_fen": avg_ticket,
                "staff_count": staff_count,
                "per_capita_revenue_fen": per_capita_revenue,
            }
        )

    logger.info(
        "shift_analysis_completed",
        store_id=str(store_id),
        tenant_id=str(tenant_id),
        shift_count=len(by_shift),
    )

    return {
        "store_id": str(store_id),
        "date_range": [str(start_date), str(end_date)],
        "by_shift": by_shift,
    }


# ─── 6. 多店对比 ───


async def store_comparison(
    store_ids: list[uuid.UUID],
    metrics: list[str],
    date_range: tuple[date, date],
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> dict:
    """多店多维对比矩阵

    Args:
        store_ids: 门店ID列表
        metrics: 指标列表，支持 revenue/orders/avg_ticket/turnover/per_capita
        date_range: (start_date, end_date)
        tenant_id: 租户ID
        db: 异步数据库会话

    Returns:
        {
            "date_range": [str, str],
            "metrics": [str],
            "stores": [
                {
                    "store_id": str,
                    "store_name": str,
                    "values": {"revenue": int, "orders": int, ...},
                    "ranks": {"revenue": int, "orders": int, ...},
                }
            ],
        }
    """
    VALID_COMPARISON_METRICS = {"revenue", "orders", "avg_ticket", "turnover", "per_capita"}
    for m in metrics:
        if m not in VALID_COMPARISON_METRICS:
            raise ValueError(f"invalid metric: {m}, must be one of {VALID_COMPARISON_METRICS}")

    start_date, end_date = date_range
    day_start, day_end = _date_range_to_timestamps(date_range)
    total_days = max((end_date - start_date).days + 1, 1)

    # 查询所有目标门店的核心指标
    store_id_strs = [str(sid) for sid in store_ids]
    result = await db.execute(
        text("""
            SELECT s.id AS store_id,
                   s.store_name,
                   COALESCE(SUM(o.total_amount_fen), 0) AS revenue_fen,
                   COUNT(o.id) AS order_count,
                   COALESCE(AVG(o.total_amount_fen), 0) AS avg_ticket_fen,
                   COALESCE(SUM(o.guest_count), 0) AS total_guests
            FROM stores s
            LEFT JOIN orders o ON o.store_id = s.id
                AND o.tenant_id = s.tenant_id
                AND o.created_at >= :day_start
                AND o.created_at < :day_end
                AND o.status = 'paid'
                AND o.is_deleted = false
            WHERE s.id = ANY(:store_ids)
              AND s.tenant_id = :tenant_id
              AND s.is_deleted = false
            GROUP BY s.id, s.store_name
        """),
        {
            "store_ids": store_id_strs,
            "tenant_id": tenant_id,
            "day_start": day_start,
            "day_end": day_end,
        },
    )
    rows = result.mappings().all()

    # 查询各门店桌台数（用于翻台率）
    tables_result = await db.execute(
        text("""
            SELECT store_id, COUNT(*) AS cnt
            FROM tables
            WHERE store_id = ANY(:store_ids)
              AND tenant_id = :tenant_id
              AND is_deleted = false
              AND is_active = true
            GROUP BY store_id
        """),
        {"store_ids": store_id_strs, "tenant_id": tenant_id},
    )
    table_counts = {str(r["store_id"]): int(r["cnt"]) for r in tables_result.mappings().all()}

    # 构建门店数据
    stores_data = []
    for r in rows:
        sid = str(r["store_id"])
        revenue = int(r["revenue_fen"])
        orders = int(r["order_count"])
        avg_ticket = int(r["avg_ticket_fen"])
        total_guests = int(r["total_guests"])
        per_capita = revenue // total_guests if total_guests > 0 else 0
        table_count = table_counts.get(sid, 1)
        turnover_rate = round(orders / (table_count * total_days), 2) if table_count > 0 else 0.0

        values = {
            "revenue": revenue,
            "orders": orders,
            "avg_ticket": avg_ticket,
            "turnover": turnover_rate,
            "per_capita": per_capita,
        }
        # 只保留请求的指标
        filtered_values = {m: values[m] for m in metrics}

        stores_data.append(
            {
                "store_id": sid,
                "store_name": r["store_name"],
                "values": filtered_values,
                "ranks": {},  # 下面计算
            }
        )

    # 计算排名
    for m in metrics:
        sorted_stores = sorted(
            stores_data,
            key=lambda x: x["values"].get(m, 0),
            reverse=True,
        )
        for rank, store in enumerate(sorted_stores, 1):
            store["ranks"][m] = rank

    logger.info(
        "store_comparison_completed",
        tenant_id=str(tenant_id),
        store_count=len(stores_data),
        metrics=metrics,
    )

    return {
        "date_range": [str(start_date), str(end_date)],
        "metrics": metrics,
        "stores": stores_data,
    }
