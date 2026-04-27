"""tx-trade 拼团 + 扫码点餐 路由层测试

覆盖文件：
  - src/api/group_buy_routes.py   (7 个端点)
  - src/api/scan_order_api.py     (8 个端点)

测试共 18 个（group_buy: 10, scan_order: 8）

场景清单：
  group_buy:
    1.  POST /activities            — 创建活动 happy path
    2.  POST /activities            — ValueError → 返回 ok=False
    3.  GET  /activities            — 列表 happy path
    4.  POST /teams                 — 发起拼团 happy path
    5.  POST /teams                 — ValueError → 返回 ok=False
    6.  POST /teams/{id}/join       — 参与拼团 happy path
    7.  POST /teams/{id}/join       — ValueError → 返回 ok=False
    8.  GET  /teams/{id}            — 拼团详情 happy path
    9.  GET  /teams/{id}            — team_not_found
    10. POST /expire-check          — 超时处理 happy path

  scan_order:
    11. POST /qrcode/generate       — 生成桌码 happy path
    12. POST /qrcode/parse          — 解析桌码 happy path
    13. POST /qrcode/parse          — ValueError → 400
    14. POST /create                — 扫码下单 happy path
    15. POST /add-items             — 加菜 happy path
    16. GET  /table-order           — 查看当桌订单 happy path
    17. POST /checkout              — 请求结账 happy path
    18. GET  /stats                 — 统计 happy path
"""

import os
import sys
import types
import uuid

# ─── sys.path 准备 ───────────────────────────────────────────────────────────
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
_ensure_pkg("src.services", os.path.join(_SRC_DIR, "services"))

# ─── shared.ontology mock（scan_order_api 使用 shared.ontology.src.database） ─
_shared_pkg = types.ModuleType("shared")
_shared_pkg.__path__ = [os.path.join(_ROOT_DIR, "shared")]
sys.modules.setdefault("shared", _shared_pkg)

for _mod in ("shared.ontology", "shared.ontology.src", "shared.ontology.src.database"):
    sys.modules.setdefault(_mod, types.ModuleType(_mod))


# 向 shared.ontology.src.database 注入 get_db
async def _fake_get_db():  # type: ignore[return]
    yield None


_db_mod = sys.modules["shared.ontology.src.database"]
_db_mod.get_db = _fake_get_db  # type: ignore[attr-defined]

# ─── group_buy_service mock ──────────────────────────────────────────────────
_svc_mod = types.ModuleType("src.services.group_buy_service")
sys.modules.setdefault("src.services.group_buy_service", _svc_mod)

# ─── scan_order_service mock ─────────────────────────────────────────────────
_scan_svc = types.ModuleType("src.services.scan_order_service")
sys.modules.setdefault("src.services.scan_order_service", _scan_svc)

# ─── structlog mock ──────────────────────────────────────────────────────────
import types as _types

_structlog = _types.ModuleType("structlog")
_structlog.get_logger = lambda *a, **kw: _types.SimpleNamespace(  # type: ignore[attr-defined]
    info=lambda *a, **k: None,
    warning=lambda *a, **k: None,
    error=lambda *a, **k: None,
)
sys.modules.setdefault("structlog", _structlog)

# ─── 正式 import ─────────────────────────────────────────────────────────────
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.ontology.src.database import get_db as shared_get_db  # type: ignore[import]
from src.api import scan_order_api  # type: ignore[import]
from src.api.group_buy_routes import get_db as gb_get_db  # type: ignore[import]
from src.api.group_buy_routes import router as gb_router  # type: ignore[import]
from src.api.scan_order_api import router as so_router  # type: ignore[import]

# ─── 常量 ────────────────────────────────────────────────────────────────────
TENANT = "tenant-abc"
STORE = "store-001"
ACTIVITY_ID = str(uuid.uuid4())
TEAM_ID = str(uuid.uuid4())
ORDER_ID = str(uuid.uuid4())

_BASE_HEADERS = {"X-Tenant-ID": TENANT}


# ─── 工具函数 ─────────────────────────────────────────────────────────────────


def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.commit = AsyncMock()
    return db


def _make_gb_app(db: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.include_router(gb_router)
    app.dependency_overrides[gb_get_db] = lambda: db
    return app


def _make_so_app(db: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.include_router(so_router)
    app.dependency_overrides[shared_get_db] = lambda: db
    return app


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP BUY ROUTES — group_buy_routes.py
# ═══════════════════════════════════════════════════════════════════════════════

# ── 1. POST /activities — happy path ─────────────────────────────────────────


def test_create_activity_happy_path():
    db = _make_db()
    activity_data = {"id": ACTIVITY_ID, "name": "双人拼团优惠", "status": "active"}
    with patch(
        "src.api.group_buy_routes.group_buy_service.create_activity",
        new=AsyncMock(return_value=activity_data),
    ):
        client = TestClient(_make_gb_app(db))
        resp = client.post(
            "/api/v1/group-buy/activities",
            json={
                "name": "双人拼团优惠",
                "product_id": "dish-001",
                "product_name": "酸菜鱼",
                "original_price_fen": 8800,
                "group_price_fen": 6600,
            },
            headers=_BASE_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["id"] == ACTIVITY_ID


# ── 2. POST /activities — ValueError ─────────────────────────────────────────


def test_create_activity_value_error():
    db = _make_db()
    with patch(
        "src.api.group_buy_routes.group_buy_service.create_activity",
        new=AsyncMock(side_effect=ValueError("group_price must be less than original_price")),
    ):
        client = TestClient(_make_gb_app(db))
        resp = client.post(
            "/api/v1/group-buy/activities",
            json={
                "name": "错误活动",
                "product_id": "dish-001",
                "product_name": "酸菜鱼",
                "original_price_fen": 5000,
                "group_price_fen": 8000,
            },
            headers=_BASE_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "group_price" in body["error"]["message"]


# ── 3. GET /activities — 列表 ────────────────────────────────────────────────


def test_list_activities_happy_path():
    db = _make_db()
    list_data = {"items": [{"id": ACTIVITY_ID}], "total": 1}
    with patch(
        "src.api.group_buy_routes.group_buy_service.list_activities",
        new=AsyncMock(return_value=list_data),
    ):
        client = TestClient(_make_gb_app(db))
        resp = client.get(
            "/api/v1/group-buy/activities",
            headers=_BASE_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 1


# ── 4. POST /teams — 发起拼团 happy path ─────────────────────────────────────


def test_create_team_happy_path():
    db = _make_db()
    team_data = {"team_id": TEAM_ID, "status": "open", "members": 1}
    with patch(
        "src.api.group_buy_routes.group_buy_service.create_team",
        new=AsyncMock(return_value=team_data),
    ):
        client = TestClient(_make_gb_app(db))
        resp = client.post(
            "/api/v1/group-buy/teams",
            json={"activity_id": ACTIVITY_ID, "initiator_id": "cust-001"},
            headers=_BASE_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["team_id"] == TEAM_ID


# ── 5. POST /teams — ValueError ──────────────────────────────────────────────


def test_create_team_value_error():
    db = _make_db()
    with patch(
        "src.api.group_buy_routes.group_buy_service.create_team",
        new=AsyncMock(side_effect=ValueError("activity_not_found")),
    ):
        client = TestClient(_make_gb_app(db))
        resp = client.post(
            "/api/v1/group-buy/teams",
            json={"activity_id": "bad-id", "initiator_id": "cust-001"},
            headers=_BASE_HEADERS,
        )
    assert resp.status_code == 200
    assert resp.json()["ok"] is False


# ── 6. POST /teams/{id}/join — happy path ────────────────────────────────────


def test_join_team_happy_path():
    db = _make_db()
    join_data = {"team_id": TEAM_ID, "members": 2, "status": "open"}
    with patch(
        "src.api.group_buy_routes.group_buy_service.join_team",
        new=AsyncMock(return_value=join_data),
    ):
        client = TestClient(_make_gb_app(db))
        resp = client.post(
            f"/api/v1/group-buy/teams/{TEAM_ID}/join",
            json={"customer_id": "cust-002"},
            headers=_BASE_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["members"] == 2


# ── 7. POST /teams/{id}/join — ValueError ────────────────────────────────────


def test_join_team_value_error():
    db = _make_db()
    with patch(
        "src.api.group_buy_routes.group_buy_service.join_team",
        new=AsyncMock(side_effect=ValueError("team_already_full")),
    ):
        client = TestClient(_make_gb_app(db))
        resp = client.post(
            f"/api/v1/group-buy/teams/{TEAM_ID}/join",
            json={"customer_id": "cust-003"},
            headers=_BASE_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "team_already_full" in body["error"]["message"]


# ── 8. GET /teams/{id} — 拼团详情 happy path ─────────────────────────────────


def test_get_team_detail_happy_path():
    db = _make_db()
    detail = {"team_id": TEAM_ID, "members": ["cust-001"], "status": "open"}
    with patch(
        "src.api.group_buy_routes.group_buy_service.get_team_detail",
        new=AsyncMock(return_value=detail),
    ):
        client = TestClient(_make_gb_app(db))
        resp = client.get(
            f"/api/v1/group-buy/teams/{TEAM_ID}",
            headers=_BASE_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["team_id"] == TEAM_ID


# ── 9. GET /teams/{id} — team not found ──────────────────────────────────────


def test_get_team_detail_not_found():
    db = _make_db()
    with patch(
        "src.api.group_buy_routes.group_buy_service.get_team_detail",
        new=AsyncMock(return_value=None),
    ):
        client = TestClient(_make_gb_app(db))
        resp = client.get(
            "/api/v1/group-buy/teams/non-existent",
            headers=_BASE_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["message"] == "team_not_found"


# ── 10. POST /expire-check — happy path ──────────────────────────────────────


def test_expire_check_happy_path():
    db = _make_db()
    result = {"expired_count": 3, "refunded_count": 3}
    with patch(
        "src.api.group_buy_routes.group_buy_service.expire_teams",
        new=AsyncMock(return_value=result),
    ):
        client = TestClient(_make_gb_app(db))
        resp = client.post(
            "/api/v1/group-buy/expire-check",
            headers=_BASE_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["expired_count"] == 3


# ═══════════════════════════════════════════════════════════════════════════════
# SCAN ORDER API — scan_order_api.py
# ═══════════════════════════════════════════════════════════════════════════════

# ── 11. POST /qrcode/generate — happy path ────────────────────────────────────


def test_generate_qrcode_happy_path():
    db = _make_db()
    qr_data = {"code": "TX:store001:T03:abc123", "miniapp_path": "/pages/menu/index?code=abc123"}
    with patch.object(scan_order_api, "generate_table_qrcode", return_value=qr_data):
        client = TestClient(_make_so_app(db))
        resp = client.post(
            "/api/v1/scan-order/qrcode/generate",
            json={"store_id": STORE, "table_id": "T03"},
            headers=_BASE_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "code" in body["data"]


# ── 12. POST /qrcode/parse — happy path ──────────────────────────────────────


def test_parse_qrcode_happy_path():
    db = _make_db()
    parse_data = {"store_short_code": "store001", "table_id": "T03"}
    with patch.object(scan_order_api, "parse_qrcode", return_value=parse_data):
        client = TestClient(_make_so_app(db))
        resp = client.post(
            "/api/v1/scan-order/qrcode/parse",
            json={"code": "TX:store001:T03:abc123"},
            headers=_BASE_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["table_id"] == "T03"


# ── 13. POST /qrcode/parse — ValueError → 400 ────────────────────────────────


def test_parse_qrcode_invalid():
    db = _make_db()
    with patch.object(scan_order_api, "parse_qrcode", side_effect=ValueError("invalid_qrcode_format")):
        client = TestClient(_make_so_app(db))
        resp = client.post(
            "/api/v1/scan-order/qrcode/parse",
            json={"code": "INVALID"},
            headers=_BASE_HEADERS,
        )
    assert resp.status_code == 400


# ── 14. POST /create — 扫码下单 happy path ────────────────────────────────────


def test_create_scan_order_happy_path():
    db = _make_db()
    order_data = {"order_id": ORDER_ID, "status": "open", "items_count": 2}
    with patch.object(scan_order_api, "create_scan_order", new=AsyncMock(return_value=order_data)):
        client = TestClient(_make_so_app(db))
        resp = client.post(
            "/api/v1/scan-order/create",
            json={
                "store_id": STORE,
                "table_id": "T05",
                "items": [
                    {"dish_id": "dish-001", "quantity": 2},
                    {"dish_id": "dish-002", "quantity": 1},
                ],
            },
            headers=_BASE_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["order_id"] == ORDER_ID


# ── 15. POST /add-items — 加菜 happy path ─────────────────────────────────────


def test_add_items_happy_path():
    db = _make_db()
    result = {"order_id": ORDER_ID, "added_items": 1, "total_items": 3}
    with patch.object(scan_order_api, "add_items_to_order", new=AsyncMock(return_value=result)):
        client = TestClient(_make_so_app(db))
        resp = client.post(
            "/api/v1/scan-order/add-items",
            json={
                "order_id": ORDER_ID,
                "items": [{"dish_id": "dish-003", "quantity": 1}],
            },
            headers=_BASE_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["added_items"] == 1


# ── 16. GET /table-order — 查看当桌订单 ──────────────────────────────────────


def test_get_table_order_happy_path():
    db = _make_db()
    table_order = {"order_id": ORDER_ID, "status": "open", "items": []}
    with patch.object(scan_order_api, "get_table_order", new=AsyncMock(return_value=table_order)):
        client = TestClient(_make_so_app(db))
        resp = client.get(
            "/api/v1/scan-order/table-order",
            params={"store_id": STORE, "table_id": "T05"},
            headers=_BASE_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["order_id"] == ORDER_ID


# ── 17. POST /checkout — 请求结账 ─────────────────────────────────────────────


def test_request_checkout_happy_path():
    db = _make_db()
    checkout_data = {"order_id": ORDER_ID, "status": "checkout_requested"}
    with patch.object(scan_order_api, "request_checkout", new=AsyncMock(return_value=checkout_data)):
        client = TestClient(_make_so_app(db))
        resp = client.post(
            "/api/v1/scan-order/checkout",
            json={"order_id": ORDER_ID},
            headers=_BASE_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "checkout_requested"


# ── 18. GET /stats — 统计 happy path ─────────────────────────────────────────


def test_get_stats_happy_path():
    db = _make_db()
    stats = {"total_orders": 42, "total_revenue_fen": 168000, "avg_table_size": 2.3}
    with patch.object(scan_order_api, "get_scan_order_stats", new=AsyncMock(return_value=stats)):
        client = TestClient(_make_so_app(db))
        resp = client.get(
            "/api/v1/scan-order/stats",
            params={"store_id": STORE, "start_date": "2026-04-01", "end_date": "2026-04-06"},
            headers=_BASE_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total_orders"] == 42
