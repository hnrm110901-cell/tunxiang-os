"""经营洞察API测试"""

import os
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.api.insights_routes import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)

HEADERS = {"X-Tenant-ID": "11111111-1111-1111-1111-111111111111"}


class TestStoreInsights:
    def test_get_all_stores(self):
        resp = client.get("/api/v1/analytics/store-insights?period=today", headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data["data"]["items"]) == 6

    def test_filter_by_region(self):
        resp = client.get("/api/v1/analytics/store-insights?period=today&region=长沙", headers=HEADERS)
        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        assert all(s["region"] == "长沙" for s in items)
        assert len(items) == 3

    def test_missing_tenant(self):
        resp = client.get("/api/v1/analytics/store-insights?period=today")
        assert resp.status_code == 400

    def test_store_fields(self):
        resp = client.get("/api/v1/analytics/store-insights", headers=HEADERS)
        item = resp.json()["data"]["items"][0]
        assert "store_id" in item
        assert "revenue_fen" in item
        assert "health_score" in item
        assert "gross_margin" in item
        assert isinstance(item["revenue_fen"], int)


class TestPeriodAnalysis:
    def test_get_periods(self):
        resp = client.get("/api/v1/analytics/period-analysis?store_id=s1", headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data["data"]["periods"]) == 3

    def test_period_names(self):
        resp = client.get("/api/v1/analytics/period-analysis?store_id=s1", headers=HEADERS)
        names = [p["period_name"] for p in resp.json()["data"]["periods"]]
        assert names == ["午餐", "晚餐", "夜宵"]

    def test_top_dishes_present(self):
        resp = client.get("/api/v1/analytics/period-analysis?store_id=s1", headers=HEADERS)
        period = resp.json()["data"]["periods"][0]
        assert len(period["top_dishes"]) >= 3
        assert "name" in period["top_dishes"][0]
        assert "count" in period["top_dishes"][0]

    def test_missing_store_id(self):
        resp = client.get("/api/v1/analytics/period-analysis", headers=HEADERS)
        assert resp.status_code == 422  # FastAPI validation error
