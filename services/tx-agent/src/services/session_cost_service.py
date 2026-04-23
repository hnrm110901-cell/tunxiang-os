"""SessionCostService — Session 成本统计与趋势分析

按维度（Agent模板/门店/日期）聚合 Session 的 Token 消耗和成本数据。
金额单位：分（整数），遵循 CLAUDE.md 规范。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.session_run import SessionRun

logger = structlog.get_logger()


class SessionCostService:
    """Session 成本统计服务"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_cost_summary(
        self,
        tenant_id: str,
        *,
        store_id: uuid.UUID | None = None,
        agent_template_name: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> dict:
        """按维度聚合成本统计。

        返回:
            {
                total_sessions, total_tokens, total_cost_fen,
                avg_tokens_per_session, avg_cost_per_session,
                by_agent: [{agent_template_name, sessions, tokens, cost_fen}, ...],
                by_store: [{store_id, sessions, tokens, cost_fen}, ...],
            }
        """
        tid = uuid.UUID(tenant_id)

        # 基础过滤条件
        base_filters = [
            SessionRun.tenant_id == tid,
            SessionRun.is_deleted.is_(False),
            SessionRun.status == "completed",
        ]
        if store_id is not None:
            base_filters.append(SessionRun.store_id == store_id)
        if agent_template_name is not None:
            base_filters.append(SessionRun.agent_template_name == agent_template_name)
        if start_date is not None:
            base_filters.append(SessionRun.created_at >= start_date)
        if end_date is not None:
            base_filters.append(SessionRun.created_at <= end_date)

        # 总计
        total_stmt = select(
            func.count(SessionRun.id).label("total_sessions"),
            func.coalesce(func.sum(SessionRun.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(SessionRun.total_cost_fen), 0).label("total_cost_fen"),
        ).where(*base_filters)
        total_result = await self.db.execute(total_stmt)
        total_row = total_result.one()

        total_sessions: int = total_row.total_sessions
        total_tokens: int = total_row.total_tokens
        total_cost_fen: int = total_row.total_cost_fen
        avg_tokens = total_tokens // total_sessions if total_sessions > 0 else 0
        avg_cost = total_cost_fen // total_sessions if total_sessions > 0 else 0

        # 按 Agent 模板聚合
        by_agent_stmt = (
            select(
                SessionRun.agent_template_name,
                func.count(SessionRun.id).label("sessions"),
                func.coalesce(func.sum(SessionRun.total_tokens), 0).label("tokens"),
                func.coalesce(func.sum(SessionRun.total_cost_fen), 0).label("cost_fen"),
            )
            .where(*base_filters)
            .where(SessionRun.agent_template_name.is_not(None))
            .group_by(SessionRun.agent_template_name)
            .order_by(func.sum(SessionRun.total_cost_fen).desc())
        )
        by_agent_result = await self.db.execute(by_agent_stmt)
        by_agent = [
            {
                "agent_template_name": row.agent_template_name,
                "sessions": row.sessions,
                "tokens": row.tokens,
                "cost_fen": row.cost_fen,
            }
            for row in by_agent_result.all()
        ]

        # 按门店聚合
        by_store_stmt = (
            select(
                SessionRun.store_id,
                func.count(SessionRun.id).label("sessions"),
                func.coalesce(func.sum(SessionRun.total_tokens), 0).label("tokens"),
                func.coalesce(func.sum(SessionRun.total_cost_fen), 0).label("cost_fen"),
            )
            .where(*base_filters)
            .where(SessionRun.store_id.is_not(None))
            .group_by(SessionRun.store_id)
            .order_by(func.sum(SessionRun.total_cost_fen).desc())
        )
        by_store_result = await self.db.execute(by_store_stmt)
        by_store = [
            {
                "store_id": str(row.store_id),
                "sessions": row.sessions,
                "tokens": row.tokens,
                "cost_fen": row.cost_fen,
            }
            for row in by_store_result.all()
        ]

        return {
            "total_sessions": total_sessions,
            "total_tokens": total_tokens,
            "total_cost_fen": total_cost_fen,
            "avg_tokens_per_session": avg_tokens,
            "avg_cost_per_session": avg_cost,
            "by_agent": by_agent,
            "by_store": by_store,
        }

    async def get_daily_cost_trend(
        self,
        tenant_id: str,
        *,
        days: int = 30,
        store_id: uuid.UUID | None = None,
    ) -> list[dict]:
        """按天聚合成本趋势。

        返回: [{date, sessions, tokens, cost_fen}, ...]
        """
        tid = uuid.UUID(tenant_id)
        since = datetime.now(timezone.utc) - timedelta(days=days)

        filters = [
            SessionRun.tenant_id == tid,
            SessionRun.is_deleted.is_(False),
            SessionRun.status == "completed",
            SessionRun.created_at >= since,
        ]
        if store_id is not None:
            filters.append(SessionRun.store_id == store_id)

        day_col = cast(SessionRun.created_at, Date).label("day")
        stmt = (
            select(
                day_col,
                func.count(SessionRun.id).label("sessions"),
                func.coalesce(func.sum(SessionRun.total_tokens), 0).label("tokens"),
                func.coalesce(func.sum(SessionRun.total_cost_fen), 0).label("cost_fen"),
            )
            .where(*filters)
            .group_by(day_col)
            .order_by(day_col.asc())
        )
        result = await self.db.execute(stmt)
        return [
            {
                "date": str(row.day),
                "sessions": row.sessions,
                "tokens": row.tokens,
                "cost_fen": row.cost_fen,
            }
            for row in result.all()
        ]
