"""市场情报中枢 (Market Intelligence Hub) — FastAPI 主应用

提供竞对监测、消费洞察、口碑分析、新品雷达、价格洞察、情报报告、试点建议等 API。
"""

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from services.calendar_signal import CalendarSignalService
from services.competitor_monitor import CompetitorMonitorService
from services.consumer_insight import ConsumerInsightService
from services.intel_report_engine import IntelReportEngine
from services.new_product_radar import NewProductRadar
from services.pilot_suggestion import PilotSuggestionService
from services.pricing_insight import PricingInsightService
from services.review_topic_engine import ReviewTopicEngine
from services.weather_signal import WeatherSignalService

AGENT_SERVICE_URL = os.getenv("AGENT_SERVICE_URL", "http://tx-agent:8008")


async def _daily_intel_report_task() -> None:
    """每日0点自动生成竞对情报周报（后台任务）"""
    import structlog as _structlog

    _logger = _structlog.get_logger("daily_intel_task")

    while True:
        now = datetime.now()
        # 计算到明日0点的等待时间
        tomorrow_midnight = datetime(now.year, now.month, now.day) + timedelta(days=1)
        wait_seconds = (tomorrow_midnight - now).total_seconds()
        _logger.info("daily_intel_task_scheduled", wait_seconds=int(wait_seconds))
        await asyncio.sleep(wait_seconds)

        # 触发周报生成
        week_end = datetime.now().date().isoformat()
        week_start = (datetime.now().date() - timedelta(days=7)).isoformat()
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{AGENT_SERVICE_URL}/api/v1/agent/dispatch",
                    headers={"X-Tenant-ID": "system"},
                    json={
                        "agent_id": "competitor_watch",
                        "action": "generate_weekly_intel_report",
                        "params": {
                            "tenant_id": "system",
                            "competitor_snapshots": [],
                            "own_reviews": [],
                            "competitor_reviews": [],
                            "market_trends": [],
                            "week_start": week_start,
                            "week_end": week_end,
                        },
                    },
                )
                _logger.info(
                    "daily_intel_report_completed",
                    status_code=resp.status_code,
                    week_start=week_start,
                    week_end=week_end,
                )
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            _logger.warning("daily_intel_report_failed", error=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_daily_intel_report_task())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="屯象OS — 市场情报中枢",
    description="Market Intelligence Hub: 竞对监测、消费洞察、口碑分析、新品雷达、价格洞察、情报报告、试点建议、天气信号、节庆日历",
    version="1.1.0",
    lifespan=lifespan,
)

from prometheus_fastapi_instrumentator import Instrumentator

Instrumentator().instrument(app).expose(app)

# /api/v1/intel/competitor-monitor/* — 竞品监控（v207）
from .api.competitor_monitoring_routes import router as competitor_monitoring_router

app.include_router(competitor_monitoring_router)

# ─── 服务实例 ───

competitor_svc = CompetitorMonitorService()
consumer_svc = ConsumerInsightService()
review_engine = ReviewTopicEngine()
product_radar = NewProductRadar()
pricing_svc = PricingInsightService()
report_engine = IntelReportEngine()
pilot_svc = PilotSuggestionService()
weather_svc = WeatherSignalService()
calendar_svc = CalendarSignalService()


# ─── 通用响应 ───


def ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


def err(message: str, status_code: int = 400) -> None:
    raise HTTPException(status_code=status_code, detail={"ok": False, "data": None, "error": message})


# ═══════════════════════════════════════
# 竞对监测 API
# ═══════════════════════════════════════


class RegisterCompetitorReq(BaseModel):
    name: str
    category: str
    price_tier: str
    cities: list[str]
    stores_count: int
    monitor_level: str
    tags: list[str] = []
    avg_rating: float = 0.0
    avg_spend_fen: int = 0
    notes: str = ""


class RecordActionReq(BaseModel):
    competitor_id: str
    action_type: str
    title: str
    detail: str
    impact_level: str
    source: str
    city: str = ""


@app.post("/api/v1/intel/competitors")
def register_competitor(req: RegisterCompetitorReq) -> dict:
    try:
        result = competitor_svc.register_competitor(
            name=req.name,
            category=req.category,
            price_tier=req.price_tier,
            cities=req.cities,
            stores_count=req.stores_count,
            monitor_level=req.monitor_level,
            tags=req.tags,
            avg_rating=req.avg_rating,
            avg_spend_fen=req.avg_spend_fen,
            notes=req.notes,
        )
        return ok(result)
    except ValueError as e:
        err(str(e))


@app.get("/api/v1/intel/competitors")
def list_competitors(
    category: Optional[str] = None,
    city: Optional[str] = None,
) -> dict:
    return ok(competitor_svc.list_competitors(category=category, city=city))


@app.get("/api/v1/intel/competitors/{competitor_id}")
def get_competitor_detail(competitor_id: str) -> dict:
    try:
        return ok(competitor_svc.get_competitor_detail(competitor_id))
    except KeyError as e:
        err(str(e), 404)


@app.post("/api/v1/intel/competitors/actions")
def record_action(req: RecordActionReq) -> dict:
    try:
        result = competitor_svc.record_competitor_action(
            competitor_id=req.competitor_id,
            action_type=req.action_type,
            title=req.title,
            detail=req.detail,
            impact_level=req.impact_level,
            source=req.source,
            city=req.city,
        )
        return ok(result)
    except (KeyError, ValueError) as e:
        err(str(e), 400)


@app.get("/api/v1/intel/competitors/actions/recent")
def get_recent_actions(
    days: int = 7,
    competitor_id: Optional[str] = None,
    action_type: Optional[str] = None,
) -> dict:
    return ok(competitor_svc.get_recent_actions(days=days, competitor_id=competitor_id, action_type=action_type))


@app.get("/api/v1/intel/competitors/{competitor_id}/compare")
def compare_with_self(competitor_id: str, metrics: str = "stores_count,avg_rating,avg_spend_fen") -> dict:
    try:
        metric_list = [m.strip() for m in metrics.split(",")]
        return ok(competitor_svc.compare_with_self(competitor_id, metric_list))
    except KeyError as e:
        err(str(e), 404)


@app.get("/api/v1/intel/competitors/{competitor_id}/timeline")
def get_competitor_timeline(competitor_id: str, days: int = 90) -> dict:
    try:
        return ok(competitor_svc.get_competitor_timeline(competitor_id, days))
    except KeyError as e:
        err(str(e), 404)


@app.get("/api/v1/intel/threats")
def detect_threats() -> dict:
    return ok(competitor_svc.detect_threats())


@app.get("/api/v1/intel/competitors/{competitor_id}/summary")
def get_competitor_summary(competitor_id: str) -> dict:
    try:
        return ok(competitor_svc.generate_competitor_summary(competitor_id))
    except KeyError as e:
        err(str(e), 404)


# ═══════════════════════════════════════
# 消费需求洞察 API
# ═══════════════════════════════════════


class IngestSignalReq(BaseModel):
    source_type: str
    content: str
    city: Optional[str] = None
    store_id: Optional[str] = None


class ExtractTopicsReq(BaseModel):
    signals: list[dict]


@app.post("/api/v1/intel/signals")
def ingest_signal(req: IngestSignalReq) -> dict:
    try:
        result = consumer_svc.ingest_signal(
            source_type=req.source_type,
            content=req.content,
            city=req.city,
            store_id=req.store_id,
        )
        return ok(result)
    except ValueError as e:
        err(str(e))


@app.post("/api/v1/intel/signals/extract-topics")
def extract_topics(req: ExtractTopicsReq) -> dict:
    return ok(consumer_svc.extract_topics(req.signals))


@app.get("/api/v1/intel/topics/trending")
def get_trending_topics(
    category: Optional[str] = None,
    city: Optional[str] = None,
    days: int = 30,
) -> dict:
    return ok(consumer_svc.get_trending_topics(category=category, city=city, days=days))


@app.get("/api/v1/intel/topics/{topic_id}")
def get_topic_detail(topic_id: str) -> dict:
    try:
        return ok(consumer_svc.get_topic_detail(topic_id))
    except KeyError as e:
        err(str(e), 404)


@app.get("/api/v1/intel/demand/summary")
def get_demand_summary(period: str = "week") -> dict:
    return ok(consumer_svc.get_demand_change_summary(period=period))


@app.get("/api/v1/intel/demand/compare-cities")
def compare_cities(cities: str = "长沙,深圳") -> dict:
    city_list = [c.strip() for c in cities.split(",")]
    return ok(consumer_svc.compare_cities(city_list))


@app.get("/api/v1/intel/demand/emerging")
def detect_emerging_needs() -> dict:
    return ok(consumer_svc.detect_emerging_needs())


# ═══════════════════════════════════════
# 口碑主题分析 API
# ═══════════════════════════════════════


class AnalyzeReviewsReq(BaseModel):
    reviews: list[dict]


@app.post("/api/v1/intel/reviews/analyze")
def analyze_reviews(req: AnalyzeReviewsReq) -> dict:
    return ok(review_engine.analyze_reviews(req.reviews))


@app.get("/api/v1/intel/reviews/topics")
def get_review_topic_summary(
    store_id: Optional[str] = None,
    topic_type: Optional[str] = None,
    days: int = 30,
) -> dict:
    return ok(review_engine.get_topic_summary(store_id=store_id, topic_type=topic_type, days=days))


@app.get("/api/v1/intel/reviews/dishes")
def get_dish_mentions(store_id: Optional[str] = None, days: int = 30) -> dict:
    return ok(review_engine.get_dish_mentions(store_id=store_id, days=days))


@app.get("/api/v1/intel/reviews/compare-stores")
def compare_stores_reputation(store_ids: str = "S001,S002") -> dict:
    sid_list = [s.strip() for s in store_ids.split(",")]
    return ok(review_engine.compare_stores_reputation(sid_list))


@app.get("/api/v1/intel/reviews/issues")
def get_actionable_issues(store_id: Optional[str] = None) -> dict:
    return ok(review_engine.get_actionable_issues(store_id=store_id))


@app.get("/api/v1/intel/reviews/highlights")
def get_marketing_highlights(store_id: Optional[str] = None) -> dict:
    return ok(review_engine.get_marketing_highlights(store_id=store_id))


@app.get("/api/v1/intel/reviews/trend/{topic_name}")
def track_topic_trend(topic_name: str, days: int = 90) -> dict:
    return ok(review_engine.track_topic_trend(topic_name, days=days))


# ═══════════════════════════════════════
# 新品雷达 API
# ═══════════════════════════════════════


class RegisterOpportunityReq(BaseModel):
    name: str
    category: str
    source: str
    description: str
    market_heat_score: float = 0.0
    brand_fit_score: float = 0.0
    audience_fit_score: float = 0.0
    cost_feasibility_score: float = 0.0


class CreatePilotPlanReq(BaseModel):
    opportunity_id: str
    stores: list[str]
    period_days: int
    metrics: list[str]


@app.post("/api/v1/intel/opportunities")
def register_opportunity(req: RegisterOpportunityReq) -> dict:
    result = product_radar.register_opportunity(
        name=req.name,
        category=req.category,
        source=req.source,
        description=req.description,
        market_heat_score=req.market_heat_score,
        brand_fit_score=req.brand_fit_score,
        audience_fit_score=req.audience_fit_score,
        cost_feasibility_score=req.cost_feasibility_score,
    )
    return ok(result)


@app.get("/api/v1/intel/opportunities")
def list_opportunities(
    status: Optional[str] = None,
    category: Optional[str] = None,
    sort_by: str = "score",
) -> dict:
    return ok(product_radar.list_opportunities(status=status, category=category, sort_by=sort_by))


@app.get("/api/v1/intel/opportunities/{opportunity_id}")
def get_opportunity_detail(opportunity_id: str) -> dict:
    try:
        return ok(product_radar.get_opportunity_detail(opportunity_id))
    except KeyError as e:
        err(str(e), 404)


@app.get("/api/v1/intel/opportunities/{opportunity_id}/score")
def score_opportunity(opportunity_id: str) -> dict:
    try:
        return ok(product_radar.score_opportunity(opportunity_id))
    except KeyError as e:
        err(str(e), 404)


@app.get("/api/v1/intel/opportunities/{opportunity_id}/pilot-stores")
def recommend_pilot_stores(opportunity_id: str) -> dict:
    try:
        return ok(product_radar.recommend_pilot_stores(opportunity_id))
    except KeyError as e:
        err(str(e), 404)


@app.post("/api/v1/intel/opportunities/pilot-plan")
def create_pilot_plan(req: CreatePilotPlanReq) -> dict:
    try:
        result = product_radar.create_pilot_plan(
            opportunity_id=req.opportunity_id,
            stores=req.stores,
            period_days=req.period_days,
            metrics=req.metrics,
        )
        return ok(result)
    except KeyError as e:
        err(str(e), 404)


@app.get("/api/v1/intel/ingredients/trends")
def track_ingredient_trends(days: int = 90) -> dict:
    return ok(product_radar.track_ingredient_trends(days=days))


@app.get("/api/v1/intel/flavors/new")
def detect_new_flavors() -> dict:
    return ok(product_radar.detect_new_flavors())


@app.get("/api/v1/intel/ingredients/{ingredient_name}/feasibility")
def assess_supply_feasibility(ingredient_name: str) -> dict:
    return ok(product_radar.assess_supply_feasibility(ingredient_name))


# ═══════════════════════════════════════
# 价格洞察 API
# ═══════════════════════════════════════


class SuggestPriceReq(BaseModel):
    dish_id: str
    current_price_fen: int


@app.get("/api/v1/intel/pricing/bands")
def analyze_price_bands(category: str, city: Optional[str] = None) -> dict:
    return ok(pricing_svc.analyze_price_bands(category=category, city=city))


@app.get("/api/v1/intel/pricing/competitor-compare")
def compare_competitor_pricing(
    competitor_ids: str = "",
    dish_category: Optional[str] = None,
) -> dict:
    cid_list = [c.strip() for c in competitor_ids.split(",") if c.strip()]
    return ok(pricing_svc.compare_competitor_pricing(cid_list, dish_category=dish_category))


@app.get("/api/v1/intel/pricing/set-meal-trends")
def analyze_set_meal_trends(city: Optional[str] = None) -> dict:
    return ok(pricing_svc.analyze_set_meal_trends(city=city))


@app.post("/api/v1/intel/pricing/suggest")
def suggest_price_adjustment(req: SuggestPriceReq) -> dict:
    return ok(pricing_svc.suggest_price_adjustment(req.dish_id, req.current_price_fen))


@app.get("/api/v1/intel/pricing/spend-trend")
def analyze_spend_trend(days: int = 90) -> dict:
    return ok(pricing_svc.analyze_customer_spend_trend(days=days))


@app.get("/api/v1/intel/pricing/value-gaps")
def detect_value_gaps() -> dict:
    return ok(pricing_svc.detect_value_perception_gap())


# ═══════════════════════════════════════
# 情报报告 API
# ═══════════════════════════════════════


class GenerateReportReq(BaseModel):
    report_type: str
    date_range: dict
    city: Optional[str] = None


class ScheduleReportReq(BaseModel):
    report_type: str
    frequency: str
    recipients: list[str]


@app.post("/api/v1/intel/reports/generate")
def generate_report(req: GenerateReportReq) -> dict:
    try:
        result = report_engine.generate_report(
            report_type=req.report_type,
            date_range=req.date_range,
            city=req.city,
        )
        return ok(result)
    except ValueError as e:
        err(str(e))


@app.get("/api/v1/intel/reports")
def list_reports(report_type: Optional[str] = None) -> dict:
    return ok(report_engine.list_reports(report_type=report_type))


@app.get("/api/v1/intel/reports/{report_id}")
def get_report_detail(report_id: str) -> dict:
    try:
        return ok(report_engine.get_report_detail(report_id))
    except KeyError as e:
        err(str(e), 404)


@app.post("/api/v1/intel/reports/schedule")
def schedule_report(req: ScheduleReportReq) -> dict:
    try:
        result = report_engine.schedule_auto_report(
            report_type=req.report_type,
            frequency=req.frequency,
            recipients=req.recipients,
        )
        return ok(result)
    except ValueError as e:
        err(str(e))


@app.get("/api/v1/intel/reports/{report_id}/export")
def export_report(report_id: str, format: str = "pdf") -> dict:
    try:
        return ok(report_engine.export_report(report_id, format=format))
    except (KeyError, ValueError) as e:
        err(str(e), 400)


# ═══════════════════════════════════════
# 试点建议 API
# ═══════════════════════════════════════


class CreateSuggestionReq(BaseModel):
    source_type: str
    source_id: str
    suggestion_type: str
    title: str
    description: str
    recommended_stores: list[str]
    period_days: int
    success_metrics: list[dict]


class ApprovePilotReq(BaseModel):
    suggestion_id: str
    approved_stores: list[str]
    adjusted_metrics: Optional[list[dict]] = None


class CompletePilotReq(BaseModel):
    pilot_id: str
    results: dict
    conclusion: str


@app.post("/api/v1/intel/pilots/suggestions")
def create_suggestion(req: CreateSuggestionReq) -> dict:
    try:
        result = pilot_svc.create_suggestion(
            source_type=req.source_type,
            source_id=req.source_id,
            suggestion_type=req.suggestion_type,
            title=req.title,
            description=req.description,
            recommended_stores=req.recommended_stores,
            period_days=req.period_days,
            success_metrics=req.success_metrics,
        )
        return ok(result)
    except ValueError as e:
        err(str(e))


@app.get("/api/v1/intel/pilots/suggestions")
def list_suggestions(
    status: Optional[str] = None,
    suggestion_type: Optional[str] = None,
) -> dict:
    return ok(pilot_svc.list_suggestions(status=status, suggestion_type=suggestion_type))


@app.post("/api/v1/intel/pilots/approve")
def approve_pilot(req: ApprovePilotReq) -> dict:
    try:
        result = pilot_svc.approve_pilot(
            suggestion_id=req.suggestion_id,
            approved_stores=req.approved_stores,
            adjusted_metrics=req.adjusted_metrics,
        )
        return ok(result)
    except (KeyError, ValueError) as e:
        err(str(e), 400)


@app.get("/api/v1/intel/pilots/{pilot_id}/progress")
def track_pilot_progress(pilot_id: str) -> dict:
    try:
        return ok(pilot_svc.track_pilot_progress(pilot_id))
    except KeyError as e:
        err(str(e), 404)


@app.post("/api/v1/intel/pilots/review")
def complete_pilot_review(req: CompletePilotReq) -> dict:
    try:
        result = pilot_svc.complete_pilot_review(
            pilot_id=req.pilot_id,
            results=req.results,
            conclusion=req.conclusion,
        )
        return ok(result)
    except KeyError as e:
        err(str(e), 404)


@app.get("/api/v1/intel/pilots/{pilot_id}/scale-up")
def recommend_scale_up(pilot_id: str) -> dict:
    try:
        return ok(pilot_svc.recommend_scale_up(pilot_id))
    except (KeyError, ValueError) as e:
        err(str(e), 400)


@app.get("/api/v1/intel/pilots/portfolio")
def get_pilot_portfolio() -> dict:
    return ok(pilot_svc.get_pilot_portfolio())


# ═══════════════════════════════════════
# 天气信号 API（V3.0 新增）
# ═══════════════════════════════════════


@app.get("/api/v1/intel/weather/signal")
async def get_weather_signal(city: str, target_date: Optional[str] = None) -> dict:
    from datetime import date as _date

    td = _date.fromisoformat(target_date) if target_date else None
    result = await weather_svc.get_weather_signal(city, td)
    return ok(result)


@app.get("/api/v1/intel/weather/forecast")
async def get_weather_forecast(city: str) -> dict:
    result = await weather_svc.get_weekly_forecast_signals(city)
    return ok(result)


# ═══════════════════════════════════════
# 节庆日历 API（V3.0 新增）
# ═══════��══════════════════════��════════


@app.get("/api/v1/intel/calendar/upcoming")
def get_upcoming_events(days: int = 14) -> dict:
    return ok(calendar_svc.get_upcoming_events(days_ahead=days))


@app.get("/api/v1/intel/calendar/triggers")
def get_growth_triggers() -> dict:
    return ok(calendar_svc.get_growth_triggers())


@app.get("/api/v1/intel/calendar/event")
def get_event_by_date(target_date: str) -> dict:
    result = calendar_svc.get_event_by_date(target_date)
    if result is None:
        err("Event not found", 404)
    return ok(result)


# ─── 评价情感分析路由 ───

from .api.sentiment_routes import router as sentiment_router

app.include_router(sentiment_router)

# ─── 健康检查 ───


@app.get("/health")
def health_check() -> dict:
    return ok(
        {
            "service": "tx-intel",
            "version": "1.1.0",
            "engines": [
                "competitor_monitor",
                "consumer_insight",
                "review_topic_engine",
                "new_product_radar",
                "pricing_insight",
                "intel_report_engine",
                "pilot_suggestion",
                "weather_signal",
                "calendar_signal",
                "sentiment_analysis",
            ],
        }
    )
