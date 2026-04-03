"""tx-finance — 域E 财务结算微服务

FCT业财税、预算、现金流、月报、成本分析、P&L、凭证生成
"""
from contextlib import asynccontextmanager

from api.analytics_routes import router as analytics_router
from api.cost_routes import router as cost_router
from api.cost_routes_v2 import router as cost_v2_router
from api.e_invoice_routes import router as invoice_router
from api.erp_routes import router as erp_router
from api.finance import router as finance_router
from api.finance_cost_routes import router as finance_cost_router
from api.finance_pl_routes import router as finance_pl_router
from api.pl_routes import router as pl_router
from api.pnl_routes import router as pnl_router
from api.reconciliation_routes import router as reconciliation_router
from api.revenue_aggregation_routes import router as revenue_aggregation_router
from api.revenue_routes import router as revenue_router
from api.seafood_loss_routes import router as seafood_loss_router
from api.settlement_routes import router as settlement_router
from api.fund_settlement_routes import router as fund_settlement_router
from api.split_routes import router as split_router
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.ontology.src.database import init_db


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
app.include_router(cost_router,    prefix="/api/v1/costs")
app.include_router(pl_router,      prefix="/api/v1/pl")
app.include_router(invoice_router, prefix="/api/v1/invoices")
app.include_router(settlement_router)
app.include_router(fund_settlement_router)
app.include_router(erp_router)
app.include_router(reconciliation_router, prefix="/api/v1")
app.include_router(revenue_aggregation_router)
app.include_router(finance_cost_router, prefix="/api/v1/finance")
app.include_router(finance_pl_router,   prefix="/api/v1/finance")
app.include_router(split_router)  # /api/v1/finance/splits/* — v100 分润规则与分账流水

# v117 财务计算引擎路由
app.include_router(pnl_router,         prefix="/api/v1/finance")   # /pnl/*
app.include_router(cost_v2_router,     prefix="/api/v1/finance")   # /costs/* /configs/*
app.include_router(revenue_router,     prefix="/api/v1/finance")   # /revenue/*
app.include_router(seafood_loss_router, prefix="/api/v1/finance")  # /seafood-loss/*


@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-finance", "version": "4.0.0"}}
