"""tx-growth — 增长中枢微服务

品牌策略、客户分群、触发式营销编排、内容生成、优惠策略、渠道触达、ROI归因

七大引擎协同驱动连锁餐饮品牌的精细化增长。
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Optional

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from pydantic import BaseModel
from services.audience_segmentation import AudienceSegmentationService
from services.brand_strategy import BrandStrategyService
from services.journey_orchestrator import JourneyOrchestratorService

# ChannelEngine / ContentEngine / OfferEngine: v144 DB化，已移至各自路由文件
from services.roi_attribution import ROIAttributionService
from workers.journey_executor import JourneyEventListener, JourneyExecutor

from shared.events.event_publisher import MemberEventPublisher
from shared.ontology.src.database import async_session_factory, init_db

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# APScheduler — 旅程执行引擎（每60秒 tick 一次）
# ---------------------------------------------------------------------------

_scheduler = AsyncIOScheduler()
_journey_executor = JourneyExecutor()

# 全局事件监听 Task（lifespan 中启动/取消）
_journey_listener_task: asyncio.Task | None = None


async def _run_journey_tick() -> None:
    """
    定时任务入口：创建 DB session 并执行 JourneyExecutor.tick(db)。

    参照 tx-member 的 _run_rfm_update() 模式：
      - async_session_factory() 负责连接生命周期（含 commit / rollback）
      - 具体异常类型列举，禁止 broad except
    """
    logger.info("journey_tick_job_started")
    async with async_session_factory() as db:
        try:
            result = await _journey_executor.tick(db)
            await db.commit()
            logger.info("journey_tick_job_finished", **result)
        except (OSError, RuntimeError, ValueError) as exc:
            await db.rollback()
            logger.error(
                "journey_tick_job_error",
                error=str(exc),
                exc_info=True,
            )


def _schedule_tick() -> None:
    """
    APScheduler 调度回调：在事件循环中创建 Task 执行 _run_journey_tick()。

    使用 asyncio.create_task 而非 await，保证 APScheduler 的调度线程不阻塞。
    Task 内部异常通过 _on_tick_done 回调记录，不会静默丢失。
    """
    task = asyncio.create_task(_run_journey_tick())
    task.add_done_callback(_on_tick_done)


def _on_tick_done(task: asyncio.Task) -> None:
    """tick Task 完成回调：捕获并记录未处理异常。"""
    exc = task.exception() if not task.cancelled() else None
    if exc is not None:
        logger.error(
            "journey_executor_tick_unhandled_error",
            error=str(exc),
            exc_info=exc,
        )


# ---------------------------------------------------------------------------
# FastAPI App（lifespan 管理 DB 初始化 + scheduler）
# ---------------------------------------------------------------------------

from engine.event_bridge import get_event_bridge as _get_event_bridge
from engine.journey_engine import JourneyEngine as _JourneyEngine
from services.approval_service import ApprovalService as _ApprovalService

from .api.ab_test_routes import router as ab_test_router
from .api.ai_marketing_routes import router as ai_marketing_router  # AI营销自动化（v207）
from .api.approval_routes import router as approval_router
from .api.attribution_routes import router as attribution_router
from .api.brand_strategy_routes import router as brand_strategy_router
from .api.campaign_engine_db_routes import router as campaign_engine_db_router  # v193 活动引擎持久化
from .api.campaign_routes import router as campaign_router
from .api.channel_routes import router as channel_router  # v144 DB化
from .api.content_routes import router as content_router  # v144 DB化
from .api.coupon_routes import router as coupon_router
from .api.distribution_routes import router as distribution_router  # v191 三级分销
from .api.growth_campaign_routes import router as growth_campaign_router
from .api.growth_hub_routes import router as growth_hub_router
from .api.journey_routes import router as journey_router
from .api.offer_routes import router as offer_router  # v144 DB化
from .api.promotion_rules_v2_routes import router as promotion_rules_v2_router  # 模块2.5 促销规则引擎V2
from .api.promotion_rules_v3_routes import (
    router as promotion_rules_v3_router,  # 模块2.6 促销规则引擎V3（互斥组/执行顺序/总量限制/新类型）
)
from .api.referral_routes import router as referral_router
from .api.segmentation_routes import router as segmentation_router
from .api.touch_attribution_routes import router as touch_attribution_router
from .api.wecom_scrm_agent_routes import router as wecom_scrm_agent_router  # P3-05 企微SCRM私域Agent

_approval_service = _ApprovalService()

# ---------------------------------------------------------------------------
# Journey Engine — 定时任务（每分钟处理到期 enrollment 步骤）
# ---------------------------------------------------------------------------

_journey_engine = _JourneyEngine()
# EventBridge 在 lifespan 中初始化（需要 db_session_factory）
_journey_engine_task: asyncio.Task | None = None


async def _run_journey_engine_tick() -> None:
    """定时任务：每分钟推进到期的 Journey enrollment 步骤。"""
    logger.info("journey_engine_tick_started")
    async with async_session_factory() as db:
        try:
            result = await _journey_engine.process_pending_steps(db)
            await db.commit()
            logger.info("journey_engine_tick_done", **result)
        except (OSError, RuntimeError, ValueError) as exc:
            await db.rollback()
            logger.error(
                "journey_engine_tick_error",
                error=str(exc),
                exc_info=True,
            )


def _schedule_journey_engine_tick() -> None:
    """APScheduler 回调：在事件循环中创建 Task 执行 Journey Engine tick。"""
    task = asyncio.create_task(_run_journey_engine_tick())
    task.add_done_callback(_on_journey_engine_tick_done)


def _on_journey_engine_tick_done(task: asyncio.Task) -> None:
    """Journey Engine tick Task 完成回调。"""
    exc = task.exception() if not task.cancelled() else None
    if exc is not None:
        logger.error(
            "journey_engine_tick_unhandled_error",
            error=str(exc),
            exc_info=exc,
        )


# ---------------------------------------------------------------------------
# APScheduler — 审批超时检查（每小时 tick 一次）
# ---------------------------------------------------------------------------


async def _run_approval_expiry_check() -> None:
    """
    定时任务：检查所有租户超时审批单，按策略自动通过或标记 expired。

    参照 _run_journey_tick() 模式：
      - async_session_factory() 管理连接生命周期
      - 具体异常类型列举，禁止 broad except
    生产版应从 tenants 表查出活跃租户列表，逐一调用 check_expired_requests。
    此处为占位实现，RLS 策略需在调用处通过 SET LOCAL app.tenant_id 激活。
    """
    logger.info("approval_expiry_check_started")
    # 先查出所有活跃租户（用无 RLS 连接查 DISTINCT tenant_id）
    from sqlalchemy import text as _text

    async with async_session_factory() as probe_db:
        try:
            result = await probe_db.execute(_text("SELECT DISTINCT tenant_id FROM stores WHERE is_active = true"))
            tenant_ids = [str(row[0]) for row in result.fetchall()]
        except (OSError, RuntimeError, ValueError) as exc:
            logger.error("approval_expiry_fetch_tenants_error", error=str(exc), exc_info=True)
            return

    for tenant_id in tenant_ids:
        async with async_session_factory() as db:
            try:
                await db.execute(
                    _text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": tenant_id},
                )
                result = await _approval_service.check_expired_requests(tenant_id, db)
                await db.commit()
                logger.info("approval_expiry_check_tenant_done", tenant_id=tenant_id, **result)
            except (OSError, RuntimeError, ValueError) as exc:
                await db.rollback()
                logger.error(
                    "approval_expiry_check_tenant_error",
                    tenant_id=tenant_id,
                    error=str(exc),
                    exc_info=True,
                )

    logger.info("approval_expiry_check_finished", tenant_count=len(tenant_ids))


def _schedule_approval_expiry() -> None:
    """APScheduler 回调：在事件循环中创建 Task 执行超时审批检查。"""
    task = asyncio.create_task(_run_approval_expiry_check())
    task.add_done_callback(_on_approval_expiry_done)


def _on_approval_expiry_done(task: asyncio.Task) -> None:
    """超时检查 Task 完成回调：捕获并记录未处理异常。"""
    exc = task.exception() if not task.cancelled() else None
    if exc is not None:
        logger.error(
            "approval_expiry_check_unhandled_error",
            error=str(exc),
            exc_info=exc,
        )


# ---------------------------------------------------------------------------
# APScheduler — Growth Journey V2 tick（每60秒）
# ---------------------------------------------------------------------------

from services.growth_brand_service import GrowthBrandService as _GrowthBrandService
from services.growth_journey_service import GrowthJourneyService as _GrowthJourneyService

# Feature Flag SDK — 控制 Growth Journey V2 / 沉默召回 等 cron 任务
try:
    from shared.feature_flags import FlagContext
    from shared.feature_flags import is_enabled as _ff_is_enabled
    from shared.feature_flags.flag_names import GrowthFlags as _GrowthFlags

    _FEATURE_FLAGS_AVAILABLE = True
except ImportError:
    _FEATURE_FLAGS_AVAILABLE = False
    logger.warning("feature_flags_sdk_not_available", reason="import failed, all flags default to enabled")

_growth_journey_svc = _GrowthJourneyService()
_growth_brand_svc = _GrowthBrandService()


async def _run_growth_journey_tick() -> None:
    """定时任务：每分钟推进所有租户到期的增长中枢V2旅程。"""
    # Feature Flag 检查：growth.hub.journey_v2.enable
    # 关闭时跳过整个 V2 tick，降级依赖 V1 旅程执行器（_run_journey_tick）继续工作
    if _FEATURE_FLAGS_AVAILABLE and not _ff_is_enabled(_GrowthFlags.JOURNEY_V2):
        logger.info(
            "growth_journey_v2_tick_skipped",
            reason="feature_flag_disabled",
            flag=_GrowthFlags.JOURNEY_V2,
        )
        return

    logger.info("growth_journey_v2_tick_started")
    from sqlalchemy import text as _text

    # 查出所有活跃租户
    async with async_session_factory() as probe_db:
        try:
            result = await probe_db.execute(_text("SELECT DISTINCT tenant_id FROM stores WHERE is_active = true"))
            tenant_ids = [str(row[0]) for row in result.fetchall()]
        except (OSError, RuntimeError, ValueError) as exc:
            logger.error("growth_journey_v2_fetch_tenants_error", error=str(exc), exc_info=True)
            return

    total_scanned = 0
    total_advanced = 0
    total_failed = 0

    for tid in tenant_ids:
        async with async_session_factory() as db:
            try:
                await db.execute(_text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tid})
                result = await _growth_journey_svc.process_pending(tenant_id=tid, db=db)
                await db.commit()
                total_scanned += result.get("scanned", 0)
                total_advanced += result.get("advanced", 0)
                total_failed += result.get("failed", 0)
            except (OSError, RuntimeError, ValueError) as exc:
                await db.rollback()
                logger.error("growth_journey_v2_tick_tenant_error", tenant_id=tid, error=str(exc), exc_info=True)

    logger.info(
        "growth_journey_v2_tick_done",
        tenant_count=len(tenant_ids),
        scanned=total_scanned,
        advanced=total_advanced,
        failed=total_failed,
    )


def _schedule_growth_journey_tick() -> None:
    task = asyncio.create_task(_run_growth_journey_tick())
    task.add_done_callback(_on_growth_journey_tick_done)


def _on_growth_journey_tick_done(task: asyncio.Task) -> None:
    exc = task.exception() if not task.cancelled() else None
    if exc is not None:
        logger.error("growth_journey_v2_tick_unhandled", error=str(exc), exc_info=exc)


# ---------------------------------------------------------------------------
# APScheduler — Silent Detection（每日凌晨2点）
# ---------------------------------------------------------------------------

from services.growth_experiment_service import GrowthExperimentService as _GrowthExperimentService
from services.growth_profile_service import GrowthProfileService as _GrowthProfileService

_growth_experiment_svc = _GrowthExperimentService()
_growth_profile_svc = _GrowthProfileService()


async def _run_silent_detection() -> None:
    """每日凌晨2点：扫描沉默客户，更新召回优先级。"""
    # Feature Flag 检查：growth.member.recall_v2.enable
    # 关闭时跳过 V2 沉默召回检测（V1 召回逻辑不受影响）
    if _FEATURE_FLAGS_AVAILABLE and not _ff_is_enabled(_GrowthFlags.RECALL_V2):
        logger.info(
            "growth_silent_detection_skipped",
            reason="feature_flag_disabled",
            flag=_GrowthFlags.RECALL_V2,
        )
        return

    logger.info("growth_silent_detection_started")
    from sqlalchemy import text as _text

    async with async_session_factory() as probe_db:
        try:
            result = await probe_db.execute(_text("SELECT DISTINCT tenant_id FROM stores WHERE is_active = true"))
            tenant_ids = [str(row[0]) for row in result.fetchall()]
        except (OSError, RuntimeError, ValueError) as exc:
            logger.error("silent_detection_fetch_tenants_error", error=str(exc), exc_info=True)
            return
    for tid in tenant_ids:
        async with async_session_factory() as db:
            try:
                await db.execute(_text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tid})
                result = await _growth_profile_svc.batch_detect_silent(tid, db)
                await db.commit()
                logger.info("silent_detection_tenant_done", tenant_id=tid, **result)
            except (OSError, RuntimeError, ValueError) as exc:
                await db.rollback()
                logger.error("silent_detection_tenant_error", tenant_id=tid, error=str(exc), exc_info=True)
    logger.info("growth_silent_detection_finished", tenant_count=len(tenant_ids))


def _schedule_silent_detection() -> None:
    task = asyncio.create_task(_run_silent_detection())
    task.add_done_callback(_on_silent_detection_done)


def _on_silent_detection_done(task: asyncio.Task) -> None:
    exc = task.exception() if not task.cancelled() else None
    if exc is not None:
        logger.error("silent_detection_unhandled", error=str(exc), exc_info=exc)


# ---------------------------------------------------------------------------
# APScheduler — P1 Field Computation（每日凌晨3点）
# ---------------------------------------------------------------------------


async def _run_p1_field_computation() -> None:
    """每日凌晨3点：计算P1字段（心理距离/超级用户/里程碑/裂变场景）"""
    # Feature Flag 检查
    if _FEATURE_FLAGS_AVAILABLE and not _ff_is_enabled(_GrowthFlags.RECALL_V2):
        logger.info(
            "p1_field_computation_skipped",
            reason="feature_flag_disabled",
        )
        return

    logger.info("p1_field_computation_started")
    from sqlalchemy import text as _text

    async with async_session_factory() as probe_db:
        try:
            result = await probe_db.execute(_text("SELECT DISTINCT tenant_id FROM stores WHERE is_active = true"))
            tenant_ids = [str(row[0]) for row in result.fetchall()]
        except (OSError, RuntimeError, ValueError) as exc:
            logger.error("p1_computation_fetch_tenants_error", error=str(exc), exc_info=True)
            return

    for tid in tenant_ids:
        async with async_session_factory() as db:
            try:
                await db.execute(_text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tid})
                result = await _growth_profile_svc.batch_compute_p1_fields(tid, db)
                await db.commit()
                logger.info(
                    "p1_computation_tenant_done",
                    tenant_id=tid,
                    **{k: v.get("total_updated", 0) for k, v in result.items()},
                )
            except (OSError, RuntimeError, ValueError) as exc:
                await db.rollback()
                logger.error("p1_computation_tenant_error", tenant_id=tid, error=str(exc), exc_info=True)
    logger.info("p1_field_computation_finished", tenant_count=len(tenant_ids))


def _schedule_p1_computation() -> None:
    task = asyncio.create_task(_run_p1_field_computation())
    task.add_done_callback(_on_p1_computation_done)


def _on_p1_computation_done(task: asyncio.Task) -> None:
    exc = task.exception() if not task.cancelled() else None
    if exc is not None:
        logger.error("p1_computation_unhandled", error=str(exc), exc_info=exc)


# ---------------------------------------------------------------------------
# APScheduler — Auto Iterate Experiments（每6小时）
# ---------------------------------------------------------------------------


async def _run_auto_iterate() -> None:
    """每6小时：自动迭代实验 + 调整旅程参数"""
    logger.info("auto_iterate_started")
    from sqlalchemy import text as _text

    async with async_session_factory() as probe_db:
        try:
            result = await probe_db.execute(_text("SELECT DISTINCT tenant_id FROM stores WHERE is_active = true"))
            tenant_ids = [str(row[0]) for row in result.fetchall()]
        except (OSError, RuntimeError, ValueError) as exc:
            logger.error("auto_iterate_fetch_tenants_error", error=str(exc), exc_info=True)
            return

    for tid in tenant_ids:
        async with async_session_factory() as db:
            try:
                await db.execute(_text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tid})
                iter_result = await _growth_experiment_svc.auto_iterate(tid, db)
                adjust_result = await _growth_experiment_svc.auto_adjust_journey_params(tid, db)
                await db.commit()
                logger.info(
                    "auto_iterate_tenant_done",
                    tenant_id=tid,
                    actions=len(iter_result.get("actions_taken", [])),
                    adjustments=len(adjust_result.get("adjustments", [])),
                )
            except (OSError, RuntimeError, ValueError) as exc:
                await db.rollback()
                logger.error("auto_iterate_tenant_error", tenant_id=tid, error=str(exc), exc_info=True)

    logger.info("auto_iterate_finished", tenant_count=len(tenant_ids))


def _schedule_auto_iterate() -> None:
    task = asyncio.create_task(_run_auto_iterate())
    task.add_done_callback(_on_auto_iterate_done)


def _on_auto_iterate_done(task: asyncio.Task) -> None:
    exc = task.exception() if not task.cancelled() else None
    if exc is not None:
        logger.error("auto_iterate_unhandled", error=str(exc), exc_info=exc)


# ---------------------------------------------------------------------------
# APScheduler — Calendar Trigger Check（每日08:00 节庆信号检测）
# ---------------------------------------------------------------------------

from services.calendar_signal_proxy import CalendarSignalService as _CalendarSignalService

_calendar_signal_svc = _CalendarSignalService()


async def _run_calendar_trigger_check() -> None:
    """每日早8点：检查是否有节庆信号需要触发增长旅程。"""
    logger.info("calendar_trigger_check_started")
    try:
        triggers = _calendar_signal_svc.get_growth_triggers()
    except (ValueError, RuntimeError, OSError) as exc:
        logger.error("calendar_trigger_check_error", error=str(exc), exc_info=True)
        return

    if not triggers:
        logger.info("calendar_trigger_check_no_triggers")
        return

    logger.info("calendar_trigger_check_found", count=len(triggers))
    for trigger in triggers:
        # 生成Agent建议（不直接执行旅程，走审核流）
        logger.info(
            "calendar_trigger_suggestion",
            event=trigger["event_name"],
            action=trigger.get("action"),
            description=trigger.get("description"),
        )
        # 后续接入：调用 growth_suggestion_service.create_suggestion()


def _schedule_calendar_trigger() -> None:
    task = asyncio.create_task(_run_calendar_trigger_check())
    task.add_done_callback(_on_calendar_trigger_done)


def _on_calendar_trigger_done(task: asyncio.Task) -> None:
    exc = task.exception() if not task.cancelled() else None
    if exc is not None:
        logger.error("calendar_trigger_check_unhandled", error=str(exc), exc_info=exc)


async def _run_journey_event_listener() -> None:
    """旅程事件监听后台任务：订阅 Redis Stream，实时触发旅程。

    使用长存活的 AsyncSession，_trigger_for_customer 每次调用后 commit。
    若 Redis 不可用，循环内自动重试（5s 间隔），不影响 APScheduler 轮询。
    """
    logger.info("journey_event_listener_task_started")
    listener = JourneyEventListener()
    try:
        async with async_session_factory() as db:
            await listener.listen(db)
    except (OSError, RuntimeError) as exc:
        logger.error(
            "journey_event_listener_task_crashed",
            error=str(exc),
            exc_info=True,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """初始化 DB 表结构，启动旅程调度器 + 审批超时检查调度器 + 事件监听。"""
    global _journey_listener_task

    await init_db()

    _scheduler.add_job(
        _schedule_tick,
        trigger="interval",
        seconds=60,
        id="journey_executor",
        replace_existing=True,
        max_instances=1,  # 防止并发 tick 重叠
        misfire_grace_time=30,  # 系统繁忙时延迟30秒内可补发
    )

    _scheduler.add_job(
        _schedule_approval_expiry,
        trigger="interval",
        hours=1,
        id="approval_expiry_check",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,  # 超时检查允许5分钟内补发
    )

    # Journey Engine tick — 每分钟推进到期 enrollment 步骤
    _scheduler.add_job(
        _schedule_journey_engine_tick,
        trigger="interval",
        seconds=60,
        id="journey_engine_tick",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=30,
    )

    # Growth Journey V2 tick — 每分钟推进到期的增长中枢V2旅程
    _scheduler.add_job(
        _schedule_growth_journey_tick,
        trigger="interval",
        seconds=60,
        id="growth_journey_v2_tick",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=30,
    )

    # Silent Detection — 每日凌晨2点
    _scheduler.add_job(
        _schedule_silent_detection,
        trigger="cron",
        hour=2,
        id="growth_silent_detection",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )

    # P1 Field Computation — 每日凌晨3点（心理距离/超级用户/里程碑/裂变场景）
    _scheduler.add_job(
        _schedule_p1_computation,
        trigger="cron",
        hour=3,
        id="growth_p1_computation",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )

    # Auto Iterate Experiments — 每6小时自动迭代实验 + 调整旅程参数
    _scheduler.add_job(
        _schedule_auto_iterate,
        trigger="interval",
        hours=6,
        id="growth_auto_iterate",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=600,
    )

    # Calendar Trigger Check — 每日08:00 节庆信号检测
    _scheduler.add_job(
        _schedule_calendar_trigger,
        trigger="cron",
        hour=8,
        id="growth_calendar_trigger",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )

    _scheduler.start()
    logger.info("journey_executor_scheduler_started", interval_seconds=60)
    logger.info("approval_expiry_scheduler_started", interval_hours=1)
    logger.info("journey_engine_scheduler_started", interval_seconds=60)
    logger.info("growth_journey_v2_scheduler_started", interval_seconds=60)
    logger.info("growth_silent_detection_scheduler_started", trigger="cron_02:00")
    logger.info("growth_p1_computation_scheduler_started", trigger="cron_03:00")
    logger.info("growth_auto_iterate_scheduler_started", interval_hours=6)
    logger.info("growth_calendar_trigger_scheduler_started", trigger="cron_08:00")

    # 启动 EventBridge（桥接业务事件 → JourneyEngine）
    _bridge = _get_event_bridge(
        journey_engine=_journey_engine,
        db_session_factory=async_session_factory,
    )
    await _bridge.start()
    logger.info("journey_event_bridge_started")

    # 启动旅程事件监听后台任务（MEMBER_REGISTERED / ORDER_PAID → 实时触发旅程）
    _journey_listener_task = asyncio.create_task(_run_journey_event_listener())
    logger.info("journey_event_listener_started")

    yield

    # 关闭事件监听
    if _journey_listener_task and not _journey_listener_task.done():
        _journey_listener_task.cancel()
        logger.info("journey_event_listener_stopped")

    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("journey_executor_scheduler_stopped")
        logger.info("approval_expiry_scheduler_stopped")
        logger.info("journey_engine_scheduler_stopped")

    # 停止 EventBridge
    try:
        from engine.event_bridge import _bridge_instance as _eb

        if _eb is not None:
            await _eb.stop()
            logger.info("journey_event_bridge_stopped")
    except (OSError, RuntimeError, ImportError):
        pass

    await MemberEventPublisher.close()


app = FastAPI(title="TunxiangOS tx-growth", version="3.0.0", lifespan=lifespan)

from prometheus_fastapi_instrumentator import Instrumentator

Instrumentator().instrument(app).expose(app)

app.include_router(campaign_router)
app.include_router(coupon_router)  # /api/v1/growth/coupons（优惠券核销）
app.include_router(growth_campaign_router)  # /api/v1/growth/campaigns（新标准路径）
app.include_router(campaign_engine_db_router)  # /api/v1/growth/campaigns-v2（v193 持久化引擎）
app.include_router(segmentation_router)
app.include_router(referral_router)
app.include_router(distribution_router)  # v191 三级分销 /api/v1/growth/referral/*
app.include_router(attribution_router)
app.include_router(touch_attribution_router)
app.include_router(ab_test_router)
app.include_router(approval_router)
app.include_router(brand_strategy_router)
app.include_router(journey_router)
# v144 DB化路由（替换下方旧的内存版端点）
app.include_router(offer_router)  # /api/v1/offers — offers/offer_redemptions 表
app.include_router(content_router)  # /api/v1/content — content_templates 表
app.include_router(channel_router)  # /api/v1/channels — channel_configs/message_send_logs 表
app.include_router(growth_hub_router)  # /api/v1/growth — 增长中枢V2
app.include_router(wecom_scrm_agent_router)  # P3-05 企微SCRM私域Agent
app.include_router(ai_marketing_router)  # /api/v1/growth/ai-marketing/* — AI营销自动化（v207）（生日/沉睡/回访）
app.include_router(promotion_rules_v2_router)  # /api/v1/promotions/* — 促销规则引擎V2（模块2.5）
app.include_router(promotion_rules_v3_router)  # /api/v1/promotions/v3/* — 促销规则引擎V3（模块2.6）

# 服务实例
brand_svc = BrandStrategyService()
segment_svc = AudienceSegmentationService()
journey_svc = JourneyOrchestratorService()
# content_svc / offer_svc / channel_svc 已 v144 DB化，
# 各自通过独立路由文件 (content_router/offer_router/channel_router) 接入 AsyncSession
roi_svc = ROIAttributionService()


# ---------------------------------------------------------------------------
# 统一响应格式
# ---------------------------------------------------------------------------


def ok_response(data: Any) -> dict:
    return {"ok": True, "data": data}


def error_response(msg: str) -> dict:
    return {"ok": False, "error": {"message": msg}}


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "data": {"service": "tx-growth", "version": "3.0.0"}}


# ---------------------------------------------------------------------------
# 品牌策略 API
# ---------------------------------------------------------------------------


class BrandStrategyRequest(BaseModel):
    brand_id: str
    positioning: str
    tone: str
    target_audience: list[str]
    price_range: dict
    signature_dishes: list[dict]
    seasonal_plans: list[dict]
    promo_boundaries: dict
    forbidden_expressions: list[str]


class BrandStrategyUpdateRequest(BaseModel):
    updates: dict


class CityStrategyRequest(BaseModel):
    brand_id: str
    city: str
    district_strategies: list[dict]


class ContentValidationRequest(BaseModel):
    brand_id: str
    content_text: str


@app.post("/api/v1/brand-strategy")
async def create_brand_strategy(req: BrandStrategyRequest) -> dict:
    result = brand_svc.create_brand_strategy(
        brand_id=req.brand_id,
        positioning=req.positioning,
        tone=req.tone,
        target_audience=req.target_audience,
        price_range=req.price_range,
        signature_dishes=req.signature_dishes,
        seasonal_plans=req.seasonal_plans,
        promo_boundaries=req.promo_boundaries,
        forbidden_expressions=req.forbidden_expressions,
    )
    return ok_response(result)


@app.get("/api/v1/brand-strategy/{brand_id}")
async def get_brand_strategy(brand_id: str) -> dict:
    result = brand_svc.get_brand_strategy(brand_id)
    if "error" in result:
        return error_response(result["error"])
    return ok_response(result)


@app.put("/api/v1/brand-strategy/{brand_id}")
async def update_brand_strategy(brand_id: str, req: BrandStrategyUpdateRequest) -> dict:
    result = brand_svc.update_brand_strategy(brand_id, req.updates)
    if "error" in result:
        return error_response(result["error"])
    return ok_response(result)


@app.post("/api/v1/brand-strategy/city")
async def create_city_strategy(req: CityStrategyRequest) -> dict:
    result = brand_svc.create_city_strategy(req.brand_id, req.city, req.district_strategies)
    return ok_response(result)


@app.get("/api/v1/brand-strategy/{brand_id}/seasonal-calendar")
async def get_seasonal_calendar(brand_id: str) -> dict:
    result = brand_svc.get_seasonal_calendar(brand_id)
    return ok_response(result)


@app.post("/api/v1/brand-strategy/validate-content")
async def validate_content_against_brand(req: ContentValidationRequest) -> dict:
    result = brand_svc.validate_content_against_brand(req.brand_id, req.content_text)
    return ok_response(result)


@app.get("/api/v1/brand-strategy/{brand_id}/strategy-card")
async def get_strategy_card(brand_id: str) -> dict:
    result = brand_svc.generate_strategy_card(brand_id)
    if "error" in result:
        return error_response(result["error"])
    return ok_response(result)


# ---------------------------------------------------------------------------
# 客户分群 API
# ---------------------------------------------------------------------------


class SegmentRequest(BaseModel):
    name: str
    rules: dict
    segment_type: str = "custom"


class ClassifyUserRequest(BaseModel):
    user_data: dict


@app.post("/api/v1/segments")
async def create_segment(req: SegmentRequest) -> dict:
    result = segment_svc.create_segment(req.name, req.rules, req.segment_type)
    return ok_response(result)


@app.get("/api/v1/segments")
async def list_segments() -> dict:
    result = segment_svc.list_segments()
    return ok_response(result)


@app.get("/api/v1/segments/{segment_id}")
async def get_segment_detail(segment_id: str) -> dict:
    result = segment_svc.get_segment_detail(segment_id)
    if "error" in result:
        return error_response(result["error"])
    return ok_response(result)


@app.get("/api/v1/segments/{segment_id}/users")
async def get_segment_users(segment_id: str, page: int = 1, size: int = 20) -> dict:
    result = segment_svc.get_segment_users(segment_id, page, size)
    if "error" in result:
        return error_response(result["error"])
    return ok_response(result)


@app.get("/api/v1/segments/{segment_id}/stats")
async def get_segment_stats(segment_id: str) -> dict:
    result = segment_svc.compute_segment_stats(segment_id)
    if "error" in result:
        return error_response(result["error"])
    return ok_response(result)


@app.post("/api/v1/segments/classify")
async def classify_user(req: ClassifyUserRequest) -> dict:
    result = segment_svc.classify_user(req.user_data)
    return ok_response({"matched_segments": result})


@app.get("/api/v1/segments/ai-recommend/{brand_id}")
async def ai_recommend_segments(brand_id: str) -> dict:
    result = segment_svc.ai_recommend_segments(brand_id)
    return ok_response(result)


@app.get("/api/v1/segments/lifecycle-distribution")
async def get_lifecycle_distribution() -> dict:
    result = segment_svc.get_lifecycle_distribution()
    return ok_response(result)


# ---------------------------------------------------------------------------
# 旅程编排 API
# ---------------------------------------------------------------------------


class JourneyRequest(BaseModel):
    name: str
    journey_type: str
    trigger: dict
    nodes: list[dict]
    target_segment_id: str


class JourneyUpdateRequest(BaseModel):
    updates: dict


class ExecuteNodeRequest(BaseModel):
    journey_id: str
    node_id: str
    user_id: str


@app.post("/api/v1/journeys")
async def create_journey(req: JourneyRequest) -> dict:
    result = journey_svc.create_journey(req.name, req.journey_type, req.trigger, req.nodes, req.target_segment_id)
    return ok_response(result)


@app.put("/api/v1/journeys/{journey_id}")
async def update_journey(journey_id: str, req: JourneyUpdateRequest) -> dict:
    result = journey_svc.update_journey(journey_id, req.updates)
    if "error" in result:
        return error_response(result["error"])
    return ok_response(result)


@app.post("/api/v1/journeys/{journey_id}/publish")
async def publish_journey(journey_id: str) -> dict:
    result = journey_svc.publish_journey(journey_id)
    if "error" in result:
        return error_response(result["error"])
    return ok_response(result)


@app.post("/api/v1/journeys/{journey_id}/pause")
async def pause_journey(journey_id: str) -> dict:
    result = journey_svc.pause_journey(journey_id)
    if "error" in result:
        return error_response(result["error"])
    return ok_response(result)


@app.get("/api/v1/journeys/{journey_id}")
async def get_journey_detail(journey_id: str) -> dict:
    result = journey_svc.get_journey_detail(journey_id)
    if "error" in result:
        return error_response(result["error"])
    return ok_response(result)


@app.get("/api/v1/journeys")
async def list_journeys(status: Optional[str] = None) -> dict:
    result = journey_svc.list_journeys(status)
    return ok_response(result)


@app.post("/api/v1/journeys/execute-node")
async def execute_node(req: ExecuteNodeRequest) -> dict:
    result = journey_svc.execute_node(req.journey_id, req.node_id, req.user_id)
    if "error" in result:
        return error_response(result["error"])
    return ok_response(result)


@app.get("/api/v1/journeys/{journey_id}/stats")
async def get_journey_stats(journey_id: str) -> dict:
    result = journey_svc.get_journey_stats(journey_id)
    if "error" in result:
        return error_response(result["error"])
    return ok_response(result)


@app.get("/api/v1/journeys/{journey_id}/simulate")
async def simulate_journey(journey_id: str) -> dict:
    result = journey_svc.simulate_journey(journey_id)
    if "error" in result:
        return error_response(result["error"])
    return ok_response(result)


# ---------------------------------------------------------------------------
# 内容引擎 / 优惠引擎 / 渠道引擎 API
# 已完全迁移至独立路由文件（v144 DB化），通过 include_router 挂载：
#   offer_router   → /api/v1/offers
#   content_router → /api/v1/content
#   channel_router → /api/v1/channels
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# ROI 归因 API
# ---------------------------------------------------------------------------


class TouchpointRequest(BaseModel):
    user_id: str
    channel: str
    campaign_id: str
    touchpoint_type: str


class ConversionRequest(BaseModel):
    user_id: str
    order_id: str
    revenue_fen: int


@app.post("/api/v1/roi/touchpoint")
async def record_touchpoint(req: TouchpointRequest) -> dict:
    result = roi_svc.record_touchpoint(req.user_id, req.channel, req.campaign_id, req.touchpoint_type)
    return ok_response(result)


@app.post("/api/v1/roi/conversion")
async def record_conversion(req: ConversionRequest) -> dict:
    result = roi_svc.record_conversion(req.user_id, req.order_id, req.revenue_fen)
    return ok_response(result)


@app.get("/api/v1/roi/campaign/{campaign_id}")
async def get_campaign_attribution(campaign_id: str, model: str = "multi_touch") -> dict:
    result = roi_svc.compute_attribution(campaign_id, model)
    if "error" in result:
        return error_response(result["error"])
    return ok_response(result)


@app.get("/api/v1/roi/channels")
async def get_channel_roi(start: str = "", end: str = "") -> dict:
    result = roi_svc.get_channel_roi({"start": start, "end": end})
    return ok_response(result)


@app.get("/api/v1/roi/segments")
async def get_segment_roi(start: str = "", end: str = "") -> dict:
    result = roi_svc.get_segment_roi({"start": start, "end": end})
    return ok_response(result)


@app.get("/api/v1/roi/user/{user_id}/path")
async def get_attribution_path(user_id: str) -> dict:
    result = roi_svc.get_attribution_path(user_id)
    return ok_response(result)


@app.get("/api/v1/roi/overview")
async def get_roi_overview(start: str = "", end: str = "") -> dict:
    result = roi_svc.get_roi_overview({"start": start, "end": end})
    return ok_response(result)
