"""MetricsAuthMiddleware — Prometheus /metrics 端点多层防御鉴权

issue #825 (Tier 1 邻接): PR #823 ship Counter `tx_events_emit_total` 进 emitter.py 但
gateway AuthMiddleware 拦 /metrics 401 → Prometheus scrape 永远 fail → W3 D2 决策矩阵
分母拿不到数据 → 不能 evaluate W11 #767 真投递切换决策.

多层防御 (per issue 验收标准):
  1. Bearer token — timing-safe `hmac.compare_digest`. 仅接受 `Authorization: Bearer <token>`
     header (Prometheus 原生 `authorization: type: Bearer` 用此, 与生产 prometheus.yml 一致).
     round-2 (§19 critic): 删除 X-Prometheus-Token branch — prometheus.yml 用 `authorization`
     字段, 该 branch 在生产是 dead code, 违反 surgical 红线 (CLAUDE.md §3).
  2. IP allowlist (CIDR) — `ipaddress.ip_network` 标准库
  3. XFF spoof 防御 (round-2 §19 security P0-1): 默认禁用 X-Forwarded-For 解析;
     仅当 `PROMETHEUS_TRUST_XFF=true` **且** 直连源 IP 在 `PROMETHEUS_TRUSTED_PROXIES` 内
     才信任 XFF 首位. 默认 attacker 发 XFF: 10.0.0.1 仍用真 client IP 校验.
  4. AuthMiddleware exempt /metrics (gateway main.py 已加 prefix)
  5. prod env hard gate (round-2 §19 critic P1-2): ENVIRONMENT in (production, prod, staging)
     + PROMETHEUS_AUTH_ENFORCE=false → 启动 raise (生产不可绕过).
  6. Token 长度 sanity check (round-2 §19 critic P1-3): enforce=true + token < 16 chars → raise.

设计原则:
  - 关注点分离: 不混入 gateway AuthMiddleware (业务 JWT 鉴权), 独立中间件接管 /metrics
  - fail-loud (per feedback_pydantic_v2_validation_error.md): PROMETHEUS_BEARER_TOKEN 缺
    且 enforce=true → 启动 raise RuntimeError (生产/staging)
  - fail-open (per feedback_graceful_degradation_pattern.md): dev/test 模式或非 /metrics
    路径 → 直接 call_next (不阻塞业务)
  - bypass exempt 列表: /health 不受影响 (k8s liveness 必须可访问)

环境变量:
  PROMETHEUS_BEARER_TOKEN     — 必需 (生产), 启动检; 缺且 PROMETHEUS_AUTH_ENFORCE=true → raise
  PROMETHEUS_IP_ALLOWLIST     — CIDR 逗号分隔, default 内网段
  PROMETHEUS_AUTH_ENFORCE     — "false" 关闭鉴权 (仅 dev/CI), default "true"
  PROMETHEUS_TRUST_XFF        — round-2: "true" opt-in X-Forwarded-For 解析, default false
  PROMETHEUS_TRUSTED_PROXIES  — round-2: trusted proxy CIDR 逗号分隔, default 空
                                (XFF 仅当 direct IP ∈ trusted_proxies 才信)
  ENVIRONMENT                 — round-2: production/prod/staging 时 enforce=false 启动 raise
"""

from __future__ import annotations

import hmac
import ipaddress
import os
from typing import Optional, Sequence

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = structlog.get_logger(__name__)


# 内网默认段 (RFC1918 + loopback + Docker/k8s 常见段)
_DEFAULT_ALLOWLIST_CIDR = (
    "127.0.0.0/8",     # loopback
    "10.0.0.0/8",      # RFC1918 + k8s pod CIDR 常见
    "172.16.0.0/12",   # RFC1918 + Docker default bridge
    "192.168.0.0/16",  # RFC1918
    "::1/128",         # IPv6 loopback
    "fc00::/7",        # IPv6 ULA
)

# 受 metrics auth 保护的 path (/metrics 是 prometheus_fastapi_instrumentator 默认)
# round-2 §19 critic P1-1: 严格匹配 — 路径必须等于 /metrics 或以 /metrics/ 开头.
# 旧 startswith("/metrics") 会拦 /metrics-debug / /metricsfoo 等无关路径 (false-positive),
# 也可能漏抓真子路径 /metrics/foo (正则错配概率). 改成 path == _P or path.startswith(_P + "/").
_PROTECTED_PATH = "/metrics"

# 绝不拦截的 path (k8s liveness / 业务 health)
_NEVER_PROTECT: tuple[str, ...] = ("/health", "/docs", "/openapi.json", "/redoc")

# round-2 §19 security P0-1: XFF spoof 防御 env vars
_TRUST_XFF_ENV = "PROMETHEUS_TRUST_XFF"
_TRUSTED_PROXIES_ENV = "PROMETHEUS_TRUSTED_PROXIES"

# round-2 §19 critic P1-2: prod env list (启动 raise if enforce=false)
_PROD_ENV_NAMES: tuple[str, ...] = ("production", "prod", "staging")

# round-2 §19 critic P1-3: token 最小长度 (placeholder 防御)
_MIN_TOKEN_LEN = 16


def _parse_cidr_list(raw: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """逗号分隔 CIDR → tuple of ip_network. 无效项 fail-loud raise."""
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for item in (raw or "").split(","):
        cidr = item.strip()
        if not cidr:
            continue
        networks.append(ipaddress.ip_network(cidr, strict=False))
    return tuple(networks)


def _is_trusted_proxy(
    ip_str: str,
    trusted_cidrs: Sequence[ipaddress.IPv4Network | ipaddress.IPv6Network],
) -> bool:
    """check direct client IP ∈ trusted_proxies (CIDR match). 空列表 → 永远 False."""
    if not trusted_cidrs:
        return False
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(ip in net for net in trusted_cidrs)


def _get_client_ip(
    request: Request,
    trust_xff: bool,
    trusted_proxy_cidrs: Sequence[ipaddress.IPv4Network | ipaddress.IPv6Network],
) -> Optional[str]:
    """提取真实 client IP.

    round-2 §19 security P0-1 改造: 默认仅用 `request.client.host` (直连 socket peer).
    仅当 `trust_xff=true` **且** 直连源 IP 在 `trusted_proxy_cidrs` 内才信任
    `X-Forwarded-For` 首位 (反代场景). 默认拒绝 attacker 通过 `X-Forwarded-For: 10.0.0.1`
    spoof allowlist 校验.
    """
    direct = request.client.host if request.client else None
    if not direct:
        return None
    if trust_xff and _is_trusted_proxy(direct, trusted_proxy_cidrs):
        xff = request.headers.get("X-Forwarded-For", "").strip()
        if xff:
            # X-Forwarded-For: client, proxy1, proxy2 — 取首位 (真客户端 IP)
            return xff.split(",")[0].strip()
    return direct


def _ip_in_allowlist(
    ip_str: str,
    allowlist: Sequence[ipaddress.IPv4Network | ipaddress.IPv6Network],
) -> bool:
    """check IP ∈ allowlist (CIDR match)."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(ip in network for network in allowlist)


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "ok": False,
            "data": None,
            "error": {"code": code, "message": message},
        },
    )


class MetricsAuthMiddleware(BaseHTTPMiddleware):
    """Prometheus /metrics 端点鉴权中间件 (Bearer token + IP allowlist).

    挂载顺序建议: 在 AuthMiddleware **外侧** (即先 add_middleware), 因为 Starlette
    middleware 栈是 LIFO — 后加的先执行. 我们希望 MetricsAuthMiddleware 先拦
    `/metrics`, AuthMiddleware 不再处理 (AUTH_EXEMPT_PREFIXES 已加 /metrics 双保险).

    流程:
      1. 非 /metrics 路径 → 透传 call_next
      2. /metrics 路径:
         a. PROMETHEUS_AUTH_ENFORCE=false → 直接放行 (dev/CI)
         b. Bearer token 缺 / 错 → 401
         c. client IP ∉ allowlist → 401
         d. 全通过 → call_next 返回 metrics body
    """

    def __init__(
        self,
        app,  # noqa: ANN001
        *,
        bearer_token: Optional[str] = None,
        allowlist_cidr: Optional[Sequence[str]] = None,
        enforce: Optional[bool] = None,
        trust_xff: Optional[bool] = None,
        trusted_proxies: Optional[Sequence[str]] = None,
    ) -> None:
        super().__init__(app)

        # enforce flag: 显式参数 > env > default true
        if enforce is None:
            enforce_env = os.environ.get("PROMETHEUS_AUTH_ENFORCE", "true").strip().lower()
            self._enforce = enforce_env != "false"
        else:
            self._enforce = enforce

        # round-2 §19 critic P1-2: prod env + enforce=false → 启动 raise (生产不可绕过)
        env_name = os.environ.get("ENVIRONMENT", "").strip().lower()
        if env_name in _PROD_ENV_NAMES and not self._enforce:
            raise RuntimeError(
                f"PROMETHEUS_AUTH_ENFORCE=false is FORBIDDEN in ENVIRONMENT={env_name}. "
                "Refusing to start with /metrics unprotected. "
                "Set PROMETHEUS_AUTH_ENFORCE=true or do not set ENVIRONMENT to production/prod/staging."
            )

        # bearer token: 显式参数 > env
        token = bearer_token if bearer_token is not None else os.environ.get(
            "PROMETHEUS_BEARER_TOKEN", ""
        ).strip()
        if self._enforce and not token:
            raise RuntimeError(
                "PROMETHEUS_BEARER_TOKEN 未配置且 PROMETHEUS_AUTH_ENFORCE=true; "
                "/metrics 端点鉴权要求 token (issue #825 Tier 1 邻接). "
                "dev/CI 模式设 PROMETHEUS_AUTH_ENFORCE=false 关闭强制."
            )
        # round-2 §19 critic P1-3: token 长度 sanity check (避免 placeholder/弱 token 上线)
        if self._enforce and len(token) < _MIN_TOKEN_LEN:
            raise RuntimeError(
                f"PROMETHEUS_BEARER_TOKEN 长度不足 {_MIN_TOKEN_LEN} chars (实际 {len(token)}), "
                "可能是 placeholder; 生产建议 32+ chars 随机串 "
                "(`python -c 'import secrets; print(secrets.token_urlsafe(32))'`)."
            )
        self._token = token

        # allowlist: 显式参数 > env > default
        if allowlist_cidr is not None:
            cidr_raw = ",".join(allowlist_cidr)
        else:
            cidr_raw = os.environ.get(
                "PROMETHEUS_IP_ALLOWLIST", ",".join(_DEFAULT_ALLOWLIST_CIDR)
            )
        self._allowlist = _parse_cidr_list(cidr_raw)

        # round-2 §19 security P0-1: XFF trust opt-in
        if trust_xff is None:
            self._trust_xff = os.environ.get(_TRUST_XFF_ENV, "false").strip().lower() == "true"
        else:
            self._trust_xff = trust_xff
        if trusted_proxies is not None:
            proxies_raw = ",".join(trusted_proxies)
        else:
            proxies_raw = os.environ.get(_TRUSTED_PROXIES_ENV, "")
        self._trusted_proxies = _parse_cidr_list(proxies_raw)
        # 警告: 启用 trust_xff 但 trusted_proxies 空 = 拒绝信 XFF (静默 fallback)
        if self._trust_xff and not self._trusted_proxies:
            logger.warning(
                "metrics_auth_trust_xff_enabled_but_no_trusted_proxies",
                hint="PROMETHEUS_TRUST_XFF=true 但 PROMETHEUS_TRUSTED_PROXIES 为空; "
                "XFF 永远不会被信任 (silent reject).",
            )

        logger.info(
            "metrics_auth_middleware_init",
            enforce=self._enforce,
            allowlist_count=len(self._allowlist),
            token_configured=bool(self._token),
            trust_xff=self._trust_xff,
            trusted_proxies_count=len(self._trusted_proxies),
            env=env_name or "unknown",
        )

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001
        path = request.url.path

        # 1. 绝不拦截的 path
        if any(path.startswith(p) for p in _NEVER_PROTECT):
            return await call_next(request)

        # 2. 非 /metrics 透传 (round-2 P1-1: 严格匹配, 不再 startswith)
        if path != _PROTECTED_PATH and not path.startswith(_PROTECTED_PATH + "/"):
            return await call_next(request)

        # 3. /metrics 路径
        # 3a. enforce=false → dev/CI 放行
        if not self._enforce:
            return await call_next(request)

        # 3b. Bearer token check (timing-safe compare)
        # round-2 §19 critic: 仅 Authorization: Bearer (prometheus.yml `authorization: type: Bearer`),
        # 删除 X-Prometheus-Token branch — 生产 dead code, 违反 surgical 红线.
        auth = request.headers.get("Authorization", "").strip()
        token_header = ""
        if auth.startswith("Bearer "):
            token_header = auth[7:].strip()
        if not token_header:
            logger.warning(
                "metrics_auth_missing_token",
                path=path,
                client_ip=_get_client_ip(request, self._trust_xff, self._trusted_proxies),
            )
            return _error_response(
                401,
                "METRICS_AUTH_REQUIRED",
                "Authorization: Bearer header required",
            )
        if not hmac.compare_digest(token_header, self._token):
            logger.warning(
                "metrics_auth_invalid_token",
                path=path,
                client_ip=_get_client_ip(request, self._trust_xff, self._trusted_proxies),
            )
            return _error_response(
                401, "METRICS_AUTH_INVALID_TOKEN", "Invalid metrics auth token"
            )

        # 3c. IP allowlist check
        client_ip = _get_client_ip(request, self._trust_xff, self._trusted_proxies)
        if not client_ip:
            logger.warning("metrics_auth_no_client_ip", path=path)
            return _error_response(
                401, "METRICS_AUTH_NO_CLIENT_IP", "Cannot determine client IP"
            )
        if not _ip_in_allowlist(client_ip, self._allowlist):
            logger.warning(
                "metrics_auth_ip_not_allowed",
                path=path,
                client_ip=client_ip,
            )
            return _error_response(
                401, "METRICS_AUTH_IP_NOT_ALLOWED", "Client IP not in allowlist"
            )

        # 3d. 全通过 → 放行
        return await call_next(request)
