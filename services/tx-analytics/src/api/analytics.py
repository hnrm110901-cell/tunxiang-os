"""经营分析 API"""
from typing import Optional
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


# 门店健康度
@router.get("/stores/health")
async def get_store_health(store_id: Optional[str] = None, date: Optional[str] = None):
    """门店健康度评分（5维度加权：营收/翻台率/成本率/客诉/人效）"""
    return {"ok": True, "data": {"scores": []}}

@router.get("/stores/{store_id}/health/detail")
async def get_store_health_detail(store_id: str):
    return {"ok": True, "data": {"dimensions": {}}}

# 经营简报
@router.get("/stores/{store_id}/brief")
async def get_store_brief(store_id: str, date: str = "today"):
    """经营简报（≤200字 NarrativeEngine）"""
    return {"ok": True, "data": {"brief": "", "metrics": {}}}

# KPI 监控
@router.get("/kpi/alerts")
async def get_kpi_alerts(store_id: str):
    return {"ok": True, "data": {"alerts": []}}

@router.get("/kpi/trend")
async def get_kpi_trend(store_id: str, kpi_name: str, days: int = 30):
    return {"ok": True, "data": {"trend": []}}

# 报表
@router.get("/reports/daily")
async def get_daily_report(store_id: str, date: Optional[str] = None):
    return {"ok": True, "data": {"report": {}}}

@router.get("/reports/weekly")
async def get_weekly_report(store_id: str, week: Optional[str] = None):
    return {"ok": True, "data": {"report": {}}}

# 经营决策
@router.get("/decisions/top3")
async def get_top3_decisions(store_id: str):
    """Top3 AI 决策推荐（含¥影响分）"""
    return {"ok": True, "data": {"decisions": []}}

@router.get("/decisions/behavior-report")
async def get_behavior_report(store_id: str, start_date: str, end_date: str):
    """AI建议采纳率报告"""
    return {"ok": True, "data": {"adoption_rate": 0, "roi_summary": {}}}

# 场景识别
@router.get("/scenario")
async def identify_scenario(store_id: str):
    """当前经营场景识别（节假日/雨天/促销等）"""
    return {"ok": True, "data": {"scenario": "weekday_normal", "similar_cases": []}}

# 跨店分析
@router.get("/cross-store/insights")
async def get_cross_store_insights(brand_id: str):
    return {"ok": True, "data": {"insights": []}}

# 竞品分析
@router.get("/competitive")
async def get_competitive_analysis(store_id: str):
    return {"ok": True, "data": {"analysis": {}}}

# BFF 聚合
@router.get("/bff/hq/{brand_id}")
async def bff_hq(brand_id: str):
    """总部首屏 BFF（30s Redis 缓存）"""
    return {"ok": True, "data": {"health_scores": [], "top_decisions": [], "alerts": []}}

@router.get("/bff/sm/{store_id}")
async def bff_store_manager(store_id: str):
    """店长首屏 BFF"""
    return {"ok": True, "data": {"brief": "", "staffing_advice": {}, "alerts": []}}
