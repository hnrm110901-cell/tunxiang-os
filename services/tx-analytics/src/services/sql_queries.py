"""统一SQL查询层 — 经营决策中台所有报表共用

所有查询使用 sqlalchemy.text() 参数化，绝不拼接 SQL。
金额从 orders 表读 fen（分）。
每条查询强制 tenant_id 过滤 + RLS 兼容。
"""
from datetime import date, datetime, timedelta, timezone

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()


# ──────────────────────────────────────────────
# 1. 每日营收查询
# ──────────────────────────────────────────────

async def query_daily_revenue(
    store_id: str,
    target_date: date,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """从 orders 表查询指定日期营收汇总

    Args:
        store_id: 门店ID
        target_date: 查询日期
        tenant_id: 租户ID
        db: 异步数据库会话

    Returns:
        {"revenue_fen": int, "order_count": int, "avg_ticket_fen": int}
    """
    log.info(
        "query_daily_revenue",
        store_id=store_id,
        date=str(target_date),
        tenant_id=tenant_id,
    )

    result = await db.execute(
        text("""
            SELECT COALESCE(SUM(total_fen), 0) AS revenue_fen,
                   COUNT(*) AS order_count
            FROM orders
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND DATE(created_at) = :target_date
              AND status = 'paid'
              AND is_deleted = FALSE
        """),
        {
            "store_id": store_id,
            "tenant_id": tenant_id,
            "target_date": target_date,
        },
    )
    row = result.mappings().first()
    if row is None:
        return {"revenue_fen": 0, "order_count": 0, "avg_ticket_fen": 0}

    revenue_fen = int(row["revenue_fen"])
    order_count = int(row["order_count"])
    avg_ticket_fen = revenue_fen // order_count if order_count > 0 else 0

    return {
        "revenue_fen": revenue_fen,
        "order_count": order_count,
        "avg_ticket_fen": avg_ticket_fen,
    }


# ──────────────────────────────────────────────
# 2. 订单数查询
# ──────────────────────────────────────────────

async def query_order_count(
    store_id: str,
    target_date: date,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """查询指定日期订单数及分时段统计

    Returns:
        {"total": int, "paid": int, "cancelled": int, "refunded": int}
    """
    log.info(
        "query_order_count",
        store_id=store_id,
        date=str(target_date),
        tenant_id=tenant_id,
    )

    result = await db.execute(
        text("""
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE status = 'paid') AS paid,
                   COUNT(*) FILTER (WHERE status = 'cancelled') AS cancelled,
                   COUNT(*) FILTER (WHERE status = 'refunded') AS refunded
            FROM orders
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND DATE(created_at) = :target_date
              AND is_deleted = FALSE
        """),
        {
            "store_id": store_id,
            "tenant_id": tenant_id,
            "target_date": target_date,
        },
    )
    row = result.mappings().first()
    if row is None:
        return {"total": 0, "paid": 0, "cancelled": 0, "refunded": 0}

    return {
        "total": int(row["total"]),
        "paid": int(row["paid"]),
        "cancelled": int(row["cancelled"]),
        "refunded": int(row["refunded"]),
    }


# ──────────────────────────────────────────────
# 3. 菜品销售明细
# ──────────────────────────────────────────────

async def query_dish_sales(
    store_id: str,
    date_range: tuple[date, date],
    tenant_id: str,
    db: AsyncSession,
) -> list[dict]:
    """查询日期范围内菜品销售明细

    Args:
        store_id: 门店ID
        date_range: (start_date, end_date) 含首尾
        tenant_id: 租户ID
        db: 异步数据库会话

    Returns:
        [{"dish_id", "dish_name", "sales_qty", "sales_amount_fen", "category"}]
    """
    start_date, end_date = date_range
    day_start = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)
    day_end = datetime(end_date.year, end_date.month, end_date.day, tzinfo=timezone.utc) + timedelta(days=1)

    log.info(
        "query_dish_sales",
        store_id=store_id,
        start_date=str(start_date),
        end_date=str(end_date),
        tenant_id=tenant_id,
    )

    result = await db.execute(
        text("""
            SELECT oi.dish_id,
                   d.dish_name,
                   d.category,
                   SUM(oi.quantity) AS sales_qty,
                   SUM(oi.subtotal_fen) AS sales_amount_fen
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
            JOIN dishes d ON d.id = oi.dish_id AND d.tenant_id = oi.tenant_id
            WHERE o.store_id = :store_id
              AND o.tenant_id = :tenant_id
              AND o.created_at >= :day_start
              AND o.created_at < :day_end
              AND o.status = 'paid'
              AND o.is_deleted = FALSE
              AND oi.is_deleted = FALSE
            GROUP BY oi.dish_id, d.dish_name, d.category
            ORDER BY sales_qty DESC
        """),
        {
            "store_id": store_id,
            "tenant_id": tenant_id,
            "day_start": day_start,
            "day_end": day_end,
        },
    )
    rows = result.mappings().all()
    return [
        {
            "dish_id": str(r["dish_id"]),
            "dish_name": r["dish_name"],
            "category": r["category"] or "uncategorized",
            "sales_qty": int(r["sales_qty"]),
            "sales_amount_fen": int(r["sales_amount_fen"]),
        }
        for r in rows
    ]


# ──────────────────────────────────────────────
# 4. 按小时分布
# ──────────────────────────────────────────────

async def query_hourly_distribution(
    store_id: str,
    target_date: date,
    tenant_id: str,
    db: AsyncSession,
) -> list[dict]:
    """查询指定日期按小时的营收和订单分布

    Returns:
        [{"hour": int, "revenue_fen": int, "order_count": int}]
    """
    log.info(
        "query_hourly_distribution",
        store_id=store_id,
        date=str(target_date),
        tenant_id=tenant_id,
    )

    result = await db.execute(
        text("""
            SELECT EXTRACT(HOUR FROM created_at)::int AS hour,
                   COALESCE(SUM(total_fen), 0) AS revenue_fen,
                   COUNT(*) AS order_count
            FROM orders
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND DATE(created_at) = :target_date
              AND status = 'paid'
              AND is_deleted = FALSE
            GROUP BY EXTRACT(HOUR FROM created_at)::int
            ORDER BY hour
        """),
        {
            "store_id": store_id,
            "tenant_id": tenant_id,
            "target_date": target_date,
        },
    )
    rows = result.mappings().all()
    return [
        {
            "hour": int(r["hour"]),
            "revenue_fen": int(r["revenue_fen"]),
            "order_count": int(r["order_count"]),
        }
        for r in rows
    ]


# ──────────────────────────────────────────────
# 5. 支付方式分布
# ──────────────────────────────────────────────

async def query_payment_breakdown(
    store_id: str,
    target_date: date,
    tenant_id: str,
    db: AsyncSession,
) -> list[dict]:
    """查询指定日期支付方式分布

    Returns:
        [{"payment_method": str, "amount_fen": int, "count": int, "pct": float}]
    """
    log.info(
        "query_payment_breakdown",
        store_id=store_id,
        date=str(target_date),
        tenant_id=tenant_id,
    )

    result = await db.execute(
        text("""
            SELECT COALESCE(payment_method, 'unknown') AS payment_method,
                   COALESCE(SUM(total_fen), 0) AS amount_fen,
                   COUNT(*) AS count
            FROM orders
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND DATE(created_at) = :target_date
              AND status = 'paid'
              AND is_deleted = FALSE
            GROUP BY COALESCE(payment_method, 'unknown')
            ORDER BY amount_fen DESC
        """),
        {
            "store_id": store_id,
            "tenant_id": tenant_id,
            "target_date": target_date,
        },
    )
    rows = result.mappings().all()

    total_fen = sum(int(r["amount_fen"]) for r in rows)

    return [
        {
            "payment_method": r["payment_method"],
            "amount_fen": int(r["amount_fen"]),
            "count": int(r["count"]),
            "pct": round(int(r["amount_fen"]) / total_fen * 100, 1) if total_fen > 0 else 0.0,
        }
        for r in rows
    ]


# ──────────────────────────────────────────────
# 6. 桌台会话（翻台）
# ──────────────────────────────────────────────

async def query_table_sessions(
    store_id: str,
    target_date: date,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """查询桌台会话数据，计算翻台率

    Returns:
        {
            "total_tables": int,
            "occupied_sessions": int,
            "turnover_rate": float,
            "avg_duration_minutes": float,
        }
    """
    log.info(
        "query_table_sessions",
        store_id=store_id,
        date=str(target_date),
        tenant_id=tenant_id,
    )

    # 查询桌台总数
    tables_result = await db.execute(
        text("""
            SELECT COUNT(*) AS total_tables
            FROM tables
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND is_deleted = FALSE
              AND is_active = TRUE
        """),
        {"store_id": store_id, "tenant_id": tenant_id},
    )
    total_tables = int(tables_result.scalar() or 0)

    # 查询当日桌台使用次数和平均时长
    sessions_result = await db.execute(
        text("""
            SELECT COUNT(DISTINCT (table_id, id)) AS occupied_sessions,
                   AVG(EXTRACT(EPOCH FROM (updated_at - created_at)) / 60) AS avg_duration_minutes
            FROM orders
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND DATE(created_at) = :target_date
              AND table_id IS NOT NULL
              AND status IN ('paid', 'pending_payment')
              AND is_deleted = FALSE
        """),
        {
            "store_id": store_id,
            "tenant_id": tenant_id,
            "target_date": target_date,
        },
    )
    sess_row = sessions_result.mappings().first()

    occupied_sessions = int(sess_row["occupied_sessions"]) if sess_row else 0
    avg_duration = float(sess_row["avg_duration_minutes"] or 0) if sess_row else 0.0
    turnover_rate = round(occupied_sessions / total_tables, 2) if total_tables > 0 else 0.0

    return {
        "total_tables": total_tables,
        "occupied_sessions": occupied_sessions,
        "turnover_rate": turnover_rate,
        "avg_duration_minutes": round(avg_duration, 1),
    }


# ──────────────────────────────────────────────
# 7. 退菜记录
# ──────────────────────────────────────────────

async def query_returns(
    store_id: str,
    date_range: tuple[date, date],
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """查询退菜记录汇总

    Returns:
        {
            "total_return_qty": int,
            "total_return_amount_fen": int,
            "by_dish": [{"dish_id", "dish_name", "return_qty", "return_amount_fen"}],
            "by_reason": [{"reason", "count"}],
        }
    """
    start_date, end_date = date_range
    day_start = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)
    day_end = datetime(end_date.year, end_date.month, end_date.day, tzinfo=timezone.utc) + timedelta(days=1)

    log.info(
        "query_returns",
        store_id=store_id,
        start_date=str(start_date),
        end_date=str(end_date),
        tenant_id=tenant_id,
    )

    # 按菜品汇总退菜
    dish_result = await db.execute(
        text("""
            SELECT oi.dish_id,
                   d.dish_name,
                   SUM(oi.quantity) AS return_qty,
                   SUM(oi.subtotal_fen) AS return_amount_fen
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
            JOIN dishes d ON d.id = oi.dish_id AND d.tenant_id = oi.tenant_id
            WHERE o.store_id = :store_id
              AND o.tenant_id = :tenant_id
              AND o.created_at >= :day_start
              AND o.created_at < :day_end
              AND oi.status = 'returned'
              AND o.is_deleted = FALSE
              AND oi.is_deleted = FALSE
            GROUP BY oi.dish_id, d.dish_name
            ORDER BY return_qty DESC
        """),
        {
            "store_id": store_id,
            "tenant_id": tenant_id,
            "day_start": day_start,
            "day_end": day_end,
        },
    )
    dish_rows = dish_result.mappings().all()
    by_dish = [
        {
            "dish_id": str(r["dish_id"]),
            "dish_name": r["dish_name"],
            "return_qty": int(r["return_qty"]),
            "return_amount_fen": int(r["return_amount_fen"]),
        }
        for r in dish_rows
    ]

    # 按原因汇总
    reason_result = await db.execute(
        text("""
            SELECT COALESCE(oi.return_reason, 'unknown') AS reason,
                   COUNT(*) AS count
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
            WHERE o.store_id = :store_id
              AND o.tenant_id = :tenant_id
              AND o.created_at >= :day_start
              AND o.created_at < :day_end
              AND oi.status = 'returned'
              AND o.is_deleted = FALSE
              AND oi.is_deleted = FALSE
            GROUP BY COALESCE(oi.return_reason, 'unknown')
            ORDER BY count DESC
        """),
        {
            "store_id": store_id,
            "tenant_id": tenant_id,
            "day_start": day_start,
            "day_end": day_end,
        },
    )
    reason_rows = reason_result.mappings().all()
    by_reason = [
        {"reason": r["reason"], "count": int(r["count"])}
        for r in reason_rows
    ]

    total_return_qty = sum(d["return_qty"] for d in by_dish)
    total_return_amount_fen = sum(d["return_amount_fen"] for d in by_dish)

    return {
        "total_return_qty": total_return_qty,
        "total_return_amount_fen": total_return_amount_fen,
        "by_dish": by_dish,
        "by_reason": by_reason,
    }


# ──────────────────────────────────────────────
# 8. 今日异常
# ──────────────────────────────────────────────

async def query_alerts_today(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> list[dict]:
    """查询今日异常告警列表

    Returns:
        [{"id", "type", "severity", "title", "detail", "time", "status", "action_required"}]
    """
    today = date.today()

    log.info(
        "query_alerts_today",
        store_id=store_id,
        tenant_id=tenant_id,
        date=str(today),
    )

    result = await db.execute(
        text("""
            SELECT id,
                   type,
                   severity,
                   title,
                   detail,
                   time,
                   status,
                   action_required
            FROM alerts
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND DATE(time) = :today
              AND is_deleted = FALSE
            ORDER BY
                CASE severity
                    WHEN 'critical' THEN 0
                    WHEN 'warning' THEN 1
                    WHEN 'info' THEN 2
                    ELSE 3
                END,
                time DESC
        """),
        {
            "store_id": store_id,
            "tenant_id": tenant_id,
            "today": today,
        },
    )
    rows = result.mappings().all()
    return [
        {
            "id": str(r["id"]),
            "type": r["type"],
            "severity": r["severity"],
            "title": r["title"],
            "detail": r["detail"],
            "time": r["time"].isoformat() if hasattr(r["time"], "isoformat") else str(r["time"]),
            "status": r["status"],
            "action_required": bool(r["action_required"]),
        }
        for r in rows
    ]
