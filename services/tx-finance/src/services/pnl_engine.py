"""损益表引擎 — 门店日/月度 P&L 实时计算

P&L 结构（全部以分为单位）：
  净营收
  - 食材成本（BOM 或 order_item.food_cost_fen 字段）
  = 毛利
  - 人工成本（crew_shifts.actual_hours × Employee.hourly_wage_fen，fallback门店配置比率）
  - 租金（门店配置 monthly_rent_fen ÷ 当月天数）
  - 水电（门店配置 monthly_utilities_fen ÷ 当月天数）
  - 其他运营费（门店配置）
  = 运营利润（EBITDA）

所有金额：分（fen）。禁止 broad except，最外层兜底必须带 exc_info=True。
"""
from __future__ import annotations

import calendar
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import structlog
from sqlalchemy import func, select, text, and_
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Order, OrderItem, Store

logger = structlog.get_logger(__name__)


def _safe_ratio(n: int | float, d: int | float) -> float:
    return round(n / d, 4) if d != 0 else 0.0


def _day_window(biz_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(biz_date, datetime.min.time()).replace(tzinfo=timezone.utc)
    end = datetime.combine(biz_date, datetime.max.time()).replace(tzinfo=timezone.utc)
    return start, end


_COMPLETED = ["completed", "settled", "paid"]


# ─── 数据类 ──────────────────────────────────────────────────────────────────

@dataclass
class PnLStatement:
    """单期损益表（日或月均可用）"""
    store_id: uuid.UUID
    period_start: date
    period_end: date
    period_type: str              # daily | monthly

    # 收入
    gross_revenue_fen: int
    discount_fen: int
    refund_fen: int

    # 成本
    food_cost_fen: int            # 食材成本（BOM或order_item字段）
    labor_cost_fen: int           # 人工成本
    rent_fen: int                 # 租金分摊
    utilities_fen: int            # 水电分摊
    other_opex_fen: int           # 其他运营费

    # KPI
    order_count: int
    # 明细（可选，前端报表用）
    extra: dict[str, Any] = field(default_factory=dict)

    # ── 计算属性 ─────────────────────────────────────────────
    @property
    def net_revenue_fen(self) -> int:
        return self.gross_revenue_fen - self.discount_fen - self.refund_fen

    @property
    def gross_profit_fen(self) -> int:
        return self.net_revenue_fen - self.food_cost_fen

    @property
    def total_opex_fen(self) -> int:
        return self.labor_cost_fen + self.rent_fen + self.utilities_fen + self.other_opex_fen

    @property
    def operating_profit_fen(self) -> int:
        return self.gross_profit_fen - self.total_opex_fen

    @property
    def gross_margin(self) -> float:
        return _safe_ratio(self.gross_profit_fen, self.net_revenue_fen)

    @property
    def operating_margin(self) -> float:
        return _safe_ratio(self.operating_profit_fen, self.net_revenue_fen)

    @property
    def food_cost_ratio(self) -> float:
        return _safe_ratio(self.food_cost_fen, self.net_revenue_fen)

    @property
    def labor_cost_ratio(self) -> float:
        return _safe_ratio(self.labor_cost_fen, self.net_revenue_fen)

    @property
    def avg_ticket_fen(self) -> int:
        return self.net_revenue_fen // self.order_count if self.order_count > 0 else 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "store_id": str(self.store_id),
            "period_start": str(self.period_start),
            "period_end": str(self.period_end),
            "period_type": self.period_type,
            "revenue": {
                "gross_revenue_fen": self.gross_revenue_fen,
                "discount_fen": self.discount_fen,
                "refund_fen": self.refund_fen,
                "net_revenue_fen": self.net_revenue_fen,
            },
            "cogs": {
                "food_cost_fen": self.food_cost_fen,
                "food_cost_ratio": self.food_cost_ratio,
            },
            "gross_profit": {
                "amount_fen": self.gross_profit_fen,
                "gross_margin": self.gross_margin,
            },
            "opex": {
                "labor_cost_fen": self.labor_cost_fen,
                "rent_fen": self.rent_fen,
                "utilities_fen": self.utilities_fen,
                "other_opex_fen": self.other_opex_fen,
                "total_opex_fen": self.total_opex_fen,
                "labor_cost_ratio": self.labor_cost_ratio,
            },
            "operating_profit": {
                "amount_fen": self.operating_profit_fen,
                "operating_margin": self.operating_margin,
            },
            "kpi": {
                "order_count": self.order_count,
                "avg_ticket_fen": self.avg_ticket_fen,
                "gross_margin": self.gross_margin,
                "operating_margin": self.operating_margin,
                "food_cost_ratio": self.food_cost_ratio,
                "labor_cost_ratio": self.labor_cost_ratio,
            },
            **self.extra,
        }


@dataclass
class MonthlyPnL:
    """月度损益表，聚合多日 PnLStatement"""
    store_id: uuid.UUID
    year: int
    month: int
    daily_pnls: list[PnLStatement] = field(default_factory=list)

    @property
    def days_with_data(self) -> int:
        return len(self.daily_pnls)

    def _sum(self, attr: str) -> int:
        return sum(getattr(p, attr) for p in self.daily_pnls)

    @property
    def gross_revenue_fen(self) -> int:
        return self._sum("gross_revenue_fen")

    @property
    def net_revenue_fen(self) -> int:
        return self._sum("net_revenue_fen")

    @property
    def food_cost_fen(self) -> int:
        return self._sum("food_cost_fen")

    @property
    def gross_profit_fen(self) -> int:
        return self.net_revenue_fen - self.food_cost_fen

    @property
    def total_opex_fen(self) -> int:
        return self._sum("total_opex_fen")

    @property
    def operating_profit_fen(self) -> int:
        return self.gross_profit_fen - self.total_opex_fen

    @property
    def order_count(self) -> int:
        return self._sum("order_count")

    @property
    def gross_margin(self) -> float:
        return _safe_ratio(self.gross_profit_fen, self.net_revenue_fen)

    @property
    def operating_margin(self) -> float:
        return _safe_ratio(self.operating_profit_fen, self.net_revenue_fen)

    def to_dict(self) -> dict[str, Any]:
        return {
            "store_id": str(self.store_id),
            "year": self.year,
            "month": self.month,
            "month_label": f"{self.year}-{self.month:02d}",
            "days_in_month": calendar.monthrange(self.year, self.month)[1],
            "days_with_data": self.days_with_data,
            "gross_revenue_fen": self.gross_revenue_fen,
            "net_revenue_fen": self.net_revenue_fen,
            "food_cost_fen": self.food_cost_fen,
            "gross_profit_fen": self.gross_profit_fen,
            "total_opex_fen": self.total_opex_fen,
            "operating_profit_fen": self.operating_profit_fen,
            "order_count": self.order_count,
            "gross_margin": self.gross_margin,
            "operating_margin": self.operating_margin,
            "daily_trend": [
                {
                    "date": str(p.period_start),
                    "net_revenue_fen": p.net_revenue_fen,
                    "gross_profit_fen": p.gross_profit_fen,
                    "operating_profit_fen": p.operating_profit_fen,
                    "order_count": p.order_count,
                }
                for p in sorted(self.daily_pnls, key=lambda x: x.period_start)
            ],
        }


# ─── PnLEngine ───────────────────────────────────────────────────────────────

class PnLEngine:
    """门店损益表引擎

    get_daily_pnl  → 日度 PnLStatement
    get_monthly_pnl → 月度 MonthlyPnL（聚合每日）
    """

    async def get_daily_pnl(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        biz_date: date,
        db: AsyncSession,
    ) -> PnLStatement:
        """计算门店日度损益

        成本来源优先级：
        1. OrderItem.food_cost_fen（BOM已写入字段）
        2. OrderItem.cost_fen fallback（旧字段兼容）
        人工成本：优先从 crew_shifts 表查 actual_hours × Employee.hourly_wage_fen，
                  次级 fallback 到门店配置的 labor_cost_ratio_target × net_revenue。
        租金/水电：门店配置 monthly_rent_fen / monthly_utilities_fen 按天分摊。
        """
        log = logger.bind(
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            biz_date=str(biz_date),
        )
        start_dt, end_dt = _day_window(biz_date)

        # ── 1. 营收汇总 ──────────────────────────────────────
        rev_row = await db.execute(
            select(
                func.coalesce(func.sum(Order.total_amount_fen), 0).label("gross"),
                func.coalesce(func.sum(Order.discount_amount_fen), 0).label("discount"),
                func.count(Order.id).label("cnt"),
            )
            .where(
                and_(
                    Order.tenant_id == tenant_id,
                    Order.store_id == store_id,
                    Order.status.in_(_COMPLETED),
                    Order.order_time >= start_dt,
                    Order.order_time <= end_dt,
                    Order.is_deleted == False,  # noqa: E712
                )
            )
        )
        rev = rev_row.one()
        gross_revenue_fen = int(rev.gross)
        discount_fen = int(rev.discount)
        order_count = int(rev.cnt)

        # ── 2. 退菜金额 ──────────────────────────────────────
        refund_row = await db.execute(
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
        refund_fen = int(refund_row.scalar_one())

        net_revenue_fen = gross_revenue_fen - discount_fen - refund_fen

        # ── 3. 食材成本（food_cost_fen = BOM 计算写入值）───────
        food_cost_row = await db.execute(
            select(
                func.coalesce(func.sum(OrderItem.food_cost_fen), 0).label("food_cost"),
            )
            .join(Order, OrderItem.order_id == Order.id)
            .where(
                and_(
                    Order.tenant_id == tenant_id,
                    Order.store_id == store_id,
                    Order.status.in_(_COMPLETED),
                    Order.order_time >= start_dt,
                    Order.order_time <= end_dt,
                    Order.is_deleted == False,  # noqa: E712
                )
            )
        )
        food_cost_fen = int(food_cost_row.scalar_one())

        # ── 4. 门店配置（人工/租金/水电）───────────────────
        store_cfg = await self._fetch_store_config(tenant_id, store_id, db)
        days_in_month = calendar.monthrange(biz_date.year, biz_date.month)[1]

        labor_cost_fen = await self._compute_labor_cost(
            tenant_id, store_id, start_dt, end_dt, net_revenue_fen, store_cfg, db
        )
        monthly_rent = store_cfg.get("monthly_rent_fen", 0)
        monthly_utilities = store_cfg.get("monthly_utilities_fen", 0)
        rent_fen = monthly_rent // days_in_month
        utilities_fen = monthly_utilities // days_in_month
        other_opex_fen = store_cfg.get("daily_other_opex_fen", 0)

        log.info(
            "daily_pnl_computed",
            gross_revenue_fen=gross_revenue_fen,
            net_revenue_fen=net_revenue_fen,
            food_cost_fen=food_cost_fen,
            labor_cost_fen=labor_cost_fen,
            rent_fen=rent_fen,
            order_count=order_count,
        )

        return PnLStatement(
            store_id=store_id,
            period_start=biz_date,
            period_end=biz_date,
            period_type="daily",
            gross_revenue_fen=gross_revenue_fen,
            discount_fen=discount_fen,
            refund_fen=refund_fen,
            food_cost_fen=food_cost_fen,
            labor_cost_fen=labor_cost_fen,
            rent_fen=rent_fen,
            utilities_fen=utilities_fen,
            other_opex_fen=other_opex_fen,
            order_count=order_count,
        )

    async def get_monthly_pnl(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        year: int,
        month: int,
        db: AsyncSession,
    ) -> MonthlyPnL:
        """月度损益表：聚合该月每一天的 daily PnL"""
        days_in_month = calendar.monthrange(year, month)[1]
        monthly = MonthlyPnL(store_id=store_id, year=year, month=month)

        for day_num in range(1, days_in_month + 1):
            biz_date = date(year, month, day_num)
            if biz_date > date.today():
                break  # 未来日期跳过
            daily = await self.get_daily_pnl(tenant_id, store_id, biz_date, db)
            if daily.order_count > 0 or daily.gross_revenue_fen > 0:
                monthly.daily_pnls.append(daily)

        logger.info(
            "monthly_pnl_computed",
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            year=year,
            month=month,
            days_with_data=monthly.days_with_data,
            net_revenue_fen=monthly.net_revenue_fen,
        )
        return monthly

    # ── 内部方法 ──────────────────────────────────────────────

    async def _fetch_store_config(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict:
        """从门店配置中提取财务参数"""
        result = await db.execute(
            select(Store.config, Store.labor_cost_ratio_target, Store.monthly_revenue_target_fen)
            .where(
                and_(
                    Store.id == store_id,
                    Store.tenant_id == tenant_id,
                    Store.is_deleted == False,  # noqa: E712
                )
            )
        )
        row = result.first()
        if row is None:
            return {}

        cfg = row.config if isinstance(row.config, dict) else {}
        cfg["labor_cost_ratio_target"] = row.labor_cost_ratio_target or 0.25
        cfg["monthly_revenue_target_fen"] = row.monthly_revenue_target_fen or 0
        return cfg

    async def _compute_labor_cost(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        start_dt: datetime,
        end_dt: datetime,
        net_revenue_fen: int,
        store_cfg: dict,
        db: AsyncSession,
    ) -> int:
        """人工成本：尝试从 crew_shifts 计算实际工时×时薪，fallback 到比率估算"""
        try:
            result = await db.execute(
                text("""
                    SELECT COALESCE(SUM(
                        cs.actual_hours * COALESCE(e.hourly_wage_fen, 0)
                    ), 0) AS labor_cost
                    FROM crew_shifts cs
                    JOIN employees e ON e.id = cs.employee_id
                    WHERE cs.store_id = :store_id::UUID
                      AND cs.tenant_id = :tenant_id::UUID
                      AND cs.shift_start >= :start_dt
                      AND cs.shift_start <= :end_dt
                      AND cs.is_deleted = FALSE
                """),
                {
                    "store_id": str(store_id),
                    "tenant_id": str(tenant_id),
                    "start_dt": start_dt.isoformat(),
                    "end_dt": end_dt.isoformat(),
                },
            )
            labor_cost = int(result.scalar() or 0)
            if labor_cost > 0:
                return labor_cost
        except Exception as exc:
            logger.warning(
                "labor_cost_from_shifts.failed_fallback",
                store_id=str(store_id),
                error=str(exc),
                exc_info=True,
            )

        # Fallback：按门店配置比率估算
        ratio = float(store_cfg.get("labor_cost_ratio_target") or 0.25)
        return int(net_revenue_fen * ratio)
