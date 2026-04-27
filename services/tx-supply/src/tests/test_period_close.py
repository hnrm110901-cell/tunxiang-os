"""月结与成本测试"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from services.period_close import (
    check_pending_documents,
    close_period,
    create_cost_adjustment,
    get_payable_summary,
    get_receipt_balance,
    reverse_close,
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  月结
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestClosePeriod:
    @pytest.mark.asyncio
    async def test_close_success(self):
        result = await close_period("store_1", "2026-03", "t1", db=None, pending_count=0)
        assert result["close_id"].startswith("close_")
        assert result["status"] == "closed"
        assert result["is_closed"] is True

    @pytest.mark.asyncio
    async def test_close_with_pending_raises(self):
        with pytest.raises(ValueError, match="未完成单据"):
            await close_period("store_1", "2026-03", "t1", db=None, pending_count=3)

    @pytest.mark.asyncio
    async def test_close_already_closed_raises(self):
        period = {"is_closed": True}
        with pytest.raises(ValueError, match="已完成月结"):
            await close_period("store_1", "2026-03", "t1", db=None, period_data=period)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  反月结
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestReverseClose:
    @pytest.mark.asyncio
    async def test_reverse_success(self):
        period = {"is_closed": True, "status": "closed"}
        result = await reverse_close("store_1", "2026-03", "t1", db=None, period_data=period)
        assert result["status"] == "reopened"
        assert result["is_closed"] is False
        assert period["is_closed"] is False

    @pytest.mark.asyncio
    async def test_reverse_not_closed_raises(self):
        period = {"is_closed": False}
        with pytest.raises(ValueError, match="尚未月结"):
            await reverse_close("store_1", "2026-03", "t1", db=None, period_data=period)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  成本调整
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestCreateCostAdjustment:
    @pytest.mark.asyncio
    async def test_adjustment_basic(self):
        items = [
            {"ingredient_id": "i1", "name": "鲈鱼", "old_cost_fen": 3500, "new_cost_fen": 3800, "reason": "涨价"},
        ]
        result = await create_cost_adjustment("store_1", items, "t1", db=None, month="2026-03")
        assert result["adjustment_id"].startswith("cadj_")
        assert result["status"] == "applied"
        assert result["total_diff_fen"] == 300

    @pytest.mark.asyncio
    async def test_adjustment_period_closed_raises(self):
        items = [{"ingredient_id": "i1", "old_cost_fen": 100, "new_cost_fen": 200}]
        with pytest.raises(ValueError, match="已月结"):
            await create_cost_adjustment(
                "store_1",
                items,
                "t1",
                db=None,
                period_closed=True,
                month="2026-03",
            )

    @pytest.mark.asyncio
    async def test_adjustment_empty_items_raises(self):
        with pytest.raises(ValueError, match="至少一项"):
            await create_cost_adjustment("store_1", [], "t1", db=None)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  未完成单据检查
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestCheckPendingDocuments:
    @pytest.mark.asyncio
    async def test_no_pending(self):
        docs = [
            {"doc_type": "purchase", "status": "completed"},
            {"doc_type": "issue", "status": "completed"},
        ]
        result = await check_pending_documents("store_1", "t1", db=None, documents=docs)
        assert result["pending_count"] == 0
        assert result["can_close"] is True

    @pytest.mark.asyncio
    async def test_has_pending(self):
        docs = [
            {"doc_type": "purchase", "status": "ordered"},
            {"doc_type": "issue", "status": "completed"},
            {"doc_type": "transfer", "status": "pending"},
        ]
        result = await check_pending_documents("store_1", "t1", db=None, documents=docs)
        assert result["pending_count"] == 2
        assert result["can_close"] is False
        assert result["type_summary"]["purchase"] == 1
        assert result["type_summary"]["transfer"] == 1


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  收发结存表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestGetReceiptBalance:
    @pytest.mark.asyncio
    async def test_balance_calculation(self):
        data = [
            {
                "ingredient_id": "i1",
                "name": "鲈鱼",
                "unit": "kg",
                "opening_qty": 100,
                "opening_cost_fen": 350000,
                "received_qty": 50,
                "received_cost_fen": 175000,
                "issued_qty": 80,
                "issued_cost_fen": 280000,
            },
        ]
        result = await get_receipt_balance("store_1", "2026-03", "t1", db=None, balance_data=data)
        assert result["item_count"] == 1
        item = result["items"][0]
        assert item["closing_qty"] == 70  # 100 + 50 - 80
        assert item["closing_cost_fen"] == 245000  # 350000 + 175000 - 280000
        assert result["summary"]["total_closing_fen"] == 245000

    @pytest.mark.asyncio
    async def test_empty_balance(self):
        result = await get_receipt_balance("store_1", "2026-03", "t1", db=None, balance_data=[])
        assert result["item_count"] == 0
        assert result["summary"]["total_closing_fen"] == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  应付账款
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestGetPayableSummary:
    @pytest.mark.asyncio
    async def test_payable_summary(self):
        data = [
            {
                "supplier_id": "s1",
                "supplier_name": "供应商A",
                "total_payable_fen": 100000,
                "paid_fen": 60000,
                "po_count": 3,
            },
            {
                "supplier_id": "s2",
                "supplier_name": "供应商B",
                "total_payable_fen": 50000,
                "paid_fen": 50000,
                "po_count": 2,
            },
        ]
        result = await get_payable_summary("store_1", "t1", db=None, payable_data=data)
        assert result["supplier_count"] == 2
        assert result["summary"]["total_payable_fen"] == 150000
        assert result["summary"]["total_paid_fen"] == 110000
        assert result["summary"]["total_outstanding_fen"] == 40000

    @pytest.mark.asyncio
    async def test_empty_payable(self):
        result = await get_payable_summary("store_1", "t1", db=None, payable_data=[])
        assert result["supplier_count"] == 0
        assert result["summary"]["total_outstanding_fen"] == 0
