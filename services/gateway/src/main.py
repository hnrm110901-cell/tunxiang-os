"""TunxiangOS API Gateway — 统一入口，按域路由到各微服务"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="TunxiangOS Gateway",
    version="3.0.0",
    description="AI-Native Restaurant Chain Operating System",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: 生产环境限制域名
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def tenant_id_middleware(request: Request, call_next):
    """从 X-Tenant-ID header 提取租户 ID"""
    tenant_id = request.headers.get("X-Tenant-ID")
    request.state.tenant_id = tenant_id
    response = await call_next(request)
    return response


@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "gateway", "version": "3.0.0"}}


# 域服务路由（按域迁移后逐步添加）
# from services.tx_trade.src.api import router as trade_router
# app.include_router(trade_router, prefix="/api/v1/trade")
