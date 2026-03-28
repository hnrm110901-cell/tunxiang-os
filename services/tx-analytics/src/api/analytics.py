"""经营分析 API — 接通 Repository 真查询"""
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from ..services.repository import AnalyticsRepository
from ..services.narrative_engine import compose_brief
from ..services.store_health_service import classify_health

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


@router.get("/stores/health")
async def get_store_health(request: Request, store_id: Optional[str] = None, date: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    tid = _get_tenant_id(request)
    if not store_id:
        return {"ok": False, "error": {"code": "MISSING_PARAM", "message": "store_id is required"}}
    try:
        repo = AnalyticsRepository(db, tid)
        data = await repo.get_store_health(store_id, date)
        return {"ok": True, "data": {"scores": [data]}}
    except ValueError as exc:
        return {"ok": False, "error": {"code": "NOT_FOUND", "message": str(exc)}}


@router.get("/stores/{store_id}/health/detail")
async def get_store_health_detail(store_id: str, request: Request, date: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    tid = _get_tenant_id(request)
    try:
        repo = AnalyticsRepository(db, tid)
        data = await repo.get_store_health(store_id, date)
        data["level"] = classify_health(data["overall_score"])
        return {"ok": True, "data": {"dimensions": data}}
    except ValueError as exc:
        return {"ok": False, "error": {"code": "NOT_FOUND", "message": str(exc)}}


@router.get("/stores/{store_id}/brief")
async def get_store_brief(store_id: str, request: Request, date: str = "today", db: AsyncSession = Depends(get_db)):
    tid = _get_tenant_id(request)
    try:
        repo = AnalyticsRepository(db, tid)
        daily = await repo.get_daily_report(store_id, date)
        health = await repo.get_store_health(store_id, date)
        alerts = await repo.get_kpi_alerts(store_id)
        decisions = await repo.get_top3_decisions(store_id)
        revenue_yuan = daily["revenue_fen"] / 100
        cost_metrics = {"revenue_yuan": revenue_yuan, "actual_cost_pct": 0.0, "cost_rate_label": "正常", "cost_rate_status": "ok"}
        brief = compose_brief(store_label=f"门店{store_id[:8]}", cost_metrics=cost_metrics, decision_summary={"approved": 0, "total": len(decisions)}, waste_top5=[], pending_count=len(decisions), top_decisions=decisions)
        return {"ok": True, "data": {"brief": brief, "metrics": {"revenue_fen": daily["revenue_fen"], "order_count": daily["order_count"], "avg_ticket_fen": daily["avg_ticket_fen"], "health_score": health["overall_score"], "alert_count": len(alerts)}}}
    except ValueError as exc:
        return {"ok": False, "error": {"code": "NOT_FOUND", "message": str(exc)}}


@router.get("/kpi/alerts")
async def get_kpi_alerts(store_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    tid = _get_tenant_id(request)
    repo = AnalyticsRepository(db, tid)
    alerts = await repo.get_kpi_alerts(store_id)
    return {"ok": True, "data": {"alerts": alerts}}


@router.get("/kpi/trend")
async def get_kpi_trend(store_id: str, kpi_name: str, request: Request, days: int = 30, db: AsyncSession = Depends(get_db)):
    tid = _get_tenant_id(request)
    repo = AnalyticsRepository(db, tid)
    trend = await repo.get_kpi_trend(store_id, kpi_name, days)
    return {"ok": True, "data": {"trend": trend}}


@router.get("/reports/daily")
async def get_daily_report(store_id: str, request: Request, date: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    tid = _get_tenant_id(request)
    repo = AnalyticsRepository(db, tid)
    report = await repo.get_daily_report(store_id, date or "today")
    return {"ok": True, "data": {"report": report}}


@router.get("/reports/weekly")
async def get_weekly_report(store_id: str, request: Request, week: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    tid = _get_tenant_id(request)
    repo = AnalyticsRepository(db, tid)
    report = await repo.get_weekly_report(store_id, week)
    return {"ok": True, "data": {"report": report}}


@router.get("/decisions/top3")
async def get_top3_decisions(store_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    tid = _get_tenant_id(request)
    repo = AnalyticsRepository(db, tid)
    decisions = await repo.get_top3_decisions(store_id)
    return {"ok": True, "data": {"decisions": decisions}}


@router.get("/decisions/behavior-report")
async def get_behavior_report(store_id: str, start_date: str, end_date: str, request: Request, db: AsyncSession = Depends(get_db)):
    tid = _get_tenant_id(request)
    repo = AnalyticsRepository(db, tid)
    report = await repo.get_behavior_report(store_id, start_date, end_date)
    return {"ok": True, "data": report}


@router.get("/scenario")
async def identify_scenario(store_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    tid = _get_tenant_id(request)
    repo = AnalyticsRepository(db, tid)
    scenario = await repo.identify_scenario(store_id)
    return {"ok": True, "data": scenario}


@router.get("/cross-store/insights")
async def get_cross_store_insights(brand_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    tid = _get_tenant_id(request)
    repo = AnalyticsRepository(db, tid)
    insights = await repo.get_cross_store_insights(brand_id)
    return {"ok": True, "data": {"insights": insights}}


@router.get("/competitive")
async def get_competitive_analysis(store_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    tid = _get_tenant_id(request)
    repo = AnalyticsRepository(db, tid)
    analysis = await repo.get_competitive_analysis(store_id)
    return {"ok": True, "data": {"analysis": analysis}}


@router.get("/bff/hq/{brand_id}")
async def bff_hq(brand_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    tid = _get_tenant_id(request)
    repo = AnalyticsRepository(db, tid)
    stores = await repo.get_brand_stores(brand_id)
    health_scores = []
    for store in stores:
        try:
            score = await repo.get_store_health(str(store.id))
            score["store_name"] = store.store_name
            health_scores.append(score)
        except ValueError:
            continue
    all_alerts = []
    for store in stores:
        alerts = await repo.get_kpi_alerts(str(store.id))
        for a in alerts:
            a["store_id"] = str(store.id)
            a["store_name"] = store.store_name
        all_alerts.extend(alerts)
    top_decisions = []
    for store in stores[:3]:
        decisions = await repo.get_top3_decisions(str(store.id))
        for d in decisions:
            d["store_id"] = str(store.id)
            d["store_name"] = store.store_name
        top_decisions.extend(decisions)
    return {"ok": True, "data": {"health_scores": health_scores, "top_decisions": top_decisions[:5], "alerts": all_alerts}}


@router.get("/bff/sm/{store_id}")
async def bff_store_manager(store_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    tid = _get_tenant_id(request)
    repo = AnalyticsRepository(db, tid)
    try:
        daily = await repo.get_daily_report(store_id, "today")
        health = await repo.get_store_health(store_id)
        alerts = await repo.get_kpi_alerts(store_id)
        decisions = await repo.get_top3_decisions(store_id)
        brief = compose_brief(store_label=f"门店{store_id[:8]}", cost_metrics={"revenue_yuan": daily["revenue_fen"] / 100, "actual_cost_pct": 0.0, "cost_rate_label": "正常", "cost_rate_status": "ok"}, decision_summary={"approved": 0, "total": len(decisions)}, waste_top5=[], pending_count=len(decisions), top_decisions=decisions)
        return {"ok": True, "data": {"brief": brief, "health_score": health["overall_score"], "health_level": classify_health(health["overall_score"]), "alerts": alerts, "decisions": decisions, "metrics": {"revenue_fen": daily["revenue_fen"], "order_count": daily["order_count"], "avg_ticket_fen": daily["avg_ticket_fen"], "guest_count": daily["guest_count"]}}}
    except ValueError as exc:
        return {"ok": False, "error": {"code": "NOT_FOUND", "message": str(exc)}}
