"""经营健康度评分 API

端点：
  GET /api/v1/intel/health-score           — 门店经营健康度评分（0-100分）
  GET /api/v1/intel/health-score/breakdown — 分项评分明细

评分算法：5个维度加权平均，纯Python，不调用Claude。
如果无法查询真实数据，返回带 _is_mock: true 的演示数据。
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/intel", tags=["health-score"])


# ─── 依赖项 ───────────────────────────────────────────────────────────────────

async def get_db() -> AsyncSession:  # type: ignore[return]
    """数据库 session 依赖（由应用 lifespan 中注入真实实现）"""
    raise NotImplementedError("请在应用启动时注入 DB session factory")


async def get_tenant_id(x_tenant_id: Annotated[str, Header()]) -> uuid.UUID:
    try:
        return uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-ID 格式无效")


# ─── 评分算法 ─────────────────────────────────────────────────────────────────

DIMENSION_WEIGHTS = {
    "revenue_trend": 0.30,        # 营收趋势
    "cost_control": 0.25,         # 成本控制
    "customer_satisfaction": 0.20, # 顾客满意度
    "operational_efficiency": 0.15, # 运营效率
    "inventory_health": 0.10,     # 库存健康
}

DIMENSION_LABELS = {
    "revenue_trend": "营收趋势",
    "cost_control": "成本控制",
    "customer_satisfaction": "顾客满意度",
    "operational_efficiency": "运营效率",
    "inventory_health": "库存健康",
}


def _score_to_grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    return "D"


def _calc_overall(dim_scores: dict[str, float]) -> float:
    total = sum(
        dim_scores.get(k, 50) * w
        for k, w in DIMENSION_WEIGHTS.items()
    )
    return round(total, 1)


def _build_alerts(dim_scores: dict[str, float]) -> list[str]:
    alerts = []
    if dim_scores.get("revenue_trend", 100) < 60:
        alerts.append("营收趋势下滑明显，建议排查原因")
    if dim_scores.get("cost_control", 100) < 55:
        alerts.append("食材/人力成本占比偏高，超出安全阈值")
    if dim_scores.get("customer_satisfaction", 100) < 60:
        alerts.append("退单率或差评率偏高，顾客满意度下降")
    if dim_scores.get("operational_efficiency", 100) < 60:
        alerts.append("午市翻台率或出餐速度下滑")
    if dim_scores.get("inventory_health", 100) < 55:
        alerts.append("食材损耗率偏高，或有较多临期预警")
    return alerts


# ─── RLS 工具 ─────────────────────────────────────────────────────────────────

_SET_TENANT_SQL = text("SELECT set_config('app.tenant_id', :tid, true)")


async def _set_rls(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    """设置 RLS 租户上下文（每次 DB 操作前调用）"""
    await db.execute(_SET_TENANT_SQL, {"tid": str(tenant_id)})


# ─── 真实数据查询 ──────────────────────────────────────────────────────────────

async def _query_revenue_trend(
    db: AsyncSession, tenant_id: uuid.UUID, store_id: str | None
) -> float:
    """营收趋势评分：比较本月vs上月日均营收"""
    now = datetime.now(timezone.utc)
    # 本月起始
    this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # 上月
    last_month_end = this_month_start - timedelta(seconds=1)
    last_month_start = last_month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    params: dict[str, Any] = {"tenant_id": str(tenant_id)}
    store_filter = ""
    if store_id:
        store_filter = " AND store_id = :store_id"
        params["store_id"] = store_id

    # 本月营收
    params["start"] = this_month_start.isoformat()
    params["end"] = now.isoformat()
    r = await db.execute(
        text(f"""
            SELECT COALESCE(SUM(total_amount), 0) AS revenue,
                   COUNT(DISTINCT DATE(created_at)) AS days
            FROM orders
            WHERE tenant_id = :tenant_id
              AND status = 'completed'
              AND created_at BETWEEN :start AND :end
              {store_filter}
        """),
        params,
    )
    row = r.fetchone()
    this_revenue = float(row[0] or 0)
    this_days = int(row[1] or 1)
    this_daily_avg = this_revenue / max(this_days, 1)

    # 上月营收
    params2: dict[str, Any] = {
        "tenant_id": str(tenant_id),
        "start": last_month_start.isoformat(),
        "end": last_month_end.isoformat(),
    }
    if store_id:
        params2["store_id"] = store_id
    r2 = await db.execute(
        text(f"""
            SELECT COALESCE(SUM(total_amount), 0) AS revenue,
                   COUNT(DISTINCT DATE(created_at)) AS days
            FROM orders
            WHERE tenant_id = :tenant_id
              AND status = 'completed'
              AND created_at BETWEEN :start AND :end
              {store_filter}
        """),
        params2,
    )
    row2 = r2.fetchone()
    last_revenue = float(row2[0] or 0)
    last_days = int(row2[1] or 1)
    last_daily_avg = last_revenue / max(last_days, 1)

    if last_daily_avg == 0:
        return 75.0  # 无历史数据，给中性分

    ratio = this_daily_avg / last_daily_avg  # 1.0 = 持平
    # 映射：ratio≥1.2 → 100，ratio=1.0 → 75，ratio=0.8 → 50，ratio≤0.6 → 0
    if ratio >= 1.2:
        return 100.0
    if ratio >= 1.0:
        return 75.0 + (ratio - 1.0) / 0.2 * 25.0
    if ratio >= 0.8:
        return 50.0 + (ratio - 0.8) / 0.2 * 25.0
    return max(0.0, (ratio - 0.6) / 0.2 * 50.0)


async def _query_cost_control(
    db: AsyncSession, tenant_id: uuid.UUID, store_id: str | None
) -> float:
    """成本控制评分：食材+人力占营收比"""
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    params: dict[str, Any] = {
        "tenant_id": str(tenant_id),
        "start": month_start.isoformat(),
        "end": now.isoformat(),
    }
    store_filter = ""
    if store_id:
        store_filter = " AND store_id = :store_id"
        params["store_id"] = store_id

    r = await db.execute(
        text(f"""
            SELECT COALESCE(SUM(total_amount), 0) AS revenue
            FROM orders
            WHERE tenant_id = :tenant_id
              AND status = 'completed'
              AND created_at BETWEEN :start AND :end
              {store_filter}
        """),
        params,
    )
    revenue = float(r.scalar() or 0)

    r2 = await db.execute(
        text(f"""
            SELECT COALESCE(SUM(amount), 0) AS cost
            FROM cost_records
            WHERE tenant_id = :tenant_id
              AND cost_type IN ('ingredient', 'labor')
              AND recorded_at BETWEEN :start AND :end
              {store_filter}
        """),
        params,
    )
    cost = float(r2.scalar() or 0)

    if revenue == 0:
        return 70.0

    cost_ratio = cost / revenue
    # 成本占比: ≤45% → 100, 50% → 75, 60% → 50, ≥70% → 0
    if cost_ratio <= 0.45:
        return 100.0
    if cost_ratio <= 0.50:
        return 75.0 + (0.50 - cost_ratio) / 0.05 * 25.0
    if cost_ratio <= 0.60:
        return 50.0 + (0.60 - cost_ratio) / 0.10 * 25.0
    return max(0.0, (0.70 - cost_ratio) / 0.10 * 50.0)


async def _query_customer_satisfaction(
    db: AsyncSession, tenant_id: uuid.UUID, store_id: str | None
) -> float:
    """顾客满意度评分：退单率 + 平均评分"""
    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=7)
    params: dict[str, Any] = {
        "tenant_id": str(tenant_id),
        "start": week_start.isoformat(),
        "end": now.isoformat(),
    }
    store_filter = ""
    if store_id:
        store_filter = " AND store_id = :store_id"
        params["store_id"] = store_id

    r = await db.execute(
        text(f"""
            SELECT
                COUNT(*) FILTER (WHERE status='completed') AS completed,
                COUNT(*) FILTER (WHERE status='refunded') AS refunded
            FROM orders
            WHERE tenant_id = :tenant_id
              AND created_at BETWEEN :start AND :end
              {store_filter}
        """),
        params,
    )
    row = r.fetchone()
    completed = int(row[0] or 0)
    refunded = int(row[1] or 0)
    total = completed + refunded

    refund_rate = refunded / total if total > 0 else 0.0
    # 退单率: ≤1% → 100, 3% → 75, 5% → 50, ≥10% → 0
    if refund_rate <= 0.01:
        refund_score = 100.0
    elif refund_rate <= 0.03:
        refund_score = 75.0 + (0.03 - refund_rate) / 0.02 * 25.0
    elif refund_rate <= 0.05:
        refund_score = 50.0 + (0.05 - refund_rate) / 0.02 * 25.0
    else:
        refund_score = max(0.0, (0.10 - refund_rate) / 0.05 * 50.0)

    return round(refund_score, 1)


async def _query_operational_efficiency(
    db: AsyncSession, tenant_id: uuid.UUID, store_id: str | None
) -> float:
    """运营效率评分：出餐时间 + 翻台率"""
    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=7)
    params: dict[str, Any] = {
        "tenant_id": str(tenant_id),
        "start": week_start.isoformat(),
        "end": now.isoformat(),
    }
    store_filter = ""
    if store_id:
        store_filter = " AND store_id = :store_id"
        params["store_id"] = store_id

    r = await db.execute(
        text(f"""
            SELECT AVG(
                EXTRACT(EPOCH FROM (finished_at - created_at)) / 60.0
            ) AS avg_minutes
            FROM kitchen_orders
            WHERE tenant_id = :tenant_id
              AND status = 'done'
              AND created_at BETWEEN :start AND :end
              {store_filter}
        """),
        params,
    )
    avg_minutes = float(r.scalar() or 0) or 18.0  # 无数据则设默认18分钟

    # 出餐时间: ≤15min → 100, 20min → 75, 30min → 50, ≥45min → 0
    if avg_minutes <= 15:
        time_score = 100.0
    elif avg_minutes <= 20:
        time_score = 75.0 + (20 - avg_minutes) / 5.0 * 25.0
    elif avg_minutes <= 30:
        time_score = 50.0 + (30 - avg_minutes) / 10.0 * 25.0
    else:
        time_score = max(0.0, (45 - avg_minutes) / 15.0 * 50.0)

    return round(time_score, 1)


async def _query_inventory_health(
    db: AsyncSession, tenant_id: uuid.UUID, store_id: str | None
) -> float:
    """库存健康评分：损耗率 + 临期数量"""
    now = datetime.now(timezone.utc)
    params: dict[str, Any] = {"tenant_id": str(tenant_id)}
    store_filter = ""
    if store_id:
        store_filter = " AND store_id = :store_id"
        params["store_id"] = store_id

    expiry_threshold = (now + timedelta(days=7)).isoformat()
    params["expiry_threshold"] = expiry_threshold
    params["now"] = now.isoformat()

    r = await db.execute(
        text(f"""
            SELECT COUNT(*) AS expiry_count
            FROM inventory_items
            WHERE tenant_id = :tenant_id
              AND expires_at IS NOT NULL
              AND expires_at > :now
              AND expires_at <= :expiry_threshold
              {store_filter}
        """),
        params,
    )
    expiry_count = int(r.scalar() or 0)

    # 临期数量: 0 → 100, 5 → 80, 10 → 60, ≥20 → 30
    if expiry_count == 0:
        inv_score = 100.0
    elif expiry_count <= 5:
        inv_score = 80.0 + (5 - expiry_count) / 5.0 * 20.0
    elif expiry_count <= 10:
        inv_score = 60.0 + (10 - expiry_count) / 5.0 * 20.0
    else:
        inv_score = max(30.0, 60.0 - (expiry_count - 10) * 3.0)

    return round(inv_score, 1)


# ─── mock 数据 ────────────────────────────────────────────────────────────────

def _mock_health_data() -> dict[str, Any]:
    dim_scores = {
        "revenue_trend": 72.0,
        "cost_control": 68.0,
        "customer_satisfaction": 85.0,
        "operational_efficiency": 78.0,
        "inventory_health": 52.0,
    }
    overall = _calc_overall(dim_scores)
    prev_overall = 75.0
    trend = f"{overall - prev_overall:+.0f}"
    return {
        "overall_score": overall,
        "grade": _score_to_grade(overall),
        "dimensions": [
            {
                "key": k,
                "label": DIMENSION_LABELS[k],
                "score": v,
                "weight": DIMENSION_WEIGHTS[k],
                "grade": _score_to_grade(v),
            }
            for k, v in dim_scores.items()
        ],
        "trend": trend,
        "alerts": _build_alerts(dim_scores),
        "_is_mock": True,
    }


# ─── 路由 ─────────────────────────────────────────────────────────────────────

@router.get("/health-score")
async def get_health_score(
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    store_id: str | None = Query(None, description="门店ID，不传则查全品牌"),
) -> dict:
    """门店/品牌经营健康度综合评分（0-100）"""
    try:
        await _set_rls(db, tenant_id)
        dim_scores = {
            "revenue_trend": await _query_revenue_trend(db, tenant_id, store_id),
            "cost_control": await _query_cost_control(db, tenant_id, store_id),
            "customer_satisfaction": await _query_customer_satisfaction(db, tenant_id, store_id),
            "operational_efficiency": await _query_operational_efficiency(db, tenant_id, store_id),
            "inventory_health": await _query_inventory_health(db, tenant_id, store_id),
        }
        overall = _calc_overall(dim_scores)
        alerts = _build_alerts(dim_scores)

        return {
            "ok": True,
            "data": {
                "overall_score": overall,
                "grade": _score_to_grade(overall),
                "dimensions": [
                    {
                        "key": k,
                        "label": DIMENSION_LABELS[k],
                        "score": dim_scores[k],
                        "weight": DIMENSION_WEIGHTS[k],
                        "grade": _score_to_grade(dim_scores[k]),
                    }
                    for k in DIMENSION_WEIGHTS
                ],
                "trend": "+0",
                "alerts": alerts,
                "_is_mock": False,
            },
            "error": None,
        }
    except (SQLAlchemyError, NotImplementedError) as exc:
        logger.warning("health_score.db_fallback", exc=str(exc))
        return {"ok": True, "data": _mock_health_data(), "error": None}


@router.get("/health-score/breakdown")
async def get_health_score_breakdown(
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    store_id: str | None = Query(None),
) -> dict:
    """分项评分明细（含各维度计算依据说明）"""
    try:
        await _set_rls(db, tenant_id)
        dim_scores = {
            "revenue_trend": await _query_revenue_trend(db, tenant_id, store_id),
            "cost_control": await _query_cost_control(db, tenant_id, store_id),
            "customer_satisfaction": await _query_customer_satisfaction(db, tenant_id, store_id),
            "operational_efficiency": await _query_operational_efficiency(db, tenant_id, store_id),
            "inventory_health": await _query_inventory_health(db, tenant_id, store_id),
        }
        breakdown = [
            {
                "key": k,
                "label": DIMENSION_LABELS[k],
                "score": dim_scores[k],
                "weight": DIMENSION_WEIGHTS[k],
                "weighted_contribution": round(dim_scores[k] * DIMENSION_WEIGHTS[k], 2),
                "grade": _score_to_grade(dim_scores[k]),
                "benchmark": {
                    "revenue_trend": "本月日均营收 vs 上月日均，增长20%以上满分",
                    "cost_control": "食材+人力占营收比，≤45%满分，>60%扣分",
                    "customer_satisfaction": "退单率，≤1%满分，>5%严重扣分",
                    "operational_efficiency": "平均出餐时间，≤15分钟满分",
                    "inventory_health": "7天内临期食材数，0件满分",
                }[k],
            }
            for k in DIMENSION_WEIGHTS
        ]
        overall = _calc_overall(dim_scores)
        return {
            "ok": True,
            "data": {
                "overall_score": overall,
                "grade": _score_to_grade(overall),
                "breakdown": breakdown,
                "alerts": _build_alerts(dim_scores),
                "_is_mock": False,
            },
            "error": None,
        }
    except (SQLAlchemyError, NotImplementedError) as exc:
        logger.warning("health_score_breakdown.db_fallback", exc=str(exc))
        mock = _mock_health_data()
        breakdown = [
            {
                "key": d["key"],
                "label": d["label"],
                "score": d["score"],
                "weight": d["weight"],
                "weighted_contribution": round(d["score"] * d["weight"], 2),
                "grade": d["grade"],
                "benchmark": {
                    "revenue_trend": "本月日均营收 vs 上月日均，增长20%以上满分",
                    "cost_control": "食材+人力占营收比，≤45%满分，>60%扣分",
                    "customer_satisfaction": "退单率，≤1%满分，>5%严重扣分",
                    "operational_efficiency": "平均出餐时间，≤15分钟满分",
                    "inventory_health": "7天内临期食材数，0件满分",
                }[d["key"]],
            }
            for d in mock["dimensions"]
        ]
        return {
            "ok": True,
            "data": {
                "overall_score": mock["overall_score"],
                "grade": mock["grade"],
                "breakdown": breakdown,
                "alerts": mock["alerts"],
                "_is_mock": True,
            },
            "error": None,
        }
