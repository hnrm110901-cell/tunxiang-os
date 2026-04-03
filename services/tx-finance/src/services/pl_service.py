"""P&L 损益表 Service 层

完整损益表结构：
  营业收入（堂食/外卖/储值/其他）
  - 食材成本（BOM计算 or 估算）
  - 食材损耗
  = 毛利 / 毛利率

  经营费用
  - 人工成本
  - 房租
  - 水电
  - 其他固定费用
  = 经营利润 / 经营利润率

品牌级 P&L = 多门店加总。

所有金额单位：分（fen）。
"""
from __future__ import annotations

import calendar
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .cost_engine_repository import CostEngineRepository
from .cost_engine_service import CostEngineService, calculate_cost_health_score

logger = structlog.get_logger(__name__)

# 无 BOM 时默认食材成本率
_DEFAULT_FOOD_COST_RATE = 0.30


def _safe_ratio(numerator: int | float, denominator: int | float, precision: int = 4) -> float:
    return round(numerator / denominator, precision) if denominator != 0 else 0.0


def _days_in_period(start_date: date, end_date: date) -> int:
    return (end_date - start_date).days + 1


def _prorate(monthly_fen: int, period_days: int, month_days: int) -> int:
    """将月度固定费用按天数摊销到区间"""
    if month_days <= 0:
        return 0
    return int(monthly_fen * period_days / month_days)


# ─── 数据类 ──────────────────────────────────────────────────────────────────

@dataclass
class RevenueBreakdown:
    """营收明细"""
    dine_in_fen: int = 0          # 堂食收入
    delivery_fen: int = 0         # 外卖收入
    stored_value_fen: int = 0     # 储值卡收现（充值）
    other_fen: int = 0            # 其他收入

    @property
    def total_fen(self) -> int:
        return self.dine_in_fen + self.delivery_fen + self.stored_value_fen + self.other_fen


@dataclass
class CostBreakdown:
    """成本明细"""
    food_cost_fen: int = 0        # 食材成本（BOM计算）
    waste_cost_fen: int = 0       # 食材损耗
    is_estimated: bool = False    # 是否使用估算值
    estimated_reason: str = ""

    @property
    def total_food_cost_fen(self) -> int:
        return self.food_cost_fen + self.waste_cost_fen


@dataclass
class OperatingExpenses:
    """经营费用"""
    labor_cost_fen: int = 0       # 人工成本
    rent_fen: int = 0             # 房租
    utility_fen: int = 0          # 水电
    other_fixed_fen: int = 0      # 其他固定费用

    @property
    def total_fen(self) -> int:
        return self.labor_cost_fen + self.rent_fen + self.utility_fen + self.other_fixed_fen


@dataclass
class PLStatement:
    """门店 P&L 损益表"""
    store_id: uuid.UUID
    start_date: date
    end_date: date
    period_days: int
    revenue: RevenueBreakdown = field(default_factory=RevenueBreakdown)
    cost: CostBreakdown = field(default_factory=CostBreakdown)
    opex: OperatingExpenses = field(default_factory=OperatingExpenses)

    @property
    def total_revenue_fen(self) -> int:
        return self.revenue.total_fen

    @property
    def gross_profit_fen(self) -> int:
        return self.total_revenue_fen - self.cost.total_food_cost_fen

    @property
    def gross_margin_rate(self) -> float:
        return _safe_ratio(self.gross_profit_fen, self.total_revenue_fen)

    @property
    def food_cost_rate(self) -> float:
        return _safe_ratio(self.cost.total_food_cost_fen, self.total_revenue_fen)

    @property
    def operating_profit_fen(self) -> int:
        return self.gross_profit_fen - self.opex.total_fen

    @property
    def operating_margin_rate(self) -> float:
        return _safe_ratio(self.operating_profit_fen, self.total_revenue_fen)

    def to_dict(self) -> dict[str, Any]:
        health = calculate_cost_health_score(self.food_cost_rate)
        return {
            "store_id": str(self.store_id),
            "start_date": str(self.start_date),
            "end_date": str(self.end_date),
            "period_days": self.period_days,
            # ── 营业收入 ──
            "revenue": {
                "dine_in_fen": self.revenue.dine_in_fen,
                "delivery_fen": self.revenue.delivery_fen,
                "stored_value_fen": self.revenue.stored_value_fen,
                "other_fen": self.revenue.other_fen,
                "total_fen": self.total_revenue_fen,
            },
            # ── 营业成本 ──
            "cost": {
                "food_cost_fen": self.cost.food_cost_fen,
                "waste_cost_fen": self.cost.waste_cost_fen,
                "total_food_cost_fen": self.cost.total_food_cost_fen,
                "is_estimated": self.cost.is_estimated,
                "estimated_reason": self.cost.estimated_reason,
            },
            # ── 毛利 ──
            "gross_profit_fen": self.gross_profit_fen,
            "gross_margin_rate": self.gross_margin_rate,
            "gross_margin_rate_pct": round(self.gross_margin_rate * 100, 2),
            "food_cost_rate": self.food_cost_rate,
            "food_cost_rate_pct": round(self.food_cost_rate * 100, 2),
            # ── 经营费用 ──
            "opex": {
                "labor_cost_fen": self.opex.labor_cost_fen,
                "rent_fen": self.opex.rent_fen,
                "utility_fen": self.opex.utility_fen,
                "other_fixed_fen": self.opex.other_fixed_fen,
                "total_fen": self.opex.total_fen,
            },
            # ── 经营利润 ──
            "operating_profit_fen": self.operating_profit_fen,
            "operating_margin_rate": self.operating_margin_rate,
            "operating_margin_rate_pct": round(self.operating_margin_rate * 100, 2),
            # ── 健康度 ──
            "cost_health": health.to_dict(),
        }


@dataclass
class BrandPLStatement:
    """品牌级 P&L（多门店汇总）"""
    brand_id: str
    month: str              # YYYY-MM
    store_count: int
    total_revenue_fen: int
    total_food_cost_fen: int
    total_gross_profit_fen: int
    total_operating_profit_fen: int
    overall_gross_margin_rate: float
    overall_food_cost_rate: float
    overall_operating_margin_rate: float
    is_estimated: bool
    store_details: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        health = calculate_cost_health_score(self.overall_food_cost_rate)
        return {
            "brand_id": self.brand_id,
            "month": self.month,
            "store_count": self.store_count,
            "summary": {
                "total_revenue_fen": self.total_revenue_fen,
                "total_food_cost_fen": self.total_food_cost_fen,
                "total_gross_profit_fen": self.total_gross_profit_fen,
                "total_operating_profit_fen": self.total_operating_profit_fen,
                "gross_margin_rate": self.overall_gross_margin_rate,
                "gross_margin_rate_pct": round(self.overall_gross_margin_rate * 100, 2),
                "food_cost_rate": self.overall_food_cost_rate,
                "food_cost_rate_pct": round(self.overall_food_cost_rate * 100, 2),
                "operating_margin_rate": self.overall_operating_margin_rate,
                "operating_margin_rate_pct": round(self.overall_operating_margin_rate * 100, 2),
                "is_estimated": self.is_estimated,
            },
            "cost_health": health.to_dict(),
            "store_details": self.store_details,
        }


# ─── PLService ────────────────────────────────────────────────────────────────

class PLService:
    """P&L 损益表服务

    所有公共方法接受显式 tenant_id，配合 RLS 双重隔离。
    """

    def __init__(self) -> None:
        self._repo = CostEngineRepository()
        self._cost_svc = CostEngineService()

    # ── 门店 P&L ──────────────────────────────────────────────

    async def get_store_pl(
        self,
        store_id: uuid.UUID,
        start_date: date,
        end_date: date,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> PLStatement:
        """门店 P&L 损益表（支持任意日期区间）

        流程：
        1. 营收：从 orders 按渠道分类汇总
        2. 食材成本：从 cost_snapshots，无快照则估算
        3. 损耗：从 waste_events
        4. 固定费用：从 stores 配置按天摊销
        5. 人工成本：从 payroll_records
        """
        log = logger.bind(
            store_id=str(store_id),
            start_date=str(start_date),
            end_date=str(end_date),
            tenant_id=str(tenant_id),
        )

        period_days = _days_in_period(start_date, end_date)

        # ── 1. 营收明细 ──
        revenue = await self._fetch_revenue_breakdown(
            store_id, start_date, end_date, tenant_id, db
        )

        # ── 2. 食材成本（从 cost_snapshots）──
        food_cost_fen, is_estimated, estimated_reason = await self._fetch_food_cost(
            store_id, start_date, end_date, tenant_id, db, revenue.total_fen
        )

        # ── 3. 损耗成本 ──
        waste_cost_fen = await self._repo.fetch_waste_cost(
            store_id, start_date, end_date, tenant_id, db
        )

        cost = CostBreakdown(
            food_cost_fen=food_cost_fen,
            waste_cost_fen=waste_cost_fen,
            is_estimated=is_estimated,
            estimated_reason=estimated_reason,
        )

        # ── 4. 经营费用（固定成本按天摊销）──
        opex = await self._fetch_operating_expenses(
            store_id, start_date, end_date, period_days, tenant_id, db
        )

        log.info(
            "store_pl.computed",
            total_revenue_fen=revenue.total_fen,
            food_cost_fen=food_cost_fen,
            gross_profit_fen=revenue.total_fen - cost.total_food_cost_fen,
            is_estimated=is_estimated,
        )

        return PLStatement(
            store_id=store_id,
            start_date=start_date,
            end_date=end_date,
            period_days=period_days,
            revenue=revenue,
            cost=cost,
            opex=opex,
        )

    # ── 品牌级 P&L ─────────────────────────────────────────────

    async def get_brand_pl(
        self,
        brand_id: str,
        month: str,       # YYYY-MM
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> BrandPLStatement:
        """品牌级 P&L（指定月份，所有门店汇总）

        month 格式：YYYY-MM
        """
        year, mon = int(month[:4]), int(month[5:7])
        start_date = date(year, mon, 1)
        end_date = date(year, mon, calendar.monthrange(year, mon)[1])

        # 查询品牌下所有门店
        store_ids = await self._fetch_brand_store_ids(brand_id, tenant_id, db)
        if not store_ids:
            return BrandPLStatement(
                brand_id=brand_id,
                month=month,
                store_count=0,
                total_revenue_fen=0,
                total_food_cost_fen=0,
                total_gross_profit_fen=0,
                total_operating_profit_fen=0,
                overall_gross_margin_rate=0.0,
                overall_food_cost_rate=0.0,
                overall_operating_margin_rate=0.0,
                is_estimated=False,
            )

        store_details = []
        total_revenue = 0
        total_food_cost = 0
        total_gross_profit = 0
        total_operating_profit = 0
        any_estimated = False

        for sid in store_ids:
            pl = await self.get_store_pl(sid, start_date, end_date, tenant_id, db)
            store_details.append({
                "store_id": str(sid),
                **{k: v for k, v in pl.to_dict().items() if k != "store_id"},
            })
            total_revenue += pl.total_revenue_fen
            total_food_cost += pl.cost.total_food_cost_fen
            total_gross_profit += pl.gross_profit_fen
            total_operating_profit += pl.operating_profit_fen
            if pl.cost.is_estimated:
                any_estimated = True

        # 按毛利率降序排列门店
        store_details.sort(
            key=lambda x: x.get("gross_margin_rate", 0), reverse=True
        )

        logger.info(
            "brand_pl.computed",
            brand_id=brand_id,
            month=month,
            store_count=len(store_ids),
            total_revenue_fen=total_revenue,
            total_gross_profit_fen=total_gross_profit,
        )

        return BrandPLStatement(
            brand_id=brand_id,
            month=month,
            store_count=len(store_ids),
            total_revenue_fen=total_revenue,
            total_food_cost_fen=total_food_cost,
            total_gross_profit_fen=total_gross_profit,
            total_operating_profit_fen=total_operating_profit,
            overall_gross_margin_rate=_safe_ratio(total_gross_profit, total_revenue),
            overall_food_cost_rate=_safe_ratio(total_food_cost, total_revenue),
            overall_operating_margin_rate=_safe_ratio(total_operating_profit, total_revenue),
            is_estimated=any_estimated,
            store_details=store_details,
        )

    # ── 内部辅助方法 ──────────────────────────────────────────

    async def _fetch_revenue_breakdown(
        self,
        store_id: uuid.UUID,
        start_date: date,
        end_date: date,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> RevenueBreakdown:
        """按渠道分类汇总营收

        order_type 映射：
          dine_in / table → 堂食
          delivery / takeout → 外卖
          stored_value / topup → 储值充值
          其他 → other
        """
        sql = text("""
            SELECT
                o.order_type,
                COALESCE(SUM(o.final_amount_fen), 0) AS revenue_fen
            FROM orders o
            WHERE o.store_id   = :store_id
              AND o.tenant_id  = :tenant_id
              AND o.status     IN ('completed', 'settled', 'paid')
              AND o.order_time >= :start_dt
              AND o.order_time <= :end_dt
              AND o.is_deleted = false
            GROUP BY o.order_type
        """)
        from datetime import datetime, timezone
        start_dt = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=timezone.utc)
        end_dt = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=timezone.utc)

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
            rows = result.all()
        except Exception as exc:  # noqa: BLE001 — DB driver 级别可能有多种异常，降级查总收入
            logger.warning(
                "fetch_revenue_breakdown.query_failed_fallback_total",
                store_id=str(store_id),
                error=str(exc),
            )
            # 降级：查总收入不分类
            total = await self._repo.fetch_daily_revenue_for_cost(
                store_id, start_date, tenant_id, db
            )
            return RevenueBreakdown(dine_in_fen=total)

        rb = RevenueBreakdown()
        _DINE_IN_TYPES = {"dine_in", "table", "pos", "eat_in", "in_store"}
        _DELIVERY_TYPES = {"delivery", "takeout", "take_out", "meituan", "eleme", "douyin"}
        _STORED_VALUE_TYPES = {"stored_value", "topup", "recharge", "top_up"}

        for row in rows:
            ot = (row.order_type or "").lower()
            amt = int(row.revenue_fen)
            if ot in _DINE_IN_TYPES:
                rb.dine_in_fen += amt
            elif ot in _DELIVERY_TYPES:
                rb.delivery_fen += amt
            elif ot in _STORED_VALUE_TYPES:
                rb.stored_value_fen += amt
            else:
                rb.other_fen += amt

        # 如果没有 order_type 区分（所有都落到 other），尝试按 delivery orders 表补充
        if rb.dine_in_fen == 0 and rb.delivery_fen == 0 and rb.other_fen > 0:
            rb.dine_in_fen = rb.other_fen
            rb.other_fen = 0

        return rb

    async def _fetch_food_cost(
        self,
        store_id: uuid.UUID,
        start_date: date,
        end_date: date,
        tenant_id: uuid.UUID,
        db: AsyncSession,
        total_revenue_fen: int,
    ) -> tuple[int, bool, str]:
        """查询区间食材成本，无快照时估算

        返回 (food_cost_fen, is_estimated, estimated_reason)
        """
        sql = text("""
            SELECT COALESCE(SUM(cs.raw_material_cost), 0)::BIGINT AS food_cost_fen
            FROM cost_snapshots cs
            JOIN orders o ON o.id = cs.order_id
            WHERE o.store_id   = :store_id
              AND cs.tenant_id = :tenant_id
              AND o.order_time >= :start_dt
              AND o.order_time <= :end_dt
              AND o.is_deleted = false
        """)
        from datetime import datetime, timezone
        start_dt = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=timezone.utc)
        end_dt = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=timezone.utc)

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
        food_cost_fen = int(row.food_cost_fen) if row else 0

        if food_cost_fen == 0 and total_revenue_fen > 0:
            food_cost_fen = int(total_revenue_fen * _DEFAULT_FOOD_COST_RATE)
            return food_cost_fen, True, "无BOM成本快照，使用行业均值30%估算"

        return food_cost_fen, False, ""

    async def _fetch_operating_expenses(
        self,
        store_id: uuid.UUID,
        start_date: date,
        end_date: date,
        period_days: int,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> OperatingExpenses:
        """获取区间内经营费用

        固定成本按天数摊销：月度金额 × (period_days / 当月天数)
        人工成本：从 payroll_records 按月查询
        """
        # 读取门店固定成本配置
        config = await self._repo.fetch_store_fixed_cost_config(
            store_id, tenant_id, db
        )

        # 按区间跨越的月份摊销固定费用
        rent_fen = 0
        utility_fen = 0
        other_fixed_fen = 0

        # 逐月计算摊销（区间可能跨月）
        current = start_date.replace(day=1)
        while current <= end_date:
            month_days = calendar.monthrange(current.year, current.month)[1]
            month_start = date(current.year, current.month, 1)
            month_end = date(current.year, current.month, month_days)

            # 本月在区间内的天数
            overlap_start = max(start_date, month_start)
            overlap_end = min(end_date, month_end)
            overlap_days = (overlap_end - overlap_start).days + 1

            rent_fen += _prorate(config["monthly_rent_fen"], overlap_days, month_days)
            utility_fen += _prorate(config["monthly_utility_fen"], overlap_days, month_days)
            other_fixed_fen += _prorate(config["monthly_other_fixed_fen"], overlap_days, month_days)

            # 下一个月
            if current.month == 12:
                current = date(current.year + 1, 1, 1)
            else:
                current = date(current.year, current.month + 1, 1)

        # 人工成本：汇总区间内涉及的月份
        labor_cost_fen = 0
        months_covered: set[tuple[int, int]] = set()
        current = start_date
        while current <= end_date:
            months_covered.add((current.year, current.month))
            current += timedelta(days=1)

        for y, m in months_covered:
            month_labor = await self._repo.fetch_monthly_labor_cost(
                store_id, y, m, tenant_id, db
            )
            if month_labor > 0:
                month_days = calendar.monthrange(y, m)[1]
                month_start = date(y, m, 1)
                month_end = date(y, m, month_days)
                overlap_start = max(start_date, month_start)
                overlap_end = min(end_date, month_end)
                overlap_days = (overlap_end - overlap_start).days + 1
                labor_cost_fen += _prorate(month_labor, overlap_days, month_days)

        return OperatingExpenses(
            labor_cost_fen=labor_cost_fen,
            rent_fen=rent_fen,
            utility_fen=utility_fen,
            other_fixed_fen=other_fixed_fen,
        )

    async def _fetch_brand_store_ids(
        self,
        brand_id: str,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> list[uuid.UUID]:
        """查询品牌下所有激活门店 ID"""
        sql = text("""
            SELECT id
            FROM stores
            WHERE brand_id  = :brand_id
              AND tenant_id = :tenant_id
              AND is_active = true
              AND is_deleted = false
            ORDER BY store_name
        """)
        result = await db.execute(
            sql,
            {"brand_id": brand_id, "tenant_id": str(tenant_id)},
        )
        return [row.id for row in result.all()]
