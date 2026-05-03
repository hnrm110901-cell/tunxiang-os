"""tx-forge — Forge 开发者市场微服务 (port 8013)

管理ISV生态、商品审核、安装订阅、收入结算、AI OPS可观测性、信任治理 · MCP · Ontology。
"""

import os

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

logger = structlog.get_logger(__name__)

from .api.ai_ops_routes import router as ai_ops_router
from .api.alliance_routes import router as alliance_router
from .api.analytics_routes import router as analytics_router
from .api.app_routes import router as app_router
from .api.auto_review_routes import router as auto_review_router
from .api.builder_routes import router as builder_router
from .api.developer_routes import router as developer_router
from .api.discovery_routes import router as discovery_router
from .api.ecosystem_routes import router as ecosystem_router
from .api.evidence_routes import router as evidence_router
from .api.installation_routes import router as installation_router
from .api.mcp_routes import router as mcp_router
from .api.ontology_routes import router as ontology_router
from .api.outcome_routes import router as outcome_router
from .api.payout_routes import router as payout_router
from .api.review_routes import router as review_router
from .api.runtime_routes import router as runtime_router
from .api.sandbox_routes import router as sandbox_router
from .api.sdk_routes import router as sdk_router
from .api.token_routes import router as token_router
from .api.trust_routes import router as trust_router
from .api.workflow_routes import router as workflow_router

app = FastAPI(
    title="TunxiangOS tx-forge",
    version="3.0.0",
    description="Forge开发者市场 · ISV管理 · AI OPS · 信任治理 · MCP · Ontology · 结果计价 · Token计量 · 智能发现 · 证据卡片 · 低代码构建 · AI审核 · 跨品牌联盟 · Agent编排 · 生态健康",
)

Instrumentator().instrument(app).expose(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(developer_router, tags=["ISV开发者"])
app.include_router(app_router, tags=["应用市场"])
app.include_router(review_router, tags=["审核管理"])
app.include_router(installation_router, tags=["安装管理"])
app.include_router(sdk_router, tags=["SDK密钥"])
app.include_router(sandbox_router, tags=["沙箱环境"])
app.include_router(payout_router, tags=["收入结算"])
app.include_router(analytics_router, tags=["市场分析"])
app.include_router(ai_ops_router, tags=["AI可观测性"])
app.include_router(trust_router, tags=["信任管理"])
app.include_router(runtime_router, tags=["运行时策略"])
app.include_router(mcp_router, tags=["MCP协议"])
app.include_router(ontology_router, tags=["Ontology绑定"])
app.include_router(outcome_router, tags=["结果计价"])
app.include_router(token_router, tags=["Token计量"])
app.include_router(discovery_router, tags=["智能发现"])
app.include_router(evidence_router, tags=["证据卡片"])
app.include_router(builder_router, tags=["Forge Builder"])
app.include_router(auto_review_router, tags=["AI审核"])
app.include_router(alliance_router, tags=["跨品牌联盟"])
app.include_router(workflow_router, tags=["Agent编排"])
app.include_router(ecosystem_router, tags=["生态健康"])


@app.on_event("startup")
async def startup():
    logger.info("tx_forge_started", version="3.0.0", port=8013)


@app.get("/health")
async def health():
    return {"ok": True, "service": "tx-forge", "version": "3.0.0"}
