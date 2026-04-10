"""AB测试 & ROI归因 API 路由测试

覆盖路由文件：
  - api/ab_test_routes.py      (8 个端点)
  - api/attribution_routes.py  (7 个端点)

测试场景：
1.  POST /api/v1/growth/ab-tests                   — 正常创建 AB 测试
2.  POST /api/v1/growth/ab-tests                   — weight 之和不等于 100 → ValueError 返回 ok=False
3.  POST /api/v1/growth/ab-tests                   — 只有一个变体 → ValueError
4.  GET  /api/v1/growth/ab-tests                   — 正常列表返回 items/total
5.  GET  /api/v1/growth/ab-tests/{id}              — 正常详情返回 ok=True
6.  POST /api/v1/growth/ab-tests/{id}/start        — 正常启动返回 status
7.  POST /api/v1/growth/ab-tests/{id}/pause        — 正常暂停返回 status
8.  POST /api/v1/growth/ab-tests/{id}/conclude     — 正常手动结论
9.  POST /api/v1/growth/ab-tests/{id}/apply-winner — 正常应用获胜变体
10. GET  /api/v1/growth/ab-tests/{id}/results      — 正常返回统计结果
11. GET  /api/v1/growth/attribution/dashboard       — 正常仪表盘返回
12. GET  /api/v1/growth/attribution/campaigns/{id}/roi — 正常活动 ROI
13. GET  /api/v1/growth/attribution/journeys/{id}/roi  — 正常旅程 ROI
14. GET  /api/v1/growth/attribution/funnel/{id}        — 正常漏斗
15. POST /api/v1/growth/attribution/touch              — 正常记录触达
16. POST /api/v1/growth/attribution/order              — 正常订单归因
17. GET  /api/v1/growth/attribution/top-performers     — 正常排名列表
18. POST /api/v1/growth/attribution/touch              — 非法 touch_type → 422
19. POST /api/v1/growth/attribution/order              — 负数 order_amount_fen → 422
20. GET  /api/v1/growth/attribution/dashboard          — 非法 X-Tenant-ID → 422
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import types
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

TENANT_ID = str(uuid.uuid4())
_HEADERS = {"X-Tenant-ID": TENANT_ID}

# ---------------------------------------------------------------------------
# Mock shared.ontology.src.database  (async_session_factory used by both files)
# ---------------------------------------------------------------------------

_fake_shared = types.ModuleType("shared")
_fake_ontology = types.ModuleType("shared.ontology")
_fake_src = types.ModuleType("shared.ontology.src")
_fake_database = types.ModuleType("shared.ontology.src.database")

# async_session_factory used by ab_test_routes + attribution_routes
_fake_session = AsyncMock()
_fake_session.commit = AsyncMock()
_fake_session.rollback = AsyncMock()

class _FakeSessionCtx:
    async def __aenter__(self):
        return _fake_session
    async def __aexit__(self, *_):
        pass

_fake_database.async_session_factory = MagicMock(return_value=_FakeSessionCtx())

sys.modules.setdefault("shared", _fake_shared)
sys.modules.setdefault("shared.ontology", _fake_ontology)
sys.modules.setdefault("shared.ontology.src", _fake_src)
sys.modules["shared.ontology.src.database"] = _fake_database

# ---------------------------------------------------------------------------
# Mock structlog
# ---------------------------------------------------------------------------
_fake_structlog = types.ModuleType("structlog")
_fake_structlog.get_logger = MagicMock(return_value=MagicMock(
    info=MagicMock(), warning=MagicMock(), error=MagicMock()
))
sys.modules.setdefault("structlog", _fake_structlog)


# ===========================================================================
# AB TEST ROUTES
# ===========================================================================

_ab_svc_mock = MagicMock()

with patch("services.ab_test_service.ABTestService", return_value=_ab_svc_mock):
    from api.ab_test_routes import router as ab_router, get_db as ab_get_db

ab_app = FastAPI()
ab_app.include_router(ab_router)

_ab_test_id = uuid.uuid4()

def _make_ab_db():
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db

def _ab_db_override(db):
    async def _dep():
        return db
    return _dep


# --- helpers ---

def _fake_test(status="draft"):
    t = MagicMock()
    t.id = _ab_test_id
    t.name = "价格AB测试"
    t.status = status
    t.split_type = "random"
    t.winner_variant = "A"
    t.started_at = datetime.now(timezone.utc)
    t.ended_at = datetime.now(timezone.utc)
    return t

_VALID_PAYLOAD = {
    "name": "价格AB测试",
    "split_type": "random",
    "variants": [
        {"variant": "A", "name": "控制组", "weight": 50, "content": {"title": "A"}},
        {"variant": "B", "name": "实验组", "weight": 50, "content": {"title": "B"}},
    ],
    "primary_metric": "conversion_rate",
    "min_sample_size": 100,
    "confidence_level": 0.95,
}

# ── Test 1: 正常创建 AB 测试 ────────────────────────────────────────────────

def test_create_ab_test_success():
    db = _make_ab_db()
    _ab_svc_mock.create_test = AsyncMock(return_value=_fake_test())
    ab_app.dependency_overrides[ab_get_db] = _ab_db_override(db)

    client = TestClient(ab_app)
    resp = client.post("/api/v1/growth/ab-tests", json=_VALID_PAYLOAD, headers=_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "test_id" in data["data"]
    assert data["data"]["status"] == "draft"

# ── Test 2: weight 之和不为 100 → ok=False ───────────────────────────────────

def test_create_ab_test_bad_weight():
    db = _make_ab_db()
    _ab_svc_mock.create_test = AsyncMock(side_effect=ValueError("weight 之和必须为 100"))
    ab_app.dependency_overrides[ab_get_db] = _ab_db_override(db)

    payload = dict(_VALID_PAYLOAD)
    payload["variants"] = [
        {"variant": "A", "name": "控制组", "weight": 60, "content": {}},
        {"variant": "B", "name": "实验组", "weight": 60, "content": {}},
    ]
    client = TestClient(ab_app)
    resp = client.post("/api/v1/growth/ab-tests", json=payload, headers=_HEADERS)
    # Pydantic validator should reject this
    assert resp.status_code == 422

# ── Test 3: 单变体 → 422 ─────────────────────────────────────────────────────

def test_create_ab_test_single_variant():
    db = _make_ab_db()
    ab_app.dependency_overrides[ab_get_db] = _ab_db_override(db)

    payload = dict(_VALID_PAYLOAD)
    payload["variants"] = [
        {"variant": "A", "name": "只有A", "weight": 100, "content": {}},
    ]
    client = TestClient(ab_app)
    resp = client.post("/api/v1/growth/ab-tests", json=payload, headers=_HEADERS)
    assert resp.status_code == 422

# ── Test 4: 列表返回 ──────────────────────────────────────────────────────────

def test_list_ab_tests():
    db = _make_ab_db()
    _ab_svc_mock.list_tests = AsyncMock(return_value=[
        {"id": str(_ab_test_id), "name": "测试1", "status": "draft"}
    ])
    ab_app.dependency_overrides[ab_get_db] = _ab_db_override(db)

    client = TestClient(ab_app)
    resp = client.get("/api/v1/growth/ab-tests", headers=_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["total"] == 1

# ── Test 5: 详情 ──────────────────────────────────────────────────────────────

def test_get_ab_test_detail():
    db = _make_ab_db()
    _ab_svc_mock.calculate_results = AsyncMock(return_value={"test_id": str(_ab_test_id)})
    ab_app.dependency_overrides[ab_get_db] = _ab_db_override(db)

    client = TestClient(ab_app)
    resp = client.get(f"/api/v1/growth/ab-tests/{_ab_test_id}", headers=_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

# ── Test 6: 启动测试 ──────────────────────────────────────────────────────────

def test_start_ab_test():
    db = _make_ab_db()
    _ab_svc_mock.start_test = AsyncMock(return_value=_fake_test("running"))
    ab_app.dependency_overrides[ab_get_db] = _ab_db_override(db)

    client = TestClient(ab_app)
    resp = client.post(f"/api/v1/growth/ab-tests/{_ab_test_id}/start", headers=_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "running"

# ── Test 7: 暂停测试 ──────────────────────────────────────────────────────────

def test_pause_ab_test():
    db = _make_ab_db()
    _ab_svc_mock.pause_test = AsyncMock(return_value=_fake_test("paused"))
    ab_app.dependency_overrides[ab_get_db] = _ab_db_override(db)

    client = TestClient(ab_app)
    resp = client.post(f"/api/v1/growth/ab-tests/{_ab_test_id}/pause", headers=_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "paused"

# ── Test 8: 手动结论 ──────────────────────────────────────────────────────────

def test_conclude_ab_test():
    db = _make_ab_db()
    _ab_svc_mock.conclude_test = AsyncMock(return_value=_fake_test("completed"))
    ab_app.dependency_overrides[ab_get_db] = _ab_db_override(db)

    client = TestClient(ab_app)
    resp = client.post(
        f"/api/v1/growth/ab-tests/{_ab_test_id}/conclude",
        json={"winner_variant": "A"},
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

# ── Test 9: 应用获胜变体 ──────────────────────────────────────────────────────

def test_apply_winner():
    db = _make_ab_db()
    _ab_svc_mock.apply_winner = AsyncMock(return_value={"applied": True, "winner": "A"})
    ab_app.dependency_overrides[ab_get_db] = _ab_db_override(db)

    client = TestClient(ab_app)
    resp = client.post(f"/api/v1/growth/ab-tests/{_ab_test_id}/apply-winner", headers=_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

# ── Test 10: 详细统计结果 ─────────────────────────────────────────────────────

def test_get_ab_results():
    db = _make_ab_db()
    _ab_svc_mock.calculate_results = AsyncMock(return_value={
        "test_id": str(_ab_test_id),
        "variants": {"A": {"conversion_rate": 0.12}, "B": {"conversion_rate": 0.15}},
        "p_value": 0.03,
        "is_significant": True,
    })
    ab_app.dependency_overrides[ab_get_db] = _ab_db_override(db)

    client = TestClient(ab_app)
    resp = client.get(f"/api/v1/growth/ab-tests/{_ab_test_id}/results", headers=_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True


# ===========================================================================
# ATTRIBUTION ROUTES
# ===========================================================================

_roi_svc_mock = MagicMock()

with patch("services.roi_attribution.ROIAttributionService", return_value=_roi_svc_mock):
    from api.attribution_routes import router as attr_router

attr_app = FastAPI()
attr_app.include_router(attr_router)

_CAMPAIGN_ID = str(uuid.uuid4())
_CUSTOMER_ID = str(uuid.uuid4())
_ORDER_ID = str(uuid.uuid4())

# ── Test 11: 仪表盘 ──────────────────────────────────────────────────────────

def test_attribution_dashboard():
    _roi_svc_mock.get_attribution_dashboard = AsyncMock(return_value={
        "total_touches": 1200,
        "total_conversions": 80,
        "total_revenue_fen": 960000,
        "average_roi": 3.2,
    })
    client = TestClient(attr_app)
    resp = client.get("/api/v1/growth/attribution/dashboard", headers=_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert "total_touches" in resp.json()["data"]

# ── Test 12: 活动 ROI ────────────────────────────────────────────────────────

def test_campaign_roi():
    _roi_svc_mock.calculate_campaign_roi = AsyncMock(return_value={
        "campaign_id": _CAMPAIGN_ID,
        "roi": 2.8,
        "revenue_fen": 280000,
        "cost_fen": 100000,
    })
    client = TestClient(attr_app)
    resp = client.get(
        f"/api/v1/growth/attribution/campaigns/{_CAMPAIGN_ID}/roi",
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["roi"] == 2.8

# ── Test 13: 旅程 ROI ────────────────────────────────────────────────────────

def test_journey_roi():
    journey_id = str(uuid.uuid4())
    _roi_svc_mock.calculate_journey_roi = AsyncMock(return_value={
        "journey_id": journey_id,
        "roi": 1.9,
    })
    client = TestClient(attr_app)
    resp = client.get(
        f"/api/v1/growth/attribution/journeys/{journey_id}/roi",
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

# ── Test 14: 转化漏斗 ────────────────────────────────────────────────────────

def test_conversion_funnel():
    source_id = str(uuid.uuid4())
    _roi_svc_mock.get_conversion_funnel = AsyncMock(return_value={
        "source_id": source_id,
        "steps": [
            {"name": "触达", "count": 500},
            {"name": "点击", "count": 200},
            {"name": "下单", "count": 50},
        ],
    })
    client = TestClient(attr_app)
    resp = client.get(
        f"/api/v1/growth/attribution/funnel/{source_id}",
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

# ── Test 15: 记录触达 ────────────────────────────────────────────────────────

def test_record_touch():
    touch_obj = MagicMock()
    touch_obj.id = uuid.uuid4()
    touch_obj.customer_id = uuid.UUID(_CUSTOMER_ID)
    touch_obj.source_id = _CAMPAIGN_ID
    touch_obj.channel = "sms"
    touch_obj.touched_at = datetime.now(timezone.utc)

    _roi_svc_mock.record_touch = AsyncMock(return_value=touch_obj)
    client = TestClient(attr_app)
    resp = client.post(
        "/api/v1/growth/attribution/touch",
        json={
            "customer_id": _CUSTOMER_ID,
            "touch_type": "campaign",
            "source_id": _CAMPAIGN_ID,
            "channel": "sms",
        },
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["channel"] == "sms"

# ── Test 16: 订单归因 ────────────────────────────────────────────────────────

def test_attribute_order():
    _roi_svc_mock.attribute_order = AsyncMock(return_value={
        "attributed": True,
        "touch_id": str(uuid.uuid4()),
        "model": "last_touch",
    })
    client = TestClient(attr_app)
    resp = client.post(
        "/api/v1/growth/attribution/order",
        json={
            "order_id": _ORDER_ID,
            "customer_id": _CUSTOMER_ID,
            "order_amount_fen": 8800,
            "model": "last_touch",
        },
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

# ── Test 17: 排名列表 ────────────────────────────────────────────────────────

def test_top_performers():
    _roi_svc_mock.get_top_performers = AsyncMock(return_value=[
        {"campaign_id": _CAMPAIGN_ID, "roi": 5.2, "name": "暑期大促"},
        {"campaign_id": str(uuid.uuid4()), "roi": 3.1, "name": "会员日"},
    ])
    client = TestClient(attr_app)
    resp = client.get(
        "/api/v1/growth/attribution/top-performers?limit=5&days=30",
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["total"] == 2

# ── Test 18: 非法 touch_type → 422 ──────────────────────────────────────────

def test_record_touch_bad_type():
    client = TestClient(attr_app)
    resp = client.post(
        "/api/v1/growth/attribution/touch",
        json={
            "customer_id": _CUSTOMER_ID,
            "touch_type": "invalid_type",
            "source_id": _CAMPAIGN_ID,
            "channel": "sms",
        },
        headers=_HEADERS,
    )
    assert resp.status_code == 422

# ── Test 19: 负数 order_amount_fen → 422 ────────────────────────────────────

def test_attribute_order_negative_amount():
    client = TestClient(attr_app)
    resp = client.post(
        "/api/v1/growth/attribution/order",
        json={
            "order_id": _ORDER_ID,
            "customer_id": _CUSTOMER_ID,
            "order_amount_fen": -100,
        },
        headers=_HEADERS,
    )
    assert resp.status_code == 422

# ── Test 20: 非法 X-Tenant-ID → 422 ─────────────────────────────────────────

def test_dashboard_bad_tenant_id():
    client = TestClient(attr_app)
    resp = client.get(
        "/api/v1/growth/attribution/dashboard",
        headers={"X-Tenant-ID": "not-a-uuid"},
    )
    assert resp.status_code == 422
