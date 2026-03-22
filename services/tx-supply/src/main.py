"""tx-supply — 域D 供应链微服务

库存管理、采购、供应商、损耗追踪、需求预测
来源：12 个 service 文件迁移自 tunxiang V2.x
"""
from fastapi import FastAPI
from .api.inventory import router as inv_router

app = FastAPI(title="TunxiangOS tx-supply", version="3.0.0")
app.include_router(inv_router)

@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-supply", "version": "3.0.0"}}
