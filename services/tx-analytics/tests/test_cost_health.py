"""成本健康指数引擎测试 — 多品牌跨门店对标

覆盖：
- 食材成本率计算（成本/营业额 × 100%）
- 跨门店偏差检测（超出品牌均值 ±15% 为异常）
- 成本健康指数合并计算（食材+人力+损耗三维度加权）
- 异常门店识别
- AI 改进建议 mock
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.cost_health_engine import (
    CostHealthEngine,
    StoreCostHealthReport,
    BrandCostBenchmark,
    calc_ingredient_cost_rate,
    calc_dimension_score,
    calc_weighted_health_score,
    classify_cost_health,
    detect_deviation,
)

# ─── 纯函数测试 ───────────────────────────────────────────────────────────────


class TestCalcIngredientCostRate:
    """食材成本率计算：cost / revenue × 100%"""

    def test_normal_case(self):
        """食材成本3万，营收10万 → 30%"""
        rate = calc_ingredient_cost_rate(food_cost_fen=3_000_000, net_revenue_fen=10_000_000)
        assert rate == pytest.approx(0.30, abs=1e-4)

    def test_zero_revenue_returns_zero(self):
        """营收为0时不除零，返回0"""
        rate = calc_ingredient_cost_rate(food_cost_fen=500_000, net_revenue_fen=0)
        assert rate == 0.0

    def test_high_cost_rate(self):
        """食材成本5万，营收8万 → 62.5%（超标但可计算）"""
        rate = calc_ingredient_cost_rate(food_cost_fen=5_000_000, net_revenue_fen=8_000_000)
        assert rate == pytest.approx(0.625, abs=1e-4)

    def test_zero_cost(self):
        """食材成本0 → 0%"""
        rate = calc_ingredient_cost_rate(food_cost_fen=0, net_revenue_fen=10_000_000)
        assert rate == 0.0


class TestCalcDimensionScore:
    """单维度分数：基于行业基准阈值映射到 0-100"""

    def test_ingredient_excellent(self):
        """食材成本率25% → 接近满分"""
        score = calc_dimension_score("ingredient_cost_rate", actual=0.25, industry_target=0.30)
        assert score >= 90.0

    def test_ingredient_at_target(self):
        """食材成本率等于目标值 → 中等分（约70-80）"""
        score = calc_dimension_score("ingredient_cost_rate", actual=0.30, industry_target=0.30)
        assert 65.0 <= score <= 85.0

    def test_ingredient_over_target(self):
        """食材成本率超目标50% → 低分"""
        score = calc_dimension_score("ingredient_cost_rate", actual=0.45, industry_target=0.30)
        assert score < 50.0

    def test_waste_excellent(self):
        """损耗率2% → 高分"""
        score = calc_dimension_score("waste_rate", actual=0.02, industry_target=0.05)
        assert score >= 85.0

    def test_score_clamp_0_100(self):
        """分数必须在 [0, 100]"""
        score_low = calc_dimension_score("labor_cost_rate", actual=0.80, industry_target=0.30)
        score_high = calc_dimension_score("labor_cost_rate", actual=0.10, industry_target=0.30)
        assert 0.0 <= score_low <= 100.0
        assert 0.0 <= score_high <= 100.0


class TestCalcWeightedHealthScore:
    """三维度加权合并：食材×0.45 + 人力×0.30 + 损耗×0.25"""

    def test_all_excellent(self):
        """三维度均高分 → 综合分高"""
        score = calc_weighted_health_score(
            ingredient_score=95.0,
            labor_score=90.0,
            waste_score=88.0,
        )
        assert score >= 90.0

    def test_all_critical(self):
        """三维度均低分 → 综合分低"""
        score = calc_weighted_health_score(
            ingredient_score=20.0,
            labor_score=30.0,
            waste_score=25.0,
        )
        assert score < 30.0

    def test_weights_sum_to_one(self):
        """验证权重：三维度各100分 → 综合100分"""
        score = calc_weighted_health_score(100.0, 100.0, 100.0)
        assert score == pytest.approx(100.0, abs=0.1)

    def test_ingredient_weight_dominates(self):
        """食材权重最高（0.45）：食材差时综合分拉低更多"""
        score_ingredient_bad = calc_weighted_health_score(
            ingredient_score=20.0, labor_score=100.0, waste_score=100.0
        )
        score_labor_bad = calc_weighted_health_score(
            ingredient_score=100.0, labor_score=20.0, waste_score=100.0
        )
        # 食材差 → 综合分更低
        assert score_ingredient_bad < score_labor_bad

    def test_result_range_0_100(self):
        score = calc_weighted_health_score(50.0, 50.0, 50.0)
        assert 0.0 <= score <= 100.0


class TestClassifyCostHealth:
    """健康等级分类"""

    def test_healthy_threshold(self):
        assert classify_cost_health(80.0) == "healthy"
        assert classify_cost_health(100.0) == "healthy"

    def test_warning_threshold(self):
        assert classify_cost_health(65.0) == "warning"
        assert classify_cost_health(79.9) == "warning"

    def test_critical_threshold(self):
        assert classify_cost_health(0.0) == "critical"
        assert classify_cost_health(64.9) == "critical"


class TestDetectDeviation:
    """跨门店偏差检测：超出品牌均值 ±15% 为异常"""

    def test_normal_deviation(self):
        """偏差在 ±15% 以内 → is_anomaly=False"""
        deviation, is_anomaly = detect_deviation(actual=0.30, benchmark=0.28)
        assert abs(deviation) < 0.15
        assert is_anomaly is False

    def test_positive_anomaly(self):
        """成本率超出基准15%+ → 异常"""
        deviation, is_anomaly = detect_deviation(actual=0.40, benchmark=0.25)
        # 偏差 = (0.40 - 0.25) / 0.25 = 60% > 15%
        assert deviation > 0.15
        assert is_anomaly is True

    def test_negative_anomaly(self):
        """成本率低于基准15%+ → 也标记异常（可能数据问题）"""
        deviation, is_anomaly = detect_deviation(actual=0.10, benchmark=0.30)
        # 偏差 = (0.10 - 0.30) / 0.30 = -66.7%
        assert deviation < -0.15
        assert is_anomaly is True

    def test_boundary_exactly_15pct(self):
        """恰好15%边界 → 正好不触发异常"""
        deviation, is_anomaly = detect_deviation(actual=0.345, benchmark=0.30)
        # 偏差 = 15% 时 is_anomaly=False（不含等号）
        assert deviation == pytest.approx(0.15, abs=1e-4)
        assert is_anomaly is False

    def test_zero_benchmark_no_crash(self):
        """基准为0时不崩溃"""
        deviation, is_anomaly = detect_deviation(actual=0.30, benchmark=0.0)
        assert isinstance(deviation, float)
        assert isinstance(is_anomaly, bool)


# ─── StoreCostHealthReport / BrandCostBenchmark 模型测试 ─────────────────────


class TestStoreCostHealthReport:
    """Pydantic V2 模型校验"""

    def test_create_healthy_report(self):
        report = StoreCostHealthReport(
            store_id="store-001",
            store_name="总店",
            brand_id="brand-001",
            tenant_id="tenant-001",
            period_days=30,
            ingredient_cost_rate=0.28,
            labor_cost_rate=0.22,
            waste_rate=0.03,
            ingredient_score=90.0,
            labor_score=85.0,
            waste_score=88.0,
            health_score=88.0,
            health_level="healthy",
            benchmark_ingredient=0.30,
            benchmark_labor=0.25,
            benchmark_waste=0.05,
            ingredient_deviation=0.0,
            labor_deviation=0.0,
            waste_deviation=0.0,
            is_ingredient_anomaly=False,
            is_labor_anomaly=False,
            is_waste_anomaly=False,
        )
        assert report.store_id == "store-001"
        assert report.health_level == "healthy"

    def test_invalid_health_level_raises(self):
        with pytest.raises(ValueError):
            StoreCostHealthReport(
                store_id="s1", store_name="X", brand_id="b1", tenant_id="t1",
                period_days=30,
                ingredient_cost_rate=0.3, labor_cost_rate=0.2, waste_rate=0.05,
                ingredient_score=70.0, labor_score=70.0, waste_score=70.0,
                health_score=70.0,
                health_level="unknown_level",  # 非法值
                benchmark_ingredient=0.3, benchmark_labor=0.25, benchmark_waste=0.05,
                ingredient_deviation=0.0, labor_deviation=0.0, waste_deviation=0.0,
                is_ingredient_anomaly=False, is_labor_anomaly=False, is_waste_anomaly=False,
            )


class TestBrandCostBenchmark:
    """品牌基准模型校验"""

    def test_create_benchmark(self):
        benchmark = BrandCostBenchmark(
            brand_id="brand-001",
            tenant_id="tenant-001",
            period_days=30,
            store_count=5,
            median_ingredient_cost_rate=0.30,
            median_labor_cost_rate=0.25,
            median_waste_rate=0.05,
            mean_ingredient_cost_rate=0.31,
            mean_labor_cost_rate=0.26,
            mean_waste_rate=0.05,
            p25_ingredient_cost_rate=0.27,
            p75_ingredient_cost_rate=0.34,
        )
        assert benchmark.store_count == 5
        assert benchmark.median_ingredient_cost_rate == pytest.approx(0.30, abs=1e-4)


# ─── CostHealthEngine 集成测试（mock DB）────────────────────────────────────


@pytest.fixture
def engine():
    return CostHealthEngine()


@pytest.fixture
def mock_db():
    db = AsyncMock()
    return db


def _make_row(**kwargs):
    """创建 mock DB 行，支持属性访问和 mappings().first()"""
    row = MagicMock()
    for k, v in kwargs.items():
        setattr(row, k, v)
    # 支持 row[key] 访问
    row.__getitem__ = lambda self, key: kwargs[key]
    return row


class TestCalcStoreCostHealth:
    """单店成本健康报告（mock DB）"""

    @pytest.mark.asyncio
    async def test_healthy_store(self, engine, mock_db):
        """食材成本率28%、人力22%、损耗3% → 应为 healthy"""
        revenue_fen = 10_000_000  # 10万
        food_cost_fen = 2_800_000  # 28%
        labor_cost_fen = 2_200_000  # 22%
        waste_cost_fen = 300_000    # 3%

        # mock SQL 查询
        mock_db.execute = AsyncMock(side_effect=[
            # 1. 营收 + 食材成本
            MagicMock(mappings=lambda: MagicMock(first=lambda: {
                "net_revenue_fen": revenue_fen,
                "food_cost_fen": food_cost_fen,
            })),
            # 2. 人力成本
            MagicMock(mappings=lambda: MagicMock(first=lambda: {
                "labor_cost_fen": labor_cost_fen,
            })),
            # 3. 损耗成本
            MagicMock(mappings=lambda: MagicMock(first=lambda: {
                "waste_cost_fen": waste_cost_fen,
                "total_purchase_fen": 10_000_000,
            })),
            # 4. 品牌基准（同品牌门店聚合）
            MagicMock(mappings=lambda: MagicMock(first=lambda: {
                "median_ingredient": 0.30,
                "median_labor": 0.25,
                "median_waste": 0.05,
                "mean_ingredient": 0.30,
                "mean_labor": 0.25,
                "mean_waste": 0.05,
                "p25_ingredient": 0.27,
                "p75_ingredient": 0.33,
                "store_count": 4,
            })),
            # 5. 门店信息（store_name、brand_id）
            MagicMock(mappings=lambda: MagicMock(first=lambda: {
                "store_name": "测试门店",
                "brand_id": "brand-001",
            })),
        ])

        report = await engine.calc_store_cost_health(
            store_id="store-001",
            tenant_id="tenant-001",
            period_days=30,
            db=mock_db,
        )

        assert report.health_level == "healthy"
        assert report.health_score >= 80.0
        assert report.ingredient_cost_rate == pytest.approx(0.28, abs=1e-4)
        assert report.is_ingredient_anomaly is False

    @pytest.mark.asyncio
    async def test_critical_store(self, engine, mock_db):
        """食材成本率55%、人力40%、损耗15% → 应为 critical"""
        revenue_fen = 10_000_000
        food_cost_fen = 5_500_000   # 55%
        labor_cost_fen = 4_000_000  # 40%
        waste_cost_fen = 1_500_000  # 15%

        mock_db.execute = AsyncMock(side_effect=[
            MagicMock(mappings=lambda: MagicMock(first=lambda: {
                "net_revenue_fen": revenue_fen,
                "food_cost_fen": food_cost_fen,
            })),
            MagicMock(mappings=lambda: MagicMock(first=lambda: {
                "labor_cost_fen": labor_cost_fen,
            })),
            MagicMock(mappings=lambda: MagicMock(first=lambda: {
                "waste_cost_fen": waste_cost_fen,
                "total_purchase_fen": 10_000_000,
            })),
            MagicMock(mappings=lambda: MagicMock(first=lambda: {
                "median_ingredient": 0.30,
                "median_labor": 0.25,
                "median_waste": 0.05,
                "mean_ingredient": 0.30,
                "mean_labor": 0.25,
                "mean_waste": 0.05,
                "p25_ingredient": 0.27,
                "p75_ingredient": 0.33,
                "store_count": 4,
            })),
            MagicMock(mappings=lambda: MagicMock(first=lambda: {
                "store_name": "问题门店",
                "brand_id": "brand-001",
            })),
        ])

        report = await engine.calc_store_cost_health(
            store_id="store-002",
            tenant_id="tenant-001",
            period_days=30,
            db=mock_db,
        )

        assert report.health_level == "critical"
        assert report.health_score < 65.0
        # 食材成本率55%，基准30%，偏差 > 15%
        assert report.is_ingredient_anomaly is True


class TestGetBrandCostBenchmark:
    """品牌成本基准计算（mock DB）"""

    @pytest.mark.asyncio
    async def test_brand_benchmark(self, engine, mock_db):
        """品牌5家门店聚合基准"""
        mock_db.execute = AsyncMock(return_value=MagicMock(
            mappings=lambda: MagicMock(first=lambda: {
                "store_count": 5,
                "median_ingredient": 0.29,
                "median_labor": 0.24,
                "median_waste": 0.04,
                "mean_ingredient": 0.295,
                "mean_labor": 0.245,
                "mean_waste": 0.042,
                "p25_ingredient": 0.26,
                "p75_ingredient": 0.32,
            })
        ))

        benchmark = await engine.get_brand_cost_benchmark(
            brand_id="brand-001",
            tenant_id="tenant-001",
            period_days=30,
            db=mock_db,
        )

        assert benchmark.store_count == 5
        assert benchmark.median_ingredient_cost_rate == pytest.approx(0.29, abs=1e-4)
        assert benchmark.brand_id == "brand-001"

    @pytest.mark.asyncio
    async def test_brand_no_data_returns_defaults(self, engine, mock_db):
        """无门店数据时返回行业默认基准"""
        mock_db.execute = AsyncMock(return_value=MagicMock(
            mappings=lambda: MagicMock(first=lambda: None)  # 无数据
        ))

        benchmark = await engine.get_brand_cost_benchmark(
            brand_id="brand-empty",
            tenant_id="tenant-001",
            period_days=30,
            db=mock_db,
        )

        # 应返回行业默认值而非崩溃
        assert benchmark.store_count == 0
        assert benchmark.median_ingredient_cost_rate == pytest.approx(0.30, abs=1e-4)


class TestGetGroupCostHeatmap:
    """集团热力图：所有门店排序（mock DB）"""

    @pytest.mark.asyncio
    async def test_heatmap_sorted_by_score(self, engine, mock_db):
        """热力图按 health_score 升序（高风险门店优先）"""
        # 模拟两家门店
        store_list_row = MagicMock()
        store_list_row.mappings = lambda: MagicMock(all=lambda: [
            {"store_id": "s1", "store_name": "门店A", "brand_id": "b1"},
            {"store_id": "s2", "store_name": "门店B", "brand_id": "b1"},
        ])

        with patch.object(engine, "calc_store_cost_health", new_callable=AsyncMock) as mock_calc:
            mock_calc.side_effect = [
                StoreCostHealthReport(
                    store_id="s1", store_name="门店A", brand_id="b1", tenant_id="t1",
                    period_days=30, ingredient_cost_rate=0.28, labor_cost_rate=0.22,
                    waste_rate=0.03, ingredient_score=90.0, labor_score=85.0, waste_score=88.0,
                    health_score=88.0, health_level="healthy",
                    benchmark_ingredient=0.30, benchmark_labor=0.25, benchmark_waste=0.05,
                    ingredient_deviation=0.0, labor_deviation=0.0, waste_deviation=0.0,
                    is_ingredient_anomaly=False, is_labor_anomaly=False, is_waste_anomaly=False,
                ),
                StoreCostHealthReport(
                    store_id="s2", store_name="门店B", brand_id="b1", tenant_id="t1",
                    period_days=30, ingredient_cost_rate=0.48, labor_cost_rate=0.38,
                    waste_rate=0.12, ingredient_score=30.0, labor_score=25.0, waste_score=20.0,
                    health_score=26.0, health_level="critical",
                    benchmark_ingredient=0.30, benchmark_labor=0.25, benchmark_waste=0.05,
                    ingredient_deviation=0.60, labor_deviation=0.52, waste_deviation=1.40,
                    is_ingredient_anomaly=True, is_labor_anomaly=True, is_waste_anomaly=True,
                ),
            ]
            mock_db.execute = AsyncMock(return_value=store_list_row)

            reports = await engine.get_group_cost_heatmap(
                tenant_id="tenant-001",
                period_days=30,
                db=mock_db,
            )

        assert len(reports) == 2
        # 高风险（低分）门店排在前面
        assert reports[0].health_score < reports[1].health_score
        assert reports[0].store_id == "s2"

    @pytest.mark.asyncio
    async def test_heatmap_identifies_critical_stores(self, engine, mock_db):
        """集团热力图能正确识别 critical 门店"""
        with patch.object(engine, "calc_store_cost_health", new_callable=AsyncMock) as mock_calc:
            mock_calc.return_value = StoreCostHealthReport(
                store_id="s3", store_name="高风险店", brand_id="b1", tenant_id="t1",
                period_days=30, ingredient_cost_rate=0.50, labor_cost_rate=0.35,
                waste_rate=0.10, ingredient_score=10.0, labor_score=20.0, waste_score=15.0,
                health_score=14.75, health_level="critical",
                benchmark_ingredient=0.30, benchmark_labor=0.25, benchmark_waste=0.05,
                ingredient_deviation=0.67, labor_deviation=0.40, waste_deviation=1.0,
                is_ingredient_anomaly=True, is_labor_anomaly=True, is_waste_anomaly=True,
            )
            mock_db.execute = AsyncMock(return_value=MagicMock(
                mappings=lambda: MagicMock(all=lambda: [
                    {"store_id": "s3", "store_name": "高风险店", "brand_id": "b1"},
                ])
            ))

            reports = await engine.get_group_cost_heatmap("tenant-001", 30, mock_db)

        critical_stores = [r for r in reports if r.health_level == "critical"]
        assert len(critical_stores) == 1
        assert critical_stores[0].store_id == "s3"


class TestGenerateCostOptimizationSuggestion:
    """AI 优化建议：仅在 health_score < 65 时触发"""

    @pytest.mark.asyncio
    async def test_ai_triggered_when_critical(self):
        """health_score=45 → 触发 AI，返回建议文字"""
        engine = CostHealthEngine()

        critical_report = StoreCostHealthReport(
            store_id="s1", store_name="问题店", brand_id="b1", tenant_id="t1",
            period_days=30, ingredient_cost_rate=0.48, labor_cost_rate=0.35,
            waste_rate=0.10, ingredient_score=30.0, labor_score=40.0, waste_score=35.0,
            health_score=34.0, health_level="critical",
            benchmark_ingredient=0.30, benchmark_labor=0.25, benchmark_waste=0.05,
            ingredient_deviation=0.60, labor_deviation=0.40, waste_deviation=1.0,
            is_ingredient_anomaly=True, is_labor_anomaly=True, is_waste_anomaly=True,
        )

        benchmark = BrandCostBenchmark(
            brand_id="b1", tenant_id="t1", period_days=30, store_count=4,
            median_ingredient_cost_rate=0.30, median_labor_cost_rate=0.25,
            median_waste_rate=0.05, mean_ingredient_cost_rate=0.30,
            mean_labor_cost_rate=0.25, mean_waste_rate=0.05,
            p25_ingredient_cost_rate=0.27, p75_ingredient_cost_rate=0.33,
        )

        mock_router = AsyncMock()
        mock_router.complete = AsyncMock(return_value="建议：1. 优化食材采购合同降低单价；2. 减少高损耗食材用量；3. 优化排班减少人力浪费。")

        suggestion = await engine.generate_cost_optimization_suggestion(
            store_report=critical_report,
            brand_benchmark=benchmark,
            model_router=mock_router,
        )

        mock_router.complete.assert_called_once()
        assert isinstance(suggestion, str)
        assert len(suggestion) > 0

    @pytest.mark.asyncio
    async def test_ai_not_triggered_when_healthy(self):
        """health_score=88 → 不触发 AI，直接返回空字符串"""
        engine = CostHealthEngine()

        healthy_report = StoreCostHealthReport(
            store_id="s2", store_name="优质店", brand_id="b1", tenant_id="t1",
            period_days=30, ingredient_cost_rate=0.27, labor_cost_rate=0.20,
            waste_rate=0.03, ingredient_score=95.0, labor_score=90.0, waste_score=92.0,
            health_score=92.25, health_level="healthy",
            benchmark_ingredient=0.30, benchmark_labor=0.25, benchmark_waste=0.05,
            ingredient_deviation=-0.10, labor_deviation=-0.20, waste_deviation=-0.40,
            is_ingredient_anomaly=False, is_labor_anomaly=False, is_waste_anomaly=False,
        )

        benchmark = BrandCostBenchmark(
            brand_id="b1", tenant_id="t1", period_days=30, store_count=4,
            median_ingredient_cost_rate=0.30, median_labor_cost_rate=0.25,
            median_waste_rate=0.05, mean_ingredient_cost_rate=0.30,
            mean_labor_cost_rate=0.25, mean_waste_rate=0.05,
            p25_ingredient_cost_rate=0.27, p75_ingredient_cost_rate=0.33,
        )

        mock_router = AsyncMock()

        suggestion = await engine.generate_cost_optimization_suggestion(
            store_report=healthy_report,
            brand_benchmark=benchmark,
            model_router=mock_router,
        )

        # 健康门店不调 AI
        mock_router.complete.assert_not_called()
        assert suggestion == ""

    @pytest.mark.asyncio
    async def test_ai_triggered_at_warning_boundary(self):
        """health_score=64（刚好 < 65）→ 触发 AI"""
        engine = CostHealthEngine()

        warning_report = StoreCostHealthReport(
            store_id="s3", store_name="边界店", brand_id="b1", tenant_id="t1",
            period_days=30, ingredient_cost_rate=0.35, labor_cost_rate=0.28,
            waste_rate=0.07, ingredient_score=60.0, labor_score=65.0, waste_score=70.0,
            health_score=64.0, health_level="critical",
            benchmark_ingredient=0.30, benchmark_labor=0.25, benchmark_waste=0.05,
            ingredient_deviation=0.167, labor_deviation=0.12, waste_deviation=0.40,
            is_ingredient_anomaly=True, is_labor_anomaly=False, is_waste_anomaly=False,
        )

        benchmark = BrandCostBenchmark(
            brand_id="b1", tenant_id="t1", period_days=30, store_count=4,
            median_ingredient_cost_rate=0.30, median_labor_cost_rate=0.25,
            median_waste_rate=0.05, mean_ingredient_cost_rate=0.30,
            mean_labor_cost_rate=0.25, mean_waste_rate=0.05,
            p25_ingredient_cost_rate=0.27, p75_ingredient_cost_rate=0.33,
        )

        mock_router = AsyncMock()
        mock_router.complete = AsyncMock(return_value="食材成本偏高，建议审查采购渠道。")

        suggestion = await engine.generate_cost_optimization_suggestion(
            store_report=warning_report,
            brand_benchmark=benchmark,
            model_router=mock_router,
        )

        mock_router.complete.assert_called_once()
        assert len(suggestion) > 0
