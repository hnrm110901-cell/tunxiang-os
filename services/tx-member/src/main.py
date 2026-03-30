"""tx-member — 域C 会员CDP微服务

Golden ID 全渠道画像、RFM 分层、营销活动、用户旅程、私域运营、储值卡、积分商城、付费会员
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.ontology.src.database import init_db
from api.members import router as member_router
from api.marketing import router as marketing_router
from api.analytics_routes import router as analytics_router
from api.customer_depth_routes import router as customer_depth_router
from api.card_routes import router as card_router
from api.points_routes import router as points_router
from api.coupon_engine_routes import router as coupon_engine_router
from api.gift_card_routes import router as gift_card_router
from api.smart_dispatch_routes import router as smart_dispatch_router
from api.stored_value_routes import router as stored_value_router
from api.premium_card_routes import router as premium_card_router
from api.points_mall_routes import router as points_mall_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="TunxiangOS tx-member",
    version="4.0.0",
    description="会员CDP — 储值卡/积分商城/付费会员/营销/优惠券",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(member_router)
app.include_router(marketing_router)
app.include_router(analytics_router)
app.include_router(customer_depth_router)
app.include_router(card_router)
app.include_router(points_router)
app.include_router(coupon_engine_router)
app.include_router(gift_card_router)
app.include_router(smart_dispatch_router)
app.include_router(stored_value_router)
app.include_router(premium_card_router)
app.include_router(points_mall_router)


@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-member", "version": "4.0.0"}}
