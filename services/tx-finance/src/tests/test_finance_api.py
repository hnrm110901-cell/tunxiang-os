"""tx-finance API 端点冒烟测试"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


class TestHealth:
    def test_health(self):
        r = client.get("/health")
        assert r.status_code == 200


class TestFinanceEndpoints:
    def test_daily_profit(self):
        r = client.get("/api/v1/finance/daily-profit?store_id=s1")
        assert r.json()["ok"]

    def test_cost_rate(self):
        r = client.get("/api/v1/finance/cost-rate?store_id=s1")
        assert r.json()["ok"]

    def test_cost_ranking(self):
        r = client.get("/api/v1/finance/cost-rate/ranking")
        assert r.json()["ok"]

    def test_fct_report(self):
        r = client.get("/api/v1/finance/fct/report?store_id=s1")
        assert r.json()["ok"]

    def test_fct_dashboard(self):
        r = client.get("/api/v1/finance/fct/dashboard?store_id=s1")
        assert r.json()["ok"]

    def test_budget(self):
        r = client.get("/api/v1/finance/budget?store_id=s1")
        assert r.json()["ok"]

    def test_cashflow(self):
        r = client.get("/api/v1/finance/cashflow/forecast?store_id=s1")
        assert r.json()["ok"]

    def test_monthly_report(self):
        r = client.get("/api/v1/finance/reports/monthly/s1")
        assert r.json()["ok"]

    def test_invoice(self):
        r = client.post("/api/v1/finance/invoice?order_id=o1", json={"buyer_name": "test"})
        assert r.json()["ok"]
