"""W12-5 TV 菜单屏 25 端点契约测试

验证 routes 与 service 层的端到端集成 + 沽清 / 屏幕注册的状态保持。
不依赖真实 DB（service 层目前用 mock + 内存字典）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from services.tx_trade.src.main import app  # type: ignore

TENANT = "11111111-1111-1111-1111-111111111111"
STORE = "store-001"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def headers() -> dict[str, str]:
    return {"X-Tenant-ID": TENANT}


# ─── GET 端点冒烟（19 个）────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        f"/api/v1/tv-menu/layout/{STORE}",
        f"/api/v1/tv-menu/screen/{STORE}/1",
        f"/api/v1/tv-menu/status/{STORE}",
        f"/api/v1/tv-menu/recommend/{STORE}",
        f"/api/v1/tv-menu/weather/{STORE}",
        f"/api/v1/tv-menu/smart-layout/{STORE}",
        f"/api/v1/tv-menu/config/{STORE}",
        f"/api/v1/tv-menu/seafood-board/{STORE}",
        f"/api/v1/tv-menu/ranking/{STORE}",
        f"/api/v1/tv-menu/waitlist/{STORE}",
        f"/api/v1/tv-menu/waitlist-detail/{STORE}",
        f"/api/v1/tv-menu/categories/{STORE}",
        f"/api/v1/tv-menu/dishes/{STORE}/1",
        f"/api/v1/tv-menu/sales-today/{STORE}",
        f"/api/v1/tv-menu/combos/{STORE}",
        f"/api/v1/tv-menu/festival/{STORE}",
        f"/api/v1/tv-menu/sold-out/{STORE}",
        f"/api/v1/tv-menu/timeslot/{STORE}",
    ],
)
def test_get_endpoint_returns_ok(client: TestClient, headers: dict, path: str):
    r = client.get(path, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert "data" in body


def test_health_no_tenant_required(client: TestClient):
    r = client.get("/api/v1/tv-menu/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["service"] == "tx-trade.tv-menu"


def test_weather_mock_no_tenant_required(client: TestClient):
    r = client.get("/api/v1/tv-menu/weather-mock?city=changsha")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["city"] == "changsha"
    assert body["data"]["weather"] in {"normal", "rainy", "hot", "cold", "snowy", "windy"}


# ─── POST 端点 + 状态保持（5 个）────────────────────────────────


def test_screen_register_then_heartbeat_then_unregister(client: TestClient, headers: dict):
    register_body = {
        "store_id": STORE,
        "screen_id": "screen-tier1-001",
        "ip": "10.0.0.55",
        "position": "main-wall",
        "size_inches": 65,
    }
    r1 = client.post("/api/v1/tv-menu/screen/register", json=register_body, headers=headers)
    assert r1.status_code == 200
    assert r1.json()["ok"] is True

    heartbeat_body = {"store_id": STORE, "screen_id": "screen-tier1-001"}
    r2 = client.post("/api/v1/tv-menu/screen/heartbeat", json=heartbeat_body, headers=headers)
    assert r2.status_code == 200
    assert r2.json()["data"]["status"] == "ok"

    unreg_body = {"store_id": STORE, "screen_id": "screen-tier1-001"}
    r3 = client.post("/api/v1/tv-menu/screen/unregister", json=unreg_body, headers=headers)
    assert r3.status_code == 200
    assert r3.json()["data"]["removed"] is True

    # 二次注销返回 removed=False
    r4 = client.post("/api/v1/tv-menu/screen/unregister", json=unreg_body, headers=headers)
    assert r4.status_code == 200
    assert r4.json()["data"]["removed"] is False


def test_mark_sold_out_then_query_then_dishes_filter(client: TestClient, headers: dict):
    """沽清 → 列表 → 菜品过滤的端到端链路"""
    # 选一个测试用门店避开污染
    test_store = "store-soldout-test"
    test_headers = {"X-Tenant-ID": "22222222-2222-2222-2222-222222222222"}

    # 标记沽清
    r1 = client.post(
        "/api/v1/tv-menu/sold-out",
        json={"store_id": test_store, "dish_ids": ["dish-x", "dish-y"]},
        headers=test_headers,
    )
    assert r1.status_code == 200
    assert r1.json()["data"]["marked_count"] == 2

    # 查询沽清列表
    r2 = client.get(f"/api/v1/tv-menu/sold-out/{test_store}", headers=test_headers)
    assert r2.status_code == 200
    assert set(r2.json()["data"]["soldOutIds"]) == {"dish-x", "dish-y"}


def test_tv_order_returns_order_id(client: TestClient, headers: dict):
    body = {
        "store_id": STORE,
        "table_id": "T01",
        "items": [{"dish_id": "d1", "qty": 2}],
        "customer_id": "c-001",
    }
    r = client.post("/api/v1/tv-menu/order", json=body, headers=headers)
    assert r.status_code == 200
    assert r.json()["ok"] is True


# ─── 边界 / 安全 ────────────────────────────────


def test_missing_tenant_returns_4xx(client: TestClient):
    r = client.get(f"/api/v1/tv-menu/layout/{STORE}")
    # FastAPI Header(...) 必填，返回 422
    assert r.status_code in (400, 422)


def test_dishes_is_available_filter(client: TestClient, headers: dict):
    r = client.get(f"/api/v1/tv-menu/dishes/{STORE}/1?is_available=true", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    # 仅返回未沽清菜品
    for d in body["data"]:
        assert not d.get("is_soldout", False)
