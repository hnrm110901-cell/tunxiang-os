"""域路由代理 — Strangler Fig 模式，按域渐进切换

初期：所有请求转发到旧 tunxiang 单体
按域迁移后：逐步切到新微服务
"""
import os

import httpx
from fastapi import APIRouter, Request

router = APIRouter()

# 域服务注册表（迁移完成后更新 target）
DOMAIN_ROUTES = {
    "trade": os.getenv("TX_TRADE_URL", ""),
    "menu": os.getenv("TX_MENU_URL", ""),
    "member": os.getenv("TX_MEMBER_URL", ""),
    "supply": os.getenv("TX_SUPPLY_URL", ""),
    "finance": os.getenv("TX_FINANCE_URL", ""),
    "org": os.getenv("TX_ORG_URL", ""),
    "analytics": os.getenv("TX_ANALYTICS_URL", ""),
    "agent": os.getenv("TX_AGENT_URL", ""),
}

# 旧单体回退地址
LEGACY_URL = os.getenv("LEGACY_API_URL", "")


async def _proxy(request: Request, target_url: str) -> dict:
    """转发请求到目标服务"""
    if not target_url:
        return {"ok": False, "data": None, "error": {"code": "SERVICE_UNAVAILABLE", "message": "Target service not configured"}}

    async with httpx.AsyncClient(timeout=30) as client:
        url = f"{target_url}{request.url.path}"
        headers = dict(request.headers)
        headers.pop("host", None)

        body = await request.body()
        resp = await client.request(
            method=request.method,
            url=url,
            headers=headers,
            params=dict(request.query_params),
            content=body if body else None,
        )
        return resp.json()


@router.api_route("/api/v1/{domain}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def domain_proxy(request: Request, domain: str, path: str):
    """按域路由到对应微服务，未配置的域回退到旧单体"""
    target = DOMAIN_ROUTES.get(domain, "")

    if not target and LEGACY_URL:
        target = LEGACY_URL

    return await _proxy(request, target)
