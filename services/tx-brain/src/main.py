"""tx-brain FastAPI Main — 屯象OS 智能内核统一服务

注册所有 brain 服务：
- Voice AI (ASR + NLU + Dialog + TTS)
- CFO Dashboard
- Evolution 2030
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Feature Flag SDK（try/except 保护，SDK不可用时自动降级为全量开启）
try:
    from shared.feature_flags import is_enabled
    from shared.feature_flags.flag_names import AgentFlags

    _FLAG_SDK_AVAILABLE = True
except ImportError:
    _FLAG_SDK_AVAILABLE = False

    def is_enabled(flag, context=None):
        return True  # noqa: E731


from .api.activity_roi_routes import router as activity_roi_router  # D3b 活动 ROI 预测
from .api.brain_routes import router as brain_router
from .api.content_hub_routes import router as content_hub_router  # AI营销内容中枢（v207）
from .api.dish_pricing_routes import router as dish_pricing_router  # D3c — 菜品动态定价
from .api.voice_api import router as voice_router
from .api.voice_order_stable_routes import router as voice_stable_router
from .services.cfo_dashboard import CFODashboardService
from .services.evolution_2030 import Evolution2030Service
from .services.voice_orchestrator import VoiceOrchestrator
from .services.voice_session import VoiceSessionManager

logger = structlog.get_logger()

# ─── Service Singletons ─────────────────────────────────────────

voice_orchestrator = VoiceOrchestrator()
voice_session_mgr = VoiceSessionManager()
cfo_dashboard = CFODashboardService()
evolution_2030 = Evolution2030Service()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup & shutdown."""
    logger.info(
        "tx_brain_starting",
        services=[
            "voice_orchestrator",
            "voice_session_mgr",
            "cfo_dashboard",
            "evolution_2030",
            "discount_guardian",
            "member_insight",
        ],
    )

    # ── Feature Flag 启动检查 ────────────────────────────────────────
    # AgentFlags.FINANCE_PNL_SUMMARY: P&L AI摘要功能
    # Flag关闭时：ModelRouter应使用轻量模型或返回占位结果，避免不必要的LLM调用
    if is_enabled(AgentFlags.FINANCE_PNL_SUMMARY):
        logger.info(
            "feature_flag_enabled",
            flag=AgentFlags.FINANCE_PNL_SUMMARY,
            note="P&L AI摘要已激活，ModelRouter将使用完整推理链路",
        )
    else:
        logger.info(
            "feature_flag_disabled",
            flag=AgentFlags.FINANCE_PNL_SUMMARY,
            note="P&L AI摘要已关闭，ModelRouter降级为轻量模型或占位结果",
        )

    yield
    logger.info("tx_brain_shutting_down")


# ─── FastAPI App ─────────────────────────────────────────────────

app = FastAPI(
    title="tx-brain — 屯象OS 智能内核",
    description="Voice AI + CFO Dashboard + 2030 Evolution",
    version="3.0.0-sprint1112",
    lifespan=lifespan,
)

from prometheus_client import Counter, Histogram
from prometheus_fastapi_instrumentator import Instrumentator

llm_requests_total = Counter("llm_api_requests_total", "Total LLM API requests", ["model", "status"])
llm_request_duration = Histogram("llm_request_duration_seconds", "LLM API request duration")
Instrumentator().instrument(app).expose(app)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Register Routers ────────────────────────────────────────────

app.include_router(voice_router)
app.include_router(brain_router)
app.include_router(voice_stable_router)
app.include_router(content_hub_router)  # /api/v1/brain/content/* — AIGC 营销内容生成（v207）
app.include_router(activity_roi_router)  # /api/v1/agents/activity-roi/* — 活动 ROI 预测（D3b）
app.include_router(dish_pricing_router)  # /api/v1/agents/dish-pricing/* — 菜品动态定价（D3c）


# ── Sprint G 路由自动挂载（PR #97 A/B 实验框架 合入后自动生效）──
from pathlib import Path as _Path  # noqa: E402

from shared.service_utils import auto_mount_routes, validate_result  # noqa: E402

_sprint_g_mount = auto_mount_routes(
    app,
    pkg=__package__,
    api_dir=_Path(__file__).parent / "api",
    modules=[
        ("ab_experiment_routes", "router"),  # G #97
    ],
)
validate_result(_sprint_g_mount)


# ─── Health & Info ───────────────────────────────────────────────


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "tx-brain",
        "version": "3.0.0-sprint1112",
        "components": {
            "voice_orchestrator": "ready",
            "voice_session": "ready",
            "cfo_dashboard": "ready",
            "evolution_2030": "ready",
            "discount_guardian": "ready",
            "member_insight": "ready",
        },
    }


@app.get("/api/v1/brain/info")
async def brain_info() -> dict[str, Any]:
    return {
        "ok": True,
        "data": {
            "service": "tx-brain",
            "sprint": "11-12",
            "capabilities": [
                "voice_asr",
                "voice_nlu",
                "voice_dialog",
                "voice_action",
                "voice_response",
                "cfo_cash_flow",
                "cfo_consolidation",
                "cfo_tax",
                "cfo_cost_analytics",
                "cfo_kpis",
                "cfo_budget_vs_actual",
                "cfo_forecast",
                "cfo_executive_summary",
                "evolution_feature_flags",
                "evolution_multi_region",
                "evolution_multi_currency",
                "evolution_agent_levels",
                "discount_guardian_agent",
                "member_insight_agent",
            ],
        },
    }


# ─── Global Error Handler ───────────────────────────────────────


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"ok": False, "error": {"code": "VALUE_ERROR", "message": str(exc)}},
    )


@app.exception_handler(KeyError)
async def key_error_handler(request: Request, exc: KeyError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"ok": False, "error": {"code": "KEY_ERROR", "message": str(exc)}},
    )
