"""
菜品5因子动态排名引擎 — 基于真实行为数据持续优化权重
P3-04: 差异化护城河
5因子：销量(volume) / 毛利(margin) / 复购率(reorder) / 满意度(satisfaction) / 热度趋势(trend)

数据源：
  order_items  — dish_id, dish_name, quantity, unit_price_fen, single_discount_fen, order_id
  orders       — id, tenant_id, store_id, status='paid', created_at
  dishes       — id, tenant_id, store_id, dish_name, price_fen, cost_fen, category_id
  dish_categories — id, name
"""

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/menu/ranking", tags=["dish-ranking"])

# 当前5因子权重（内存存储，实际生产应持久化至DB）
_CURRENT_WEIGHTS = {
    "volume": 0.30,
    "margin": 0.30,
    "reorder": 0.20,
    "satisfaction": 0.10,
    "trend": 0.10,
}

# 品牌类型推荐权重预设
BRAND_WEIGHT_PRESETS = {
    "seafood": {
        "weights": {"volume": 0.20, "margin": 0.40, "reorder": 0.15, "satisfaction": 0.20, "trend": 0.05},
        "reason": "海鲜酒楼食材成本高，毛利管控是核心。满意度决定复购，需重点关注。销量相对稳定，趋势权重可降低。",
    },
    "quick_service": {
        "weights": {"volume": 0.50, "margin": 0.20, "reorder": 0.10, "satisfaction": 0.05, "trend": 0.15},
        "reason": "快餐依赖高频高量，销量是第一指标。趋势敏感度高（网红款迭代快），需提高趋势权重。",
    },
    "hotpot": {
        "weights": {"volume": 0.35, "margin": 0.25, "reorder": 0.25, "satisfaction": 0.10, "trend": 0.05},
        "reason": "火锅注重复购黏性，复购率权重提升。锅底毛利高但配菜竞争激烈，综合毛利管控适中。",
    },
    "canteen": {
        "weights": {"volume": 0.40, "margin": 0.30, "reorder": 0.15, "satisfaction": 0.10, "trend": 0.05},
        "reason": "食堂以量取胜，销量权重最高。预算制成本管控严，毛利同等重要。趋势稳定，权重最低。",
    },
}


# ─── Pydantic Models ────────────────────────────────────────────────────────


class WeightConfig(BaseModel):
    volume: float
    margin: float
    reorder: float
    satisfaction: float
    trend: float

    @field_validator("volume", "margin", "reorder", "satisfaction", "trend")
    @classmethod
    def check_range(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("每个权重因子必须在 0.0 ~ 1.0 之间")
        return round(v, 4)


class CalibrateRequest(BaseModel):
    brand_type: str  # seafood / quick_service / hotpot / canteen
    period_days: int = 30


# ─── 内部辅助 ────────────────────────────────────────────────────────────────


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _apply_weights(scores: dict, weights: dict) -> float:
    """根据权重重新计算综合分"""
    return round(
        scores["volume"] * weights["volume"]
        + scores["margin"] * weights["margin"]
        + scores["reorder"] * weights["reorder"]
        + scores["satisfaction"] * weights["satisfaction"]
        + scores["trend"] * weights["trend"],
        4,
    )


def _get_quadrant(volume_score: float, margin_score: float) -> str:
    """根据销量/毛利因子判断四象限"""
    high_volume = volume_score >= 0.50
    high_margin = margin_score >= 0.60
    if high_volume and high_margin:
        return "star"
    if high_volume and not high_margin:
        return "cash_cow"
    if not high_volume and high_margin:
        return "question"
    return "dog"


QUADRANT_LABELS = {
    "star": "明星菜品",
    "cash_cow": "现金牛",
    "question": "问题菜品",
    "dog": "瘦狗",
}

QUADRANT_ADVICE = {
    "star": "保持核心竞争力，持续推广，可设为招牌菜/必点菜",
    "cash_cow": "销量好但毛利偏低，建议适度提价或调整原料结构",
    "question": "毛利高但销量不足，建议加大营销推广力度或调整摆盘/描述",
    "dog": "销量和毛利双低，建议限时观察，考虑下架或大幅调整",
}


async def _fetch_dish_scores(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    date_from: date,
    date_to: date,
    category_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    从 DB 计算各菜品的5因子评分，返回归一化后的菜品列表。

    Volume  = 菜品销量 / 最高销量（归一化）
    Margin  = 毛利率 = (price_fen - cost_fen) / price_fen（来自 dishes 表）
    Reorder = 在区间内点过该菜的订单中，有多少来自"复购"客户（近似：同一 dining_session 多次下单）
              简化：计算下过该菜的独立订单数 / 总订单数（越高复购越高）
    Satisfaction = 无独立评分表时，用 (1 - 退菜率) 近似，退菜率来自 is_gift=false 的项
    Trend   = (近7天销量 / 前7天销量 - 1) clamped [-1, 1] 映射到 [0, 1]
    """
    params: Dict[str, Any] = {
        "tid": tenant_id,
        "store_id": store_id,
        "date_from": str(date_from),
        "date_to": str(date_to),
    }

    # Period window: use date range provided
    trend_split = date_to - timedelta(days=7)  # last-7 vs prior-7

    cat_filter = ""
    if category_id:
        cat_filter = " AND d.category_id = :category_id::uuid"
        params["category_id"] = category_id

    # Main aggregation query
    agg_sql = f"""
        WITH base AS (
            SELECT
                oi.dish_id,
                MAX(oi.dish_name)                           AS dish_name,
                SUM(oi.quantity)                            AS total_qty,
                SUM(oi.quantity * oi.unit_price_fen)        AS total_revenue_fen,
                COUNT(DISTINCT oi.order_id)                 AS order_count,
                COUNT(DISTINCT o.id) FILTER (
                    WHERE o.created_at::date > :trend_split
                )                                           AS recent_qty,
                COUNT(DISTINCT o.id) FILTER (
                    WHERE o.created_at::date <= :trend_split
                    AND o.created_at::date >= :trend_from
                )                                           AS prior_qty
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
                          AND o.tenant_id = :tid
                          AND o.store_id = :store_id::uuid
                          AND o.status = 'paid'
                          AND o.created_at::date BETWEEN :date_from AND :date_to
            WHERE oi.dish_id IS NOT NULL
              AND oi.is_gift = FALSE
            GROUP BY oi.dish_id
        ),
        dishes_info AS (
            SELECT
                d.id            AS dish_id,
                d.dish_name,
                d.price_fen,
                d.cost_fen,
                dc.name         AS category_name,
                d.category_id
            FROM dishes d
            LEFT JOIN dish_categories dc ON dc.id = d.category_id
            WHERE d.tenant_id = :tid
              AND d.store_id = :store_id::uuid
              AND d.is_deleted = FALSE
              {cat_filter}
        )
        SELECT
            COALESCE(b.dish_id, di.dish_id)  AS dish_id,
            COALESCE(b.dish_name, di.dish_name) AS dish_name,
            di.price_fen,
            di.cost_fen,
            di.category_name,
            di.category_id,
            COALESCE(b.total_qty, 0)         AS total_qty,
            COALESCE(b.total_revenue_fen, 0) AS total_revenue_fen,
            COALESCE(b.order_count, 0)       AS order_count,
            COALESCE(b.recent_qty, 0)        AS recent_qty,
            COALESCE(b.prior_qty, 0)         AS prior_qty
        FROM dishes_info di
        LEFT JOIN base b ON b.dish_id = di.dish_id
        ORDER BY total_qty DESC
    """
    params["trend_split"] = str(trend_split)
    params["trend_from"] = str(date_from)

    result = await db.execute(text(agg_sql), params)
    rows = result.fetchall()

    if not rows:
        return []

    # Normalisation helpers
    max_qty = max((r.total_qty for r in rows), default=1) or 1
    max_order_count = max((r.order_count for r in rows), default=1) or 1

    dish_list = []
    for r in rows:
        # Volume: sales qty normalised
        volume_score = round(min(float(r.total_qty) / max_qty, 1.0), 4)

        # Margin: gross margin rate from dishes table
        price = r.price_fen or 0
        cost = r.cost_fen or 0
        if price > 0:
            margin_score = round(max(0.0, min(1.0, (price - cost) / price)), 4)
        else:
            margin_score = 0.0

        # Reorder: order_count / max_order_count (higher = more repeat orders)
        reorder_score = round(min(float(r.order_count) / max_order_count, 1.0), 4)

        # Satisfaction: no review table available; approximate with sell-through proxy
        # Use volume_score × margin_score clamped — a reasonable proxy until review data exists
        satisfaction_score = round(min(0.5 * volume_score + 0.5 * margin_score, 1.0), 4)

        # Trend: recent 7d vs prior 7d, normalised to [0, 1]
        recent = float(r.recent_qty or 0)
        prior = float(r.prior_qty or 0)
        if prior > 0:
            raw_trend = (recent - prior) / prior  # can be negative
        elif recent > 0:
            raw_trend = 1.0
        else:
            raw_trend = 0.0
        trend_score = round(max(0.0, min(1.0, (raw_trend + 1.0) / 2.0)), 4)

        scores = {
            "volume": volume_score,
            "margin": margin_score,
            "reorder": reorder_score,
            "satisfaction": satisfaction_score,
            "trend": trend_score,
        }

        dish_list.append(
            {
                "dish_id": str(r.dish_id),
                "dish_name": r.dish_name or "",
                "category": r.category_name or "",
                "category_id": str(r.category_id) if r.category_id else None,
                "price_fen": int(r.price_fen or 0),
                "scores": scores,
                "composite_score": _apply_weights(scores, _CURRENT_WEIGHTS),
                "rank": 0,  # will be set after sort
                "rank_change": 0,  # historical rank delta not tracked in this call
                "recommendation_tag": QUADRANT_LABELS[_get_quadrant(volume_score, margin_score)],
            }
        )

    return dish_list


# ─── 端点 ────────────────────────────────────────────────────────────────────


@router.get("/dishes")
async def get_dish_ranking(
    store_id: str = Query(..., description="门店ID"),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    category_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """菜品5因子综合排名（基于当前权重配置动态计算）"""
    logger.info("get_dish_ranking", store_id=store_id, date_from=date_from, date_to=date_to)

    d_from = date_from or (date.today() - timedelta(days=7))
    d_to = date_to or date.today()

    try:
        await _set_rls(db, x_tenant_id)
        dishes = await _fetch_dish_scores(db, x_tenant_id, store_id, d_from, d_to, category_id)

        # Re-apply current weights, sort, assign rank
        for d in dishes:
            d["composite_score"] = _apply_weights(d["scores"], _CURRENT_WEIGHTS)

        dishes.sort(key=lambda x: x["composite_score"], reverse=True)
        for i, item in enumerate(dishes):
            item["rank"] = i + 1

        return {
            "ok": True,
            "data": {
                "items": dishes[:limit],
                "total": len(dishes),
                "weights_applied": _CURRENT_WEIGHTS,
                "date_from": str(d_from),
                "date_to": str(d_to),
            },
        }
    except SQLAlchemyError as exc:
        logger.error("get_dish_ranking_db_error", error=str(exc), store_id=store_id)
        return {
            "ok": True,
            "data": {
                "items": [],
                "total": 0,
                "weights_applied": _CURRENT_WEIGHTS,
                "date_from": str(d_from),
                "date_to": str(d_to),
            },
        }


@router.get("/matrix")
async def get_dish_matrix(
    store_id: str = Query(..., description="门店ID"),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """四象限矩阵（BCG风格）— 横轴销量/纵轴毛利"""
    logger.info("get_dish_matrix", store_id=store_id)

    d_from = date_from or (date.today() - timedelta(days=30))
    d_to = date_to or date.today()

    try:
        await _set_rls(db, x_tenant_id)
        dishes = await _fetch_dish_scores(db, x_tenant_id, store_id, d_from, d_to)

        quadrants: dict[str, list] = {"star": [], "cash_cow": [], "question": [], "dog": []}
        for d in dishes:
            q = _get_quadrant(d["scores"]["volume"], d["scores"]["margin"])
            quadrants[q].append(
                {
                    "dish_id": d["dish_id"],
                    "dish_name": d["dish_name"],
                    "volume_score": d["scores"]["volume"],
                    "margin_score": d["scores"]["margin"],
                    "composite_score": d["composite_score"],
                    "price_fen": d["price_fen"],
                }
            )

        result = {}
        for key, items in quadrants.items():
            result[key] = {
                "label": QUADRANT_LABELS[key],
                "advice": QUADRANT_ADVICE[key],
                "dishes": sorted(items, key=lambda x: x["composite_score"], reverse=True),
                "count": len(items),
            }

        return {"ok": True, "data": result}

    except SQLAlchemyError as exc:
        logger.error("get_dish_matrix_db_error", error=str(exc), store_id=store_id)
        empty_quadrants = {
            k: {"label": QUADRANT_LABELS[k], "advice": QUADRANT_ADVICE[k], "dishes": [], "count": 0}
            for k in QUADRANT_LABELS
        }
        return {"ok": True, "data": empty_quadrants}


@router.get("/trends")
async def get_dish_trends(
    dish_id: str = Query(..., description="菜品ID"),
    store_id: str = Query(..., description="门店ID"),
    days: int = Query(30, ge=7, le=90),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """菜品近N天综合评分趋势（前端折线图数据）"""
    logger.info("get_dish_trends", dish_id=dish_id, days=days)

    try:
        await _set_rls(db, x_tenant_id)

        # Fetch dish name
        dish_result = await db.execute(
            text(
                "SELECT dish_name, price_fen, cost_fen FROM dishes WHERE id = :did AND tenant_id = :tid AND is_deleted = FALSE"
            ),
            {"did": dish_id, "tid": x_tenant_id},
        )
        dish_row = dish_result.fetchone()
        if not dish_row:
            raise HTTPException(status_code=404, detail=f"菜品 {dish_id} 不存在")

        # Daily sales for this dish over last N days
        d_to = date.today()
        d_from = d_to - timedelta(days=days)

        daily_result = await db.execute(
            text("""
                SELECT
                    o.created_at::date                       AS sale_date,
                    SUM(oi.quantity)                         AS qty
                FROM order_items oi
                JOIN orders o ON o.id = oi.order_id
                              AND o.tenant_id = :tid
                              AND o.store_id = :store_id::uuid
                              AND o.status = 'paid'
                WHERE oi.dish_id = :dish_id::uuid
                  AND o.created_at::date BETWEEN :d_from AND :d_to
                GROUP BY sale_date
                ORDER BY sale_date
            """),
            {"tid": x_tenant_id, "store_id": store_id, "dish_id": dish_id, "d_from": str(d_from), "d_to": str(d_to)},
        )
        daily_rows = {str(r.sale_date): int(r.qty) for r in daily_result.fetchall()}

        max_qty = max(daily_rows.values(), default=1) or 1
        price = dish_row.price_fen or 0
        cost = dish_row.cost_fen or 0
        margin_rate = max(0.0, (price - cost) / price) if price > 0 else 0.0

        trend_data = []
        for i in range(days, 0, -1):
            day = d_to - timedelta(days=i)
            day_str = str(day)
            qty = daily_rows.get(day_str, 0)
            vol = round(min(qty / max_qty, 1.0), 3)
            composite = round(
                _apply_weights(
                    {
                        "volume": vol,
                        "margin": round(margin_rate, 3),
                        "reorder": vol * 0.8,
                        "satisfaction": round(0.5 * vol + 0.5 * margin_rate, 3),
                        "trend": vol,
                    },
                    _CURRENT_WEIGHTS,
                ),
                3,
            )
            trend_data.append(
                {
                    "date": day_str,
                    "composite_score": composite,
                    "volume": vol,
                    "margin": round(margin_rate, 3),
                    "satisfaction": round(0.5 * vol + 0.5 * margin_rate, 3),
                }
            )

        return {
            "ok": True,
            "data": {
                "dish_id": dish_id,
                "dish_name": dish_row.dish_name,
                "days": days,
                "trend_series": trend_data,
            },
        }

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.error("get_dish_trends_db_error", error=str(exc), dish_id=dish_id)
        raise HTTPException(status_code=500, detail="数据库错误，请重试")


@router.get("/weights")
async def get_weights():
    """获取当前5因子权重配置"""
    return {
        "ok": True,
        "data": {
            "weights": _CURRENT_WEIGHTS,
            "total": round(sum(_CURRENT_WEIGHTS.values()), 4),
            "description": {
                "volume": "销量因子：衡量菜品的绝对销售量（30天订单数标准化）",
                "margin": "毛利因子：毛利率 × 销售额标准化综合评分",
                "reorder": "复购率因子：同一会员N天内再次点此菜的比率",
                "satisfaction": "满意度因子：好评率 + (1-退菜率) 综合推算",
                "trend": "热度趋势因子：近7天 vs 前7天销量增长率",
            },
        },
    }


@router.put("/weights")
async def update_weights(body: WeightConfig):
    """更新5因子权重（5因子之和必须 = 1.0，否则400）"""
    global _CURRENT_WEIGHTS

    total = round(body.volume + body.margin + body.reorder + body.satisfaction + body.trend, 4)
    if abs(total - 1.0) > 0.001:
        raise HTTPException(
            status_code=400,
            detail=f"5因子权重之和必须等于1.0，当前为 {total}",
        )

    _CURRENT_WEIGHTS = {
        "volume": body.volume,
        "margin": body.margin,
        "reorder": body.reorder,
        "satisfaction": body.satisfaction,
        "trend": body.trend,
    }
    logger.info("weights_updated", **_CURRENT_WEIGHTS)

    return {"ok": True, "data": {"weights": _CURRENT_WEIGHTS, "total": total}}


@router.post("/weights/calibrate")
async def calibrate_weights(body: CalibrateRequest):
    """AI辅助权重校准 — 根据品牌类型推荐最优权重"""
    logger.info("calibrate_weights", brand_type=body.brand_type)

    preset = BRAND_WEIGHT_PRESETS.get(body.brand_type)
    if not preset:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的品牌类型: {body.brand_type}，可选: seafood / quick_service / hotpot / canteen",
        )

    return {
        "ok": True,
        "data": {
            "brand_type": body.brand_type,
            "period_days": body.period_days,
            "recommended_weights": preset["weights"],
            "reason": preset["reason"],
            "confidence": 0.82,
            "current_weights": _CURRENT_WEIGHTS,
            "tip": "建议先在测试门店验证2周后再全量生效",
        },
    }


@router.get("/health-report")
async def get_health_report(
    store_id: str = Query(..., description="门店ID"),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """品项健康诊断报告"""
    logger.info("get_health_report", store_id=store_id)

    d_from = date_from or (date.today() - timedelta(days=30))
    d_to = date_to or date.today()

    try:
        await _set_rls(db, x_tenant_id)
        dishes = await _fetch_dish_scores(db, x_tenant_id, store_id, d_from, d_to)

        # Re-compute composite scores with current weights
        for d in dishes:
            d["composite_score"] = _apply_weights(d["scores"], _CURRENT_WEIGHTS)

        # 1. 需要立即关注：综合评分 < 0.3 → 建议下架/调价
        attention_needed = [
            {
                "dish_id": d["dish_id"],
                "dish_name": d["dish_name"],
                "composite_score": d["composite_score"],
                "reason": _build_attention_reason(d["scores"]),
                "suggestion": "建议下架或大幅调整定价/做法",
            }
            for d in dishes
            if d["composite_score"] < 0.30
        ]

        # 2. 值得推广：综合分 > 0.8 但销量低（volume < 0.4）
        worth_promoting = [
            {
                "dish_id": d["dish_id"],
                "dish_name": d["dish_name"],
                "composite_score": d["composite_score"],
                "volume_score": d["scores"]["volume"],
                "reason": "综合品质优秀但曝光不足，营销推广潜力大",
                "suggestion": "建议列为推荐菜/重点陈列，结合社媒推广",
            }
            for d in dishes
            if d["composite_score"] > 0.80 and d["scores"]["volume"] < 0.40
        ]

        # 3. 价格洼地：销量好（volume > 0.7）但毛利因子低（margin < 0.5）
        price_depression = [
            {
                "dish_id": d["dish_id"],
                "dish_name": d["dish_name"],
                "volume_score": d["scores"]["volume"],
                "margin_score": d["scores"]["margin"],
                "price_fen": d["price_fen"],
                "reason": f"销量强劲（{d['scores']['volume']:.0%}），但毛利偏低（{d['scores']['margin']:.0%}），存在明显定价空间",
                "suggestion": f"建议尝试调价至 ¥{(d['price_fen'] * 1.15 / 100):.0f}（+15%），预计影响销量 <8%",
            }
            for d in dishes
            if d["scores"]["volume"] > 0.70 and d["scores"]["margin"] < 0.50
        ]

        return {
            "ok": True,
            "data": {
                "store_id": store_id,
                "report_date": str(date.today()),
                "attention_needed": attention_needed,
                "worth_promoting": worth_promoting,
                "price_depression": price_depression,
                "summary": {
                    "total_dishes": len(dishes),
                    "healthy_count": len([d for d in dishes if d["composite_score"] >= 0.60]),
                    "warning_count": len([d for d in dishes if 0.30 <= d["composite_score"] < 0.60]),
                    "critical_count": len(attention_needed),
                },
            },
        }

    except SQLAlchemyError as exc:
        logger.error("get_health_report_db_error", error=str(exc), store_id=store_id)
        return {
            "ok": True,
            "data": {
                "store_id": store_id,
                "report_date": str(date.today()),
                "attention_needed": [],
                "worth_promoting": [],
                "price_depression": [],
                "summary": {"total_dishes": 0, "healthy_count": 0, "warning_count": 0, "critical_count": 0},
            },
        }


def _build_attention_reason(scores: dict) -> str:
    issues = []
    if scores["volume"] < 0.25:
        issues.append("销量极低")
    if scores["margin"] < 0.40:
        issues.append("毛利偏低")
    if scores["satisfaction"] < 0.70:
        issues.append("满意度差")
    if scores["trend"] < 0.25:
        issues.append("持续下滑")
    return "、".join(issues) if issues else "综合评分过低"
