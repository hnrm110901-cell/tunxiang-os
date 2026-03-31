"""tx-growth — 增长中枢微服务

品牌策略、客户分群、触发式营销编排、内容生成、优惠策略、渠道触达、ROI归因

七大引擎协同驱动连锁餐饮品牌的精细化增长。
"""
import asyncio
from contextlib import asynccontextmanager

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, Optional

from shared.ontology.src.database import init_db, async_session_factory
from services.brand_strategy import BrandStrategyService
from services.audience_segmentation import AudienceSegmentationService
from services.journey_orchestrator import JourneyOrchestratorService
from services.content_engine import ContentEngine
from services.offer_engine import OfferEngine
from services.channel_engine import ChannelEngine
from services.roi_attribution import ROIAttributionService
from workers.journey_executor import JourneyExecutor, JourneyEventListener
from shared.events.event_publisher import MemberEventPublisher

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

from .api.campaign_routes import router as campaign_router
from .api.segmentation_routes import router as segmentation_router
from .api.referral_routes import router as referral_router
from .api.attribution_routes import router as attribution_router
from .api.touch_attribution_routes import router as touch_attribution_router
from .api.ab_test_routes import router as ab_test_router
from .api.approval_routes import router as approval_router
from .api.brand_strategy_routes import router as brand_strategy_router
from .api.journey_routes import router as journey_router
from services.approval_service import ApprovalService as _ApprovalService
from engine.journey_engine import JourneyEngine as _JourneyEngine
from engine.event_bridge import get_event_bridge as _get_event_bridge

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
    async with async_session_factory() as db:
        try:
            # TODO: 按活跃租户列表循环；当前仅记录启动日志
            # 生产实现：
            #   tenants = await fetch_active_tenant_ids(db)
            #   for tenant_id in tenants:
            #       await db.execute(text(f"SET LOCAL app.tenant_id='{tenant_id}'"))
            #       result = await _approval_service.check_expired_requests(tenant_id, db)
            #       logger.info("approval_expiry_check_tenant_done", tenant_id=str(tenant_id), **result)
            await db.commit()
            logger.info("approval_expiry_check_finished")
        except (OSError, RuntimeError, ValueError) as exc:
            await db.rollback()
            logger.error(
                "approval_expiry_check_error",
                error=str(exc),
                exc_info=True,
            )


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
        max_instances=1,        # 防止并发 tick 重叠
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

    _scheduler.start()
    logger.info("journey_executor_scheduler_started", interval_seconds=60)
    logger.info("approval_expiry_scheduler_started", interval_hours=1)
    logger.info("journey_engine_scheduler_started", interval_seconds=60)

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
app.include_router(campaign_router)
app.include_router(segmentation_router)
app.include_router(referral_router)
app.include_router(attribution_router)
app.include_router(touch_attribution_router)
app.include_router(ab_test_router)
app.include_router(approval_router)
app.include_router(brand_strategy_router)
app.include_router(journey_router)

# 服务实例
brand_svc = BrandStrategyService()
segment_svc = AudienceSegmentationService()
journey_svc = JourneyOrchestratorService()
content_svc = ContentEngine()
offer_svc = OfferEngine()
channel_svc = ChannelEngine()
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
    result = journey_svc.create_journey(
        req.name, req.journey_type, req.trigger, req.nodes, req.target_segment_id
    )
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
# 内容引擎 API
# ---------------------------------------------------------------------------

class GenerateContentRequest(BaseModel):
    content_type: str
    brand_id: str
    target_segment: str
    dish_name: Optional[str] = None
    event_name: Optional[str] = None
    tone: Optional[str] = None


class CreateTemplateRequest(BaseModel):
    name: str
    content_type: str
    body_template: str
    variables: list[str]


@app.post("/api/v1/content/generate")
async def generate_content(req: GenerateContentRequest) -> dict:
    result = content_svc.generate_content(
        req.content_type, req.brand_id, req.target_segment,
        req.dish_name, req.event_name, req.tone,
    )
    if "error" in result:
        return error_response(result["error"])
    return ok_response(result)


@app.get("/api/v1/content/templates")
async def list_templates(content_type: Optional[str] = None) -> dict:
    result = content_svc.list_templates(content_type)
    return ok_response(result)


@app.post("/api/v1/content/templates")
async def create_template(req: CreateTemplateRequest) -> dict:
    result = content_svc.create_template(req.name, req.content_type, req.body_template, req.variables)
    return ok_response(result)


@app.post("/api/v1/content/validate")
async def validate_content(req: ContentValidationRequest) -> dict:
    result = content_svc.validate_content(req.brand_id, req.content_text)
    return ok_response(result)


@app.get("/api/v1/content/{content_id}/performance")
async def get_content_performance(content_id: str) -> dict:
    result = content_svc.get_content_performance(content_id)
    if "error" in result:
        return error_response(result["error"])
    return ok_response(result)


# ---------------------------------------------------------------------------
# 优惠引擎 API
# ---------------------------------------------------------------------------

class OfferRequest(BaseModel):
    name: str
    offer_type: str
    discount_rules: dict
    validity_days: int
    target_segments: list[str]
    stores: list[str] = []
    time_slots: list[dict] = []
    margin_floor: float = 0.45


class EligibilityRequest(BaseModel):
    user_id: str
    offer_id: str


class MarginCheckRequest(BaseModel):
    offer_id: str
    order_data: dict


@app.post("/api/v1/offers")
async def create_offer(req: OfferRequest) -> dict:
    result = offer_svc.create_offer(
        req.name, req.offer_type, req.discount_rules, req.validity_days,
        req.target_segments, req.stores, req.time_slots, req.margin_floor,
    )
    if "error" in result:
        return error_response(result["error"])
    return ok_response(result)


@app.post("/api/v1/offers/check-eligibility")
async def check_eligibility(req: EligibilityRequest) -> dict:
    result = offer_svc.evaluate_offer_eligibility(req.user_id, req.offer_id)
    return ok_response(result)


@app.get("/api/v1/offers/{offer_id}/cost")
async def calculate_offer_cost(offer_id: str) -> dict:
    result = offer_svc.calculate_offer_cost(offer_id)
    if "error" in result:
        return error_response(result["error"])
    return ok_response(result)


@app.post("/api/v1/offers/check-margin")
async def check_margin_compliance(req: MarginCheckRequest) -> dict:
    result = offer_svc.check_margin_compliance(req.offer_id, req.order_data)
    return ok_response(result)


@app.get("/api/v1/offers/{offer_id}/analytics")
async def get_offer_analytics(offer_id: str) -> dict:
    result = offer_svc.get_offer_analytics(offer_id)
    if "error" in result:
        return error_response(result["error"])
    return ok_response(result)


@app.get("/api/v1/offers/recommend/{segment_id}")
async def recommend_offer(segment_id: str) -> dict:
    result = offer_svc.recommend_offer_for_segment(segment_id)
    return ok_response(result)


# ---------------------------------------------------------------------------
# 渠道引擎 API
# ---------------------------------------------------------------------------

class SendMessageRequest(BaseModel):
    channel: str
    user_id: str
    content: str
    offer_id: Optional[str] = None


class ChannelConfigRequest(BaseModel):
    channel: str
    settings: dict


@app.post("/api/v1/channels/send")
async def send_message(req: SendMessageRequest) -> dict:
    result = channel_svc.send_message(req.channel, req.user_id, req.content, req.offer_id)
    return ok_response(result)


@app.get("/api/v1/channels/{channel}/frequency/{user_id}")
async def check_frequency(channel: str, user_id: str) -> dict:
    result = channel_svc.check_frequency_limit(user_id, channel)
    return ok_response(result)


@app.get("/api/v1/channels/{channel}/stats")
async def get_channel_stats(channel: str, start: str = "", end: str = "") -> dict:
    result = channel_svc.get_channel_stats(channel, {"start": start, "end": end})
    if "error" in result:
        return error_response(result["error"])
    return ok_response(result)


@app.post("/api/v1/channels/configure")
async def configure_channel(req: ChannelConfigRequest) -> dict:
    result = channel_svc.configure_channel(req.channel, req.settings)
    if "error" in result:
        return error_response(result["error"])
    return ok_response(result)


@app.get("/api/v1/channels/send-log")
async def get_send_log(
    user_id: Optional[str] = None,
    channel: Optional[str] = None,
    start: str = "",
    end: str = "",
) -> dict:
    date_range = {"start": start, "end": end} if start or end else None
    result = channel_svc.get_send_log(user_id, channel, date_range)
    return ok_response(result)


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
