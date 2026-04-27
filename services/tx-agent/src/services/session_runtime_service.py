"""SessionRuntimeService — Session 运行实例管理

为 Agent 编排任务提供持久化的运行实例管理，包括创建/启动/暂停/恢复/完成/失败/取消。
状态机：created → running → completed/failed
                  running → paused → running（恢复）
         created/running/paused → cancelled
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.session_checkpoint import SessionCheckpoint
from ..models.session_event import SessionEvent
from ..models.session_run import SessionRun

logger = structlog.get_logger()

# 合法的状态转换映射
_VALID_TRANSITIONS: dict[str, set[str]] = {
    "created": {"running", "cancelled"},
    "running": {"paused", "completed", "failed", "cancelled"},
    "paused": {"running", "cancelled"},
    # 终态不可再转换
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}


class SessionStateError(ValueError):
    """Session 状态转换错误"""


class SessionNotFoundError(ValueError):
    """Session 不存在"""


class SessionRuntimeService:
    """Session 运行实例管理服务"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ─────────────────────────────────────────────────────────────────────────
    # 内部辅助
    # ─────────────────────────────────────────────────────────────────────────

    async def _get_session_or_raise(self, tenant_id: str, session_id: uuid.UUID) -> SessionRun:
        """获取 SessionRun，不存在时抛出 SessionNotFoundError。"""
        stmt = select(SessionRun).where(
            SessionRun.id == session_id,
            SessionRun.tenant_id == uuid.UUID(tenant_id),
            SessionRun.is_deleted.is_(False),
        )
        result = await self.db.execute(stmt)
        session_run = result.scalar_one_or_none()
        if session_run is None:
            raise SessionNotFoundError(f"Session {session_id} not found for tenant {tenant_id}")
        return session_run

    def _assert_transition(self, current: str, target: str) -> None:
        """校验状态转换合法性。"""
        allowed = _VALID_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise SessionStateError(
                f"Cannot transition from '{current}' to '{target}'. "
                f"Allowed transitions: {allowed or 'none (terminal state)'}"
            )

    @staticmethod
    def _generate_session_id() -> str:
        """生成可读的 session_id: SR-{YYYYMMDD}-{short_uuid}"""
        date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
        short_id = uuid.uuid4().hex[:8]
        return f"SR-{date_part}-{short_id}"

    async def _next_sequence_no(self, session_id: uuid.UUID) -> int:
        """获取下一个事件序号。"""
        stmt = select(func.coalesce(func.max(SessionEvent.sequence_no), 0)).where(SessionEvent.session_id == session_id)
        result = await self.db.execute(stmt)
        current_max: int = result.scalar_one()
        return current_max + 1

    # ─────────────────────────────────────────────────────────────────────────
    # 生命周期管理
    # ─────────────────────────────────────────────────────────────────────────

    async def create_session(
        self,
        tenant_id: str,
        *,
        agent_template_name: str | None = None,
        store_id: uuid.UUID | None = None,
        trigger_type: str,
        trigger_data: dict | None = None,
    ) -> SessionRun:
        """创建新的 Session 运行实例。

        生成可读的 session_id: "SR-{YYYYMMDD}-{short_uuid}"
        初始 status = "created"
        """
        session_run = SessionRun(
            tenant_id=uuid.UUID(tenant_id),
            session_id=self._generate_session_id(),
            agent_template_name=agent_template_name,
            store_id=store_id,
            trigger_type=trigger_type,
            trigger_data=trigger_data,
            status="created",
            total_steps=0,
            completed_steps=0,
            failed_steps=0,
            total_tokens=0,
            total_cost_fen=0,
        )
        self.db.add(session_run)
        await self.db.flush()

        logger.info(
            "session_created",
            session_id=session_run.session_id,
            tenant_id=tenant_id,
            trigger_type=trigger_type,
            agent_template_name=agent_template_name,
        )
        return session_run

    async def start_session(self, tenant_id: str, session_id: uuid.UUID) -> SessionRun:
        """启动 Session（created → running）。设置 started_at。"""
        session_run = await self._get_session_or_raise(tenant_id, session_id)
        self._assert_transition(session_run.status, "running")

        session_run.status = "running"
        session_run.started_at = datetime.now(timezone.utc)
        await self.db.flush()

        logger.info(
            "session_started",
            session_id=session_run.session_id,
            tenant_id=tenant_id,
        )
        return session_run

    async def pause_session(
        self,
        tenant_id: str,
        session_id: uuid.UUID,
        *,
        step_id: str,
        agent_id: str | None = None,
        reason: str,
        reason_detail: str | None = None,
        checkpoint_data: dict | None = None,
        pending_action: dict | None = None,
    ) -> SessionCheckpoint:
        """暂停 Session（running → paused）。创建 SessionCheckpoint 记录。"""
        session_run = await self._get_session_or_raise(tenant_id, session_id)
        self._assert_transition(session_run.status, "paused")

        session_run.status = "paused"

        checkpoint = SessionCheckpoint(
            tenant_id=uuid.UUID(tenant_id),
            session_id=session_run.id,
            step_id=step_id,
            agent_id=agent_id,
            reason=reason,
            reason_detail=reason_detail,
            checkpoint_data=checkpoint_data,
            pending_action=pending_action,
        )
        self.db.add(checkpoint)
        await self.db.flush()

        logger.info(
            "session_paused",
            session_id=session_run.session_id,
            tenant_id=tenant_id,
            reason=reason,
            checkpoint_id=str(checkpoint.id),
        )
        return checkpoint

    async def resume_session(
        self,
        tenant_id: str,
        session_id: uuid.UUID,
        checkpoint_id: uuid.UUID,
        *,
        resolution: str,
        resolved_by: str,
        comment: str | None = None,
    ) -> SessionRun:
        """恢复 Session（paused → running）。

        更新 SessionCheckpoint 的 resolution/resolved_at/resolved_comment。
        更新 SessionRun 的 status → running。
        """
        session_run = await self._get_session_or_raise(tenant_id, session_id)
        self._assert_transition(session_run.status, "running")

        # 更新 checkpoint
        stmt = select(SessionCheckpoint).where(
            SessionCheckpoint.id == checkpoint_id,
            SessionCheckpoint.session_id == session_run.id,
            SessionCheckpoint.tenant_id == uuid.UUID(tenant_id),
        )
        result = await self.db.execute(stmt)
        checkpoint = result.scalar_one_or_none()
        if checkpoint is None:
            raise SessionNotFoundError(f"Checkpoint {checkpoint_id} not found for session {session_id}")

        now = datetime.now(timezone.utc)
        checkpoint.resolution = resolution
        checkpoint.resolved_by = resolved_by
        checkpoint.resolved_at = now
        checkpoint.resolved_comment = comment
        checkpoint.resumed_at = now

        session_run.status = "running"
        await self.db.flush()

        logger.info(
            "session_resumed",
            session_id=session_run.session_id,
            tenant_id=tenant_id,
            checkpoint_id=str(checkpoint_id),
            resolution=resolution,
        )
        return session_run

    async def complete_session(
        self,
        tenant_id: str,
        session_id: uuid.UUID,
        *,
        result_json: dict | None = None,
        total_tokens: int = 0,
        total_cost_fen: int = 0,
    ) -> SessionRun:
        """完成 Session（running → completed）。

        设置 finished_at, result_json, total_tokens, total_cost_fen。
        """
        session_run = await self._get_session_or_raise(tenant_id, session_id)
        self._assert_transition(session_run.status, "completed")

        session_run.status = "completed"
        session_run.finished_at = datetime.now(timezone.utc)
        session_run.result_json = result_json
        session_run.total_tokens = total_tokens
        session_run.total_cost_fen = total_cost_fen
        await self.db.flush()

        logger.info(
            "session_completed",
            session_id=session_run.session_id,
            tenant_id=tenant_id,
            total_tokens=total_tokens,
            total_cost_fen=total_cost_fen,
        )
        return session_run

    async def fail_session(
        self,
        tenant_id: str,
        session_id: uuid.UUID,
        *,
        error_message: str,
    ) -> SessionRun:
        """标记 Session 失败（running → failed）。"""
        session_run = await self._get_session_or_raise(tenant_id, session_id)
        self._assert_transition(session_run.status, "failed")

        session_run.status = "failed"
        session_run.finished_at = datetime.now(timezone.utc)
        session_run.error_message = error_message
        await self.db.flush()

        logger.warning(
            "session_failed",
            session_id=session_run.session_id,
            tenant_id=tenant_id,
            error_message=error_message,
        )
        return session_run

    async def cancel_session(
        self,
        tenant_id: str,
        session_id: uuid.UUID,
    ) -> SessionRun:
        """取消 Session（created/running/paused → cancelled）。"""
        session_run = await self._get_session_or_raise(tenant_id, session_id)
        self._assert_transition(session_run.status, "cancelled")

        session_run.status = "cancelled"
        session_run.finished_at = datetime.now(timezone.utc)
        await self.db.flush()

        logger.info(
            "session_cancelled",
            session_id=session_run.session_id,
            tenant_id=tenant_id,
        )
        return session_run

    # ─────────────────────────────────────────────────────────────────────────
    # 事件记录
    # ─────────────────────────────────────────────────────────────────────────

    async def record_event(
        self,
        tenant_id: str,
        session_id: uuid.UUID,
        *,
        event_type: str,
        step_id: str | None = None,
        agent_id: str | None = None,
        action: str | None = None,
        input_json: dict | None = None,
        output_json: dict | None = None,
        reasoning: str | None = None,
        tokens_used: int = 0,
        duration_ms: int = 0,
        inference_layer: str | None = None,
    ) -> SessionEvent:
        """记录 Session 事件。自动递增 sequence_no。"""
        # 校验 session 存在
        await self._get_session_or_raise(tenant_id, session_id)

        seq_no = await self._next_sequence_no(session_id)

        event = SessionEvent(
            tenant_id=uuid.UUID(tenant_id),
            session_id=session_id,
            sequence_no=seq_no,
            event_type=event_type,
            step_id=step_id,
            agent_id=agent_id,
            action=action,
            input_json=input_json,
            output_json=output_json,
            reasoning=reasoning,
            tokens_used=tokens_used,
            duration_ms=duration_ms,
            inference_layer=inference_layer,
        )
        self.db.add(event)
        await self.db.flush()

        logger.debug(
            "session_event_recorded",
            session_id=str(session_id),
            sequence_no=seq_no,
            event_type=event_type,
        )
        return event

    # ─────────────────────────────────────────────────────────────────────────
    # 查询
    # ─────────────────────────────────────────────────────────────────────────

    async def get_session(self, tenant_id: str, session_id: uuid.UUID) -> SessionRun | None:
        """获取 Session 详情。"""
        stmt = select(SessionRun).where(
            SessionRun.id == session_id,
            SessionRun.tenant_id == uuid.UUID(tenant_id),
            SessionRun.is_deleted.is_(False),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_sessions(
        self,
        tenant_id: str,
        *,
        store_id: uuid.UUID | None = None,
        status: str | None = None,
        agent_template_name: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[SessionRun], int]:
        """列出 Sessions（分页+过滤）。"""
        base = select(SessionRun).where(
            SessionRun.tenant_id == uuid.UUID(tenant_id),
            SessionRun.is_deleted.is_(False),
        )

        if store_id is not None:
            base = base.where(SessionRun.store_id == store_id)
        if status is not None:
            base = base.where(SessionRun.status == status)
        if agent_template_name is not None:
            base = base.where(SessionRun.agent_template_name == agent_template_name)

        # 总数
        count_stmt = select(func.count()).select_from(base.subquery())
        total_result = await self.db.execute(count_stmt)
        total: int = total_result.scalar_one()

        # 分页数据
        offset = (page - 1) * size
        data_stmt = base.order_by(SessionRun.created_at.desc()).offset(offset).limit(size)
        data_result = await self.db.execute(data_stmt)
        items = list(data_result.scalars().all())

        return items, total

    async def get_session_timeline(
        self,
        tenant_id: str,
        session_id: uuid.UUID,
    ) -> list[SessionEvent]:
        """获取 Session 的完整事件时间线（按 sequence_no 排序）。"""
        # 校验 session 存在
        await self._get_session_or_raise(tenant_id, session_id)

        stmt = (
            select(SessionEvent)
            .where(
                SessionEvent.session_id == session_id,
                SessionEvent.tenant_id == uuid.UUID(tenant_id),
                SessionEvent.is_deleted.is_(False),
            )
            .order_by(SessionEvent.sequence_no.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_session_checkpoints(
        self,
        tenant_id: str,
        session_id: uuid.UUID,
    ) -> list[SessionCheckpoint]:
        """获取 Session 的所有 checkpoint。"""
        # 校验 session 存在
        await self._get_session_or_raise(tenant_id, session_id)

        stmt = (
            select(SessionCheckpoint)
            .where(
                SessionCheckpoint.session_id == session_id,
                SessionCheckpoint.tenant_id == uuid.UUID(tenant_id),
                SessionCheckpoint.is_deleted.is_(False),
            )
            .order_by(SessionCheckpoint.created_at.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update_step_counts(
        self,
        tenant_id: str,
        session_id: uuid.UUID,
        *,
        total_steps: int | None = None,
        completed_steps: int | None = None,
        failed_steps: int | None = None,
    ) -> None:
        """更新步骤计数。"""
        session_run = await self._get_session_or_raise(tenant_id, session_id)

        if total_steps is not None:
            session_run.total_steps = total_steps
        if completed_steps is not None:
            session_run.completed_steps = completed_steps
        if failed_steps is not None:
            session_run.failed_steps = failed_steps

        await self.db.flush()

        logger.debug(
            "session_step_counts_updated",
            session_id=session_run.session_id,
            total_steps=session_run.total_steps,
            completed_steps=session_run.completed_steps,
            failed_steps=session_run.failed_steps,
        )
