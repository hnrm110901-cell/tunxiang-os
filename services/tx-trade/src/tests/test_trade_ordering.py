"""收银核心 & 交易订单路由测试

覆盖文件：
  - api/cashier_api.py   (15 端点，收银台开台→点单→结算全流程)
  - api/orders.py        (13 端点，订单CRUD + 支付 + 打印)

测试场景（共 10 个）：

cashier_api.py:
  1. POST /api/v1/orders              — 开台成功，返回 ok=True + order_id
  2. POST /api/v1/orders/{id}/items   — 加菜成功，返回 ok=True + item 信息
  3. POST /api/v1/orders/{id}/settle  — 结算成功，返回 ok=True
  4. POST /api/v1/orders/{id}/cancel  — CashierEngine 抛 ValueError → 400
  5. GET  /api/v1/orders/{id}         — 订单不存在 ValueError → 404

orders.py:
  6. POST /api/v1/trade/orders             — 创建订单成功
  7. POST /api/v1/trade/orders/{id}/items  — 加菜成功
  8. GET  /api/v1/trade/orders/{id}        — 订单不存在 → 404
  9. POST /api/v1/trade/orders/{id}/payments — DB 错误（execute 抛异常）→ 500
 10. POST /api/v1/trade/orders/{id}/discount  — 422 缺必填字段
"""

import os
import sys
import types
import uuid

# ─── 路径 ─────────────────────────────────────────────────────────────────────
_TESTS_DIR = os.path.dirname(__file__)
_SRC_DIR = os.path.abspath(os.path.join(_TESTS_DIR, ".."))
_ROOT_DIR = os.path.abspath(os.path.join(_SRC_DIR, "..", "..", ".."))

for _p in (_SRC_DIR, _ROOT_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ─── 建立 src 包 & api 包 ─────────────────────────────────────────────────────


def _ensure_pkg(name: str, path: str) -> None:
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = [path]
        mod.__package__ = name
        sys.modules[name] = mod


_ensure_pkg("src", _SRC_DIR)
_ensure_pkg("src.api", os.path.join(_SRC_DIR, "api"))


# ─── 存根：cashier_api 所依赖的 services & discount_engine ────────────────────
#
#  cashier_api 使用相对导入：
#    from ..services.cashier_engine  import CashierEngine
#    from ..services.daily_settlement import DailySettlementService
#    from ..services.payment_gateway  import PaymentGateway
#    from ..services.payment_saga_service import PaymentSagaService
#    from ..services.permission_client import CashierPermissionClient
#    from .discount_engine_routes import DiscountInput, _build_steps, ...
#
#  orders.py 使用相对导入：
#    from ..services.order_service   import OrderService
#    from ..services.payment_service import PaymentService
#    from ..services.receipt_service import ReceiptService
#
#  通过 sys.modules 注入存根后，再 import router 时相对导入可以解析。

import unittest.mock as _mock

# ── 存根 services 包 ──
_services_path = os.path.join(_SRC_DIR, "services")
_ensure_pkg("src.services", _services_path)

_SVC_CLASS_MAP = {
    "cashier_engine": ["CashierEngine"],
    "daily_settlement": ["DailySettlementService"],
    "payment_gateway": ["PaymentGateway"],
    "payment_saga_service": ["PaymentSagaService"],
    "permission_client": ["CashierPermissionClient"],
    "order_service": ["OrderService"],
    "payment_service": ["PaymentService"],
    "receipt_service": ["ReceiptService"],
}

for _svc, _classes in _SVC_CLASS_MAP.items():
    _full = f"src.services.{_svc}"
    if _full not in sys.modules:
        _m = types.ModuleType(_full)
        for _cls_name in _classes:
            # Create a minimal stub class so `from module import ClassName` works
            setattr(_m, _cls_name, type(_cls_name, (), {}))
        sys.modules[_full] = _m

# ── 存根 discount_engine_routes（cashier_api 从同包导入） ──
_discount_stub = types.ModuleType("src.api.discount_engine_routes")
_discount_stub.DiscountInput = object  # 仅类型占位
_discount_stub._build_steps = lambda *a, **kw: []
_discount_stub._fetch_active_rules = _mock.AsyncMock(return_value=[])
_discount_stub._insert_discount_log = _mock.AsyncMock(return_value=None)
_discount_stub._resolve_conflicts = lambda *a, **kw: ([], [])
sys.modules["src.api.discount_engine_routes"] = _discount_stub


# ─── 导入 ─────────────────────────────────────────────────────────────────────
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from shared.ontology.src.database import get_db  # noqa: E402

# ─── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_ID = "22222222-2222-2222-2222-222222222222"
ORDER_ID = str(uuid.uuid4())
ITEM_ID = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}


# ─── 共用工具 ─────────────────────────────────────────────────────────────────


def _make_mock_db() -> AsyncMock:
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _make_app_with_db(router, db: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.include_router(router)

    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    return app


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Part 1 — cashier_api.py 测试（5 个）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.fixture(scope="module")
def cashier_router():
    """导入 cashier_api router，CashierEngine 等通过 patch 替换。"""
    from src.api.cashier_api import router  # type: ignore[import]

    return router


# ─── 场景 1: 开台成功 ──────────────────────────────────────────────────────────


def test_cashier_open_table_success(cashier_router):
    """POST /api/v1/orders — CashierEngine.open_table 返回正常 → ok=True，含 order_id。"""
    fake_result = {"order_id": ORDER_ID, "status": "confirmed", "table_no": "A01"}

    mock_engine = MagicMock()
    mock_engine.open_table = AsyncMock(return_value=fake_result)

    db = _make_mock_db()
    app = _make_app_with_db(cashier_router, db)

    with patch("src.api.cashier_api.CashierEngine", return_value=mock_engine):
        client = TestClient(app)
        resp = client.post(
            "/api/v1/orders",
            json={
                "store_id": str(uuid.uuid4()),
                "table_no": "A01",
                "waiter_id": str(uuid.uuid4()),
                "guest_count": 2,
            },
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["order_id"] == ORDER_ID
    mock_engine.open_table.assert_awaited_once()


# ─── 场景 2: 加菜成功 ──────────────────────────────────────────────────────────


def test_cashier_add_item_success(cashier_router):
    """POST /api/v1/orders/{id}/items — 加菜成功，返回 ok=True + item 信息。"""
    fake_item = {"item_id": ITEM_ID, "dish_name": "宫保鸡丁", "qty": 2, "subtotal_fen": 7600}

    mock_engine = MagicMock()
    mock_engine.add_item = AsyncMock(return_value=fake_item)

    db = _make_mock_db()
    app = _make_app_with_db(cashier_router, db)

    with patch("src.api.cashier_api.CashierEngine", return_value=mock_engine):
        client = TestClient(app)
        resp = client.post(
            f"/api/v1/orders/{ORDER_ID}/items",
            json={
                "dish_id": str(uuid.uuid4()),
                "dish_name": "宫保鸡丁",
                "qty": 2,
                "unit_price_fen": 3800,
            },
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["item_id"] == ITEM_ID
    assert body["data"]["subtotal_fen"] == 7600


# ─── 场景 3: 结算成功 ──────────────────────────────────────────────────────────


def test_cashier_settle_order_success(cashier_router):
    """POST /api/v1/orders/{id}/settle — settle_order 返回正常 → ok=True。"""
    fake_result = {"order_id": ORDER_ID, "status": "completed", "total_fen": 8800}

    mock_engine = MagicMock()
    mock_engine.settle_order = AsyncMock(return_value=fake_result)

    db = _make_mock_db()
    app = _make_app_with_db(cashier_router, db)

    with patch("src.api.cashier_api.CashierEngine", return_value=mock_engine):
        client = TestClient(app)
        resp = client.post(
            f"/api/v1/orders/{ORDER_ID}/settle",
            json={"payments": [{"method": "wechat", "amount_fen": 8800}]},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "completed"


# ─── 场景 4: 取消订单 — ValueError → 400 ──────────────────────────────────────


def test_cashier_cancel_order_value_error(cashier_router):
    """POST /api/v1/orders/{id}/cancel — engine 抛 ValueError（如订单已完成）→ 400。"""
    mock_engine = MagicMock()
    mock_engine.cancel_order = AsyncMock(side_effect=ValueError("订单已结算，无法取消"))

    db = _make_mock_db()
    app = _make_app_with_db(cashier_router, db)

    with patch("src.api.cashier_api.CashierEngine", return_value=mock_engine):
        client = TestClient(app)
        resp = client.post(
            f"/api/v1/orders/{ORDER_ID}/cancel",
            json={"reason": "顾客改变主意"},
            headers=HEADERS,
        )

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "订单已结算" in str(detail)


# ─── 场景 5: 查询订单 — 不存在 → 404 ──────────────────────────────────────────


def test_cashier_get_order_not_found(cashier_router):
    """GET /api/v1/orders/{id} — engine 抛 ValueError（订单不存在）→ 404。"""
    mock_engine = MagicMock()
    mock_engine.get_order_detail = AsyncMock(side_effect=ValueError("订单不存在"))

    db = _make_mock_db()
    app = _make_app_with_db(cashier_router, db)

    with patch("src.api.cashier_api.CashierEngine", return_value=mock_engine):
        client = TestClient(app)
        resp = client.get(
            f"/api/v1/orders/{ORDER_ID}",
            headers=HEADERS,
        )

    assert resp.status_code == 404
    assert "订单不存在" in str(resp.json()["detail"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Part 2 — orders.py 测试（5 个）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.fixture(scope="module")
def trade_router():
    """导入 orders.py router，OrderService / PaymentService / ReceiptService patch 替换。"""
    from src.api.orders import router  # type: ignore[import]

    return router


# ─── 场景 6: 创建订单成功 ──────────────────────────────────────────────────────


def test_trade_create_order_success(trade_router):
    """POST /api/v1/trade/orders — OrderService.create_order 返回正常 → ok=True + order_id。"""
    fake_order = {"order_id": ORDER_ID, "status": "draft", "order_type": "dine_in"}

    mock_svc = MagicMock()
    mock_svc.create_order = AsyncMock(return_value=fake_order)

    db = _make_mock_db()
    app = _make_app_with_db(trade_router, db)

    with patch("src.api.orders.OrderService", return_value=mock_svc):
        client = TestClient(app)
        resp = client.post(
            "/api/v1/trade/orders",
            json={
                "store_id": str(uuid.uuid4()),
                "order_type": "dine_in",
                "table_no": "B03",
            },
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["order_id"] == ORDER_ID
    mock_svc.create_order.assert_awaited_once()


# ─── 场景 7: 加菜成功 ──────────────────────────────────────────────────────────


def test_trade_add_item_success(trade_router):
    """POST /api/v1/trade/orders/{id}/items — add_item 成功 → ok=True。"""
    fake_item = {"item_id": ITEM_ID, "dish_name": "清蒸鲈鱼", "quantity": 1}

    mock_svc = MagicMock()
    mock_svc.add_item = AsyncMock(return_value=fake_item)

    db = _make_mock_db()
    app = _make_app_with_db(trade_router, db)

    with patch("src.api.orders.OrderService", return_value=mock_svc):
        client = TestClient(app)
        resp = client.post(
            f"/api/v1/trade/orders/{ORDER_ID}/items",
            json={
                "dish_id": str(uuid.uuid4()),
                "dish_name": "清蒸鲈鱼",
                "quantity": 1,
                "unit_price_fen": 6800,
            },
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["dish_name"] == "清蒸鲈鱼"


# ─── 场景 8: 查询订单 — 不存在 → 404 ──────────────────────────────────────────


def test_trade_get_order_not_found(trade_router):
    """GET /api/v1/trade/orders/{id} — OrderService.get_order 返回 None → 404。"""
    mock_svc = MagicMock()
    mock_svc.get_order = AsyncMock(return_value=None)

    db = _make_mock_db()
    app = _make_app_with_db(trade_router, db)

    with patch("src.api.orders.OrderService", return_value=mock_svc):
        client = TestClient(app)
        resp = client.get(
            f"/api/v1/trade/orders/{ORDER_ID}",
            headers=HEADERS,
        )

    assert resp.status_code == 404
    assert "Order not found" in resp.json()["detail"]


# ─── 场景 9: 创建支付 — DB 错误 → 500 ────────────────────────────────────────


def test_trade_create_payment_db_error(trade_router):
    """POST /api/v1/trade/orders/{id}/payments — PaymentService.create_payment 抛 Exception → 500。"""
    mock_svc = MagicMock()
    mock_svc.create_payment = AsyncMock(side_effect=Exception("DB connection pool exhausted"))

    db = _make_mock_db()
    app = _make_app_with_db(trade_router, db)

    with patch("src.api.orders.PaymentService", return_value=mock_svc):
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            f"/api/v1/trade/orders/{ORDER_ID}/payments",
            json={"method": "wechat", "amount_fen": 8800},
            headers=HEADERS,
        )

    assert resp.status_code == 500


# ─── 场景 10: 应用折扣 — 缺必填字段 → 422 ──────────────────────────────────────


def test_trade_apply_discount_missing_field(trade_router):
    """POST /api/v1/trade/orders/{id}/discount — 缺少必填 discount_fen → 422 Unprocessable Entity。"""
    db = _make_mock_db()
    app = _make_app_with_db(trade_router, db)

    client = TestClient(app)
    resp = client.post(
        f"/api/v1/trade/orders/{ORDER_ID}/discount",
        json={"reason": "VIP优惠"},  # 缺少 discount_fen
        headers=HEADERS,
    )

    assert resp.status_code == 422
    errors = resp.json()["detail"]
    field_names = [e["loc"][-1] if isinstance(e.get("loc"), list) else str(e) for e in errors]
    assert any("discount_fen" in str(f) for f in field_names)
