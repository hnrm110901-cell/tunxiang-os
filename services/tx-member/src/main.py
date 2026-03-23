"""tx-member — 域C 会员CDP微服务

Golden ID 全渠道画像、RFM 分层、营销活动、用户旅程、私域运营
来源：35 个 service 文件迁移自 tunxiang V2.x
"""
from fastapi import FastAPI
from api.members import router as member_router

app = FastAPI(title="TunxiangOS tx-member", version="3.0.0")
app.include_router(member_router)

@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-member", "version": "3.0.0"}}
