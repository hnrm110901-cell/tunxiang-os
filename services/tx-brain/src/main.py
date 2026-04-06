"""tx-brain FastAPI Main — 屯象OS 智能内核统一服务

注册所有 brain 服务：
- Voice AI (ASR + NLU + Dialog + TTS)
- CFO Dashboard
- Evolution 2030
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.brain_routes import router as brain_router
from .api.voice_api import router as voice_router
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
    logger.info("tx_brain_starting", services=[
        "voice_orchestrator",
        "voice_session_mgr",
        "cfo_dashboard",
        "evolution_2030",
        "discount_guardian",
        "member_insight",
    ])
    yield
    logger.info("tx_brain_shutting_down")


# ─── FastAPI App ─────────────────────────────────────────────────

app = FastAPI(
    title="tx-brain — 屯象OS 智能内核",
    description="Voice AI + CFO Dashboard + 2030 Evolution",
    version="3.0.0-sprint1112",
    lifespan=lifespan,
)

from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Counter, Histogram
llm_requests_total = Counter('llm_api_requests_total', 'Total LLM API requests', ['model', 'status'])
llm_request_duration = Histogram('llm_request_duration_seconds', 'LLM API request duration')
Instrumentator().instrument(app).expose(app)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Register Routers ────────────────────────────────────────────

app.include_router(voice_router)
app.include_router(brain_router)


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
