"""经营洞察 API 路由 — 门店对比排名 + 餐段分析

前缀: /api/v1/analytics

端点:
  GET  /store-insights    — 多门店经营排名（营收/客流/翻台率/毛利率/健康度）
  GET  /period-analysis   — 餐段分析（按午/晚/夜宵分时段营收/客流/热销菜品）
"""
import uuid
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/analytics", tags=["insights"])


# ─── 辅助 ──────────────────────────────────────────────────────────────────────

def _require_tenant(tenant_id: Optional[str]) -> uuid.UUID:
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    try:
        return uuid.UUID(tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid tenant_id: {tenant_id}") from exc


def _today() -> str:
    return date.today().isoformat()


# ═══════════════════════════════════════════════════════════════════════════════
# 门店经营洞察
# ═══════════════════════════════════════════════════════════════════════════════

class StoreMetric(BaseModel):
    store_id: str
    store_name: str
    region: str
    revenue_fen: int
    order_count: int
    guest_count: int
    avg_check_fen: int
    table_turn_rate: float
    gross_margin: float
    health_score: int
    revenue_growth: float
    complaint_count: int


class StoreInsightsResponse(BaseModel):
    ok: bool = True
    data: dict = Field(default_factory=dict)


@router.get("/store-insights")
async def get_store_insights(
    period: str = Query("today", description="today|week|month"),
    region: str = Query("", description="区域筛选（空=全部）"),
    x_tenant_id: str = Header(None, alias="X-Tenant-ID"),
):
    """多门店经营排名 — 供 StoreInsightsPage 调用"""
    tid = _require_tenant(x_tenant_id)

    # TODO: 从物化视图 mv_store_pnl + mv_daily_settlement 聚合查询
    # 当前返回演示数据，接入真实DB后替换
    demo_stores = [
        StoreMetric(store_id="s1", store_name="徐记海鲜·芙蓉店", region="长沙", revenue_fen=8560000, order_count=420, guest_count=1260, avg_check_fen=6800, table_turn_rate=3.2, gross_margin=0.62, health_score=92, revenue_growth=0.08, complaint_count=1),
        StoreMetric(store_id="s2", store_name="徐记海鲜·梅溪湖店", region="长沙", revenue_fen=6320000, order_count=310, guest_count=930, avg_check_fen=6800, table_turn_rate=2.8, gross_margin=0.58, health_score=85, revenue_growth=0.05, complaint_count=3),
        StoreMetric(store_id="s3", store_name="徐记海鲜·IFS店", region="长沙", revenue_fen=12800000, order_count=580, guest_count=1740, avg_check_fen=7400, table_turn_rate=3.8, gross_margin=0.65, health_score=96, revenue_growth=0.12, complaint_count=0),
        StoreMetric(store_id="s4", store_name="徐记海鲜·武汉光谷店", region="武汉", revenue_fen=5100000, order_count=260, guest_count=780, avg_check_fen=6500, table_turn_rate=2.5, gross_margin=0.55, health_score=78, revenue_growth=-0.03, complaint_count=5),
        StoreMetric(store_id="s5", store_name="徐记海鲜·深圳万象城店", region="深圳", revenue_fen=15200000, order_count=650, guest_count=1950, avg_check_fen=7800, table_turn_rate=4.1, gross_margin=0.68, health_score=98, revenue_growth=0.15, complaint_count=0),
        StoreMetric(store_id="s6", store_name="徐记海鲜·广州天河店", region="广州", revenue_fen=9800000, order_count=470, guest_count=1410, avg_check_fen=6950, table_turn_rate=3.5, gross_margin=0.60, health_score=88, revenue_growth=0.06, complaint_count=2),
    ]

    items = demo_stores
    if region:
        items = [s for s in items if s.region == region]

    return {
        "ok": True,
        "data": {
            "items": [s.model_dump() for s in items],
            "period": period,
            "total": len(items),
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 餐段分析
# ═══════════════════════════════════════════════════════════════════════════════

class TopDish(BaseModel):
    name: str
    count: int
    revenue_fen: int


class PeriodData(BaseModel):
    period_name: str
    start_time: str
    end_time: str
    revenue_fen: int
    order_count: int
    guest_count: int
    avg_check_fen: int
    table_turn_rate: float
    top_dishes: list[TopDish]
    peak_hour: str
    occupancy_rate: float


@router.get("/period-analysis")
async def get_period_analysis(
    store_id: str = Query(..., description="门店ID"),
    analysis_date: str = Query("", description="日期 YYYY-MM-DD（默认今日）"),
    x_tenant_id: str = Header(None, alias="X-Tenant-ID"),
):
    """按餐段分析 — 供 PeriodAnalysisPage 调用"""
    tid = _require_tenant(x_tenant_id)
    target_date = analysis_date or _today()

    # TODO: 从 orders + order_items 按时段聚合查询
    # 当前返回演示数据
    demo_periods = [
        PeriodData(
            period_name="午餐", start_time="11:00", end_time="14:00",
            revenue_fen=3850000, order_count=185, guest_count=555, avg_check_fen=6940, table_turn_rate=1.8,
            top_dishes=[
                TopDish(name="剁椒鱼头", count=68, revenue_fen=598400),
                TopDish(name="口味虾", count=52, revenue_fen=665600),
                TopDish(name="农家小炒肉", count=95, revenue_fen=399000),
                TopDish(name="蒜蓉粉丝蒸扇贝", count=48, revenue_fen=326400),
                TopDish(name="米饭", count=420, revenue_fen=126000),
            ],
            peak_hour="12:00-12:30", occupancy_rate=0.92,
        ),
        PeriodData(
            period_name="晚餐", start_time="17:00", end_time="21:00",
            revenue_fen=4280000, order_count=195, guest_count=630, avg_check_fen=6800, table_turn_rate=1.5,
            top_dishes=[
                TopDish(name="口味虾", count=78, revenue_fen=998400),
                TopDish(name="剁椒鱼头", count=72, revenue_fen=633600),
                TopDish(name="红烧肉", count=55, revenue_fen=319000),
                TopDish(name="鲈鱼（活）", count=35, revenue_fen=406000),
                TopDish(name="酸梅汤", count=180, revenue_fen=144000),
            ],
            peak_hour="18:30-19:00", occupancy_rate=0.98,
        ),
        PeriodData(
            period_name="夜宵", start_time="21:00", end_time="23:30",
            revenue_fen=430000, order_count=40, guest_count=75, avg_check_fen=5700, table_turn_rate=0.5,
            top_dishes=[
                TopDish(name="口味虾", count=22, revenue_fen=281600),
                TopDish(name="凉拌黄瓜", count=18, revenue_fen=16200),
                TopDish(name="酸梅汤", count=35, revenue_fen=28000),
            ],
            peak_hour="21:30-22:00", occupancy_rate=0.35,
        ),
    ]

    return {
        "ok": True,
        "data": {
            "periods": [p.model_dump() for p in demo_periods],
            "store_id": store_id,
            "date": target_date,
        },
    }
