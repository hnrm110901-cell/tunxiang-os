"""tx-malaysia — 马来西亚本地化微服务

SST 税引擎（Sprint 1.3）+ LHDN e-Invoice（Sprint 1.5）
+ SSM 企业验证 + 政府补贴计费（Phase 2 Sprint 2.5）
+ 马来西亚仪表盘 & AI 洞察（Phase 3 Sprint 3.3）
+ 跨区域业务 & SME 入驻（Phase 3 Sprint 3.6）

注：合并到 main 时需同时启用主分支已存在的路由文件。
"""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.ontology.src.database import init_db

from .api.my_dashboard_routes import router as my_dashboard_router
from .api.ai_insights_routes import router as ai_insights_router
from .api.regional_routes import router as regional_router
from .api.sme_onboarding_routes import router as onboarding_router

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("tx_malaysia_started", port=8015)
    yield
    logger.info("tx_malaysia_stopped")


app = FastAPI(
    title="TunxiangOS tx-malaysia",
    version="1.0.0",
    description="马来西亚本地化 — SST / e-Invoice / SSM / 政府补贴 / 仪表盘 / AI 洞察",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Sprint 3.3: 马来西亚仪表盘 & AI 洞察
app.include_router(my_dashboard_router)
app.include_router(ai_insights_router)

# Sprint 3.6: 跨区域业务 & SME 入驻
app.include_router(regional_router)
app.include_router(onboarding_router)


# ── 合并提醒 ───────────────────────────────────────────────────────
# 合并到 main 时，请在此处添加主分支已有的路由：
#
#   from .api.e_invoice_routes import router as einvoice_router
#   from .api.pdpa_routes import router as pdpa_router
#   from .api.ssm_routes import router as ssm_router
#   from .api.sst_routes import router as sst_router
#   from .api.subsidy_routes import router as subsidy_router
#
#   app.include_router(sst_router)
#   app.include_router(einvoice_router)
#   app.include_router(pdpa_router)
#   app.include_router(ssm_router)
#   app.include_router(subsidy_router)
#
# Sprint 3.6 新增（已在此分支注册）：
#   from .api.regional_routes import router as regional_router
#   from .api.sme_onboarding_routes import router as onboarding_router
#
#   app.include_router(regional_router)
#   app.include_router(onboarding_router)
# ───────────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"ok": True, "service": "tx-malaysia", "version": "1.0.0"}
