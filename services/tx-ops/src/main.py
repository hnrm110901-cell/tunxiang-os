"""tx-ops — 日清日结操作层微服务 (E1-E8)"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.approval_center_routes import router as approval_center_router
from .api.approval_workflow_routes import router as approval_router
from .api.daily_ops import router
from .api.daily_settlement_routes import router as settlement_router
from .api.daily_summary_routes import router as daily_summary_router
from .api.dispatch_routes import router as dispatch_router
from .api.inspection_routes import router as inspection_router
from .api.issues_routes import router as issues_router
from .api.notification_routes import router as notification_router
from .api.notification_center_routes import router as notification_center_router
from .api.notification_center_routes import template_router as notification_template_router
from .api.ops_routes import router as ops_router
from .api.peak_routes import router as peak_router
from .api.performance_routes import router as performance_router
from .api.regional_routes import router as regional_router
from .api.review_routes import router as review_router
from .api.shift_routes import router as shift_router
from .api.store_clone import router as clone_router
from .api.food_safety_routes import router as food_safety_router
from .api.energy_routes import router as energy_router
from .api.public_opinion_routes import router as public_opinion_router
from .api.safety_inspection_router import router as safety_inspection_router
from .api.haccp_routes import router as haccp_router

app = FastAPI(title="TunxiangOS tx-ops", version="3.0.0", description="日清日结操作层")
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
app.include_router(food_safety_router)        # Phase 4: 食安合规（事件驱动）
app.include_router(safety_inspection_router) # Phase 4: 食安巡检（结构化DB）
app.include_router(energy_router)            # Phase 4: 能耗管理
app.include_router(public_opinion_router)    # Phase 4: 舆情监控
app.include_router(haccp_router)             # Phase 4: HACCP检查计划数字化


@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-ops", "version": "3.0.0"}}
