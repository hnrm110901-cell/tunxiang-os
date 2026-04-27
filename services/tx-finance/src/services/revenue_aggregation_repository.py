"""营收聚合 Repository 层 — 原始数据访问

直接查询 orders / payments / refunds 三张表，
返回低层结构化数据，供 Service 层做业务聚合。

所有金额单位：分（fen）。
RLS 由 get_db_with_tenant 在连接级设置，这里额外显式传入 tenant_id 作双重过滤。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

import structlog
from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Order, OrderItem

logger = structlog.get_logger(__name__)

_COMPLETED_STATUSES = ("completed", "settled", "paid")


def _day_window(biz_date: date) -> tuple[datetime, datetime]:
    """返回业务日期的 UTC 时间窗口（00:00:00 ~ 23:59:59）"""
    start = datetime.combine(biz_date, datetime.min.time()).replace(tzinfo=timezone.utc)
    end = datetime.combine(biz_date, datetime.max.time()).replace(tzinfo=timezone.utc)
    return start, end


def _range_window(start_date: date, end_date: date) -> tuple[datetime, datetime]:
    """返回日期区间的 UTC 时间窗口"""
    start = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=timezone.utc)
    end = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=timezone.utc)
    return start, end


class RevenueAggregationRepository:
    """营收聚合数据访问层

    约定：
    - 所有方法显式接收 tenant_id (UUID) 作为额外过滤条件（与 RLS 双重隔离）
    - 所有方法返回原始 dict 列表或聚合 dict，不含业务逻辑
    """

    # ── 日营收基础聚合 ───────────────────────────────────────────

    async def fetch_daily_order_summary(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        biz_date: date,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """查询当日订单汇总：毛收、折扣、订单数"""
        start_dt, end_dt = _day_window(biz_date)

        result = await db.execute(
            select(
                func.coalesce(func.sum(Order.total_amount_fen), 0).label("gross"),
                func.coalesce(func.sum(Order.discount_amount_fen), 0).label("discount"),
                func.count(Order.id).label("cnt"),
            ).where(
                and_(
                    Order.tenant_id == tenant_id,
                    Order.store_id == store_id,
                    Order.status.in_(_COMPLETED_STATUSES),
                    Order.order_time >= start_dt,
                    Order.order_time <= end_dt,
                    Order.is_deleted == False,  # noqa: E712
                )
            )
        )
        row = result.one()
        return {
            "gross_revenue_fen": int(row.gross),
            "discount_fen": int(row.discount),
            "order_count": int(row.cnt),
        }

    async def fetch_daily_refund_from_items(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        biz_date: date,
        db: AsyncSession,
    ) -> int:
        """通过 order_items.return_flag 计算退菜金额（分）"""
        start_dt, end_dt = _day_window(biz_date)

        result = await db.execute(
            select(func.coalesce(func.sum(OrderItem.subtotal_fen), 0))
            .join(Order, OrderItem.order_id == Order.id)
            .where(
                and_(
                    Order.tenant_id == tenant_id,
                    Order.store_id == store_id,
                    Order.order_time >= start_dt,
                    Order.order_time <= end_dt,
                    Order.is_deleted == False,  # noqa: E712
                    OrderItem.return_flag == True,  # noqa: E712
                )
            )
        )
        return int(result.scalar_one())

    async def fetch_daily_refund_from_payments(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        biz_date: date,
        db: AsyncSession,
    ) -> int:
        """通过 refunds 表获取当日退款金额（分）

        refunds 表没有 ORM 实体，用 text() + 参数化查询。
        """
        start_dt, end_dt = _day_window(biz_date)
        sql = text("""
            SELECT COALESCE(SUM(r.amount_fen), 0)
            FROM refunds r
            JOIN orders o ON r.order_id = o.id
            WHERE r.tenant_id  = :tenant_id
              AND o.store_id   = :store_id
              AND o.order_time >= :start_dt
              AND o.order_time <= :end_dt
              AND r.is_deleted = false
              AND o.is_deleted = false
        """)
        result = await db.execute(
            sql,
            {
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
                "start_dt": start_dt,
                "end_dt": end_dt,
            },
        )
        return int(result.scalar_one() or 0)

    async def fetch_payment_breakdown(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        biz_date: date,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        """按支付方式分组统计支付金额（从 payments 表）

        返回: [{"method": "wechat", "amount_fen": 12300, "order_count": 5}]
        """
        start_dt, end_dt = _day_window(biz_date)
        sql = text("""
            SELECT
                p.method                          AS method,
                COALESCE(SUM(p.amount_fen), 0)    AS amount_fen,
                COUNT(DISTINCT p.order_id)         AS order_count
            FROM payments p
            JOIN orders o ON p.order_id = o.id
            WHERE p.tenant_id  = :tenant_id
              AND o.store_id   = :store_id
              AND p.status     IN ('completed', 'paid', 'success')
              AND p.is_actual_revenue = true
              AND o.order_time >= :start_dt
              AND o.order_time <= :end_dt
              AND p.is_deleted = false
              AND o.is_deleted = false
            GROUP BY p.method
            ORDER BY SUM(p.amount_fen) DESC
        """)
        result = await db.execute(
            sql,
            {
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
                "start_dt": start_dt,
                "end_dt": end_dt,
            },
        )
        return [
            {
                "method": row.method or "unknown",
                "amount_fen": int(row.amount_fen),
                "order_count": int(row.order_count),
            }
            for row in result.all()
        ]

    async def fetch_hourly_breakdown(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        biz_date: date,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        """按小时分布统计订单量和营收

        返回: [{"hour": 12, "order_count": 30, "revenue_fen": 90000}]
        """
        start_dt, end_dt = _day_window(biz_date)

        result = await db.execute(
            select(
                func.extract("hour", Order.order_time).label("hour"),
                func.count(Order.id).label("order_count"),
                func.coalesce(func.sum(Order.final_amount_fen), 0).label("revenue"),
            )
            .where(
                and_(
                    Order.tenant_id == tenant_id,
                    Order.store_id == store_id,
                    Order.status.in_(_COMPLETED_STATUSES),
                    Order.order_time >= start_dt,
                    Order.order_time <= end_dt,
                    Order.is_deleted == False,  # noqa: E712
                )
            )
            .group_by(text("1"))
            .order_by(text("1"))
        )
        return [
            {
                "hour": int(row.hour),
                "order_count": int(row.order_count),
                "revenue_fen": int(row.revenue),
            }
            for row in result.all()
        ]

    # ── 多日期范围聚合 ───────────────────────────────────────────

    async def fetch_revenue_by_granularity(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        start_date: date,
        end_date: date,
        granularity: str,  # day | week | month
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        """按 day/week/month 粒度聚合营收趋势

        返回: [{"period": "2026-03-01", "revenue_fen": 120000, "order_count": 45}]
        """
        start_dt, end_dt = _range_window(start_date, end_date)

        # PostgreSQL date_trunc 粒度映射
        trunc_map = {"day": "day", "week": "week", "month": "month"}
        trunc = trunc_map.get(granularity, "day")

        result = await db.execute(
            select(
                func.date_trunc(trunc, Order.order_time).label("period"),
                func.coalesce(func.sum(Order.final_amount_fen), 0).label("revenue"),
                func.coalesce(func.sum(Order.discount_amount_fen), 0).label("discount"),
                func.count(Order.id).label("order_count"),
            )
            .where(
                and_(
                    Order.tenant_id == tenant_id,
                    Order.store_id == store_id,
                    Order.status.in_(_COMPLETED_STATUSES),
                    Order.order_time >= start_dt,
                    Order.order_time <= end_dt,
                    Order.is_deleted == False,  # noqa: E712
                )
            )
            .group_by(text("1"))
            .order_by(text("1"))
        )
        return [
            {
                "period": str(row.period.date()) if row.period else "",
                "revenue_fen": int(row.revenue),
                "discount_fen": int(row.discount),
                "order_count": int(row.order_count),
            }
            for row in result.all()
        ]

    async def fetch_range_order_summary(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        start_date: date,
        end_date: date,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """查询区间内订单汇总（毛收/折扣/单量）"""
        start_dt, end_dt = _range_window(start_date, end_date)

        result = await db.execute(
            select(
                func.coalesce(func.sum(Order.total_amount_fen), 0).label("gross"),
                func.coalesce(func.sum(Order.discount_amount_fen), 0).label("discount"),
                func.coalesce(func.sum(Order.final_amount_fen), 0).label("final"),
                func.count(Order.id).label("cnt"),
            ).where(
                and_(
                    Order.tenant_id == tenant_id,
                    Order.store_id == store_id,
                    Order.status.in_(_COMPLETED_STATUSES),
                    Order.order_time >= start_dt,
                    Order.order_time <= end_dt,
                    Order.is_deleted == False,  # noqa: E712
                )
            )
        )
        row = result.one()
        return {
            "gross_revenue_fen": int(row.gross),
            "discount_fen": int(row.discount),
            "final_revenue_fen": int(row.final),
            "order_count": int(row.cnt),
        }

    async def fetch_range_refund_from_payments(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        start_date: date,
        end_date: date,
        db: AsyncSession,
    ) -> int:
        """查询区间内 refunds 表退款总额（分）"""
        start_dt, end_dt = _range_window(start_date, end_date)
        sql = text("""
            SELECT COALESCE(SUM(r.amount_fen), 0)
            FROM refunds r
            JOIN orders o ON r.order_id = o.id
            WHERE r.tenant_id  = :tenant_id
              AND o.store_id   = :store_id
              AND o.order_time >= :start_dt
              AND o.order_time <= :end_dt
              AND r.is_deleted = false
              AND o.is_deleted = false
        """)
        result = await db.execute(
            sql,
            {
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
                "start_dt": start_dt,
                "end_dt": end_dt,
            },
        )
        return int(result.scalar_one() or 0)

    # ── 支付方式对账 ─────────────────────────────────────────────

    async def fetch_payment_reconciliation(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        start_date: date,
        end_date: date,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        """各支付方式对账汇总：订单数/应收（订单)/实收（支付）

        返回:
        [
          {
            "method": "wechat",
            "label": "微信",
            "order_count": 30,
            "order_amount_fen": 90000,   # 应收（来自 orders）
            "paid_amount_fen": 89500,    # 实收（来自 payments）
            "refund_amount_fen": 500,    # 退款（来自 refunds）
            "net_fen": 89000,
          }
        ]
        """
        start_dt, end_dt = _range_window(start_date, end_date)
        sql = text("""
            WITH order_by_method AS (
                -- 通过 payments 关联找出每笔订单的支付方式
                SELECT
                    p.method,
                    COUNT(DISTINCT o.id)                       AS order_count,
                    COALESCE(SUM(o.final_amount_fen), 0)       AS order_amount_fen
                FROM orders o
                JOIN payments p ON p.order_id = o.id
                WHERE o.tenant_id  = :tenant_id
                  AND o.store_id   = :store_id
                  AND o.status     IN ('completed', 'settled', 'paid')
                  AND p.is_actual_revenue = true
                  AND o.order_time >= :start_dt
                  AND o.order_time <= :end_dt
                  AND o.is_deleted = false
                  AND p.is_deleted = false
                GROUP BY p.method
            ),
            paid_by_method AS (
                SELECT
                    p.method,
                    COALESCE(SUM(p.amount_fen), 0)             AS paid_amount_fen
                FROM payments p
                JOIN orders o ON p.order_id = o.id
                WHERE p.tenant_id  = :tenant_id
                  AND o.store_id   = :store_id
                  AND p.status     IN ('completed', 'paid', 'success')
                  AND p.is_actual_revenue = true
                  AND o.order_time >= :start_dt
                  AND o.order_time <= :end_dt
                  AND p.is_deleted = false
                  AND o.is_deleted = false
                GROUP BY p.method
            ),
            refund_by_method AS (
                SELECT
                    p.method,
                    COALESCE(SUM(r.amount_fen), 0)             AS refund_amount_fen
                FROM refunds r
                JOIN payments p ON r.payment_id = p.id
                JOIN orders  o ON r.order_id    = o.id
                WHERE r.tenant_id  = :tenant_id
                  AND o.store_id   = :store_id
                  AND o.order_time >= :start_dt
                  AND o.order_time <= :end_dt
                  AND r.is_deleted = false
                  AND o.is_deleted = false
                GROUP BY p.method
            )
            SELECT
                COALESCE(ob.method, pb.method, rb.method) AS method,
                COALESCE(ob.order_count,     0)            AS order_count,
                COALESCE(ob.order_amount_fen, 0)           AS order_amount_fen,
                COALESCE(pb.paid_amount_fen,  0)           AS paid_amount_fen,
                COALESCE(rb.refund_amount_fen,0)           AS refund_amount_fen
            FROM order_by_method ob
            FULL OUTER JOIN paid_by_method   pb ON ob.method = pb.method
            FULL OUTER JOIN refund_by_method rb ON ob.method = rb.method
            ORDER BY COALESCE(pb.paid_amount_fen, 0) DESC
        """)
        result = await db.execute(
            sql,
            {
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
                "start_dt": start_dt,
                "end_dt": end_dt,
            },
        )
        return [
            {
                "method": row.method or "unknown",
                "order_count": int(row.order_count),
                "order_amount_fen": int(row.order_amount_fen),
                "paid_amount_fen": int(row.paid_amount_fen),
                "refund_amount_fen": int(row.refund_amount_fen),
            }
            for row in result.all()
        ]
