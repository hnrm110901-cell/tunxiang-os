"""理论成本 + 实际成本 纯函数测试"""
import sys
import os
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.theoretical_cost import (
    compute_dish_theoretical_cost_from_bom,
    _sum_bom_item_costs,
    get_dish_theoretical_cost,
)
from services.actual_cost import (
    compute_actual_cost_from_prices,
    get_ingredient_actual_price,
    calculate_actual_dish_cost,
)


# ═══════════════════════════════════════════════
# 理论成本测试
# ═══════════════════════════════════════════════

class TestTheoreticalCostPureFunctions:
    """测试 BOM 理论成本计算纯函数"""

    def test_basic_bom_cost(self):
        """基本 BOM 成本：2种原料，无损耗"""
        items = [
            {"standard_qty": "0.5", "waste_factor": "0", "unit_cost_fen": 2000},   # 0.5kg * 20元/kg = 10元
            {"standard_qty": "0.2", "waste_factor": "0", "unit_cost_fen": 5000},   # 0.2kg * 50元/kg = 10元
        ]
        result = compute_dish_theoretical_cost_from_bom(items)
        assert result == 2000  # 1000 + 1000 = 2000分 = 20元

    def test_bom_cost_with_waste_factor(self):
        """包含损耗因子的 BOM 成本"""
        items = [
            # 0.5kg * (1 + 0.1) * 2000分 = 0.55 * 2000 = 1100分
            {"standard_qty": "0.5", "waste_factor": "0.1", "unit_cost_fen": 2000},
        ]
        result = compute_dish_theoretical_cost_from_bom(items)
        assert result == 1100

    def test_bom_cost_empty_items(self):
        """空 BOM 返回 0"""
        assert compute_dish_theoretical_cost_from_bom([]) == 0

    def test_bom_cost_zero_unit_cost(self):
        """单价为0的原料不影响总成本"""
        items = [
            {"standard_qty": "1.0", "waste_factor": "0", "unit_cost_fen": 1000},
            {"standard_qty": "0.5", "waste_factor": "0", "unit_cost_fen": 0},
        ]
        result = compute_dish_theoretical_cost_from_bom(items)
        assert result == 1000

    def test_bom_cost_null_unit_cost(self):
        """unit_cost_fen 为 None 时按 0 处理"""
        items = [
            {"standard_qty": "1.0", "waste_factor": "0", "unit_cost_fen": None},
        ]
        result = compute_dish_theoretical_cost_from_bom(items)
        assert result == 0

    def test_bom_cost_multiple_ingredients(self):
        """多原料综合测试（模拟一道菜）"""
        items = [
            # 猪肉 0.3kg, 损耗5%, 40元/kg → 0.3 * 1.05 * 4000 = 1260分
            {"standard_qty": "0.3", "waste_factor": "0.05", "unit_cost_fen": 4000},
            # 青椒 0.15kg, 损耗10%, 8元/kg → 0.15 * 1.10 * 800 = 132分
            {"standard_qty": "0.15", "waste_factor": "0.10", "unit_cost_fen": 800},
            # 姜蒜 0.02kg, 无损耗, 20元/kg → 0.02 * 2000 = 40分
            {"standard_qty": "0.02", "waste_factor": "0", "unit_cost_fen": 2000},
        ]
        result = compute_dish_theoretical_cost_from_bom(items)
        assert result == 1432  # 1260 + 132 + 40

    def test_no_db_returns_zero(self):
        """无数据库连接时返回 0"""
        import uuid
        result = get_dish_theoretical_cost(uuid.uuid4(), uuid.uuid4(), None)
        assert result == 0


# ═══════════════════════════════════════════════
# 实际成本测试
# ═══════════════════════════════════════════════

class TestActualCostPureFunctions:
    """测试实际成本计算纯函数"""

    def test_basic_actual_cost(self):
        """基本实际成本计算"""
        bom_items = [
            {"ingredient_id": "ing-001", "standard_qty": "0.5", "waste_factor": "0"},
            {"ingredient_id": "ing-002", "standard_qty": "0.2", "waste_factor": "0"},
        ]
        price_map = {
            "ing-001": 2200,  # 实际采购价 22元/kg（比理论贵）
            "ing-002": 4800,  # 实际采购价 48元/kg（比理论便宜）
        }
        result = compute_actual_cost_from_prices(bom_items, price_map)
        # 0.5 * 2200 + 0.2 * 4800 = 1100 + 960 = 2060分
        assert result == 2060

    def test_actual_cost_with_waste(self):
        """含损耗的实际成本"""
        bom_items = [
            {"ingredient_id": "ing-001", "standard_qty": "1.0", "waste_factor": "0.15"},
        ]
        price_map = {"ing-001": 1000}
        result = compute_actual_cost_from_prices(bom_items, price_map)
        # 1.0 * (1+0.15) * 1000 = 1150
        assert result == 1150

    def test_actual_cost_missing_price(self):
        """价格缺失时该项成本为0"""
        bom_items = [
            {"ingredient_id": "ing-001", "standard_qty": "1.0", "waste_factor": "0"},
            {"ingredient_id": "ing-999", "standard_qty": "0.5", "waste_factor": "0"},
        ]
        price_map = {"ing-001": 1000}  # ing-999 无价格
        result = compute_actual_cost_from_prices(bom_items, price_map)
        assert result == 1000

    def test_actual_cost_empty_bom(self):
        """空 BOM 返回 0"""
        assert compute_actual_cost_from_prices([], {}) == 0

    def test_no_db_returns_zero(self):
        """无数据库连接时返回 0"""
        import uuid
        result = get_ingredient_actual_price(uuid.uuid4(), uuid.uuid4(), None)
        assert result == 0

        result2 = calculate_actual_dish_cost(uuid.uuid4(), uuid.uuid4(), None)
        assert result2 == 0


# ═══════════════════════════════════════════════
# 理论 vs 实际对比测试
# ═══════════════════════════════════════════════

class TestCostComparison:
    """理论成本与实际成本对比"""

    def test_theoretical_vs_actual_same_price(self):
        """价格一致时，理论成本 == 实际成本"""
        bom_items_for_theoretical = [
            {"standard_qty": "0.5", "waste_factor": "0.05", "unit_cost_fen": 2000},
        ]
        bom_items_for_actual = [
            {"ingredient_id": "ing-001", "standard_qty": "0.5", "waste_factor": "0.05"},
        ]
        price_map = {"ing-001": 2000}

        theo = compute_dish_theoretical_cost_from_bom(bom_items_for_theoretical)
        actual = compute_actual_cost_from_prices(bom_items_for_actual, price_map)
        assert theo == actual  # 都是 0.5 * 1.05 * 2000 = 1050

    def test_price_increase_raises_actual(self):
        """采购涨价导致实际成本 > 理论成本"""
        bom_items_theo = [
            {"standard_qty": "1.0", "waste_factor": "0", "unit_cost_fen": 1000},
        ]
        bom_items_actual = [
            {"ingredient_id": "ing-001", "standard_qty": "1.0", "waste_factor": "0"},
        ]
        price_map = {"ing-001": 1200}  # 涨了 20%

        theo = compute_dish_theoretical_cost_from_bom(bom_items_theo)
        actual = compute_actual_cost_from_prices(bom_items_actual, price_map)
        assert actual > theo
        assert actual - theo == 200  # 差 200分 = 2元
