"""采购预测集成服务测试

覆盖场景：
  1. 销售历史 × 7天 → 计算食材需求量
  2. 库存充足时不触发补货建议
  3. 库存低于安全水位触发补货，考虑供应商交期
  4. AI 摘要生成 mock 测试（不真实调用）
  5. 边界值：零库存、负预测（异常处理）
  6. generate_purchase_order_draft 按供应商分组 + EOQ
  7. get_replenishment_urgency 紧急预警（不走 AI）
"""
from __future__ import annotations

import os
import sys

# ─── 将 src 目录加入 Python 路径（与其他测试保持一致）───
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─── 从服务直接导入，避免 DB 依赖 ───
from services.procurement_forecast_service import (
    IngredientDemandForecast,
    ProcurementForecastService,
    PurchaseOrderDraft,
    _calc_purchase_qty,
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  辅助工厂
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STORE_ID = "store-001"
TENANT_ID = "tenant-abc"


def _make_demand(
    ingredient_id: str = "ing-001",
    ingredient_name: str = "鸡腿",
    forecast_qty: float = 70.0,
    current_stock: float = 20.0,
    safety_stock: float = 15.0,
    unit: str = "kg",
    unit_cost_fen: int = 1200,
    supplier_id: str = "sup-001",
    supplier_lead_days: int = 1,
    package_size: float = 5.0,
    confidence: float = 0.85,
    purchase_qty: float = 0.0,
) -> IngredientDemandForecast:
    return IngredientDemandForecast(
        ingredient_id=ingredient_id,
        ingredient_name=ingredient_name,
        forecast_qty=forecast_qty,
        current_stock=current_stock,
        safety_stock=safety_stock,
        unit=unit,
        unit_cost_fen=unit_cost_fen,
        supplier_id=supplier_id,
        supplier_lead_days=supplier_lead_days,
        package_size=package_size,
        confidence=confidence,
        purchase_qty=purchase_qty,
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  单元测试：辅助计算函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestCalcPurchaseQty:
    """_calc_purchase_qty(demand, stock, safety, lead_days, package_size, safety_factor)"""

    def test_basic_purchase_calculation(self):
        """需求70kg，当前库存20kg，安全库存15kg，交期1天(日均10kg)，包装5kg"""
        # 净需求 = max(0, 70 - 20 + 15 + 10*1) = max(0, 75) = 75
        # 含安全系数1.1 → 75*1.1 = 82.5 → 向上取整到包装规格5 → ceil(82.5/5)*5 = 85
        qty = _calc_purchase_qty(
            forecast_demand=70.0,
            current_stock=20.0,
            safety_stock=15.0,
            supplier_lead_days=1,
            daily_demand=10.0,
            package_size=5.0,
            safety_factor=1.1,
        )
        assert qty == 85.0

    def test_sufficient_stock_returns_zero(self):
        """库存充足（远超需求），不触发采购"""
        qty = _calc_purchase_qty(
            forecast_demand=10.0,
            current_stock=100.0,
            safety_stock=5.0,
            supplier_lead_days=1,
            daily_demand=1.43,
            package_size=1.0,
            safety_factor=1.1,
        )
        assert qty == 0.0

    def test_zero_stock_triggers_full_purchase(self):
        """零库存：采购量 = 全部需求 × 安全系数，取整到包装"""
        qty = _calc_purchase_qty(
            forecast_demand=50.0,
            current_stock=0.0,
            safety_stock=10.0,
            supplier_lead_days=2,
            daily_demand=7.14,
            package_size=10.0,
            safety_factor=1.1,
        )
        # 净需求 = 50 - 0 + 10 + 2*7.14 = 50+10+14.28 = 74.28
        # × 1.1 = 81.7 → ceil(81.7/10)*10 = 90
        assert qty == 90.0

    def test_package_size_rounding(self):
        """包装取整：结果必须是 package_size 的整数倍"""
        qty = _calc_purchase_qty(
            forecast_demand=33.0,
            current_stock=5.0,
            safety_stock=5.0,
            supplier_lead_days=0,
            daily_demand=4.71,
            package_size=6.0,
            safety_factor=1.0,
        )
        assert qty % 6.0 == 0.0

    def test_negative_forecast_treated_as_zero(self):
        """负预测量（数据异常）应当按0处理，不抛出异常"""
        qty = _calc_purchase_qty(
            forecast_demand=-5.0,
            current_stock=20.0,
            safety_stock=10.0,
            supplier_lead_days=1,
            daily_demand=2.0,
            package_size=1.0,
            safety_factor=1.0,
        )
        # 负预测视为0：净需求 = max(0, 0 - 20 + 10 + 2) = 0
        assert qty == 0.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  集成测试：forecast_ingredient_demand
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestForecastIngredientDemand:
    """forecast_ingredient_demand 集成流程"""

    @pytest.mark.asyncio
    async def test_7day_demand_forecast_from_history(self):
        """7天销售历史 → 正确计算食材需求量（confidence 来自数据质量）"""
        svc = ProcurementForecastService()
        mock_db = MagicMock()

        # 模拟 DemandForecastService.forecast_next_period 返回值
        # 食材A：每天消耗 10kg，7天 = 70kg；食材B：5kg/天，7天 = 35kg
        mock_forecasts = {
            "ing-A": 70.0,
            "ing-B": 35.0,
        }

        async def mock_forecast_period(ingredient_id, **kwargs):
            return mock_forecasts.get(ingredient_id, 0.0)

        # 模拟阈值列表返回
        from services.smart_replenishment import InventoryThreshold
        mock_thresholds = [
            InventoryThreshold(
                tenant_id=TENANT_ID, store_id=STORE_ID,
                ingredient_id="ing-A", ingredient_name="鸡腿",
                safety_stock=15.0, target_stock=100.0, min_order_qty=5.0,
                trigger_rule="safety_only",
            ),
            InventoryThreshold(
                tenant_id=TENANT_ID, store_id=STORE_ID,
                ingredient_id="ing-B", ingredient_name="大葱",
                safety_stock=5.0, target_stock=50.0, min_order_qty=1.0,
                trigger_rule="safety_only",
            ),
        ]

        with (
            patch.object(svc, "_fetch_thresholds", AsyncMock(return_value=mock_thresholds)),
            patch.object(svc, "_fetch_current_stocks", AsyncMock(return_value={"ing-A": 20.0, "ing-B": 8.0})),
            patch.object(svc, "_fetch_supplier_info", AsyncMock(return_value={
                "ing-A": {"supplier_id": "sup-001", "lead_days": 1, "package_size": 5.0, "unit_cost_fen": 1200},
                "ing-B": {"supplier_id": "sup-002", "lead_days": 2, "package_size": 1.0, "unit_cost_fen": 300},
            })),
            patch("services.procurement_forecast_service.DemandForecastService") as MockDFS,
        ):
            mock_dfs_instance = MockDFS.return_value
            mock_dfs_instance.forecast_next_period = AsyncMock(side_effect=lambda ingredient_id, **kw: mock_forecasts.get(ingredient_id, 0.0))

            result = await svc.forecast_ingredient_demand(
                store_id=STORE_ID,
                tenant_id=TENANT_ID,
                forecast_days=7,
                db=mock_db,
            )

        assert len(result) == 2
        ing_a = next(r for r in result if r.ingredient_id == "ing-A")
        ing_b = next(r for r in result if r.ingredient_id == "ing-B")
        assert ing_a.forecast_qty == 70.0
        assert ing_b.forecast_qty == 35.0
        # 置信度在 [0, 1] 区间
        assert 0.0 <= ing_a.confidence <= 1.0
        assert 0.0 <= ing_b.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_sufficient_stock_no_purchase_needed(self):
        """库存充足时，purchase_qty 应为 0（不触发补货）"""
        svc = ProcurementForecastService()
        mock_db = MagicMock()

        from services.smart_replenishment import InventoryThreshold
        mock_thresholds = [
            InventoryThreshold(
                tenant_id=TENANT_ID, store_id=STORE_ID,
                ingredient_id="ing-C", ingredient_name="食盐",
                safety_stock=2.0, target_stock=20.0, min_order_qty=1.0,
                trigger_rule="safety_only",
            ),
        ]

        with (
            patch.object(svc, "_fetch_thresholds", AsyncMock(return_value=mock_thresholds)),
            # 当前库存 200kg，远超 7 天预测 5kg
            patch.object(svc, "_fetch_current_stocks", AsyncMock(return_value={"ing-C": 200.0})),
            patch.object(svc, "_fetch_supplier_info", AsyncMock(return_value={
                "ing-C": {"supplier_id": "sup-003", "lead_days": 1, "package_size": 1.0, "unit_cost_fen": 50},
            })),
            patch("services.procurement_forecast_service.DemandForecastService") as MockDFS,
        ):
            mock_dfs_instance = MockDFS.return_value
            mock_dfs_instance.forecast_next_period = AsyncMock(return_value=5.0)

            result = await svc.forecast_ingredient_demand(
                store_id=STORE_ID,
                tenant_id=TENANT_ID,
                forecast_days=7,
                db=mock_db,
            )

        assert len(result) == 1
        assert result[0].purchase_qty == 0.0, "库存充足，purchase_qty 应为 0"

    @pytest.mark.asyncio
    async def test_low_stock_triggers_purchase_with_lead_time(self):
        """库存低于安全水位 + 考虑供应商交期 → 触发采购"""
        svc = ProcurementForecastService()
        mock_db = MagicMock()

        from services.smart_replenishment import InventoryThreshold
        mock_thresholds = [
            InventoryThreshold(
                tenant_id=TENANT_ID, store_id=STORE_ID,
                ingredient_id="ing-D", ingredient_name="猪五花",
                safety_stock=20.0, target_stock=150.0, min_order_qty=5.0,
                trigger_rule="safety_only",
            ),
        ]

        with (
            patch.object(svc, "_fetch_thresholds", AsyncMock(return_value=mock_thresholds)),
            # 当前库存仅 10kg，低于安全库存 20kg
            patch.object(svc, "_fetch_current_stocks", AsyncMock(return_value={"ing-D": 10.0})),
            patch.object(svc, "_fetch_supplier_info", AsyncMock(return_value={
                "ing-D": {
                    "supplier_id": "sup-004",
                    "lead_days": 3,      # 3天交期，需额外储备
                    "package_size": 5.0,
                    "unit_cost_fen": 2500,
                },
            })),
            patch("services.procurement_forecast_service.DemandForecastService") as MockDFS,
        ):
            mock_dfs_instance = MockDFS.return_value
            # 7天预测消耗 70kg（日均10kg）
            mock_dfs_instance.forecast_next_period = AsyncMock(return_value=70.0)

            result = await svc.forecast_ingredient_demand(
                store_id=STORE_ID,
                tenant_id=TENANT_ID,
                forecast_days=7,
                db=mock_db,
            )

        assert len(result) == 1
        demand = result[0]
        assert demand.purchase_qty > 0, "库存低于安全水位，应触发采购"
        # 采购量必须是 package_size=5 的整数倍
        assert demand.purchase_qty % 5.0 == 0.0
        # 考虑了交期（3天 × 日均10kg = 30kg 缓冲），总采购量应充分
        assert demand.purchase_qty >= 70.0, "采购量应覆盖预测需求"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  集成测试：generate_purchase_order_draft
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestGeneratePurchaseOrderDraft:
    """generate_purchase_order_draft：按供应商分组 + AI 摘要条件触发"""

    @pytest.mark.asyncio
    async def test_group_by_supplier(self):
        """多个食材来自同一供应商，应合并为一张采购单"""
        svc = ProcurementForecastService()
        mock_db = MagicMock()

        demands = [
            _make_demand("ing-001", "鸡腿", 70.0, 20.0, 15.0, supplier_id="sup-001", purchase_qty=85.0),
            _make_demand("ing-002", "鸡翅", 40.0, 10.0, 8.0, supplier_id="sup-001", purchase_qty=45.0),
            _make_demand("ing-003", "大葱", 35.0, 8.0, 5.0, supplier_id="sup-002", purchase_qty=30.0),
        ]

        result = await svc.generate_purchase_order_draft(
            store_id=STORE_ID,
            tenant_id=TENANT_ID,
            demand_forecast=demands,
            db=mock_db,
        )

        assert isinstance(result, PurchaseOrderDraft)
        assert len(result.orders_by_supplier) == 2, "应分为2个供应商采购单"

        sup1_order = next(o for o in result.orders_by_supplier if o.supplier_id == "sup-001")
        assert len(sup1_order.items) == 2, "sup-001 应有2个食材"

    @pytest.mark.asyncio
    async def test_ai_summary_not_triggered_below_threshold(self):
        """总金额 < 1万元时，不调用 AI，ai_summary 为 None"""
        svc = ProcurementForecastService()
        mock_db = MagicMock()

        # 单价 100分 × 10kg = 1000分 = 10元，远低于1万
        demands = [
            _make_demand(unit_cost_fen=100, purchase_qty=10.0),
        ]

        with patch.object(svc, "_call_ai_summary", AsyncMock()) as mock_ai:
            result = await svc.generate_purchase_order_draft(
                store_id=STORE_ID,
                tenant_id=TENANT_ID,
                demand_forecast=demands,
                db=mock_db,
            )

        mock_ai.assert_not_called()
        assert result.ai_summary is None

    @pytest.mark.asyncio
    async def test_ai_summary_triggered_above_threshold(self):
        """总金额 >= 1万元时，调用 ModelRouter 生成摘要"""
        svc = ProcurementForecastService()
        mock_db = MagicMock()

        # 单价 10000分 × 200kg = 2,000,000分 = 2万元
        demands = [
            _make_demand(unit_cost_fen=10000, purchase_qty=200.0),
        ]

        mock_summary = "本次采购总金额约2万元，主要为鸡腿食材，建议与供应商确认交期。"

        with patch.object(svc, "_call_ai_summary", AsyncMock(return_value=mock_summary)) as mock_ai:
            result = await svc.generate_purchase_order_draft(
                store_id=STORE_ID,
                tenant_id=TENANT_ID,
                demand_forecast=demands,
                db=mock_db,
            )

        mock_ai.assert_called_once()
        assert result.ai_summary == mock_summary

    @pytest.mark.asyncio
    async def test_empty_demand_returns_empty_draft(self):
        """空需求列表，返回空草稿（不崩溃）"""
        svc = ProcurementForecastService()
        mock_db = MagicMock()

        result = await svc.generate_purchase_order_draft(
            store_id=STORE_ID,
            tenant_id=TENANT_ID,
            demand_forecast=[],
            db=mock_db,
        )

        assert isinstance(result, PurchaseOrderDraft)
        assert result.orders_by_supplier == []
        assert result.total_amount_fen == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  集成测试：get_replenishment_urgency
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestGetReplenishmentUrgency:
    """get_replenishment_urgency：实时低延迟，不走 AI"""

    @pytest.mark.asyncio
    async def test_urgent_ingredients_detected(self):
        """库存不足以支撑明日营业的食材，出现在紧急清单中"""
        svc = ProcurementForecastService()
        mock_db = MagicMock()

        from services.smart_replenishment import InventoryThreshold
        mock_thresholds = [
            # 库存 2kg，明日需求 10kg，严重不足
            InventoryThreshold(
                tenant_id=TENANT_ID, store_id=STORE_ID,
                ingredient_id="ing-E", ingredient_name="生蚝",
                safety_stock=10.0, target_stock=50.0, min_order_qty=1.0,
                trigger_rule="safety_only",
            ),
            # 库存 50kg，明日需求 5kg，充足
            InventoryThreshold(
                tenant_id=TENANT_ID, store_id=STORE_ID,
                ingredient_id="ing-F", ingredient_name="食用油",
                safety_stock=5.0, target_stock=30.0, min_order_qty=1.0,
                trigger_rule="safety_only",
            ),
        ]

        with (
            patch.object(svc, "_fetch_thresholds", AsyncMock(return_value=mock_thresholds)),
            patch.object(svc, "_fetch_current_stocks", AsyncMock(return_value={
                "ing-E": 2.0,   # 严重不足
                "ing-F": 50.0,  # 充足
            })),
            patch("services.procurement_forecast_service.DemandForecastService") as MockDFS,
        ):
            mock_dfs_instance = MockDFS.return_value
            # 明日预计消耗：生蚝10kg，食用油5kg
            async def _daily_forecast(ingredient_id, **kw):
                return {"ing-E": 10.0, "ing-F": 5.0}.get(ingredient_id, 0.0)
            mock_dfs_instance.forecast_next_period = AsyncMock(side_effect=_daily_forecast)

            result = await svc.get_replenishment_urgency(
                store_id=STORE_ID,
                tenant_id=TENANT_ID,
                db=mock_db,
            )

        urgent_ids = [u.ingredient_id for u in result]
        assert "ing-E" in urgent_ids, "生蚝库存严重不足，应在紧急清单"
        assert "ing-F" not in urgent_ids, "食用油充足，不应在紧急清单"

    @pytest.mark.asyncio
    async def test_urgent_result_not_ai_generated(self):
        """紧急预警不调用 AI（低延迟优先）"""
        svc = ProcurementForecastService()
        mock_db = MagicMock()

        from services.smart_replenishment import InventoryThreshold
        mock_thresholds = [
            InventoryThreshold(
                tenant_id=TENANT_ID, store_id=STORE_ID,
                ingredient_id="ing-G", ingredient_name="辣椒",
                safety_stock=5.0, target_stock=30.0, min_order_qty=1.0,
                trigger_rule="safety_only",
            ),
        ]

        with (
            patch.object(svc, "_fetch_thresholds", AsyncMock(return_value=mock_thresholds)),
            patch.object(svc, "_fetch_current_stocks", AsyncMock(return_value={"ing-G": 1.0})),
            patch.object(svc, "_call_ai_summary", AsyncMock()) as mock_ai,
            patch("services.procurement_forecast_service.DemandForecastService") as MockDFS,
        ):
            mock_dfs_instance = MockDFS.return_value
            mock_dfs_instance.forecast_next_period = AsyncMock(return_value=8.0)

            await svc.get_replenishment_urgency(
                store_id=STORE_ID,
                tenant_id=TENANT_ID,
                db=mock_db,
            )

        mock_ai.assert_not_called(), "紧急预警不应调用 AI"

    @pytest.mark.asyncio
    async def test_zero_stock_ingredient_always_urgent(self):
        """零库存食材必定在紧急清单中"""
        svc = ProcurementForecastService()
        mock_db = MagicMock()

        from services.smart_replenishment import InventoryThreshold
        mock_thresholds = [
            InventoryThreshold(
                tenant_id=TENANT_ID, store_id=STORE_ID,
                ingredient_id="ing-H", ingredient_name="虾仁",
                safety_stock=5.0, target_stock=30.0, min_order_qty=1.0,
                trigger_rule="safety_only",
            ),
        ]

        with (
            patch.object(svc, "_fetch_thresholds", AsyncMock(return_value=mock_thresholds)),
            patch.object(svc, "_fetch_current_stocks", AsyncMock(return_value={"ing-H": 0.0})),
            patch("services.procurement_forecast_service.DemandForecastService") as MockDFS,
        ):
            mock_dfs_instance = MockDFS.return_value
            mock_dfs_instance.forecast_next_period = AsyncMock(return_value=5.0)

            result = await svc.get_replenishment_urgency(
                store_id=STORE_ID,
                tenant_id=TENANT_ID,
                db=mock_db,
            )

        assert any(u.ingredient_id == "ing-H" for u in result)
        urgent_item = next(u for u in result if u.ingredient_id == "ing-H")
        assert urgent_item.shortage_qty > 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  边界值测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestEdgeCases:
    """边界值：零库存、负预测、无食材、超大需求"""

    @pytest.mark.asyncio
    async def test_no_thresholds_returns_empty(self):
        """门店无阈值配置时，返回空列表（不崩溃）"""
        svc = ProcurementForecastService()
        mock_db = MagicMock()

        with patch.object(svc, "_fetch_thresholds", AsyncMock(return_value=[])):
            result = await svc.forecast_ingredient_demand(
                store_id=STORE_ID,
                tenant_id=TENANT_ID,
                forecast_days=7,
                db=mock_db,
            )

        assert result == []

    def test_negative_forecast_clamped_to_zero(self):
        """负预测量应被钳制到0，不产生负的采购量"""
        qty = _calc_purchase_qty(
            forecast_demand=-100.0,   # 异常负值
            current_stock=5.0,
            safety_stock=3.0,
            supplier_lead_days=1,
            daily_demand=1.0,
            package_size=1.0,
            safety_factor=1.0,
        )
        assert qty >= 0.0, "采购量不能为负"

    def test_purchase_qty_is_multiple_of_package_size(self):
        """各种需求量，结果必须是包装规格的整数倍"""
        for demand in [7.3, 13.7, 50.0, 99.9]:
            for pkg in [1.0, 5.0, 10.0, 25.0]:
                qty = _calc_purchase_qty(
                    forecast_demand=demand,
                    current_stock=0.0,
                    safety_stock=1.0,
                    supplier_lead_days=0,
                    daily_demand=demand / 7,
                    package_size=pkg,
                    safety_factor=1.1,
                )
                if qty > 0:
                    remainder = round(qty % pkg, 6)
                    assert remainder == 0.0, f"qty={qty} 不是 pkg={pkg} 的整数倍"

    @pytest.mark.asyncio
    async def test_confidence_field_always_present(self):
        """所有预测结果都必须携带 confidence 字段，值在 [0, 1]"""
        svc = ProcurementForecastService()
        mock_db = MagicMock()

        from services.smart_replenishment import InventoryThreshold
        mock_thresholds = [
            InventoryThreshold(
                tenant_id=TENANT_ID, store_id=STORE_ID,
                ingredient_id="ing-I", ingredient_name="测试食材",
                safety_stock=5.0, target_stock=50.0, min_order_qty=1.0,
                trigger_rule="safety_only",
            ),
        ]

        with (
            patch.object(svc, "_fetch_thresholds", AsyncMock(return_value=mock_thresholds)),
            patch.object(svc, "_fetch_current_stocks", AsyncMock(return_value={"ing-I": 10.0})),
            patch.object(svc, "_fetch_supplier_info", AsyncMock(return_value={
                "ing-I": {"supplier_id": "sup-X", "lead_days": 1, "package_size": 1.0, "unit_cost_fen": 500},
            })),
            patch("services.procurement_forecast_service.DemandForecastService") as MockDFS,
        ):
            mock_dfs_instance = MockDFS.return_value
            mock_dfs_instance.forecast_next_period = AsyncMock(return_value=20.0)

            result = await svc.forecast_ingredient_demand(
                store_id=STORE_ID,
                tenant_id=TENANT_ID,
                forecast_days=7,
                db=mock_db,
            )

        for item in result:
            assert hasattr(item, "confidence")
            assert 0.0 <= item.confidence <= 1.0
