"""菜品毛利 + 门店报表 + 成本偏差 纯函数测试"""

import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.cost_variance import (
    build_variance_report,
    classify_variance_cause,
    compute_dish_variance,
    generate_actions,
)
from services.dish_margin import (
    compute_margin,
    compute_margin_ranking,
    filter_low_margin,
)
from services.store_margin_report import (
    build_daily_report,
    compute_cost_variance,
    compute_margin_rate,
)

# ═══════════════════════════════════════════════
# 菜品毛利计算测试
# ═══════════════════════════════════════════════


class TestComputeMargin:
    """测试单品毛利计算"""

    def test_normal_margin(self):
        """正常毛利：售价100元，成本35元，毛利65%"""
        result = compute_margin(selling_price_fen=10000, cost_fen=3500)
        assert result["selling_price_fen"] == 10000
        assert result["cost_fen"] == 3500
        assert result["margin_fen"] == 6500
        assert result["margin_rate"] == Decimal("65.00")

    def test_zero_price(self):
        """售价为0时毛利率为0"""
        result = compute_margin(selling_price_fen=0, cost_fen=1000)
        assert result["margin_rate"] == Decimal("0.00")
        assert result["margin_fen"] == -1000

    def test_high_cost(self):
        """成本高于售价，负毛利"""
        result = compute_margin(selling_price_fen=5000, cost_fen=6000)
        assert result["margin_fen"] == -1000
        assert result["margin_rate"] == Decimal("-20.00")

    def test_zero_cost(self):
        """零成本，毛利100%"""
        result = compute_margin(selling_price_fen=5000, cost_fen=0)
        assert result["margin_fen"] == 5000
        assert result["margin_rate"] == Decimal("100.00")

    def test_margin_rate_precision(self):
        """毛利率精度到小数点后两位"""
        result = compute_margin(selling_price_fen=3000, cost_fen=1000)
        # (3000-1000)/3000 = 66.666...% → 66.67%
        assert result["margin_rate"] == Decimal("66.67")


class TestMarginRanking:
    """测试毛利排行"""

    def test_ranking_by_margin_rate(self):
        """按毛利率排行（默认降序）"""
        dishes = [
            {"dish_name": "A", "margin_rate": Decimal("50.00")},
            {"dish_name": "B", "margin_rate": Decimal("70.00")},
            {"dish_name": "C", "margin_rate": Decimal("30.00")},
        ]
        result = compute_margin_ranking(dishes)
        assert result[0]["dish_name"] == "B"
        assert result[0]["rank"] == 1
        assert result[2]["dish_name"] == "C"
        assert result[2]["rank"] == 3

    def test_filter_low_margin(self):
        """低毛利筛选"""
        dishes = [
            {"dish_name": "A", "margin_rate": Decimal("50.00")},
            {"dish_name": "B", "margin_rate": Decimal("25.00")},
            {"dish_name": "C", "margin_rate": Decimal("70.00")},
            {"dish_name": "D", "margin_rate": Decimal("15.00")},
        ]
        result = filter_low_margin(dishes, Decimal("30.00"))
        assert len(result) == 2
        names = {d["dish_name"] for d in result}
        assert names == {"B", "D"}


# ═══════════════════════════════════════════════
# 门店毛利日报测试
# ═══════════════════════════════════════════════


class TestStoreMarginReport:
    """测试门店日报纯函数"""

    def test_margin_rate_calculation(self):
        """毛利率计算"""
        assert compute_margin_rate(10000, 3500) == Decimal("65.00")
        assert compute_margin_rate(0, 1000) == Decimal("0.00")

    def test_cost_variance_ok(self):
        """成本偏差 <5% → ok"""
        result = compute_cost_variance(10000, 10200)
        assert result["status"] == "ok"
        assert result["variance_fen"] == 200

    def test_cost_variance_warning(self):
        """成本偏差 5-10% → warning"""
        result = compute_cost_variance(10000, 10700)
        assert result["status"] == "warning"
        assert result["variance_rate"] == Decimal("7.00")

    def test_cost_variance_critical(self):
        """成本偏差 >=10% → critical"""
        result = compute_cost_variance(10000, 11500)
        assert result["status"] == "critical"

    def test_build_daily_report_with_alerts(self):
        """日报构建：低毛利 + 成本偏差预警"""
        report = build_daily_report(
            store_id="store-001",
            report_date="2026-03-27",
            revenue_fen=100000,  # 1000元营收
            theoretical_cost_fen=35000,  # 350元理论成本
            actual_cost_fen=42000,  # 420元实际成本
            top_cost_dishes=[{"dish_name": "龙虾", "total_cost_fen": 15000}],
        )
        assert report["revenue_fen"] == 100000
        assert report["theoretical_margin_rate"] == Decimal("65.00")
        assert report["actual_margin_rate"] == Decimal("58.00")
        assert report["cost_variance_fen"] == 7000
        # 偏差 = 7000/35000 = 20% → critical
        assert report["cost_variance_status"] == "critical"
        # 实际毛利58% < 目标60% → 有低毛利预警
        assert any(a["type"] == "low_margin" for a in report["alerts"])
        assert any(a["type"] == "cost_variance" for a in report["alerts"])

    def test_build_report_healthy(self):
        """健康门店：无预警"""
        report = build_daily_report(
            store_id="store-002",
            report_date="2026-03-27",
            revenue_fen=100000,
            theoretical_cost_fen=30000,
            actual_cost_fen=31000,  # 偏差约3.3%
            top_cost_dishes=[],
        )
        assert report["cost_variance_status"] == "ok"
        assert report["actual_margin_rate"] == Decimal("69.00")
        # 毛利69% > 目标60%，偏差3.3% < 5% → 无预警
        assert len(report["alerts"]) == 0


# ═══════════════════════════════════════════════
# 成本偏差分析测试
# ═══════════════════════════════════════════════


class TestCostVariance:
    """测试成本偏差分析纯函数"""

    def test_dish_variance_positive(self):
        """实际超支"""
        result = compute_dish_variance("红烧肉", 1200, 1500, 10)
        assert result["variance_fen"] == 300
        assert result["total_variance_fen"] == 3000
        assert result["variance_rate_pct"] == Decimal("25.00")

    def test_dish_variance_negative(self):
        """实际低于理论（节省）"""
        result = compute_dish_variance("青菜", 800, 600, 20)
        assert result["variance_fen"] == -200
        assert result["total_variance_fen"] == -4000

    def test_classify_price_fluctuation(self):
        """价格波动归因"""
        cause = classify_variance_cause(Decimal("15.00"), price_changed=True)
        assert cause == "price_fluctuation"

    def test_classify_waste_excess(self):
        """损耗超标归因"""
        cause = classify_variance_cause(Decimal("8.00"), waste_above_target=True)
        assert cause == "waste_excess"

    def test_classify_recipe_deviation(self):
        """配方偏差（大幅偏差）"""
        cause = classify_variance_cause(Decimal("25.00"))
        assert cause == "recipe_deviation"

    def test_classify_over_portioning(self):
        """超量投料（中等偏差）"""
        cause = classify_variance_cause(Decimal("12.00"))
        assert cause == "over_portioning"

    def test_generate_actions(self):
        """生成建议动作"""
        actions = generate_actions(["price_fluctuation", "waste_excess", "price_fluctuation"])
        assert len(actions) == 2  # 去重
        causes = {a["cause"] for a in actions}
        assert "price_fluctuation" in causes
        assert "waste_excess" in causes
        assert all(a.get("action") for a in actions)  # 每个都有建议

    def test_build_variance_report(self):
        """组装偏差分析报告"""
        report = build_variance_report(
            store_id="store-001",
            report_date="2026-03-27",
            total_theoretical_fen=50000,
            total_actual_fen=55000,
            dish_variances=[
                {"dish_name": "A", "total_variance_fen": 3000, "cause": "price_fluctuation"},
                {"dish_name": "B", "total_variance_fen": 2000, "cause": "waste_excess"},
            ],
            ingredient_variances=[
                {"ingredient_name": "猪肉", "variance_fen": 2500, "cause": "price_fluctuation"},
            ],
        )
        assert report["total_variance_fen"] == 5000
        assert report["overall_variance_rate_pct"] == Decimal("10.00")
        assert len(report["top_dish_variances"]) == 2
        assert len(report["suggested_actions"]) == 2
