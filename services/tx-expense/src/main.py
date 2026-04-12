"""tx-expense · 屯象费控管理服务 (:8015)

负责连锁餐饮企业全链路费用管控:
- 费用申请 (10个场景/科目体系/附件)
- 审批流 (多级审批/路由规则/转交)
- 备用金 (借款/还款/盘点)
- 发票 (采集/核验/归档)
- 差旅 (出差申请/实报实销)
- 预算 (年度/季度预算管控)
- 合同台账 (合同签署/到期提醒)
- 成本归因 (费用分摊/门店归因)
- 费控看板 (汇总分析/预算执行率)
"""
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

try:
    from shared.feature_flags import is_enabled, FlagContext
    _FLAG_SDK_AVAILABLE = True
except ImportError:
    _FLAG_SDK_AVAILABLE = False
    def is_enabled(flag, context=None): return True

logger = structlog.get_logger(__name__)

# 导入路由
from .api.expense_routes import router as expense_router
from .api.approval_routes import router as approval_router
from .api.petty_cash_routes import router as petty_cash_router
from .api.invoice_routes import router as invoice_router
from .api.travel_routes import router as travel_router
from .api.budget_routes import router as budget_router
from .api.contract_routes import router as contract_router
from .api.cost_attribution_routes import router as cost_attribution_router
from .api.expense_dashboard import router as expense_dashboard_router
from .api.event_webhook_routes import router as event_webhook_router

app = FastAPI(
    title="tx-expense · 屯象费控管理服务",
    version="1.0.0",
    description="连锁餐饮企业全链路费用管控系统"
)

# Prometheus
from prometheus_fastapi_instrumentator import Instrumentator
Instrumentator().instrument(app).expose(app)

# CORS — 生产环境通过 CORS_ALLOW_ORIGINS 环境变量覆盖
import os
_allow_origins = os.getenv("CORS_ALLOW_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(expense_router,           prefix="/api/v1/expense",                  tags=["费用申请"])
app.include_router(approval_router,          prefix="/api/v1/expense/approval",          tags=["审批流"])
app.include_router(petty_cash_router,        prefix="/api/v1/expense/petty-cash",        tags=["备用金"])
app.include_router(invoice_router,           prefix="/api/v1/expense/invoices",          tags=["发票"])
app.include_router(travel_router,            prefix="/api/v1/expense/travel",            tags=["差旅"])
app.include_router(budget_router,            prefix="/api/v1/expense/budgets",           tags=["预算"])
app.include_router(contract_router,          prefix="/api/v1/expense/contracts",         tags=["合同台账"])
app.include_router(cost_attribution_router,  prefix="/api/v1/expense/cost-attribution",  tags=["成本归因"])
app.include_router(expense_dashboard_router, prefix="/api/v1/expense/dashboard",         tags=["费控看板"])
app.include_router(event_webhook_router,                                                 tags=["内部事件"])


@app.get("/health")
async def health():
    """服务健康检查端点"""
    return {"status": "ok", "service": "tx-expense", "version": "1.0.0"}


@app.on_event("startup")
async def startup() -> None:
    logger.info("tx_expense_started", service="tx-expense", version="1.0.0")


@app.on_event("shutdown")
async def shutdown() -> None:
    logger.info("tx_expense_stopped", service="tx-expense", version="1.0.0")
