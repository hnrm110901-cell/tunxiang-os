"""薪资项目库测试 -- >=10 个测试用例"""

import os
import sys

# 确保 src 目录在导入路径中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from services.salary_item_library import (
    SALARY_ITEMS,
    compute_salary_by_items,
    get_all_items,
    get_categories,
    get_items_by_category,
    init_store_salary_config,
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. 项目库完整性
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestLibraryCompleteness:
    """测试项目库完整性"""

    def test_seven_categories_exist(self):
        """7大分类都存在"""
        expected = {"attendance", "overtime", "leave", "performance", "subsidy", "deduction", "social"}
        assert set(SALARY_ITEMS.keys()) == expected

    def test_total_items_at_least_66(self):
        """总项目数 >= 66"""
        all_items = get_all_items()
        assert len(all_items) >= 66, f"总项目数 {len(all_items)} 不足66"

    def test_item_codes_unique(self):
        """所有 item_code 不重复"""
        all_items = get_all_items()
        codes = [item.item_code for item in all_items]
        assert len(codes) == len(set(codes)), "存在重复的 item_code"

    def test_each_category_has_items(self):
        """每个分类至少有8个项目"""
        for cat, items in SALARY_ITEMS.items():
            assert len(items) >= 8, f"分类 {cat} 只有 {len(items)} 项，不足8"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. 按分类筛选
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestCategoryFilter:
    """测试按分类筛选"""

    def test_filter_attendance(self):
        """出勤类有10项"""
        items = get_items_by_category("attendance")
        assert len(items) == 10
        assert all(item.category == "attendance" for item in items)

    def test_filter_unknown_category_returns_empty(self):
        """未知分类返回空列表"""
        items = get_items_by_category("nonexistent")
        assert items == []

    def test_get_categories_returns_all(self):
        """get_categories 返回7个分类"""
        cats = get_categories()
        assert len(cats) == 7
        assert "attendance" in cats
        assert cats["attendance"] == "出勤类"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. 门店模板初始化
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestStoreTemplateInit:
    """测试3种模板初始化"""

    def test_standard_template(self):
        """标准中餐模板初始化"""
        config = init_store_salary_config("standard")
        assert config["template"] == "standard"
        assert config["template_name"] == "标准中餐"
        assert config["enabled_count"] > 0
        # 基本工资默认5000元 = 500000分
        base_items = [i for i in config["enabled_items"] if i["item_code"] == "ATT_001"]
        assert len(base_items) == 1
        assert base_items[0]["default_value_fen"] == 500000

    def test_seafood_template(self):
        """海鲜酒楼模板初始化"""
        config = init_store_salary_config("seafood")
        assert config["template"] == "seafood"
        assert config["template_name"] == "海鲜酒楼"
        # 海鲜酒楼项目多于标准中餐
        standard_config = init_store_salary_config("standard")
        assert config["enabled_count"] > standard_config["enabled_count"]

    def test_fast_food_template(self):
        """快餐模板初始化"""
        config = init_store_salary_config("fast_food")
        assert config["template"] == "fast_food"
        assert config["template_name"] == "快餐"
        # 快餐基本工资低于标准
        base_items = [i for i in config["enabled_items"] if i["item_code"] == "ATT_001"]
        assert base_items[0]["default_value_fen"] == 380000

    def test_invalid_template_raises(self):
        """无效模板抛出 ValueError"""
        with pytest.raises(ValueError, match="未知模板"):
            init_store_salary_config("invalid_type")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. 薪资计算
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestSalaryCompute:
    """测试薪资计算引擎"""

    def _standard_employee(self) -> dict:
        """标准员工数据"""
        return {
            "base_salary_fen": 500000,       # 5000元
            "attendance_days": 22,
            "work_days_in_month": 22,
            "weekday_ot_hours": 10,
            "weekend_ot_hours": 8,
            "holiday_ot_hours": 0,
            "personal_leave_days": 0,
            "sick_leave_days": 0,
            "late_count": 0,
            "late_deduction_per_time_fen": 5000,
            "early_leave_count": 0,
            "early_leave_deduction_per_time_fen": 5000,
            "absent_days": 0,
            "perf_coefficient": 120,         # 绩效1.2
            "sales_amount_fen": 10000000,    # 销售额10万
            "commission_rate": 0.02,         # 2%提成
            "full_attendance_bonus_fen": 30000,  # 全勤奖300元
            "seniority_months": 30,          # 工龄30个月
            "social_base_fen": 500000,
            "housing_fund_base_fen": 500000,
            "housing_fund_rate": 0.07,
            "meal_allowance_fen": 30000,
            "transport_allowance_fen": 20000,
            "month_index": 3,
            "cumulative_prev_taxable_income_yuan": 0,
            "cumulative_prev_tax_yuan": 0,
            "special_deduction_yuan": 0,
        }

    def _standard_enabled(self) -> list:
        """标准启用项"""
        return [
            "ATT_001", "ATT_005", "ATT_007",
            "OT_002", "OT_004", "OT_007",
            "PERF_002", "PERF_003", "PERF_006",
            "SUB_001", "SUB_002", "SUB_005",
            "DED_001", "DED_002",
            "SOC_001", "SOC_002", "SOC_003", "SOC_004",
        ]

    def test_basic_salary_compute(self):
        """基本+加班+绩效+扣款+社保完整计算"""
        data = self._standard_employee()
        enabled = self._standard_enabled()
        result = compute_salary_by_items(data, enabled)

        assert "items" in result
        assert "gross_fen" in result
        assert "tax_fen" in result
        assert "net_fen" in result
        assert result["gross_fen"] > 0
        assert result["net_fen"] > 0
        # 实发 = 应发 - 扣款 - 社保 - 个税
        assert result["net_fen"] == (
            result["gross_fen"]
            - result["total_deduction_fen"]
            - result["social_personal_fen"]
            - result["tax_fen"]
        )

    def test_full_attendance_bonus_awarded(self):
        """满勤员工获得全勤奖"""
        data = self._standard_employee()
        enabled = ["PERF_006"]
        result = compute_salary_by_items(data, enabled)
        perf_items = [i for i in result["items"] if i["item_code"] == "PERF_006"]
        assert len(perf_items) == 1
        assert perf_items[0]["amount_fen"] == 30000

    def test_full_attendance_bonus_denied_when_late(self):
        """有迟到时不发全勤奖"""
        data = self._standard_employee()
        data["late_count"] = 2
        enabled = ["PERF_006"]
        result = compute_salary_by_items(data, enabled)
        perf_items = [i for i in result["items"] if i["item_code"] == "PERF_006"]
        assert len(perf_items) == 1
        assert perf_items[0]["amount_fen"] == 0

    def test_overtime_calculation(self):
        """加班费计算正确"""
        data = self._standard_employee()
        data["weekday_ot_hours"] = 10
        data["weekend_ot_hours"] = 8
        enabled = ["OT_002", "OT_004", "OT_007"]
        result = compute_salary_by_items(data, enabled)

        ot_items = {i["item_code"]: i["amount_fen"] for i in result["items"]}
        assert "OT_002" in ot_items  # 工作日加班工资
        assert "OT_004" in ot_items  # 休息日加班工资
        assert "OT_007" in ot_items  # 加班合计
        assert ot_items["OT_007"] == ot_items["OT_002"] + ot_items["OT_004"]

    def test_social_insurance_deduction(self):
        """社保扣款计算正确"""
        data = self._standard_employee()
        data["social_base_fen"] = 500000  # 5000元基数
        enabled = ["SOC_001", "SOC_002", "SOC_003", "SOC_004"]
        result = compute_salary_by_items(data, enabled)

        soc_items = {i["item_code"]: i["amount_fen"] for i in result["items"]}
        # 养老 8% = 40000分
        assert soc_items["SOC_001"] == 40000
        # 医疗 2% = 10000分
        assert soc_items["SOC_002"] == 10000
        # 失业 0.5% = 2500分
        assert soc_items["SOC_003"] == 2500
        # 公积金 7% = 35000分
        assert soc_items["SOC_004"] == 35000

    def test_net_salary_after_tax(self):
        """税后工资验证：实发工资 > 0 且合理"""
        data = self._standard_employee()
        enabled = self._standard_enabled()
        result = compute_salary_by_items(data, enabled)

        # 应发 > 实发（有扣款和个税）
        assert result["gross_fen"] > result["net_fen"]
        # 实发为正
        assert result["net_fen"] > 0
        # 个税 >= 0
        assert result["tax_fen"] >= 0

    def test_seniority_subsidy(self):
        """工龄补贴阶梯测试"""
        data = self._standard_employee()
        data["seniority_months"] = 30  # 24-35月，应得100元/月
        enabled = ["SUB_005"]
        result = compute_salary_by_items(data, enabled)
        sub_items = [i for i in result["items"] if i["item_code"] == "SUB_005"]
        assert len(sub_items) == 1
        assert sub_items[0]["amount_fen"] == 10000  # 100元

    def test_deduction_with_late_and_absent(self):
        """迟到+旷工扣款组合测试"""
        data = self._standard_employee()
        data["late_count"] = 3
        data["absent_days"] = 1
        enabled = ["ATT_001", "DED_001", "DED_003"]
        result = compute_salary_by_items(data, enabled)

        ded_items = {i["item_code"]: i["amount_fen"] for i in result["items"]}
        # 迟到3次 x 50元 = 15000分
        assert ded_items["DED_001"] == 15000
        # 旷工1天 x 日薪 x 3
        daily = 500000 // 22
        expected_absent = int(daily * 1 * 3)
        assert ded_items["DED_003"] == expected_absent

    def test_empty_enabled_items(self):
        """无启用项目时返回零"""
        data = self._standard_employee()
        result = compute_salary_by_items(data, [])
        assert result["gross_fen"] == 0
        assert result["net_fen"] == 0
        assert result["tax_fen"] == 0
        assert result["items"] == []
