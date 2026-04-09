"""运营Agent HTTP API 路由测试

测试 ops_agent_routes.py 的14个端点。
使用 FastAPI TestClient 进行集成测试。
"""
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Use absolute imports matching the package structure
from src.api.ops_agent_routes import router

from fastapi import FastAPI

app = FastAPI()
app.include_router(router)
client = TestClient(app)

HEADERS = {"X-Tenant-ID": "test-tenant"}


class TestQueueRoutes:
    def test_predict_wait(self):
        resp = client.post("/api/v1/agent/ops/queue/predict-wait", json={
            "store_id": "s1", "action": "predict_wait_time",
            "params": {"party_size": 4, "queue_position": 2, "matching_table_count": 3, "avg_turn_minutes": 45},
        }, headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["success"] is True

    def test_suggest_seating(self):
        resp = client.post("/api/v1/agent/ops/queue/suggest-seating", json={
            "store_id": "s1", "action": "suggest_seating",
            "params": {
                "party_size": 6,
                "available_tables": [
                    {"code": "A-01", "seat_capacity": 4},
                    {"code": "A-10", "seat_capacity": 8},
                ],
            },
        }, headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["data"]["success"] is True

    def test_auto_call(self):
        resp = client.post("/api/v1/agent/ops/queue/auto-call", json={
            "store_id": "s1", "action": "auto_call_next",
            "params": {
                "freed_table": {"code": "A-05", "seat_capacity": 4},
                "queue": [{"ticket_no": "Q001", "party_size": 3, "is_vip": False, "is_member": False}],
            },
        }, headers=HEADERS)
        assert resp.status_code == 200


class TestKitchenRoutes:
    def test_scan_overtime(self):
        resp = client.post("/api/v1/agent/ops/kitchen/scan-overtime", json={
            "store_id": "s1", "action": "scan",
            "params": {
                "pending_items": [{"dish_name": "口味虾", "elapsed_minutes": 30}],
                "threshold_minutes": 25,
            },
        }, headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["data"]["data"]["overtime_count"] == 1

    def test_rush(self):
        resp = client.post("/api/v1/agent/ops/kitchen/rush", json={
            "store_id": "s1", "action": "rush",
            "params": {"item": {"order_no": "O1", "dish_name": "鲈鱼", "table_no": "A01", "kitchen_station": "活鲜档"}},
        }, headers=HEADERS)
        assert resp.status_code == 200

    def test_bottleneck(self):
        resp = client.post("/api/v1/agent/ops/kitchen/bottleneck", json={
            "store_id": "s1", "action": "bottleneck",
            "params": {"station_stats": [
                {"station_name": "热菜档", "avg_serve_minutes": 22, "overtime_rate": 0.5, "pending_count": 10},
            ]},
        }, headers=HEADERS)
        assert resp.status_code == 200
        assert len(resp.json()["data"]["data"]["bottlenecks"]) == 1


class TestBillingRoutes:
    def test_detect_reverse(self):
        resp = client.post("/api/v1/agent/ops/billing/detect-reverse", json={
            "store_id": "s1", "action": "detect",
            "params": {"operator_id": "c1", "order_id": "o1", "reverse_count_today": 5, "reverse_amount_fen": 80000},
        }, headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["data"]["data"]["risk_level"] == "high"

    def test_scan_missing(self):
        resp = client.post("/api/v1/agent/ops/billing/scan-missing", json={
            "store_id": "s1", "action": "scan",
            "params": {
                "occupied_tables": [{"table_no": "A01", "status": "dining"}],
                "active_order_table_nos": [],
            },
        }, headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["data"]["data"]["missing_count"] == 1


class TestClosingRoutes:
    def test_pre_check(self):
        resp = client.post("/api/v1/agent/ops/closing/pre-check", json={
            "store_id": "s1", "action": "pre_check",
            "params": {
                "unsettled_order_count": 0, "shift_closed": True,
                "cash_variance_fen": 0, "checklist_completed": True,
                "occupied_table_count": 0, "pending_invoice_count": 0,
            },
        }, headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["data"]["data"]["can_close"] is True

    def test_validate_settlement(self):
        resp = client.post("/api/v1/agent/ops/closing/validate-settlement", json={
            "store_id": "s1", "action": "validate",
            "params": {
                "total_revenue_fen": 100000, "payment_sum_fen": 100000,
                "refund_total_fen": 0, "order_count": 10, "channel_order_sum": 10,
            },
        }, headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["data"]["data"]["passed"] is True


class TestGenericExecute:
    def test_execute_valid_agent(self):
        resp = client.post("/api/v1/agent/ops/execute", json={
            "agent_id": "queue_seating",
            "action": "match_table_type",
            "store_id": "s1",
            "params": {"party_size": 6},
        }, headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["data"]["data"]["recommended_type"] == "large"

    def test_execute_unknown_agent(self):
        resp = client.post("/api/v1/agent/ops/execute", json={
            "agent_id": "nonexistent",
            "action": "test",
            "store_id": "s1",
        }, headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["ok"] is False
