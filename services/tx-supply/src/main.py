"""tx-supply — 域D 供应链微服务

库存管理、采购、供应商、损耗追踪、需求预测、BOM管理、理论成本计算
来源：12 个 service 文件迁移自 tunxiang V2.x
"""
from fastapi import FastAPI
from .api.inventory import router as inv_router
from .api.bom_routes import router as bom_router
from .api.deduction_routes import router as deduction_router
from .api.receiving_routes import router as receiving_router
from .api.kingdee_routes import router as kingdee_router
from .api.requisition_routes import router as requisition_router
from .api.dept_issue_routes import router as dept_issue_router
from .api.warehouse_ops_routes import router as warehouse_ops_router
from .api.period_close_routes import router as period_close_router
from .api.craft_routes import router as craft_router
from .api.distribution_routes import router as distribution_router
from .api.food_safety_routes import router as food_safety_router
from .api.seafood_routes import router as seafood_router
from .api.trace_routes import router as trace_router
from .api.central_kitchen_routes import router as ck_router
from .api.procurement_recommend_routes import router as procurement_recommend_router
from .api.smart_replenishment_routes import router as smart_replenishment_router
from .api.delivery_route_routes import router as delivery_route_router
from .api.supplier_scoring_routes import router as supplier_scoring_router

app = FastAPI(title="TunxiangOS tx-supply", version="3.0.0")
app.include_router(inv_router)
app.include_router(bom_router)
app.include_router(deduction_router)
app.include_router(receiving_router)
app.include_router(kingdee_router)
app.include_router(requisition_router)
app.include_router(dept_issue_router)
app.include_router(warehouse_ops_router)
app.include_router(period_close_router)
app.include_router(craft_router)
app.include_router(distribution_router)
app.include_router(food_safety_router)
app.include_router(seafood_router)
app.include_router(trace_router)
app.include_router(ck_router)
app.include_router(procurement_recommend_router,  prefix="/api/v1/procurement")
app.include_router(smart_replenishment_router,   prefix="/api/v1/smart-replenishment")
app.include_router(delivery_route_router)
app.include_router(supplier_scoring_router)

@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-supply", "version": "3.0.0"}}
