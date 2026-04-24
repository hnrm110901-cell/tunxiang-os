"""tx-member — 域C 会员CDP微服务

Golden ID 全渠道画像、RFM 分层、营销活动、用户旅程、私域运营、储值卡、积分商城、付费会员
"""

import asyncio
from contextlib import asynccontextmanager

# Feature Flag SDK（try/except 保护，SDK不可用时自动降级为全量开启）
try:
    from shared.feature_flags import FlagContext, is_enabled
    from shared.feature_flags.flag_names import MemberFlags

    _FLAG_SDK_AVAILABLE = True
except ImportError:
    _FLAG_SDK_AVAILABLE = False

    def is_enabled(flag, context=None):
        return True  # noqa: E731


import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from workers.rfm_updater import RFMEventListener, RFMUpdater

from shared.events.event_publisher import MemberEventPublisher
from shared.ontology.src.database import async_session_factory, init_db

from .api.analytics_routes import router as analytics_router
from .api.card_routes import router as card_router
from .api.coupon_engine_routes import router as coupon_engine_router
from .api.cross_brand_member_routes import router as cross_brand_router  # 跨品牌会员智能
from .api.customer_depth_routes import router as customer_depth_router
from .api.gdpr_routes import router as gdpr_router
from .api.gift_card_routes import router as gift_card_router
from .api.golden_id_routes import router as golden_id_router  # Y-D9 全渠道 Golden ID 映射
from .api.group_member_routes import router as group_member_router
from .api.group_routes import router as group_router
from .api.lifecycle_router import router as lifecycle_v2_router
from .api.lifecycle_routes import router as lifecycle_router
from .api.marketing import router as marketing_router
from .api.member_insight_routes import router as member_insight_router
from .api.member_level_routes import router as member_level_router
from .api.members import router as member_router
from .api.platform_routes import router as platform_router
from .api.points_mall_routes import router as points_mall_router
from .api.points_routes import router as points_router
from .api.premium_card_routes import router as premium_card_router
from .api.premium_membership_card_routes import router as premium_membership_router  # Y-D7 付费会员卡产品化
from .api.recommendation_routes import router as recommendation_router  # 实时推荐引擎
from .api.rfm_routes import router as rfm_router
from .api.smart_dispatch_routes import router as smart_dispatch_router
from .api.social_routes import router as social_router
from .api.stamp_card_routes import router as stamp_card_router
from .api.stored_value_card_routes import router as stored_value_card_router
from .api.stored_value_router import router as stored_value_v2_router
from .api.stored_value_routes import router as stored_value_router
from .api.subscription_routes import router as subscription_router  # 付费会员订阅

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

    # 注入 stamp_card_routes 的 get_db（避免 NotImplementedError stub）
    import api.stamp_card_routes as _stamp_mod

    from shared.ontology.src.database import get_db as _shared_get_db

    _stamp_mod.get_db = _shared_get_db

    # ── Feature Flag 启动检查 ──────────────────────────────────────
    # MemberFlags.INSIGHT_360: 客户360页面功能
    if is_enabled(MemberFlags.INSIGHT_360):
        logger.info("feature_flag_enabled", flag=MemberFlags.INSIGHT_360)
    else:
        logger.info(
            "feature_flag_disabled",
            flag=MemberFlags.INSIGHT_360,
            note="客户360画像路由已注册但Flag关闭，接口将返回功能未开启提示",
        )

    # MemberFlags.CLV_ENGINE: CLV生命周期价值引擎
    if is_enabled(MemberFlags.CLV_ENGINE):
        logger.info("feature_flag_enabled", flag=MemberFlags.CLV_ENGINE)
    else:
        logger.info(
            "feature_flag_disabled", flag=MemberFlags.CLV_ENGINE, note="CLV引擎已跳过初始化，相关API将返回功能未开启"
        )

    # MemberFlags.GDPR_ANONYMIZE: GDPR匿名化（等保三级合规）
    if is_enabled(MemberFlags.GDPR_ANONYMIZE):
        logger.info("feature_flag_enabled", flag=MemberFlags.GDPR_ANONYMIZE, note="GDPR匿名化合规功能已激活")
    else:
        logger.warning(
            "feature_flag_disabled", flag=MemberFlags.GDPR_ANONYMIZE, note="GDPR匿名化未启用，等保三级合规可能不满足"
        )

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

from prometheus_fastapi_instrumentator import Instrumentator

Instrumentator().instrument(app).expose(app)

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
app.include_router(stored_value_v2_router)
app.include_router(stored_value_card_router)
app.include_router(premium_card_router)
app.include_router(premium_membership_router)  # Y-D7 付费会员卡产品化
app.include_router(points_mall_router)
app.include_router(rfm_router)
app.include_router(group_router)
app.include_router(lifecycle_router)
app.include_router(lifecycle_v2_router)
app.include_router(platform_router)
app.include_router(group_member_router)
app.include_router(social_router)
app.include_router(stamp_card_router)
app.include_router(member_level_router)
app.include_router(member_insight_router)
app.include_router(gdpr_router)  # Y-L6 GDPR 删除/导出请求工作流
app.include_router(golden_id_router)  # Y-D9 全渠道 Golden ID 映射
app.include_router(cross_brand_router)  # 跨品牌会员智能
app.include_router(recommendation_router)  # 实时推荐引擎
app.include_router(subscription_router)  # 付费会员订阅


# ── Sprint D3a/D3b 路由自动挂载（PR #82 #83 合入后自动生效）──
from pathlib import Path as _Path  # noqa: E402

from shared.service_utils import auto_mount_routes  # noqa: E402

_sprint_d3_mount = auto_mount_routes(
    app,
    pkg=__package__,
    api_dir=_Path(__file__).parent / "api",
    modules=[
        ("rfm_outreach_routes", "router"),            # D3a #82
        ("campaign_roi_forecast_routes", "router"),    # D3b #83
    ],
)


@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-member", "version": "4.0.0"}}
