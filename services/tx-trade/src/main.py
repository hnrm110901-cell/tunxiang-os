"""tx-trade — 域A 交易履约微服务

收银引擎：开单/点餐/结算/支付/退款/打印/日结
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.ontology.src.database import init_db
from .api.orders import router as orders_router
from .api.cashier_api import router as cashier_router
from .api.kds_routes import router as kds_router
from .api.handover_routes import router as handover_router
from .api.table_routes import router as table_router
from .api.enterprise_routes import router as enterprise_router
from .api.order_ext_routes import router as order_ext_router
from .api.coupon_routes import router as coupon_router
from .api.platform_coupon_routes import router as platform_coupon_router
from .api.service_charge_routes import router as service_charge_router
from .api.invoice_routes import router as invoice_router
from .api.payment_direct_routes import router as payment_direct_router
from .api.webhook_routes import router as webhook_router
from .api.printer_routes import router as printer_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时创建表（开发环境）
    await init_db()
    yield


app = FastAPI(
    title="TunxiangOS tx-trade",
    version="3.0.0",
    description="交易履约微服务 — 收银引擎",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(orders_router)
app.include_router(cashier_router)
app.include_router(kds_router)
app.include_router(handover_router)
app.include_router(table_router)
app.include_router(enterprise_router)
app.include_router(order_ext_router)
app.include_router(coupon_router)
app.include_router(platform_coupon_router)
app.include_router(service_charge_router)
app.include_router(invoice_router)
app.include_router(payment_direct_router)
app.include_router(webhook_router)
app.include_router(printer_router)


@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-trade", "version": "3.0.0"}}
