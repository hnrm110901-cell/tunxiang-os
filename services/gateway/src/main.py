"""TunxiangOS API Gateway — 统一入口，按域路由到各微服务"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .middleware import TenantMiddleware, RequestLogMiddleware
from .proxy import router as proxy_router
from .hub_api import router as hub_router
from .growth_intel_relay import router as relay_router
from .response import ok

app = FastAPI(
    title="TunxiangOS Gateway",
    version="3.0.0",
    description="AI-Native Restaurant Chain Operating System",
)

# Middleware（执行顺序：后添加先执行）
app.add_middleware(RequestLogMiddleware)
app.add_middleware(TenantMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: 生产环境限制域名
    allow_methods=["*"],
    allow_headers=["*"],
)

# Hub 运维管理 API（必须在 proxy 之前注册，否则被通配路由拦截）
app.include_router(hub_router)

# 情报→增长自动接力 API
app.include_router(relay_router)

# 域路由代理（通配路由 /api/v1/{domain}/{path}，放最后）
app.include_router(proxy_router)


@app.get("/health")
async def health():
    return ok({"service": "gateway", "version": "3.0.0"})


@app.get("/api/v1/domains")
async def list_domains():
    """列出所有域服务及其状态"""
    from .proxy import DOMAIN_ROUTES
    domains = {k: {"configured": bool(v), "url": v or "not configured"} for k, v in DOMAIN_ROUTES.items()}
    return ok(domains)


@app.get("/api/v1/menu-config")
async def get_menu_config(role: str = "admin"):
    """决策4：菜单配置引擎 — 根据角色动态生成菜单树"""
    from .menu_config import generate_menu_for_tenant
    # 全域签约（demo）
    all_domains = ["tx-trade", "tx-menu", "tx-member", "tx-supply", "tx-finance", "tx-org", "tx-analytics", "tx-agent"]
    modules = generate_menu_for_tenant(all_domains, role)
    return ok(modules)
