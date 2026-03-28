"""tx-member — 域C 会员CDP微服务

Golden ID 全渠道画像、RFM 分层、营销活动、用户旅程、私域运营
来源：35 个 service 文件迁移自 tunxiang V2.x
"""
from fastapi import FastAPI
from api.members import router as member_router
from api.marketing import router as marketing_router
from api.analytics_routes import router as analytics_router
from api.customer_depth_routes import router as customer_depth_router
from api.card_routes import router as card_router
from api.points_routes import router as points_router
from api.coupon_engine_routes import router as coupon_engine_router
from api.gift_card_routes import router as gift_card_router

app = FastAPI(title="TunxiangOS tx-member", version="3.0.0")
app.include_router(member_router)
app.include_router(marketing_router)
app.include_router(analytics_router)
app.include_router(customer_depth_router)
app.include_router(card_router)
app.include_router(points_router)
app.include_router(coupon_engine_router)
app.include_router(gift_card_router)

@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-member", "version": "3.0.0"}}
