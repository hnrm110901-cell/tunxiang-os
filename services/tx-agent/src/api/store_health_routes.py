"""
门店健康 BFF 接口

GET /api/v1/store-health/overview   — 所有门店健康汇总（用于列表页）
GET /api/v1/store-health/{store_id} — 单门店详细健康报告
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.daily_review_service import DailyReviewService

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/store-health", tags=["store-health"])


async def _get_db_with_tenant(
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
) -> AsyncSession:
    """依赖：从 X-Tenant-ID header 提取租户 ID，返回带 RLS 隔离的 DB session。"""
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _calc_health_score(
    revenue_rate: float,
    cost_rate: float,
    daily_review_rate: float,
) -> int:
    """
    综合健康分 0-100。

    权重：营收达成率 40% + 成本率 30% + 日清完成率 30%
    成本率基准 30%，超出 20ppt 全扣。
    """
    revenue_score = min(100.0, revenue_rate * 100)
    cost_score = max(0.0, 100.0 - max(0.0, (cost_rate - 0.30) / 0.20 * 100))
    review_score = daily_review_rate * 100
    return int(revenue_score * 0.4 + cost_score * 0.3 + review_score * 0.3)


def _health_grade(score: int) -> str:
    if score >= 80:
        return "A"
    if score >= 60:
        return "B"
    if score >= 40:
        return "C"
    return "D"


async def _fetch_all_stores(db: AsyncSession, tenant_id: str) -> list[dict]:
    """返回租户下所有在营门店基础信息。"""
    result = await db.execute(
        text("""
            SELECT
                s.id::text          AS store_id,
                s.name              AS store_name,
                s.status,
                s.daily_target_fen
            FROM stores s
            WHERE s.tenant_id = :tenant_id
              AND s.is_deleted = FALSE
            ORDER BY s.name
        """),
        {"tenant_id": tenant_id},
    )
    return [
        {
            "store_id": r.store_id,
            "store_name": r.store_name,
            "status": r.status or "unknown",
            "daily_target_fen": r.daily_target_fen,
        }
        for r in result.fetchall()
    ]


async def _fetch_store_revenue(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    today: str,
) -> dict:
    """
    今日实际营收 + 成本率。

    成本率从 daily_pl_records 取，无记录时用 None 降级。
    目标营收优先取 stores.daily_target_fen，否则用近 30 天历史均值。
    """
    try:
        rev_result = await db.execute(
            text("""
                SELECT
                    COALESCE(SUM(total_amount_fen), 0)::bigint AS revenue_fen,
                    COUNT(*)::int AS order_count
                FROM orders
                WHERE tenant_id = :tenant_id
                  AND store_id = :store_id::uuid
                  AND DATE(created_at AT TIME ZONE 'Asia/Shanghai') = :today
                  AND status IN ('paid', 'completed')
                  AND is_deleted = FALSE
            """),
            {"tenant_id": tenant_id, "store_id": store_id, "today": today},
        )
        rev_row = rev_result.fetchone()

        cost_result = await db.execute(
            text("""
                SELECT COALESCE(cost_rate, 0) AS cost_rate
                FROM daily_pl_records
                WHERE tenant_id = :tenant_id
                  AND store_id = :store_id::uuid
                  AND record_date = :today
                LIMIT 1
            """),
            {"tenant_id": tenant_id, "store_id": store_id, "today": today},
        )
        cost_row = cost_result.fetchone()

        return {
            "revenue_fen": int(rev_row.revenue_fen) if rev_row else 0,
            "order_count": int(rev_row.order_count) if rev_row else 0,
            "cost_rate": float(cost_row.cost_rate) if cost_row and cost_row.cost_rate else 0.0,
        }
    except SQLAlchemyError as exc:
        logger.warning(
            "store_health_revenue_fetch_failed",
            store_id=store_id,
            error=str(exc),
            exc_info=True,
        )
        return {"revenue_fen": 0, "order_count": 0, "cost_rate": 0.0}
    except Exception as exc:  # noqa: BLE001 — 最外层兜底，不影响其他门店
        logger.warning(
            "store_health_revenue_unexpected_error",
            store_id=store_id,
            error=str(exc),
            exc_info=True,
        )
        return {"revenue_fen": 0, "order_count": 0, "cost_rate": 0.0}


async def _fetch_target_fen(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    daily_target_fen: int | None,
) -> int:
    """
    返回目标营收（分）。

    优先 stores.daily_target_fen，否则用近 30 天历史均值，均无则返回 0。
    """
    if daily_target_fen and daily_target_fen > 0:
        return daily_target_fen
    try:
        hist_result = await db.execute(
            text("""
                SELECT COALESCE(AVG(revenue_fen), 0)::bigint AS avg_revenue
                FROM daily_pl_records
                WHERE tenant_id = :tenant_id
                  AND store_id = :store_id::uuid
                  AND record_date >= CURRENT_DATE - INTERVAL '30 days'
            """),
            {"tenant_id": tenant_id, "store_id": store_id},
        )
        hist_row = hist_result.fetchone()
        return int(hist_row.avg_revenue) if hist_row and hist_row.avg_revenue else 0
    except SQLAlchemyError as exc:
        logger.warning(
            "store_health_target_fetch_failed",
            store_id=store_id,
            error=str(exc),
            exc_info=True,
        )
        return 0
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "store_health_target_unexpected_error",
            store_id=store_id,
            error=str(exc),
            exc_info=True,
        )
        return 0


def _build_alerts(
    revenue_rate: float,
    cost_rate: float,
    daily_review_rate: float,
    store_status: str,
) -> list[str]:
    """根据各维度指标生成预警信息列表。"""
    alerts: list[str] = []
    if store_status == "offline":
        alerts.append("门店离线")
    if revenue_rate < 0.6:
        alerts.append(f"营收仅达目标 {revenue_rate:.0%}，严重不足")
    elif revenue_rate < 0.8:
        alerts.append(f"营收达成率偏低 {revenue_rate:.0%}")
    if cost_rate > 0.50:
        alerts.append(f"成本率过高 {cost_rate:.1%}，需立即排查")
    elif cost_rate > 0.38:
        alerts.append(f"成本率偏高 {cost_rate:.1%}")
    if daily_review_rate < 0.5:
        alerts.append(f"日清完成率仅 {daily_review_rate:.0%}")
    return alerts


async def _build_store_health_item(
    db: AsyncSession,
    tenant_id: str,
    store_info: dict,
    today: str,
) -> dict:
    """
    为单个门店聚合健康数据。

    任意子查询失败时降级，不影响其他门店。
    """
    store_id = store_info["store_id"]
    store_name = store_info["store_name"]
    store_status = store_info["status"]

    # 并发拉取营收 + 目标营收
    revenue_data, target_fen = await asyncio.gather(
        _fetch_store_revenue(db, tenant_id, store_id, today),
        _fetch_target_fen(db, tenant_id, store_id, store_info.get("daily_target_fen")),
    )

    today_revenue_fen = revenue_data["revenue_fen"]
    cost_rate = revenue_data["cost_rate"]
    revenue_rate = (today_revenue_fen / target_fen) if target_fen > 0 else 0.0

    # 日清完成率（内存服务，不会抛 DB 异常）
    daily_review_rate = 0.0
    try:
        summaries = DailyReviewService.get_multi_store_summary(tenant_id, [store_id])
        if summaries:
            daily_review_rate = summaries[0].get("completion_rate", 0.0)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "store_health_daily_review_failed",
            store_id=store_id,
            error=str(exc),
            exc_info=True,
        )

    health_score = _calc_health_score(revenue_rate, cost_rate, daily_review_rate)
    health_grade = _health_grade(health_score)
    alerts = _build_alerts(revenue_rate, cost_rate, daily_review_rate, store_status)

    return {
        "store_id": store_id,
        "store_name": store_name,
        "status": store_status,
        "health_score": health_score,
        "health_grade": health_grade,
        "today_revenue_fen": today_revenue_fen,
        "revenue_rate": round(revenue_rate, 4),
        "cost_rate": round(cost_rate, 4),
        "daily_review_completion": round(daily_review_rate, 4),
        "alerts": alerts,
    }


@router.get("/overview")
async def get_store_health_overview(
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_with_tenant),
) -> dict:
    """
    所有门店健康汇总。

    - 并发查询每个门店数据
    - 单门店失败时返回灰色降级状态，不影响其他门店
    """
    today = date.today().isoformat()
    tenant_id = x_tenant_id

    try:
        stores = await _fetch_all_stores(db, tenant_id)
    except SQLAlchemyError as exc:
        logger.error("store_health_overview_stores_fetch_failed", error=str(exc), exc_info=True)
        return {"ok": True, "data": {"stores": [], "summary": _empty_summary()}}
    except Exception as exc:  # noqa: BLE001
        logger.error("store_health_overview_unexpected_error", error=str(exc), exc_info=True)
        return {"ok": True, "data": {"stores": [], "summary": _empty_summary()}}

    # 逐门店并发聚合（异常已在 _build_store_health_item 内降级）
    tasks = [_build_store_health_item(db, tenant_id, s, today) for s in stores]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    items: list[dict] = []
    for store_info, result in zip(stores, results):
        if isinstance(result, Exception):
            logger.warning(
                "store_health_item_failed",
                store_id=store_info["store_id"],
                error=str(result),
                exc_info=True,
            )
            # 降级：灰色占位
            items.append(_degraded_item(store_info))
        else:
            items.append(result)  # type: ignore[arg-type]

    summary = _calc_summary(items)

    return {
        "ok": True,
        "data": {
            "stores": items,
            "summary": summary,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


@router.get("/{store_id}")
async def get_store_health_detail(
    store_id: str,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_with_tenant),
) -> dict:
    """单门店详细健康报告。"""
    today = date.today().isoformat()
    tenant_id = x_tenant_id

    try:
        result = await db.execute(
            text("""
                SELECT
                    s.id::text       AS store_id,
                    s.name           AS store_name,
                    s.status,
                    s.daily_target_fen
                FROM stores s
                WHERE s.tenant_id = :tenant_id
                  AND s.id = :store_id::uuid
                  AND s.is_deleted = FALSE
            """),
            {"tenant_id": tenant_id, "store_id": store_id},
        )
        row = result.fetchone()
    except SQLAlchemyError as exc:
        logger.error(
            "store_health_detail_db_error",
            store_id=store_id,
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(status_code=503, detail="数据库查询失败，请稍后重试") from exc

    if not row:
        raise HTTPException(status_code=404, detail=f"门店 {store_id} 不存在")

    store_info = {
        "store_id": row.store_id,
        "store_name": row.store_name,
        "status": row.status or "unknown",
        "daily_target_fen": row.daily_target_fen,
    }

    try:
        item = await _build_store_health_item(db, tenant_id, store_info, today)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "store_health_detail_build_failed",
            store_id=store_id,
            error=str(exc),
            exc_info=True,
        )
        item = _degraded_item(store_info)

    return {"ok": True, "data": item}


# ─── 内部工具函数 ──────────────────────────────────────────────────────────────


def _empty_summary() -> dict:
    return {
        "total_stores": 0,
        "online_stores": 0,
        "avg_health_score": 0,
        "total_revenue_fen": 0,
    }


def _degraded_item(store_info: dict) -> dict:
    """门店数据获取失败时的灰色降级状态。"""
    return {
        "store_id": store_info["store_id"],
        "store_name": store_info["store_name"],
        "status": "unknown",
        "health_score": -1,  # -1 表示数据降级，前端显示灰色
        "health_grade": "-",
        "today_revenue_fen": 0,
        "revenue_rate": 0.0,
        "cost_rate": 0.0,
        "daily_review_completion": 0.0,
        "alerts": ["数据加载失败"],
    }


def _calc_summary(items: list[dict]) -> dict:
    """从门店列表计算汇总指标。"""
    total = len(items)
    online = sum(1 for s in items if s["status"] == "online")
    valid_scores = [s["health_score"] for s in items if s["health_score"] >= 0]
    avg_score = int(sum(valid_scores) / len(valid_scores)) if valid_scores else 0
    total_revenue = sum(s["today_revenue_fen"] for s in items)
    return {
        "total_stores": total,
        "online_stores": online,
        "avg_health_score": avg_score,
        "total_revenue_fen": total_revenue,
    }
