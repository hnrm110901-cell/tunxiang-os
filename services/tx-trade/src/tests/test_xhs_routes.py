"""小红书路由测试 — xhs_routes.py

覆盖场景（共 7 个）：
1. POST /api/v1/xhs/verify    — 正常核销：adapter 返回 verified=True
2. POST /api/v1/xhs/verify    — 核销失败：adapter 抛 ValueError，返回 ok=False
3. GET  /api/v1/xhs/verifications — 正常列表查询
4. POST /api/v1/xhs/poi/bind  — 正常绑定 POI，DB execute + commit 成功
5. GET  /api/v1/xhs/poi/{store_id} — 存在绑定记录时返回 ok=True
6. GET  /api/v1/xhs/poi/{store_id} — 无绑定时返回 ok=False
7. POST /webhook/xhs           — 接受任意 payload，返回 code=0
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.xhs_routes import router
from shared.ontology.src.database import get_db


# ─── 工具 ──────────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID  = str(uuid.uuid4())

_BASE_HEADERS = {
    "X-Tenant-ID": TENANT_ID,
}


def _make_db():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=AsyncMock())
    db.commit   = AsyncMock()
    db.refresh  = AsyncMock()
    return db


def _override_db(db):
    def _dep():
        return db
    return _dep


def _make_app(db):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = _override_db(db)
    return app


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 1: POST /api/v1/xhs/verify — 正常核销
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_verify_coupon_ok():
    """adapter.verify_and_record 返回 verified=True 时应返回 ok=True"""
    db = _make_db()

    mock_adapter = AsyncMock()
    mock_adapter.verify_and_record = AsyncMock(return_value={
        "verified": True,
        "coupon_code": "XHS20260101",
        "store_id": STORE_ID,
    })

    with patch(
        "shared.adapters.xiaohongshu.src.xhs_coupon_adapter.XHSCouponAdapter",
        return_value=mock_adapter,
    ):
        app = _make_app(db)
        client = TestClient(app)
        resp = client.post(
            "/api/v1/xhs/verify",
            json={
                "coupon_code": "XHS20260101",
                "store_id":    STORE_ID,
                "order_id":    str(uuid.uuid4()),
                "verified_by": "staff_001",
            },
            headers=_BASE_HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["verified"] is True
    # db.commit 应被调用
    db.commit.assert_awaited_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 2: POST /api/v1/xhs/verify — adapter 抛 ValueError，返回 ok=False
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_verify_coupon_adapter_error():
    """adapter 抛 ValueError 时应返回 ok=False，不抛 500"""
    db = _make_db()

    mock_adapter = AsyncMock()
    mock_adapter.verify_and_record = AsyncMock(
        side_effect=ValueError("券码已核销")
    )

    with patch(
        "shared.adapters.xiaohongshu.src.xhs_coupon_adapter.XHSCouponAdapter",
        return_value=mock_adapter,
    ):
        app = _make_app(db)
        client = TestClient(app)
        resp = client.post(
            "/api/v1/xhs/verify",
            json={
                "coupon_code": "EXPIRED001",
                "store_id":    STORE_ID,
            },
            headers=_BASE_HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "券码已核销" in body["error"]["message"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 3: GET /api/v1/xhs/verifications — 正常列表查询
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_list_verifications_ok():
    """list_verifications 正常返回 ok=True 和 items 列表"""
    db = _make_db()

    mock_adapter = AsyncMock()
    mock_adapter.list_verifications = AsyncMock(return_value={
        "items": [
            {"coupon_code": "XHS001", "status": "verified", "verified_at": "2026-07-01T10:00:00"},
        ],
        "total": 1,
        "page": 1,
        "size": 20,
    })

    with patch(
        "shared.adapters.xiaohongshu.src.xhs_coupon_adapter.XHSCouponAdapter",
        return_value=mock_adapter,
    ):
        app = _make_app(db)
        client = TestClient(app)
        resp = client.get(
            f"/api/v1/xhs/verifications?store_id={STORE_ID}&status=verified",
            headers=_BASE_HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 1
    assert len(body["data"]["items"]) == 1


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 4: POST /api/v1/xhs/poi/bind — 正常绑定 POI
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_bind_poi_ok():
    """绑定 POI 时 DB execute + commit 应被调用，返回 ok=True + status=bound"""
    db = _make_db()

    app = _make_app(db)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/xhs/poi/bind",
        json={
            "store_id":      STORE_ID,
            "xhs_poi_id":    "poi_xhs_12345",
            "xhs_shop_name": "徐记海鲜小红书门店",
        },
        headers=_BASE_HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "bound"
    assert body["data"]["xhs_poi_id"] == "poi_xhs_12345"
    # DB execute 应至少被调用两次（set_config + INSERT）
    assert db.execute.await_count >= 2
    db.commit.assert_awaited_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 5: GET /api/v1/xhs/poi/{store_id} — 存在绑定时返回 ok=True
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_get_poi_binding_found():
    """存在 POI 绑定记录时应返回 ok=True 及绑定信息"""
    db = _make_db()

    fake_mapping = MagicMock()
    fake_mapping.xhs_poi_id    = "poi_xhs_12345"
    fake_mapping.xhs_shop_name = "徐记海鲜小红书门店"
    fake_mapping.sync_status   = "synced"
    fake_mapping.last_synced_at = datetime(2026, 7, 1, 10, 0, 0, tzinfo=timezone.utc)

    set_cfg_result = MagicMock()
    query_result   = MagicMock()
    query_result.fetchone = MagicMock(return_value=fake_mapping)
    db.execute = AsyncMock(side_effect=[set_cfg_result, query_result])

    app = _make_app(db)
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/xhs/poi/{STORE_ID}",
        headers=_BASE_HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["xhs_poi_id"] == "poi_xhs_12345"
    assert body["data"]["sync_status"] == "synced"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 6: GET /api/v1/xhs/poi/{store_id} — 无绑定时返回 ok=False
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_get_poi_binding_not_found():
    """无 POI 绑定时应返回 ok=False"""
    db = _make_db()

    set_cfg_result = MagicMock()
    query_result   = MagicMock()
    query_result.fetchone = MagicMock(return_value=None)   # 无绑定
    db.execute = AsyncMock(side_effect=[set_cfg_result, query_result])

    app = _make_app(db)
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/xhs/poi/{STORE_ID}",
        headers=_BASE_HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "poi_not_bound" in body["error"]["message"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 7: POST /webhook/xhs — 接受任意 payload，返回 code=0
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_xhs_webhook_accepts_any_payload():
    """小红书 Webhook 无论 event_type 如何，均应返回 code=0, msg=ok"""
    db = _make_db()
    app = _make_app(db)
    client = TestClient(app)

    for event in ("order_verified", "order_refunded", "poi_updated", "unknown_event"):
        resp = client.post(
            "/webhook/xhs",
            json={"event_type": event, "data": {"key": "value"}},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["msg"] == "ok"
