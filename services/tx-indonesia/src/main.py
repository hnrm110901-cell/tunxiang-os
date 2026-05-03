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

app.include_router(ppn_router)


@app.get("/health")
async def health():
    return {"ok": True, "service": "tx-indonesia", "version": "1.0.0"}
