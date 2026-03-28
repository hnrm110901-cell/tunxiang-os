"""tx-trade — 域A 交易履约微服务

收银引擎：开单/点餐/结算/支付/退款/打印/日结
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.ontology.src.database import init_db
from .api.orders import router as orders_router
from .api.cashier_api import router as cashier_router
from .api.kds_routes import router as kds_router
from .api.handover_routes import router as handover_router
from .api.table_routes import router as table_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时创建表（开发环境）
    await init_db()
    yield


app = FastAPI(
    title="TunxiangOS tx-trade",
    version="3.0.0",
    description="交易履约微服务 — 收银引擎",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(orders_router)
app.include_router(cashier_router)
app.include_router(kds_router)
app.include_router(handover_router)
app.include_router(table_router)


@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-trade", "version": "3.0.0"}}
