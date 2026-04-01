"""
Dashboard BFF — 总部首页数据聚合接口

GET /api/v1/dashboard/summary
返回今日经营关键指标、门店健康排名、近期 Agent 决策
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone

import structlog
from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


async def _get_db_with_tenant(
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
) -> AsyncSession:
    """依赖：从 X-Tenant-ID header 提取租户 ID，返回带 RLS 隔离的 DB session。"""
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


@router.get("/summary")
async def get_dashboard_summary(
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_with_tenant),
) -> dict:
    """
    聚合接口：今日 KPI + 门店健康 + 最近 Agent 决策
    单次请求返回首页所需全部数据
    """
    today = date.today().isoformat()
    tenant_id = x_tenant_id

    kpi, stores, decisions = await asyncio.gather(
        _fetch_today_kpi(db, tenant_id, today),
        _fetch_store_health(db, tenant_id),
        _fetch_recent_decisions(db, tenant_id),
    )

    return {
        "ok": True,
        "data": {
            "kpi": kpi,
            "stores": stores,
            "decisions": decisions,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


async def _fetch_today_kpi(db: AsyncSession, tenant_id: str, today: str) -> dict:
    """今日 KPI：营收/订单数/客单价/成本率"""
    try:
        result = await db.execute(
            text("""
                SELECT
                    COALESCE(SUM(total_amount_fen), 0)::bigint AS revenue_fen,
                    COUNT(*)::int AS order_count,
                    CASE WHEN COUNT(*) > 0
                         THEN (SUM(total_amount_fen) / COUNT(*))::int
                         ELSE 0 END AS avg_order_fen
                FROM orders
                WHERE tenant_id = :tenant_id
                  AND DATE(created_at AT TIME ZONE 'Asia/Shanghai') = :today
                  AND status IN ('paid', 'completed')
                  AND is_deleted = FALSE
            """),
            {"tenant_id": tenant_id, "today": today},
        )
        row = result.fetchone()

        cost_result = await db.execute(
            text("""
                SELECT COALESCE(AVG(cost_rate), 0) AS cost_rate
                FROM daily_pl_records
                WHERE tenant_id = :tenant_id AND record_date = :today
            """),
            {"tenant_id": tenant_id, "today": today},
        )
        cost_row = cost_result.fetchone()

        return {
            "revenue_fen": int(row.revenue_fen) if row else 0,
            "order_count": int(row.order_count) if row else 0,
            "avg_order_fen": int(row.avg_order_fen) if row else 0,
            "cost_rate": float(cost_row.cost_rate) if cost_row and cost_row.cost_rate else None,
        }
    except Exception as exc:  # noqa: BLE001 — BFF 最外层兜底，不影响其他卡片
        logger.warning("dashboard_kpi_fetch_failed", error=str(exc), exc_info=True)
        return {"revenue_fen": 0, "order_count": 0, "avg_order_fen": 0, "cost_rate": None}


async def _fetch_store_health(db: AsyncSession, tenant_id: str) -> list[dict]:
    """门店健康排名（按今日营收降序，最多 10 条）"""
    try:
        result = await db.execute(
            text("""
                SELECT
                    s.id::text AS store_id,
                    s.name AS store_name,
                    COALESCE(SUM(o.total_amount_fen), 0)::bigint AS today_revenue_fen,
                    COUNT(o.id)::int AS today_orders,
                    s.status
                FROM stores s
                LEFT JOIN orders o ON o.store_id = s.id
                    AND o.tenant_id = :tenant_id
                    AND DATE(o.created_at AT TIME ZONE 'Asia/Shanghai') = CURRENT_DATE
                    AND o.status IN ('paid', 'completed')
                    AND o.is_deleted = FALSE
                WHERE s.tenant_id = :tenant_id AND s.is_deleted = FALSE
                GROUP BY s.id, s.name, s.status
                ORDER BY today_revenue_fen DESC
                LIMIT 10
            """),
            {"tenant_id": tenant_id},
        )
        rows = result.fetchall()
        return [
            {
                "store_id": r.store_id,
                "store_name": r.store_name,
                "today_revenue_fen": r.today_revenue_fen,
                "today_orders": r.today_orders,
                "status": r.status or "unknown",
            }
            for r in rows
        ]
    except Exception as exc:  # noqa: BLE001 — BFF 最外层兜底
        logger.warning("dashboard_stores_fetch_failed", error=str(exc), exc_info=True)
        return []


async def _fetch_recent_decisions(db: AsyncSession, tenant_id: str) -> list[dict]:
    """最近 5 条 Agent 决策日志"""
    try:
        result = await db.execute(
            text("""
                SELECT
                    id::text,
                    agent_id,
                    action,
                    decision_type,
                    confidence,
                    created_at
                FROM agent_decision_logs
                WHERE tenant_id = :tenant_id
                ORDER BY created_at DESC
                LIMIT 5
            """),
            {"tenant_id": tenant_id},
        )
        rows = result.fetchall()
        return [
            {
                "id": r.id,
                "agent_id": r.agent_id,
                "action": r.action,
                "decision_type": r.decision_type,
                "confidence": float(r.confidence) if r.confidence is not None else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    except Exception as exc:  # noqa: BLE001 — BFF 最外层兜底
        logger.warning("dashboard_decisions_fetch_failed", error=str(exc), exc_info=True)
        return []
