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
from .api.approval_routes import router as approval_router
from .api.booking_api import router as booking_router
from .api.kds_shortage_routes import router as kds_shortage_router
from .api.scan_order_routes import router as scan_order_router
from .api.order_ops_routes import router as order_ops_router
from .api.shift_routes import router as shift_router
from .api.dish_practice_routes import router as dish_practice_router
from .api.table_ops_routes import router as table_ops_router
from .api.banquet_routes import router as banquet_router
from .api.mobile_ops_routes import router as mobile_ops_router
from .api.takeaway_routes import router as takeaway_router
from .api.retail_mall_routes import router as retail_mall_router
from .api.runner_routes import router as runner_router
from .api.expo_routes import router as expo_router
from .api.cook_time_routes import router as cook_time_router
from .api.shift_report_routes import router as shift_report_router
from .api.dispatch_rule_routes import router as dispatch_rule_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    from .services.cook_time_stats import start_daily_scheduler
    from shared.ontology.src.database import async_session_factory
    await init_db()
    asyncio.create_task(start_daily_scheduler(async_session_factory))
    yield


app = FastAPI(
    title="TunxiangOS tx-trade",
    version="4.0.0",
    description="交易履约微服务 — 收银/外卖聚合/零售商城",
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
app.include_router(approval_router)
app.include_router(booking_router)
app.include_router(kds_shortage_router)
app.include_router(scan_order_router)
app.include_router(order_ops_router)
app.include_router(shift_router)
app.include_router(dish_practice_router)
app.include_router(table_ops_router)
app.include_router(banquet_router)
app.include_router(mobile_ops_router)
app.include_router(takeaway_router)
app.include_router(retail_mall_router)
app.include_router(runner_router,        prefix="/api/v1/runner")
app.include_router(expo_router,          prefix="/api/v1/expo")
app.include_router(cook_time_router,     prefix="/api/v1/cook-time")
app.include_router(shift_report_router,  prefix="/api/v1/shifts")
app.include_router(dispatch_rule_router, prefix="/api/v1/dispatch-rules")


@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-trade", "version": "4.0.0"}}
