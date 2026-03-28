"""tx-supply — 域D 供应链微服务

库存管理、采购、供应商、损耗追踪、需求预测、BOM管理、理论成本计算
来源：12 个 service 文件迁移自 tunxiang V2.x
"""
from fastapi import FastAPI
from .api.inventory import router as inv_router
from .api.bom_routes import router as bom_router
from .api.deduction_routes import router as deduction_router
from .api.receiving_routes import router as receiving_router

app = FastAPI(title="TunxiangOS tx-supply", version="3.0.0")
app.include_router(inv_router)
app.include_router(bom_router)
app.include_router(deduction_router)
app.include_router(receiving_router)

@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-supply", "version": "3.0.0"}}
