"""配送调度路由测试 — delivery_dispatch_routes.py（v391 持久化版）

覆盖：
1. POST /dispatch — 自动选 provider 成功（mock repo + adapter）
2. POST /dispatch — 门店无可用 provider 返回 422
3. POST /dispatch — preferred_provider 指定 self_rider 走自有骑手
4. POST /dispatch/{id}/cancel — 已 dispatched 状态可取消
5. POST /dispatch/{id}/cancel — picked_up 状态返回 409
6. GET  /dispatch/{id}/track — 不存在返回 404
7. POST /dispatch/kds-ready — 触发 adapter.notify_pickup_ready，回写 kds_ready_at
8. POST /dispatch/kds-ready — 订单无自营 dispatch 时静默 200
9. PUT  /config — 优先级重复返回 422
10. tenant 不传 / 非 UUID 时返回 400
"""

from __future__ import annotations

import os
import sys
import types

# ─── 路径准备 ─────────────────────────────────────────────────────────────────
_TESTS_DIR = os.path.dirname(__file__)
_SRC_DIR = os.path.join(_TESTS_DIR, "..")
_ROOT_DIR = os.path.abspath(os.path.join(_TESTS_DIR, "..", "..", "..", ".."))
for _p in [_SRC_DIR, _ROOT_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _ensure_pkg(name: str, path: str) -> None:
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = [path]
        mod.__package__ = name
        sys.modules[name] = mod


_ensure_pkg("src", _SRC_DIR)
_ensure_pkg("src.api", os.path.join(_SRC_DIR, "api"))
_ensure_pkg("src.models", os.path.join(_SRC_DIR, "models"))
_ensure_pkg("src.services", os.path.join(_SRC_DIR, "services"))
_ensure_pkg("src.repositories", os.path.join(_SRC_DIR, "repositories"))
_ensure_pkg(
    "src.services.delivery_dispatch_adapters",
    os.path.join(_SRC_DIR, "services", "delivery_dispatch_adapters"),
)


import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.ontology.src.database import get_db
from src.api import delivery_dispatch_routes as routes
from src.api.delivery_dispatch_routes import router

TENANT_ID = "00000000-0000-0000-0000-000000000099"
STORE_ID = "store-test-001"
HEADERS = {"X-Tenant-ID": TENANT_ID}


# ─── 测试 App + DB override ─────────────────────────────────────────────────


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)

    async def _fake_db():
        # 路由本身只依赖 repository.* 的 staticmethod，不直接操作 session
        # 因此返回一个 AsyncMock 即可
        m = AsyncMock()
        yield m

    app.dependency_overrides[get_db] = _fake_db
    return app


@pytest.fixture
def client(monkeypatch):
    """每个用例独立 client + 重置 monkeypatch"""
    app = _build_app()
    return TestClient(app)


# ─── 测试用 DispatchModel / ConfigModel ──────────────────────────────────────


def _make_dispatch(
    *,
    dispatch_no: str = "DSP-TEST00000001",
    status: str = "dispatched",
    provider: str = "dada",
    provider_order_id: str | None = "DADA-XYZ123",
    kds_ready_at=None,
) -> MagicMock:
    d = MagicMock()
    d.id = uuid.uuid4()
    d.dispatch_no = dispatch_no
    d.tenant_id = uuid.UUID(TENANT_ID)
    d.store_id = STORE_ID
    d.order_id = "ORD-001"
    d.provider = provider
    d.provider_order_id = provider_order_id
    d.status = status
    d.rider_name = None
    d.rider_phone = None
    d.rider_lat = None
    d.rider_lng = None
    d.rider_updated_at = None
    d.delivery_address = "长沙市岳麓区测试路1号"
    d.delivery_lat = 28.2
    d.delivery_lng = 112.9
    d.distance_meters = 2500
    d.delivery_fee_fen = 600
    d.tip_fen = 200
    d.estimated_minutes = 25
    d.actual_minutes = None
    d.dispatched_at = datetime.now(timezone.utc)
    d.accepted_at = None
    d.picked_up_at = None
    d.delivered_at = None
    d.cancelled_at = None
    d.cancel_reason = None
    d.fail_reason = None
    d.kds_ready_at = kds_ready_at
    d.rider_notified_at = None
    d.created_at = datetime.now(timezone.utc)
    d.updated_at = datetime.now(timezone.utc)
    return d


def _make_config(provider: str = "dada", *, enabled: bool = True, priority: int = 0) -> MagicMock:
    c = MagicMock()
    c.id = uuid.uuid4()
    c.tenant_id = uuid.UUID(TENANT_ID)
    c.store_id = STORE_ID
    c.provider = provider
    c.enabled = enabled
    c.priority = priority
    c.app_key = "ak-x"
    c.app_secret = "sk-x-1234567890"
    c.merchant_id = "m-001"
    c.shop_no = "shop-001"
    c.callback_url = "https://example.com/cb"
    c.extra_config = {}
    return c


# ─── Tests ──────────────────────────────────────────────────────────────────


def test_create_dispatch_auto_select_success(client, monkeypatch):
    monkeypatch.setattr(
        routes.DeliveryProviderConfigRepository,
        "select_best_enabled",
        AsyncMock(return_value=_make_config("dada", enabled=True, priority=0)),
    )
    created = _make_dispatch()
    monkeypatch.setattr(
        routes.DeliveryDispatchRepository,
        "create",
        AsyncMock(return_value=created),
    )

    resp = client.post(
        "/api/v1/delivery/self/dispatch",
        headers=HEADERS,
        json={
            "order_id": "ORD-001",
            "store_id": STORE_ID,
            "delivery_address": "长沙市岳麓区测试路1号",
            "distance_meters": 2500,
            "delivery_fee_fen": 600,
            "tip_fen": 200,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["provider"] == "dada"
    assert body["data"]["status"] == "dispatched"
    assert body["data"]["id"] == "DSP-TEST00000001"


def test_create_dispatch_no_provider_returns_422(client, monkeypatch):
    monkeypatch.setattr(
        routes.DeliveryProviderConfigRepository,
        "select_best_enabled",
        AsyncMock(return_value=None),
    )
    resp = client.post(
        "/api/v1/delivery/self/dispatch",
        headers=HEADERS,
        json={
            "order_id": "ORD-001",
            "store_id": STORE_ID,
            "delivery_address": "长沙市岳麓区测试路1号",
        },
    )
    assert resp.status_code == 422, resp.text


def test_create_dispatch_preferred_self_rider(client, monkeypatch):
    # 没有配置时也允许 preferred_provider 走 mock adapter
    monkeypatch.setattr(
        routes.DeliveryProviderConfigRepository,
        "get_one",
        AsyncMock(return_value=None),
    )
    created = _make_dispatch(
        dispatch_no="DSP-SELF00000001",
        provider="self_rider",
        provider_order_id="SELF_RIDER-ABC123",
    )
    monkeypatch.setattr(
        routes.DeliveryDispatchRepository,
        "create",
        AsyncMock(return_value=created),
    )

    resp = client.post(
        "/api/v1/delivery/self/dispatch",
        headers=HEADERS,
        json={
            "order_id": "ORD-002",
            "store_id": STORE_ID,
            "delivery_address": "长沙市天心区测试路2号",
            "distance_meters": 1000,
            "preferred_provider": "self_rider",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["provider"] == "self_rider"


def test_cancel_dispatch_success(client, monkeypatch):
    d = _make_dispatch(status="dispatched")
    # 第一次 get：拿原始单；第二次 get：取消后重读
    cancelled = _make_dispatch(status="cancelled")
    cancelled.cancel_reason = "顾客取消"
    monkeypatch.setattr(
        routes.DeliveryDispatchRepository,
        "get",
        AsyncMock(side_effect=[d, cancelled]),
    )
    monkeypatch.setattr(
        routes.DeliveryProviderConfigRepository,
        "get_one",
        AsyncMock(return_value=_make_config("dada")),
    )
    monkeypatch.setattr(
        routes.DeliveryDispatchRepository,
        "cancel",
        AsyncMock(return_value=True),
    )

    resp = client.post(
        f"/api/v1/delivery/self/dispatch/{d.dispatch_no}/cancel",
        headers=HEADERS,
        json={"reason": "顾客取消"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data"]["status"] == "cancelled"
    assert body["data"]["cancel_reason"] == "顾客取消"


def test_cancel_after_picked_up_returns_409(client, monkeypatch):
    d = _make_dispatch(status="picked_up")
    monkeypatch.setattr(
        routes.DeliveryDispatchRepository, "get", AsyncMock(return_value=d)
    )
    resp = client.post(
        f"/api/v1/delivery/self/dispatch/{d.dispatch_no}/cancel",
        headers=HEADERS,
        json={"reason": "试图取消"},
    )
    assert resp.status_code == 409, resp.text


def test_track_dispatch_not_found_returns_404(client, monkeypatch):
    monkeypatch.setattr(
        routes.DeliveryDispatchRepository, "get", AsyncMock(return_value=None)
    )
    resp = client.get(
        "/api/v1/delivery/self/dispatch/DSP-NOTEXIST/track",
        headers=HEADERS,
    )
    assert resp.status_code == 404


def test_kds_ready_triggers_notify(client, monkeypatch):
    d = _make_dispatch(provider="self_rider", provider_order_id="SR-1", kds_ready_at=None)
    monkeypatch.setattr(
        routes.DeliveryDispatchRepository,
        "get_by_order",
        AsyncMock(return_value=d),
    )
    monkeypatch.setattr(
        routes.DeliveryProviderConfigRepository,
        "get_one",
        AsyncMock(return_value=None),
    )
    mark_ready = AsyncMock(return_value=True)
    mark_notified = AsyncMock(return_value=True)
    monkeypatch.setattr(routes.DeliveryDispatchRepository, "mark_kds_ready", mark_ready)
    monkeypatch.setattr(
        routes.DeliveryDispatchRepository, "mark_rider_notified", mark_notified
    )

    resp = client.post(
        "/api/v1/delivery/self/dispatch/kds-ready",
        headers=HEADERS,
        json={"order_id": "ORD-001"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data"]["notified"] is True
    assert body["data"]["provider"] == "self_rider"
    mark_ready.assert_awaited_once()
    mark_notified.assert_awaited_once()


def test_kds_ready_without_self_dispatch_returns_silent_ok(client, monkeypatch):
    monkeypatch.setattr(
        routes.DeliveryDispatchRepository,
        "get_by_order",
        AsyncMock(return_value=None),
    )
    resp = client.post(
        "/api/v1/delivery/self/dispatch/kds-ready",
        headers=HEADERS,
        json={"order_id": "ORD-NONE"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["notified"] is False


def test_update_config_duplicate_priority_returns_422(client):
    resp = client.put(
        "/api/v1/delivery/self/config",
        headers=HEADERS,
        json={
            "store_id": STORE_ID,
            "configs": [
                {"provider": "dada", "enabled": True, "priority": 0},
                {"provider": "shunfeng", "enabled": True, "priority": 0},
            ],
        },
    )
    assert resp.status_code == 422, resp.text


def test_invalid_tenant_uuid_returns_400(client):
    resp = client.post(
        "/api/v1/delivery/self/dispatch",
        headers={"X-Tenant-ID": "not-a-uuid"},
        json={
            "order_id": "ORD-x",
            "store_id": STORE_ID,
            "delivery_address": "test",
        },
    )
    assert resp.status_code == 400, resp.text


def test_missing_tenant_returns_422(client):
    resp = client.post(
        "/api/v1/delivery/self/dispatch",
        json={
            "order_id": "ORD-x",
            "store_id": STORE_ID,
            "delivery_address": "test",
        },
    )
    assert resp.status_code == 422  # FastAPI: missing required header
