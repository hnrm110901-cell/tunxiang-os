"""域路由代理 — Strangler Fig 模式，全域切换到新微服务

M4a: Gateway 路由 100% 切换到 tunxiang-os 域微服务。
旧 tunxiang 单体作为 fallback 保留，可通过 LEGACY_API_URL 配置。
"""
import os

import httpx
import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = structlog.get_logger()
router = APIRouter()

# 全局连接池 — 复用 TCP 连接，避免每次请求新建连接（省 8-25ms）
_http_pool = httpx.AsyncClient(
    timeout=httpx.Timeout(connect=5, read=30, write=10, pool=5),
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20, keepalive_expiry=30),
    follow_redirects=False,
)

# 域服务注册表 — 全部指向新微服务
DOMAIN_ROUTES = {
    "trade": os.getenv("TX_TRADE_URL", "http://localhost:8001"),
    "menu": os.getenv("TX_MENU_URL", "http://localhost:8002"),
    "member": os.getenv("TX_MEMBER_URL", "http://localhost:8003"),
    "growth": os.getenv("TX_GROWTH_URL", "http://localhost:8004"),
    "ops": os.getenv("TX_OPS_URL", "http://localhost:8005"),
    "supply": os.getenv("TX_SUPPLY_URL", "http://localhost:8006"),
    "finance": os.getenv("TX_FINANCE_URL", "http://localhost:8007"),
    "agent": os.getenv("TX_AGENT_URL", "http://localhost:8008"),
    "analytics": os.getenv("TX_ANALYTICS_URL", "http://localhost:8009"),
    "brain": os.getenv("TX_BRAIN_URL", "http://localhost:8010"),
    "intel": os.getenv("TX_INTEL_URL", "http://localhost:8011"),
    "org": os.getenv("TX_ORG_URL", "http://localhost:8012"),
    # 别名路由：print/* 和 kds/* 均转发到 tx-trade
    "print": os.getenv("TX_TRADE_URL", "http://localhost:8001"),
    "kds": os.getenv("TX_TRADE_URL", "http://localhost:8001"),
    # Agent 子域路由（tx-agent:8008）
    "agent-hub": os.getenv("TX_AGENT_URL", "http://localhost:8008"),
    "agent-monitor": os.getenv("TX_AGENT_URL", "http://localhost:8008"),
    "stream": os.getenv("TX_AGENT_URL", "http://localhost:8008"),
    "daily-review": os.getenv("TX_AGENT_URL", "http://localhost:8008"),
    "master-agent": os.getenv("TX_AGENT_URL", "http://localhost:8008"),
    # Analytics 子域路由（tx-analytics:8009）
    "nlq": os.getenv("TX_ANALYTICS_URL", "http://localhost:8009"),
    "anomaly": os.getenv("TX_ANALYTICS_URL", "http://localhost:8009"),
    "store-analysis": os.getenv("TX_ANALYTICS_URL", "http://localhost:8009"),
    "knowledge-query": os.getenv("TX_ANALYTICS_URL", "http://localhost:8009"),
    "narrative": os.getenv("TX_ANALYTICS_URL", "http://localhost:8009"),
    # Supply 子域路由（tx-supply:8006）
    "procurement-recommend": os.getenv("TX_SUPPLY_URL", "http://localhost:8006"),
}

# 旧单体回退（M4a 后可移除）
LEGACY_URL = os.getenv("LEGACY_API_URL", "")


async def _proxy(request: Request, target_url: str) -> JSONResponse:
    """转发请求到目标服务"""
    if not target_url:
        return JSONResponse(
            status_code=503,
            content={"ok": False, "data": None, "error": {"code": "SERVICE_UNAVAILABLE", "message": "Target service not configured"}},
        )

    try:
        url = f"{target_url}{request.url.path}"
        headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")}
        body = await request.body()

        resp = await _http_pool.request(
            method=request.method,
            url=url,
            headers=headers,
            params=dict(request.query_params),
            content=body if body else None,
        )
        return JSONResponse(status_code=resp.status_code, content=resp.json())
    except httpx.ConnectError:
        logger.warning("service_unreachable", target=target_url, path=request.url.path)
        # 回退到旧单体
        if LEGACY_URL:
            return await _proxy(request, LEGACY_URL)
        return JSONResponse(
            status_code=503,
            content={"ok": False, "data": None, "error": {"code": "SERVICE_DOWN", "message": "Service unreachable"}},
        )
    except httpx.TimeoutException as e:
        logger.warning("proxy_timeout", target=target_url, path=request.url.path, error=str(e))
        return JSONResponse(
            status_code=504,
            content={"ok": False, "data": None, "error": {"code": "PROXY_TIMEOUT", "message": "Upstream service timeout"}},
        )
    except httpx.HTTPError as e:
        logger.error("proxy_http_error", target=target_url, error=str(e))
        return JSONResponse(
            status_code=502,
            content={"ok": False, "data": None, "error": {"code": "PROXY_ERROR", "message": str(e)}},
        )
    except (ValueError, KeyError, UnicodeDecodeError, OSError) as e:
        logger.error("proxy_unexpected_error", error=str(e), error_type=type(e).__name__, exc_info=True)
        return JSONResponse(
            status_code=502,
            content={"ok": False, "data": None, "error": {"code": "PROXY_ERROR", "message": "Internal proxy error"}},
        )


@router.api_route("/api/v1/{domain}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def domain_proxy(request: Request, domain: str, path: str):
    """按域路由到对应微服务"""
    target = DOMAIN_ROUTES.get(domain, "")
    if not target and LEGACY_URL:
        target = LEGACY_URL
    return await _proxy(request, target)
