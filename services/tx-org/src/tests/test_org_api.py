"""tx-org API 端点冒烟测试"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


class TestHealth:
    def test_health(self):
        r = client.get("/health")
        assert r.status_code == 200


class TestEmployees:
    def test_list(self):
        r = client.get("/api/v1/org/employees?store_id=s1")
        assert r.json()["ok"]

    def test_create(self):
        r = client.post("/api/v1/org/employees", json={"emp_name": "张三", "role": "waiter", "store_id": "s1"})
        assert r.json()["ok"]

    def test_get(self):
        r = client.get("/api/v1/org/employees/e1")
        assert r.json()["ok"]

    def test_performance(self):
        r = client.get("/api/v1/org/employees/e1/performance")
        assert r.json()["ok"]


class TestSchedule:
    def test_get(self):
        r = client.get("/api/v1/org/schedule/?store_id=s1")
        assert r.json()["ok"]

    def test_generate(self):
        r = client.post("/api/v1/org/schedule/generate?store_id=s1&week=2026-W13")
        assert r.json()["ok"]

    def test_staffing_needs(self):
        r = client.get("/api/v1/org/schedule/staffing-needs?store_id=s1&date=2026-03-23")
        assert r.json()["ok"]

    def test_fairness(self):
        r = client.get("/api/v1/org/schedule/fairness?store_id=s1")
        assert r.json()["ok"]


class TestLaborCost:
    def test_labor_cost(self):
        r = client.get("/api/v1/org/labor-cost?store_id=s1")
        assert r.json()["ok"]

    def test_ranking(self):
        r = client.get("/api/v1/org/labor-cost/ranking")
        assert r.json()["ok"]


class TestOther:
    def test_attendance(self):
        r = client.get("/api/v1/org/attendance?store_id=s1")
        assert r.json()["ok"]

    def test_turnover_risk(self):
        r = client.get("/api/v1/org/turnover-risk?store_id=s1")
        assert r.json()["ok"]

    def test_hierarchy(self):
        r = client.get("/api/v1/org/hierarchy")
        assert r.json()["ok"]

    def test_skill_gaps(self):
        r = client.get("/api/v1/org/employees/e1/skill-gaps")
        assert r.json()["ok"]
