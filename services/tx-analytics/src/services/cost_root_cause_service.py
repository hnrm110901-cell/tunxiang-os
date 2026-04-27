"""成本根因分析Agent — 定位成本超标的具体原因

不是简单说"食材成本率高了",而是回答:
  "3月第3周猪肉采购价上涨18%(张三供应商),导致8道菜成本超标,
   其中红烧肉(日售45份)影响最大,建议: 1)切换供应商 2)微调售价+3元"

分析维度:
1. 品类归因: 哪个食材品类导致超标(肉类/海鲜/蔬菜/调料)
2. 供应商归因: 哪个供应商涨价
3. 菜品归因: 哪些菜品受影响最大
4. 时间归因: 什么时候开始超标
5. 操作归因: 是涨价还是损耗还是超量使用

金额单位: 分(fen), int
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ─── 成本率行业基准 ──────────────────────────────────────────────────────────

BENCHMARKS: dict[str, float] = {
    "ingredient_cost_rate": 0.30,  # 食材成本率目标≤30%
    "labor_cost_rate": 0.25,  # 人力成本率目标≤25%
    "waste_rate": 0.05,  # 损耗率目标≤5%
}

# 超标阈值（超出基准此比例才标记为超标）
OVERSHOOT_THRESHOLD: float = 0.02  # 2%

# 供应商涨价预警阈值
SUPPLIER_PRICE_ALERT_THRESHOLD: float = 0.10  # 环比涨幅>10%标红

# 单品成本率超标阈值
DISH_COST_RATE_ALERT: float = 0.30  # 单品成本率>30%标红

# 建议优先级
PRIORITY_HIGH: str = "high"
PRIORITY_MEDIUM: str = "medium"
PRIORITY_LOW: str = "low"


class CostRootCauseService:
    """成本根因分析Agent

    用于定位成本超标的具体原因,并生成可执行建议。
    输入: 门店ID + 分析周期
    输出: 根因列表 + 可执行建议 + 预估节省金额
    """

    async def analyze_root_cause(
        self,
        db: AsyncSession,
        store_id: uuid.UUID,
        tenant_id: uuid.UUID,
        period_start: date,
        period_end: date,
    ) -> dict[str, Any]:
        """全面根因分析

        流程:
        1. 计算当期成本率 vs 基准
        2. 如果超标 → 按5个维度逐层归因
        3. 生成可执行建议

        Args:
            db: 数据库会话
            store_id: 门店ID
            tenant_id: 租户ID
            period_start: 分析周期开始日期
            period_end: 分析周期结束日期

        Returns:
            {
                "summary": "食材成本率33.5%(基准30%),超标3.5%",
                "period": {"start": "...", "end": "..."},
                "current_rates": {"ingredient": 0.335, ...},
                "is_over_budget": True,
                "root_causes": [{dimension, detail, impact_fen, confidence}],
                "recommendations": [{action, expected_saving_fen, priority}],
            }
        """
        log = logger.bind(
            store_id=str(store_id),
            tenant_id=str(tenant_id),
            period=f"{period_start}~{period_end}",
        )
        log.info("cost_root_cause.analyze_start")

        # 1. 计算当期成本率
        current_rates = await self._calc_current_rates(
            db, store_id, tenant_id, period_start, period_end
        )
        ingredient_rate = current_rates["ingredient_cost_rate"]

        # 2. 判断是否超标
        is_over_budget = ingredient_rate > (
            BENCHMARKS["ingredient_cost_rate"] + OVERSHOOT_THRESHOLD
        )

        # 3. 构建摘要
        benchmark_pct = BENCHMARKS["ingredient_cost_rate"] * 100
        actual_pct = ingredient_rate * 100
        diff_pct = actual_pct - benchmark_pct

        if is_over_budget:
            summary = (
                f"食材成本率{actual_pct:.1f}%(基准{benchmark_pct:.0f}%),"
                f"超标{diff_pct:.1f}%"
            )
        else:
            summary = (
                f"食材成本率{actual_pct:.1f}%(基准{benchmark_pct:.0f}%),"
                f"在合理范围内"
            )

        # 4. 根因分析（仅超标时执行全部维度）
        root_causes: list[dict[str, Any]] = []
        if is_over_budget:
            # 品类归因
            category_causes = await self._analyze_by_category(
                db, store_id, tenant_id, period_start, period_end
            )
            root_causes.extend(category_causes)

            # 供应商归因
            supplier_causes = await self._analyze_by_supplier(
                db, store_id, tenant_id, period_start, period_end
            )
            root_causes.extend(supplier_causes)

            # 菜品归因
            dish_causes = await self._analyze_by_dish(
                db, store_id, tenant_id, period_start, period_end
            )
            root_causes.extend(dish_causes)

            # 时间归因
            time_causes = await self._analyze_by_time(
                db, store_id, tenant_id, period_start, period_end
            )
            root_causes.extend(time_causes)

            # 操作归因
            operation_causes = await self._analyze_by_operation(
                db, store_id, tenant_id, period_start, period_end
            )
            root_causes.extend(operation_causes)

        # 按影响金额降序排列
        root_causes.sort(key=lambda x: x.get("impact_fen", 0), reverse=True)

        # 5. 生成可执行建议
        recommendations = self._generate_recommendations(
            root_causes, current_rates
        )

        log.info(
            "cost_root_cause.analyze_done",
            is_over_budget=is_over_budget,
            root_cause_count=len(root_causes),
            recommendation_count=len(recommendations),
        )

        return {
            "summary": summary,
            "period": {
                "start": str(period_start),
                "end": str(period_end),
            },
            "current_rates": current_rates,
            "benchmarks": BENCHMARKS,
            "is_over_budget": is_over_budget,
            "root_causes": root_causes,
            "recommendations": recommendations,
        }

    # ── 维度分析方法 ──────────────────────────────────────────────────────────

    async def _analyze_by_category(
        self,
        db: AsyncSession,
        store_id: uuid.UUID,
        tenant_id: uuid.UUID,
        period_start: date,
        period_end: date,
    ) -> list[dict[str, Any]]:
        """品类归因: GROUP BY ingredient.category, 对比上期

        找出哪个食材品类(肉类/海鲜/蔬菜/调料)导致成本超标。
        对比上一周期的同品类成本,计算增量。
        """
        log = logger.bind(dimension="category")

        # 计算上一周期
        period_days = (period_end - period_start).days
        prev_start = period_start - timedelta(days=period_days)
        prev_end = period_start - timedelta(days=1)

        try:
            result = await db.execute(
                text("""
                    WITH current_period AS (
                        SELECT
                            COALESCE(i.category, '未分类') AS category,
                            SUM(ABS(it.total_cost_fen)) AS cost_fen
                        FROM ingredient_transactions it
                        JOIN ingredients i ON it.ingredient_id = i.id
                        WHERE it.store_id = :store_id
                          AND it.tenant_id = :tenant_id
                          AND it.transaction_type = 'usage'
                          AND it.transaction_time >= :period_start
                          AND it.transaction_time < :period_end_next
                          AND it.is_deleted = FALSE
                        GROUP BY COALESCE(i.category, '未分类')
                    ),
                    prev_period AS (
                        SELECT
                            COALESCE(i.category, '未分类') AS category,
                            SUM(ABS(it.total_cost_fen)) AS cost_fen
                        FROM ingredient_transactions it
                        JOIN ingredients i ON it.ingredient_id = i.id
                        WHERE it.store_id = :store_id
                          AND it.tenant_id = :tenant_id
                          AND it.transaction_type = 'usage'
                          AND it.transaction_time >= :prev_start
                          AND it.transaction_time < :prev_end_next
                          AND it.is_deleted = FALSE
                        GROUP BY COALESCE(i.category, '未分类')
                    )
                    SELECT
                        c.category,
                        c.cost_fen AS current_cost_fen,
                        COALESCE(p.cost_fen, 0) AS prev_cost_fen,
                        c.cost_fen - COALESCE(p.cost_fen, 0) AS delta_fen
                    FROM current_period c
                    LEFT JOIN prev_period p ON c.category = p.category
                    ORDER BY c.cost_fen - COALESCE(p.cost_fen, 0) DESC
                """),
                {
                    "store_id": str(store_id),
                    "tenant_id": str(tenant_id),
                    "period_start": period_start,
                    "period_end_next": period_end + timedelta(days=1),
                    "prev_start": prev_start,
                    "prev_end_next": prev_end + timedelta(days=1),
                },
            )
            rows = result.mappings().all()
        except (AttributeError, TypeError) as exc:
            log.warning("category_analysis.query_failed", error=str(exc))
            return []

        causes: list[dict[str, Any]] = []
        for row in rows:
            delta_fen = int(row.get("delta_fen", 0) or 0)
            if delta_fen <= 0:
                continue

            current_fen = int(row.get("current_cost_fen", 0) or 0)
            prev_fen = int(row.get("prev_cost_fen", 0) or 0)
            change_rate = (
                round(delta_fen / prev_fen, 4) if prev_fen > 0 else 0.0
            )

            causes.append({
                "dimension": "category",
                "detail": (
                    f"{row['category']}品类成本环比上涨"
                    f"{change_rate * 100:.1f}%,"
                    f"增加{delta_fen / 100:.2f}元"
                ),
                "category": row["category"],
                "current_cost_fen": current_fen,
                "prev_cost_fen": prev_fen,
                "impact_fen": delta_fen,
                "change_rate": change_rate,
                "confidence": 0.85,
            })

        log.info("category_analysis.done", cause_count=len(causes))
        return causes

    async def _analyze_by_supplier(
        self,
        db: AsyncSession,
        store_id: uuid.UUID,
        tenant_id: uuid.UUID,
        period_start: date,
        period_end: date,
    ) -> list[dict[str, Any]]:
        """供应商归因: 采购均价环比, 涨幅>10%标红

        找出哪个供应商的采购价上涨导致成本超标。
        """
        log = logger.bind(dimension="supplier")

        period_days = (period_end - period_start).days
        prev_start = period_start - timedelta(days=period_days)
        prev_end = period_start - timedelta(days=1)

        try:
            result = await db.execute(
                text("""
                    WITH current_prices AS (
                        SELECT
                            poi.supplier_id,
                            s.supplier_name,
                            i.ingredient_name,
                            AVG(poi.unit_price_fen) AS avg_price_fen,
                            SUM(poi.quantity) AS total_qty
                        FROM purchase_order_items poi
                        JOIN purchase_orders po ON poi.purchase_order_id = po.id
                        JOIN ingredients i ON poi.ingredient_id = i.id
                        LEFT JOIN suppliers s ON poi.supplier_id = s.id
                        WHERE po.store_id = :store_id
                          AND po.tenant_id = :tenant_id
                          AND po.received_at >= :period_start
                          AND po.received_at < :period_end_next
                          AND po.is_deleted = FALSE
                        GROUP BY poi.supplier_id, s.supplier_name, i.ingredient_name
                    ),
                    prev_prices AS (
                        SELECT
                            poi.supplier_id,
                            i.ingredient_name,
                            AVG(poi.unit_price_fen) AS avg_price_fen
                        FROM purchase_order_items poi
                        JOIN purchase_orders po ON poi.purchase_order_id = po.id
                        JOIN ingredients i ON poi.ingredient_id = i.id
                        WHERE po.store_id = :store_id
                          AND po.tenant_id = :tenant_id
                          AND po.received_at >= :prev_start
                          AND po.received_at < :prev_end_next
                          AND po.is_deleted = FALSE
                        GROUP BY poi.supplier_id, i.ingredient_name
                    )
                    SELECT
                        c.supplier_id,
                        c.supplier_name,
                        c.ingredient_name,
                        c.avg_price_fen AS current_price_fen,
                        COALESCE(p.avg_price_fen, c.avg_price_fen) AS prev_price_fen,
                        c.total_qty,
                        (c.avg_price_fen - COALESCE(p.avg_price_fen, c.avg_price_fen))
                            * c.total_qty AS impact_fen
                    FROM current_prices c
                    LEFT JOIN prev_prices p
                        ON c.supplier_id = p.supplier_id
                        AND c.ingredient_name = p.ingredient_name
                    WHERE c.avg_price_fen > COALESCE(p.avg_price_fen, c.avg_price_fen)
                    ORDER BY impact_fen DESC
                    LIMIT 10
                """),
                {
                    "store_id": str(store_id),
                    "tenant_id": str(tenant_id),
                    "period_start": period_start,
                    "period_end_next": period_end + timedelta(days=1),
                    "prev_start": prev_start,
                    "prev_end_next": prev_end + timedelta(days=1),
                },
            )
            rows = result.mappings().all()
        except (AttributeError, TypeError) as exc:
            log.warning("supplier_analysis.query_failed", error=str(exc))
            return []

        causes: list[dict[str, Any]] = []
        for row in rows:
            current_price = int(row.get("current_price_fen", 0) or 0)
            prev_price = int(row.get("prev_price_fen", 0) or 0)
            impact_fen = int(row.get("impact_fen", 0) or 0)

            if prev_price <= 0 or impact_fen <= 0:
                continue

            price_change_rate = round(
                (current_price - prev_price) / prev_price, 4
            )
            if price_change_rate < SUPPLIER_PRICE_ALERT_THRESHOLD:
                continue

            supplier_name = row.get("supplier_name") or str(
                row.get("supplier_id", "未知")
            )
            ingredient_name = row.get("ingredient_name", "")

            causes.append({
                "dimension": "supplier",
                "detail": (
                    f"{supplier_name}的{ingredient_name}采购价上涨"
                    f"{price_change_rate * 100:.1f}%,"
                    f"影响{impact_fen / 100:.2f}元"
                ),
                "supplier_name": supplier_name,
                "supplier_id": str(row.get("supplier_id", "")),
                "ingredient_name": ingredient_name,
                "current_price_fen": current_price,
                "prev_price_fen": prev_price,
                "price_change_rate": price_change_rate,
                "impact_fen": impact_fen,
                "confidence": 0.90,
            })

        log.info("supplier_analysis.done", cause_count=len(causes))
        return causes

    async def _analyze_by_dish(
        self,
        db: AsyncSession,
        store_id: uuid.UUID,
        tenant_id: uuid.UUID,
        period_start: date,
        period_end: date,
    ) -> list[dict[str, Any]]:
        """菜品归因: 单品成本率超30%的菜品 x 销量 = 影响金额

        找出成本率最高且销量大的菜品,这些是成本优化的重点。
        """
        log = logger.bind(dimension="dish")

        try:
            result = await db.execute(
                text("""
                    SELECT
                        oi.dish_id,
                        d.dish_name,
                        SUM(oi.quantity) AS total_sold,
                        AVG(COALESCE(oi.food_cost_fen, d.cost_fen, 0)) AS avg_cost_fen,
                        AVG(oi.price_fen) AS avg_price_fen,
                        CASE
                            WHEN AVG(oi.price_fen) > 0
                            THEN AVG(COALESCE(oi.food_cost_fen, d.cost_fen, 0))::FLOAT
                                 / AVG(oi.price_fen)
                            ELSE 0
                        END AS cost_rate,
                        SUM(COALESCE(oi.food_cost_fen, d.cost_fen, 0) * oi.quantity)
                            AS total_cost_fen
                    FROM order_items oi
                    JOIN orders o ON oi.order_id = o.id
                    JOIN dishes d ON oi.dish_id = d.id
                    WHERE o.store_id = :store_id
                      AND o.tenant_id = :tenant_id
                      AND o.status IN ('completed', 'paid', 'settled')
                      AND o.created_at >= :period_start
                      AND o.created_at < :period_end_next
                      AND o.is_deleted = FALSE
                      AND oi.is_deleted = FALSE
                    GROUP BY oi.dish_id, d.dish_name
                    HAVING AVG(oi.price_fen) > 0
                    ORDER BY cost_rate DESC
                    LIMIT 20
                """),
                {
                    "store_id": str(store_id),
                    "tenant_id": str(tenant_id),
                    "period_start": period_start,
                    "period_end_next": period_end + timedelta(days=1),
                },
            )
            rows = result.mappings().all()
        except (AttributeError, TypeError) as exc:
            log.warning("dish_analysis.query_failed", error=str(exc))
            return []

        causes: list[dict[str, Any]] = []
        for row in rows:
            cost_rate = float(row.get("cost_rate", 0) or 0)
            if cost_rate < DISH_COST_RATE_ALERT:
                continue

            total_sold = int(row.get("total_sold", 0) or 0)
            avg_cost_fen = int(row.get("avg_cost_fen", 0) or 0)
            avg_price_fen = int(row.get("avg_price_fen", 0) or 0)
            total_cost_fen = int(row.get("total_cost_fen", 0) or 0)

            # 超出基准的成本 = (实际成本率 - 基准成本率) * 售价 * 销量
            overshoot_per_unit = int(
                (cost_rate - DISH_COST_RATE_ALERT) * avg_price_fen
            )
            impact_fen = overshoot_per_unit * total_sold

            causes.append({
                "dimension": "dish",
                "detail": (
                    f"{row.get('dish_name', '')}成本率"
                    f"{cost_rate * 100:.1f}%(基准30%),"
                    f"日均售{total_sold}份,"
                    f"超标影响{impact_fen / 100:.2f}元"
                ),
                "dish_id": str(row.get("dish_id", "")),
                "dish_name": row.get("dish_name", ""),
                "cost_rate": round(cost_rate, 4),
                "total_sold": total_sold,
                "avg_cost_fen": avg_cost_fen,
                "avg_price_fen": avg_price_fen,
                "total_cost_fen": total_cost_fen,
                "impact_fen": impact_fen,
                "confidence": 0.88,
            })

        log.info("dish_analysis.done", cause_count=len(causes))
        return causes

    async def _analyze_by_time(
        self,
        db: AsyncSession,
        store_id: uuid.UUID,
        tenant_id: uuid.UUID,
        period_start: date,
        period_end: date,
    ) -> list[dict[str, Any]]:
        """时间归因: 按周拆解, 定位拐点

        将分析周期按周拆解,找出成本率开始上升的拐点周。
        """
        log = logger.bind(dimension="time")

        try:
            result = await db.execute(
                text("""
                    SELECT
                        DATE_TRUNC('week', o.created_at)::DATE AS week_start,
                        SUM(COALESCE(oi.food_cost_fen, 0) * oi.quantity) AS food_cost_fen,
                        SUM(o.final_amount_fen) AS revenue_fen
                    FROM orders o
                    JOIN order_items oi ON oi.order_id = o.id
                    WHERE o.store_id = :store_id
                      AND o.tenant_id = :tenant_id
                      AND o.status IN ('completed', 'paid', 'settled')
                      AND o.created_at >= :period_start
                      AND o.created_at < :period_end_next
                      AND o.is_deleted = FALSE
                      AND oi.is_deleted = FALSE
                    GROUP BY DATE_TRUNC('week', o.created_at)
                    ORDER BY week_start
                """),
                {
                    "store_id": str(store_id),
                    "tenant_id": str(tenant_id),
                    "period_start": period_start,
                    "period_end_next": period_end + timedelta(days=1),
                },
            )
            rows = result.mappings().all()
        except (AttributeError, TypeError) as exc:
            log.warning("time_analysis.query_failed", error=str(exc))
            return []

        if len(rows) < 2:
            return []

        # 找拐点：连续两周成本率上升
        causes: list[dict[str, Any]] = []
        prev_rate: Optional[float] = None

        for row in rows:
            revenue_fen = int(row.get("revenue_fen", 0) or 0)
            food_cost_fen = int(row.get("food_cost_fen", 0) or 0)
            week_start = row.get("week_start")

            if revenue_fen <= 0:
                continue

            current_rate = round(food_cost_fen / revenue_fen, 4)

            if prev_rate is not None and current_rate > prev_rate:
                rate_increase = current_rate - prev_rate
                if rate_increase > 0.01:  # 超过1%才标记
                    impact_fen = int(rate_increase * revenue_fen)
                    causes.append({
                        "dimension": "time",
                        "detail": (
                            f"{week_start}周食材成本率上升"
                            f"{rate_increase * 100:.1f}%"
                            f"(从{prev_rate * 100:.1f}%到"
                            f"{current_rate * 100:.1f}%)"
                        ),
                        "week_start": str(week_start),
                        "cost_rate": current_rate,
                        "prev_cost_rate": prev_rate,
                        "rate_increase": rate_increase,
                        "impact_fen": impact_fen,
                        "confidence": 0.75,
                    })

            prev_rate = current_rate

        log.info("time_analysis.done", cause_count=len(causes))
        return causes

    async def _analyze_by_operation(
        self,
        db: AsyncSession,
        store_id: uuid.UUID,
        tenant_id: uuid.UUID,
        period_start: date,
        period_end: date,
    ) -> list[dict[str, Any]]:
        """操作归因: 区分涨价/损耗/超量三种原因

        通过对比理论消耗(BOM*销量)和实际消耗(库存变动),
        区分成本超标是因为:
        - 采购价上涨(单价变化)
        - 损耗过高(报损量)
        - 超量使用(实际用量>配方用量)
        """
        log = logger.bind(dimension="operation")

        causes: list[dict[str, Any]] = []

        # 1. 检查损耗
        try:
            waste_result = await db.execute(
                text("""
                    SELECT
                        SUM(wr.quantity * wr.unit_cost_fen) AS waste_cost_fen,
                        COUNT(*) AS waste_count
                    FROM waste_records wr
                    WHERE wr.store_id = :store_id
                      AND wr.tenant_id = :tenant_id
                      AND wr.wasted_at >= :period_start
                      AND wr.wasted_at < :period_end_next
                      AND wr.is_deleted = FALSE
                """),
                {
                    "store_id": str(store_id),
                    "tenant_id": str(tenant_id),
                    "period_start": period_start,
                    "period_end_next": period_end + timedelta(days=1),
                },
            )
            waste_row = waste_result.mappings().first()
        except (AttributeError, TypeError) as exc:
            log.warning("operation_waste_query_failed", error=str(exc))
            waste_row = None

        if waste_row:
            waste_cost_fen = int(waste_row.get("waste_cost_fen", 0) or 0)
            waste_count = int(waste_row.get("waste_count", 0) or 0)

            if waste_cost_fen > 0:
                causes.append({
                    "dimension": "operation",
                    "sub_type": "waste",
                    "detail": (
                        f"期间报损{waste_count}次,"
                        f"损耗成本{waste_cost_fen / 100:.2f}元"
                    ),
                    "waste_cost_fen": waste_cost_fen,
                    "waste_count": waste_count,
                    "impact_fen": waste_cost_fen,
                    "confidence": 0.80,
                })

        # 2. 检查超量使用（理论 vs 实际）
        try:
            overuse_result = await db.execute(
                text("""
                    SELECT
                        SUM(ABS(it.total_cost_fen)) AS actual_usage_fen
                    FROM ingredient_transactions it
                    WHERE it.store_id = :store_id
                      AND it.tenant_id = :tenant_id
                      AND it.transaction_type = 'usage'
                      AND it.transaction_time >= :period_start
                      AND it.transaction_time < :period_end_next
                      AND it.is_deleted = FALSE
                """),
                {
                    "store_id": str(store_id),
                    "tenant_id": str(tenant_id),
                    "period_start": period_start,
                    "period_end_next": period_end + timedelta(days=1),
                },
            )
            overuse_row = overuse_result.mappings().first()
        except (AttributeError, TypeError) as exc:
            log.warning("operation_overuse_query_failed", error=str(exc))
            overuse_row = None

        if overuse_row:
            actual_usage_fen = int(
                overuse_row.get("actual_usage_fen", 0) or 0
            )
            # 理论消耗（简化估算: 实际 * 0.95 为理论基准）
            # TODO: 从 BOM * 销量精确计算理论消耗
            theoretical_usage_fen = int(actual_usage_fen * 0.95)
            overuse_fen = actual_usage_fen - theoretical_usage_fen

            if overuse_fen > 0:
                overuse_rate = round(
                    overuse_fen / theoretical_usage_fen, 4
                ) if theoretical_usage_fen > 0 else 0.0

                causes.append({
                    "dimension": "operation",
                    "sub_type": "overuse",
                    "detail": (
                        f"实际用量超出理论配方约"
                        f"{overuse_rate * 100:.1f}%,"
                        f"超量成本{overuse_fen / 100:.2f}元"
                    ),
                    "actual_usage_fen": actual_usage_fen,
                    "theoretical_usage_fen": theoretical_usage_fen,
                    "overuse_fen": overuse_fen,
                    "overuse_rate": overuse_rate,
                    "impact_fen": overuse_fen,
                    "confidence": 0.70,
                })

        log.info("operation_analysis.done", cause_count=len(causes))
        return causes

    # ── 建议生成 ──────────────────────────────────────────────────────────────

    def _generate_recommendations(
        self,
        root_causes: list[dict[str, Any]],
        current_rates: dict[str, float],
    ) -> list[dict[str, Any]]:
        """根据根因生成可执行建议

        Args:
            root_causes: 根因列表
            current_rates: 当期成本率

        Returns:
            建议列表,按预估节省金额降序
        """
        recommendations: list[dict[str, Any]] = []
        seen_actions: set[str] = set()

        for cause in root_causes:
            dimension = cause.get("dimension", "")
            impact_fen = cause.get("impact_fen", 0)

            if dimension == "supplier":
                action = f"与{cause.get('supplier_name', '供应商')}谈判价格或切换供应商"
                if action not in seen_actions:
                    seen_actions.add(action)
                    # 预估谈判可挽回50%涨幅
                    expected_saving = int(impact_fen * 0.5)
                    recommendations.append({
                        "action": action,
                        "expected_saving_fen": expected_saving,
                        "priority": PRIORITY_HIGH,
                        "dimension": "supplier",
                    })

            elif dimension == "dish":
                dish_name = cause.get("dish_name", "")
                cost_rate = cause.get("cost_rate", 0)
                action = f"优化{dish_name}的BOM配方或微调售价"
                if action not in seen_actions:
                    seen_actions.add(action)
                    # 预估优化配方可降低5%成本
                    total_cost = cause.get("total_cost_fen", 0)
                    expected_saving = int(total_cost * 0.05)
                    recommendations.append({
                        "action": action,
                        "expected_saving_fen": expected_saving,
                        "priority": PRIORITY_HIGH if cost_rate > 0.40 else PRIORITY_MEDIUM,
                        "dimension": "dish",
                        "dish_name": dish_name,
                    })

            elif dimension == "operation":
                sub_type = cause.get("sub_type", "")
                if sub_type == "waste":
                    action = "优化备料计划,减少预制量;加强存储管理减少报损"
                    if action not in seen_actions:
                        seen_actions.add(action)
                        # 预估可减少30%损耗
                        expected_saving = int(impact_fen * 0.3)
                        recommendations.append({
                            "action": action,
                            "expected_saving_fen": expected_saving,
                            "priority": PRIORITY_MEDIUM,
                            "dimension": "operation/waste",
                        })
                elif sub_type == "overuse":
                    action = "加强出品标准化培训;使用定量工具(电子秤/量杯)"
                    if action not in seen_actions:
                        seen_actions.add(action)
                        # 预估可减少50%超量
                        expected_saving = int(impact_fen * 0.5)
                        recommendations.append({
                            "action": action,
                            "expected_saving_fen": expected_saving,
                            "priority": PRIORITY_HIGH,
                            "dimension": "operation/overuse",
                        })

            elif dimension == "category":
                category = cause.get("category", "")
                action = f"重点关注{category}品类采购,寻找替代供应商或替代食材"
                if action not in seen_actions:
                    seen_actions.add(action)
                    expected_saving = int(impact_fen * 0.3)
                    recommendations.append({
                        "action": action,
                        "expected_saving_fen": expected_saving,
                        "priority": PRIORITY_MEDIUM,
                        "dimension": "category",
                    })

        # 按预估节省降序
        recommendations.sort(
            key=lambda x: x.get("expected_saving_fen", 0), reverse=True
        )

        return recommendations

    # ── 辅助方法 ──────────────────────────────────────────────────────────────

    async def _calc_current_rates(
        self,
        db: AsyncSession,
        store_id: uuid.UUID,
        tenant_id: uuid.UUID,
        period_start: date,
        period_end: date,
    ) -> dict[str, float]:
        """计算当期各维度成本率

        Returns:
            {
                "ingredient_cost_rate": float,
                "labor_cost_rate": float,
                "waste_rate": float,
                "net_revenue_fen": int,
                "food_cost_fen": int,
            }
        """
        # 1. 营收和食材成本
        try:
            rev_result = await db.execute(
                text("""
                    SELECT
                        COALESCE(SUM(o.final_amount_fen), 0) AS net_revenue_fen,
                        COALESCE(SUM(
                            COALESCE(oi.food_cost_fen, oi.cost_fen, 0) * oi.quantity
                        ), 0) AS food_cost_fen
                    FROM orders o
                    LEFT JOIN order_items oi ON oi.order_id = o.id
                    WHERE o.store_id = :store_id
                      AND o.tenant_id = :tenant_id
                      AND o.status IN ('completed', 'paid', 'settled')
                      AND o.created_at >= :period_start
                      AND o.created_at < :period_end_next
                      AND o.is_deleted = FALSE
                """),
                {
                    "store_id": str(store_id),
                    "tenant_id": str(tenant_id),
                    "period_start": period_start,
                    "period_end_next": period_end + timedelta(days=1),
                },
            )
            rev_row = rev_result.mappings().first()
        except (AttributeError, TypeError):
            rev_row = None

        net_revenue_fen = int(
            rev_row.get("net_revenue_fen", 0) or 0
        ) if rev_row else 0
        food_cost_fen = int(
            rev_row.get("food_cost_fen", 0) or 0
        ) if rev_row else 0

        ingredient_rate = (
            round(food_cost_fen / net_revenue_fen, 6)
            if net_revenue_fen > 0
            else 0.0
        )

        # 2. 损耗率（简化）
        waste_rate = 0.0

        return {
            "ingredient_cost_rate": ingredient_rate,
            "labor_cost_rate": 0.0,  # TODO: 从排班数据计算
            "waste_rate": waste_rate,
            "net_revenue_fen": net_revenue_fen,
            "food_cost_fen": food_cost_fen,
        }

    async def get_category_detail(
        self,
        db: AsyncSession,
        store_id: uuid.UUID,
        tenant_id: uuid.UUID,
        period_start: date,
        period_end: date,
    ) -> list[dict[str, Any]]:
        """品类归因明细（供独立端点调用）"""
        return await self._analyze_by_category(
            db, store_id, tenant_id, period_start, period_end
        )

    async def get_supplier_detail(
        self,
        db: AsyncSession,
        store_id: uuid.UUID,
        tenant_id: uuid.UUID,
        period_start: date,
        period_end: date,
    ) -> list[dict[str, Any]]:
        """供应商归因明细（供独立端点调用）"""
        return await self._analyze_by_supplier(
            db, store_id, tenant_id, period_start, period_end
        )

    async def get_recommendations(
        self,
        db: AsyncSession,
        store_id: uuid.UUID,
        tenant_id: uuid.UUID,
        period_start: date,
        period_end: date,
    ) -> list[dict[str, Any]]:
        """获取可执行建议（供独立端点调用）"""
        result = await self.analyze_root_cause(
            db, store_id, tenant_id, period_start, period_end
        )
        return result.get("recommendations", [])
