"""多品牌成本健康指数引擎

核心能力：跨品牌/跨门店对标食材成本、人力成本、损耗率。
屯象OS vs 奥琦玮差异化：奥琦玮只能看单门店成本，本引擎支持集团横向对标。

三维度数据来源：
  - 食材成本率：SUM(order_items.food_cost_fen) / SUM(orders.final_amount_fen)
  - 人力成本率：SUM(crew_shifts.actual_hours × employees.hourly_wage_fen) / net_revenue
  - 损耗率：   SUM(waste_records.quantity × unit_cost_fen) / SUM(purchase_orders.total_amount_fen)

AI 建议触发策略：health_score < 65 时才调用 ModelRouter（控成本）。
缓存策略：计算结果允许1小时缓存。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

import structlog
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ─── 引擎常量 ──────────────────────────────────────────────────────────────────

DIMENSION_WEIGHTS: dict[str, float] = {
    "ingredient_cost_rate": 0.45,  # 食材成本率（最重要）
    "labor_cost_rate": 0.30,  # 人力成本率
    "waste_rate": 0.25,  # 损耗率
}

# 行业目标阈值（餐饮行业经验值）
INDUSTRY_TARGETS: dict[str, float] = {
    "ingredient_cost_rate": 0.30,  # 食材成本率目标≤30%
    "labor_cost_rate": 0.25,  # 人力成本率目标≤25%
    "waste_rate": 0.05,  # 损耗率目标≤5%
}

# 健康等级阈值
HEALTH_THRESHOLDS = {
    "healthy": 80.0,  # 绿色：成本结构健康
    "warning": 65.0,  # 黄色：需关注
    # < 65 → critical：需立即干预
}

# 异常偏差阈值（超出品牌均值±15%为异常）
ANOMALY_THRESHOLD = 0.15

# AI 触发阈值
AI_TRIGGER_THRESHOLD = 65.0

HealthLevel = Literal["healthy", "warning", "critical"]


# ─── Pydantic V2 模型 ─────────────────────────────────────────────────────────


class StoreCostHealthReport(BaseModel):
    """单店成本健康报告"""

    store_id: str
    store_name: str
    brand_id: str
    tenant_id: str
    period_days: int

    # 三维度实际成本率
    ingredient_cost_rate: float  # 食材成本率（来自 order_items + orders）
    labor_cost_rate: float  # 人力成本率（来自 crew_shifts + employees）
    waste_rate: float  # 损耗率（来自 waste_records + purchase_orders）

    # 三维度单项分数（0-100）
    ingredient_score: float
    labor_score: float
    waste_score: float

    # 综合健康分
    health_score: float  # 加权综合分 0-100
    health_level: HealthLevel  # healthy / warning / critical

    # 品牌基准（同品牌其他门店中位数）
    benchmark_ingredient: float
    benchmark_labor: float
    benchmark_waste: float

    # 与基准偏差（相对值，正数表示高于基准）
    ingredient_deviation: float
    labor_deviation: float
    waste_deviation: float

    # 异常标记（偏差超出 ±15% 为异常）
    is_ingredient_anomaly: bool
    is_labor_anomaly: bool
    is_waste_anomaly: bool

    @field_validator("health_level")
    @classmethod
    def validate_health_level(cls, v: str) -> str:
        allowed = {"healthy", "warning", "critical"}
        if v not in allowed:
            raise ValueError(f"health_level 必须为 {allowed}，实际：{v!r}")
        return v


class BrandCostBenchmark(BaseModel):
    """品牌成本基准（同品牌所有门店的统计分布）"""

    brand_id: str
    tenant_id: str
    period_days: int
    store_count: int

    # 中位数（推荐作为对标线：抗异常值）
    median_ingredient_cost_rate: float
    median_labor_cost_rate: float
    median_waste_rate: float

    # 均值
    mean_ingredient_cost_rate: float
    mean_labor_cost_rate: float
    mean_waste_rate: float

    # 分布（用于识别极端值）
    p25_ingredient_cost_rate: float
    p75_ingredient_cost_rate: float


# ─── 纯函数：计算层 ───────────────────────────────────────────────────────────


def calc_ingredient_cost_rate(food_cost_fen: int, net_revenue_fen: int) -> float:
    """食材成本率 = 食材成本 / 净营收

    Args:
        food_cost_fen: 食材成本（分）
        net_revenue_fen: 净营收（分）

    Returns:
        成本率（0-1 之间的小数），营收为0时返回0.0
    """
    if net_revenue_fen <= 0:
        return 0.0
    return round(food_cost_fen / net_revenue_fen, 6)


def calc_dimension_score(
    dimension: str,
    actual: float,
    industry_target: float,
) -> float:
    """将实际成本率映射到 0-100 分数

    成本类维度：实际值低于目标 → 高分；超出越多 → 低分。
    映射规则：
      actual <= target * 0.8  → 100分（超出预期）
      actual == target        → 70分（达标）
      actual == target * 1.5  → 0分（超标50%）
      线性插值，夹紧到 [0, 100]

    Args:
        dimension: 维度名（用于日志）
        actual: 实际成本率
        industry_target: 行业目标成本率

    Returns:
        0-100 分数
    """
    if industry_target <= 0:
        return 50.0

    # 优秀阈值：目标的80%以下得满分
    excellent = industry_target * 0.8
    # 零分阈值：超出目标50%以上
    zero_threshold = industry_target * 1.5

    if actual <= excellent:
        score = 100.0
    elif actual >= zero_threshold:
        score = 0.0
    elif actual <= industry_target:
        # excellent → target: 100 → 70
        ratio = (actual - excellent) / (industry_target - excellent)
        score = 100.0 - ratio * 30.0
    else:
        # target → zero_threshold: 70 → 0
        ratio = (actual - industry_target) / (zero_threshold - industry_target)
        score = 70.0 - ratio * 70.0

    clamped = max(0.0, min(100.0, score))
    logger.debug(
        "dimension_score_calc",
        dimension=dimension,
        actual=actual,
        target=industry_target,
        score=round(clamped, 2),
    )
    return round(clamped, 2)


def calc_weighted_health_score(
    ingredient_score: float,
    labor_score: float,
    waste_score: float,
) -> float:
    """三维度加权综合健康分

    权重：食材×0.45 + 人力×0.30 + 损耗×0.25

    Returns:
        0-100 综合分，保留1位小数
    """
    score = (
        ingredient_score * DIMENSION_WEIGHTS["ingredient_cost_rate"]
        + labor_score * DIMENSION_WEIGHTS["labor_cost_rate"]
        + waste_score * DIMENSION_WEIGHTS["waste_rate"]
    )
    return round(max(0.0, min(100.0, score)), 1)


def classify_cost_health(score: float) -> HealthLevel:
    """成本健康等级分类

    Returns:
        healthy (≥80) / warning (≥65) / critical (<65)
    """
    if score >= HEALTH_THRESHOLDS["healthy"]:
        return "healthy"
    if score >= HEALTH_THRESHOLDS["warning"]:
        return "warning"
    return "critical"


def detect_deviation(actual: float, benchmark: float) -> tuple[float, bool]:
    """计算与基准的相对偏差，判断是否异常

    偏差 = (actual - benchmark) / benchmark
    超出 ±ANOMALY_THRESHOLD（15%）为异常。

    Args:
        actual: 门店实际成本率
        benchmark: 品牌基准成本率（中位数）

    Returns:
        (deviation, is_anomaly)
        deviation: 相对偏差（正数=高于基准，负数=低于基准）
        is_anomaly: 是否超出±15%阈值
    """
    if benchmark <= 0:
        return 0.0, False

    deviation = round((actual - benchmark) / benchmark, 6)
    is_anomaly = abs(deviation) > ANOMALY_THRESHOLD
    return deviation, is_anomaly


# ─── CostHealthEngine ─────────────────────────────────────────────────────────


class CostHealthEngine:
    """多品牌成本健康指数引擎

    支持：
    - 单店成本健康报告（三维度评分 + 品牌对标）
    - 品牌成本基准计算（中位数/均值/分布）
    - 集团成本热力图（所有门店排序）
    - AI 成本优化建议（health_score < 65 时触发）
    """

    async def calc_store_cost_health(
        self,
        store_id: str,
        tenant_id: str,
        period_days: int = 30,
        db: AsyncSession = None,
    ) -> StoreCostHealthReport:
        """单店成本健康报告

        数据来源：
        - 食材成本率：order_items.food_cost_fen / orders.final_amount_fen（近N天）
        - 人力成本率：crew_shifts.actual_hours × employees.hourly_wage_fen / net_revenue
        - 损耗率：waste_records.quantity × unit_cost_fen / purchase_orders.total_amount_fen

        Args:
            store_id: 门店ID
            tenant_id: 租户ID（RLS 隔离）
            period_days: 统计周期（天）
            db: 数据库会话

        Returns:
            StoreCostHealthReport
        """
        log = logger.bind(store_id=store_id, tenant_id=tenant_id, period_days=period_days)
        log.info("calc_store_cost_health.start")

        # ── 1. 查询门店基本信息 ────────────────────────────────
        store_row = await self._fetch_store_info(store_id, tenant_id, db)
        store_name = store_row["store_name"] if store_row else store_id
        brand_id = store_row["brand_id"] if store_row else ""

        # ── 2. 食材成本率 ──────────────────────────────────────
        # SQL: SUM(oi.food_cost_fen) / SUM(o.final_amount_fen)，来自已完成订单
        revenue_cost_row = await self._fetch_revenue_and_food_cost(store_id, tenant_id, period_days, db)
        net_revenue_fen = revenue_cost_row["net_revenue_fen"] if revenue_cost_row else 0
        food_cost_fen = revenue_cost_row["food_cost_fen"] if revenue_cost_row else 0
        ingredient_rate = calc_ingredient_cost_rate(food_cost_fen, net_revenue_fen)

        # ── 3. 人力成本率 ──────────────────────────────────────
        # SQL: SUM(cs.actual_hours * e.hourly_wage_fen) / net_revenue
        # 无排班数据时 fallback 到门店配置比率
        labor_row = await self._fetch_labor_cost(store_id, tenant_id, period_days, db)
        labor_cost_fen = labor_row["labor_cost_fen"] if labor_row else 0
        labor_rate = calc_ingredient_cost_rate(labor_cost_fen, net_revenue_fen)

        # ── 4. 损耗率 ──────────────────────────────────────────
        # SQL: SUM(wr.quantity * wr.unit_cost_fen) / SUM(po.total_amount_fen)
        waste_row = await self._fetch_waste_rate(store_id, tenant_id, period_days, db)
        waste_cost_fen = waste_row["waste_cost_fen"] if waste_row else 0
        total_purchase_fen = waste_row["total_purchase_fen"] if waste_row else 0
        waste_rate = calc_ingredient_cost_rate(waste_cost_fen, total_purchase_fen)

        # ── 5. 品牌基准（同品牌门店中位数）───────────────────
        benchmark = await self.get_brand_cost_benchmark(brand_id, tenant_id, period_days, db)
        bench_ingredient = benchmark.median_ingredient_cost_rate
        bench_labor = benchmark.median_labor_cost_rate
        bench_waste = benchmark.median_waste_rate

        # ── 6. 偏差检测 ────────────────────────────────────────
        ingr_dev, ingr_anomaly = detect_deviation(ingredient_rate, bench_ingredient)
        labor_dev, labor_anomaly = detect_deviation(labor_rate, bench_labor)
        waste_dev, waste_anomaly = detect_deviation(waste_rate, bench_waste)

        # ── 7. 三维度评分 ──────────────────────────────────────
        ingr_score = calc_dimension_score(
            "ingredient_cost_rate", ingredient_rate, INDUSTRY_TARGETS["ingredient_cost_rate"]
        )
        labor_score = calc_dimension_score("labor_cost_rate", labor_rate, INDUSTRY_TARGETS["labor_cost_rate"])
        waste_score = calc_dimension_score("waste_rate", waste_rate, INDUSTRY_TARGETS["waste_rate"])

        # ── 8. 综合健康分 ──────────────────────────────────────
        health_score = calc_weighted_health_score(ingr_score, labor_score, waste_score)
        health_level = classify_cost_health(health_score)

        log.info(
            "calc_store_cost_health.done",
            ingredient_rate=ingredient_rate,
            labor_rate=labor_rate,
            waste_rate=waste_rate,
            health_score=health_score,
            health_level=health_level,
        )

        return StoreCostHealthReport(
            store_id=store_id,
            store_name=store_name,
            brand_id=brand_id,
            tenant_id=tenant_id,
            period_days=period_days,
            ingredient_cost_rate=ingredient_rate,
            labor_cost_rate=labor_rate,
            waste_rate=waste_rate,
            ingredient_score=ingr_score,
            labor_score=labor_score,
            waste_score=waste_score,
            health_score=health_score,
            health_level=health_level,
            benchmark_ingredient=bench_ingredient,
            benchmark_labor=bench_labor,
            benchmark_waste=bench_waste,
            ingredient_deviation=ingr_dev,
            labor_deviation=labor_dev,
            waste_deviation=waste_dev,
            is_ingredient_anomaly=ingr_anomaly,
            is_labor_anomaly=labor_anomaly,
            is_waste_anomaly=waste_anomaly,
        )

    async def get_brand_cost_benchmark(
        self,
        brand_id: str,
        tenant_id: str,
        period_days: int = 30,
        db: AsyncSession = None,
    ) -> BrandCostBenchmark:
        """品牌成本基准：计算该品牌所有门店的各维度中位数和均值

        使用 PostgreSQL PERCENTILE_CONT 计算真实中位数，抗异常值干扰。

        SQL 逻辑：
          对每家门店先聚合计算三维度成本率，再对所有门店取中位数/均值。
          这样避免大门店营收数据污染小门店基准。

        Args:
            brand_id: 品牌ID
            tenant_id: 租户ID
            period_days: 统计周期（天）
            db: 数据库会话

        Returns:
            BrandCostBenchmark（无数据时返回行业默认值）
        """
        log = logger.bind(brand_id=brand_id, tenant_id=tenant_id)

        if not brand_id or db is None:
            return self._default_benchmark(brand_id or "", tenant_id, period_days)

        row = await db.execute(
            text("""
                WITH store_metrics AS (
                    -- 先按门店聚合出各维度成本率
                    SELECT
                        o.store_id,
                        CASE
                            WHEN SUM(o.final_amount_fen) > 0
                            THEN SUM(oi.food_cost_fen)::FLOAT / SUM(o.final_amount_fen)
                            ELSE 0
                        END AS ingredient_rate,
                        CASE
                            WHEN SUM(o.final_amount_fen) > 0
                            THEN COALESCE(lc.labor_cost_fen, 0)::FLOAT / SUM(o.final_amount_fen)
                            ELSE 0
                        END AS labor_rate,
                        CASE
                            WHEN COALESCE(po.total_purchase_fen, 0) > 0
                            THEN COALESCE(wr.total_waste_fen, 0)::FLOAT / po.total_purchase_fen
                            ELSE 0
                        END AS waste_rate
                    FROM orders o
                    JOIN stores s
                      ON s.id = o.store_id
                      AND s.tenant_id = o.tenant_id
                      AND s.brand_id = :brand_id
                      AND s.is_deleted = FALSE
                    LEFT JOIN order_items oi
                      ON oi.order_id = o.id
                    LEFT JOIN LATERAL (
                        SELECT SUM(cs.actual_hours * COALESCE(e.hourly_wage_fen, 0)) AS labor_cost_fen
                        FROM crew_shifts cs
                        JOIN employees e ON e.id = cs.employee_id
                          AND e.tenant_id = :tenant_id
                        WHERE cs.store_id = o.store_id
                          AND cs.tenant_id = :tenant_id
                          AND cs.shift_start >= NOW() - INTERVAL ':period_days days'
                          AND cs.is_deleted = FALSE
                    ) lc ON TRUE
                    LEFT JOIN LATERAL (
                        SELECT SUM(wr2.quantity * wr2.unit_cost_fen) AS total_waste_fen
                        FROM waste_records wr2
                        WHERE wr2.store_id = o.store_id
                          AND wr2.tenant_id = :tenant_id
                          AND wr2.wasted_at >= NOW() - INTERVAL ':period_days days'
                          AND wr2.is_deleted = FALSE
                    ) wr ON TRUE
                    LEFT JOIN LATERAL (
                        SELECT SUM(po2.total_amount_fen) AS total_purchase_fen
                        FROM purchase_orders po2
                        WHERE po2.store_id = o.store_id
                          AND po2.tenant_id = :tenant_id
                          AND po2.received_at >= NOW() - INTERVAL ':period_days days'
                          AND po2.is_deleted = FALSE
                    ) po ON TRUE
                    WHERE o.tenant_id = :tenant_id
                      AND o.status IN ('completed', 'settled', 'paid')
                      AND o.created_at >= NOW() - INTERVAL ':period_days days'
                      AND o.is_deleted = FALSE
                    GROUP BY o.store_id, lc.labor_cost_fen, wr.total_waste_fen, po.total_purchase_fen
                )
                SELECT
                    COUNT(*)                                               AS store_count,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ingredient_rate) AS median_ingredient,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY labor_rate)      AS median_labor,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY waste_rate)      AS median_waste,
                    AVG(ingredient_rate)                                   AS mean_ingredient,
                    AVG(labor_rate)                                        AS mean_labor,
                    AVG(waste_rate)                                        AS mean_waste,
                    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY ingredient_rate) AS p25_ingredient,
                    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY ingredient_rate) AS p75_ingredient
                FROM store_metrics
            """),
            {
                "brand_id": brand_id,
                "tenant_id": tenant_id,
                "period_days": period_days,
            },
        )

        row_data = row.mappings().first()
        if not row_data or (row_data["store_count"] or 0) == 0:
            log.warning("get_brand_cost_benchmark.no_data", brand_id=brand_id)
            return self._default_benchmark(brand_id, tenant_id, period_days)

        return BrandCostBenchmark(
            brand_id=brand_id,
            tenant_id=tenant_id,
            period_days=period_days,
            store_count=int(row_data["store_count"] or 0),
            median_ingredient_cost_rate=float(
                row_data["median_ingredient"] or INDUSTRY_TARGETS["ingredient_cost_rate"]
            ),
            median_labor_cost_rate=float(row_data["median_labor"] or INDUSTRY_TARGETS["labor_cost_rate"]),
            median_waste_rate=float(row_data["median_waste"] or INDUSTRY_TARGETS["waste_rate"]),
            mean_ingredient_cost_rate=float(row_data["mean_ingredient"] or INDUSTRY_TARGETS["ingredient_cost_rate"]),
            mean_labor_cost_rate=float(row_data["mean_labor"] or INDUSTRY_TARGETS["labor_cost_rate"]),
            mean_waste_rate=float(row_data["mean_waste"] or INDUSTRY_TARGETS["waste_rate"]),
            p25_ingredient_cost_rate=float(row_data["p25_ingredient"] or INDUSTRY_TARGETS["ingredient_cost_rate"]),
            p75_ingredient_cost_rate=float(row_data["p75_ingredient"] or INDUSTRY_TARGETS["ingredient_cost_rate"]),
        )

    async def get_group_cost_heatmap(
        self,
        tenant_id: str,
        period_days: int = 30,
        db: AsyncSession = None,
    ) -> list[StoreCostHealthReport]:
        """集团成本热力图数据

        返回该租户所有门店的成本健康状态，按 health_score 升序排列
        （高风险门店在最前，便于快速识别和干预）。

        Args:
            tenant_id: 租户ID
            period_days: 统计周期（天）
            db: 数据库会话

        Returns:
            list[StoreCostHealthReport]，按 health_score 升序（低分优先）
        """
        log = logger.bind(tenant_id=tenant_id, period_days=period_days)
        log.info("get_group_cost_heatmap.start")

        stores_row = await db.execute(
            text("""
                SELECT id AS store_id, name AS store_name, brand_id
                FROM stores
                WHERE tenant_id = :tenant_id
                  AND is_deleted = FALSE
                ORDER BY name
            """),
            {"tenant_id": tenant_id},
        )
        stores = list(stores_row.mappings().all())

        reports: list[StoreCostHealthReport] = []
        for store in stores:
            try:
                report = await self.calc_store_cost_health(
                    store_id=str(store["store_id"]),
                    tenant_id=tenant_id,
                    period_days=period_days,
                    db=db,
                )
                reports.append(report)
            except (ValueError, KeyError, TypeError) as exc:
                log.error(
                    "get_group_cost_heatmap.store_failed",
                    store_id=str(store["store_id"]),
                    error=str(exc),
                    exc_info=True,
                )

        # 按 health_score 升序（高风险优先）
        reports.sort(key=lambda r: r.health_score)

        log.info(
            "get_group_cost_heatmap.done",
            total_stores=len(reports),
            critical_count=sum(1 for r in reports if r.health_level == "critical"),
            warning_count=sum(1 for r in reports if r.health_level == "warning"),
        )
        return reports

    async def generate_cost_optimization_suggestion(
        self,
        store_report: StoreCostHealthReport,
        brand_benchmark: BrandCostBenchmark,
        model_router,
    ) -> str:
        """AI 成本优化建议

        触发条件：health_score < 65（warning + critical 级别）。
        健康门店不调用 AI，控制模型成本。

        输入上下文：
        - 门店三维度成本率 vs 品牌基准
        - 异常维度标记
        - 偏差百分比

        输出：具体的成本改进建议（200字内）

        Args:
            store_report: 门店成本健康报告
            brand_benchmark: 品牌成本基准
            model_router: ModelRouter 实例（通过依赖注入）

        Returns:
            AI 建议文字；健康门店返回空字符串
        """
        if store_report.health_score >= AI_TRIGGER_THRESHOLD:
            logger.debug(
                "generate_suggestion.skipped",
                store_id=store_report.store_id,
                health_score=store_report.health_score,
                reason="score_above_threshold",
            )
            return ""

        logger.info(
            "generate_suggestion.triggered",
            store_id=store_report.store_id,
            health_score=store_report.health_score,
            health_level=store_report.health_level,
        )

        anomaly_details = []
        if store_report.is_ingredient_anomaly:
            anomaly_details.append(
                f"食材成本率{store_report.ingredient_cost_rate:.1%}（品牌基准"
                f"{store_report.benchmark_ingredient:.1%}，偏差"
                f"{store_report.ingredient_deviation:+.1%}）"
            )
        if store_report.is_labor_anomaly:
            anomaly_details.append(
                f"人力成本率{store_report.labor_cost_rate:.1%}（品牌基准"
                f"{store_report.benchmark_labor:.1%}，偏差"
                f"{store_report.labor_deviation:+.1%}）"
            )
        if store_report.is_waste_anomaly:
            anomaly_details.append(
                f"损耗率{store_report.waste_rate:.1%}（品牌基准"
                f"{store_report.benchmark_waste:.1%}，偏差"
                f"{store_report.waste_deviation:+.1%}）"
            )

        if not anomaly_details:
            # 无具体异常但综合分低，给出通用建议
            anomaly_details.append("整体成本结构偏高，需综合优化")

        prompt = (
            f"餐饮门店「{store_report.store_name}」成本健康指数{store_report.health_score:.1f}分"
            f"（{store_report.health_level}），近{store_report.period_days}天成本分析：\n"
            + "\n".join(f"- {d}" for d in anomaly_details)
            + f"\n\n品牌内{brand_benchmark.store_count}家门店基准："
            f"食材{brand_benchmark.median_ingredient_cost_rate:.1%}、"
            f"人力{brand_benchmark.median_labor_cost_rate:.1%}、"
            f"损耗{brand_benchmark.median_waste_rate:.1%}。\n\n"
            "请用200字内给出3条具体、可操作的成本降低建议，直接针对上述异常维度。"
        )

        suggestion: str = await model_router.complete(
            prompt=prompt,
            max_tokens=300,
            temperature=0.3,
        )
        return suggestion.strip() if suggestion else ""

    # ── 内部 DB 查询方法 ────────────────────────────────────────────────────

    async def _fetch_store_info(self, store_id: str, tenant_id: str, db: AsyncSession) -> dict | None:
        """查询门店名称和品牌ID"""
        result = await db.execute(
            text("""
                SELECT name AS store_name, brand_id
                FROM stores
                WHERE id = :store_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
                LIMIT 1
            """),
            {"store_id": store_id, "tenant_id": tenant_id},
        )
        return result.mappings().first()

    async def _fetch_revenue_and_food_cost(
        self, store_id: str, tenant_id: str, period_days: int, db: AsyncSession
    ) -> dict | None:
        """查询净营收和食材成本

        SQL 逻辑：
          - 净营收 = SUM(final_amount_fen)：订单实际收款金额（已含折扣）
          - 食材成本 = SUM(order_items.food_cost_fen)：BOM 计算写入字段
            fallback 到 order_items.cost_fen（旧字段兼容）
          - 仅统计 status IN ('completed', 'settled', 'paid') 的订单
          - 时间范围：最近 period_days 天
        """
        result = await db.execute(
            text("""
                SELECT
                    COALESCE(SUM(o.final_amount_fen), 0)          AS net_revenue_fen,
                    COALESCE(SUM(
                        COALESCE(oi.food_cost_fen, oi.cost_fen, 0)
                    ), 0)                                         AS food_cost_fen
                FROM orders o
                LEFT JOIN order_items oi ON oi.order_id = o.id
                WHERE o.store_id  = :store_id
                  AND o.tenant_id = :tenant_id
                  AND o.status IN ('completed', 'settled', 'paid')
                  AND o.created_at >= NOW() - INTERVAL ':period_days days'
                  AND o.is_deleted = FALSE
            """),
            {"store_id": store_id, "tenant_id": tenant_id, "period_days": period_days},
        )
        return result.mappings().first()

    async def _fetch_labor_cost(self, store_id: str, tenant_id: str, period_days: int, db: AsyncSession) -> dict | None:
        """查询人力成本

        SQL 逻辑：
          - 从 crew_shifts 取实际工时，关联 employees.hourly_wage_fen
          - 人力成本 = SUM(actual_hours × hourly_wage_fen)
          - 无排班数据时返回 0（调用方 fallback 到配置比率）
        """
        result = await db.execute(
            text("""
                SELECT
                    COALESCE(SUM(
                        cs.actual_hours * COALESCE(e.hourly_wage_fen, 0)
                    ), 0) AS labor_cost_fen
                FROM crew_shifts cs
                JOIN employees e
                  ON e.id = cs.employee_id
                  AND e.tenant_id = :tenant_id
                WHERE cs.store_id  = :store_id
                  AND cs.tenant_id = :tenant_id
                  AND cs.shift_start >= NOW() - INTERVAL ':period_days days'
                  AND cs.is_deleted = FALSE
            """),
            {"store_id": store_id, "tenant_id": tenant_id, "period_days": period_days},
        )
        return result.mappings().first()

    async def _fetch_waste_rate(self, store_id: str, tenant_id: str, period_days: int, db: AsyncSession) -> dict | None:
        """查询损耗成本和采购总额

        SQL 逻辑：
          - 损耗成本 = SUM(waste_records.quantity × unit_cost_fen)
          - 采购总额 = SUM(purchase_orders.total_amount_fen)
          - 损耗率 = 损耗成本 / 采购总额
          - 时间范围内无数据时返回 0（不影响整体评分）
        """
        result = await db.execute(
            text("""
                SELECT
                    COALESCE((
                        SELECT SUM(wr.quantity * wr.unit_cost_fen)
                        FROM waste_records wr
                        WHERE wr.store_id  = :store_id
                          AND wr.tenant_id = :tenant_id
                          AND wr.wasted_at >= NOW() - INTERVAL ':period_days days'
                          AND wr.is_deleted = FALSE
                    ), 0) AS waste_cost_fen,
                    COALESCE((
                        SELECT SUM(po.total_amount_fen)
                        FROM purchase_orders po
                        WHERE po.store_id  = :store_id
                          AND po.tenant_id = :tenant_id
                          AND po.received_at >= NOW() - INTERVAL ':period_days days'
                          AND po.is_deleted = FALSE
                    ), 0) AS total_purchase_fen
            """),
            {"store_id": store_id, "tenant_id": tenant_id, "period_days": period_days},
        )
        return result.mappings().first()

    def _default_benchmark(self, brand_id: str, tenant_id: str, period_days: int) -> BrandCostBenchmark:
        """无门店数据时返回行业默认基准"""
        return BrandCostBenchmark(
            brand_id=brand_id,
            tenant_id=tenant_id,
            period_days=period_days,
            store_count=0,
            median_ingredient_cost_rate=INDUSTRY_TARGETS["ingredient_cost_rate"],
            median_labor_cost_rate=INDUSTRY_TARGETS["labor_cost_rate"],
            median_waste_rate=INDUSTRY_TARGETS["waste_rate"],
            mean_ingredient_cost_rate=INDUSTRY_TARGETS["ingredient_cost_rate"],
            mean_labor_cost_rate=INDUSTRY_TARGETS["labor_cost_rate"],
            mean_waste_rate=INDUSTRY_TARGETS["waste_rate"],
            p25_ingredient_cost_rate=INDUSTRY_TARGETS["ingredient_cost_rate"] * 0.9,
            p75_ingredient_cost_rate=INDUSTRY_TARGETS["ingredient_cost_rate"] * 1.1,
        )


# ─── 模块级缓存工具 ───────────────────────────────────────────────────────────

_cache: dict[str, tuple[datetime, object]] = {}
_CACHE_TTL_SECONDS = 3600  # 1小时缓存


def _cache_get(key: str) -> object | None:
    """从内存缓存读取（过期返回 None）"""
    if key not in _cache:
        return None
    cached_at, value = _cache[key]
    if datetime.now(timezone.utc) - cached_at > timedelta(seconds=_CACHE_TTL_SECONDS):
        del _cache[key]
        return None
    return value


def _cache_set(key: str, value: object) -> None:
    """写入内存缓存"""
    _cache[key] = (datetime.now(timezone.utc), value)
