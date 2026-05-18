"""MetricsAuthMiddleware — Prometheus /metrics 端点多层防御鉴权

issue #825 (Tier 1 邻接): PR #823 ship Counter `tx_events_emit_total` 进 emitter.py 但
gateway AuthMiddleware 拦 /metrics 401 → Prometheus scrape 永远 fail → W3 D2 决策矩阵
分母拿不到数据 → 不能 evaluate W11 #767 真投递切换决策.

多层防御 (per issue 验收标准):
  1. Bearer token (`X-Prometheus-Token` header) — timing-safe `hmac.compare_digest`
  2. IP allowlist (CIDR) — `ipaddress.ip_network` 标准库
  3. AuthMiddleware exempt /metrics (gateway main.py 已加 prefix)

设计原则:
  - 关注点分离: 不混入 gateway AuthMiddleware (业务 JWT 鉴权), 独立中间件接管 /metrics
  - fail-loud (per feedback_pydantic_v2_validation_error.md): PROMETHEUS_BEARER_TOKEN 缺
    且 enforce=true → 启动 raise RuntimeError (生产/staging)
  - fail-open (per feedback_graceful_degradation_pattern.md): dev/test 模式或非 /metrics
    路径 → 直接 call_next (不阻塞业务)
  - bypass exempt 列表: /health 不受影响 (k8s liveness 必须可访问)

环境变量:
  PROMETHEUS_BEARER_TOKEN  — 必需 (生产), 启动检; 缺且 PROMETHEUS_AUTH_ENFORCE=true → raise
  PROMETHEUS_IP_ALLOWLIST  — CIDR 逗号分隔, default 内网段
  PROMETHEUS_AUTH_ENFORCE  — "false" 关闭鉴权 (仅 dev/CI), default "true"
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

# 受 metrics auth 保护的 path prefix (/metrics 是 prometheus_fastapi_instrumentator 默认)
_PROTECTED_PREFIX = "/metrics"

# 绝不拦截的 path (k8s liveness / 业务 health)
_NEVER_PROTECT: tuple[str, ...] = ("/health", "/docs", "/openapi.json", "/redoc")


def _parse_cidr_list(raw: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """逗号分隔 CIDR → tuple of ip_network. 无效项 fail-loud raise."""
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for item in (raw or "").split(","):
        cidr = item.strip()
        if not cidr:
            continue
        networks.append(ipaddress.ip_network(cidr, strict=False))
    return tuple(networks)


def _get_client_ip(request: Request) -> Optional[str]:
    """提取真实 client IP. k8s/nginx 反代场景优先 X-Forwarded-For 首位.

    注: trust X-Forwarded-For 仅当本中间件部署在内网 (反代之后); 公网部署不可
    直接 trust, 需在 reverse proxy 层 strip 客户端伪造的 header.
    """
    xff = request.headers.get("X-Forwarded-For", "").strip()
    if xff:
        # X-Forwarded-For: client, proxy1, proxy2 — 取首位
        return xff.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


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
    ) -> None:
        super().__init__(app)

        # enforce flag: 显式参数 > env > default true
        if enforce is None:
            enforce_env = os.environ.get("PROMETHEUS_AUTH_ENFORCE", "true").strip().lower()
            self._enforce = enforce_env != "false"
        else:
            self._enforce = enforce

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
        self._token = token

        # allowlist: 显式参数 > env > default
        if allowlist_cidr is not None:
            cidr_raw = ",".join(allowlist_cidr)
        else:
            cidr_raw = os.environ.get(
                "PROMETHEUS_IP_ALLOWLIST", ",".join(_DEFAULT_ALLOWLIST_CIDR)
            )
        self._allowlist = _parse_cidr_list(cidr_raw)

        logger.info(
            "metrics_auth_middleware_init",
            enforce=self._enforce,
            allowlist_count=len(self._allowlist),
            token_configured=bool(self._token),
        )

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001
        path = request.url.path

        # 1. 绝不拦截的 path
        if any(path.startswith(p) for p in _NEVER_PROTECT):
            return await call_next(request)

        # 2. 非 /metrics 透传
        if not path.startswith(_PROTECTED_PREFIX):
            return await call_next(request)

        # 3. /metrics 路径
        # 3a. enforce=false → dev/CI 放行
        if not self._enforce:
            return await call_next(request)

        # 3b. Bearer token check (timing-safe compare)
        token_header = request.headers.get("X-Prometheus-Token", "").strip()
        if not token_header:
            logger.warning(
                "metrics_auth_missing_token",
                path=path,
                client_ip=_get_client_ip(request),
            )
            return _error_response(
                401, "METRICS_AUTH_REQUIRED", "X-Prometheus-Token header required"
            )
        if not hmac.compare_digest(token_header, self._token):
            logger.warning(
                "metrics_auth_invalid_token",
                path=path,
                client_ip=_get_client_ip(request),
            )
            return _error_response(
                401, "METRICS_AUTH_INVALID_TOKEN", "Invalid X-Prometheus-Token"
            )

        # 3c. IP allowlist check
        client_ip = _get_client_ip(request)
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
