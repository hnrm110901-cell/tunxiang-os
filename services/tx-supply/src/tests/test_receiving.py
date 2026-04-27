"""C5 收货验收 + 退货 + 调拨测试"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from services.receiving_service import (
    confirm_transfer,
    create_receiving,
    create_transfer,
    get_central_warehouse_stock,
    reject_item,
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  收货验收
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestCreateReceiving:
    @pytest.mark.asyncio
    async def test_all_pass(self):
        items = [
            {"ingredient_id": "i1", "name": "鲈鱼", "ordered_qty": 10, "received_qty": 10, "quality": "pass"},
            {"ingredient_id": "i2", "name": "虾", "ordered_qty": 5, "received_qty": 5, "quality": "pass"},
        ]
        result = await create_receiving("po_001", items, "emp_1", "t1", db=None)
        assert result["receiving_id"].startswith("rcv_")
        assert result["status"] == "accepted"
        assert result["all_pass"] is True
        assert result["shortage"] == 0
        assert result["total_received"] == 15

    @pytest.mark.asyncio
    async def test_partial_quality(self):
        items = [
            {"ingredient_id": "i1", "ordered_qty": 10, "received_qty": 8, "quality": "pass"},
            {"ingredient_id": "i2", "ordered_qty": 5, "received_qty": 5, "quality": "fail"},
        ]
        result = await create_receiving("po_002", items, "emp_1", "t1", db=None)
        assert result["status"] == "partial"
        assert result["all_pass"] is False
        assert result["quality_issue_count"] == 1
        assert result["shortage"] == 2


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  退货
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestRejectItem:
    @pytest.mark.asyncio
    async def test_reject_creates_record(self):
        result = await reject_item("rcv_001", "i2", "变质", 3.0, "t1", db=None)
        assert result["rejection_id"].startswith("rej_")
        assert result["quantity"] == 3.0
        assert result["reason"] == "变质"
        assert result["status"] == "pending_return"

    @pytest.mark.asyncio
    async def test_reject_zero_quantity_raises(self):
        with pytest.raises(ValueError, match="must be positive"):
            await reject_item("rcv_001", "i2", "坏了", 0, "t1", db=None)

    @pytest.mark.asyncio
    async def test_reject_negative_quantity_raises(self):
        with pytest.raises(ValueError, match="must be positive"):
            await reject_item("rcv_001", "i2", "坏了", -1, "t1", db=None)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  调拨
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestCreateTransfer:
    @pytest.mark.asyncio
    async def test_create_transfer(self):
        items = [{"ingredient_id": "i1", "name": "鲈鱼", "quantity": 5, "unit": "kg"}]
        result = await create_transfer("store_a", "store_b", items, "t1", db=None)
        assert result["transfer_id"].startswith("tf_")
        assert result["status"] == "pending"
        assert result["sender_confirmed"] is False
        assert result["receiver_confirmed"] is False
        assert result["item_count"] == 1

    @pytest.mark.asyncio
    async def test_same_store_raises(self):
        with pytest.raises(ValueError, match="same store"):
            await create_transfer("store_a", "store_a", [{"ingredient_id": "i1", "quantity": 1}], "t1", db=None)

    @pytest.mark.asyncio
    async def test_empty_items_raises(self):
        with pytest.raises(ValueError, match="at least one item"):
            await create_transfer("store_a", "store_b", [], "t1", db=None)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  调拨确认（双方确认制）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestConfirmTransfer:
    @pytest.mark.asyncio
    async def test_sender_confirm_only(self):
        transfer = {"status": "pending", "sender_confirmed": False, "receiver_confirmed": False}
        result = await confirm_transfer("tf_001", "emp_a", "t1", db=None, transfer=transfer, role="sender")
        assert transfer["sender_confirmed"] is True
        assert transfer["status"] == "sender_confirmed"
        assert transfer["receiver_confirmed"] is False

    @pytest.mark.asyncio
    async def test_both_confirm_completes(self):
        transfer = {"status": "pending", "sender_confirmed": False, "receiver_confirmed": False}
        await confirm_transfer("tf_001", "emp_a", "t1", db=None, transfer=transfer, role="sender")
        await confirm_transfer("tf_001", "emp_b", "t1", db=None, transfer=transfer, role="receiver")
        assert transfer["status"] == "completed"
        assert transfer["sender_confirmed"] is True
        assert transfer["receiver_confirmed"] is True

    @pytest.mark.asyncio
    async def test_completed_transfer_raises(self):
        transfer = {"status": "completed", "sender_confirmed": True, "receiver_confirmed": True}
        with pytest.raises(ValueError, match="already 'completed'"):
            await confirm_transfer("tf_001", "emp_a", "t1", db=None, transfer=transfer, role="sender")

    @pytest.mark.asyncio
    async def test_invalid_role_raises(self):
        with pytest.raises(ValueError, match="must be 'sender' or 'receiver'"):
            await confirm_transfer("tf_001", "emp_a", "t1", db=None, role="admin")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  中央仓库存
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestCentralWarehouseStock:
    @pytest.mark.asyncio
    async def test_stock_summary(self):
        stock = [
            {"ingredient_id": "i1", "name": "鲈鱼", "quantity": 100, "min_quantity": 20, "unit_price_fen": 3500},
            {"ingredient_id": "i2", "name": "虾", "quantity": 5, "min_quantity": 10, "unit_price_fen": 5000},
        ]
        result = await get_central_warehouse_stock("t1", db=None, stock_data=stock)
        assert result["summary"]["total_items"] == 2
        assert result["summary"]["low_stock_count"] == 1
        assert result["summary"]["total_value_fen"] == 100 * 3500 + 5 * 5000

    @pytest.mark.asyncio
    async def test_empty_stock(self):
        result = await get_central_warehouse_stock("t1", db=None, stock_data=[])
        assert result["summary"]["total_items"] == 0
        assert result["summary"]["low_stock_count"] == 0
        assert result["summary"]["total_value_fen"] == 0
