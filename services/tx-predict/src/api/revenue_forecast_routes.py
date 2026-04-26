"""营收预测 API 路由

端点：
  GET /api/v1/predict/revenue/{store_id}  — 日/周/月营收预测
  GET /api/v1/predict/revenue/group       — 集团级营收预测汇总
"""

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.traffic_predictor import TrafficPredictor

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/predict/revenue", tags=["revenue-forecast"])


# ── 依赖注入 ──


def _require_tenant(x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID")) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header 必填")
    return x_tenant_id


async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


async def _get_avg_check(store_id: str, tenant_id: str, db: AsyncSession) -> float:
    """获取门店近30天平均客单价（分）"""
    try:
        result = await db.execute(
            text("""
                SELECT COALESCE(AVG(total_amount_fen), 0)
                FROM orders
                WHERE tenant_id = :tenant_id::uuid
                  AND store_id = :store_id::uuid
                  AND is_deleted = FALSE
                  AND created_at >= NOW() - INTERVAL '30 days'
                  AND total_amount_fen > 0
            """),
            {"tenant_id": tenant_id, "store_id": store_id},
        )
        return float(result.scalar() or 0)
    except (AttributeError, TypeError) as exc:
        logger.debug("revenue.avg_check_error", error=str(exc))
        return 0.0


async def _get_store_list(tenant_id: str, db: AsyncSession) -> list[dict]:
    """获取租户下所有门店"""
    try:
        result = await db.execute(
            text("""
                SELECT id::text, store_name, city
                FROM stores
                WHERE tenant_id = :tenant_id::uuid
                  AND is_deleted = FALSE
            """),
            {"tenant_id": tenant_id},
        )
        return [{"store_id": r[0], "store_name": r[1], "city": r[2]} for r in result.fetchall()]
    except (AttributeError, TypeError) as exc:
        logger.debug("revenue.store_list_error", error=str(exc))
        return []


# ── 1. 单店营收预测 ──


@router.get(
    "/{store_id}",
    summary="日/周/月营收预测",
    description="基于客流预测 x 客单价计算营收预测（日/周/月三个维度）",
)
async def get_revenue_forecast(
    store_id: str,
    city: Optional[str] = Query(None, description="城市名（天气修正）"),
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """营收预测 = 预测客流 x 平均客单价

    逻辑：
    1. 调用 TrafficPredictor 获取7天客流预测
    2. 查询近30天平均客单价
    3. 客流 x 客单价 = 营收预测
    4. 汇总为日/周/月视图
    """
    predictor = TrafficPredictor()

    try:
        traffic = await predictor.forecast_7days(store_id, tenant_id, db, city=city)
    except (ValueError, KeyError) as exc:
        logger.warning("revenue_forecast.traffic_error", store_id=store_id, error=str(exc))
        raise HTTPException(status_code=422, detail=str(exc))

    avg_check_fen = await _get_avg_check(store_id, tenant_id, db)

    daily_revenue = []
    week_total_fen = 0

    for day in traffic.get("daily_forecasts", []):
        day_traffic = day.get("total_traffic", 0)
        day_revenue_fen = round(day_traffic * avg_check_fen)

        daily_revenue.append(
            {
                "date": day["date"],
                "weekday_name": day.get("weekday_name", ""),
                "predicted_traffic": day_traffic,
                "predicted_revenue_fen": day_revenue_fen,
                "predicted_revenue_yuan": round(day_revenue_fen / 100, 2),
            }
        )
        week_total_fen += day_revenue_fen

    # 月预测（7天 x 4.3）
    month_total_fen = round(week_total_fen * (30 / 7))

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "avg_check_fen": round(avg_check_fen),
            "avg_check_yuan": round(avg_check_fen / 100, 2),
            "daily_revenue": daily_revenue,
            "week_total_fen": week_total_fen,
            "week_total_yuan": round(week_total_fen / 100, 2),
            "month_estimated_fen": month_total_fen,
            "month_estimated_yuan": round(month_total_fen / 100, 2),
        },
    }


# ── 2. 集团级营收预测汇总 ──


@router.get(
    "/group",
    summary="集团级营收预测汇总",
    description="汇总所有门店的营收预测，提供集团总览",
)
async def get_group_revenue_forecast(
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(_get_tenant_db),
):
    stores = await _get_store_list(tenant_id, db)

    if not stores:
        return {
            "ok": True,
            "data": {
                "store_count": 0,
                "stores": [],
                "group_week_total_fen": 0,
                "group_month_estimated_fen": 0,
            },
        }

    predictor = TrafficPredictor()
    store_summaries = []
    group_week_total = 0

    for store in stores:
        sid = store["store_id"]
        city = store.get("city")

        try:
            traffic = await predictor.forecast_7days(sid, tenant_id, db, city=city)
            avg_check = await _get_avg_check(sid, tenant_id, db)

            week_traffic = traffic.get("summary", {}).get("total_7d", 0)
            week_revenue = round(week_traffic * avg_check)

            store_summaries.append(
                {
                    "store_id": sid,
                    "store_name": store.get("store_name", ""),
                    "week_traffic": week_traffic,
                    "avg_check_fen": round(avg_check),
                    "week_revenue_fen": week_revenue,
                    "week_revenue_yuan": round(week_revenue / 100, 2),
                }
            )
            group_week_total += week_revenue

        except (ValueError, KeyError) as exc:
            logger.warning("revenue_forecast.group_store_error", store_id=sid, error=str(exc))
            store_summaries.append(
                {
                    "store_id": sid,
                    "store_name": store.get("store_name", ""),
                    "week_traffic": 0,
                    "avg_check_fen": 0,
                    "week_revenue_fen": 0,
                    "week_revenue_yuan": 0,
                    "error": str(exc),
                }
            )

    # 按周营收降序
    store_summaries.sort(key=lambda x: x.get("week_revenue_fen", 0), reverse=True)
    group_month_total = round(group_week_total * (30 / 7))

    return {
        "ok": True,
        "data": {
            "store_count": len(stores),
            "stores": store_summaries,
            "group_week_total_fen": group_week_total,
            "group_week_total_yuan": round(group_week_total / 100, 2),
            "group_month_estimated_fen": group_month_total,
            "group_month_estimated_yuan": round(group_month_total / 100, 2),
        },
    }
