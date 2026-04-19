"""tx-ops — 日清日结操作层微服务 (E1-E8)"""

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Feature Flag SDK（try/except 保护，SDK不可用时自动降级为全量开启）
try:
    from shared.feature_flags import FlagContext, is_enabled
    from shared.feature_flags.flag_names import AgentFlags

    _FLAG_SDK_AVAILABLE = True
except ImportError:
    _FLAG_SDK_AVAILABLE = False

    def is_enabled(flag, context=None):
        return True  # noqa: E731


logger = structlog.get_logger(__name__)

from .api.approval_center_routes import router as approval_center_router
from .api.approval_workflow_routes import router as approval_router
from .api.daily_ops import router
from .api.daily_settlement_routes import router as settlement_router
from .api.daily_summary_routes import router as daily_summary_router
from .api.dispatch_routes import router as dispatch_router
from .api.energy_routes import router as energy_router
from .api.food_safety_routes import router as food_safety_router
from .api.haccp_routes import router as haccp_router
from .api.inspection_routes import router as inspection_router
from .api.issues_routes import router as issues_router
from .api.notification_center_routes import router as notification_center_router
from .api.notification_center_routes import template_router as notification_template_router
from .api.notification_routes import router as notification_router
from .api.ops_routes import router as ops_router
from .api.peak_routes import router as peak_router
from .api.performance_routes import router as performance_router
from .api.public_opinion_routes import router as public_opinion_router
from .api.regional_routes import router as regional_router
from .api.review_routes import router as review_router
from .api.safety_inspection_router import router as safety_inspection_router
from .api.settlement_monitor_routes import router as settlement_monitor_router
from .api.shift_routes import router as shift_router
from .api.store_clone import router as clone_router
from .api.sync_management_routes import router as sync_management_router
from .api.telemetry_routes import router as telemetry_router
from .api.trial_data_routes import router as trial_data_router

app = FastAPI(title="TunxiangOS tx-ops", version="3.0.0", description="日清日结操作层")

# ── Feature Flag 启动检查 ──────────────────────────────────────────
# AgentFlags.OPS_DAILY_REVIEW: 日清E1-E8全流程追踪Agent
if is_enabled(AgentFlags.OPS_DAILY_REVIEW):
    logger.info("feature_flag_enabled", flag=AgentFlags.OPS_DAILY_REVIEW, note="日清E1-E8追踪Agent已激活")
else:
    logger.info(
        "feature_flag_disabled", flag=AgentFlags.OPS_DAILY_REVIEW, note="日清追踪Agent已关闭，仅提供基础日结功能"
    )

# AgentFlags.TRADE_DISCOUNT_ALERT: 食安合规+折扣健康预警（P0级）
if is_enabled(AgentFlags.TRADE_DISCOUNT_ALERT):
    logger.info(
        "feature_flag_enabled", flag=AgentFlags.TRADE_DISCOUNT_ALERT, note="折扣健康预警Agent已激活（P0级安全功能）"
    )
else:
    logger.warning(
        "feature_flag_disabled",
        flag=AgentFlags.TRADE_DISCOUNT_ALERT,
        note="折扣预警Agent已关闭，食安合规调度任务将跳过预警推送",
    )

from prometheus_fastapi_instrumentator import Instrumentator

Instrumentator().instrument(app).expose(app)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(router)
app.include_router(clone_router)
app.include_router(ops_router)
app.include_router(review_router)
app.include_router(regional_router)
app.include_router(peak_router)
app.include_router(dispatch_router)
app.include_router(notification_router)
# E1-E8 日清日结完整实现
app.include_router(shift_router)
app.include_router(daily_summary_router)
app.include_router(issues_router)
app.include_router(inspection_router)
app.include_router(performance_router)
app.include_router(settlement_router)
app.include_router(approval_router)
app.include_router(approval_center_router)
app.include_router(notification_center_router)
app.include_router(notification_template_router)
app.include_router(food_safety_router)  # Phase 4: 食安合规（事件驱动）
app.include_router(safety_inspection_router)  # Phase 4: 食安巡检（结构化DB）
app.include_router(energy_router)  # Phase 4: 能耗管理
app.include_router(public_opinion_router)  # Phase 4: 舆情监控
app.include_router(haccp_router)  # Phase 4: HACCP检查计划数字化
app.include_router(settlement_monitor_router)  # TC-P0-05: 日结监控看板（总部多店聚合）
app.include_router(trial_data_router)  # TC-P1-11: 试营业数据清除
app.include_router(sync_management_router)  # 四系统数据同步协调器管理API
app.include_router(telemetry_router)  # Sprint A1: POS 前端崩溃上报


@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-ops", "version": "3.0.0"}}
