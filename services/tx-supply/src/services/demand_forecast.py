"""需求预测服务 — 日均消耗计算 + 周期预测

策略：
  1. 优先从近N天出库记录计算日均消耗（TransactionType.usage）
  2. 历史数据不足（=0）时，用BOM反推（订单量 × BOM用量）
  3. 支持节假日系数（从配置中读取，默认1.0）

金额单位：分（fen）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

# 节假日系数配置（可由外部配置覆盖）
DEFAULT_HOLIDAY_FACTORS: dict[str, float] = {
    # 格式: "MM-DD": factor  -- 暂无具体配置时默认1.0
}
DEFAULT_HOLIDAY_FACTOR = 1.0


class DemandForecastService:
    """需求预测服务

    职责：
    - 从库存出库记录计算日均消耗
    - 历史不足时用BOM反向推算
    - 预测未来N天需求量（含节假日系数）
    """

    def __init__(
        self,
        holiday_factors: Optional[dict[str, float]] = None,
    ) -> None:
        self._holiday_factors: dict[str, float] = holiday_factors or DEFAULT_HOLIDAY_FACTORS

    # ──────────────────────────────────────────────────────
    #  内部工具
    # ──────────────────────────────────────────────────────

    async def _set_tenant(self, db: AsyncSession, tenant_id: str) -> None:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

    def _get_holiday_factor(self, days: int) -> float:
        """获取未来days天内的节假日系数均值

        当前简化实现：取今天起days天内每天系数的平均值。
        无配置时返回1.0。
        """
        today = datetime.now(timezone.utc).date()
        factors = []
        for i in range(days):
            day = today + timedelta(days=i)
            key = day.strftime("%m-%d")
            factors.append(self._holiday_factors.get(key, DEFAULT_HOLIDAY_FACTOR))
        return sum(factors) / len(factors) if factors else DEFAULT_HOLIDAY_FACTOR

    async def _get_daily_from_db(
        self,
        ingredient_id: str,
        store_id: str,
        days: int,
        tenant_id: str,
        db: AsyncSession,
    ) -> float:
        """从DB出库流水计算日均消耗"""
        import uuid as _uuid_mod

        # 避免循环import，在函数内引入
        from shared.ontology.src.entities import IngredientTransaction
        from shared.ontology.src.enums import TransactionType

        def _uuid(val: str) -> _uuid_mod.UUID:
            return _uuid_mod.UUID(str(val))

        since = datetime.now(timezone.utc) - timedelta(days=days)
        q = (
            select(func.coalesce(func.sum(IngredientTransaction.quantity), 0))
            .where(
                IngredientTransaction.tenant_id == _uuid(tenant_id),
                IngredientTransaction.ingredient_id == _uuid(ingredient_id),
                IngredientTransaction.store_id == _uuid(store_id),
                IngredientTransaction.transaction_type == TransactionType.usage.value,
                IngredientTransaction.is_deleted == False,  # noqa: E712
                IngredientTransaction.created_at >= since,
            )
        )
        result = await db.execute(q)
        total = float(result.scalar() or 0)
        return total / days if days > 0 else 0.0

    async def _get_bom_daily(
        self,
        ingredient_id: str,
        store_id: str,
        days: int,
        tenant_id: str,
        db: AsyncSession,
    ) -> float:
        """BOM反向推算日均消耗

        逻辑：查询近days天内该门店的订单量，乘以BOM中该原料用量，除以天数。
        若BOM数据不可用，返回0.0（不报错）。
        """
        try:
            import uuid as _uuid_mod

            from shared.ontology.src.entities import BOMItem, BOMTemplate, Order, OrderItem

            def _uuid(val: str) -> _uuid_mod.UUID:
                return _uuid_mod.UUID(str(val))

            since = datetime.now(timezone.utc) - timedelta(days=days)

            # 查找含该原料的活跃BOM
            bom_q = (
                select(BOMItem.standard_qty, BOMItem.dish_id)
                .join(BOMTemplate, BOMTemplate.id == BOMItem.bom_template_id)
                .where(
                    BOMItem.ingredient_id == _uuid(ingredient_id),
                    BOMTemplate.tenant_id == _uuid(tenant_id),
                    BOMTemplate.store_id == _uuid(store_id),
                    BOMTemplate.is_active == True,  # noqa: E712
                    BOMTemplate.is_deleted == False,  # noqa: E712
                    BOMItem.is_deleted == False,  # noqa: E712
                )
            )
            bom_result = await db.execute(bom_q)
            bom_rows = bom_result.all()

            if not bom_rows:
                return 0.0

            total_usage = 0.0
            for bom_qty, dish_id in bom_rows:
                # 查询该菜品近N天订单数量
                order_q = (
                    select(func.coalesce(func.sum(OrderItem.quantity), 0))
                    .join(Order, Order.id == OrderItem.order_id)
                    .where(
                        Order.tenant_id == _uuid(tenant_id),
                        Order.store_id == _uuid(store_id),
                        OrderItem.dish_id == dish_id,
                        Order.created_at >= since,
                        Order.is_deleted == False,  # noqa: E712
                    )
                )
                order_result = await db.execute(order_q)
                order_qty = float(order_result.scalar() or 0)
                total_usage += order_qty * float(bom_qty or 0)

            return total_usage / days if days > 0 else 0.0

        except (ImportError, AttributeError, Exception):
            # BOM表或订单表不可用时，静默返回0
            return 0.0

    # ──────────────────────────────────────────────────────
    #  公开接口
    # ──────────────────────────────────────────────────────

    async def get_daily_consumption(
        self,
        ingredient_id: str,
        store_id: str,
        days: int,
        tenant_id: str,
        db: Any,
        *,
        # 测试mock参数（生产中忽略）
        _mock_total_usage: Optional[float] = None,
        _mock_bom_daily: Optional[float] = None,
    ) -> float:
        """计算原料日均消耗量

        优先级：
          1. 出库流水统计（近days天总出库 / days）
          2. 流水为0时，BOM反推（_mock_bom_daily 或 DB BOM查询）
          3. 都为0时，返回0.0（不报错）

        Args:
            ingredient_id: 原料ID
            store_id: 门店ID
            days: 回溯天数（默认7）
            tenant_id: 租户ID（隔离用）
            db: 数据库会话（None时使用mock数据）
            _mock_total_usage: 测试用，注入近N天总出库量
            _mock_bom_daily: 测试用，注入BOM反推日均量

        Returns:
            日均消耗量（float，单位同原料单位）
        """
        if _mock_total_usage is not None:
            # 测试模式：直接使用注入的数值
            daily = _mock_total_usage / days if days > 0 else 0.0
            if daily == 0.0 and _mock_bom_daily is not None:
                daily = _mock_bom_daily
            log.debug(
                "demand_forecast.daily_consumption.mock",
                ingredient_id=ingredient_id,
                store_id=store_id,
                daily=daily,
                tenant_id=tenant_id,
            )
            return daily

        if db is None:
            return 0.0

        # 生产模式：从DB计算
        await self._set_tenant(db, tenant_id)
        daily = await self._get_daily_from_db(ingredient_id, store_id, days, tenant_id, db)

        if daily == 0.0:
            # 历史不足，BOM反推
            daily = await self._get_bom_daily(ingredient_id, store_id, days, tenant_id, db)

        log.info(
            "demand_forecast.daily_consumption",
            ingredient_id=ingredient_id,
            store_id=store_id,
            days=days,
            daily=round(daily, 4),
            tenant_id=tenant_id,
        )
        return daily

    async def forecast_next_period(
        self,
        ingredient_id: str,
        store_id: str,
        days: int,
        tenant_id: str,
        db: Any,
        *,
        _mock_daily: Optional[float] = None,
        _mock_holiday_factor: Optional[float] = None,
    ) -> float:
        """预测未来N天总消耗量

        预测量 = 日均消耗 × days × 节假日系数

        Args:
            ingredient_id: 原料ID
            store_id: 门店ID
            days: 预测天数
            tenant_id: 租户ID
            db: 数据库会话
            _mock_daily: 测试用，注入日均消耗
            _mock_holiday_factor: 测试用，注入节假日系数

        Returns:
            未来N天预计总消耗量（float）
        """
        if _mock_daily is not None:
            daily = _mock_daily
        else:
            daily = await self.get_daily_consumption(
                ingredient_id=ingredient_id,
                store_id=store_id,
                days=7,
                tenant_id=tenant_id,
                db=db,
            )

        if daily == 0.0:
            return 0.0

        if _mock_holiday_factor is not None:
            factor = _mock_holiday_factor
        else:
            factor = self._get_holiday_factor(days)

        forecast = daily * days * factor

        log.info(
            "demand_forecast.forecast_next_period",
            ingredient_id=ingredient_id,
            store_id=store_id,
            days=days,
            daily=round(daily, 4),
            holiday_factor=round(factor, 3),
            forecast=round(forecast, 2),
            tenant_id=tenant_id,
        )
        return forecast
