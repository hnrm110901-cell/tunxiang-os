"""AI 薪资推荐路由层端到端测试 -- FastAPI TestClient

覆盖:
- Pydantic 校验边界 (min_length / ge / le / max_length)
- 成功路径响应结构
- HTTPException 不被吞成 500
- 批量 1001 条拒绝 (DoS 防护)
- 目录端点字段一致性
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.ai_salary_advisor_routes import router


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ── 成功路径 ─────────────────────────────────────────────────────


def test_recommend_success(client: TestClient):
    r = client.post("/api/v1/org/salary-advisor/recommend", json={
        "role": "店长",
        "region": "长沙",
        "years_of_service": 5,
        "store_monthly_revenue_fen": 100_000_00,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["role"] == "店长"
    assert data["role_tier"] == "L5_manager"
    assert data["region_code"] == "tier1_5"
    assert data["confidence"] == 0.90
    assert data["estimated_total_gross_fen"] > 0


def test_recommend_minimal_payload(client: TestClient):
    """最小合法 payload,只传 role"""
    r = client.post("/api/v1/org/salary-advisor/recommend", json={"role": "服务员"})
    assert r.status_code == 200
    assert r.json()["data"]["role_tier"] == "L1_basic"


# ── Pydantic 校验边界 ────────────────────────────────────────────


def test_recommend_empty_role_422(client: TestClient):
    r = client.post("/api/v1/org/salary-advisor/recommend", json={"role": ""})
    assert r.status_code == 422  # Pydantic min_length=1


def test_recommend_negative_years_422(client: TestClient):
    r = client.post("/api/v1/org/salary-advisor/recommend", json={
        "role": "服务员", "years_of_service": -1,
    })
    assert r.status_code == 422  # ge=0


def test_recommend_excessive_years_422(client: TestClient):
    r = client.post("/api/v1/org/salary-advisor/recommend", json={
        "role": "服务员", "years_of_service": 61,
    })
    assert r.status_code == 422  # le=60


def test_recommend_negative_revenue_422(client: TestClient):
    r = client.post("/api/v1/org/salary-advisor/recommend", json={
        "role": "服务员", "store_monthly_revenue_fen": -100,
    })
    assert r.status_code == 422  # ge=0


# ── 批量 ─────────────────────────────────────────────────────────


def test_batch_success(client: TestClient):
    r = client.post("/api/v1/org/salary-advisor/batch", json={
        "employees": [
            {"role": "服务员", "region": "tier2", "years_of_service": 0},
            {"role": "厨师", "region": "tier2", "years_of_service": 2},
        ],
        "store_monthly_revenue_fen": 80_000_00,
    })
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["summary"]["headcount"] == 2
    assert len(body["recommendations"]) == 2


def test_batch_empty_list_422(client: TestClient):
    """空列表违反 min_length=1"""
    r = client.post("/api/v1/org/salary-advisor/batch", json={"employees": []})
    assert r.status_code == 422


def test_batch_1001_rejected_422(client: TestClient):
    """DoS 防护:1001 条应被 Pydantic max_length=1000 拒绝"""
    r = client.post("/api/v1/org/salary-advisor/batch", json={
        "employees": [{"role": "服务员", "region": "tier2", "years_of_service": 0}] * 1001,
    })
    assert r.status_code == 422


def test_batch_1000_boundary_ok(client: TestClient):
    """1000 条边界内应接受"""
    r = client.post("/api/v1/org/salary-advisor/batch", json={
        "employees": [{"role": "服务员", "region": "tier2", "years_of_service": 0}] * 1000,
    })
    assert r.status_code == 200
    assert r.json()["data"]["summary"]["headcount"] == 1000


# ── 目录端点 ─────────────────────────────────────────────────────


def test_role_tiers_endpoint(client: TestClient):
    r = client.get("/api/v1/org/salary-advisor/role-tiers")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["count"] == 6
    tier_codes = {t["tier_code"] for t in data["tiers"]}
    assert tier_codes == {"L1_basic", "L2_skilled", "L3_senior_skilled",
                          "L4_supervisor", "L5_manager", "L6_regional"}
    # 字段命名:不得再暴露 tier2
    for t in data["tiers"]:
        assert "base_salary_fen_baseline" in t
        assert "base_salary_fen_tier2" not in t


def test_regions_endpoint(client: TestClient):
    r = client.get("/api/v1/org/salary-advisor/regions")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["count"] == 5
    tier1 = next(r for r in data["regions"] if r["region_code"] == "tier1")
    assert tier1["factor"] == 1.25


def test_seniority_curve_endpoint(client: TestClient):
    r = client.get("/api/v1/org/salary-advisor/seniority-curve")
    assert r.status_code == 200
    assert r.json()["data"]["count"] == 5


def test_health_endpoint(client: TestClient):
    r = client.get("/api/v1/org/salary-advisor/health")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["status"] == "ok"
    assert data["module"] == "ai_salary_advisor"
