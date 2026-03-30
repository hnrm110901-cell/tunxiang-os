"""tx-member — 域C 会员CDP微服务

Golden ID 全渠道画像、RFM 分层、营销活动、用户旅程、私域运营、储值卡、积分商城、付费会员
"""
import asyncio
from contextlib import asynccontextmanager

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.ontology.src.database import init_db, async_session_factory
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
from api.rfm_routes import router as rfm_router
from api.group_routes import router as group_router
from api.lifecycle_routes import router as lifecycle_router
from api.platform_routes import router as platform_router
from workers.rfm_updater import RFMUpdater, RFMEventListener
from shared.events.event_publisher import MemberEventPublisher

logger = structlog.get_logger(__name__)

# 全局 scheduler 实例（lifespan 中启动/关闭）
_scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")

# 全局事件监听 Task（lifespan 中启动/取消）
_rfm_listener_task: asyncio.Task | None = None


async def _run_rfm_update() -> None:
    """定时任务入口：获取 DB session 并执行全量 RFM 更新"""
    logger.info("rfm_scheduled_job_started")
    async with async_session_factory() as db:
        try:
            result = await RFMUpdater().update_all_tenants(db)
            logger.info("rfm_scheduled_job_finished", **result)
        except (OSError, RuntimeError, ValueError) as exc:
            logger.error(
                "rfm_scheduled_job_error",
                error=str(exc),
                exc_info=True,
            )


async def _run_rfm_event_listener() -> None:
    """RFM 事件监听后台任务：持续订阅 ORDER_PAID 实时刷新 RFM。

    DB session 在此函数内部通过 async_session_factory 管理，
    每条消息独立 session，避免长事务。
    """
    logger.info("rfm_event_listener_task_started")
    try:
        await RFMEventListener().listen(async_session_factory)
    except (OSError, RuntimeError) as exc:
        logger.error(
            "rfm_event_listener_task_crashed",
            error=str(exc),
            exc_info=True,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _rfm_listener_task

    await init_db()

    # 注册 RFM 每日凌晨2点定时任务（Asia/Shanghai）
    _scheduler.add_job(
        lambda: asyncio.create_task(_run_rfm_update()),
        "cron",
        hour=2,
        minute=0,
        id="rfm_daily_update",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("rfm_scheduler_started", next_run=str(_scheduler.get_job("rfm_daily_update").next_run_time))

    # 启动 RFM 事件监听后台任务（ORDER_PAID → 实时 RFM 刷新）
    _rfm_listener_task = asyncio.create_task(_run_rfm_event_listener())
    logger.info("rfm_event_listener_started")

    yield

    # 关闭事件监听
    if _rfm_listener_task and not _rfm_listener_task.done():
        _rfm_listener_task.cancel()
        logger.info("rfm_event_listener_stopped")

    _scheduler.shutdown(wait=False)
    logger.info("rfm_scheduler_stopped")

    await MemberEventPublisher.close()


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
app.include_router(rfm_router)
app.include_router(group_router)
app.include_router(lifecycle_router)
app.include_router(platform_router)


@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-member", "version": "4.0.0"}}
