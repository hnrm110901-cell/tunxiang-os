"""tx-ops — 日清日结操作层微服务 (E1-E8)"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .api.daily_ops import router
from .api.store_clone import router as clone_router
from .api.ops_routes import router as ops_router
from .api.review_routes import router as review_router
from .api.regional_routes import router as regional_router
from .api.peak_routes import router as peak_router
from .api.dispatch_routes import router as dispatch_router
from .api.notification_routes import router as notification_router
from .api.shift_routes import router as shift_router
from .api.daily_summary_routes import router as daily_summary_router
from .api.issues_routes import router as issues_router
from .api.inspection_routes import router as inspection_router
from .api.performance_routes import router as performance_router
from .api.daily_settlement_routes import router as settlement_router
from .api.approval_workflow_routes import router as approval_router

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


@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-ops", "version": "3.0.0"}}
