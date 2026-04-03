"""tx-member API 端点冒烟测试"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


class TestHealth:
    def test_health(self):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["ok"]


class TestCustomers:
    def test_list(self):
        r = client.get("/api/v1/member/customers?store_id=s1")
        assert r.json()["ok"]

    def test_create(self):
        r = client.post("/api/v1/member/customers", json={"phone": "138001", "source": "manual"})
        assert r.json()["ok"]

    def test_get(self):
        r = client.get("/api/v1/member/customers/c1")
        assert r.json()["ok"]


class TestRFM:
    def test_segments(self):
        r = client.get("/api/v1/member/rfm/segments?store_id=s1")
        assert r.json()["ok"]

    def test_at_risk(self):
        r = client.get("/api/v1/member/rfm/at-risk?store_id=s1")
        assert r.json()["ok"]


class TestCampaigns:
    def test_list(self):
        r = client.get("/api/v1/member/campaigns?store_id=s1")
        assert r.json()["ok"]

    def test_create(self):
        r = client.post("/api/v1/member/campaigns", json={"type": "reactivation"})
        assert r.json()["ok"]


class TestJourneys:
    def test_list(self):
        r = client.get("/api/v1/member/journeys?store_id=s1")
        assert r.json()["ok"]

    def test_trigger(self):
        r = client.post("/api/v1/member/journeys/trigger?customer_id=c1&journey_type=welcome")
        assert r.json()["ok"]

    def test_merge(self):
        r = client.post("/api/v1/member/customers/merge?primary_id=c1&secondary_id=c2")
        assert r.json()["ok"]
