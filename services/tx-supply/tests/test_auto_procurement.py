"""自动采购推荐 Agent — 单元测试

测试范围：
1. 基于近7天销量计算日均消耗量
2. 安全库存 = 日均消耗 × (采购周期+安全天数)
3. 建议采购量 = 安全库存 - 当前库存（≤0时不建议采购）
4. 供应商选择：同原料多供应商时选准期率最高的
5. 紧急采购预警：库存低于3天用量时标记urgent
6. 生成采购建议单（不自动提交，需人工确认）
7. tenant_id隔离
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import pytest

from services.demand_forecast import DemandForecastService
from services.auto_procurement import AutoProcurementService, ProcurementRecommendation


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. 日均消耗量计算
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestDailyConsumption:
    @pytest.mark.asyncio
    async def test_daily_consumption_from_history(self):
        """有历史出库数据时，正确计算日均消耗"""
        svc = DemandForecastService()
        # 注入: 近7天共出库70kg
        result = await svc.get_daily_consumption(
            ingredient_id="ing_001",
            store_id="store_001",
            days=7,
            tenant_id="tenant_001",
            db=None,
            _mock_total_usage=70.0,
        )
        assert result == pytest.approx(10.0)  # 70 / 7 = 10

    @pytest.mark.asyncio
    async def test_daily_consumption_zero_history(self):
        """无历史数据时，返回0（不报错，由BOM反推兜底）"""
        svc = DemandForecastService()
        result = await svc.get_daily_consumption(
            ingredient_id="ing_999",
            store_id="store_001",
            days=7,
            tenant_id="tenant_001",
            db=None,
            _mock_total_usage=0.0,
        )
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_daily_consumption_partial_days(self):
        """3天数据按3天平均，不按7天"""
        svc = DemandForecastService()
        result = await svc.get_daily_consumption(
            ingredient_id="ing_001",
            store_id="store_001",
            days=3,
            tenant_id="tenant_001",
            db=None,
            _mock_total_usage=30.0,
        )
        assert result == pytest.approx(10.0)

    @pytest.mark.asyncio
    async def test_bom_fallback_when_no_history(self):
        """历史不足时，用BOM反向推算估算消耗"""
        svc = DemandForecastService()
        # 模拟: 近7天订单300份，BOM用量0.05kg/份
        result = await svc.get_daily_consumption(
            ingredient_id="ing_bom",
            store_id="store_001",
            days=7,
            tenant_id="tenant_001",
            db=None,
            _mock_total_usage=0.0,          # 无直接出库记录
            _mock_bom_daily=2.14,           # BOM反推: 300/7 * 0.05
        )
        assert result == pytest.approx(2.14)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. 安全库存计算
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestSafetyStock:
    def test_safety_stock_formula(self):
        """安全库存 = 日均消耗 × (采购周期 + 安全天数)"""
        svc = AutoProcurementService()
        # 日均10kg, 采购周期2天, 安全天数3天
        safety = svc.calc_safety_stock(daily_consumption=10.0, reorder_cycle_days=2)
        # 10 × (2 + 3) = 50
        assert safety == pytest.approx(50.0)

    def test_safety_stock_custom_safety_days(self):
        """自定义安全天数"""
        svc = AutoProcurementService(safety_days=5)
        safety = svc.calc_safety_stock(daily_consumption=5.0, reorder_cycle_days=3)
        # 5 × (3 + 5) = 40
        assert safety == pytest.approx(40.0)

    def test_safety_stock_zero_consumption(self):
        """零消耗时安全库存为0"""
        svc = AutoProcurementService()
        safety = svc.calc_safety_stock(daily_consumption=0.0, reorder_cycle_days=2)
        assert safety == 0.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. 建议采购量计算
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestRecommendedQuantity:
    def test_recommend_qty_positive(self):
        """库存不足时，建议量 = 安全库存 - 当前库存"""
        svc = AutoProcurementService()
        qty = svc.calc_recommended_quantity(safety_stock=50.0, current_qty=20.0)
        assert qty == pytest.approx(30.0)

    def test_recommend_qty_zero_when_sufficient(self):
        """库存充足时，建议量 = 0（不建议采购）"""
        svc = AutoProcurementService()
        qty = svc.calc_recommended_quantity(safety_stock=50.0, current_qty=60.0)
        assert qty == 0.0

    def test_recommend_qty_exactly_at_safety(self):
        """库存恰好等于安全库存时，建议量 = 0"""
        svc = AutoProcurementService()
        qty = svc.calc_recommended_quantity(safety_stock=50.0, current_qty=50.0)
        assert qty == 0.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. 供应商选择：选准期率最高的
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestSupplierSelection:
    @pytest.mark.asyncio
    async def test_select_best_supplier_by_score(self):
        """同原料多供应商时，选综合评分最高的"""
        svc = AutoProcurementService()
        suppliers = [
            {
                "supplier_id": "sup_A",
                "on_time_rate": 0.95,   # 准期率 95%
                "quality_rate": 0.90,   # 质量合格率 90%
                "price_score": 0.70,    # 价格竞争力 70%
            },
            {
                "supplier_id": "sup_B",
                "on_time_rate": 0.80,
                "quality_rate": 0.95,
                "price_score": 0.85,
            },
        ]
        # sup_A: 0.95×0.5 + 0.90×0.3 + 0.70×0.2 = 0.475 + 0.27 + 0.14 = 0.885
        # sup_B: 0.80×0.5 + 0.95×0.3 + 0.85×0.2 = 0.40 + 0.285 + 0.17 = 0.855
        best = await svc.select_best_supplier(
            suppliers=suppliers,
            ingredient_id="ing_001",
            tenant_id="tenant_001",
            db=None,
        )
        assert best["supplier_id"] == "sup_A"

    @pytest.mark.asyncio
    async def test_select_supplier_empty_list(self):
        """无供应商时返回None，不抛异常"""
        svc = AutoProcurementService()
        best = await svc.select_best_supplier(
            suppliers=[],
            ingredient_id="ing_001",
            tenant_id="tenant_001",
            db=None,
        )
        assert best is None

    @pytest.mark.asyncio
    async def test_supplier_score_calculation(self):
        """供应商评分公式：准期率×0.5 + 质量合格率×0.3 + 价格竞争力×0.2"""
        svc = AutoProcurementService()
        score = svc.calc_supplier_score(
            on_time_rate=1.0,
            quality_rate=1.0,
            price_score=1.0,
        )
        assert score == pytest.approx(1.0)

    def test_supplier_score_partial(self):
        """供应商部分数据计算"""
        svc = AutoProcurementService()
        score = svc.calc_supplier_score(
            on_time_rate=0.9,
            quality_rate=0.8,
            price_score=0.6,
        )
        expected = 0.9 * 0.5 + 0.8 * 0.3 + 0.6 * 0.2
        assert score == pytest.approx(expected)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. 紧急采购预警
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestUrgentAlert:
    def test_urgent_when_below_threshold(self):
        """库存低于3天用量时标记urgent"""
        svc = AutoProcurementService()
        # 日均10kg, 当前库存25kg -> 2.5天用量 < 3天
        is_urgent = svc.is_urgent(daily_consumption=10.0, current_qty=25.0)
        assert is_urgent is True

    def test_not_urgent_when_above_threshold(self):
        """库存高于3天用量时不标记urgent"""
        svc = AutoProcurementService()
        # 日均10kg, 当前库存35kg -> 3.5天用量 > 3天
        is_urgent = svc.is_urgent(daily_consumption=10.0, current_qty=35.0)
        assert is_urgent is False

    def test_not_urgent_at_exact_threshold(self):
        """库存恰好等于3天用量时不标记urgent"""
        svc = AutoProcurementService()
        is_urgent = svc.is_urgent(daily_consumption=10.0, current_qty=30.0)
        assert is_urgent is False

    def test_not_urgent_zero_consumption(self):
        """零消耗不标记urgent"""
        svc = AutoProcurementService()
        is_urgent = svc.is_urgent(daily_consumption=0.0, current_qty=0.0)
        assert is_urgent is False

    def test_urgent_custom_threshold(self):
        """自定义紧急预警阈值"""
        svc = AutoProcurementService(urgent_threshold_days=5)
        # 日均10kg, 当前40kg -> 4天 < 5天
        assert svc.is_urgent(daily_consumption=10.0, current_qty=40.0) is True
        # 日均10kg, 当前60kg -> 6天 > 5天
        assert svc.is_urgent(daily_consumption=10.0, current_qty=60.0) is False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  6. 生成采购建议单（需人工确认，不自动提交）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestGenerateRecommendations:
    @pytest.mark.asyncio
    async def test_generate_recommendations_basic(self):
        """生成采购建议列表，urgent原料排在前面"""
        svc = AutoProcurementService()
        # 模拟两种原料：一种紧急，一种普通
        mock_ingredients = [
            {
                "ingredient_id": "ing_001",
                "ingredient_name": "鲈鱼",
                "current_qty": 5.0,      # 库存仅5kg
                "unit": "kg",
                "unit_price_fen": 3500,
                "_mock_daily": 10.0,     # 日均10kg -> urgent
                "_mock_supplier": {"supplier_id": "sup_A", "supplier_name": "渔港"},
                "reorder_cycle_days": 2,
            },
            {
                "ingredient_id": "ing_002",
                "ingredient_name": "大米",
                "current_qty": 100.0,    # 库存100kg
                "unit": "kg",
                "unit_price_fen": 300,
                "_mock_daily": 5.0,      # 日均5kg -> 100/5=20天，不urgent
                "_mock_supplier": {"supplier_id": "sup_B", "supplier_name": "粮油商"},
                "reorder_cycle_days": 3,
            },
        ]
        recommendations = await svc.generate_recommendations_from_mock(
            mock_ingredients=mock_ingredients,
            store_id="store_001",
            tenant_id="tenant_001",
            db=None,
        )
        assert len(recommendations) >= 1
        # 鲈鱼有建议（库存不足）
        fish_rec = next((r for r in recommendations if r.ingredient_id == "ing_001"), None)
        assert fish_rec is not None
        assert fish_rec.is_urgent is True
        # 大米库存充足，不建议采购
        rice_rec = next((r for r in recommendations if r.ingredient_id == "ing_002"), None)
        assert rice_rec is None

    @pytest.mark.asyncio
    async def test_recommendations_sorted_urgent_first(self):
        """urgent原料排在普通原料之前"""
        svc = AutoProcurementService()
        mock_ingredients = [
            {
                "ingredient_id": "ing_A",
                "ingredient_name": "普通食材",
                "current_qty": 20.0,
                "unit": "kg",
                "unit_price_fen": 500,
                "_mock_daily": 5.0,      # 20/5=4天，不urgent，但需要补货
                "_mock_supplier": {"supplier_id": "sup_X", "supplier_name": "供应商X"},
                "reorder_cycle_days": 2,
            },
            {
                "ingredient_id": "ing_B",
                "ingredient_name": "紧急食材",
                "current_qty": 3.0,
                "unit": "kg",
                "unit_price_fen": 1000,
                "_mock_daily": 5.0,      # 3/5=0.6天，urgent
                "_mock_supplier": {"supplier_id": "sup_Y", "supplier_name": "供应商Y"},
                "reorder_cycle_days": 2,
            },
        ]
        recommendations = await svc.generate_recommendations_from_mock(
            mock_ingredients=mock_ingredients,
            store_id="store_001",
            tenant_id="tenant_001",
            db=None,
        )
        # 紧急原料排在前面
        urgent_recs = [r for r in recommendations if r.is_urgent]
        normal_recs = [r for r in recommendations if not r.is_urgent]
        if urgent_recs and normal_recs:
            first_urgent_idx = recommendations.index(urgent_recs[0])
            first_normal_idx = recommendations.index(normal_recs[0])
            assert first_urgent_idx < first_normal_idx

    @pytest.mark.asyncio
    async def test_recommendations_not_auto_submitted(self):
        """建议单状态为draft，不自动提交"""
        svc = AutoProcurementService()
        mock_ingredients = [
            {
                "ingredient_id": "ing_001",
                "ingredient_name": "鲈鱼",
                "current_qty": 5.0,
                "unit": "kg",
                "unit_price_fen": 3500,
                "_mock_daily": 10.0,
                "_mock_supplier": {"supplier_id": "sup_A", "supplier_name": "渔港"},
                "reorder_cycle_days": 2,
            },
        ]
        recommendations = await svc.generate_recommendations_from_mock(
            mock_ingredients=mock_ingredients,
            store_id="store_001",
            tenant_id="tenant_001",
            db=None,
        )
        for rec in recommendations:
            assert rec.status == "draft"

    @pytest.mark.asyncio
    async def test_recommendations_data_structure(self):
        """建议单包含必要字段"""
        svc = AutoProcurementService()
        mock_ingredients = [
            {
                "ingredient_id": "ing_001",
                "ingredient_name": "鲈鱼",
                "current_qty": 5.0,
                "unit": "kg",
                "unit_price_fen": 3500,
                "_mock_daily": 10.0,
                "_mock_supplier": {"supplier_id": "sup_A", "supplier_name": "渔港"},
                "reorder_cycle_days": 2,
            },
        ]
        recommendations = await svc.generate_recommendations_from_mock(
            mock_ingredients=mock_ingredients,
            store_id="store_001",
            tenant_id="tenant_001",
            db=None,
        )
        assert len(recommendations) == 1
        rec = recommendations[0]
        assert isinstance(rec, ProcurementRecommendation)
        assert rec.ingredient_id == "ing_001"
        assert rec.ingredient_name == "鲈鱼"
        assert rec.recommended_qty > 0
        assert rec.supplier_id == "sup_A"
        assert rec.estimated_cost_fen > 0
        assert rec.store_id == "store_001"
        assert rec.tenant_id == "tenant_001"
        assert rec.daily_consumption == pytest.approx(10.0)
        assert rec.current_qty == 5.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  7. tenant_id 隔离
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestTenantIsolation:
    @pytest.mark.asyncio
    async def test_recommendations_carry_tenant_id(self):
        """生成的建议单必须包含正确的tenant_id"""
        svc = AutoProcurementService()
        mock_ingredients = [
            {
                "ingredient_id": "ing_001",
                "ingredient_name": "鲈鱼",
                "current_qty": 5.0,
                "unit": "kg",
                "unit_price_fen": 3500,
                "_mock_daily": 10.0,
                "_mock_supplier": {"supplier_id": "sup_A", "supplier_name": "渔港"},
                "reorder_cycle_days": 2,
            },
        ]
        for tenant in ["tenant_AAA", "tenant_BBB"]:
            recs = await svc.generate_recommendations_from_mock(
                mock_ingredients=mock_ingredients,
                store_id="store_001",
                tenant_id=tenant,
                db=None,
            )
            for rec in recs:
                assert rec.tenant_id == tenant

    @pytest.mark.asyncio
    async def test_create_requisition_carries_tenant_id(self):
        """将建议转为申购单时，tenant_id 正确传递"""
        svc = AutoProcurementService()
        recs = [
            ProcurementRecommendation(
                recommendation_id="rec_001",
                ingredient_id="ing_001",
                ingredient_name="鲈鱼",
                current_qty=5.0,
                daily_consumption=10.0,
                safety_stock=50.0,
                recommended_qty=45.0,
                unit="kg",
                unit_price_fen=3500,
                estimated_cost_fen=157500,
                supplier_id="sup_A",
                supplier_name="渔港",
                is_urgent=True,
                status="draft",
                store_id="store_001",
                tenant_id="tenant_XYZ",
            )
        ]
        result = await svc.create_requisition_from_recommendations(
            recommendations=recs,
            store_id="store_001",
            tenant_id="tenant_XYZ",
            db=None,
        )
        assert result["tenant_id"] == "tenant_XYZ"

    @pytest.mark.asyncio
    async def test_demand_forecast_carries_tenant_id(self):
        """需求预测包含tenant_id参数，不混用其他租户数据"""
        svc = DemandForecastService()
        # 不同租户可独立调用，不抛异常
        for tenant in ["t1", "t2", "t3"]:
            result = await svc.get_daily_consumption(
                ingredient_id="ing_001",
                store_id="store_001",
                days=7,
                tenant_id=tenant,
                db=None,
                _mock_total_usage=0.0,
            )
            assert isinstance(result, float)
            assert result >= 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  8. 将建议转为正式申购单
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestCreateRequisitionFromRecommendations:
    @pytest.mark.asyncio
    async def test_create_requisition_basic(self):
        """将建议列表转为申购单，包含正确字段"""
        svc = AutoProcurementService()
        recs = [
            ProcurementRecommendation(
                recommendation_id="rec_001",
                ingredient_id="ing_001",
                ingredient_name="鲈鱼",
                current_qty=5.0,
                daily_consumption=10.0,
                safety_stock=50.0,
                recommended_qty=45.0,
                unit="kg",
                unit_price_fen=3500,
                estimated_cost_fen=157500,
                supplier_id="sup_A",
                supplier_name="渔港",
                is_urgent=True,
                status="draft",
                store_id="store_001",
                tenant_id="tenant_001",
            )
        ]
        result = await svc.create_requisition_from_recommendations(
            recommendations=recs,
            store_id="store_001",
            tenant_id="tenant_001",
            db=None,
        )
        assert result["status"] == "draft"
        assert result["store_id"] == "store_001"
        assert result["tenant_id"] == "tenant_001"
        assert result["item_count"] == 1
        assert result["total_estimated_fen"] == 157500
        assert result["source"] == "auto_procurement_agent"
        assert "requisition_id" in result

    @pytest.mark.asyncio
    async def test_create_requisition_empty_raises(self):
        """空建议列表时抛出ValueError"""
        svc = AutoProcurementService()
        with pytest.raises(ValueError, match="至少一项"):
            await svc.create_requisition_from_recommendations(
                recommendations=[],
                store_id="store_001",
                tenant_id="tenant_001",
                db=None,
            )

    @pytest.mark.asyncio
    async def test_create_requisition_multiple_items(self):
        """多原料建议合并为一张申购单"""
        svc = AutoProcurementService()
        recs = [
            ProcurementRecommendation(
                recommendation_id="rec_001",
                ingredient_id="ing_001",
                ingredient_name="鲈鱼",
                current_qty=5.0,
                daily_consumption=10.0,
                safety_stock=50.0,
                recommended_qty=45.0,
                unit="kg",
                unit_price_fen=3500,
                estimated_cost_fen=157500,
                supplier_id="sup_A",
                supplier_name="渔港",
                is_urgent=True,
                status="draft",
                store_id="store_001",
                tenant_id="tenant_001",
            ),
            ProcurementRecommendation(
                recommendation_id="rec_002",
                ingredient_id="ing_002",
                ingredient_name="大虾",
                current_qty=2.0,
                daily_consumption=3.0,
                safety_stock=15.0,
                recommended_qty=13.0,
                unit="kg",
                unit_price_fen=8000,
                estimated_cost_fen=104000,
                supplier_id="sup_B",
                supplier_name="海鲜市场",
                is_urgent=False,
                status="draft",
                store_id="store_001",
                tenant_id="tenant_001",
            ),
        ]
        result = await svc.create_requisition_from_recommendations(
            recommendations=recs,
            store_id="store_001",
            tenant_id="tenant_001",
            db=None,
        )
        assert result["item_count"] == 2
        assert result["total_estimated_fen"] == 157500 + 104000


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  9. 需求预测
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestDemandForecast:
    @pytest.mark.asyncio
    async def test_forecast_next_period(self):
        """预测未来N天消耗 = 日均 × N"""
        svc = DemandForecastService()
        forecast = await svc.forecast_next_period(
            ingredient_id="ing_001",
            store_id="store_001",
            days=7,
            tenant_id="tenant_001",
            db=None,
            _mock_daily=10.0,
        )
        assert forecast == pytest.approx(70.0)  # 10 × 7

    @pytest.mark.asyncio
    async def test_forecast_with_holiday_factor(self):
        """节假日系数影响预测结果"""
        svc = DemandForecastService()
        # 节假日系数1.3，预测量应乘以1.3
        forecast = await svc.forecast_next_period(
            ingredient_id="ing_001",
            store_id="store_001",
            days=7,
            tenant_id="tenant_001",
            db=None,
            _mock_daily=10.0,
            _mock_holiday_factor=1.3,
        )
        assert forecast == pytest.approx(91.0)  # 10 × 7 × 1.3

    @pytest.mark.asyncio
    async def test_forecast_no_history_returns_zero(self):
        """无历史数据且无BOM时，预测返回0，不报错"""
        svc = DemandForecastService()
        forecast = await svc.forecast_next_period(
            ingredient_id="ing_new",
            store_id="store_001",
            days=7,
            tenant_id="tenant_001",
            db=None,
            _mock_daily=0.0,
        )
        assert forecast == 0.0
