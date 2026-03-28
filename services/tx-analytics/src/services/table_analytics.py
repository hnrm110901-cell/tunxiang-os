"""翻台分析服务 — 翻台率/时段热力图/包厢营收

为 tx-analytics 域G 提供桌台经营分析能力。
金额单位统一为分(fen)。
"""
import uuid
from datetime import datetime, date, timedelta, timezone

import structlog
from sqlalchemy import select, func, text, and_
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


# ─── 翻台率计算 ───


async def calculate_turnover_rate(
    store_id: uuid.UUID,
    target_date: date,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> dict:
    """计算指定日期的翻台率

    翻台率 = 当日总入座批次 / 可用桌台总数

    Returns:
        {
            "rate": float,
            "avg_duration_minutes": float,
            "total_seated": int,
            "total_tables": int,
            "date": str,
        }
    """
    # 查询门店桌台总数（从 tables 表）
    from services.tx_trade_models import Table  # 跨域查询需通过 shared view 或直接 SQL

    # 使用原生 SQL 查询 tables 表中该门店的桌台数
    total_tables_result = await db.execute(
        text("""
            SELECT COUNT(*) as cnt
            FROM tables
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND is_deleted = false
              AND is_active = true
        """),
        {"store_id": store_id, "tenant_id": tenant_id},
    )
    total_tables = total_tables_result.scalar() or 0

    # 查询当日已完成的订单数（作为入座批次近似值）
    day_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)

    orders_result = await db.execute(
        text("""
            SELECT
                COUNT(*) as total_seated,
                AVG(EXTRACT(EPOCH FROM (updated_at - created_at)) / 60) as avg_duration_min
            FROM orders
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND created_at >= :day_start
              AND created_at < :day_end
              AND status IN ('paid', 'pending_payment')
              AND is_deleted = false
        """),
        {
            "store_id": store_id,
            "tenant_id": tenant_id,
            "day_start": day_start,
            "day_end": day_end,
        },
    )
    row = orders_result.mappings().first()
    total_seated = int(row["total_seated"]) if row and row["total_seated"] else 0
    avg_duration = round(float(row["avg_duration_min"]), 1) if row and row["avg_duration_min"] else 0.0

    rate = round(total_seated / total_tables, 2) if total_tables > 0 else 0.0

    logger.info(
        "turnover_rate_calculated",
        store_id=str(store_id),
        tenant_id=str(tenant_id),
        date=str(target_date),
        rate=rate,
        total_seated=total_seated,
        total_tables=total_tables,
    )

    return {
        "rate": rate,
        "avg_duration_minutes": avg_duration,
        "total_seated": total_seated,
        "total_tables": total_tables,
        "date": str(target_date),
    }


# ─── 时段热力图 ───


async def get_table_heatmap(
    store_id: uuid.UUID,
    target_date: date,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> dict:
    """获取时段 x 桌台热力图数据

    按小时统计每张桌台的使用情况。

    Returns:
        {
            "date": str,
            "hours": [0..23],
            "tables": [{"table_no": str, "usage": {hour: count}}],
            "hourly_totals": {hour: total_count},
        }
    """
    day_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)

    # 查询当日各桌台各小时的订单分布
    heatmap_result = await db.execute(
        text("""
            SELECT
                t.table_no,
                EXTRACT(HOUR FROM o.created_at) as hour,
                COUNT(*) as cnt
            FROM orders o
            JOIN tables t ON t.id = o.table_id AND t.tenant_id = o.tenant_id
            WHERE o.store_id = :store_id
              AND o.tenant_id = :tenant_id
              AND o.created_at >= :day_start
              AND o.created_at < :day_end
              AND o.is_deleted = false
            GROUP BY t.table_no, EXTRACT(HOUR FROM o.created_at)
            ORDER BY t.table_no, hour
        """),
        {
            "store_id": store_id,
            "tenant_id": tenant_id,
            "day_start": day_start,
            "day_end": day_end,
        },
    )

    rows = heatmap_result.mappings().all()

    # 组装热力图
    tables_map: dict[str, dict[int, int]] = {}
    hourly_totals: dict[int, int] = {h: 0 for h in range(24)}

    for row in rows:
        table_no = row["table_no"]
        hour = int(row["hour"])
        cnt = int(row["cnt"])

        if table_no not in tables_map:
            tables_map[table_no] = {}
        tables_map[table_no][hour] = cnt
        hourly_totals[hour] += cnt

    tables_data = [
        {"table_no": tn, "usage": usage}
        for tn, usage in sorted(tables_map.items())
    ]

    logger.info(
        "table_heatmap_generated",
        store_id=str(store_id),
        tenant_id=str(tenant_id),
        date=str(target_date),
        table_count=len(tables_data),
    )

    return {
        "date": str(target_date),
        "hours": list(range(24)),
        "tables": tables_data,
        "hourly_totals": hourly_totals,
    }


# ─── 包厢营收分析 ───


async def get_room_revenue_analysis(
    store_id: uuid.UUID,
    date_range: tuple[date, date],
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> dict:
    """包厢营收分析

    Args:
        date_range: (start_date, end_date) 含首尾

    Returns:
        {
            "store_id": str,
            "date_range": [str, str],
            "rooms": [
                {
                    "table_no": str,
                    "area": str,
                    "total_revenue_fen": int,
                    "order_count": int,
                    "avg_per_order_fen": int,
                    "minimum_charge_fen": int,
                    "utilization_rate": float,
                }
            ],
            "summary": {
                "total_revenue_fen": int,
                "total_orders": int,
                "avg_revenue_per_room_fen": int,
            }
        }
    """
    start_date, end_date = date_range
    day_start = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)
    day_end = datetime(end_date.year, end_date.month, end_date.day, tzinfo=timezone.utc) + timedelta(days=1)

    # 包厢 = area 含 "包间"/"包厢"/"VIP"
    room_revenue_result = await db.execute(
        text("""
            SELECT
                t.table_no,
                t.area,
                t.min_consume_fen,
                COUNT(o.id) as order_count,
                COALESCE(SUM(o.total_amount_fen), 0) as total_revenue_fen
            FROM tables t
            LEFT JOIN orders o ON o.table_id = t.id
                AND o.tenant_id = t.tenant_id
                AND o.created_at >= :day_start
                AND o.created_at < :day_end
                AND o.status = 'paid'
                AND o.is_deleted = false
            WHERE t.store_id = :store_id
              AND t.tenant_id = :tenant_id
              AND t.is_deleted = false
              AND t.is_active = true
              AND (t.area LIKE '%%包间%%' OR t.area LIKE '%%包厢%%' OR t.area LIKE '%%VIP%%')
            GROUP BY t.table_no, t.area, t.min_consume_fen
            ORDER BY t.table_no
        """),
        {
            "store_id": store_id,
            "tenant_id": tenant_id,
            "day_start": day_start,
            "day_end": day_end,
        },
    )

    rows = room_revenue_result.mappings().all()
    total_days = (end_date - start_date).days + 1

    rooms = []
    total_revenue = 0
    total_orders = 0

    for row in rows:
        order_count = int(row["order_count"])
        revenue_fen = int(row["total_revenue_fen"])
        avg_fen = revenue_fen // order_count if order_count > 0 else 0
        # 利用率 = 有订单天数占比（简化：order_count / total_days，封顶1.0）
        utilization = min(round(order_count / total_days, 2), 1.0) if total_days > 0 else 0.0

        rooms.append({
            "table_no": row["table_no"],
            "area": row["area"],
            "total_revenue_fen": revenue_fen,
            "order_count": order_count,
            "avg_per_order_fen": avg_fen,
            "minimum_charge_fen": int(row["min_consume_fen"] or 0),
            "utilization_rate": utilization,
        })

        total_revenue += revenue_fen
        total_orders += order_count

    avg_revenue_per_room = total_revenue // len(rooms) if rooms else 0

    logger.info(
        "room_revenue_analyzed",
        store_id=str(store_id),
        tenant_id=str(tenant_id),
        date_range=[str(start_date), str(end_date)],
        room_count=len(rooms),
        total_revenue_fen=total_revenue,
    )

    return {
        "store_id": str(store_id),
        "date_range": [str(start_date), str(end_date)],
        "rooms": rooms,
        "summary": {
            "total_revenue_fen": total_revenue,
            "total_orders": total_orders,
            "avg_revenue_per_room_fen": avg_revenue_per_room,
        },
    }
