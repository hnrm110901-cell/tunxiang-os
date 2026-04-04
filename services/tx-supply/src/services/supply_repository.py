"""SupplyRepository -- 供应商 / 损耗 / 需求预测 DB 查询层

将 inventory.py 中的 Mock 端点升级为真实 DB 查询。
Repository 模式，async/await，type hints，graceful fallback。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import Date, cast, desc, func, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Ingredient, IngredientTransaction
from shared.ontology.src.enums import TransactionType

logger = structlog.get_logger(__name__)


def _uuid(val: str | uuid.UUID) -> uuid.UUID:
    return val if isinstance(val, uuid.UUID) else uuid.UUID(str(val))


class SupplyRepository:
    """供应链扩展 Repository -- 供应商/损耗/需求预测 DB 查询"""

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self._tenant_uuid = _uuid(tenant_id)

    async def _set_tenant(self) -> None:
        await self.db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": self.tenant_id},
        )

    # ─── 供应商列表（从 ingredients 聚合） ───

    async def list_suppliers(
        self, page: int = 1, size: int = 20,
    ) -> dict[str, Any]:
        """供应商列表 -- 从 ingredients 表聚合去重 supplier_name

        Returns: {items: [{supplier_name, ingredient_count, categories}], total}
        """
        await self._set_tenant()

        try:
            # 统计每个供应商关联的食材数和品类
            query = (
                select(
                    Ingredient.supplier_name,
                    func.count(Ingredient.id).label("ingredient_count"),
                    func.array_agg(func.distinct(Ingredient.category)).label("categories"),
                )
                .where(
                    Ingredient.tenant_id == self._tenant_uuid,
                    Ingredient.is_deleted == False,  # noqa: E712
                    Ingredient.supplier_name.isnot(None),
                    Ingredient.supplier_name != "",
                )
                .group_by(Ingredient.supplier_name)
                .order_by(Ingredient.supplier_name)
            )

            # 计算总数
            count_subq = query.subquery()
            count_result = await self.db.execute(
                select(func.count()).select_from(count_subq)
            )
            total = count_result.scalar() or 0

            # 分页
            offset = (page - 1) * size
            paginated = query.offset(offset).limit(size)
            result = await self.db.execute(paginated)
            rows = result.all()

            items = []
            for row in rows:
                categories = row.categories or []
                # array_agg 可能包含 None
                categories = [c for c in categories if c]
                items.append({
                    "supplier_name": row.supplier_name,
                    "ingredient_count": row.ingredient_count,
                    "categories": categories,
                })

            return {"items": items, "total": total}
        except ProgrammingError as exc:
            logger.warning("list_suppliers_fallback", error=str(exc))
            return {"items": [], "total": 0}

    # ─── 供应商评分（从 supplier_score_history 表） ───

    async def get_supplier_rating(
        self, supplier_id: str,
    ) -> Optional[dict[str, Any]]:
        """从 supplier_score_history 表查询最新评分

        graceful fallback: 表不存在返回 None
        """
        await self._set_tenant()

        try:
            result = await self.db.execute(
                text("""
                    SELECT supplier_id, composite_score, delivery_rate,
                           quality_rate, price_stability, response_speed,
                           compliance_rate, tier, score_month, created_at
                    FROM supplier_score_history
                    WHERE tenant_id = :tenant_id
                      AND supplier_id = :supplier_id::uuid
                    ORDER BY score_month DESC
                    LIMIT 1
                """),
                {"tenant_id": self.tenant_id, "supplier_id": supplier_id},
            )
            row = result.fetchone()
            if row is None:
                return None
            return dict(row._mapping)
        except ProgrammingError as exc:
            if "does not exist" in str(exc).lower():
                logger.warning("supplier_score_history_not_ready", error=str(exc))
                return None
            raise

    # ─── 供应商价格对比 ───

    async def compare_supplier_prices(
        self, ingredient_id: str,
    ) -> list[dict[str, Any]]:
        """同一食材不同供应商的价格对比

        从 purchase_order_items 聚合各供应商的平均单价
        graceful fallback: 表不存在返回空列表
        """
        await self._set_tenant()

        try:
            result = await self.db.execute(
                text("""
                    SELECT po.supplier_id,
                           AVG(poi.unit_price_fen)::BIGINT AS avg_price_fen,
                           MIN(poi.unit_price_fen)          AS min_price_fen,
                           MAX(poi.unit_price_fen)          AS max_price_fen,
                           COUNT(poi.id)                    AS order_count
                    FROM purchase_order_items poi
                    JOIN purchase_orders po ON po.id = poi.po_id
                    WHERE poi.tenant_id = :tenant_id
                      AND poi.ingredient_id = :ingredient_id::uuid
                      AND po.is_deleted = FALSE
                      AND po.supplier_id IS NOT NULL
                    GROUP BY po.supplier_id
                    ORDER BY avg_price_fen ASC
                """),
                {
                    "tenant_id": self.tenant_id,
                    "ingredient_id": ingredient_id,
                },
            )
            rows = result.fetchall()
            return [dict(row._mapping) for row in rows]
        except ProgrammingError as exc:
            if "does not exist" in str(exc).lower():
                logger.warning("purchase_orders_not_ready_for_price_compare", error=str(exc))
                return []
            raise

    # ─── 损耗 Top5 ───

    async def get_waste_top5(
        self, store_id: str, period: str = "month",
    ) -> list[dict[str, Any]]:
        """损耗 Top5（按金额排序 + 归因）

        从 ingredient_transactions (type=waste) 聚合
        """
        await self._set_tenant()

        store_uuid = _uuid(store_id)
        now = datetime.now(timezone.utc)
        if period == "week":
            since = now - timedelta(days=7)
        elif period == "quarter":
            since = now - timedelta(days=90)
        else:
            since = now - timedelta(days=30)

        try:
            query = (
                select(
                    Ingredient.id.label("ingredient_id"),
                    Ingredient.ingredient_name,
                    Ingredient.category,
                    Ingredient.unit,
                    Ingredient.unit_price_fen,
                    func.count(IngredientTransaction.id).label("event_count"),
                    func.sum(func.abs(IngredientTransaction.quantity)).label("total_qty"),
                )
                .join(
                    IngredientTransaction,
                    IngredientTransaction.ingredient_id == Ingredient.id,
                )
                .where(
                    Ingredient.tenant_id == self._tenant_uuid,
                    Ingredient.store_id == store_uuid,
                    IngredientTransaction.transaction_type == TransactionType.waste.value,
                    IngredientTransaction.is_deleted == False,  # noqa: E712
                    IngredientTransaction.created_at >= since,
                )
                .group_by(
                    Ingredient.id,
                    Ingredient.ingredient_name,
                    Ingredient.category,
                    Ingredient.unit,
                    Ingredient.unit_price_fen,
                )
            )

            result = await self.db.execute(query)
            rows = result.all()

            items = []
            for row in rows:
                unit_price = row.unit_price_fen or 0
                total_qty = float(row.total_qty) if row.total_qty else 0.0
                cost_fen = int(total_qty * unit_price)
                items.append({
                    "ingredient_id": str(row.ingredient_id),
                    "ingredient_name": row.ingredient_name,
                    "category": row.category,
                    "unit": row.unit,
                    "total_waste_qty": round(total_qty, 2),
                    "total_waste_fen": cost_fen,
                    "total_waste_yuan": round(cost_fen / 100, 2),
                    "event_count": row.event_count,
                })

            items.sort(key=lambda x: x["total_waste_fen"], reverse=True)
            return items[:5]
        except ProgrammingError as exc:
            logger.warning("waste_top5_fallback", error=str(exc))
            return []

    # ─── 损耗率 ───

    async def get_waste_rate(
        self, store_id: str,
    ) -> dict[str, Any]:
        """损耗率 -- 近30天损耗金额 / 近30天出库总金额

        graceful fallback: 查询失败返回 0
        """
        await self._set_tenant()

        store_uuid = _uuid(store_id)
        since = datetime.now(timezone.utc) - timedelta(days=30)

        try:
            # 损耗总额
            waste_q = (
                select(
                    func.coalesce(
                        func.sum(
                            func.abs(IngredientTransaction.quantity)
                            * IngredientTransaction.unit_cost_fen
                        ),
                        0,
                    ).label("waste_fen"),
                )
                .where(
                    IngredientTransaction.tenant_id == self._tenant_uuid,
                    IngredientTransaction.store_id == store_uuid,
                    IngredientTransaction.transaction_type == TransactionType.waste.value,
                    IngredientTransaction.is_deleted == False,  # noqa: E712
                    IngredientTransaction.created_at >= since,
                )
            )
            waste_result = await self.db.execute(waste_q)
            waste_fen = int(waste_result.scalar() or 0)

            # 出库总额（usage + waste + transfer）
            out_types = [
                TransactionType.usage.value,
                TransactionType.waste.value,
                TransactionType.transfer.value,
            ]
            total_q = (
                select(
                    func.coalesce(
                        func.sum(
                            func.abs(IngredientTransaction.quantity)
                            * IngredientTransaction.unit_cost_fen
                        ),
                        0,
                    ).label("total_fen"),
                )
                .where(
                    IngredientTransaction.tenant_id == self._tenant_uuid,
                    IngredientTransaction.store_id == store_uuid,
                    IngredientTransaction.transaction_type.in_(out_types),
                    IngredientTransaction.is_deleted == False,  # noqa: E712
                    IngredientTransaction.created_at >= since,
                )
            )
            total_result = await self.db.execute(total_q)
            total_fen = int(total_result.scalar() or 0)

            waste_rate = round(waste_fen / total_fen * 100, 2) if total_fen > 0 else 0.0

            # 近4周趋势
            trend = await self._get_waste_trend(store_uuid, weeks=4)

            return {
                "waste_rate": waste_rate,
                "waste_fen": waste_fen,
                "total_outbound_fen": total_fen,
                "period_days": 30,
                "trend": trend,
            }
        except ProgrammingError as exc:
            logger.warning("waste_rate_fallback", error=str(exc))
            return {"waste_rate": 0, "trend": []}

    async def _get_waste_trend(
        self, store_uuid: uuid.UUID, weeks: int = 4,
    ) -> list[dict[str, Any]]:
        """近 N 周损耗趋势"""
        trend = []
        now = datetime.now(timezone.utc)
        for i in range(weeks - 1, -1, -1):
            week_end = now - timedelta(weeks=i)
            week_start = week_end - timedelta(weeks=1)

            result = await self.db.execute(
                select(
                    func.coalesce(
                        func.sum(
                            func.abs(IngredientTransaction.quantity)
                            * IngredientTransaction.unit_cost_fen
                        ),
                        0,
                    )
                )
                .where(
                    IngredientTransaction.tenant_id == self._tenant_uuid,
                    IngredientTransaction.store_id == store_uuid,
                    IngredientTransaction.transaction_type == TransactionType.waste.value,
                    IngredientTransaction.is_deleted == False,  # noqa: E712
                    IngredientTransaction.created_at >= week_start,
                    IngredientTransaction.created_at < week_end,
                )
            )
            fen = int(result.scalar() or 0)
            trend.append({
                "week_start": week_start.date().isoformat(),
                "week_end": week_end.date().isoformat(),
                "waste_fen": fen,
            })
        return trend

    # ─── 需求预测 ───

    async def forecast_demand(
        self, store_id: str, days: int = 7,
    ) -> list[dict[str, Any]]:
        """需求预测 -- 基于近7天日均消耗 x days 预测

        Returns: [{ingredient_id, ingredient_name, daily_avg, forecast_qty, unit}]
        """
        await self._set_tenant()

        store_uuid = _uuid(store_id)
        lookback = datetime.now(timezone.utc) - timedelta(days=7)

        try:
            query = (
                select(
                    Ingredient.id.label("ingredient_id"),
                    Ingredient.ingredient_name,
                    Ingredient.unit,
                    Ingredient.current_quantity,
                    func.coalesce(
                        func.sum(func.abs(IngredientTransaction.quantity)), 0
                    ).label("total_usage"),
                )
                .outerjoin(
                    IngredientTransaction,
                    (IngredientTransaction.ingredient_id == Ingredient.id)
                    & (IngredientTransaction.transaction_type == TransactionType.usage.value)
                    & (IngredientTransaction.is_deleted == False)  # noqa: E712
                    & (IngredientTransaction.created_at >= lookback),
                )
                .where(
                    Ingredient.tenant_id == self._tenant_uuid,
                    Ingredient.store_id == store_uuid,
                    Ingredient.is_deleted == False,  # noqa: E712
                )
                .group_by(
                    Ingredient.id,
                    Ingredient.ingredient_name,
                    Ingredient.unit,
                    Ingredient.current_quantity,
                )
                .order_by(desc("total_usage"))
            )

            result = await self.db.execute(query)
            rows = result.all()

            forecast = []
            for row in rows:
                total_usage = float(row.total_usage)
                if total_usage <= 0:
                    continue
                daily_avg = total_usage / 7
                forecast_qty = daily_avg * days
                forecast.append({
                    "ingredient_id": str(row.ingredient_id),
                    "ingredient_name": row.ingredient_name,
                    "unit": row.unit,
                    "current_quantity": row.current_quantity,
                    "daily_avg": round(daily_avg, 2),
                    "forecast_qty": round(forecast_qty, 2),
                    "forecast_days": days,
                    "coverage_days": round(row.current_quantity / daily_avg, 1)
                    if daily_avg > 0
                    else None,
                })

            return forecast
        except ProgrammingError as exc:
            logger.warning("forecast_demand_fallback", error=str(exc))
            return []
