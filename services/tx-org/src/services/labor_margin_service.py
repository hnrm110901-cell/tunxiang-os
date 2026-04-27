"""人力成本毛利联动服务

将每单毛利计算中加入实时人力成本，让老板看到"扣完人工后真赚了多少"。
这是屯象OS独有能力——i人事只有薪资数据没有订单毛利数据。

计算模型：
  真实毛利 = 营收 - 食材成本(BOM) - 渠道佣金 - 时段人力成本
  时段人力成本 = 该时段在岗人数 x 平均时薪 x 时长

金额单位：分（fen）
"""

from __future__ import annotations

from datetime import date
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ── 行业基准 ─────────────────────────────────────────────────────────────────

MARGIN_BENCHMARKS = {
    "正餐": {"min_margin_rate": 0.30, "target_margin_rate": 0.45, "max_labor_rate": 0.30},
    "快餐": {"min_margin_rate": 0.35, "target_margin_rate": 0.50, "max_labor_rate": 0.25},
    "火锅": {"min_margin_rate": 0.40, "target_margin_rate": 0.55, "max_labor_rate": 0.28},
    "宴会": {"min_margin_rate": 0.28, "target_margin_rate": 0.40, "max_labor_rate": 0.35},
}

DEFAULT_FOOD_COST_RATE = 0.38  # 无BOM数据时，按营收38%估算食材成本
DEFAULT_HOURLY_WAGE_FEN = 2500  # 默认时薪25元（2500分）


class LaborMarginService:
    """人力成本毛利联动服务"""

    # ── 实时毛利 ──────────────────────────────────────────────────────────────

    async def get_realtime_margin(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: str,
        target_date: date,
    ) -> dict[str, Any]:
        """实时毛利（含人力成本）——汇总数据"""
        hourly = await self.get_hourly_breakdown(db, tenant_id, store_id, target_date)

        total_revenue = sum(h["revenue_fen"] for h in hourly)
        total_food_cost = sum(h["food_cost_fen"] for h in hourly)
        total_channel_fee = sum(h["channel_fee_fen"] for h in hourly)
        total_labor_cost = sum(h["labor_cost_fen"] for h in hourly)
        total_real_margin = sum(h["real_margin_fen"] for h in hourly)
        margin_rate = round(total_real_margin / total_revenue, 4) if total_revenue > 0 else 0.0
        labor_rate = round(total_labor_cost / total_revenue, 4) if total_revenue > 0 else 0.0
        total_staff = max((h["staff_count"] for h in hourly), default=0)

        return {
            "store_id": store_id,
            "date": str(target_date),
            "revenue_fen": total_revenue,
            "food_cost_fen": total_food_cost,
            "channel_fee_fen": total_channel_fee,
            "labor_cost_fen": total_labor_cost,
            "real_margin_fen": total_real_margin,
            "real_margin_rate": margin_rate,
            "labor_cost_rate": labor_rate,
            "peak_staff_count": total_staff,
            "hourly_count": len([h for h in hourly if h["revenue_fen"] > 0]),
        }

    # ── 按小时分解 ────────────────────────────────────────────────────────────

    async def get_hourly_breakdown(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: str,
        target_date: date,
    ) -> list[dict[str, Any]]:
        """按小时分解（24行数据）"""
        revenue_map = await self._query_hourly_revenue(db, tenant_id, store_id, target_date)
        food_cost_map = await self._query_hourly_food_cost(db, tenant_id, store_id, target_date)
        channel_fee_map = await self._query_hourly_channel_fee(db, tenant_id, store_id, target_date)
        labor_map = await self._query_hourly_labor_cost(db, tenant_id, store_id, target_date)

        result: list[dict[str, Any]] = []
        for hour in range(24):
            revenue = revenue_map.get(hour, 0)
            food_cost = food_cost_map.get(hour, 0)
            # 降级：如果没有BOM数据，按默认食材成本率估算
            if food_cost == 0 and revenue > 0:
                food_cost = int(revenue * DEFAULT_FOOD_COST_RATE)
            channel_fee = channel_fee_map.get(hour, 0)
            labor_info = labor_map.get(hour, {"cost_fen": 0, "staff_count": 0})
            labor_cost = labor_info["cost_fen"]
            staff_count = labor_info["staff_count"]

            real_margin = revenue - food_cost - channel_fee - labor_cost
            margin_rate = round(real_margin / revenue, 4) if revenue > 0 else 0.0
            revenue_per_staff = int(revenue / staff_count) if staff_count > 0 else 0

            result.append(
                {
                    "hour": hour,
                    "revenue_fen": revenue,
                    "food_cost_fen": food_cost,
                    "channel_fee_fen": channel_fee,
                    "labor_cost_fen": labor_cost,
                    "real_margin_fen": real_margin,
                    "margin_rate": margin_rate,
                    "staff_count": staff_count,
                    "revenue_per_staff_fen": revenue_per_staff,
                }
            )
        return result

    # ── 月度趋势 ─────────────────────────────────────────────────────────────

    async def get_monthly_trend(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: str,
        month: str,
    ) -> list[dict[str, Any]]:
        """月度趋势（每日一行）"""
        # 尝试从 mv_store_pnl 物化视图读取
        q = text("""
            SELECT pnl_date::text AS pnl_date,
                   COALESCE(revenue_fen, 0) AS revenue_fen,
                   COALESCE(food_cost_fen, 0) AS food_cost_fen,
                   COALESCE(channel_fee_fen, 0) AS channel_fee_fen,
                   COALESCE(labor_cost_fen, 0) AS labor_cost_fen
            FROM mv_store_pnl
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND store_id = CAST(:store_id AS uuid)
              AND to_char(pnl_date, 'YYYY-MM') = :month
            ORDER BY pnl_date
        """)
        try:
            result = await db.execute(
                q,
                {
                    "tenant_id": tenant_id,
                    "store_id": store_id,
                    "month": month,
                },
            )
            rows = [dict(r) for r in result.mappings()]
            trend: list[dict[str, Any]] = []
            for row in rows:
                rev = int(row["revenue_fen"])
                fc = int(row["food_cost_fen"])
                cf = int(row["channel_fee_fen"])
                lc = int(row["labor_cost_fen"])
                margin = rev - fc - cf - lc
                rate = round(margin / rev, 4) if rev > 0 else 0.0
                trend.append(
                    {
                        "date": row["pnl_date"],
                        "revenue_fen": rev,
                        "food_cost_fen": fc,
                        "channel_fee_fen": cf,
                        "labor_cost_fen": lc,
                        "real_margin_fen": margin,
                        "margin_rate": rate,
                    }
                )
            if trend:
                return trend
        except (OperationalError, ProgrammingError) as exc:
            logger.warning("labor_margin_monthly_pnl_fallback", error=str(exc))

        # 降级：返回空列表
        logger.info("labor_margin_monthly_no_data", store_id=store_id, month=month)
        return []

    # ── 多店对比 ─────────────────────────────────────────────────────────────

    async def get_store_comparison(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_ids: list[str],
        month: str,
    ) -> list[dict[str, Any]]:
        """多店对比"""
        q = text("""
            SELECT s.id::text AS store_id, s.store_name,
                   COALESCE(SUM(p.revenue_fen), 0) AS revenue_fen,
                   COALESCE(SUM(p.food_cost_fen), 0) AS food_cost_fen,
                   COALESCE(SUM(p.channel_fee_fen), 0) AS channel_fee_fen,
                   COALESCE(SUM(p.labor_cost_fen), 0) AS labor_cost_fen
            FROM stores s
            LEFT JOIN mv_store_pnl p
              ON p.store_id = s.id AND p.tenant_id = s.tenant_id
              AND to_char(p.pnl_date, 'YYYY-MM') = :month
            WHERE s.tenant_id = CAST(:tenant_id AS uuid)
              AND s.id = ANY(CAST(:store_ids AS uuid[]))
              AND s.is_deleted = false
            GROUP BY s.id, s.store_name
            ORDER BY s.store_name
        """)
        try:
            result = await db.execute(
                q,
                {
                    "tenant_id": tenant_id,
                    "store_ids": store_ids,
                    "month": month,
                },
            )
            rows = [dict(r) for r in result.mappings()]
            comparison: list[dict[str, Any]] = []
            for row in rows:
                rev = int(row["revenue_fen"])
                fc = int(row["food_cost_fen"])
                cf = int(row["channel_fee_fen"])
                lc = int(row["labor_cost_fen"])
                margin = rev - fc - cf - lc
                rate = round(margin / rev, 4) if rev > 0 else 0.0
                labor_rate = round(lc / rev, 4) if rev > 0 else 0.0
                comparison.append(
                    {
                        "store_id": row["store_id"],
                        "store_name": row["store_name"],
                        "revenue_fen": rev,
                        "food_cost_fen": fc,
                        "channel_fee_fen": cf,
                        "labor_cost_fen": lc,
                        "real_margin_fen": margin,
                        "margin_rate": rate,
                        "labor_cost_rate": labor_rate,
                    }
                )
            return comparison
        except (OperationalError, ProgrammingError) as exc:
            logger.warning("labor_margin_comparison_failed", error=str(exc))
            return []

    # ── 亏损时段识别 ─────────────────────────────────────────────────────────

    async def identify_loss_hours(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: str,
        target_date: date,
    ) -> dict[str, Any]:
        """识别亏损时段 — real_margin < 0 的时段"""
        hourly = await self.get_hourly_breakdown(db, tenant_id, store_id, target_date)

        loss_hours: list[dict[str, Any]] = []
        for h in hourly:
            if h["revenue_fen"] > 0 and h["real_margin_fen"] < 0:
                suggestion = self._generate_loss_suggestion(h)
                loss_hours.append(
                    {
                        **h,
                        "suggestion": suggestion,
                    }
                )

        # 低效时段（毛利率 < 15% 但不亏损）
        low_margin_hours: list[dict[str, Any]] = []
        for h in hourly:
            if h["revenue_fen"] > 0 and 0 <= h["margin_rate"] < 0.15:
                low_margin_hours.append(h)

        total_loss_fen = sum(h["real_margin_fen"] for h in loss_hours)

        return {
            "store_id": store_id,
            "date": str(target_date),
            "loss_hours": loss_hours,
            "loss_hour_count": len(loss_hours),
            "total_loss_fen": total_loss_fen,
            "low_margin_hours": low_margin_hours,
            "low_margin_count": len(low_margin_hours),
            "ai_tag": "AI分析",
        }

    # ── 内部查询方法 ─────────────────────────────────────────────────────────

    async def _query_hourly_revenue(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: str,
        target_date: date,
    ) -> dict[int, int]:
        """A. 营收：查orders表按小时聚合"""
        q = text("""
            SELECT EXTRACT(HOUR FROM created_at)::int AS hour,
                   COALESCE(SUM(total_fen), 0)::bigint AS revenue_fen
            FROM orders
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND store_id = CAST(:store_id AS uuid)
              AND created_at::date = :target_date
              AND status NOT IN ('cancelled', 'refunded')
            GROUP BY EXTRACT(HOUR FROM created_at)
        """)
        try:
            result = await db.execute(
                q,
                {
                    "tenant_id": tenant_id,
                    "store_id": store_id,
                    "target_date": target_date,
                },
            )
            return {int(r["hour"]): int(r["revenue_fen"]) for r in result.mappings()}
        except (OperationalError, ProgrammingError) as exc:
            logger.warning("labor_margin_revenue_query_failed", error=str(exc))
            return {}

    async def _query_hourly_food_cost(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: str,
        target_date: date,
    ) -> dict[int, int]:
        """B. 食材成本：查orders.cost_fen或mv_inventory_bom"""
        # 先尝试 orders.cost_fen
        q = text("""
            SELECT EXTRACT(HOUR FROM created_at)::int AS hour,
                   COALESCE(SUM(cost_fen), 0)::bigint AS food_cost_fen
            FROM orders
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND store_id = CAST(:store_id AS uuid)
              AND created_at::date = :target_date
              AND status NOT IN ('cancelled', 'refunded')
              AND cost_fen IS NOT NULL AND cost_fen > 0
            GROUP BY EXTRACT(HOUR FROM created_at)
        """)
        try:
            result = await db.execute(
                q,
                {
                    "tenant_id": tenant_id,
                    "store_id": store_id,
                    "target_date": target_date,
                },
            )
            data = {int(r["hour"]): int(r["food_cost_fen"]) for r in result.mappings()}
            if data:
                return data
        except (OperationalError, ProgrammingError) as exc:
            logger.warning("labor_margin_food_cost_fallback", error=str(exc))
        # 降级：返回空（调用方会用默认比率估算）
        return {}

    async def _query_hourly_channel_fee(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: str,
        target_date: date,
    ) -> dict[int, int]:
        """C. 渠道佣金：查channel_commissions或降级为0"""
        q = text("""
            SELECT EXTRACT(HOUR FROM created_at)::int AS hour,
                   COALESCE(SUM(commission_fen), 0)::bigint AS channel_fee_fen
            FROM channel_commissions
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND store_id = CAST(:store_id AS uuid)
              AND created_at::date = :target_date
            GROUP BY EXTRACT(HOUR FROM created_at)
        """)
        try:
            result = await db.execute(
                q,
                {
                    "tenant_id": tenant_id,
                    "store_id": store_id,
                    "target_date": target_date,
                },
            )
            return {int(r["hour"]): int(r["channel_fee_fen"]) for r in result.mappings()}
        except (OperationalError, ProgrammingError) as exc:
            logger.debug("labor_margin_channel_fee_unavailable", error=str(exc))
            return {}

    async def _query_hourly_labor_cost(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_id: str,
        target_date: date,
    ) -> dict[int, dict[str, int]]:
        """D. 人力成本：查unified_schedules JOIN employees"""
        q = text("""
            SELECT gs.hour_slot,
                   COUNT(DISTINCT us.employee_id) AS staff_count,
                   COALESCE(SUM(
                       CASE WHEN e.daily_wage_standard_fen > 0
                            THEN e.daily_wage_standard_fen / 8
                            ELSE :default_hourly
                       END
                   ), 0)::bigint AS labor_cost_fen
            FROM unified_schedules us
            JOIN employees e ON e.id = us.employee_id AND e.tenant_id = us.tenant_id
            CROSS JOIN LATERAL generate_series(
                EXTRACT(HOUR FROM us.shift_start)::int,
                GREATEST(EXTRACT(HOUR FROM us.shift_end)::int - 1, EXTRACT(HOUR FROM us.shift_start)::int)
            ) AS gs(hour_slot)
            WHERE us.tenant_id = CAST(:tenant_id AS uuid)
              AND us.store_id = CAST(:store_id AS uuid)
              AND us.schedule_date = :target_date
              AND us.status IN ('confirmed', 'checked_in', 'active')
              AND e.is_deleted = false
            GROUP BY gs.hour_slot
            ORDER BY gs.hour_slot
        """)
        try:
            result = await db.execute(
                q,
                {
                    "tenant_id": tenant_id,
                    "store_id": store_id,
                    "target_date": target_date,
                    "default_hourly": DEFAULT_HOURLY_WAGE_FEN,
                },
            )
            return {
                int(r["hour_slot"]): {
                    "cost_fen": int(r["labor_cost_fen"]),
                    "staff_count": int(r["staff_count"]),
                }
                for r in result.mappings()
            }
        except (OperationalError, ProgrammingError) as exc:
            logger.warning("labor_margin_labor_cost_fallback", error=str(exc))
            return {}

    # ── 建议生成 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _generate_loss_suggestion(hour_data: dict[str, Any]) -> str:
        """基于亏损时段数据生成优化建议"""
        hour = hour_data["hour"]
        staff = hour_data["staff_count"]
        labor = hour_data["labor_cost_fen"]
        revenue = hour_data["revenue_fen"]

        if staff > 3 and revenue < labor:
            return (
                f"{hour}:00-{hour + 1}:00 在岗{staff}人，"
                f"人力成本({labor / 100:.0f}元)超过营收({revenue / 100:.0f}元)。"
                f"建议减少该时段排班至{max(1, staff - 2)}人，"
                f"或推出该时段特价套餐拉动客流。"
            )
        if revenue > 0:
            return f"{hour}:00-{hour + 1}:00 毛利为负。建议优化排班或推出限时折扣拉升客单价。"
        return f"{hour}:00-{hour + 1}:00 无营收但有人力成本，建议调整排班。"
