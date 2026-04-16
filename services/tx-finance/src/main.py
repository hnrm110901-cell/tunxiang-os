"""tx-finance — 域E 财务结算微服务

FCT业财税、预算、现金流、月报、成本分析、P&L、凭证生成
"""
from contextlib import asynccontextmanager

from .api.agreement_unit_routes import router as agreement_unit_router
from .api.analytics_routes import router as analytics_router
from .api.approval_callback_routes import router as approval_callback_router
from .api.cost_routes import router as cost_router
from .api.cost_routes_v2 import router as cost_v2_router
from .api.credit_account_routes import router as credit_account_router
from .api.deposit_routes import router as deposit_router
from .api.e_invoice_routes import router as invoice_router
from .api.budget_routes import router as budget_router
from .api.budget_v2_routes import router as budget_v2_router
from .api.payroll_routes import router as payroll_router
from .api.vat_routes import router as vat_router
from .api.vat_ledger_routes import router as vat_ledger_router
from .api.split_payment_routes import router as split_payment_router
from .api.erp_routes import router as erp_router
from .api.finance import router as finance_router
from .api.finance_cost_routes import router as finance_cost_router
from .api.finance_pl_routes import router as finance_pl_router
from .api.pl_routes import router as pl_router
from .api.pnl_routes import router as pnl_router
from .api.payment_reconciliation_routes import router as payment_reconciliation_router
from .api.reconciliation_routes import router as reconciliation_router
from .api.revenue_aggregation_routes import router as revenue_aggregation_router
from .api.revenue_routes import router as revenue_router
from .api.seafood_loss_routes import router as seafood_loss_router
from .api.settlement_routes import router as settlement_router
from .api.fund_settlement_routes import router as fund_settlement_router
from .api.split_routes import router as split_router
from .api.wine_storage_routes import router as wine_storage_router
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

from prometheus_fastapi_instrumentator import Instrumentator
Instrumentator().instrument(app).expose(app)

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

# v156 财务应收管理：押金 / 存酒 / 企业挂账
app.include_router(deposit_router)        # /api/v1/deposits/*
app.include_router(wine_storage_router)   # /api/v1/wine-storage/*
app.include_router(credit_account_router)     # /api/v1/credit/*
app.include_router(approval_callback_router)  # /api/v1/credit/agreements/{id}/approval-callback

# TC-P1-09 协议单位体系（企业挂账/预付管理）
app.include_router(agreement_unit_router)  # /api/v1/agreement-units/*

# TC-P0-06 支付对账报表
app.include_router(payment_reconciliation_router)  # /api/v1/finance/payment-reconciliation etc.

# Y-F9 税务管理：增值税销项/进项台账 + 诺诺/税局接口 POC + P&L 科目映射
app.include_router(vat_ledger_router)   # /api/v1/finance/vat/*

# Y-B2 聚合支付/分账：微信/支付宝分账 + 幂等通知 + SplitEngine + 调账
app.include_router(split_payment_router)  # /api/v1/finance/split/*

# v101 预算管理：预算计划 CRUD + 审批 + 执行录入 + 进度查询
app.include_router(budget_router)          # /api/v1/finance/budgets/*

# v118 预算管理 v2：面向前端报表的快捷接口（年度列表/月度创建/执行情况）
app.include_router(budget_v2_router, prefix="/api/v1/finance")  # /api/v1/finance/budget/*

# 薪资管理：薪资单 CRUD + 审批 + 发薪标记 + 方案配置 + 历史汇总
app.include_router(payroll_router)         # /api/v1/finance/payroll/*

# v102 企业增值税：申报单管理 + 进项发票录入/验证 + 税率参考
app.include_router(vat_router)             # /api/v1/finance/vat/*


@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-finance", "version": "4.0.0"}}
