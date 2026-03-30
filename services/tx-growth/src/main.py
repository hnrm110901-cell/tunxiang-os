"""tx-growth — 增长中枢微服务

品牌策略、客户分群、触发式营销编排、内容生成、优惠策略、渠道触达、ROI归因

七大引擎协同驱动连锁餐饮品牌的精细化增长。
"""
import asyncio

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, Optional

from services.brand_strategy import BrandStrategyService
from services.audience_segmentation import AudienceSegmentationService
from services.journey_orchestrator import JourneyOrchestratorService
from services.content_engine import ContentEngine
from services.offer_engine import OfferEngine
from services.channel_engine import ChannelEngine
from services.roi_attribution import ROIAttributionService
from workers.journey_executor import JourneyExecutor

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

from .api.campaign_routes import router as campaign_router
from .api.segmentation_routes import router as segmentation_router

app = FastAPI(title="TunxiangOS tx-growth", version="3.0.0")
app.include_router(campaign_router)
app.include_router(segmentation_router)

# ---------------------------------------------------------------------------
# APScheduler — 旅程执行引擎（每60秒 tick 一次）
# ---------------------------------------------------------------------------

_scheduler = AsyncIOScheduler()
_journey_executor = JourneyExecutor()


def _schedule_tick() -> None:
    """
    调度回调：创建一个 asyncio Task 执行 JourneyExecutor.tick()。

    使用 asyncio.create_task 而非 await，保证 APScheduler 的调度线程不阻塞。
    Task 内部异常通过 structlog 记录，不会静默丢失。
    """
    task = asyncio.create_task(_journey_executor.tick())
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


@app.on_event("startup")
async def start_scheduler() -> None:
    """FastAPI 启动时启动 APScheduler，每60秒驱动旅程引擎 tick。"""
    _scheduler.add_job(
        _schedule_tick,
        trigger="interval",
        seconds=60,
        id="journey_executor",
        replace_existing=True,
        max_instances=1,          # 防止并发 tick 重叠
        misfire_grace_time=30,    # 系统繁忙时延迟30秒内可补发
    )
    _scheduler.start()
    logger.info("journey_executor_scheduler_started", interval_seconds=60)


@app.on_event("shutdown")
async def stop_scheduler() -> None:
    """FastAPI 关闭时优雅停止调度器。"""
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("journey_executor_scheduler_stopped")

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
