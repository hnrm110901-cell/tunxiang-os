"""tx-finance — 域E 财务结算微服务

FCT业财税、预算、现金流、月报、成本分析、P&L、凭证生成
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.ontology.src.database import init_db
from api.finance import router as finance_router
from api.analytics_routes import router as analytics_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="TunxiangOS tx-finance",
    version="4.0.0",
    description="财务结算微服务 — 营收/成本/P&L/凭证/预算",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(finance_router)
app.include_router(analytics_router)


@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-finance", "version": "4.0.0"}}
