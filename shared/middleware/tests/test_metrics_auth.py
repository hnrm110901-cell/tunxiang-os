"""MetricsAuthMiddleware Tier 1 邻接测试 — issue #825

覆盖场景:
  - Bearer token 缺失 → 401
  - Bearer token 错 → 401
  - Bearer token 对 + IP 不在 allowlist → 401
  - Bearer token 对 + IP 在 allowlist → 200 + 真返 metrics
  - timing-safe compare (hmac.compare_digest) 实战 verify
  - /health 不受影响仍 200
  - 业务 endpoint 透传 (不受本 PR 影响)
  - dev mode (enforce=false) 直接放行
  - enforce=true + 缺 token → __init__ raise (fail-loud)
  - IPv4 + IPv6 CIDR match
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.middleware.src.metrics_auth import MetricsAuthMiddleware


@pytest.fixture
def app_with_metrics_auth() -> FastAPI:
    """构造测试 app: /metrics + /health + /api/v1/orders 路由."""
    app = FastAPI()

    @app.get("/metrics")
    async def metrics() -> dict:
        return {"counter": "tx_events_emit_total 42"}

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True}

    @app.get("/api/v1/orders")
    async def orders() -> dict:
        return {"orders": []}

    return app


class TestBearerTokenAuth:
    """场景 1-3: Bearer token 鉴权."""

    def test_missing_token_returns_401(self, app_with_metrics_auth: FastAPI) -> None:
        app_with_metrics_auth.add_middleware(
            MetricsAuthMiddleware,
            bearer_token="secret-token-abc",
            allowlist_cidr=("127.0.0.0/8",),
            enforce=True,
        )
        client = TestClient(app_with_metrics_auth)
        resp = client.get("/metrics")
        assert resp.status_code == 401
        body = resp.json()
        assert body["error"]["code"] == "METRICS_AUTH_REQUIRED"

    def test_wrong_token_returns_401(self, app_with_metrics_auth: FastAPI) -> None:
        app_with_metrics_auth.add_middleware(
            MetricsAuthMiddleware,
            bearer_token="secret-token-abc",
            allowlist_cidr=("127.0.0.0/8",),
            enforce=True,
        )
        client = TestClient(app_with_metrics_auth)
        resp = client.get("/metrics", headers={"X-Prometheus-Token": "wrong-token"})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "METRICS_AUTH_INVALID_TOKEN"

    def test_correct_token_correct_ip_returns_200(
        self, app_with_metrics_auth: FastAPI
    ) -> None:
        """场景 4: token 对 + IP 在 allowlist (X-Forwarded-For 模拟 prometheus 内网 IP) → 200."""
        app_with_metrics_auth.add_middleware(
            MetricsAuthMiddleware,
            bearer_token="secret-token-abc",
            allowlist_cidr=("10.0.0.0/8",),
            enforce=True,
        )
        client = TestClient(app_with_metrics_auth)
        resp = client.get(
            "/metrics",
            headers={
                "X-Prometheus-Token": "secret-token-abc",
                "X-Forwarded-For": "10.42.0.7",  # Prometheus pod 内网 IP 模拟
            },
        )
        assert resp.status_code == 200
        # 真返 metrics body, 不是空
        assert "tx_events_emit_total" in resp.json().get("counter", "")


class TestIPAllowlist:
    """场景 3: token 对但 IP 不在 allowlist → 401."""

    def test_ip_not_in_allowlist_returns_401(
        self, app_with_metrics_auth: FastAPI
    ) -> None:
        # TestClient default 127.0.0.1 → 用 X-Forwarded-For 模拟外网 IP
        app_with_metrics_auth.add_middleware(
            MetricsAuthMiddleware,
            bearer_token="secret-token-abc",
            allowlist_cidr=("10.0.0.0/8",),  # 内网段不含 127.0.0.1
            enforce=True,
        )
        client = TestClient(app_with_metrics_auth)
        resp = client.get(
            "/metrics",
            headers={
                "X-Prometheus-Token": "secret-token-abc",
                "X-Forwarded-For": "203.0.113.42",  # TEST-NET-3 公网段
            },
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "METRICS_AUTH_IP_NOT_ALLOWED"

    def test_ipv4_cidr_match(self, app_with_metrics_auth: FastAPI) -> None:
        app_with_metrics_auth.add_middleware(
            MetricsAuthMiddleware,
            bearer_token="secret-token-abc",
            allowlist_cidr=("10.0.0.0/8",),
            enforce=True,
        )
        client = TestClient(app_with_metrics_auth)
        resp = client.get(
            "/metrics",
            headers={
                "X-Prometheus-Token": "secret-token-abc",
                "X-Forwarded-For": "10.1.2.3",
            },
        )
        assert resp.status_code == 200

    def test_ipv6_cidr_match(self, app_with_metrics_auth: FastAPI) -> None:
        app_with_metrics_auth.add_middleware(
            MetricsAuthMiddleware,
            bearer_token="secret-token-abc",
            allowlist_cidr=("fc00::/7",),
            enforce=True,
        )
        client = TestClient(app_with_metrics_auth)
        resp = client.get(
            "/metrics",
            headers={
                "X-Prometheus-Token": "secret-token-abc",
                "X-Forwarded-For": "fc00::1",
            },
        )
        assert resp.status_code == 200


class TestBypass:
    """场景 5-6: /health 透传 + 业务 endpoint 透传."""

    def test_health_endpoint_always_passes(
        self, app_with_metrics_auth: FastAPI
    ) -> None:
        """k8s liveness check 必须可达, MetricsAuthMiddleware 绝不拦 /health."""
        app_with_metrics_auth.add_middleware(
            MetricsAuthMiddleware,
            bearer_token="secret-token-abc",
            allowlist_cidr=("127.0.0.0/8",),
            enforce=True,
        )
        client = TestClient(app_with_metrics_auth)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_business_endpoint_transparent(
        self, app_with_metrics_auth: FastAPI
    ) -> None:
        """业务 endpoint (/api/v1/orders) 不受本 PR 影响, 透传 call_next."""
        app_with_metrics_auth.add_middleware(
            MetricsAuthMiddleware,
            bearer_token="secret-token-abc",
            allowlist_cidr=("127.0.0.0/8",),
            enforce=True,
        )
        client = TestClient(app_with_metrics_auth)
        resp = client.get("/api/v1/orders")
        assert resp.status_code == 200
        assert resp.json() == {"orders": []}


class TestEnforceFlag:
    """场景 7-8: dev/CI 关闭强制 + fail-loud 配置缺失."""

    def test_enforce_false_bypasses_auth(
        self, app_with_metrics_auth: FastAPI
    ) -> None:
        """dev/CI 模式 (PROMETHEUS_AUTH_ENFORCE=false) /metrics 无 token 仍 200."""
        app_with_metrics_auth.add_middleware(
            MetricsAuthMiddleware,
            bearer_token="",  # 空 token 不 raise (enforce=false)
            allowlist_cidr=("127.0.0.0/8",),
            enforce=False,
        )
        client = TestClient(app_with_metrics_auth)
        resp = client.get("/metrics")
        assert resp.status_code == 200

    def test_enforce_true_missing_token_raises(self) -> None:
        """生产模式 (enforce=true) 缺 token → __init__ raise RuntimeError (fail-loud)."""
        app = FastAPI()
        with pytest.raises(RuntimeError, match="PROMETHEUS_BEARER_TOKEN 未配置"):
            app.add_middleware(
                MetricsAuthMiddleware,
                bearer_token="",
                allowlist_cidr=("127.0.0.0/8",),
                enforce=True,
            )
            # 触发 middleware 实例化 — TestClient 构造时
            TestClient(app).get("/")


class TestTimingSafeCompare:
    """timing-safe compare verify: 长度不同的 wrong token 也返 401 (而非 raise)."""

    def test_short_wrong_token_returns_401(
        self, app_with_metrics_auth: FastAPI
    ) -> None:
        app_with_metrics_auth.add_middleware(
            MetricsAuthMiddleware,
            bearer_token="long-correct-token-1234567890",
            allowlist_cidr=("127.0.0.0/8",),
            enforce=True,
        )
        client = TestClient(app_with_metrics_auth)
        # hmac.compare_digest 接受不同长度输入不 raise — 返回 False
        resp = client.get("/metrics", headers={"X-Prometheus-Token": "short"})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "METRICS_AUTH_INVALID_TOKEN"


class TestAuthorizationBearer:
    """Prometheus 原生 `authorization: type: Bearer` 发 Authorization: Bearer header."""

    def test_authorization_bearer_header_accepted(
        self, app_with_metrics_auth: FastAPI
    ) -> None:
        app_with_metrics_auth.add_middleware(
            MetricsAuthMiddleware,
            bearer_token="prom-secret-token",
            allowlist_cidr=("10.0.0.0/8",),
            enforce=True,
        )
        client = TestClient(app_with_metrics_auth)
        resp = client.get(
            "/metrics",
            headers={
                "Authorization": "Bearer prom-secret-token",
                "X-Forwarded-For": "10.1.2.3",
            },
        )
        assert resp.status_code == 200

    def test_x_prometheus_token_priority_over_authorization(
        self, app_with_metrics_auth: FastAPI
    ) -> None:
        """X-Prometheus-Token 优先; Authorization 错也无所谓."""
        app_with_metrics_auth.add_middleware(
            MetricsAuthMiddleware,
            bearer_token="correct-token",
            allowlist_cidr=("10.0.0.0/8",),
            enforce=True,
        )
        client = TestClient(app_with_metrics_auth)
        resp = client.get(
            "/metrics",
            headers={
                "X-Prometheus-Token": "correct-token",
                "Authorization": "Bearer wrong-token",
                "X-Forwarded-For": "10.1.2.3",
            },
        )
        assert resp.status_code == 200

    def test_authorization_non_bearer_scheme_rejected(
        self, app_with_metrics_auth: FastAPI
    ) -> None:
        """Authorization: Basic xyz 不解析 → 视为 missing token → 401."""
        app_with_metrics_auth.add_middleware(
            MetricsAuthMiddleware,
            bearer_token="correct-token",
            allowlist_cidr=("10.0.0.0/8",),
            enforce=True,
        )
        client = TestClient(app_with_metrics_auth)
        resp = client.get(
            "/metrics",
            headers={
                "Authorization": "Basic dXNlcjpwYXNz",
                "X-Forwarded-For": "10.1.2.3",
            },
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "METRICS_AUTH_REQUIRED"


class TestMetricsSubpath:
    """子路径 /metrics/foo 也受保护 (Instrumentator 默认仅 /metrics, 但防御性覆盖)."""

    def test_metrics_subpath_protected(self, app_with_metrics_auth: FastAPI) -> None:
        """e.g. /metrics-foo 也 startswith /metrics → 受保护."""

        @app_with_metrics_auth.get("/metrics-debug")
        async def metrics_debug() -> dict:
            return {"debug": "secret-data"}

        app_with_metrics_auth.add_middleware(
            MetricsAuthMiddleware,
            bearer_token="secret-token-abc",
            allowlist_cidr=("127.0.0.0/8",),
            enforce=True,
        )
        client = TestClient(app_with_metrics_auth)
        resp = client.get("/metrics-debug")
        assert resp.status_code == 401
