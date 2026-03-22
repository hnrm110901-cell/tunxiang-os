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

# 域服务注册表 — 全部指向新微服务
DOMAIN_ROUTES = {
    "trade": os.getenv("TX_TRADE_URL", "http://localhost:8001"),
    "menu": os.getenv("TX_MENU_URL", "http://localhost:8002"),
    "member": os.getenv("TX_MEMBER_URL", "http://localhost:8003"),
    "supply": os.getenv("TX_SUPPLY_URL", "http://localhost:8004"),
    "finance": os.getenv("TX_FINANCE_URL", "http://localhost:8005"),
    "org": os.getenv("TX_ORG_URL", "http://localhost:8006"),
    "analytics": os.getenv("TX_ANALYTICS_URL", "http://localhost:8007"),
    "agent": os.getenv("TX_AGENT_URL", "http://localhost:8008"),
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
        async with httpx.AsyncClient(timeout=30) as client:
            url = f"{target_url}{request.url.path}"
            headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")}
            body = await request.body()

            resp = await client.request(
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
            content={"ok": False, "data": None, "error": {"code": "SERVICE_DOWN", "message": f"Service unreachable"}},
        )
    except Exception as e:
        logger.error("proxy_error", error=str(e))
        return JSONResponse(
            status_code=502,
            content={"ok": False, "data": None, "error": {"code": "PROXY_ERROR", "message": str(e)}},
        )


@router.api_route("/api/v1/{domain}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def domain_proxy(request: Request, domain: str, path: str):
    """按域路由到对应微服务"""
    target = DOMAIN_ROUTES.get(domain, "")
    if not target and LEGACY_URL:
        target = LEGACY_URL
    return await _proxy(request, target)
