"""PLReportService — P&L报表服务

功能：
- 日P&L = 收入 - 原料成本 - 期间费用
- 期间P&L（支持日/周/月聚合）
- 多店P&L对比
- 同比/环比计算
- 凭证列表查询
"""
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal, Optional

import structlog
from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


# ─── 数据类 ──────────────────────────────────────────────────────────────────

@dataclass
class PLReport:
    """P&L报表数据结构

    金额单位：分（fen）
    """
    store_id: uuid.UUID
    start_date: date
    end_date: date
    revenue_fen: int
    raw_material_cost_fen: int
    period_days: int
    labor_cost_fen: int = 0
    rent_fen: int = 0
    other_opex_fen: int = 0

    @property
    def gross_profit_fen(self) -> int:
        return self.revenue_fen - self.raw_material_cost_fen

    @property
    def total_opex_fen(self) -> int:
        return self.labor_cost_fen + self.rent_fen + self.other_opex_fen

    @property
    def net_profit_fen(self) -> int:
        return self.gross_profit_fen - self.total_opex_fen

    @property
    def gross_margin_rate(self) -> float:
        if self.revenue_fen <= 0:
            return 0.0
        return round(self.gross_profit_fen / self.revenue_fen, 4)

    @property
    def net_margin_rate(self) -> float:
        if self.revenue_fen <= 0:
            return 0.0
        return round(self.net_profit_fen / self.revenue_fen, 4)

    @property
    def avg_daily_revenue_fen(self) -> int:
        if self.period_days <= 0:
            return self.revenue_fen
        return self.revenue_fen // self.period_days

    def to_dict(self) -> dict:
        return {
            "store_id": str(self.store_id),
            "start_date": str(self.start_date),
            "end_date": str(self.end_date),
            "period_days": self.period_days,
            "revenue_fen": self.revenue_fen,
            "raw_material_cost_fen": self.raw_material_cost_fen,
            "labor_cost_fen": self.labor_cost_fen,
            "rent_fen": self.rent_fen,
            "other_opex_fen": self.other_opex_fen,
            "gross_profit_fen": self.gross_profit_fen,
            "total_opex_fen": self.total_opex_fen,
            "net_profit_fen": self.net_profit_fen,
            "gross_margin_rate": self.gross_margin_rate,
            "net_margin_rate": self.net_margin_rate,
            "avg_daily_revenue_fen": self.avg_daily_revenue_fen,
        }


# ─── PLReportService ─────────────────────────────────────────────────────────

class PLReportService:
    """P&L报表服务

    所有方法接受显式 tenant_id，结合 DB session 的 RLS 实现双重隔离。
    """

    # ── 日P&L ─────────────────────────────────────────────────

    async def get_daily_pl(
        self,
        store_id: uuid.UUID,
        biz_date: date,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> PLReport:
        """日P&L报表

        收入：当天所有已完成订单的 final_amount_fen 合计
        原料成本：cost_snapshots 中 raw_material_cost × quantity 合计
        """
        log = logger.bind(
            store_id=str(store_id),
            biz_date=str(biz_date),
            tenant_id=str(tenant_id),
        )

        revenue_fen = await self._fetch_daily_revenue(store_id, biz_date, tenant_id, db)
        raw_cost_fen = await self._fetch_daily_raw_cost(store_id, biz_date, tenant_id, db)
        opex = await self._fetch_daily_opex(store_id, biz_date, tenant_id, db)

        log.info(
            "daily_pl_computed",
            revenue=revenue_fen,
            raw_cost=raw_cost_fen,
            gross_margin=round((revenue_fen - raw_cost_fen) / revenue_fen, 4) if revenue_fen else 0,
        )

        return PLReport(
            store_id=store_id,
            start_date=biz_date,
            end_date=biz_date,
            revenue_fen=revenue_fen,
            raw_material_cost_fen=raw_cost_fen,
            labor_cost_fen=opex.get("labor_cost_fen", 0),
            rent_fen=opex.get("rent_fen", 0),
            other_opex_fen=opex.get("other_opex_fen", 0),
            period_days=1,
        )

    # ── 期间P&L ───────────────────────────────────────────────

    async def get_period_pl(
        self,
        store_id: uuid.UUID,
        start_date: date,
        end_date: date,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> PLReport:
        """期间P&L（支持任意日期范围，日/周/月均适用）"""
        log = logger.bind(
            store_id=str(store_id),
            start=str(start_date),
            end=str(end_date),
            tenant_id=str(tenant_id),
        )

        daily_rows = await self._fetch_period_daily_rows(
            store_id, start_date, end_date, tenant_id, db
        )

        total_revenue = sum(r.get("revenue_fen", 0) for r in daily_rows)
        total_raw_cost = sum(r.get("raw_cost_fen", 0) for r in daily_rows)
        period_days = (end_date - start_date).days + 1

        log.info(
            "period_pl_computed",
            days=period_days,
            total_revenue=total_revenue,
            total_raw_cost=total_raw_cost,
        )

        return PLReport(
            store_id=store_id,
            start_date=start_date,
            end_date=end_date,
            revenue_fen=total_revenue,
            raw_material_cost_fen=total_raw_cost,
            period_days=period_days,
        )

    # ── 多店P&L对比 ───────────────────────────────────────────

    async def get_stores_pl(
        self,
        store_ids: list[uuid.UUID],
        biz_date: date,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> list[PLReport]:
        """多店当日P&L对比，返回按毛利率降序排列的列表"""
        rows = await self._fetch_stores_daily_data(store_ids, biz_date, tenant_id, db)

        results = []
        for row in rows:
            sid = row["store_id"] if isinstance(row["store_id"], uuid.UUID) else uuid.UUID(str(row["store_id"]))
            results.append(PLReport(
                store_id=sid,
                start_date=biz_date,
                end_date=biz_date,
                revenue_fen=int(row.get("revenue_fen", 0)),
                raw_material_cost_fen=int(row.get("raw_cost_fen", 0)),
                period_days=1,
            ))

        results.sort(key=lambda r: r.gross_margin_rate, reverse=True)
        return results

    # ── 同比/环比 ──────────────────────────────────────────────

    async def get_period_pl_with_comparison(
        self,
        store_id: uuid.UUID,
        start_date: date,
        end_date: date,
        tenant_id: uuid.UUID,
        db: AsyncSession,
        comparison: Literal["yoy", "mom"] = "yoy",
    ) -> dict[str, Any]:
        """期间P&L含同比/环比

        comparison:
          yoy = year-over-year（同比：去年同期）
          mom = month-over-month（环比：上个自然月）
        """
        # 当期
        current_rows = await self._fetch_period_daily_rows(
            store_id, start_date, end_date, tenant_id, db
        )
        current_rev = sum(r.get("revenue_fen", 0) for r in current_rows)
        current_cost = sum(r.get("raw_cost_fen", 0) for r in current_rows)

        # 对比期
        prior_start, prior_end = self._calc_prior_period(start_date, end_date, comparison)
        prior_rows = await self._fetch_period_daily_rows(
            store_id, prior_start, prior_end, tenant_id, db
        )
        prior_rev = sum(r.get("revenue_fen", 0) for r in prior_rows)
        prior_cost = sum(r.get("raw_cost_fen", 0) for r in prior_rows)

        def _safe_rate(current: int, prior: int) -> float:
            if prior <= 0:
                return 0.0
            return round((current - prior) / prior, 4)

        result: dict[str, Any] = {
            "store_id": str(store_id),
            "current": {
                "start_date": str(start_date),
                "end_date": str(end_date),
                "revenue_fen": current_rev,
                "raw_material_cost_fen": current_cost,
                "gross_profit_fen": current_rev - current_cost,
            },
            "prior": {
                "start_date": str(prior_start),
                "end_date": str(prior_end),
                "revenue_fen": prior_rev,
                "raw_material_cost_fen": prior_cost,
                "gross_profit_fen": prior_rev - prior_cost,
            },
            "revenue_yoy_rate" if comparison == "yoy" else "revenue_mom_rate":
                _safe_rate(current_rev, prior_rev),
            "cost_yoy_rate" if comparison == "yoy" else "cost_mom_rate":
                _safe_rate(current_cost, prior_cost),
        }
        return result

    # ── 凭证查询 ──────────────────────────────────────────────

    async def get_vouchers(
        self,
        store_id: uuid.UUID,
        biz_date: date,
        tenant_id: uuid.UUID,
        db: AsyncSession,
        status: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """查询门店指定日期的凭证列表"""
        return await self._fetch_vouchers(store_id, biz_date, tenant_id, db, status)

    # ── DB 查询（可在测试中 patch）────────────────────────────

    async def _fetch_daily_revenue(
        self,
        store_id: uuid.UUID,
        biz_date: date,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> int:
        """当天订单总收入（分）"""
        from shared.ontology.src.entities import Order

        start_dt = datetime.combine(biz_date, datetime.min.time()).replace(tzinfo=timezone.utc)
        end_dt = datetime.combine(biz_date, datetime.max.time()).replace(tzinfo=timezone.utc)

        result = await db.execute(
            select(func.coalesce(func.sum(Order.final_amount_fen), 0))
            .where(
                and_(
                    Order.store_id == store_id,
                    Order.tenant_id == tenant_id,
                    Order.status.in_(["completed", "settled"]),
                    Order.created_at >= start_dt,
                    Order.created_at <= end_dt,
                )
            )
        )
        return int(result.scalar_one())

    async def _fetch_daily_raw_cost(
        self,
        store_id: uuid.UUID,
        biz_date: date,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> int:
        """从 cost_snapshots 聚合当天原料成本（分）"""
        start_dt = datetime.combine(biz_date, datetime.min.time()).replace(tzinfo=timezone.utc)
        end_dt = datetime.combine(biz_date, datetime.max.time()).replace(tzinfo=timezone.utc)

        result = await db.execute(
            text("""
                SELECT COALESCE(SUM(cs.raw_material_cost), 0) AS total_cost
                FROM cost_snapshots cs
                JOIN orders o ON o.id = cs.order_id
                WHERE o.store_id = :store_id
                  AND cs.tenant_id = :tenant_id
                  AND cs.computed_at >= :start_dt
                  AND cs.computed_at <= :end_dt
            """),
            {
                "store_id": str(store_id),
                "tenant_id": str(tenant_id),
                "start_dt": start_dt.isoformat(),
                "end_dt": end_dt.isoformat(),
            },
        )
        row = result.fetchone()
        return int(row.total_cost) if row else 0

    async def _fetch_daily_opex(
        self,
        store_id: uuid.UUID,
        biz_date: date,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict[str, int]:
        """从门店配置获取期间费用（人工/租金/其他）

        实际生产中可从 store_expense_config 表读取。
        当前实现从 stores.config JSONB 读取固定成本配置。
        """
        from shared.ontology.src.entities import Store

        result = await db.execute(
            select(Store.config)
            .where(
                and_(
                    Store.id == store_id,
                    Store.tenant_id == tenant_id,
                )
            )
        )
        row = result.fetchone()
        if not row or not row.config:
            return {}

        config = row.config if isinstance(row.config, dict) else {}
        fixed_costs = config.get("fixed_costs", {})

        return {
            "labor_cost_fen": int(fixed_costs.get("daily_labor_fen", 0)),
            "rent_fen": int(fixed_costs.get("daily_rent_fen", 0)),
            "other_opex_fen": int(fixed_costs.get("daily_other_fen", 0)),
        }

    async def _fetch_period_daily_rows(
        self,
        store_id: uuid.UUID,
        start_date: date,
        end_date: date,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        """按天聚合期间收入与原料成本"""
        start_dt = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=timezone.utc)
        end_dt = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=timezone.utc)

        result = await db.execute(
            text("""
                SELECT
                    DATE(o.created_at AT TIME ZONE 'UTC') AS biz_date,
                    COALESCE(SUM(o.final_amount_fen), 0)  AS revenue_fen,
                    COALESCE(SUM(cs_agg.raw_cost), 0)     AS raw_cost_fen
                FROM orders o
                LEFT JOIN LATERAL (
                    SELECT SUM(cs.raw_material_cost) AS raw_cost
                    FROM cost_snapshots cs
                    WHERE cs.order_id = o.id
                      AND cs.tenant_id = :tenant_id
                ) cs_agg ON TRUE
                WHERE o.store_id = :store_id
                  AND o.tenant_id = :tenant_id
                  AND o.status IN ('completed', 'settled')
                  AND o.created_at >= :start_dt
                  AND o.created_at <= :end_dt
                GROUP BY DATE(o.created_at AT TIME ZONE 'UTC')
                ORDER BY biz_date
            """),
            {
                "store_id": str(store_id),
                "tenant_id": str(tenant_id),
                "start_dt": start_dt.isoformat(),
                "end_dt": end_dt.isoformat(),
            },
        )
        rows = result.fetchall()
        return [
            {
                "biz_date": row.biz_date,
                "revenue_fen": int(row.revenue_fen),
                "raw_cost_fen": int(row.raw_cost_fen),
            }
            for row in rows
        ]

    async def _fetch_stores_daily_data(
        self,
        store_ids: list[uuid.UUID],
        biz_date: date,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        """一次性查询多个门店的当日收入与成本"""
        start_dt = datetime.combine(biz_date, datetime.min.time()).replace(tzinfo=timezone.utc)
        end_dt = datetime.combine(biz_date, datetime.max.time()).replace(tzinfo=timezone.utc)

        sid_strs = [str(s) for s in store_ids]

        result = await db.execute(
            text("""
                SELECT
                    o.store_id,
                    COALESCE(SUM(o.final_amount_fen), 0)  AS revenue_fen,
                    COALESCE(SUM(cs_agg.raw_cost), 0)     AS raw_cost_fen
                FROM orders o
                LEFT JOIN LATERAL (
                    SELECT SUM(cs.raw_material_cost) AS raw_cost
                    FROM cost_snapshots cs
                    WHERE cs.order_id = o.id
                      AND cs.tenant_id = :tenant_id
                ) cs_agg ON TRUE
                WHERE o.store_id = ANY(:store_ids::UUID[])
                  AND o.tenant_id = :tenant_id
                  AND o.status IN ('completed', 'settled')
                  AND o.created_at >= :start_dt
                  AND o.created_at <= :end_dt
                GROUP BY o.store_id
            """),
            {
                "store_ids": sid_strs,
                "tenant_id": str(tenant_id),
                "start_dt": start_dt.isoformat(),
                "end_dt": end_dt.isoformat(),
            },
        )
        return [
            {
                "store_id": row.store_id,
                "revenue_fen": int(row.revenue_fen),
                "raw_cost_fen": int(row.raw_cost_fen),
            }
            for row in result.fetchall()
        ]

    async def _fetch_vouchers(
        self,
        store_id: uuid.UUID,
        biz_date: date,
        tenant_id: uuid.UUID,
        db: AsyncSession,
        status: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """查询凭证列表"""
        params: dict[str, Any] = {
            "store_id": str(store_id),
            "tenant_id": str(tenant_id),
            "voucher_date": str(biz_date),
        }
        status_clause = ""
        if status:
            status_clause = "AND status = :status"
            params["status"] = status

        result = await db.execute(
            text(f"""
                SELECT id, voucher_no, voucher_type, total_amount, status, created_at
                FROM financial_vouchers
                WHERE store_id = :store_id::UUID
                  AND tenant_id = :tenant_id::UUID
                  AND voucher_date = :voucher_date::DATE
                  {status_clause}
                ORDER BY created_at DESC
            """),
            params,
        )
        return [
            {
                "id": str(row.id),
                "voucher_no": row.voucher_no,
                "voucher_type": row.voucher_type,
                "total_amount": str(row.total_amount),
                "status": row.status,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in result.fetchall()
        ]

    # ── 工具方法 ──────────────────────────────────────────────

    @staticmethod
    def _calc_prior_period(
        start: date,
        end: date,
        comparison: str,
    ) -> tuple[date, date]:
        """计算对比期的日期范围"""
        if comparison == "yoy":
            prior_start = start.replace(year=start.year - 1)
            prior_end = end.replace(year=end.year - 1)
        else:  # mom
            # 上个月同期：往前推 period_days + (当月第1天到start的天数)
            # 简化：直接减去当前period的天数
            period_days = (end - start).days + 1
            prior_end = start - timedelta(days=1)
            prior_start = prior_end - timedelta(days=period_days - 1)

        return prior_start, prior_end
