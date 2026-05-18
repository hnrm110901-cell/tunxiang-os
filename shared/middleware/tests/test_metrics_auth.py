"""MetricsAuthMiddleware Tier 1 邻接测试 — issue #825 + round-2 §19

覆盖场景:
  - Bearer token 缺失 → 401
  - Bearer token 错 → 401
  - Bearer token 对 + IP 在 allowlist → 200
  - timing-safe compare (hmac.compare_digest) verify
  - /health 不受影响仍 200
  - 业务 endpoint 透传
  - dev mode (enforce=false) 直接放行
  - enforce=true + 缺 token → __init__ raise (fail-loud)
  - IPv4 + IPv6 CIDR match (via trusted_proxy + XFF)
  - round-2 P1-1: 严格 prefix 匹配 (/metrics-debug fall-through; /metrics/foo 受保护)
  - round-2 P0-1: XFF spoof default rejected + opt-in trusted_proxy 信任
  - round-2 P1-2: prod env + enforce=false → 启动 raise
  - round-2 P1-3: token < 16 chars + enforce=true → raise
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.middleware.src.metrics_auth import MetricsAuthMiddleware

# round-2: 强 token (≥ 16 chars 满足 P1-3 sanity check)
_STRONG_TOKEN = "secret-token-abc-1234567890"


class _SetClientIPScope:
    """ASGI wrapper — 注入 scope['client'] 让 request.client.host 可测试.

    Starlette TestClient 不发 scope['client'], 致 request.client = None.
    round-2 XFF spoof 防御默认拒 XFF 后, 测试必须显式控制 direct client IP.
    """

    def __init__(self, app, client_ip: str, client_port: int = 12345) -> None:
        self.app = app
        self.client_ip = client_ip
        self.client_port = client_port

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        if scope.get("type") == "http":
            # NOTE: 必须在 middleware stack 解析 request.client 之前注入
            scope = dict(scope)
            scope["client"] = (self.client_ip, self.client_port)
        await self.app(scope, receive, send)


def _make_client(app: FastAPI, client_ip: str = "127.0.0.1") -> TestClient:
    """构造 TestClient + ASGI client IP 注入."""
    return TestClient(_SetClientIPScope(app, client_ip))


@pytest.fixture
def app_with_metrics_auth() -> FastAPI:
    """构造测试 app: /metrics + /health + /api/v1/orders + /metrics-debug + /metrics/foo 路由."""
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

    @app.get("/metrics-debug")
    async def metrics_debug() -> dict:
        return {"debug": "secret-data"}

    @app.get("/metrics/foo")
    async def metrics_subpath() -> dict:
        return {"sub": "data"}

    return app


class TestBearerTokenAuth:
    """场景 1-3: Bearer token 鉴权 (Authorization: Bearer)."""

    def test_missing_token_returns_401(self, app_with_metrics_auth: FastAPI) -> None:
        app_with_metrics_auth.add_middleware(
            MetricsAuthMiddleware,
            bearer_token=_STRONG_TOKEN,
            allowlist_cidr=("127.0.0.0/8",),
            enforce=True,
        )
        client = _make_client(app_with_metrics_auth)
        resp = client.get("/metrics")
        assert resp.status_code == 401
        body = resp.json()
        assert body["error"]["code"] == "METRICS_AUTH_REQUIRED"
        assert "Authorization: Bearer" in body["error"]["message"]

    def test_wrong_token_returns_401(self, app_with_metrics_auth: FastAPI) -> None:
        app_with_metrics_auth.add_middleware(
            MetricsAuthMiddleware,
            bearer_token=_STRONG_TOKEN,
            allowlist_cidr=("127.0.0.0/8",),
            enforce=True,
        )
        client = _make_client(app_with_metrics_auth)
        resp = client.get("/metrics", headers={"Authorization": "Bearer wrong-token-xyz"})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "METRICS_AUTH_INVALID_TOKEN"

    def test_correct_token_loopback_ip_returns_200(
        self, app_with_metrics_auth: FastAPI
    ) -> None:
        """场景 4: token 对 + TestClient direct IP=127.0.0.1 在 allowlist → 200."""
        app_with_metrics_auth.add_middleware(
            MetricsAuthMiddleware,
            bearer_token=_STRONG_TOKEN,
            allowlist_cidr=("127.0.0.0/8",),
            enforce=True,
        )
        client = _make_client(app_with_metrics_auth)
        resp = client.get(
            "/metrics",
            headers={"Authorization": f"Bearer {_STRONG_TOKEN}"},
        )
        assert resp.status_code == 200
        # 真返 metrics body, 不是空
        assert "tx_events_emit_total" in resp.json().get("counter", "")


class TestIPAllowlist:
    """IP allowlist 校验 (default 用 direct client.host, 不信 XFF)."""

    def test_ip_not_in_allowlist_returns_401(
        self, app_with_metrics_auth: FastAPI
    ) -> None:
        """TestClient direct IP=127.0.0.1, allowlist 只允许 10.0.0.0/8 → 401."""
        app_with_metrics_auth.add_middleware(
            MetricsAuthMiddleware,
            bearer_token=_STRONG_TOKEN,
            allowlist_cidr=("10.0.0.0/8",),  # 不含 127.0.0.1
            enforce=True,
        )
        client = _make_client(app_with_metrics_auth)
        resp = client.get(
            "/metrics",
            headers={"Authorization": f"Bearer {_STRONG_TOKEN}"},
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "METRICS_AUTH_IP_NOT_ALLOWED"

    def test_ipv4_cidr_match_via_trusted_xff(self, app_with_metrics_auth: FastAPI) -> None:
        """开启 trust_xff + trusted_proxies=127.0.0.0/8 (TestClient) → XFF 真客户端 10.1.2.3 落 allowlist."""
        app_with_metrics_auth.add_middleware(
            MetricsAuthMiddleware,
            bearer_token=_STRONG_TOKEN,
            allowlist_cidr=("10.0.0.0/8",),
            enforce=True,
            trust_xff=True,
            trusted_proxies=("127.0.0.0/8",),  # TestClient direct = 127.0.0.1 = trusted proxy
        )
        client = _make_client(app_with_metrics_auth)
        resp = client.get(
            "/metrics",
            headers={
                "Authorization": f"Bearer {_STRONG_TOKEN}",
                "X-Forwarded-For": "10.1.2.3",
            },
        )
        assert resp.status_code == 200

    def test_ipv6_cidr_match_via_trusted_xff(self, app_with_metrics_auth: FastAPI) -> None:
        """IPv6 allowlist + XFF IPv6 → 200 (走 trusted proxy + XFF 路径)."""
        app_with_metrics_auth.add_middleware(
            MetricsAuthMiddleware,
            bearer_token=_STRONG_TOKEN,
            allowlist_cidr=("fc00::/7",),
            enforce=True,
            trust_xff=True,
            trusted_proxies=("127.0.0.0/8",),
        )
        client = _make_client(app_with_metrics_auth)
        resp = client.get(
            "/metrics",
            headers={
                "Authorization": f"Bearer {_STRONG_TOKEN}",
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
            bearer_token=_STRONG_TOKEN,
            allowlist_cidr=("127.0.0.0/8",),
            enforce=True,
        )
        client = _make_client(app_with_metrics_auth)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_business_endpoint_transparent(
        self, app_with_metrics_auth: FastAPI
    ) -> None:
        """业务 endpoint (/api/v1/orders) 不受本 PR 影响, 透传 call_next."""
        app_with_metrics_auth.add_middleware(
            MetricsAuthMiddleware,
            bearer_token=_STRONG_TOKEN,
            allowlist_cidr=("127.0.0.0/8",),
            enforce=True,
        )
        client = _make_client(app_with_metrics_auth)
        resp = client.get("/api/v1/orders")
        assert resp.status_code == 200
        assert resp.json() == {"orders": []}


class TestEnforceFlag:
    """场景 7-8: dev/CI 关闭强制 + fail-loud 配置缺失."""

    def test_enforce_false_bypasses_auth(
        self, app_with_metrics_auth: FastAPI
    ) -> None:
        """dev/CI 模式 (PROMETHEUS_AUTH_ENFORCE=false) /metrics 无 token 仍 200."""
        # 清除 ENVIRONMENT 防止 prod env hard gate 干扰
        with patch.dict(os.environ, {"ENVIRONMENT": ""}, clear=False):
            app_with_metrics_auth.add_middleware(
                MetricsAuthMiddleware,
                bearer_token="",  # 空 token 不 raise (enforce=false)
                allowlist_cidr=("127.0.0.0/8",),
                enforce=False,
            )
            client = _make_client(app_with_metrics_auth)
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
        client = _make_client(app_with_metrics_auth)
        # hmac.compare_digest 接受不同长度输入不 raise — 返回 False
        resp = client.get("/metrics", headers={"Authorization": "Bearer short"})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "METRICS_AUTH_INVALID_TOKEN"


class TestAuthorizationBearer:
    """Prometheus 原生 `authorization: type: Bearer` 发 Authorization: Bearer header."""

    def test_authorization_bearer_header_accepted(
        self, app_with_metrics_auth: FastAPI
    ) -> None:
        app_with_metrics_auth.add_middleware(
            MetricsAuthMiddleware,
            bearer_token="prom-secret-token-2026",  # 16+ chars
            allowlist_cidr=("127.0.0.0/8",),
            enforce=True,
        )
        client = _make_client(app_with_metrics_auth)
        resp = client.get(
            "/metrics",
            headers={"Authorization": "Bearer prom-secret-token-2026"},
        )
        assert resp.status_code == 200

    def test_authorization_non_bearer_scheme_rejected(
        self, app_with_metrics_auth: FastAPI
    ) -> None:
        """Authorization: Basic xyz 不解析 → 视为 missing token → 401."""
        app_with_metrics_auth.add_middleware(
            MetricsAuthMiddleware,
            bearer_token=_STRONG_TOKEN,
            allowlist_cidr=("127.0.0.0/8",),
            enforce=True,
        )
        client = _make_client(app_with_metrics_auth)
        resp = client.get(
            "/metrics",
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "METRICS_AUTH_REQUIRED"


class TestPathPrefixStrictMatch:
    """round-2 §19 critic P1-1: 严格 prefix 匹配, 不再 startswith.

    旧 startswith("/metrics") false-positive 拦 /metrics-debug / /metricsfoo.
    新逻辑: path == "/metrics" or path.startswith("/metrics/")
    """

    def test_metrics_dash_path_fall_through(
        self, app_with_metrics_auth: FastAPI
    ) -> None:
        """/metrics-debug 不应被拦 (非真子路径, 仅字面前缀)."""
        app_with_metrics_auth.add_middleware(
            MetricsAuthMiddleware,
            bearer_token=_STRONG_TOKEN,
            allowlist_cidr=("127.0.0.0/8",),
            enforce=True,
        )
        client = _make_client(app_with_metrics_auth)
        resp = client.get("/metrics-debug")
        # round-2: 不再拦, 透传到 handler
        assert resp.status_code == 200
        assert resp.json() == {"debug": "secret-data"}

    def test_metrics_real_subpath_protected(
        self, app_with_metrics_auth: FastAPI
    ) -> None:
        """/metrics/foo 真子路径 → 仍受保护, 缺 token 应 401."""
        app_with_metrics_auth.add_middleware(
            MetricsAuthMiddleware,
            bearer_token=_STRONG_TOKEN,
            allowlist_cidr=("127.0.0.0/8",),
            enforce=True,
        )
        client = _make_client(app_with_metrics_auth)
        resp = client.get("/metrics/foo")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "METRICS_AUTH_REQUIRED"


class TestXFFSpoofDefense:
    """round-2 §19 security P0-1: X-Forwarded-For spoof 防御 (默认拒, opt-in 信)."""

    def test_xff_default_rejected_uses_direct_ip(
        self, app_with_metrics_auth: FastAPI
    ) -> None:
        """默认 trust_xff=false: 攻击者 X-Forwarded-For: 10.0.0.1 应被忽略, 用 direct IP 校验.

        TestClient direct IP = 127.0.0.1, allowlist = 10.0.0.0/8 (不含 127.0.0.1)
        旧逻辑: XFF 优先 → 10.0.0.1 ∈ allowlist → 200 (spoof 成功)
        新逻辑: 默认不信 XFF → 用 127.0.0.1 → ∉ allowlist → 401
        """
        app_with_metrics_auth.add_middleware(
            MetricsAuthMiddleware,
            bearer_token=_STRONG_TOKEN,
            allowlist_cidr=("10.0.0.0/8",),  # 不含 127.0.0.1
            enforce=True,
            # trust_xff/trusted_proxies 不传 → 默认 false/空
        )
        client = _make_client(app_with_metrics_auth)
        resp = client.get(
            "/metrics",
            headers={
                "Authorization": f"Bearer {_STRONG_TOKEN}",
                "X-Forwarded-For": "10.0.0.1",  # 攻击者伪造的"内网" IP
            },
        )
        assert resp.status_code == 401
        # 用 direct 127.0.0.1 校验 ∉ 10.0.0.0/8 → IP_NOT_ALLOWED
        assert resp.json()["error"]["code"] == "METRICS_AUTH_IP_NOT_ALLOWED"

    def test_xff_opt_in_with_trusted_proxy_accepted(
        self, app_with_metrics_auth: FastAPI
    ) -> None:
        """opt-in trust_xff + direct IP ∈ trusted_proxies → 信任 XFF 首位."""
        app_with_metrics_auth.add_middleware(
            MetricsAuthMiddleware,
            bearer_token=_STRONG_TOKEN,
            allowlist_cidr=("192.168.0.0/16",),
            enforce=True,
            trust_xff=True,
            trusted_proxies=("127.0.0.0/8",),  # TestClient direct ∈ trusted_proxies
        )
        client = _make_client(app_with_metrics_auth)
        resp = client.get(
            "/metrics",
            headers={
                "Authorization": f"Bearer {_STRONG_TOKEN}",
                "X-Forwarded-For": "192.168.1.10",  # 真客户端 IP, 反代转发
            },
        )
        assert resp.status_code == 200

    def test_xff_opt_in_but_direct_not_trusted_rejected(
        self, app_with_metrics_auth: FastAPI
    ) -> None:
        """trust_xff=true 但 direct IP ∉ trusted_proxies → 仍用 direct IP, 不信 XFF.

        这覆盖 'attacker 直连且想 spoof XFF' 场景: opt-in 开了但 trusted_proxies 收紧.
        """
        app_with_metrics_auth.add_middleware(
            MetricsAuthMiddleware,
            bearer_token=_STRONG_TOKEN,
            allowlist_cidr=("10.0.0.0/8",),
            enforce=True,
            trust_xff=True,
            trusted_proxies=("192.168.0.0/16",),  # TestClient 127.0.0.1 ∉ 此段
        )
        client = _make_client(app_with_metrics_auth)
        resp = client.get(
            "/metrics",
            headers={
                "Authorization": f"Bearer {_STRONG_TOKEN}",
                "X-Forwarded-For": "10.1.2.3",  # 伪造
            },
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "METRICS_AUTH_IP_NOT_ALLOWED"


class TestProdEnvHardGate:
    """round-2 §19 critic P1-2: prod env + enforce=false → 启动 raise."""

    @pytest.mark.parametrize("env_name", ["production", "prod", "staging", "PRODUCTION"])
    def test_prod_env_enforce_false_raises(self, env_name: str) -> None:
        """ENVIRONMENT in (production/prod/staging) + enforce=false → RuntimeError."""
        app = FastAPI()
        env_patch = {"ENVIRONMENT": env_name}
        with patch.dict(os.environ, env_patch, clear=False):
            with pytest.raises(RuntimeError, match="FORBIDDEN in ENVIRONMENT"):
                app.add_middleware(
                    MetricsAuthMiddleware,
                    bearer_token=_STRONG_TOKEN,
                    allowlist_cidr=("127.0.0.0/8",),
                    enforce=False,
                )
                TestClient(app).get("/")

    def test_dev_env_enforce_false_ok(self) -> None:
        """ENVIRONMENT=dev (或未设) + enforce=false → 正常启动."""
        app = FastAPI()
        with patch.dict(os.environ, {"ENVIRONMENT": "dev"}, clear=False):
            # 不应 raise
            app.add_middleware(
                MetricsAuthMiddleware,
                bearer_token="",
                allowlist_cidr=("127.0.0.0/8",),
                enforce=False,
            )
            client = TestClient(app)
            # 路由不存在 fall-through 404, 仅 verify init 成功
            resp = client.get("/health-nonexistent")
            assert resp.status_code == 404


class TestTokenLengthSanity:
    """round-2 §19 critic P1-3: token < 16 chars + enforce=true → raise."""

    def test_short_token_enforce_true_raises(self) -> None:
        """8 chars token + enforce=true → RuntimeError (placeholder 嫌疑)."""
        app = FastAPI()
        with pytest.raises(RuntimeError, match="长度不足 16 chars"):
            app.add_middleware(
                MetricsAuthMiddleware,
                bearer_token="short8ch",  # 8 chars
                allowlist_cidr=("127.0.0.0/8",),
                enforce=True,
            )
            TestClient(app).get("/")

    def test_exact_16_chars_token_ok(self, app_with_metrics_auth: FastAPI) -> None:
        """16 chars 边界 → 通过 (>= 16)."""
        token_16 = "x" * 16
        app_with_metrics_auth.add_middleware(
            MetricsAuthMiddleware,
            bearer_token=token_16,
            allowlist_cidr=("127.0.0.0/8",),
            enforce=True,
        )
        client = _make_client(app_with_metrics_auth)
        resp = client.get("/metrics", headers={"Authorization": f"Bearer {token_16}"})
        assert resp.status_code == 200

    def test_short_token_enforce_false_ok(self) -> None:
        """短 token + enforce=false → 不 raise (dev/CI 模式不检查)."""
        app = FastAPI()
        with patch.dict(os.environ, {"ENVIRONMENT": ""}, clear=False):
            # 不应 raise
            app.add_middleware(
                MetricsAuthMiddleware,
                bearer_token="short",
                allowlist_cidr=("127.0.0.0/8",),
                enforce=False,
            )
            client = TestClient(app)
            resp = client.get("/health-nonexistent")
            assert resp.status_code == 404
