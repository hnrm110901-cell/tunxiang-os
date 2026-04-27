"""
Agent 监控 BFF 接口

GET /api/v1/agent-monitor/status    — 各 Agent 运行状态 + 今日统计
GET /api/v1/agent-monitor/decisions — 最近 Agent 决策日志（带过滤）
GET /api/v1/agent-monitor/events    — 事件流实时状态（Redis Stream 积压）
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import structlog
from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/agent-monitor", tags=["agent-monitor"])

# 9个 Skill Agent 定义
SKILL_AGENTS = [
    {"id": "discount_guard", "name": "折扣守护", "emoji": "🛡️", "priority": "P0"},
    {"id": "smart_menu", "name": "智能排菜", "emoji": "🍜", "priority": "P0"},
    {"id": "serve_dispatch", "name": "出餐调度", "emoji": "⚡", "priority": "P1"},
    {"id": "member_insight", "name": "会员洞察", "emoji": "👤", "priority": "P1"},
    {"id": "inventory_alert", "name": "库存预警", "emoji": "📦", "priority": "P1"},
    {"id": "finance_audit", "name": "财务稽核", "emoji": "💰", "priority": "P1"},
    {"id": "store_inspect", "name": "巡店质检", "emoji": "🔍", "priority": "P2"},
    {"id": "smart_service", "name": "智能客服", "emoji": "💬", "priority": "P2"},
    {"id": "private_ops", "name": "私域运营", "emoji": "📣", "priority": "P2"},
]


async def _get_db_with_tenant(
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
) -> AsyncSession:
    """依赖：从 X-Tenant-ID header 提取租户 ID，返回带 RLS 隔离的 DB session。"""
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


@router.get("/status")
async def get_agent_status(
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_with_tenant),
) -> dict:
    """各 Agent 今日执行统计"""
    today = date.today().isoformat()
    try:
        result = await db.execute(
            text("""
            SELECT
                agent_id,
                COUNT(*)::int AS total_decisions,
                AVG(confidence)::float AS avg_confidence,
                MAX(created_at) AS last_active_at,
                COUNT(*) FILTER (WHERE confidence >= 0.8)::int AS high_confidence_count
            FROM agent_decision_logs
            WHERE tenant_id = :tenant_id
              AND DATE(created_at AT TIME ZONE 'Asia/Shanghai') = :today
            GROUP BY agent_id
        """),
            {"tenant_id": x_tenant_id, "today": today},
        )
        rows = result.fetchall()
        stats_by_agent = {r.agent_id: r for r in rows}
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_status_query_failed", error=str(exc), exc_info=True)
        stats_by_agent = {}

    agents = []
    for agent in SKILL_AGENTS:
        stats = stats_by_agent.get(agent["id"])
        agents.append(
            {
                **agent,
                "status": "active" if stats else "idle",
                "today_decisions": int(stats.total_decisions) if stats else 0,
                "avg_confidence": round(float(stats.avg_confidence), 2) if stats and stats.avg_confidence else None,
                "last_active_at": stats.last_active_at.isoformat() if stats and stats.last_active_at else None,
                "high_confidence_count": int(stats.high_confidence_count) if stats else 0,
            }
        )

    total_decisions = sum(a["today_decisions"] for a in agents)
    active_count = sum(1 for a in agents if a["status"] == "active")

    return {
        "ok": True,
        "data": {
            "agents": agents,
            "summary": {
                "total_agents": len(agents),
                "active_count": active_count,
                "today_decisions": total_decisions,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
        },
    }


@router.get("/decisions")
async def get_recent_decisions(
    agent_id: str | None = Query(None),
    limit: int = Query(20, le=50),
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_with_tenant),
) -> dict:
    """最近 Agent 决策记录"""
    try:
        params: dict = {"tenant_id": x_tenant_id, "limit": limit}
        where_clause = "WHERE tenant_id = :tenant_id"
        if agent_id:
            where_clause += " AND agent_id = :agent_id"
            params["agent_id"] = agent_id

        result = await db.execute(
            text(f"""
            SELECT id::text, agent_id, action, decision_type,
                   confidence, reasoning, output_action,
                   constraints_check, created_at
            FROM agent_decision_logs
            {where_clause}
            ORDER BY created_at DESC
            LIMIT :limit
        """),
            params,
        )
        rows = result.fetchall()
        return {
            "ok": True,
            "data": [
                {
                    "id": r.id,
                    "agent_id": r.agent_id,
                    "action": r.action,
                    "decision_type": r.decision_type,
                    "confidence": float(r.confidence) if r.confidence else None,
                    "reasoning": r.reasoning,
                    "constraints_check": r.constraints_check,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ],
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_decisions_query_failed", error=str(exc), exc_info=True)
        return {"ok": True, "data": []}
