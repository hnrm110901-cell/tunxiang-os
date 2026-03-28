"""TunxiangOS API Gateway — 统一入口，按域路由到各微服务"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .middleware import AuthMiddleware, TenantMiddleware, RequestLogMiddleware
from .proxy import router as proxy_router
from .auth import router as auth_router
from .hub_api import router as hub_router
from .growth_intel_relay import router as relay_router
from .response import ok

app = FastAPI(title="TunxiangOS Gateway", version="3.0.0", description="AI-Native Restaurant Chain Operating System")

app.add_middleware(RequestLogMiddleware)
app.add_middleware(TenantMiddleware)
app.add_middleware(AuthMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(auth_router)
app.include_router(hub_router)
app.include_router(relay_router)
app.include_router(proxy_router)


@app.get("/health")
async def health():
    return ok({"service": "gateway", "version": "3.0.0"})


@app.get("/api/v1/domains")
async def list_domains():
    from .proxy import DOMAIN_ROUTES
    domains = {k: {"configured": bool(v), "url": v or "not configured"} for k, v in DOMAIN_ROUTES.items()}
    return ok(domains)


@app.get("/api/v1/menu-config")
async def get_menu_config(role: str = "admin"):
    from .menu_config import generate_menu_for_tenant
    all_domains = ["tx-trade", "tx-menu", "tx-member", "tx-supply", "tx-finance", "tx-org", "tx-analytics", "tx-agent"]
    modules = generate_menu_for_tenant(all_domains, role)
    return ok(modules)
