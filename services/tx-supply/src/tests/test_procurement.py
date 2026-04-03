"""采购全流程测试"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.procurement_service import (
    approve_requisition,
    can_procurement_transition,
    create_purchase_order,
    create_requisition,
    inspect_and_stock,
    receive_delivery,
    reject_requisition,
    suggest_procurement,
)


class TestProcurementStateMachine:
    def test_draft_to_approval(self):
        assert can_procurement_transition("draft", "pending_approval")

    def test_approved_to_ordered(self):
        assert can_procurement_transition("approved", "ordered")

    def test_cannot_skip(self):
        assert not can_procurement_transition("draft", "ordered")

    def test_rejected_can_retry(self):
        assert can_procurement_transition("rejected", "draft")


class TestRequisition:
    def test_create(self):
        req = create_requisition("s1", "emp1", [
            {"ingredient_id": "i1", "name": "鲈鱼", "quantity": 10, "estimated_price_fen": 3500},
        ])
        assert req["requisition_no"].startswith("REQ")
        assert req["total_estimated_fen"] == 35000
        assert req["status"] == "draft"

    def test_approve(self):
        req = create_requisition("s1", "emp1", [])
        req["status"] = "pending_approval"
        approved = approve_requisition(req, "mgr1")
        assert approved["status"] == "approved"

    def test_reject(self):
        req = {"status": "pending_approval"}
        rejected = reject_requisition(req, "mgr1", "预算不足")
        assert rejected["status"] == "rejected"


class TestPurchaseOrder:
    def test_create_po(self):
        req = create_requisition("s1", "emp1", [{"ingredient_id": "i1", "name": "鲈鱼", "quantity": 10, "estimated_price_fen": 3500}])
        po = create_purchase_order(req, "sup1", "渔港供应商", "2026-04-01")
        assert po["po_no"].startswith("PO")
        assert po["status"] == "ordered"


class TestReceiveAndInspect:
    def test_receive(self):
        po = {"status": "ordered", "items": [{"quantity": 10}]}
        delivery = receive_delivery(po, [{"ingredient_id": "i1", "received_qty": 10, "quality": "pass"}])
        assert delivery["status"] == "received"
        assert delivery["shortage"] == 0

    def test_quality_issue(self):
        po = {"status": "ordered", "items": [{"quantity": 10}]}
        delivery = receive_delivery(po, [{"ingredient_id": "i1", "received_qty": 8, "quality": "fail", "notes": "不新鲜"}])
        assert len(delivery["quality_issues"]) == 1

    def test_inspect_pass(self):
        delivery = {"quality_issues": [], "status": "received"}
        result = inspect_and_stock(delivery, "ins1")
        assert result["status"] == "stocked"


class TestSuggestProcurement:
    def test_suggest(self):
        alerts = [
            {"item_name": "鲈鱼", "ingredient_id": "i1", "current_qty": 2, "min_qty": 5, "daily_usage": 3},
        ]
        prices = {"i1": {"supplier": "渔港", "price_fen": 3500}}
        suggestions = suggest_procurement(alerts, prices)
        assert len(suggestions) >= 1
        assert suggestions[0]["urgency"] == "urgent"
        assert suggestions[0]["estimated_cost_fen"] > 0
