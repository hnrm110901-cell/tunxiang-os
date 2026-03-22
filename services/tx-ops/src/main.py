"""tx-ops — 日清日结操作层微服务 (E1-E8)"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .api.daily_ops import router

app = FastAPI(title="TunxiangOS tx-ops", version="3.0.0", description="日清日结操作层")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(router)

@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-ops", "version": "3.0.0"}}
