"""tx-indonesia — 印度尼西亚本地化微服务

PPN 税引擎（Sprint 3.4）+ e-Faktur 电子发票
+ GoPay/DANA 本地支付 + GoFood/ShopeeFood Indonesia
"""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.ontology.src.database import init_db

from .api.ppn_routes import router as ppn_router

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("tx_indonesia_started", port=8016)
    yield
    logger.info("tx_indonesia_stopped")


app = FastAPI(
    title="TunxiangOS tx-indonesia",
    version="1.0.0",
    description="印度尼西亚本地化 — PPN / e-Faktur / GoPay / DANA / GoFood / ShopeeFood",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 审计 S-02 闭环：校验 gateway 注入的 X-Internal-JWT，把受信 claims 写入
# request.state；env TX_INTERNAL_JWT_SECRET 未配时 skip 不破坏现状。
# 必须在 CORSMiddleware 之后 add（FastAPI 后 add 的在内层；CORS preflight
# OPTIONS 走外层 CORS 直接返 200，不经 JWT 校验）。
# 详见 docs/security/internal-jwt-rollout.md
from shared.security.src.internal_jwt_middleware import InternalJwtMiddleware

app.add_middleware(InternalJwtMiddleware)
app.include_router(ppn_router)


@app.get("/health")
async def health():
    return {"ok": True, "service": "tx-indonesia", "version": "1.0.0"}
