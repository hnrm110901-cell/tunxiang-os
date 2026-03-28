"""部门领用测试"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from services.dept_issue import (
    create_issue_order,
    create_return_order,
    create_dept_transfer,
    check_yield_rate,
    sales_to_inventory,
    get_issue_flow,
    get_monthly_summary,
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  创建领用单
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestCreateIssueOrder:
    @pytest.mark.asyncio
    async def test_create_basic(self):
        items = [
            {"ingredient_id": "i1", "name": "鲈鱼", "quantity": 5, "unit": "kg", "unit_cost_fen": 3500},
            {"ingredient_id": "i2", "name": "虾", "quantity": 3, "unit": "kg", "unit_cost_fen": 5000},
        ]
        result = await create_issue_order("store_1", "kitchen", items, "emp_1", "t1", db=None)
        assert result["issue_id"].startswith("iss_")
        assert result["status"] == "issued"
        assert result["item_count"] == 2
        assert result["total_qty"] == 8
        assert result["total_cost_fen"] == 5 * 3500 + 3 * 5000
        assert result["dept_id"] == "kitchen"

    @pytest.mark.asyncio
    async def test_empty_items_raises(self):
        with pytest.raises(ValueError, match="至少一项"):
            await create_issue_order("store_1", "kitchen", [], "emp_1", "t1", db=None)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  领用退回
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestCreateReturnOrder:
    @pytest.mark.asyncio
    async def test_return_basic(self):
        items = [{"ingredient_id": "i1", "name": "鲈鱼", "quantity": 2, "reason": "多领"}]
        result = await create_return_order("iss_001", items, "t1", db=None)
        assert result["return_id"].startswith("iret_")
        assert result["status"] == "returned"
        assert result["total_return_qty"] == 2

    @pytest.mark.asyncio
    async def test_return_exceeds_issued_raises(self):
        issue = {"items": [{"ingredient_id": "i1", "quantity": 5}]}
        items = [{"ingredient_id": "i1", "quantity": 10}]
        with pytest.raises(ValueError, match="不能超过领用数量"):
            await create_return_order("iss_001", items, "t1", db=None, issue_order=issue)

    @pytest.mark.asyncio
    async def test_return_empty_raises(self):
        with pytest.raises(ValueError, match="至少一项"):
            await create_return_order("iss_001", [], "t1", db=None)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  部门间调拨
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestCreateDeptTransfer:
    @pytest.mark.asyncio
    async def test_transfer_basic(self):
        items = [{"ingredient_id": "i1", "name": "鲈鱼", "quantity": 3, "unit": "kg"}]
        result = await create_dept_transfer("kitchen", "bar", items, "t1", db=None)
        assert result["transfer_id"].startswith("dtf_")
        assert result["status"] == "pending"
        assert result["from_dept"] == "kitchen"
        assert result["to_dept"] == "bar"

    @pytest.mark.asyncio
    async def test_same_dept_raises(self):
        items = [{"ingredient_id": "i1", "quantity": 1}]
        with pytest.raises(ValueError, match="不能相同"):
            await create_dept_transfer("kitchen", "kitchen", items, "t1", db=None)

    @pytest.mark.asyncio
    async def test_empty_items_raises(self):
        with pytest.raises(ValueError, match="至少一项"):
            await create_dept_transfer("kitchen", "bar", [], "t1", db=None)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  出料率抽检
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestCheckYieldRate:
    @pytest.mark.asyncio
    async def test_normal_yield(self):
        result = await check_yield_rate(
            "dish_1", "store_1", "t1", db=None,
            actual_output=95, theoretical_output=100,
        )
        assert result["yield_rate"] == 0.95
        assert result["yield_percent"] == 95.0
        assert result["is_normal"] is True
        assert result["status"] == "normal"

    @pytest.mark.asyncio
    async def test_abnormal_yield(self):
        result = await check_yield_rate(
            "dish_1", "store_1", "t1", db=None,
            actual_output=80, theoretical_output=100,
        )
        assert result["yield_rate"] == 0.80
        assert result["is_normal"] is False
        assert result["status"] == "abnormal"

    @pytest.mark.asyncio
    async def test_zero_theoretical_raises(self):
        with pytest.raises(ValueError, match="大于0"):
            await check_yield_rate("dish_1", "store_1", "t1", db=None,
                                   actual_output=10, theoretical_output=0)

    @pytest.mark.asyncio
    async def test_negative_actual_raises(self):
        with pytest.raises(ValueError, match="不能为负"):
            await check_yield_rate("dish_1", "store_1", "t1", db=None,
                                   actual_output=-1, theoretical_output=100)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  销售转出库
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestSalesToInventory:
    @pytest.mark.asyncio
    async def test_sales_deduction(self):
        sales = [
            {
                "dish_id": "d1", "dish_name": "红烧鲈鱼", "quantity": 2,
                "ingredients": [
                    {"ingredient_id": "i1", "name": "鲈鱼", "qty_per_dish": 0.5, "unit": "kg"},
                    {"ingredient_id": "i2", "name": "酱油", "qty_per_dish": 0.05, "unit": "L"},
                ],
            },
            {
                "dish_id": "d2", "dish_name": "清蒸鲈鱼", "quantity": 1,
                "ingredients": [
                    {"ingredient_id": "i1", "name": "鲈鱼", "qty_per_dish": 0.6, "unit": "kg"},
                ],
            },
        ]
        result = await sales_to_inventory("store_1", "2026-03-27", "t1", db=None, sales_data=sales)
        assert result["status"] == "completed"
        assert result["sales_count"] == 2
        # i1: 2*0.5 + 1*0.6 = 1.6, i2: 2*0.05 = 0.1 → 合并后 2 项
        assert result["deduction_item_count"] == 2

    @pytest.mark.asyncio
    async def test_empty_sales(self):
        result = await sales_to_inventory("store_1", "2026-03-27", "t1", db=None, sales_data=[])
        assert result["sales_count"] == 0
        assert result["deduction_item_count"] == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  领用流水 + 月度汇总
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestFlowAndSummary:
    @pytest.mark.asyncio
    async def test_issue_flow(self):
        orders = [
            {"total_cost_fen": 10000, "total_qty": 5},
            {"total_cost_fen": 20000, "total_qty": 8},
        ]
        result = await get_issue_flow("store_1", "kitchen", ("2026-03-01", "2026-03-31"), "t1", db=None, issue_orders=orders)
        assert result["total_count"] == 2
        assert result["total_cost_fen"] == 30000
        assert result["total_qty"] == 13

    @pytest.mark.asyncio
    async def test_monthly_summary(self):
        orders = [
            {"dept_id": "kitchen", "total_cost_fen": 10000, "total_qty": 5},
            {"dept_id": "kitchen", "total_cost_fen": 20000, "total_qty": 8},
            {"dept_id": "bar", "total_cost_fen": 5000, "total_qty": 3},
        ]
        result = await get_monthly_summary("store_1", "2026-03", "t1", db=None, issue_orders=orders)
        assert result["total_orders"] == 3
        assert result["total_cost_fen"] == 35000
        assert len(result["dept_summary"]) == 2
