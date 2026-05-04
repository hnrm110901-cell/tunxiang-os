"""
门店借调与成本分摊测试 -- store_transfer_service.py 纯函数测试
"""

import pytest
from services.store_transfer_service import (
    approve_transfer_order,
    compute_cost_split,
    compute_time_split,
    create_transfer_order,
    generate_cost_analysis_report,
    generate_detail_report,
    generate_summary_report,
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  借调单创建
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestCreateTransferOrder:
    """借调单创建"""

    def test_create_basic(self):
        """成功创建借调单"""
        order = create_transfer_order(
            employee_id="emp_001",
            employee_name="张三",
            from_store_id="store_a",
            from_store_name="长沙一店",
            to_store_id="store_b",
            to_store_name="长沙二店",
            start_date="2026-03-01",
            end_date="2026-03-31",
            reason="人手不足",
        )
        assert order["employee_id"] == "emp_001"
        assert order["status"] == "pending"
        assert order["from_store_id"] == "store_a"
        assert order["to_store_id"] == "store_b"
        assert order["reason"] == "人手不足"
        assert order["approved_by"] is None
        assert "id" in order

    def test_same_store_raises(self):
        """原门店与目标门店相同时报错"""
        with pytest.raises(ValueError, match="不能相同"):
            create_transfer_order(
                employee_id="emp_001",
                employee_name="张三",
                from_store_id="store_a",
                from_store_name="长沙一店",
                to_store_id="store_a",
                to_store_name="长沙一店",
                start_date="2026-03-01",
                end_date="2026-03-31",
            )

    def test_end_before_start_raises(self):
        """结束日期早于开始日期时报错"""
        with pytest.raises(ValueError, match="结束日期不能早于开始日期"):
            create_transfer_order(
                employee_id="emp_001",
                employee_name="张三",
                from_store_id="store_a",
                from_store_name="长沙一店",
                to_store_id="store_b",
                to_store_name="长沙二店",
                start_date="2026-03-31",
                end_date="2026-03-01",
            )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  借调单审批
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestApproveTransferOrder:
    """借调单审批"""

    def test_approve_pending(self):
        """审批待审核的借调单"""
        order = create_transfer_order(
            employee_id="emp_001",
            employee_name="张三",
            from_store_id="store_a",
            from_store_name="长沙一店",
            to_store_id="store_b",
            to_store_name="长沙二店",
            start_date="2026-03-01",
            end_date="2026-03-31",
        )
        approved = approve_transfer_order(order, "mgr_001")
        assert approved["status"] == "approved"
        assert approved["approved_by"] == "mgr_001"
        assert approved["approved_at"] is not None

    def test_approve_non_pending_raises(self):
        """审批非待审核状态的借调单报错"""
        order = create_transfer_order(
            employee_id="emp_001",
            employee_name="张三",
            from_store_id="store_a",
            from_store_name="长沙一店",
            to_store_id="store_b",
            to_store_name="长沙二店",
            start_date="2026-03-01",
            end_date="2026-03-31",
        )
        approved = approve_transfer_order(order, "mgr_001")
        with pytest.raises(ValueError, match="无法审批"):
            approve_transfer_order(approved, "mgr_002")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  工时拆分
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestComputeTimeSplit:
    """工时拆分"""

    def test_single_store_no_transfer(self):
        """无借调记录，工时全部归原门店"""
        transfers = []
        attendance = [
            {"employee_id": "emp_001", "date": "2026-03-01", "hours": 8, "store_id": "store_a"},
            {"employee_id": "emp_001", "date": "2026-03-02", "hours": 8, "store_id": "store_a"},
        ]
        result = compute_time_split(transfers, attendance)
        assert result == {"emp_001": {"store_a": 16.0}}

    def test_multi_store_with_transfer(self):
        """有借调记录，借调期间工时归入目标门店"""
        transfers = [
            {
                "employee_id": "emp_001",
                "from_store_id": "store_a",
                "to_store_id": "store_b",
                "start_date": "2026-03-10",
                "end_date": "2026-03-20",
            }
        ]
        attendance = [
            # 借调前 - 归 store_a
            {"employee_id": "emp_001", "date": "2026-03-05", "hours": 8, "store_id": "store_a"},
            # 借调期间 - 归 store_b
            {"employee_id": "emp_001", "date": "2026-03-15", "hours": 8, "store_id": "store_a"},
            # 借调后 - 归 store_a
            {"employee_id": "emp_001", "date": "2026-03-25", "hours": 8, "store_id": "store_a"},
        ]
        result = compute_time_split(transfers, attendance)
        assert result["emp_001"]["store_a"] == 16.0
        assert result["emp_001"]["store_b"] == 8.0

    def test_cross_month_transfer(self):
        """跨月借调：借调跨越月份边界"""
        transfers = [
            {
                "employee_id": "emp_001",
                "from_store_id": "store_a",
                "to_store_id": "store_b",
                "start_date": "2026-02-25",
                "end_date": "2026-03-10",
            }
        ]
        attendance = [
            # 2月25日 - 借调期内 → store_b
            {"employee_id": "emp_001", "date": "2026-02-25", "hours": 8, "store_id": "store_a"},
            # 3月5日 - 借调期内 → store_b
            {"employee_id": "emp_001", "date": "2026-03-05", "hours": 8, "store_id": "store_a"},
            # 3月15日 - 借调结束 → store_a
            {"employee_id": "emp_001", "date": "2026-03-15", "hours": 8, "store_id": "store_a"},
        ]
        result = compute_time_split(transfers, attendance)
        assert result["emp_001"]["store_b"] == 16.0
        assert result["emp_001"]["store_a"] == 8.0

    def test_boundary_dates_inclusive(self):
        """借调起止日期为闭区间"""
        transfers = [
            {
                "employee_id": "emp_001",
                "from_store_id": "store_a",
                "to_store_id": "store_b",
                "start_date": "2026-03-10",
                "end_date": "2026-03-10",
            }
        ]
        attendance = [
            {"employee_id": "emp_001", "date": "2026-03-09", "hours": 8, "store_id": "store_a"},
            {"employee_id": "emp_001", "date": "2026-03-10", "hours": 8, "store_id": "store_a"},
            {"employee_id": "emp_001", "date": "2026-03-11", "hours": 8, "store_id": "store_a"},
        ]
        result = compute_time_split(transfers, attendance)
        assert result["emp_001"]["store_a"] == 16.0
        assert result["emp_001"]["store_b"] == 8.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  成本分摊
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestComputeCostSplit:
    """成本分摊"""

    def test_proportional_split(self):
        """按工时比例分摊成本"""
        time_split = {
            "emp_001": {"store_a": 120.0, "store_b": 40.0},
        }
        salary_data = {
            "base_fen": 800_000,  # 8000 元
            "overtime_fen": 200_000,  # 2000 元
            "social_fen": 300_000,  # 3000 元
            "bonus_fen": 100_000,  # 1000 元
        }
        result = compute_cost_split(time_split, salary_data)
        emp = result["emp_001"]

        # store_a 占比 120/160 = 0.75, store_b 占比 40/160 = 0.25
        assert emp["store_a"]["ratio"] == 0.75
        assert emp["store_b"]["ratio"] == 0.25

        # wage = base + overtime = 1_000_000 分
        assert emp["store_a"]["wage_fen"] == 750_000
        assert emp["store_b"]["wage_fen"] == 250_000

        # social = 300_000
        assert emp["store_a"]["social_fen"] == 225_000
        assert emp["store_b"]["social_fen"] == 75_000

        # bonus = 100_000
        assert emp["store_a"]["bonus_fen"] == 75_000
        assert emp["store_b"]["bonus_fen"] == 25_000

        # total
        assert emp["store_a"]["total_fen"] == 750_000 + 225_000 + 75_000
        assert emp["store_b"]["total_fen"] == 250_000 + 75_000 + 25_000

    def test_rounding_largest_remainder(self):
        """最大余额法保证分摊总和精确等于原始总额"""
        # 10_000 分摊到 3 个门店，各占 1/3
        time_split = {
            "emp_001": {"store_a": 10.0, "store_b": 10.0, "store_c": 10.0},
        }
        salary_data = {
            "base_fen": 10_000,
            "overtime_fen": 0,
            "social_fen": 0,
            "bonus_fen": 0,
        }
        result = compute_cost_split(time_split, salary_data)
        emp = result["emp_001"]

        # 10000 / 3 = 3333.33... → 两个得 3333，一个得 3334
        wages = [emp[s]["wage_fen"] for s in ["store_a", "store_b", "store_c"]]
        assert sum(wages) == 10_000  # 总和精确
        assert sorted(wages) == [3333, 3333, 3334]  # 最大余额法

    def test_single_store_full_allocation(self):
        """单门店时全额分摊"""
        time_split = {"emp_001": {"store_a": 160.0}}
        salary_data = {
            "base_fen": 500_000,
            "overtime_fen": 100_000,
            "social_fen": 200_000,
            "bonus_fen": 50_000,
        }
        result = compute_cost_split(time_split, salary_data)
        emp = result["emp_001"]
        assert emp["store_a"]["wage_fen"] == 600_000
        assert emp["store_a"]["social_fen"] == 200_000
        assert emp["store_a"]["bonus_fen"] == 50_000
        assert emp["store_a"]["total_fen"] == 850_000
        assert emp["store_a"]["ratio"] == 1.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  三表生成
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestDetailReport:
    """明细分摊表"""

    def test_detail_report_structure(self):
        """明细报告包含正确结构"""
        time_split = {"store_a": 120.0, "store_b": 40.0}
        cost_split = {
            "store_a": {
                "wage_fen": 750_000,
                "social_fen": 225_000,
                "bonus_fen": 75_000,
                "total_fen": 1_050_000,
                "ratio": 0.75,
            },
            "store_b": {
                "wage_fen": 250_000,
                "social_fen": 75_000,
                "bonus_fen": 25_000,
                "total_fen": 350_000,
                "ratio": 0.25,
            },
        }
        report = generate_detail_report("emp_001", time_split, cost_split)

        assert report["employee_id"] == "emp_001"
        assert report["total_hours"] == 160.0
        assert report["total_cost_fen"] == 1_400_000
        assert len(report["stores"]) == 2
        assert report["stores"][0]["store_id"] == "store_a"
        assert report["stores"][0]["hours"] == 120.0


class TestSummaryReport:
    """薪资汇总表"""

    def test_summary_aggregation(self):
        """按门店汇总多个员工的成本"""
        all_emp = [
            {
                "employee_id": "emp_001",
                "cost_split": {
                    "store_a": {
                        "wage_fen": 750_000,
                        "social_fen": 225_000,
                        "bonus_fen": 75_000,
                        "total_fen": 1_050_000,
                    },
                    "store_b": {"wage_fen": 250_000, "social_fen": 75_000, "bonus_fen": 25_000, "total_fen": 350_000},
                },
            },
            {
                "employee_id": "emp_002",
                "cost_split": {
                    "store_a": {"wage_fen": 400_000, "social_fen": 100_000, "bonus_fen": 50_000, "total_fen": 550_000},
                },
            },
        ]
        report = generate_summary_report(all_emp)

        assert report["stores"]["store_a"]["employee_count"] == 2
        assert report["stores"]["store_a"]["total_wage_fen"] == 1_150_000
        assert report["stores"]["store_a"]["grand_total_fen"] == 1_600_000
        assert report["stores"]["store_b"]["employee_count"] == 1
        assert report["grand_total_fen"] == 1_950_000


class TestCostAnalysisReport:
    """成本分析表"""

    def test_variance_and_mom(self):
        """实际 vs 预算偏差 + 环比"""
        summary = {
            "stores": {
                "store_a": {
                    "employee_count": 2,
                    "total_wage_fen": 1_000_000,
                    "total_social_fen": 300_000,
                    "total_bonus_fen": 100_000,
                    "grand_total_fen": 1_400_000,
                },
            },
            "grand_total_fen": 1_400_000,
        }
        budget_data = {
            "store_a": {
                "budget_fen": 1_200_000,
                "last_period_fen": 1_300_000,
            },
        }
        report = generate_cost_analysis_report(summary, budget_data)

        sa = report["stores"]["store_a"]
        assert sa["actual_fen"] == 1_400_000
        assert sa["budget_fen"] == 1_200_000
        assert sa["variance_fen"] == 200_000  # 超预算 200_000
        # variance_rate = 200000 / 1200000 = 0.166667
        assert abs(sa["variance_rate"] - 200_000 / 1_200_000) < 0.0001
        # mom: (1400000 - 1300000) / 1300000
        assert sa["mom_change_fen"] == 100_000
        assert abs(sa["mom_rate"] - 100_000 / 1_300_000) < 0.0001

        assert report["total_actual_fen"] == 1_400_000
        assert report["total_budget_fen"] == 1_200_000
        assert report["total_variance_fen"] == 200_000
