"""Agent Observability API — Agent 可观测性中心

提供 KPI 汇总、Session 运行列表、Session 事件时间线、Agent 效果分析、健康度监控。
从 SessionRun / SessionEvent / AgentDecisionLog 真实 DB 查询。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.decision_log import AgentDecisionLog
from ..models.session_event import SessionEvent
from ..models.session_run import SessionRun
from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/agent/observability", tags=["observability"])


# ── DB 依赖 ──────────────────────────────────────────────────────────────────

async def _get_db(
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
) -> AsyncSession:
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ── 工具函数 ─────────────────────────────────────────────────────────────────

def _parse_date(d: date | None) -> datetime | None:
    """将 date 转为 timezone-aware datetime（当日 00:00 UTC）"""
    if d is None:
        return None
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def _parse_end_date(d: date | None) -> datetime | None:
    """将 date 转为 timezone-aware datetime（次日 00:00 UTC，即当日 23:59:59 之后）"""
    if d is None:
        return None
    next_day = d + timedelta(days=1)
    return datetime(next_day.year, next_day.month, next_day.day, tzinfo=timezone.utc)


# ── 1. KPI Summary ──────────────────────────────────────────────────────────

@router.get("/kpis")
async def get_kpis(
    db: AsyncSession = Depends(_get_db),
    store_id: Optional[str] = Query(None, description="按门店过滤"),
    start_date: Optional[date] = Query(None, description="起始日期"),
    end_date: Optional[date] = Query(None, description="结束日期"),
) -> dict:
    """KPI 汇总 — 总运行次数、各状态计数、平均置信度/耗时、Token/成本累计"""
    try:
        # ── SessionRun 聚合 ──
        sr_query = select(
            func.count().label("total_sessions"),
            func.count().filter(SessionRun.status == "completed").label("completed"),
            func.count().filter(SessionRun.status == "failed").label("failed"),
            func.count().filter(SessionRun.status == "paused").label("paused"),
            func.count().filter(SessionRun.status == "cancelled").label("cancelled"),
            func.count().filter(SessionRun.status == "running").label("running"),
            func.coalesce(func.sum(SessionRun.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(SessionRun.total_cost_fen), 0).label("total_cost_fen"),
        ).where(SessionRun.is_deleted.is_(False))

        if store_id:
            sr_query = sr_query.where(SessionRun.store_id == store_id)
        if start_date:
            sr_query = sr_query.where(SessionRun.started_at >= _parse_date(start_date))
        if end_date:
            sr_query = sr_query.where(SessionRun.started_at < _parse_end_date(end_date))

        sr_result = await db.execute(sr_query)
        sr_row = sr_result.one()

        # ── AgentDecisionLog 聚合 ──
        dl_query = select(
            func.avg(AgentDecisionLog.confidence).label("avg_confidence"),
            func.avg(AgentDecisionLog.execution_ms).label("avg_execution_ms"),
        ).where(AgentDecisionLog.is_deleted.is_(False))

        if store_id:
            dl_query = dl_query.where(AgentDecisionLog.store_id == store_id)
        if start_date:
            dl_query = dl_query.where(AgentDecisionLog.decided_at >= _parse_date(start_date))
        if end_date:
            dl_query = dl_query.where(AgentDecisionLog.decided_at < _parse_end_date(end_date))

        dl_result = await db.execute(dl_query)
        dl_row = dl_result.one()

        return {
            "ok": True,
            "data": {
                "total_sessions": sr_row.total_sessions,
                "completed": sr_row.completed,
                "failed": sr_row.failed,
                "paused": sr_row.paused,
                "cancelled": sr_row.cancelled,
                "running": sr_row.running,
                "avg_confidence": round(float(dl_row.avg_confidence), 4) if dl_row.avg_confidence else 0.0,
                "avg_execution_ms": round(float(dl_row.avg_execution_ms), 1) if dl_row.avg_execution_ms else 0.0,
                "total_tokens": int(sr_row.total_tokens),
                "total_cost_fen": int(sr_row.total_cost_fen),
            },
        }
    except (SQLAlchemyError, ConnectionError) as exc:
        logger.warning("observability.kpis.db_error", error=str(exc))
        return {
            "ok": True,
            "data": {
                "total_sessions": 0,
                "completed": 0,
                "failed": 0,
                "paused": 0,
                "cancelled": 0,
                "running": 0,
                "avg_confidence": 0.0,
                "avg_execution_ms": 0.0,
                "total_tokens": 0,
                "total_cost_fen": 0,
            },
        }


# ── 2. Session List ─────────────────────────────────────────────────────────

@router.get("/sessions")
async def get_sessions(
    db: AsyncSession = Depends(_get_db),
    store_id: Optional[str] = Query(None, description="按门店过滤"),
    status: Optional[str] = Query(None, description="按状态过滤: running/completed/failed/paused/cancelled"),
    agent_template_name: Optional[str] = Query(None, description="按Agent模板名过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> dict:
    """Session 列表 — 分页查询 SessionRun"""
    try:
        base = select(SessionRun).where(SessionRun.is_deleted.is_(False))

        if store_id:
            base = base.where(SessionRun.store_id == store_id)
        if status:
            base = base.where(SessionRun.status == status)
        if agent_template_name:
            base = base.where(SessionRun.agent_template_name == agent_template_name)

        # 总数
        count_q = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_q)).scalar() or 0

        # 分页数据
        items_q = base.order_by(SessionRun.started_at.desc()).offset((page - 1) * size).limit(size)
        result = await db.execute(items_q)
        rows = result.scalars().all()

        items = [
            {
                "id": str(r.id),
                "session_id": r.session_id,
                "status": r.status,
                "agent_template_name": r.agent_template_name,
                "store_id": str(r.store_id) if r.store_id else None,
                "total_steps": r.total_steps,
                "completed_steps": r.completed_steps,
                "failed_steps": r.failed_steps,
                "total_tokens": r.total_tokens,
                "total_cost_fen": r.total_cost_fen,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in rows
        ]

        return {
            "ok": True,
            "data": {
                "items": items,
                "total": total,
                "page": page,
                "size": size,
            },
        }
    except (SQLAlchemyError, ConnectionError) as exc:
        logger.warning("observability.sessions.db_error", error=str(exc))
        return {
            "ok": True,
            "data": {"items": [], "total": 0, "page": page, "size": size},
        }


# ── 3. Session Timeline ─────────────────────────────────────────────────────

@router.get("/sessions/{session_id}/timeline")
async def get_session_timeline(
    session_id: str,
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """Session 事件时间线 — 按 sequence_no 排序返回所有事件"""
    try:
        query = (
            select(SessionEvent)
            .where(
                SessionEvent.session_id == session_id,
                SessionEvent.is_deleted.is_(False),
            )
            .order_by(SessionEvent.sequence_no.asc())
        )
        result = await db.execute(query)
        rows = result.scalars().all()

        events = [
            {
                "id": str(r.id),
                "session_id": r.session_id,
                "sequence_no": r.sequence_no,
                "event_type": r.event_type,
                "step_id": r.step_id,
                "agent_id": r.agent_id,
                "action": r.action,
                "input_json": r.input_json,
                "output_json": r.output_json,
                "tokens_used": r.tokens_used,
                "duration_ms": r.duration_ms,
                "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
            }
            for r in rows
        ]

        return {
            "ok": True,
            "data": {
                "session_id": session_id,
                "events": events,
                "count": len(events),
            },
        }
    except (SQLAlchemyError, ConnectionError) as exc:
        logger.warning("observability.timeline.db_error", error=str(exc), session_id=session_id)
        return {
            "ok": True,
            "data": {"session_id": session_id, "events": [], "count": 0},
        }


# ── 4. Agent Effectiveness ──────────────────────────────────────────────────

@router.get("/effectiveness")
async def get_effectiveness(
    db: AsyncSession = Depends(_get_db),
    store_id: Optional[str] = Query(None, description="按门店过滤"),
    start_date: Optional[date] = Query(None, description="起始日期"),
    end_date: Optional[date] = Query(None, description="结束日期"),
) -> dict:
    """效果分析 — 按 agent_id 分组统计调用次数、成功率、平均置信度、平均耗时"""
    try:
        query = select(
            AgentDecisionLog.agent_id,
            func.count().label("total_calls"),
            func.avg(AgentDecisionLog.confidence).label("avg_confidence"),
            func.avg(AgentDecisionLog.execution_ms).label("avg_execution_ms"),
        ).where(AgentDecisionLog.is_deleted.is_(False)).group_by(AgentDecisionLog.agent_id)

        if store_id:
            query = query.where(AgentDecisionLog.store_id == store_id)
        if start_date:
            query = query.where(AgentDecisionLog.decided_at >= _parse_date(start_date))
        if end_date:
            query = query.where(AgentDecisionLog.decided_at < _parse_end_date(end_date))

        result = await db.execute(query)
        rows = result.all()

        # 从 SessionRun 中获取每个 agent 的成功率
        sr_query = select(
            SessionRun.agent_template_name,
            func.count().label("total"),
            func.count().filter(SessionRun.status == "completed").label("completed"),
        ).where(SessionRun.is_deleted.is_(False)).group_by(SessionRun.agent_template_name)

        if store_id:
            sr_query = sr_query.where(SessionRun.store_id == store_id)
        if start_date:
            sr_query = sr_query.where(SessionRun.started_at >= _parse_date(start_date))
        if end_date:
            sr_query = sr_query.where(SessionRun.started_at < _parse_end_date(end_date))

        sr_result = await db.execute(sr_query)
        sr_rows = sr_result.all()
        success_map = {
            r.agent_template_name: round(r.completed / r.total * 100, 1) if r.total > 0 else 0.0
            for r in sr_rows
        }

        agents = [
            {
                "agent_id": r.agent_id,
                "total_calls": r.total_calls,
                "success_rate": success_map.get(r.agent_id, 0.0),
                "avg_confidence": round(float(r.avg_confidence), 4) if r.avg_confidence else 0.0,
                "avg_execution_ms": round(float(r.avg_execution_ms), 1) if r.avg_execution_ms else 0.0,
            }
            for r in rows
        ]

        # 决策类型分布
        dt_query = select(
            AgentDecisionLog.decision_type,
            func.count().label("count"),
        ).where(AgentDecisionLog.is_deleted.is_(False)).group_by(AgentDecisionLog.decision_type)

        if store_id:
            dt_query = dt_query.where(AgentDecisionLog.store_id == store_id)
        if start_date:
            dt_query = dt_query.where(AgentDecisionLog.decided_at >= _parse_date(start_date))
        if end_date:
            dt_query = dt_query.where(AgentDecisionLog.decided_at < _parse_end_date(end_date))

        dt_result = await db.execute(dt_query)
        dt_rows = dt_result.all()

        decision_type_distribution = [
            {"type": r.decision_type, "count": r.count}
            for r in dt_rows
        ]

        return {
            "ok": True,
            "data": {
                "agents": agents,
                "decision_type_distribution": decision_type_distribution,
            },
        }
    except (SQLAlchemyError, ConnectionError) as exc:
        logger.warning("observability.effectiveness.db_error", error=str(exc))
        return {
            "ok": True,
            "data": {"agents": [], "decision_type_distribution": []},
        }


# ── 5. Health Check ──────────────────────────────────────────────────────────

@router.get("/health")
async def get_health(
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """Agent 健康度 — 最近5分钟失败情况 + 整体状态"""
    try:
        five_min_ago = datetime.now(timezone.utc) - timedelta(minutes=5)

        # 最近5分钟的 SessionRun 统计
        recent_query = select(
            func.count().label("total_recent"),
            func.count().filter(SessionRun.status == "failed").label("failed_recent"),
        ).where(
            SessionRun.is_deleted.is_(False),
            SessionRun.started_at >= five_min_ago,
        )
        recent_result = await db.execute(recent_query)
        recent = recent_result.one()

        # 各 Agent 今日统计
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        agent_query = select(
            SessionRun.agent_template_name,
            func.count().label("today_calls"),
            func.count().filter(SessionRun.status == "failed").label("today_failed"),
            func.avg(
                func.extract("epoch", SessionRun.finished_at) - func.extract("epoch", SessionRun.started_at)
            ).label("avg_duration_sec"),
        ).where(
            SessionRun.is_deleted.is_(False),
            SessionRun.started_at >= today_start,
        ).group_by(SessionRun.agent_template_name)

        agent_result = await db.execute(agent_query)
        agent_rows = agent_result.all()

        agents = []
        for r in agent_rows:
            error_rate = round(r.today_failed / r.today_calls, 4) if r.today_calls > 0 else 0.0
            avg_latency_ms = round(float(r.avg_duration_sec) * 1000, 0) if r.avg_duration_sec else 0
            agent_status = "healthy"
            if error_rate > 0.1:
                agent_status = "error"
            elif error_rate > 0.02:
                agent_status = "warning"

            agents.append({
                "agent_id": r.agent_template_name,
                "status": agent_status,
                "today_calls": r.today_calls,
                "today_failed": r.today_failed,
                "avg_latency_ms": avg_latency_ms,
                "error_rate": error_rate,
            })

        # 整体状态判定
        has_error = any(a["status"] == "error" for a in agents)
        has_warning = any(a["status"] == "warning" for a in agents)
        recent_failure_rate = (
            recent.failed_recent / recent.total_recent if recent.total_recent > 0 else 0.0
        )

        if has_error or recent_failure_rate > 0.2:
            overall_status = "unhealthy"
        elif has_warning or recent_failure_rate > 0.05:
            overall_status = "degraded"
        else:
            overall_status = "healthy"

        return {
            "ok": True,
            "data": {
                "overall_status": overall_status,
                "recent_5min": {
                    "total": recent.total_recent,
                    "failed": recent.failed_recent,
                },
                "agents": agents,
                "summary": {
                    "total_agents": len(agents),
                    "healthy": sum(1 for a in agents if a["status"] == "healthy"),
                    "warning": sum(1 for a in agents if a["status"] == "warning"),
                    "error": sum(1 for a in agents if a["status"] == "error"),
                },
            },
        }
    except (SQLAlchemyError, ConnectionError) as exc:
        logger.warning("observability.health.db_error", error=str(exc))
        return {
            "ok": True,
            "data": {
                "overall_status": "unhealthy",
                "recent_5min": {"total": 0, "failed": 0},
                "agents": [],
                "summary": {"total_agents": 0, "healthy": 0, "warning": 0, "error": 0},
            },
        }
