"""test_rbac_integration — Sprint A4 RBAC 端到端集成测试

四条端到端场景（通过 FastAPI 测试客户端，经完整 Depends(require_role) 链路）：
  1. 收银员发起支付 → 200 + audit log 有记录
  2. 服务员发起退款 → 403
  3. 店长发起 > ¥100 减免无 MFA → 403
  4. 未认证（无 state.user_id）发起任意写操作 → 401

实现要点：
  - 用 starlette middleware 模拟 gateway AuthMiddleware 注入 request.state
  - 强制 TX_AUTH_ENABLED=true，确保 RBAC 不走 dev bypass
  - get_db / _get_db 依赖用 AsyncMock 覆盖，断言 audit 写入调用次数
"""

from __future__ import annotations

import os

# 必须在 import 路由之前
os.environ["TX_AUTH_ENABLED"] = "true"

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware


@pytest.fixture(autouse=True)
def _force_auth_enabled(monkeypatch):
    """每个测试强制 TX_AUTH_ENABLED=true，防止其他测试模块把它设为 false。"""
    monkeypatch.setenv("TX_AUTH_ENABLED", "true")


class _InjectUserMiddleware(BaseHTTPMiddleware):
    """模拟 gateway AuthMiddleware：把固定的用户上下文写到 request.state。"""

    def __init__(self, app, *, user_id: str | None, role: str, mfa_verified: bool):
        super().__init__(app)
        self.user_id = user_id
        self.role = role
        self.mfa_verified = mfa_verified

    async def dispatch(self, request, call_next):
        request.state.user_id = self.user_id
        request.state.tenant_id = "00000000-0000-0000-0000-000000000001"
        request.state.role = self.role
        request.state.mfa_verified = self.mfa_verified
        request.state.store_id = None
        return await call_next(request)


def _build_app(*, user_id: str | None, role: str, mfa: bool):
    """构建测试专用 FastAPI：只挂载 payment_direct / refund / discount_engine 路由。"""
    from shared.ontology.src.database import get_db
    from src.api.discount_engine_routes import router as discount_router
    from src.api.payment_direct_routes import router as pd_router
    from src.api.refund_routes import router as refund_router

    async def _mock_db():
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
        # 为 refund 路由的 INSERT ... RETURNING 提供一个 row
        mappings_obj = AsyncMock()
        mappings_obj.one = lambda: {"id": "00000000-0000-0000-0000-000000000099", "created_at": None}
        result = AsyncMock()
        result.mappings = lambda: mappings_obj
        db.execute.return_value = result
        yield db

    app = FastAPI()
    app.add_middleware(
        _InjectUserMiddleware,
        user_id=user_id,
        role=role,
        mfa_verified=mfa,
    )
    app.include_router(pd_router)
    app.include_router(refund_router)
    app.include_router(discount_router)
    app.dependency_overrides[get_db] = _mock_db
    return app


# ─── 场景 1：收银员发 payment/wechat 支付成功 + audit 被调用 ─────────────────


@pytest.mark.asyncio
async def test_cashier_wechat_pay_returns_200_and_writes_audit():
    app = _build_app(user_id="u-cashier", role="cashier", mfa=False)
    with (
        patch("src.api.payment_direct_routes.write_audit", new=AsyncMock()) as m_audit,
        patch(
            "src.api.payment_direct_routes.create_wechat_payment",
            new=AsyncMock(return_value={"payment_id": "wx-1", "ok": True}),
        ),
    ):
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/v1/payment-direct/wechat",
            json={"order_id": "O-1", "amount_fen": 8800, "openid": "o1"},
            headers={"X-Tenant-ID": "00000000-0000-0000-0000-000000000001"},
        )
    assert resp.status_code == 200, resp.text
    assert m_audit.await_count == 1
    kwargs = m_audit.await_args.kwargs
    assert kwargs["action"] == "payment.wechat.create"
    assert kwargs["amount_fen"] == 8800
    assert kwargs["user_role"] == "cashier"


# ─── 场景 2：服务员尝试发起退款 → 403 ROLE_FORBIDDEN ──────────────────────────


def test_waiter_refund_returns_403():
    app = _build_app(user_id="u-waiter", role="waiter", mfa=False)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/api/v1/trade/refunds",
        json={
            "order_id": "00000000-0000-0000-0000-000000000011",
            "refund_type": "full",
            "refund_amount_fen": 5000,
            "reasons": ["测试"],
        },
        headers={"X-Tenant-ID": "00000000-0000-0000-0000-000000000001"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "ROLE_FORBIDDEN"


# ─── 场景 3：店长对 > ¥100 减免无 MFA → 403 MFA_REQUIRED ──────────────────────


def test_store_manager_large_discount_without_mfa_returns_403():
    app = _build_app(user_id="u-manager", role="store_manager", mfa=False)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/api/v1/discount/calculate",
        json={
            "order_id": "O-2",
            "base_amount_fen": 50000,
            "discounts": [
                {"type": "manual_discount", "deduct_fen": 15000},  # ¥150
            ],
            "store_id": None,
        },
        headers={"X-Tenant-ID": "00000000-0000-0000-0000-000000000001"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "MFA_REQUIRED"


# ─── 场景 4：无认证（state.user_id = None）→ 401 AUTH_MISSING ────────────────


def test_no_auth_returns_401_on_write_operation():
    app = _build_app(user_id=None, role="", mfa=False)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/api/v1/payment-direct/wechat",
        json={"order_id": "O-3", "amount_fen": 100, "openid": "o2"},
        headers={"X-Tenant-ID": "00000000-0000-0000-0000-000000000001"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "AUTH_MISSING"
