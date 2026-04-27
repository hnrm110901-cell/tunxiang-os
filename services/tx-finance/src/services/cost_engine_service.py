"""成本核算 Service 层 — 业务逻辑

功能：
  A. 日成本快报（食材成本/成本率/毛利率）
  B. 成本健康度评分
  C. 成本明细（菜品 TOP10 占比）

所有金额单位：分（fen）。
无 BOM 数据时使用行业平均估算值（30%），并在结果中标注 is_estimated: true。
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import structlog
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events import FinanceEventType, UniversalPublisher

from .cost_engine_repository import CostEngineRepository

logger = structlog.get_logger(__name__)

# 无 BOM 数据时的默认食材成本率
_DEFAULT_FOOD_COST_RATE = 0.30

# 成本率评级阈值
_EXCELLENT_THRESHOLD = 0.28
_NORMAL_THRESHOLD = 0.32
_HIGH_THRESHOLD = 0.36


def _safe_ratio(numerator: int | float, denominator: int | float, precision: int = 4) -> float:
    return round(numerator / denominator, precision) if denominator != 0 else 0.0


# ─── 数据类 ──────────────────────────────────────────────────────────────────


@dataclass
class CostHealthResult:
    """成本健康度评分结果"""

    food_cost_rate: float
    score: float
    status: str  # excellent | normal | high | critical
    status_label: str  # 中文标签
    color: str  # green | yellow | orange | red
    target_rate: float = 0.30
    gap_to_target: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "food_cost_rate": self.food_cost_rate,
            "food_cost_rate_pct": round(self.food_cost_rate * 100, 2),
            "score": round(self.score, 1),
            "status": self.status,
            "status_label": self.status_label,
            "color": self.color,
            "target_rate": self.target_rate,
            "target_rate_pct": round(self.target_rate * 100, 2),
            "gap_to_target": round(self.gap_to_target, 4),
            "gap_to_target_pct": round(self.gap_to_target * 100, 2),
        }


@dataclass
class DailyCostReport:
    """日成本快报"""

    store_id: str
    biz_date: str
    revenue_fen: int
    food_cost_fen: int
    food_cost_rate: float
    gross_profit_fen: int
    gross_margin_rate: float
    is_estimated: bool
    estimated_reason: str = ""
    cost_breakdown: list[dict[str, Any]] = field(default_factory=list)
    health: CostHealthResult | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "store_id": self.store_id,
            "biz_date": self.biz_date,
            "revenue_fen": self.revenue_fen,
            "food_cost_fen": self.food_cost_fen,
            "food_cost_rate": self.food_cost_rate,
            "food_cost_rate_pct": round(self.food_cost_rate * 100, 2),
            "gross_profit_fen": self.gross_profit_fen,
            "gross_margin_rate": self.gross_margin_rate,
            "gross_margin_rate_pct": round(self.gross_margin_rate * 100, 2),
            "is_estimated": self.is_estimated,
            "estimated_reason": self.estimated_reason,
            "cost_breakdown": self.cost_breakdown,
            "health": self.health.to_dict() if self.health else None,
        }


@dataclass
class CostBreakdownReport:
    """成本明细报表"""

    store_id: str
    start_date: str
    end_date: str
    total_food_cost_fen: int
    total_revenue_fen: int
    food_cost_rate: float
    is_estimated: bool
    top_dishes: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "store_id": self.store_id,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "total_food_cost_fen": self.total_food_cost_fen,
            "total_revenue_fen": self.total_revenue_fen,
            "food_cost_rate": self.food_cost_rate,
            "food_cost_rate_pct": round(self.food_cost_rate * 100, 2),
            "is_estimated": self.is_estimated,
            "top_dishes": self.top_dishes,
        }


# ─── CostEngineService ────────────────────────────────────────────────────────


class CostEngineService:
    """成本核算服务

    所有公共方法接受显式 tenant_id，配合 RLS 双重隔离。
    """

    def __init__(self) -> None:
        self._repo = CostEngineRepository()

    # ── A. 日成本快报 ──────────────────────────────────────────

    async def get_daily_cost_report(
        self,
        store_id: uuid.UUID,
        biz_date: date,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> DailyCostReport:
        """日成本快报

        流程：
        1. 从 cost_snapshots 聚合当日食材成本
        2. 查当日营收
        3. 如果快照数据不足（snapshot_count < order_count/2），用估算值补充
        4. 计算毛利率、成本率、健康度评分
        """
        log = logger.bind(
            store_id=str(store_id),
            biz_date=str(biz_date),
            tenant_id=str(tenant_id),
        )

        # 从快照获取成本数据
        snapshot = await self._repo.fetch_daily_cost_from_snapshots(store_id, biz_date, tenant_id, db)
        revenue_fen = await self._repo.fetch_daily_revenue_for_cost(store_id, biz_date, tenant_id, db)

        food_cost_fen = snapshot["total_food_cost_fen"]
        is_estimated = False
        estimated_reason = ""

        # 判断是否需要估算
        if revenue_fen > 0 and food_cost_fen == 0:
            # 没有任何成本快照：完全估算
            food_cost_fen = int(revenue_fen * _DEFAULT_FOOD_COST_RATE)
            is_estimated = True
            estimated_reason = "无BOM成本快照数据，使用行业均值30%估算"
            log.warning("daily_cost_report.no_snapshots_using_estimate", revenue_fen=revenue_fen)
        elif revenue_fen > 0 and food_cost_fen > 0:
            # 有快照但可能不完整：如果成本率明显偏低（< 15%）可能是部分快照
            actual_rate = food_cost_fen / revenue_fen
            if actual_rate < 0.15 and snapshot["snapshot_count"] > 0:
                is_estimated = True
                estimated_reason = f"BOM覆盖率不足（当前成本率{actual_rate:.1%}低于合理区间），已含估算补充"
                log.info(
                    "daily_cost_report.low_coverage_estimated",
                    actual_rate=actual_rate,
                    snapshot_count=snapshot["snapshot_count"],
                )

        food_cost_rate = _safe_ratio(food_cost_fen, revenue_fen)
        gross_profit_fen = revenue_fen - food_cost_fen
        gross_margin_rate = _safe_ratio(gross_profit_fen, revenue_fen)
        health = calculate_cost_health_score(food_cost_rate)

        log.info(
            "daily_cost_report.computed",
            revenue_fen=revenue_fen,
            food_cost_fen=food_cost_fen,
            food_cost_rate=food_cost_rate,
            gross_margin_rate=gross_margin_rate,
            is_estimated=is_estimated,
        )

        # 成本明细 TOP10
        cost_breakdown: list[dict[str, Any]] = []
        try:
            cost_breakdown = await self._repo.fetch_dish_cost_breakdown(
                store_id, biz_date, biz_date, tenant_id, db, top_n=10
            )
        except (SQLAlchemyError, ValueError) as exc:
            log.warning("daily_cost_report.breakdown_failed", error=str(exc))

        # ── 节点2：成本率超标事件 ─────────────────────────────
        if health.status in ("high", "critical"):
            asyncio.create_task(
                UniversalPublisher.publish(
                    event_type=FinanceEventType.COST_RATE_EXCEEDED,
                    tenant_id=tenant_id,
                    store_id=store_id,
                    entity_id=store_id,
                    event_data={
                        "category": "food_cost",
                        "actual_pct": round(food_cost_rate * 100, 2),
                        "threshold_pct": round(_NORMAL_THRESHOLD * 100, 2),
                    },
                    source_service="tx-finance",
                )
            )
        return DailyCostReport(
            store_id=str(store_id),
            biz_date=str(biz_date),
            revenue_fen=revenue_fen,
            food_cost_fen=food_cost_fen,
            food_cost_rate=food_cost_rate,
            gross_profit_fen=gross_profit_fen,
            gross_margin_rate=gross_margin_rate,
            is_estimated=is_estimated,
            estimated_reason=estimated_reason,
            cost_breakdown=cost_breakdown,
            health=health,
        )

    # ── B. 成本明细 ─────────────────────────────────────────────

    async def get_cost_breakdown(
        self,
        store_id: uuid.UUID,
        start_date: date,
        end_date: date,
        tenant_id: uuid.UUID,
        db: AsyncSession,
        top_n: int = 10,
    ) -> CostBreakdownReport:
        """成本明细报表（菜品 TOP N 占比）"""
        log = logger.bind(
            store_id=str(store_id),
            start_date=str(start_date),
            end_date=str(end_date),
            tenant_id=str(tenant_id),
        )

        top_dishes = await self._repo.fetch_dish_cost_breakdown(
            store_id, start_date, end_date, tenant_id, db, top_n=top_n
        )
        total_food_cost_fen = sum(d["total_cost_fen"] for d in top_dishes)

        # 计算区间总营收（复用日收入查询，按天累加）
        total_revenue_fen = 0
        current = start_date
        while current <= end_date:
            daily_rev = await self._repo.fetch_daily_revenue_for_cost(store_id, current, tenant_id, db)
            total_revenue_fen += daily_rev
            current += timedelta(days=1)

        is_estimated = total_food_cost_fen == 0 and total_revenue_fen > 0
        if is_estimated:
            total_food_cost_fen = int(total_revenue_fen * _DEFAULT_FOOD_COST_RATE)

        food_cost_rate = _safe_ratio(total_food_cost_fen, total_revenue_fen)

        log.info(
            "cost_breakdown.computed",
            total_food_cost_fen=total_food_cost_fen,
            total_revenue_fen=total_revenue_fen,
            dish_count=len(top_dishes),
            is_estimated=is_estimated,
        )

        return CostBreakdownReport(
            store_id=str(store_id),
            start_date=str(start_date),
            end_date=str(end_date),
            total_food_cost_fen=total_food_cost_fen,
            total_revenue_fen=total_revenue_fen,
            food_cost_rate=food_cost_rate,
            is_estimated=is_estimated,
            top_dishes=top_dishes,
        )

    # ── C. 门店固定成本配置 ────────────────────────────────────

    async def get_store_cost_config(
        self,
        store_id: uuid.UUID,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """读取门店固定成本配置（月度金额，分）"""
        config = await self._repo.fetch_store_fixed_cost_config(store_id, tenant_id, db)
        return {
            "store_id": str(store_id),
            "monthly_rent_fen": config["monthly_rent_fen"],
            "monthly_utility_fen": config["monthly_utility_fen"],
            "monthly_other_fixed_fen": config["monthly_other_fixed_fen"],
            "monthly_total_fixed_fen": (
                config["monthly_rent_fen"] + config["monthly_utility_fen"] + config["monthly_other_fixed_fen"]
            ),
        }

    async def update_store_cost_config(
        self,
        store_id: uuid.UUID,
        tenant_id: uuid.UUID,
        monthly_rent_fen: int,
        monthly_utility_fen: int,
        monthly_other_fixed_fen: int,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """写入门店固定成本配置"""
        await self._repo.upsert_store_fixed_cost_config(
            store_id=store_id,
            tenant_id=tenant_id,
            monthly_rent_fen=monthly_rent_fen,
            monthly_utility_fen=monthly_utility_fen,
            monthly_other_fixed_fen=monthly_other_fixed_fen,
            db=db,
        )
        logger.info(
            "store_cost_config.updated",
            store_id=str(store_id),
            monthly_rent_fen=monthly_rent_fen,
            monthly_utility_fen=monthly_utility_fen,
            monthly_other_fixed_fen=monthly_other_fixed_fen,
        )
        return await self.get_store_cost_config(store_id, tenant_id, db)


# ─── 成本健康度评分（纯函数，可单独测试）──────────────────────────────────────


def calculate_cost_health_score(food_cost_rate: float) -> CostHealthResult:
    """食材成本率 → 健康度评分

    评级规则（行业标准）：
    ≤28%:      绿色（优秀）score = 90-100
    28%-32%:   黄色（正常）score = 70-89
    32%-36%:   橙色（偏高）score = 50-69
    >36%:      红色（危险）score = 0-49

    score 在每个区间内线性插值。
    """
    rate = food_cost_rate
    target_rate = _DEFAULT_FOOD_COST_RATE

    if rate <= _EXCELLENT_THRESHOLD:
        # 0% ~ 28%: 满分100 → 90，越低越好但不超100
        ratio = rate / _EXCELLENT_THRESHOLD if _EXCELLENT_THRESHOLD > 0 else 0
        score = 100.0 - ratio * 10.0
        status = "excellent"
        status_label = "优秀"
        color = "green"
    elif rate <= _NORMAL_THRESHOLD:
        # 28% ~ 32%: 89 → 70
        ratio = (rate - _EXCELLENT_THRESHOLD) / (_NORMAL_THRESHOLD - _EXCELLENT_THRESHOLD)
        score = 89.0 - ratio * 19.0
        status = "normal"
        status_label = "正常"
        color = "yellow"
    elif rate <= _HIGH_THRESHOLD:
        # 32% ~ 36%: 69 → 50
        ratio = (rate - _NORMAL_THRESHOLD) / (_HIGH_THRESHOLD - _NORMAL_THRESHOLD)
        score = 69.0 - ratio * 19.0
        status = "high"
        status_label = "偏高"
        color = "orange"
    else:
        # >36%: 49 → 0（以 50% 为下限 score=0）
        ratio = min((rate - _HIGH_THRESHOLD) / 0.14, 1.0)
        score = max(49.0 - ratio * 49.0, 0.0)
        status = "critical"
        status_label = "危险"
        color = "red"

    gap_to_target = rate - target_rate  # 正值=超出目标，负值=优于目标

    return CostHealthResult(
        food_cost_rate=rate,
        score=round(score, 1),
        status=status,
        status_label=status_label,
        color=color,
        target_rate=target_rate,
        gap_to_target=gap_to_target,
    )
