"""预制量智能推荐服务

基于历史销量数据为当日各菜品推荐备料数量，展示在各档口KDS屏幕上。

推荐算法（三阶段）：
  1. 基线：取过去4周同星期同时段的平均销量
  2. 修正因子：
     - 节假日系数（法定节日 ×1.3 ~ ×2.0）
     - 今日预订数量加成（已订餐厅包厢的预计数量）
     - 天气修正（暂时简单处理：不做）
  3. 安全系数：×1.1（防止供不应求）

输出：
  每道菜 → 推荐备料份数（整数）
"""
from datetime import date
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

# 节假日系数（简单版，实际可接外部API）
_HOLIDAY_BOOST = {
    "2026-01-01": 1.5,   # 元旦
    "2026-02-17": 2.0,   # 春节
    "2026-05-01": 1.4,   # 劳动节
    "2026-10-01": 1.5,   # 国庆节
}

_SAFETY_FACTOR = 1.1   # 安全系数
_LOOKBACK_WEEKS = 4    # 回溯周数


async def get_prep_recommendations(
    tenant_id: str,
    store_id: str,
    dept_id: Optional[str],
    target_date: Optional[date],
    db: AsyncSession,
) -> list[dict]:
    """生成当日备料推荐列表。

    返回：[{dish_id, dish_name, dept_id, recommended_qty, baseline_qty, boost_factor, reason}]
    """
    today = target_date or date.today()
    holiday_factor = _HOLIDAY_BOOST.get(today.isoformat(), 1.0)

    # 查询过去4周同星期的历史销量（按菜品聚合）
    historical = await _query_historical_sales(
        tenant_id=tenant_id,
        store_id=store_id,
        dept_id=dept_id,
        weekday=today.weekday(),
        lookback_weeks=_LOOKBACK_WEEKS,
        db=db,
    )

    # 查询今日预订加成
    booking_boost = await _query_booking_boost(
        tenant_id=tenant_id,
        store_id=store_id,
        target_date=today,
        db=db,
    )

    recommendations = []
    for dish in historical:
        dish_id = dish["dish_id"]
        baseline = dish["avg_qty"]

        # 叠加修正因子
        boost = holiday_factor * booking_boost.get(dish_id, 1.0)
        recommended = max(1, round(baseline * boost * _SAFETY_FACTOR))

        recommendations.append({
            "dish_id": dish_id,
            "dish_name": dish["dish_name"],
            "dept_id": dish["dept_id"],
            "dept_name": dish.get("dept_name", ""),
            "recommended_qty": recommended,
            "baseline_qty": round(baseline, 1),
            "boost_factor": round(boost, 2),
            "reason": _build_reason(holiday_factor, booking_boost.get(dish_id, 1.0)),
        })

    # 按推荐数量倒序，方便厨师优先备高需求菜品
    recommendations.sort(key=lambda x: x["recommended_qty"], reverse=True)

    logger.info(
        "kds.prep_recommendation.generated",
        store_id=store_id,
        date=today.isoformat(),
        items=len(recommendations),
        holiday_factor=holiday_factor,
    )
    return recommendations


async def _query_historical_sales(
    tenant_id: str,
    store_id: str,
    dept_id: Optional[str],
    weekday: int,
    lookback_weeks: int,
    db: AsyncSession,
) -> list[dict]:
    """查询历史同星期销量数据（SQL 聚合，避免 N+1）。"""
    dept_filter = "AND dd.dept_id = :dept_id" if dept_id else ""
    sql = text(f"""
        SELECT
            oi.dish_id::TEXT                    AS dish_id,
            d.name                              AS dish_name,
            dd.dept_id::TEXT                    AS dept_id,
            pd.name                             AS dept_name,
            AVG(daily.qty)::FLOAT               AS avg_qty
        FROM (
            SELECT
                DATE_TRUNC('day', o.created_at)::DATE AS sale_date,
                oi2.dish_id,
                SUM(oi2.quantity)                      AS qty
            FROM order_items oi2
            JOIN orders o ON o.id = oi2.order_id
            WHERE o.tenant_id    = :tenant_id
              AND o.store_id     = :store_id
              AND o.created_at  >= NOW() - INTERVAL '{lookback_weeks} weeks'
              AND EXTRACT(DOW FROM o.created_at) = :weekday
              AND o.is_deleted  = FALSE
              AND oi2.is_deleted = FALSE
            GROUP BY 1, 2
        ) daily
        JOIN order_items oi ON oi.dish_id = daily.dish_id AND oi.is_deleted = FALSE
        JOIN dishes d ON d.id = daily.dish_id AND d.is_deleted = FALSE
        LEFT JOIN dish_dept_mappings dd ON dd.dish_id = daily.dish_id
            AND dd.tenant_id = :tenant_id
            {dept_filter}
        LEFT JOIN production_depts pd ON pd.id = dd.dept_id AND pd.is_deleted = FALSE
        WHERE d.tenant_id = :tenant_id
        GROUP BY oi.dish_id, d.name, dd.dept_id, pd.name
        ORDER BY avg_qty DESC
        LIMIT 100
    """)

    params: dict = {
        "tenant_id": tenant_id,
        "store_id": store_id,
        "weekday": weekday,
    }
    if dept_id:
        params["dept_id"] = dept_id

    result = await db.execute(sql, params)
    rows = result.mappings().all()
    return [dict(r) for r in rows]


async def _query_booking_boost(
    tenant_id: str,
    store_id: str,
    target_date: date,
    db: AsyncSession,
) -> dict[str, float]:
    """查询今日预订对特定菜品的需求加成。

    有预订包厢的菜品 boost 系数适当提升。
    """
    sql = text("""
        SELECT
            bpi.dish_id::TEXT  AS dish_id,
            SUM(bpi.quantity)  AS booking_qty
        FROM booking_prep_tasks bpt
        JOIN booking_prep_items bpi ON bpi.task_id = bpt.id
        WHERE bpt.tenant_id = :tenant_id
          AND bpt.store_id  = :store_id
          AND bpt.prep_date = :target_date
          AND bpt.is_deleted = FALSE
        GROUP BY bpi.dish_id
    """)
    try:
        result = await db.execute(sql, {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "target_date": target_date,
        })
        rows = result.mappings().all()
        # 有预订的菜品给 1.2x boost
        return {r["dish_id"]: 1.2 for r in rows if r["booking_qty"] > 0}
    except SQLAlchemyError as exc:
        # booking_prep_items 表可能不存在，降级为无预订加成
        logger.warning(
            "kds_prep.booking_factor_lookup_failed",
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return {}


def _build_reason(holiday_factor: float, booking_factor: float) -> str:
    """构建推荐原因说明文字。"""
    parts = []
    if holiday_factor > 1.0:
        parts.append(f"节假日+{round((holiday_factor - 1) * 100)}%")
    if booking_factor > 1.0:
        parts.append(f"预订加成+{round((booking_factor - 1) * 100)}%")
    parts.append(f"安全系数+{round((_SAFETY_FACTOR - 1) * 100)}%")
    return "、".join(parts) if parts else "基于历史平均"
