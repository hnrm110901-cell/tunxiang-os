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


class TestDevStageCompat:
    """无 TX_INTERNAL_JWT_SECRET 时（dev/test/staging）放行，保持 cutover 前兼容。"""

    def test_no_secret_no_token_passes(self):
        with mock.patch.dict(os.environ, {"TX_ENV": "dev"}, clear=True):
            client = TestClient(_make_app())
            r = client.get("/api/v1/probe")
            assert r.status_code == 200
            assert r.json()["auth_method"] is None  # 未注入

    def test_no_secret_with_token_passes_no_state(self):
        """有 secret 才校验；无 secret 时即便客户端发了 token 也忽略放行。"""
        with mock.patch.dict(os.environ, {"TX_ENV": "test"}, clear=True):
            client = TestClient(_make_app())
            r = client.get(
                "/api/v1/probe",
                headers={"X-Internal-JWT": "anything"},
            )
            assert r.status_code == 200
            assert r.json()["auth_method"] is None

    def test_secret_set_no_token_in_dev_still_passes(self):
        """生产 fail-closed，但 dev/staging 有 secret 但 client 没发 token —
        过渡期允许通过（让升级中的 client 不破坏）。"""
        with mock.patch.dict(
            os.environ,
            {"TX_INTERNAL_JWT_SECRET": _TEST_SECRET, "TX_ENV": "staging"},
            clear=True,
        ):
            client = TestClient(_make_app())
            r = client.get("/api/v1/probe")
            assert r.status_code == 200
            assert r.json()["auth_method"] is None


class TestProductionFailClosed:
    """生产环境无 secret 配置 → middleware 直接拒（兜底，启动期已经拒）。"""

    def test_production_no_secret_returns_401_with_token(self):
        with mock.patch.dict(os.environ, {"TX_ENV": "production"}, clear=True):
            client = TestClient(_make_app())
            r = client.get(
                "/api/v1/probe",
                headers={"X-Internal-JWT": "any.token.here"},
            )
            assert r.status_code == 401
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
