"""
PRD-11 sub-C 成本分摊 dashboard BFF

数据源: cost_attribution_summary 表 (v438) — 由 SplitAttributionProjector 消费
inventory.split_attributed 事件后汇总写入.

GET /api/v1/cost-attribution/orders/{order_id}
    单订单 OrderItem 级 share 切分明细 (按 occurred_at ASC)

GET /api/v1/cost-attribution/dishes/{dish_id}/summary?from=&to=
    单菜 share_count 分布 + BOM 平均分摊金额

GET /api/v1/cost-attribution/summary?from=&to=
    时段总览 (总 attribution 数 / 总 BOM 分摊金额 / share_count>1 触发比例)
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, Path, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)
router = APIRouter(
    prefix="/api/v1/cost-attribution",
    tags=["cost-attribution"],
)


async def _get_db_with_tenant(
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
) -> AsyncSession:
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _row_to_dict(row) -> dict:
    """SQLAlchemy Row -> dict (各端点共用渲染格式)."""
    shares = row.shares
    # asyncpg jsonb -> dict/list 直接到 Python; SQLAlchemy 透传不变. 若是 str
    # (sync driver / 旧版本), 走 json.loads.
    if isinstance(shares, str):
        import json

        try:
            shares = json.loads(shares)
        except (TypeError, ValueError):
            shares = []
    return {
        "id": str(row.id),
        "source_event_id": str(row.source_event_id),
        "order_id": str(row.order_id) if row.order_id else None,
        "order_item_id": str(row.order_item_id) if row.order_item_id else None,
        "dish_id": str(row.dish_id) if row.dish_id else None,
        "method": row.method,
        "share_count": row.share_count,
        "bom_cost_total_fen": int(row.bom_cost_total_fen),
        "shares": shares if isinstance(shares, list) else [],
        "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/orders/{order_id}")
async def get_order_cost_attribution(
    order_id: str = Path(..., description="订单 UUID"),
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_with_tenant),
) -> dict:
    """单订单 OrderItem 级 share 切分明细 (徐记海鲜场景: 拆单结账, 收银员看分摊明细)."""
    try:
        result = await db.execute(
            text(
                """
                SELECT id, source_event_id, order_id, order_item_id, dish_id,
                       method, share_count, bom_cost_total_fen, shares,
                       occurred_at, created_at
                FROM cost_attribution_summary
                WHERE tenant_id = :tenant_id AND order_id = :order_id
                ORDER BY occurred_at ASC
                """
            ),
            {"tenant_id": x_tenant_id, "order_id": order_id},
        )
        rows = result.fetchall()
        attributions = [_row_to_dict(r) for r in rows]
    except SQLAlchemyError as exc:
        logger.warning(
            "cost_attribution_order_query_failed",
            order_id=order_id,
            error=str(exc),
        )
        attributions = []

    total_bom_fen = sum(a["bom_cost_total_fen"] for a in attributions)
    return {
        "ok": True,
        "data": {
            "order_id": order_id,
            "attributions": attributions,
            "summary": {
                "item_count": len(attributions),
                "total_bom_cost_fen": total_bom_fen,
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


@router.get("/dishes/{dish_id}/summary")
async def get_dish_cost_attribution_summary(
    dish_id: str = Path(..., description="菜品 UUID"),
    from_date: Optional[date] = Query(None, alias="from", description="起始日期 YYYY-MM-DD"),
    to_date: Optional[date] = Query(None, alias="to", description="截止日期 YYYY-MM-DD"),
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_with_tenant),
) -> dict:
    """单菜 share_count 分布 + 平均 BOM 摊销 (产品经理场景: 看哪些菜常被拆点)."""
    where_clauses = ["tenant_id = :tenant_id", "dish_id = :dish_id"]
    params: dict = {"tenant_id": x_tenant_id, "dish_id": dish_id}
    if from_date is not None:
        where_clauses.append("occurred_at >= :from_date")
        params["from_date"] = from_date
    if to_date is not None:
        # 包含 to_date 当天 — 直接用 < to_date + 1 day; 数据库侧让 occurred_at < :to_cap
        # caller 期望直观语义 "from=2026-05-01&to=2026-05-31" 包含 5/31 全天
        where_clauses.append("occurred_at < :to_cap")
        from datetime import timedelta

        params["to_cap"] = to_date + timedelta(days=1)
    where_sql = " AND ".join(where_clauses)

    try:
        # 主聚合: share_count 分布 + bom 平均
        agg_result = await db.execute(
            text(
                f"""
                SELECT
                    share_count,
                    COUNT(*)::int AS event_count,
                    SUM(bom_cost_total_fen)::bigint AS total_bom_fen,
                    AVG(bom_cost_total_fen)::bigint AS avg_bom_fen
                FROM cost_attribution_summary
                WHERE {where_sql}
                GROUP BY share_count
                ORDER BY share_count ASC
                """  # noqa: S608 — where_sql 由白名单字段拼接, params 走 bound 参数
            ),
            params,
        )
        agg_rows = agg_result.fetchall()
        distribution = [
            {
                "share_count": int(r.share_count),
                "event_count": int(r.event_count),
                "total_bom_fen": int(r.total_bom_fen or 0),
                "avg_bom_fen": int(r.avg_bom_fen or 0),
            }
            for r in agg_rows
        ]
        total_events = sum(d["event_count"] for d in distribution)
        total_bom_fen = sum(d["total_bom_fen"] for d in distribution)
    except SQLAlchemyError as exc:
        logger.warning(
            "cost_attribution_dish_summary_failed",
            dish_id=dish_id,
            error=str(exc),
        )
        distribution = []
        total_events = 0
        total_bom_fen = 0

    return {
        "ok": True,
        "data": {
            "dish_id": dish_id,
            "from": from_date.isoformat() if from_date else None,
            "to": to_date.isoformat() if to_date else None,
            "distribution": distribution,
            "summary": {
                "total_events": total_events,
                "total_bom_fen": total_bom_fen,
                "avg_bom_fen": (total_bom_fen // total_events) if total_events else 0,
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


@router.get("/summary")
async def get_cost_attribution_summary(
    from_date: Optional[date] = Query(None, alias="from", description="起始日期 YYYY-MM-DD"),
    to_date: Optional[date] = Query(None, alias="to", description="截止日期 YYYY-MM-DD"),
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_with_tenant),
) -> dict:
    """时段总览: 总 attribution 数 / 总 BOM 分摊金额 / share_count>1 比例 (运营周报场景)."""
    where_clauses = ["tenant_id = :tenant_id"]
    params: dict = {"tenant_id": x_tenant_id}
    if from_date is not None:
        where_clauses.append("occurred_at >= :from_date")
        params["from_date"] = from_date
    if to_date is not None:
        from datetime import timedelta

        where_clauses.append("occurred_at < :to_cap")
        params["to_cap"] = to_date + timedelta(days=1)
    where_sql = " AND ".join(where_clauses)

    try:
        result = await db.execute(
            text(
                f"""
                SELECT
                    COUNT(*)::int AS total_events,
                    COUNT(*) FILTER (WHERE share_count > 1)::int AS share_split_events,
                    COALESCE(SUM(bom_cost_total_fen), 0)::bigint AS total_bom_fen,
                    COALESCE(AVG(share_count), 0)::float AS avg_share_count,
                    COUNT(DISTINCT order_id)::int AS distinct_orders,
                    COUNT(DISTINCT dish_id)::int AS distinct_dishes
                FROM cost_attribution_summary
                WHERE {where_sql}
                """  # noqa: S608
            ),
            params,
        )
        row = result.fetchone()
        total_events = int(row.total_events) if row else 0
        share_split_events = int(row.share_split_events) if row else 0
        total_bom_fen = int(row.total_bom_fen) if row else 0
        avg_share_count = float(row.avg_share_count) if row else 0.0
        distinct_orders = int(row.distinct_orders) if row else 0
        distinct_dishes = int(row.distinct_dishes) if row else 0
    except SQLAlchemyError as exc:
        logger.warning("cost_attribution_summary_query_failed", error=str(exc))
        total_events = 0
        share_split_events = 0
        total_bom_fen = 0
        avg_share_count = 0.0
        distinct_orders = 0
        distinct_dishes = 0

    share_split_ratio = (
        round(share_split_events / total_events, 4) if total_events else 0.0
    )

    return {
        "ok": True,
        "data": {
            "from": from_date.isoformat() if from_date else None,
            "to": to_date.isoformat() if to_date else None,
            "summary": {
                "total_events": total_events,
                "share_split_events": share_split_events,
                "share_split_ratio": share_split_ratio,
                "total_bom_fen": total_bom_fen,
                "avg_share_count": round(avg_share_count, 2),
                "distinct_orders": distinct_orders,
                "distinct_dishes": distinct_dishes,
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }
