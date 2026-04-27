"""菜品四象限分析 API（BCG矩阵变体）

端点：
  GET /api/v1/intel/dish-matrix               — 菜品四象限分类
  GET /api/v1/intel/dish-matrix/recommendations — 基于四象限的菜品运营建议

四象限定义：
  明星菜（Star）     ：高销量 + 高毛利 → 重点推广
  现金牛（Cash Cow） ：高销量 + 低毛利 → 保持，优化成本
  问题菜（Question） ：低销量 + 高毛利 → 加强推广/优化定价
  瘦狗菜（Dog）      ：低销量 + 低毛利 → 考虑下架

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

router = APIRouter(prefix="/api/v1/intel", tags=["dish-matrix"])


# ─── 依赖项 ───────────────────────────────────────────────────────────────────


async def get_db() -> AsyncSession:  # type: ignore[return]
    raise NotImplementedError("请在应用启动时注入 DB session factory")


async def get_tenant_id(x_tenant_id: Annotated[str, Header()]) -> uuid.UUID:
    try:
        return uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-ID 格式无效")


# ─── RLS 工具 ─────────────────────────────────────────────────────────────────

_SET_TENANT_SQL = text("SELECT set_config('app.tenant_id', :tid, true)")


async def _set_rls(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    """设置 RLS 租户上下文（每次 DB 操作前调用）"""
    await db.execute(_SET_TENANT_SQL, {"tid": str(tenant_id)})


# ─── 四象限分类逻辑 ───────────────────────────────────────────────────────────


def _classify_quadrant(
    sales_count: int,
    gross_margin_pct: float,
    sales_median: float,
    margin_median: float,
) -> str:
    """根据中位数阈值分四象限"""
    high_sales = sales_count >= sales_median
    high_margin = gross_margin_pct >= margin_median
    if high_sales and high_margin:
        return "star"
    if high_sales and not high_margin:
        return "cash_cow"
    if not high_sales and high_margin:
        return "question_mark"
    return "dog"


def _quadrant_label(quadrant: str) -> str:
    return {
        "star": "明星菜",
        "cash_cow": "现金牛",
        "question_mark": "问题菜",
        "dog": "瘦狗菜",
    }.get(quadrant, quadrant)


def _build_recommendations(dishes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    recs = []
    for d in dishes:
        q = d["quadrant"]
        if q == "dog":
            recs.append(
                {
                    "dish_name": d["dish_name"],
                    "current_quadrant": q,
                    "quadrant_label": _quadrant_label(q),
                    "action": "考虑下架或重新定价，销量和毛利均不理想",
                    "priority": "high",
                }
            )
        elif q == "question_mark":
            recs.append(
                {
                    "dish_name": d["dish_name"],
                    "current_quadrant": q,
                    "quadrant_label": _quadrant_label(q),
                    "action": "加强堂食推荐和套餐捆绑，提升曝光度，毛利空间充足",
                    "priority": "medium",
                }
            )
        elif q == "cash_cow":
            recs.append(
                {
                    "dish_name": d["dish_name"],
                    "current_quadrant": q,
                    "quadrant_label": _quadrant_label(q),
                    "action": "持续保量，优化食材采购成本，维持稳定出品",
                    "priority": "low",
                }
            )
    return recs


# ─── mock 数据 ────────────────────────────────────────────────────────────────


def _mock_matrix_data() -> dict[str, Any]:
    dishes = [
        {"dish_name": "招牌红烧肉", "sales_count": 320, "gross_margin_pct": 0.68, "quadrant": "star"},
        {"dish_name": "辣椒炒肉", "sales_count": 280, "gross_margin_pct": 0.72, "quadrant": "star"},
        {"dish_name": "白米饭", "sales_count": 450, "gross_margin_pct": 0.35, "quadrant": "cash_cow"},
        {"dish_name": "老坛酸菜鱼", "sales_count": 380, "gross_margin_pct": 0.42, "quadrant": "cash_cow"},
        {"dish_name": "松茸炖土鸡", "sales_count": 45, "gross_margin_pct": 0.71, "quadrant": "question_mark"},
        {"dish_name": "和牛刺身拼盘", "sales_count": 28, "gross_margin_pct": 0.65, "quadrant": "question_mark"},
        {"dish_name": "茄子炒肉", "sales_count": 62, "gross_margin_pct": 0.28, "quadrant": "dog"},
        {"dish_name": "素炒时蔬", "sales_count": 55, "gross_margin_pct": 0.22, "quadrant": "dog"},
    ]
    quadrants: dict[str, list] = {"star": [], "cash_cow": [], "question_mark": [], "dog": []}
    for d in dishes:
        quadrants[d["quadrant"]].append(
            {
                "dish_name": d["dish_name"],
                "sales_count": d["sales_count"],
                "gross_margin_pct": d["gross_margin_pct"],
            }
        )
    recs = _build_recommendations(dishes)
    return {
        "quadrants": quadrants,
        "recommendations": recs,
        "metadata": {
            "period_days": 30,
            "total_dishes": len(dishes),
            "sales_median": 171.0,
            "margin_median": 0.535,
        },
        "_is_mock": True,
    }


# ─── 真实数据查询 ──────────────────────────────────────────────────────────────


async def _query_dish_matrix(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    store_id: str | None,
    period_days: int,
) -> dict[str, Any]:
    await _set_rls(db, tenant_id)
    now = datetime.now(timezone.utc)
    period_start = (now - timedelta(days=period_days)).isoformat()
    params: dict[str, Any] = {
        "tenant_id": str(tenant_id),
        "start": period_start,
        "end": now.isoformat(),
    }
    store_filter = ""
    if store_id:
        store_filter = " AND o.store_id = :store_id"
        params["store_id"] = store_id

    rows = await db.execute(
        text(f"""
            SELECT
                d.name                                      AS dish_name,
                d.id                                        AS dish_id,
                COUNT(oi.id)                                AS sales_count,
                COALESCE(d.gross_margin_pct, 0.5)          AS gross_margin_pct
            FROM order_items oi
            JOIN orders o ON oi.order_id = o.id
            JOIN dishes d ON oi.dish_id = d.id
            WHERE oi.tenant_id = :tenant_id
              AND o.status = 'completed'
              AND o.created_at BETWEEN :start AND :end
              {store_filter}
            GROUP BY d.id, d.name, d.gross_margin_pct
            ORDER BY COUNT(oi.id) DESC
            LIMIT 100
        """),
        params,
    )
    all_dishes = [
        {
            "dish_name": row[0],
            "dish_id": str(row[1]),
            "sales_count": int(row[2]),
            "gross_margin_pct": float(row[3]),
        }
        for row in rows.fetchall()
    ]

    if not all_dishes:
        return _mock_matrix_data()

    sales_values = sorted(d["sales_count"] for d in all_dishes)
    margin_values = sorted(d["gross_margin_pct"] for d in all_dishes)
    n = len(sales_values)
    sales_median = sales_values[n // 2]
    margin_median = margin_values[n // 2]

    classified = []
    quadrants: dict[str, list] = {"star": [], "cash_cow": [], "question_mark": [], "dog": []}
    for d in all_dishes:
        q = _classify_quadrant(d["sales_count"], d["gross_margin_pct"], sales_median, margin_median)
        d["quadrant"] = q
        classified.append(d)
        quadrants[q].append(
            {
                "dish_name": d["dish_name"],
                "sales_count": d["sales_count"],
                "gross_margin_pct": round(d["gross_margin_pct"], 4),
            }
        )

    return {
        "quadrants": quadrants,
        "recommendations": _build_recommendations(classified),
        "metadata": {
            "period_days": period_days,
            "total_dishes": len(all_dishes),
            "sales_median": float(sales_median),
            "margin_median": round(float(margin_median), 4),
        },
        "_is_mock": False,
    }


# ─── 路由 ─────────────────────────────────────────────────────────────────────


@router.get("/dish-matrix")
async def get_dish_matrix(
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    store_id: str | None = Query(None, description="门店ID，不传则查全品牌"),
    period_days: int = Query(30, ge=7, le=90, description="统计周期（天）"),
) -> dict:
    """菜品四象限（BCG矩阵变体）：高销量/低销量 × 高毛利/低毛利"""
    try:
        data = await _query_dish_matrix(db, tenant_id, store_id, period_days)
        return {"ok": True, "data": data, "error": None}
    except (SQLAlchemyError, NotImplementedError) as exc:
        logger.warning("dish_matrix.db_fallback", exc=str(exc))
        return {"ok": True, "data": _mock_matrix_data(), "error": None}


@router.get("/dish-matrix/recommendations")
async def get_dish_recommendations(
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    store_id: str | None = Query(None),
    period_days: int = Query(30, ge=7, le=90),
    priority: str | None = Query(None, description="过滤优先级: high/medium/low"),
) -> dict:
    """基于四象限的菜品运营建议列表"""
    try:
        data = await _query_dish_matrix(db, tenant_id, store_id, period_days)
        recs = data.get("recommendations", [])
        if priority:
            recs = [r for r in recs if r.get("priority") == priority]
        return {
            "ok": True,
            "data": {
                "recommendations": recs,
                "total": len(recs),
                "_is_mock": data.get("_is_mock", False),
            },
            "error": None,
        }
    except (SQLAlchemyError, NotImplementedError) as exc:
        logger.warning("dish_recommendations.db_fallback", exc=str(exc))
        mock = _mock_matrix_data()
        recs = mock["recommendations"]
        if priority:
            recs = [r for r in recs if r.get("priority") == priority]
        return {
            "ok": True,
            "data": {
                "recommendations": recs,
                "total": len(recs),
                "_is_mock": True,
            },
            "error": None,
        }
