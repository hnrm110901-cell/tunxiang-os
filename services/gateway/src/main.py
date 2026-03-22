"""TunxiangOS API Gateway — 统一入口，按域路由到各微服务"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .middleware import TenantMiddleware, RequestLogMiddleware
from .proxy import router as proxy_router
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

# 域路由代理
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
