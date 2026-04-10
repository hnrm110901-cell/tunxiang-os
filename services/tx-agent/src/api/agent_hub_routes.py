"""
Agent 中枢 BFF 接口 — 6 核心业务 Agent 状态

GET /api/v1/agent-hub/status     — 6个核心Agent的聚合状态
GET /api/v1/agent-hub/actions    — 待处理行动队列（Phase 1：待人工确认）
POST /api/v1/agent-hub/actions/{action_id}/confirm  — 确认执行某个行动
POST /api/v1/agent-hub/actions/{action_id}/dismiss  — 驳回某个行动
GET /api/v1/agent-hub/log        — 决策行动日志（聚合视图）
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/agent-hub", tags=["agent-hub"])

# 6 核心业务 Agent 定义
CORE_AGENTS = [
    {
        "id": "tx-ops",
        "name": "运营指挥官",
        "name_en": "Operations Commander",
        "emoji": "🎯",
        "color": "#FF6B35",
        "service": "tx-ops",
        "description": "实时监控门店运营，主动识别并处理运营异常",
    },
    {
        "id": "tx-menu",
        "name": "菜品智能体",
        "name_en": "Dish Intelligence Agent",
        "emoji": "🍳",
        "color": "#0F6E56",
        "service": "tx-menu",
        "description": "分析菜品表现，优化菜单结构，预警沽清与新品机会",
    },
    {
        "id": "tx-growth",
        "name": "客户大脑",
        "name_en": "Customer Intelligence Agent",
        "emoji": "👤",
        "color": "#6D3EA8",
        "service": "tx-growth",
        "description": "洞察客户行为，预测流失，驱动精准营销与复购",
    },
    {
        "id": "tx-analytics",
        "name": "收益优化师",
        "name_en": "Revenue Optimization Agent",
        "emoji": "💰",
        "color": "#BA7517",
        "service": "tx-analytics",
        "description": "监控收益结构，发现定价机会，优化翻台率与客单价",
    },
    {
        "id": "tx-supply",
        "name": "供应链卫士",
        "name_en": "Supply Chain Guardian",
        "emoji": "📦",
        "color": "#185FA5",
        "service": "tx-supply",
        "description": "预测需求，防范食材断供，降低损耗，保障食安合规",
    },
    {
        "id": "tx-brain",
        "name": "经营分析师",
        "name_en": "Business Intelligence Agent",
        "emoji": "📊",
        "color": "#A32D2D",
        "service": "tx-brain",
        "description": "生成每日经营简报，发现经营异常，回答自然语言问题",
    },
]


async def _get_db_with_tenant(
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
) -> AsyncSession:
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


@router.get("/status")
async def get_hub_status(
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_with_tenant),
) -> dict:
    """6 个核心 Agent 今日状态聚合"""
    today = date.today().isoformat()
    try:
        result = await db.execute(text("""
            SELECT
                agent_id,
                COUNT(*)::int AS total_decisions,
                COUNT(*) FILTER (WHERE status = 'pending_confirm')::int AS pending_count,
                COUNT(*) FILTER (WHERE status = 'confirmed')::int AS confirmed_count,
                AVG(confidence)::float AS avg_confidence,
                MAX(created_at) AS last_active_at
            FROM agent_decision_logs
            WHERE tenant_id = :tenant_id
              AND DATE(created_at AT TIME ZONE 'Asia/Shanghai') = :today
            GROUP BY agent_id
        """), {"tenant_id": x_tenant_id, "today": today})
        rows = result.fetchall()
        stats = {r.agent_id: r for r in rows}
    except Exception as exc:
        logger.warning("agent_hub_status_query_failed", error=str(exc))
        stats = {}

    agents_out = []
    for agent in CORE_AGENTS:
        s = stats.get(agent["id"])
        agents_out.append({
            **agent,
            "status": "active" if s and s.total_decisions > 0 else "idle",
            "today_decisions": s.total_decisions if s else 0,
            "pending_actions": s.pending_count if s else 0,
            "avg_confidence": round(float(s.avg_confidence), 2) if s and s.avg_confidence else None,
            "last_active_at": s.last_active_at.isoformat() if s and s.last_active_at else None,
        })

    total_pending = sum(a["pending_actions"] for a in agents_out)
    active_count = sum(1 for a in agents_out if a["status"] == "active")

    return {
        "ok": True,
        "data": {
            "agents": agents_out,
            "summary": {
                "total_agents": len(agents_out),
                "active_count": active_count,
                "total_pending_actions": total_pending,
                "phase": "advisory",  # Phase 1: all actions need human confirmation
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
        },
    }


@router.get("/actions")
async def get_pending_actions(
    status: Literal["pending_confirm", "confirmed", "dismissed", "all"] = Query("pending_confirm"),
    agent_id: str | None = Query(None),
    limit: int = Query(20, le=50),
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_with_tenant),
) -> dict:
    """待处理行动队列"""
    try:
        params: dict = {"tenant_id": x_tenant_id, "limit": limit}
        where_clauses = ["tenant_id = :tenant_id"]
        if status != "all":
            where_clauses.append("status = :status")
            params["status"] = status
        if agent_id:
            where_clauses.append("agent_id = :agent_id")
            params["agent_id"] = agent_id

        result = await db.execute(text(f"""
            SELECT id::text, agent_id, action, decision_type,
                   confidence, reasoning, output_action,
                   constraints_check, status, created_at, updated_at
            FROM agent_decision_logs
            WHERE {' AND '.join(where_clauses)}
            ORDER BY created_at DESC
            LIMIT :limit
        """), params)
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
                    "output_action": r.output_action,
                    "constraints_check": r.constraints_check,
                    "status": r.status,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ],
        }
    except Exception as exc:
        logger.warning("agent_hub_actions_query_failed", error=str(exc))
        return {"ok": True, "data": []}


@router.post("/actions/{action_id}/confirm")
async def confirm_action(
    action_id: str,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_with_tenant),
) -> dict:
    """人工确认执行某个 Agent 行动（Phase 1 必须人工确认）"""
    try:
        await db.execute(text("""
            UPDATE agent_decision_logs
            SET status = 'confirmed', updated_at = NOW()
            WHERE id = :id AND tenant_id = :tenant_id
        """), {"id": action_id, "tenant_id": x_tenant_id})
        await db.commit()
        return {"ok": True, "message": "action confirmed"}
    except Exception as exc:
        logger.warning("confirm_action_failed", error=str(exc))
        return {"ok": False, "error": str(exc)}


@router.post("/actions/{action_id}/dismiss")
async def dismiss_action(
    action_id: str,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_with_tenant),
) -> dict:
    """驳回某个 Agent 行动"""
    try:
        await db.execute(text("""
            UPDATE agent_decision_logs
            SET status = 'dismissed', updated_at = NOW()
            WHERE id = :id AND tenant_id = :tenant_id
        """), {"id": action_id, "tenant_id": x_tenant_id})
        await db.commit()
        return {"ok": True, "message": "action dismissed"}
    except Exception as exc:
        logger.warning("dismiss_action_failed", error=str(exc))
        return {"ok": False, "error": str(exc)}


@router.get("/log")
async def get_action_log(
    agent_id: str | None = Query(None),
    limit: int = Query(30, le=100),
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_with_tenant),
) -> dict:
    """决策行动日志（聚合视图，含三条硬约束检查结果）"""
    try:
        params: dict = {"tenant_id": x_tenant_id, "limit": limit}
        where = "tenant_id = :tenant_id"
        if agent_id:
            where += " AND agent_id = :agent_id"
            params["agent_id"] = agent_id

        result = await db.execute(text(f"""
            SELECT id::text, agent_id, action, decision_type,
                   confidence, reasoning, output_action,
                   constraints_check, status, created_at
            FROM agent_decision_logs
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT :limit
        """), params)
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
                    "status": r.status,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ],
        }
    except Exception as exc:
        logger.warning("agent_hub_log_query_failed", error=str(exc))
        return {"ok": True, "data": []}
