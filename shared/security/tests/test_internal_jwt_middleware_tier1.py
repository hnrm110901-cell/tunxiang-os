"""InternalJwtMiddleware Tier 1 测试

审计 S-02（P0）闭环验证：中间件正确地把 X-Internal-JWT claims 注入 request.state，
失败回 401，dev/staging 兼容模式跳过，豁免路径放行。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

# 仓库根加到 sys.path 以便 `shared.security.src.*` 包导入解析（保留相对 import 形态）
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from shared.security.src.internal_jwt import mint_internal_jwt  # noqa: E402
from shared.security.src.internal_jwt_middleware import InternalJwtMiddleware  # noqa: E402

_TEST_SECRET = "test-secret-32-bytes-aaaaaaaaaaaa"


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(InternalJwtMiddleware)

    @app.get("/api/v1/probe")
    async def probe(request: Request) -> dict:
        return {
            "tenant_id": getattr(request.state, "tenant_id", ""),
            "user_id": getattr(request.state, "user_id", None),
            "role": getattr(request.state, "role", None),
            "auth_method": getattr(request.state, "auth_method", None),
        }

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True}

    @app.get("/metrics")
    async def metrics() -> dict:
        return {"ok": True}

    @app.post("/api/v1/webhook/meituan/order")
    async def webhook_meituan_order(request: Request) -> dict:
        return {"ok": True, "auth_method": getattr(request.state, "auth_method", None)}

    @app.post("/api/v1/booking/webhook/wechat")
    async def webhook_booking_wechat(request: Request) -> dict:
        return {"ok": True}

    @app.post("/api/v1/delivery/webhooks/grabfood")
    async def webhook_grabfood(request: Request) -> dict:
        return {"ok": True}

    @app.get("/api/v1/no-webhook-here/list")
    async def normal_endpoint() -> dict:
        return {"ok": True}

    return app


class TestProductionMode:
    """TX_ENV=production 严格模式 — 必须有合法 JWT，否则 401。"""

    def test_valid_jwt_injects_claims_into_state(self):
        with mock.patch.dict(
            os.environ,
            {"TX_INTERNAL_JWT_SECRET": _TEST_SECRET, "TX_ENV": "production"},
            clear=True,
        ):
            token = mint_internal_jwt(tenant_id="tenant-1", user_id="user-1", role="admin")
            assert token is not None

            client = TestClient(_make_app())
            r = client.get("/api/v1/probe", headers={"X-Internal-JWT": token})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["tenant_id"] == "tenant-1"
            assert body["user_id"] == "user-1"
            assert body["role"] == "admin"
            assert body["auth_method"] == "internal_jwt"

    def test_missing_jwt_returns_401(self):
        with mock.patch.dict(
            os.environ,
            {"TX_INTERNAL_JWT_SECRET": _TEST_SECRET, "TX_ENV": "production"},
            clear=True,
        ):
            client = TestClient(_make_app())
            r = client.get("/api/v1/probe")
            assert r.status_code == 401
            assert r.json()["error"]["code"] == "INTERNAL_JWT_INVALID"

    def test_invalid_signature_returns_401(self):
        with mock.patch.dict(
            os.environ,
            {"TX_INTERNAL_JWT_SECRET": _TEST_SECRET, "TX_ENV": "production"},
            clear=True,
        ):
            # 用错误密钥签的 token
            with mock.patch.dict(
                os.environ,
                {"TX_INTERNAL_JWT_SECRET": "wrong-secret-other-32bytes-bbbbbb"},
                clear=False,
            ):
                bad_token = mint_internal_jwt(tenant_id="t1")

            client = TestClient(_make_app())
            r = client.get(
                "/api/v1/probe",
                headers={"X-Internal-JWT": bad_token or "garbage"},
            )
            assert r.status_code == 401

    def test_garbage_jwt_returns_401(self):
        with mock.patch.dict(
            os.environ,
            {"TX_INTERNAL_JWT_SECRET": _TEST_SECRET, "TX_ENV": "production"},
            clear=True,
        ):
            client = TestClient(_make_app())
            r = client.get(
                "/api/v1/probe",
                headers={"X-Internal-JWT": "not.a.real.jwt.at.all"},
            )
            assert r.status_code == 401


class TestFailClosedAllEnvs:
    """cutover 完成后：dev/staging/prod 全环境都强制要 secret + token，
    历史 dev 跳过路径已删除（详见 docs/security/cutover-cleanup-plan.md §3.3）。"""

    def test_no_secret_returns_500_in_dev(self):
        """dev 无 secret = 服务器配置错误，500 fail-closed。"""
        with mock.patch.dict(os.environ, {"TX_ENV": "dev"}, clear=True):
            client = TestClient(_make_app())
            r = client.get("/api/v1/probe")
            assert r.status_code == 500
            assert r.json()["error"]["code"] == "INTERNAL_JWT_NOT_CONFIGURED"

    def test_no_secret_returns_500_in_test(self):
        """test 无 secret 也 500，不再静默跳过。"""
        with mock.patch.dict(os.environ, {"TX_ENV": "test"}, clear=True):
            client = TestClient(_make_app())
            r = client.get(
                "/api/v1/probe",
                headers={"X-Internal-JWT": "anything"},
            )
            assert r.status_code == 500

    def test_secret_set_no_token_in_staging_returns_401(self):
        """staging 有 secret 但 client 没发 token = 来自 gateway 之外，401（与 prod 等价）。"""
        with mock.patch.dict(
            os.environ,
            {"TX_INTERNAL_JWT_SECRET": _TEST_SECRET, "TX_ENV": "staging"},
            clear=True,
        ):
            client = TestClient(_make_app())
            r = client.get("/api/v1/probe")
            assert r.status_code == 401

    def test_production_no_secret_returns_500_with_token(self):
        """生产环境无 secret = 配置缺失，500（不再 401，避免误导为认证错误）。"""
        with mock.patch.dict(os.environ, {"TX_ENV": "production"}, clear=True):
            client = TestClient(_make_app())
            r = client.get(
                "/api/v1/probe",
                headers={"X-Internal-JWT": "any.token.here"},
            )
            assert r.status_code == 500
            assert r.json()["error"]["code"] == "INTERNAL_JWT_NOT_CONFIGURED"


class TestExemptPaths:
    """平台端点（health/metrics/docs）必须无条件放行 —— gateway 不注入 JWT 给它们。"""

    def test_health_exempt_in_production(self):
        with mock.patch.dict(
            os.environ,
            {"TX_INTERNAL_JWT_SECRET": _TEST_SECRET, "TX_ENV": "production"},
            clear=True,
        ):
            client = TestClient(_make_app())
            r = client.get("/health")  # 无 JWT header
            assert r.status_code == 200, "health 必须无条件 200"

    def test_metrics_exempt_in_production(self):
        with mock.patch.dict(
            os.environ,
            {"TX_INTERNAL_JWT_SECRET": _TEST_SECRET, "TX_ENV": "production"},
            clear=True,
        ):
            client = TestClient(_make_app())
            r = client.get("/metrics")
            assert r.status_code == 200


class TestExternalWebhookExempt:
    """外部平台 webhook 必须无条件放行（cutover 后修复）—— 美团/饿了么/抖音/微信
    等回调走公网入口，不带 X-Internal-JWT；webhook 路由内部有平台签名校验。"""

    def test_webhook_path_exempt_no_token(self):
        """/api/v1/webhook/meituan/order — 标准 webhook 路径应放行无 token 请求。"""
        with mock.patch.dict(
            os.environ,
            {"TX_INTERNAL_JWT_SECRET": _TEST_SECRET, "TX_ENV": "production"},
            clear=True,
        ):
            client = TestClient(_make_app())
            r = client.post("/api/v1/webhook/meituan/order")
            assert r.status_code == 200, "外部平台 webhook 必须 200，否则美团/饿了么订单全断"
            assert r.json()["auth_method"] is None  # 未注入 state

    def test_booking_webhook_subpath_exempt(self):
        """/api/v1/booking/webhook/wechat — 嵌套 webhook 路径段也必须豁免。"""
        with mock.patch.dict(
            os.environ,
            {"TX_INTERNAL_JWT_SECRET": _TEST_SECRET, "TX_ENV": "production"},
            clear=True,
        ):
            client = TestClient(_make_app())
            r = client.post("/api/v1/booking/webhook/wechat")
            assert r.status_code == 200

    def test_webhooks_plural_exempt(self):
        """复数 webhooks 也必须豁免（delivery_panel_router 等用 /webhooks 复数形式）。"""
        with mock.patch.dict(
            os.environ,
            {"TX_INTERNAL_JWT_SECRET": _TEST_SECRET, "TX_ENV": "production"},
            clear=True,
        ):
            client = TestClient(_make_app())
            r = client.post("/api/v1/delivery/webhooks/grabfood")
            assert r.status_code == 200

    def test_non_webhook_path_with_webhook_substring_not_exempt(self):
        """/no-webhook-here/list 含 'webhook' 子串但不是路径段，必须仍走鉴权（401）。"""
        with mock.patch.dict(
            os.environ,
            {"TX_INTERNAL_JWT_SECRET": _TEST_SECRET, "TX_ENV": "production"},
            clear=True,
        ):
            client = TestClient(_make_app())
            r = client.get("/api/v1/no-webhook-here/list")
            assert r.status_code == 401, "正则必须按路径段匹配，不能误判子串"


class TestExpiredToken:
    """过期 token 必须拒（防 replay）。"""

    def test_expired_token_returns_401(self):
        with mock.patch.dict(
            os.environ,
            {
                "TX_INTERNAL_JWT_SECRET": _TEST_SECRET,
                "TX_INTERNAL_JWT_TTL_SECONDS": "5",  # clamp lower bound is 5s
                "TX_ENV": "production",
            },
            clear=True,
        ):
            import time as _time

            token = mint_internal_jwt(tenant_id="tenant-1")
            assert token

            # 等过期
            _time.sleep(6)

            client = TestClient(_make_app())
            r = client.get(
                "/api/v1/probe",
                headers={"X-Internal-JWT": token},
            )
            assert r.status_code == 401


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
