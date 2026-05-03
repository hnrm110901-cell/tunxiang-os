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

import asyncio

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

try:
    from shared.feature_flags import is_enabled

    _FLAG_SDK_AVAILABLE = True
except ImportError:
    _FLAG_SDK_AVAILABLE = False

    def is_enabled(flag, context=None):
        return True


logger = structlog.get_logger(__name__)

# 全局 scheduler 实例
_scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")

# 导入路由
from .api.approval_routes import router as approval_router
from .api.budget_routes import router as budget_router
from .api.contract_routes import router as contract_router
from .api.cost_attribution_routes import router as cost_attribution_router
from .api.cost_routes import router as cost_routes_router
from .api.event_webhook_routes import router as event_webhook_router
from .api.expense_dashboard import router as expense_dashboard_router
from .api.expense_routes import router as expense_router
from .api.invoice_routes import router as invoice_router
from .api.petty_cash_routes import router as petty_cash_router
from .api.procurement_routes import router as procurement_router
from .api.report_routes import router as report_router
from .api.travel_routes import router as travel_router

app = FastAPI(title="tx-expense · 屯象费控管理服务", version="1.0.0", description="连锁餐饮企业全链路费用管控系统")

# Prometheus
from prometheus_fastapi_instrumentator import Instrumentator

Instrumentator().instrument(app).expose(app)

# CORS — 生产环境通过 CORS_ALLOW_ORIGINS 环境变量覆盖
import os

_allow_origins = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(expense_router, prefix="/api/v1/expense", tags=["费用申请"])
app.include_router(approval_router, prefix="/api/v1/expense/approval", tags=["审批流"])
app.include_router(petty_cash_router, prefix="/api/v1/expense/petty-cash", tags=["备用金"])
app.include_router(invoice_router, prefix="/api/v1/expense/invoices", tags=["发票"])
app.include_router(travel_router, prefix="/api/v1/expense/travel", tags=["差旅"])
app.include_router(budget_router, prefix="/api/v1/expense/budgets", tags=["预算"])
app.include_router(contract_router, prefix="/api/v1/expense/contracts", tags=["合同台账"])
app.include_router(cost_attribution_router, prefix="/api/v1/expense/cost-attribution", tags=["成本归因"])
app.include_router(cost_routes_router, prefix="/api/v1/expense/costs", tags=["成本归集日报"])
app.include_router(expense_dashboard_router, prefix="/api/v1/expense/dashboard", tags=["费控看板"])
app.include_router(event_webhook_router, tags=["内部事件"])
app.include_router(procurement_router, prefix="/api/v1/expense/procurement", tags=["采购付款"])
app.include_router(report_router, prefix="/api/v1/expense/reports", tags=["费控报表"])


@app.get("/health")
async def health():
    """服务健康检查端点"""
    return {"status": "ok", "service": "tx-expense", "version": "1.0.0"}


async def _run_monthly_petty_cash() -> None:
    from .workers.monthly_petty_cash import MonthlyPettyCashWorker

    try:
        await MonthlyPettyCashWorker().run()
    except Exception as exc:
        logger.error("scheduler.monthly_petty_cash.failed", error=str(exc), exc_info=True)


async def _run_daily_cost_attribution() -> None:
    from .workers.daily_cost_attribution import DailyCostAttributionWorker

    try:
        await DailyCostAttributionWorker().run()
    except Exception as exc:
        logger.error("scheduler.daily_cost_attribution.failed", error=str(exc), exc_info=True)


@app.on_event("startup")
async def startup() -> None:
    logger.info("tx_expense_started", service="tx-expense", version="1.0.0")

    # 每月25日 00:30：备用金月结
    _scheduler.add_job(
        lambda: asyncio.create_task(_run_monthly_petty_cash()),
        "cron",
        day=25,
        hour=0,
        minute=30,
        id="monthly_petty_cash",
        replace_existing=True,
    )
    # 每日 23:00：成本归因日报
    _scheduler.add_job(
        lambda: asyncio.create_task(_run_daily_cost_attribution()),
        "cron",
        hour=23,
        minute=0,
        id="daily_cost_attribution",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("expense_scheduler_started", jobs=[j.id for j in _scheduler.get_jobs()])


@app.on_event("shutdown")
async def shutdown() -> None:
    _scheduler.shutdown(wait=False)
    logger.info("tx_expense_stopped", service="tx-expense", version="1.0.0")
