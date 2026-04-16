"""成本核算 Repository 层 — 原始数据访问

通过 BOM 展开计算菜品食材成本，供 CostEngineService 使用。
所有金额单位：分（fen）。
RLS 由 get_db_with_tenant 在连接级设置，这里额外显式传入 tenant_id 作双重过滤。
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

_COMPLETED_STATUSES = ("completed", "settled", "paid")

# 无 BOM 时的行业平均食材成本率（28-35% 区间中点，保守取 30%）
_DEFAULT_FOOD_COST_RATE = 0.30


def _day_window(biz_date: date) -> tuple[datetime, datetime]:
    """返回业务日期的 UTC 时间窗口（00:00:00 ~ 23:59:59）"""
    start = datetime.combine(biz_date, datetime.min.time()).replace(tzinfo=timezone.utc)
    end = datetime.combine(biz_date, datetime.max.time()).replace(tzinfo=timezone.utc)
    return start, end


def _range_window(
    start_date: date, end_date: date
) -> tuple[datetime, datetime]:
    """返回日期区间的 UTC 时间窗口"""
    start = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=timezone.utc)
    end = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=timezone.utc)
    return start, end


class CostEngineRepository:
    """成本核算数据访问层

    约定：
    - 所有方法显式接收 tenant_id (UUID) 作为额外过滤条件（与 RLS 双重隔离）
    - 所有方法返回原始 dict 列表或聚合 dict，不含业务逻辑
    """

    # ── 订单明细查询 ───────────────────────────────────────────

    async def fetch_order_items_with_revenue(
        self,
        store_id: uuid.UUID,
        start_date: date,
        end_date: date,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        """查询区间内已完成订单的订单行，带菜品ID和单价

        返回: [{"order_id", "order_item_id", "dish_id", "dish_name",
                "quantity", "unit_price_fen", "subtotal_fen"}]
        """
        start_dt, end_dt = _range_window(start_date, end_date)
        sql = text("""
            SELECT
                oi.id             AS order_item_id,
                oi.order_id,
                oi.dish_id,
                d.dish_name,
                oi.quantity,
                oi.unit_price_fen,
                oi.subtotal_fen
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            LEFT JOIN dishes d ON d.id = oi.dish_id
            WHERE o.store_id  = :store_id
              AND o.tenant_id = :tenant_id
              AND o.status    IN ('completed', 'settled', 'paid')
              AND o.order_time >= :start_dt
              AND o.order_time <= :end_dt
              AND o.is_deleted = false
              AND oi.is_deleted = false
              AND (oi.return_flag IS NULL OR oi.return_flag = false)
        """)
        result = await db.execute(
            sql,
            {
                "store_id": str(store_id),
                "tenant_id": str(tenant_id),
                "start_dt": start_dt,
                "end_dt": end_dt,
            },
        )
        return [
            {
                "order_item_id": str(row.order_item_id),
                "order_id": str(row.order_id),
                "dish_id": str(row.dish_id) if row.dish_id else None,
                "dish_name": row.dish_name or "未知菜品",
                "quantity": int(row.quantity or 1),
                "unit_price_fen": int(row.unit_price_fen or 0),
                "subtotal_fen": int(row.subtotal_fen or 0),
            }
            for row in result.all()
        ]

    # ── BOM 成本查询 ───────────────────────────────────────────

    async def fetch_bom_cost_for_dishes(
        self,
        dish_ids: list[uuid.UUID],
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict[str, dict[str, Any]]:
        """批量查询菜品的 BOM 单份成本

        通过 bom_templates + bom_items 展开，取当前激活版本。
        返回: {dish_id_str: {"cost_fen": int, "bom_id": str, "is_estimated": False}}
        """
        if not dish_ids:
            return {}

        dish_id_strs = [str(d) for d in dish_ids]
        sql = text("""
            WITH active_bom AS (
                SELECT
                    bt.id          AS bom_id,
                    bt.dish_id,
                    bt.yield_rate,
                    bt.tenant_id
                FROM bom_templates bt
                WHERE bt.tenant_id = :tenant_id
                  AND bt.is_active  = TRUE
                  AND bt.is_deleted = FALSE
                  AND bt.dish_id = ANY(:dish_ids::UUID[])
            ),
            bom_cost AS (
                SELECT
                    ab.dish_id,
                    ab.bom_id,
                    SUM(
                        COALESCE(bi.standard_qty, 0)
                        * COALESCE(bi.unit_cost_fen, 0)
                        / NULLIF(COALESCE(ab.yield_rate, 1), 0)
                    )::BIGINT AS cost_fen
                FROM active_bom ab
                JOIN bom_items bi ON bi.bom_id = ab.bom_id
                WHERE bi.is_deleted = FALSE
                  AND bi.item_action != 'REMOVE'
                GROUP BY ab.dish_id, ab.bom_id
            )
            SELECT
                dish_id,
                bom_id,
                COALESCE(cost_fen, 0) AS cost_fen
            FROM bom_cost
        """)
        result = await db.execute(
            sql,
            {
                "tenant_id": str(tenant_id),
                "dish_ids": dish_id_strs,
            },
        )
        return {
            str(row.dish_id): {
                "cost_fen": int(row.cost_fen),
                "bom_id": str(row.bom_id),
                "is_estimated": False,
            }
            for row in result.all()
        }

    async def fetch_ingredient_prices(
        self,
        ingredient_ids: list[uuid.UUID],
        as_of_date: date,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict[str, int]:
        """获取食材在指定日期之前最近一次入库的单价（分）

        返回: {ingredient_id_str: unit_price_fen}
        """
        if not ingredient_ids:
            return {}

        ing_id_strs = [str(i) for i in ingredient_ids]
        as_of_dt = datetime.combine(as_of_date, datetime.max.time()).replace(tzinfo=timezone.utc)
        sql = text("""
            WITH ranked AS (
                SELECT
                    it.ingredient_id,
                    it.unit_price_fen,
                    ROW_NUMBER() OVER (
                        PARTITION BY it.ingredient_id
                        ORDER BY it.created_at DESC
                    ) AS rn
                FROM ingredient_transactions it
                WHERE it.tenant_id    = :tenant_id
                  AND it.ingredient_id = ANY(:ingredient_ids::UUID[])
                  AND it.transaction_type = 'in'
                  AND it.created_at  <= :as_of_dt
                  AND it.is_deleted  = FALSE
            )
            SELECT ingredient_id, unit_price_fen
            FROM ranked
            WHERE rn = 1
        """)
        result = await db.execute(
            sql,
            {
                "tenant_id": str(tenant_id),
                "ingredient_ids": ing_id_strs,
                "as_of_dt": as_of_dt,
            },
        )
        return {
            str(row.ingredient_id): int(row.unit_price_fen or 0)
            for row in result.all()
        }

    # ── 日成本汇总 ─────────────────────────────────────────────

    async def fetch_daily_cost_from_snapshots(
        self,
        store_id: uuid.UUID,
        biz_date: date,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """从 cost_snapshots 汇总当日食材成本

        返回: {"total_food_cost_fen": int, "order_count": int, "snapshot_count": int}
        """
        start_dt, end_dt = _day_window(biz_date)
        sql = text("""
            SELECT
                COUNT(DISTINCT cs.order_id)             AS order_count,
                COALESCE(SUM(cs.raw_material_cost), 0)  AS total_food_cost_fen,
                COUNT(cs.id)                            AS snapshot_count
            FROM cost_snapshots cs
            JOIN orders o ON o.id = cs.order_id
            WHERE o.store_id   = :store_id
              AND cs.tenant_id = :tenant_id
              AND o.order_time >= :start_dt
              AND o.order_time <= :end_dt
              AND o.is_deleted = false
        """)
        result = await db.execute(
            sql,
            {
                "store_id": str(store_id),
                "tenant_id": str(tenant_id),
                "start_dt": start_dt,
                "end_dt": end_dt,
            },
        )
        row = result.fetchone()
        if not row:
            return {"total_food_cost_fen": 0, "order_count": 0, "snapshot_count": 0}
        return {
            "total_food_cost_fen": int(row.total_food_cost_fen),
            "order_count": int(row.order_count),
            "snapshot_count": int(row.snapshot_count),
        }

    async def fetch_daily_revenue_for_cost(
        self,
        store_id: uuid.UUID,
        biz_date: date,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> int:
        """查询当日实收营收（分），用于计算成本率"""
        start_dt, end_dt = _day_window(biz_date)
        sql = text("""
            SELECT COALESCE(SUM(o.final_amount_fen), 0) AS revenue_fen
            FROM orders o
            WHERE o.store_id   = :store_id
              AND o.tenant_id  = :tenant_id
              AND o.status     IN ('completed', 'settled', 'paid')
              AND o.order_time >= :start_dt
              AND o.order_time <= :end_dt
              AND o.is_deleted = false
        """)
        result = await db.execute(
            sql,
            {
                "store_id": str(store_id),
                "tenant_id": str(tenant_id),
                "start_dt": start_dt,
                "end_dt": end_dt,
            },
        )
        row = result.fetchone()
        return int(row.revenue_fen) if row else 0

    # ── 菜品成本明细（TOP N）──────────────────────────────────

    async def fetch_dish_cost_breakdown(
        self,
        store_id: uuid.UUID,
        start_date: date,
        end_date: date,
        tenant_id: uuid.UUID,
        db: AsyncSession,
        top_n: int = 10,
    ) -> list[dict[str, Any]]:
        """按菜品聚合成本明细，返回 TOP N

        返回: [{"dish_id", "dish_name", "quantity", "total_cost_fen",
                "avg_cost_fen", "total_revenue_fen", "cost_ratio"}]
        """
        start_dt, end_dt = _range_window(start_date, end_date)
        sql = text("""
            SELECT
                cs.dish_id,
                d.dish_name,
                SUM(oi.quantity)                                    AS quantity,
                COALESCE(SUM(cs.raw_material_cost * oi.quantity), 0) AS total_cost_fen,
                COALESCE(AVG(cs.raw_material_cost), 0)              AS avg_cost_fen,
                COALESCE(SUM(oi.subtotal_fen), 0)                   AS total_revenue_fen
            FROM cost_snapshots cs
            JOIN order_items oi ON oi.id = cs.order_item_id
            JOIN orders o       ON o.id  = cs.order_id
            LEFT JOIN dishes d  ON d.id  = cs.dish_id
            WHERE o.store_id    = :store_id
              AND cs.tenant_id  = :tenant_id
              AND o.order_time  >= :start_dt
              AND o.order_time  <= :end_dt
              AND o.is_deleted  = false
              AND oi.is_deleted = false
            GROUP BY cs.dish_id, d.dish_name
            ORDER BY total_cost_fen DESC
            LIMIT :top_n
        """)
        result = await db.execute(
            sql,
            {
                "store_id": str(store_id),
                "tenant_id": str(tenant_id),
                "start_dt": start_dt,
                "end_dt": end_dt,
                "top_n": top_n,
            },
        )
        rows = result.all()
        total_cost = sum(int(r.total_cost_fen) for r in rows)
        return [
            {
                "dish_id": str(row.dish_id) if row.dish_id else None,
                "dish_name": row.dish_name or "未知菜品",
                "quantity": int(row.quantity or 0),
                "total_cost_fen": int(row.total_cost_fen),
                "avg_cost_fen": int(row.avg_cost_fen),
                "total_revenue_fen": int(row.total_revenue_fen),
                "cost_ratio": round(
                    int(row.total_cost_fen) / total_cost, 4
                ) if total_cost > 0 else 0.0,
            }
            for row in rows
        ]

    # ── 门店固定费用配置 ───────────────────────────────────────

    async def fetch_store_fixed_cost_config(
        self,
        store_id: uuid.UUID,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict[str, int]:
        """从 stores 表读取门店固定成本配置（月度金额，分）

        优先读 monthly_rent_fen / monthly_utility_fen / monthly_other_fixed_fen 列，
        降级到 config JSONB 中的 fixed_costs 字段。

        返回: {"monthly_rent_fen": int, "monthly_utility_fen": int,
               "monthly_other_fixed_fen": int}
        """
        sql = text("""
            SELECT
                COALESCE(monthly_rent_fen,        0) AS monthly_rent_fen,
                COALESCE(monthly_utility_fen,     0) AS monthly_utility_fen,
                COALESCE(monthly_other_fixed_fen, 0) AS monthly_other_fixed_fen,
                config
            FROM stores
            WHERE id        = :store_id
              AND tenant_id = :tenant_id
              AND is_deleted = false
            LIMIT 1
        """)
        try:
            result = await db.execute(
                sql,
                {"store_id": str(store_id), "tenant_id": str(tenant_id)},
            )
            row = result.fetchone()
        except (OperationalError, SQLAlchemyError) as exc:
            # 列可能尚未通过迁移添加，降级到 config JSONB
            logger.warning(
                "fetch_store_fixed_cost_config.columns_missing_fallback",
                store_id=str(store_id),
                error=str(exc),
            )
            row = None

        if row is None:
            return {
                "monthly_rent_fen": 0,
                "monthly_utility_fen": 0,
                "monthly_other_fixed_fen": 0,
            }

        # 如果专用列有值，直接返回
        rent = int(row.monthly_rent_fen)
        util = int(row.monthly_utility_fen)
        other = int(row.monthly_other_fixed_fen)

        if rent > 0 or util > 0 or other > 0:
            return {
                "monthly_rent_fen": rent,
                "monthly_utility_fen": util,
                "monthly_other_fixed_fen": other,
            }

        # 降级：从 config JSONB 读取
        config = row.config if isinstance(row.config, dict) else {}
        fixed = config.get("fixed_costs", {})
        return {
            "monthly_rent_fen": int(fixed.get("monthly_rent_fen", 0)),
            "monthly_utility_fen": int(fixed.get("monthly_utility_fen", 0)),
            "monthly_other_fixed_fen": int(fixed.get("monthly_other_fixed_fen", 0)),
        }

    async def upsert_store_fixed_cost_config(
        self,
        store_id: uuid.UUID,
        tenant_id: uuid.UUID,
        monthly_rent_fen: int,
        monthly_utility_fen: int,
        monthly_other_fixed_fen: int,
        db: AsyncSession,
    ) -> None:
        """写入门店固定成本配置到 config JSONB（兼容无专用列的情况）"""
        sql = text("""
            UPDATE stores
            SET config = COALESCE(config, '{}'::jsonb) || jsonb_build_object(
                'fixed_costs', jsonb_build_object(
                    'monthly_rent_fen',        :monthly_rent_fen,
                    'monthly_utility_fen',     :monthly_utility_fen,
                    'monthly_other_fixed_fen', :monthly_other_fixed_fen
                )
            ),
            updated_at = NOW()
            WHERE id        = :store_id
              AND tenant_id = :tenant_id
              AND is_deleted = false
        """)
        await db.execute(
            sql,
            {
                "store_id": str(store_id),
                "tenant_id": str(tenant_id),
                "monthly_rent_fen": monthly_rent_fen,
                "monthly_utility_fen": monthly_utility_fen,
                "monthly_other_fixed_fen": monthly_other_fixed_fen,
            },
        )
        await db.commit()

    # ── 人工成本查询（从薪资表）────────────────────────────────

    async def fetch_monthly_labor_cost(
        self,
        store_id: uuid.UUID,
        year: int,
        month: int,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> int:
        """从 payroll_records 查询指定月度人工成本（分）

        payroll_records 中金额单位为元，转换为分。
        通过 employees.store_id 关联到门店。
        """
        sql = text("""
            SELECT COALESCE(SUM(pr.gross_salary * 100), 0)::BIGINT AS labor_cost_fen
            FROM payroll_records pr
            JOIN employees e ON e.id = pr.employee_id
            WHERE e.store_id    = :store_id
              AND pr.tenant_id  = :tenant_id
              AND pr.period_year = :year
              AND pr.period_month = :month
              AND pr.status     != 'cancelled'
        """)
        try:
            result = await db.execute(
                sql,
                {
                    "store_id": str(store_id),
                    "tenant_id": str(tenant_id),
                    "year": year,
                    "month": month,
                },
            )
            row = result.fetchone()
            return int(row.labor_cost_fen) if row else 0
        except (OperationalError, SQLAlchemyError) as exc:
            logger.warning(
                "fetch_monthly_labor_cost.query_failed",
                store_id=str(store_id),
                year=year,
                month=month,
                error=str(exc),
            )
            return 0

    # ── 废料/损耗查询 ──────────────────────────────────────────

    async def fetch_waste_cost(
        self,
        store_id: uuid.UUID,
        start_date: date,
        end_date: date,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> int:
        """查询区间内食材损耗成本（分）

        通过 waste_events + ingredient 单价估算损耗金额。
        """
        start_dt, end_dt = _range_window(start_date, end_date)
        sql = text("""
            SELECT COALESCE(
                SUM(
                    we.quantity
                    * COALESCE(bi_price.unit_cost_fen, 0)
                ), 0
            )::BIGINT AS waste_cost_fen
            FROM waste_events we
            LEFT JOIN LATERAL (
                SELECT bi.unit_cost_fen
                FROM bom_items bi
                WHERE bi.ingredient_id = we.ingredient_id
                  AND bi.is_deleted    = FALSE
                  AND bi.item_action  != 'REMOVE'
                ORDER BY bi.updated_at DESC
                LIMIT 1
            ) bi_price ON TRUE
            WHERE we.store_id    = :store_id
              AND we.tenant_id   = :tenant_id
              AND we.occurred_at >= :start_dt
              AND we.occurred_at <= :end_dt
              AND we.is_deleted  = FALSE
        """)
        try:
            result = await db.execute(
                sql,
                {
                    "store_id": str(store_id),
                    "tenant_id": str(tenant_id),
                    "start_dt": start_dt,
                    "end_dt": end_dt,
                },
            )
            row = result.fetchone()
            return int(row.waste_cost_fen) if row else 0
        except (OperationalError, SQLAlchemyError) as exc:
            logger.warning(
                "fetch_waste_cost.query_failed",
                store_id=str(store_id),
                error=str(exc),
            )
            return 0
