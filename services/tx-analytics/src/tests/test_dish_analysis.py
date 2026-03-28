"""菜品经营分析纯函数测试 — 销量排行、退菜率、四象限、优化建议"""
import sys
import os
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.dish_analysis import (
    compute_sales_ranking,
    compute_return_rate,
    classify_quadrant,
    generate_optimization_suggestion,
)


# ═══════════════════════════════════════════════
# 销量排行纯函数测试
# ═══════════════════════════════════════════════

class TestComputeSalesRanking:
    """测试菜品销量排行"""

    def test_ranking_by_qty_descending(self):
        """按销量降序排行"""
        dishes = [
            {"dish_id": "a", "dish_name": "宫保鸡丁", "sales_qty": 50, "sales_amount_fen": 250000},
            {"dish_id": "b", "dish_name": "鱼香肉丝", "sales_qty": 80, "sales_amount_fen": 320000},
            {"dish_id": "c", "dish_name": "麻婆豆腐", "sales_qty": 30, "sales_amount_fen": 120000},
        ]
        result = compute_sales_ranking(dishes, sort_by="sales_qty")
        assert result[0]["dish_name"] == "鱼香肉丝"
        assert result[0]["rank"] == 1
        assert result[2]["dish_name"] == "麻婆豆腐"
        assert result[2]["rank"] == 3

    def test_ranking_by_amount(self):
        """按金额排行"""
        dishes = [
            {"dish_id": "a", "dish_name": "A", "sales_qty": 100, "sales_amount_fen": 200000},
            {"dish_id": "b", "dish_name": "B", "sales_qty": 50, "sales_amount_fen": 500000},
        ]
        result = compute_sales_ranking(dishes, sort_by="sales_amount_fen")
        assert result[0]["dish_name"] == "B"
        assert result[0]["rank"] == 1

    def test_qty_pct_calculation(self):
        """销量占比计算"""
        dishes = [
            {"dish_id": "a", "dish_name": "A", "sales_qty": 60, "sales_amount_fen": 300000},
            {"dish_id": "b", "dish_name": "B", "sales_qty": 40, "sales_amount_fen": 200000},
        ]
        result = compute_sales_ranking(dishes)
        # A: 60/100 = 60%, B: 40/100 = 40%
        a = next(d for d in result if d["dish_name"] == "A")
        b = next(d for d in result if d["dish_name"] == "B")
        assert a["qty_pct"] == Decimal("60.00")
        assert b["qty_pct"] == Decimal("40.00")
        assert a["amount_pct"] == Decimal("60.00")
        assert b["amount_pct"] == Decimal("40.00")

    def test_empty_list(self):
        """空列表"""
        result = compute_sales_ranking([])
        assert result == []


# ═══════════════════════════════════════════════
# 退菜率计算测试
# ═══════════════════════════════════════════════

class TestComputeReturnRate:
    """测试退菜率计算"""

    def test_normal_return_rate(self):
        """正常退菜率：5/100 = 5%"""
        assert compute_return_rate(100, 5) == Decimal("5.00")

    def test_zero_total(self):
        """总量为0时退菜率为0"""
        assert compute_return_rate(0, 0) == Decimal("0.00")

    def test_high_return_rate(self):
        """高退菜率"""
        assert compute_return_rate(20, 8) == Decimal("40.00")

    def test_precision(self):
        """精度: 1/3 = 33.33%"""
        assert compute_return_rate(3, 1) == Decimal("33.33")


# ═══════════════════════════════════════════════
# 四象限分类测试
# ═══════════════════════════════════════════════

class TestClassifyQuadrant:
    """测试菜品四象限分类"""

    def test_star(self):
        """高销量 + 高毛利 = 明星"""
        q = classify_quadrant(
            sales_qty=100, margin_rate=Decimal("65.00"),
            sales_median=50, margin_threshold=Decimal("50.00"),
        )
        assert q == "star"

    def test_cash_cow(self):
        """低销量 + 高毛利 = 金牛"""
        q = classify_quadrant(
            sales_qty=20, margin_rate=Decimal("70.00"),
            sales_median=50, margin_threshold=Decimal("50.00"),
        )
        assert q == "cash_cow"

    def test_question(self):
        """高销量 + 低毛利 = 问号"""
        q = classify_quadrant(
            sales_qty=80, margin_rate=Decimal("30.00"),
            sales_median=50, margin_threshold=Decimal("50.00"),
        )
        assert q == "question"

    def test_dog(self):
        """低销量 + 低毛利 = 瘦狗"""
        q = classify_quadrant(
            sales_qty=10, margin_rate=Decimal("20.00"),
            sales_median=50, margin_threshold=Decimal("50.00"),
        )
        assert q == "dog"

    def test_boundary_star(self):
        """边界值：销量=中位数 且 毛利=阈值 → 明星（>=）"""
        q = classify_quadrant(
            sales_qty=50, margin_rate=Decimal("50.00"),
            sales_median=50, margin_threshold=Decimal("50.00"),
        )
        assert q == "star"


# ═══════════════════════════════════════════════
# 优化建议生成测试
# ═══════════════════════════════════════════════

class TestGenerateOptimizationSuggestion:
    """测试菜单优化建议生成"""

    def test_dog_with_high_return_rate_eliminate(self):
        """瘦狗 + 高退菜率 → 汰换"""
        dish = {"dish_id": "d1", "dish_name": "红烧蹄膀"}
        result = generate_optimization_suggestion(
            dish, quadrant="dog",
            return_rate=Decimal("8.00"), negative_review_count=1,
        )
        assert result["action"] == "eliminate"
        assert result["priority"] == "high"

    def test_dog_with_negative_reviews_eliminate(self):
        """瘦狗 + 多差评 → 汰换"""
        dish = {"dish_id": "d2", "dish_name": "糖醋排骨"}
        result = generate_optimization_suggestion(
            dish, quadrant="dog",
            return_rate=Decimal("2.00"), negative_review_count=5,
        )
        assert result["action"] == "eliminate"
        assert result["priority"] == "high"

    def test_dog_normal_observe(self):
        """瘦狗（无严重问题）→ 观察"""
        dish = {"dish_id": "d3", "dish_name": "凉拌木耳"}
        result = generate_optimization_suggestion(
            dish, quadrant="dog",
            return_rate=Decimal("1.00"), negative_review_count=0,
        )
        assert result["action"] == "observe"
        assert result["priority"] == "medium"

    def test_question_raise_price(self):
        """问号菜 → 提价"""
        dish = {"dish_id": "d4", "dish_name": "水煮鱼"}
        result = generate_optimization_suggestion(
            dish, quadrant="question",
            return_rate=Decimal("2.00"), negative_review_count=0,
        )
        assert result["action"] == "raise_price"
        assert result["priority"] == "high"

    def test_cash_cow_promote(self):
        """金牛菜 → 推广"""
        dish = {"dish_id": "d5", "dish_name": "佛跳墙"}
        result = generate_optimization_suggestion(
            dish, quadrant="cash_cow",
            return_rate=Decimal("0.00"), negative_review_count=0,
        )
        assert result["action"] == "promote"
        assert result["priority"] == "medium"

    def test_star_keep(self):
        """明星菜 → 保持"""
        dish = {"dish_id": "d6", "dish_name": "剁椒鱼头"}
        result = generate_optimization_suggestion(
            dish, quadrant="star",
            return_rate=Decimal("1.00"), negative_review_count=0,
        )
        assert result["action"] == "keep"
        assert result["priority"] == "low"
