"""tx-finance — 域E 财务结算微服务

FCT业财税、预算、现金流、月报、成本分析
来源：30 个 service 文件迁移自 tunxiang V2.x
"""
from fastapi import FastAPI
from .api.finance import router as finance_router

app = FastAPI(title="TunxiangOS tx-finance", version="3.0.0")
app.include_router(finance_router)

@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-finance", "version": "3.0.0"}}
