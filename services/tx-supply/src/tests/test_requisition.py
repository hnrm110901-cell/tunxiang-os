"""申购全流程测试"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from services.requisition import (
    approve_requisition,
    convert_to_purchase,
    create_replenishment,
    create_requisition,
    create_return_request,
    get_approval_log,
    get_requisition_flow,
    submit_for_approval,
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  创建申购单
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestCreateRequisition:
    @pytest.mark.asyncio
    async def test_create_basic(self):
        items = [
            {"ingredient_id": "i1", "name": "鲈鱼", "quantity": 10, "unit": "kg", "estimated_price_fen": 3500},
            {"ingredient_id": "i2", "name": "虾", "quantity": 5, "unit": "kg", "estimated_price_fen": 5000},
        ]
        result = await create_requisition("store_1", items, "emp_1", "t1", db=None)
        assert result["requisition_id"].startswith("req_")
        assert result["status"] == "draft"
        assert result["item_count"] == 2
        assert result["total_estimated_fen"] == 10 * 3500 + 5 * 5000
        assert result["tenant_id"] == "t1"

    @pytest.mark.asyncio
    async def test_empty_items_raises(self):
        with pytest.raises(ValueError, match="至少一项"):
            await create_requisition("store_1", [], "emp_1", "t1", db=None)

    @pytest.mark.asyncio
    async def test_approval_level_store(self):
        items = [{"ingredient_id": "i1", "quantity": 1, "estimated_price_fen": 100_000}]  # 1000元
        result = await create_requisition("store_1", items, "emp_1", "t1", db=None)
        assert result["approval_level"] == "store"

    @pytest.mark.asyncio
    async def test_approval_level_region(self):
        items = [{"ingredient_id": "i1", "quantity": 1, "estimated_price_fen": 1_000_000}]  # 10000元
        result = await create_requisition("store_1", items, "emp_1", "t1", db=None)
        assert result["approval_level"] == "region"

    @pytest.mark.asyncio
    async def test_approval_level_hq(self):
        items = [{"ingredient_id": "i1", "quantity": 1, "estimated_price_fen": 5_000_000}]  # 50000元
        result = await create_requisition("store_1", items, "emp_1", "t1", db=None)
        assert result["approval_level"] == "hq"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  自动补货
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestCreateReplenishment:
    @pytest.mark.asyncio
    async def test_replenishment_needed(self):
        inventory = [
            {"ingredient_id": "i1", "name": "鲈鱼", "current_qty": 2, "safety_qty": 10,
             "daily_usage": 5, "unit": "kg", "estimated_price_fen": 3500},
        ]
        result = await create_replenishment("store_1", "t1", db=None, inventory_data=inventory)
        assert result["requisition_id"] is not None
        assert result["source"] == "auto_replenishment"
        assert len(result["items"]) == 1
        assert result["items"][0]["quantity"] > 0

    @pytest.mark.asyncio
    async def test_replenishment_not_needed(self):
        inventory = [
            {"ingredient_id": "i1", "current_qty": 100, "safety_qty": 10, "daily_usage": 5},
        ]
        result = await create_replenishment("store_1", "t1", db=None, inventory_data=inventory)
        assert result["status"] == "not_needed"
        assert result["requisition_id"] is None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  提交审批
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestSubmitForApproval:
    @pytest.mark.asyncio
    async def test_submit_draft(self):
        req = {"status": "draft", "requisition_id": "req_001"}
        result = await submit_for_approval("req_001", "t1", db=None, requisition=req)
        assert req["status"] == "pending_approval"
        assert result["status"] == "pending_approval"

    @pytest.mark.asyncio
    async def test_submit_non_draft_raises(self):
        req = {"status": "approved", "requisition_id": "req_001"}
        with pytest.raises(ValueError, match="草稿状态"):
            await submit_for_approval("req_001", "t1", db=None, requisition=req)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  审批流 (按金额分级)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestApproveRequisition:
    @pytest.mark.asyncio
    async def test_store_level_approve(self):
        req = {"status": "pending_approval", "approval_level": "store", "approval_log": []}
        result = await approve_requisition(
            "req_001", "mgr_1", "approve", "t1", db=None,
            requisition=req, approver_role="store_manager",
        )
        assert req["status"] == "approved"
        assert result["decision"] == "approve"
        assert len(req["approval_log"]) == 1

    @pytest.mark.asyncio
    async def test_region_level_needs_escalation(self):
        req = {"status": "pending_approval", "approval_level": "region", "approval_log": []}
        result = await approve_requisition(
            "req_001", "mgr_1", "approve", "t1", db=None,
            requisition=req, approver_role="store_manager",
        )
        assert req["status"] == "store_approved"  # 未最终审批, 需区域

    @pytest.mark.asyncio
    async def test_region_manager_final_approve(self):
        req = {"status": "store_approved", "approval_level": "region", "approval_log": []}
        result = await approve_requisition(
            "req_001", "reg_1", "approve", "t1", db=None,
            requisition=req, approver_role="region_manager",
        )
        assert req["status"] == "approved"

    @pytest.mark.asyncio
    async def test_reject(self):
        req = {"status": "pending_approval", "approval_level": "store", "approval_log": []}
        result = await approve_requisition(
            "req_001", "mgr_1", "reject", "t1", db=None,
            requisition=req, approver_role="store_manager", comment="预算不足",
        )
        assert req["status"] == "rejected"
        assert req["rejection_reason"] == "预算不足"

    @pytest.mark.asyncio
    async def test_invalid_decision_raises(self):
        with pytest.raises(ValueError, match="approve 或 reject"):
            await approve_requisition("req_001", "mgr_1", "maybe", "t1", db=None)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  转采购订单
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestConvertToPurchase:
    @pytest.mark.asyncio
    async def test_convert_approved(self):
        req = {
            "status": "approved",
            "store_id": "store_1",
            "items": [{"ingredient_id": "i1", "quantity": 10}],
            "total_estimated_fen": 35000,
        }
        result = await convert_to_purchase(
            "req_001", "t1", db=None,
            requisition=req, supplier_id="sup_1", supplier_name="海鲜供应商",
        )
        assert result["po_id"].startswith("po_")
        assert result["requisition_id"] == "req_001"
        assert result["supplier_id"] == "sup_1"
        assert req["status"] == "converted"

    @pytest.mark.asyncio
    async def test_convert_non_approved_raises(self):
        req = {"status": "draft"}
        with pytest.raises(ValueError, match="已审批状态"):
            await convert_to_purchase("req_001", "t1", db=None, requisition=req)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  申退单
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestCreateReturnRequest:
    @pytest.mark.asyncio
    async def test_create_return(self):
        items = [{"ingredient_id": "i1", "name": "鲈鱼", "quantity": 3, "unit": "kg"}]
        result = await create_return_request("store_1", items, "质量不合格", "t1", db=None)
        assert result["return_id"].startswith("ret_")
        assert result["reason"] == "质量不合格"
        assert result["total_return_qty"] == 3

    @pytest.mark.asyncio
    async def test_empty_reason_raises(self):
        items = [{"ingredient_id": "i1", "quantity": 1}]
        with pytest.raises(ValueError, match="原因不能为空"):
            await create_return_request("store_1", items, "  ", "t1", db=None)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  审批日志 + 流水
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestApprovalLogAndFlow:
    @pytest.mark.asyncio
    async def test_approval_log(self):
        req = {"approval_log": [{"approver_id": "a1", "decision": "approve"}]}
        result = await get_approval_log("req_001", "t1", db=None, requisition=req)
        assert result["log_count"] == 1

    @pytest.mark.asyncio
    async def test_requisition_flow(self):
        reqs = [
            {"status": "approved", "total_estimated_fen": 10000},
            {"status": "draft", "total_estimated_fen": 5000},
        ]
        result = await get_requisition_flow("store_1", "t1", db=None, requisitions=reqs)
        assert result["total_count"] == 2
        assert result["total_estimated_fen"] == 15000
        assert result["status_summary"]["approved"] == 1
        assert result["status_summary"]["draft"] == 1
