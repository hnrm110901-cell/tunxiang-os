"""外卖订单路由测试 — delivery_orders_routes.py

覆盖场景（共 8 个）：
1. PUT  /orders/{id}/status — 正常状态流转：accepted → cooking
2. PUT  /orders/{id}/status — 非法状态转换返回 409
3. PUT  /orders/{id}/status — 订单不存在返回 404
4. POST /orders/{id}/cancel — 正常取消：pending_accept → cancelled
5. POST /orders/{id}/cancel — 不可取消状态（completed）返回 409
6. POST /webhook/meituan — mock webhook 接受任意 payload，返回 status=0
7. POST /webhook/eleme   — mock webhook 返回 code=0
8. PUT  /orders/{id}/status — 缺少 X-Tenant-ID → 400
"""

import os
import sys
import types

# ─── 路径准备 ──────────────────────────────────────────────────────────────────
_TESTS_DIR = os.path.dirname(__file__)
_SRC_DIR = os.path.join(_TESTS_DIR, "..")
_ROOT_DIR = os.path.abspath(os.path.join(_TESTS_DIR, "..", "..", "..", ".."))

for _p in [_SRC_DIR, _ROOT_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ─── 建立 src 包层级，使相对导入正常工作 ────────────────────────────────────────


def _ensure_pkg(pkg_name: str, pkg_path: str) -> None:
    if pkg_name not in sys.modules:
        mod = types.ModuleType(pkg_name)
        mod.__path__ = [pkg_path]
        mod.__package__ = pkg_name
        sys.modules[pkg_name] = mod


_ensure_pkg("src", _SRC_DIR)
_ensure_pkg("src.api", os.path.join(_SRC_DIR, "api"))
_ensure_pkg("src.models", os.path.join(_SRC_DIR, "models"))
_ensure_pkg("src.services", os.path.join(_SRC_DIR, "services"))

# ─── 导入真实 DeliveryOrder（需要 SQLAlchemy ORM，但不连接 DB）────────────────
# shared.ontology.src.base 里有 TenantBase，先确保路径里有 shared

# 现在可以安全导入真实模型

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.ontology.src.database import get_db
from src.api.delivery_orders_routes import router  # type: ignore[import]  # noqa: E402

# ─── 工具 ──────────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID = uuid.uuid4()

_BASE_HEADERS = {
    "X-Tenant-ID": TENANT_ID,
}


def _make_order(status: str = "accepted") -> MagicMock:
    """构造一个 Mock DeliveryOrder ORM 对象"""
    order = MagicMock()
    order.id = uuid.uuid4()
    order.tenant_id = uuid.UUID(TENANT_ID)
    order.store_id = STORE_ID
    order.platform = "meituan"
    order.platform_name = "美团外卖"
    order.platform_order_id = f"MT{uuid.uuid4().hex[:12]}"
    order.platform_order_no = "MT12345678"
    order.status = status
    order.items_json = [{"name": "红烧肉", "qty": 1, "price_fen": 3800}]
    order.total_fen = 3800
    order.actual_revenue_fen = 3116
    order.commission_fen = 684
    order.customer_name = "张三"
    order.customer_phone = "138****0000"
    order.delivery_address = "某某路1号"
    order.special_request = ""
    order.notes = None
    order.estimated_prep_time = 25
    order.rider_name = None
    order.rider_phone = None
    order.accepted_at = None
    order.ready_at = None
    order.completed_at = None
    order.created_at = datetime.now(timezone.utc)
    order.cancel_reason = None
    order.cancel_by = None
    order.cancelled_at = None
    return order


class _FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


def _make_db_with_order(order):
    """DB execute 返回指定 order"""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_FakeScalarResult(order))
    db.commit = AsyncMock()
    db.refresh = AsyncMock(side_effect=lambda o: None)
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
# 场景 1: PUT /orders/{id}/status — accepted → cooking 正常流转
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_update_status_accepted_to_cooking():
    """accepted → cooking 为合法转换，应返回 ok=True 且 status 更新"""
    order = _make_order(status="accepted")
    db = _make_db_with_order(order)

    app = _make_app(db)
    client = TestClient(app)
    resp = client.put(
        f"/api/v1/delivery/orders/{order.id}/status",
        json={"status": "cooking"},
        headers=_BASE_HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    # status 被 mock 对象更新
    assert order.status == "cooking"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 2: PUT /orders/{id}/status — 非法状态转换返回 409
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_update_status_illegal_transition():
    """completed 状态不能再转换到任何状态，应返回 409"""
    order = _make_order(status="completed")
    db = _make_db_with_order(order)

    app = _make_app(db)
    client = TestClient(app)
    resp = client.put(
        f"/api/v1/delivery/orders/{order.id}/status",
        json={"status": "cooking"},
        headers=_BASE_HEADERS,
    )

    assert resp.status_code == 409


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 3: PUT /orders/{id}/status — 订单不存在返回 404
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_update_status_order_not_found():
    """DB 查不到对应订单时应返回 404"""
    db = _make_db_with_order(None)  # scalar_one_or_none → None

    app = _make_app(db)
    client = TestClient(app)
    resp = client.put(
        f"/api/v1/delivery/orders/{uuid.uuid4()}/status",
        json={"status": "cooking"},
        headers=_BASE_HEADERS,
    )

    assert resp.status_code == 404


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 4: POST /orders/{id}/cancel — pending_accept → cancelled 正常取消
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_cancel_order_ok():
    """pending_accept 状态订单可取消，ok=True，状态变为 cancelled"""
    order = _make_order(status="pending_accept")
    db = _make_db_with_order(order)

    app = _make_app(db)
    client = TestClient(app)
    resp = client.post(
        f"/api/v1/delivery/orders/{order.id}/cancel",
        json={"reason": "暂停营业"},
        headers=_BASE_HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert order.status == "cancelled"
    assert order.cancel_reason == "暂停营业"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 5: POST /orders/{id}/cancel — completed 状态不可取消，返回 409
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_cancel_order_completed_returns_409():
    """已完成订单不允许取消，应返回 409"""
    order = _make_order(status="completed")
    db = _make_db_with_order(order)

    app = _make_app(db)
    client = TestClient(app)
    resp = client.post(
        f"/api/v1/delivery/orders/{order.id}/cancel",
        json={"reason": "测试取消"},
        headers=_BASE_HEADERS,
    )

    assert resp.status_code == 409


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 6: POST /webhook/meituan — mock webhook 返回 status=0
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_webhook_meituan_mock_returns_ok():
    """美团 Webhook mock 端点接受任意 JSON 并返回 status=0"""
    db = _make_db_with_order(None)
    app = _make_app(db)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/delivery/webhook/meituan",
        json={"orderId": "MT123", "status": "new"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == 0
    assert body["message"] == "ok"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 7: POST /webhook/eleme — mock webhook 返回 code=0
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_webhook_eleme_mock_returns_ok():
    """饿了么 Webhook mock 端点返回 code=0"""
    db = _make_db_with_order(None)
    app = _make_app(db)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/delivery/webhook/eleme",
        json={"orderId": "EL456", "eventType": "order_placed"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["message"] == "ok"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 8: PUT /orders/{id}/status — 缺少 X-Tenant-ID → 400
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_update_status_missing_tenant_header():
    """缺少 X-Tenant-ID 时 _get_tenant_id 应返回空字符串并触发 400"""
    order = _make_order(status="accepted")
    db = _make_db_with_order(order)

    app = _make_app(db)
    client = TestClient(app)
    resp = client.put(
        f"/api/v1/delivery/orders/{order.id}/status",
        json={"status": "cooking"},
        # 不传 X-Tenant-ID
    )

    assert resp.status_code == 400
