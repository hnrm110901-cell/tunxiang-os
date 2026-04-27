"""统一任务引擎派单服务（Sprint R1 Track B 实装）

契约：shared.ontology.src.extensions.tasks.Task / TaskType / TaskStatus
事件：shared.events.src.event_types.TaskEventType（DISPATCHED / COMPLETED / ESCALATED）
迁移：shared/db-migrations/versions/v265_tasks.py

能力：
  - dispatch_task   — 派单（幂等键：当日 task_type+assignee+customer+due_at）
  - complete_task   — 关单（记录 outcome + 时间戳）
  - escalate_task   — 手动升级（Agent/店长干预调用）
  - scan_and_escalate — 定时扫描自动升级：
        * +24h 未完成 → 升级到店长（payload.escalation_chain.store_manager_employee_id）
        * +72h 未完成 → 升级到区经（payload.escalation_chain.district_manager_employee_id）
  - cancel_task     — 取消（携带 cancel_reason，不再进入升级扫描）
  - list_tasks      — 按 assignee / status / type / due_before / customer 过滤
  - list_overdue    — 所有超期未完成（跨租户或指定租户）

所有事件通过 ``asyncio.create_task(emit_event(...))`` 旁路写入，不阻塞主业务（CLAUDE.md §15）。

Tier 1 标准（CLAUDE.md §17）：
  - P99 延迟要求由 PG 迁移 + 合适索引保障；本服务不做额外网络 I/O
  - 租户隔离由仓库层 tenant_id 过滤 + v265 RLS 策略双保险
  - 幂等派单由 DB 唯一索引（v270）+ 内存仓库去重共同兜底

并发模型（独立验证 P1-1 修复，2026-04-23）：
  早期版本使用 ``_locks: dict[tenant_id, asyncio.Lock]`` 按租户串行化
  「幂等查询 + INSERT」两步。200 桌并发结账派 dining_followup 时，
  该大锁把派单退化为单线程，P99 必然破门槛。

  现方案：
    - PG 生产路径：依赖 v270 唯一部分索引（tenant_id, task_type, assignee,
      COALESCE(customer_id, ZERO_UUID), DATE(due_at)) WHERE status IN
      ('pending','completed','escalated')，``INSERT ... ON CONFLICT DO NOTHING
      RETURNING *``；冲突落空后 SELECT 出既有任务。
    - 内存仓库路径：单事件循环内，``find_by_idempotency_key`` 与 ``create``
      之间没有真正的并发写入，原子性已由 asyncio 合作调度保证。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

import structlog
from repositories.task_repo import InMemoryTaskRepository, TaskQuery, TaskRepository

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import TaskEventType
from shared.ontology.src.extensions.tasks import Task, TaskStatus, TaskType

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────────────────────────────

#: 升级阈值 — 超过 due_at 的小时数
ESCALATION_HOURS_STORE_MANAGER = 24
ESCALATION_HOURS_DISTRICT_MANAGER = 72

#: payload 中升级链路键名
ESCALATION_CHAIN_KEY = "escalation_chain"
ESCALATION_STORE_MANAGER_KEY = "store_manager_employee_id"
ESCALATION_DISTRICT_MANAGER_KEY = "district_manager_employee_id"

#: 服务名（事件 source_service）
SOURCE_SERVICE = "tx-org"


# ──────────────────────────────────────────────────────────────────────
# Service
# ──────────────────────────────────────────────────────────────────────


class TaskServiceError(Exception):
    """任务服务业务异常基类。"""


class TaskNotFound(TaskServiceError):
    """任务不存在或租户越权访问。"""


class TaskTerminalStateError(TaskServiceError):
    """任务已处于终态（completed/cancelled），不允许继续操作。"""


class EscalationChainMissing(TaskServiceError):
    """升级所需的链路信息缺失（payload.escalation_chain 为空或无对应层级）。"""


class CancelReasonRequired(TaskServiceError):
    """取消任务需提供 cancel_reason（长度 1~200）。"""


@dataclass
class TaskDispatchService:
    """统一任务引擎服务。

    repo 通常为 ``PgTaskRepository``（生产）或 ``InMemoryTaskRepository``（测试）。
    """

    repo: TaskRepository = field(default_factory=InMemoryTaskRepository)

    # ── 内部工具 ────────────────────────────────────────────────────

    def _utcnow(self) -> datetime:
        return datetime.now(timezone.utc)

    # ── 派单 ────────────────────────────────────────────────────────

    async def dispatch_task(
        self,
        *,
        task_type: TaskType,
        assignee_employee_id: UUID,
        customer_id: Optional[UUID],
        due_at: datetime,
        payload: dict[str, Any],
        tenant_id: UUID,
        store_id: Optional[UUID] = None,
        source_event_id: Optional[UUID] = None,
    ) -> Task:
        """派发一个任务（幂等）。

        幂等键 = (tenant_id, task_type, assignee_employee_id, customer_id, DATE(due_at))。
        命中幂等键时直接返回已存在的任务，不重复派单、不重复发事件。

        Args:
            task_type:            10 类任务枚举
            assignee_employee_id: 派单对象（销售/店长/服务员）
            customer_id:          目标客户（可空，如临时任务）
            due_at:               截止时间（timezone-aware 强烈建议）
            payload:              任务上下文，典型包含 escalation_chain
            tenant_id:            租户 UUID
            store_id:             门店（集团级任务可空）
            source_event_id:      因果链父事件

        Returns:
            新建或已存在的 Task 对象。
        """
        # 幂等判定由仓库层兜底：
        #   PG：v270 唯一部分索引 + INSERT ... ON CONFLICT DO NOTHING
        #   内存：create 前 find_by_idempotency_key 仍然有效（单事件循环原子）
        now = self._utcnow()
        candidate = Task(
            task_id=uuid4(),
            tenant_id=tenant_id,
            store_id=store_id,
            task_type=task_type,
            assignee_employee_id=assignee_employee_id,
            customer_id=customer_id,
            due_at=due_at,
            status=TaskStatus.PENDING,
            source_event_id=source_event_id,
            payload=payload or {},
            dispatched_at=now,
            created_at=now,
            updated_at=now,
        )
        persisted = await self.repo.create(candidate)
        idempotent_hit = persisted.task_id != candidate.task_id
        if idempotent_hit:
            logger.info(
                "task_dispatch_idempotent_hit",
                task_id=str(persisted.task_id),
                task_type=task_type.value,
                tenant_id=str(tenant_id),
            )
            return persisted

        # 事件旁路（非阻塞 create_task）
        asyncio.create_task(
            emit_event(
                event_type=TaskEventType.DISPATCHED,
                tenant_id=tenant_id,
                stream_id=str(persisted.task_id),
                payload={
                    "task_type": task_type.value,
                    "assignee_employee_id": str(assignee_employee_id),
                    "due_at": due_at.isoformat(),
                    "customer_id": str(customer_id) if customer_id else None,
                    "store_id": str(store_id) if store_id else None,
                    "source_event_id": str(source_event_id) if source_event_id else None,
                },
                store_id=store_id,
                source_service=SOURCE_SERVICE,
                causation_id=source_event_id,
            )
        )
        logger.info(
            "task_dispatched",
            task_id=str(persisted.task_id),
            task_type=task_type.value,
            tenant_id=str(tenant_id),
            assignee=str(assignee_employee_id),
            due_at=due_at.isoformat(),
        )
        return persisted

    # ── 完成 ────────────────────────────────────────────────────────

    async def complete_task(
        self,
        *,
        task_id: UUID,
        outcome_code: Optional[str],
        notes: Optional[str],
        operator_id: UUID,
        tenant_id: UUID,
    ) -> Task:
        """标记任务完成。

        Args:
            task_id:       目标任务
            outcome_code:  业务结果码（contacted / no_answer / converted 等）
            notes:         自由文本（可空）
            operator_id:   操作员（审计用，也写入 payload.operator_id）
            tenant_id:     租户

        Raises:
            TaskNotFound: 任务不存在或跨租户
            TaskTerminalStateError: 任务已 completed/cancelled
        """
        task = await self._require_task(task_id, tenant_id)
        if task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
            raise TaskTerminalStateError(
                f"task {task_id} already in terminal state {task.status.value}"
            )

        now = self._utcnow()
        updated_payload = {
            **task.payload,
            "last_outcome_code": outcome_code,
            "last_notes": notes,
            "completed_by_employee_id": str(operator_id),
        }
        updated = task.model_copy(
            update={
                "status": TaskStatus.COMPLETED,
                "completed_at": now,
                "updated_at": now,
                "payload": updated_payload,
            }
        )
        await self.repo.update(updated)

        asyncio.create_task(
            emit_event(
                event_type=TaskEventType.COMPLETED,
                tenant_id=tenant_id,
                stream_id=str(task_id),
                payload={
                    "completed_at": now.isoformat(),
                    "outcome_code": outcome_code,
                    "notes": notes,
                    "operator_id": str(operator_id),
                },
                source_service=SOURCE_SERVICE,
            )
        )
        logger.info(
            "task_completed",
            task_id=str(task_id),
            outcome_code=outcome_code,
            tenant_id=str(tenant_id),
        )
        return updated

    # ── 升级（手动） ────────────────────────────────────────────────

    async def escalate_task(
        self,
        *,
        task_id: UUID,
        escalated_to_employee_id: UUID,
        reason: str,
        tenant_id: UUID,
        escalation_level: str = "manual",
    ) -> Task:
        """手动升级：Agent 或人工调用。"""
        task = await self._require_task(task_id, tenant_id)
        if task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
            raise TaskTerminalStateError(
                f"task {task_id} already in terminal state {task.status.value}"
            )

        now = self._utcnow()
        updated = task.model_copy(
            update={
                "status": TaskStatus.ESCALATED,
                "escalated_to_employee_id": escalated_to_employee_id,
                "escalated_at": now,
                "updated_at": now,
                "payload": {**task.payload, "last_escalation_reason": reason},
            }
        )
        await self.repo.update(updated)

        asyncio.create_task(
            emit_event(
                event_type=TaskEventType.ESCALATED,
                tenant_id=tenant_id,
                stream_id=str(task_id),
                payload={
                    "escalated_to_employee_id": str(escalated_to_employee_id),
                    "escalated_at": now.isoformat(),
                    "escalation_level": escalation_level,
                    "reason": reason,
                },
                source_service=SOURCE_SERVICE,
            )
        )
        logger.info(
            "task_escalated",
            task_id=str(task_id),
            level=escalation_level,
            to=str(escalated_to_employee_id),
        )
        return updated

    # ── 升级（自动扫描） ────────────────────────────────────────────

    async def scan_and_escalate(
        self,
        *,
        tenant_id: Optional[UUID] = None,
        now: Optional[datetime] = None,
    ) -> list[Task]:
        """扫描超期未完成任务并按规则升级。

        规则：
          * due_at 已过 ≥ 72h 且尚未升级到区经 → 升级到区经
          * due_at 已过 ≥ 24h 且尚未升级到店长 → 升级到店长

        升级目标从 ``payload.escalation_chain`` 读取；缺失对应层级时跳过并记录 warning。
        已经是 ``escalated`` 的任务若尚未达到下一级门槛，也不会重复升级。
        幂等性保障：处于 ``TaskStatus.ESCALATED`` 的任务仅在满足更高级别阈值时才再次升级。
        """
        ref_now = now or self._utcnow()
        candidates = await self.repo.query_overdue_pending(now=ref_now, tenant_id=tenant_id)
        # 补充 "已升店长、尚未升区经" 的场景：扩展查询
        if tenant_id is not None:
            also_escalated = await self.repo.query(
                TaskQuery(tenant_id=tenant_id, status=TaskStatus.ESCALATED)
            )
            candidates.extend(
                t for t in also_escalated if t.due_at <= ref_now
            )

        escalated_out: list[Task] = []
        for task in candidates:
            try:
                updated = await self._maybe_escalate_by_age(task, ref_now)
            except EscalationChainMissing as exc:
                logger.warning(
                    "task_escalation_skipped_missing_chain",
                    task_id=str(task.task_id),
                    tenant_id=str(task.tenant_id),
                    error=str(exc),
                )
                continue
            if updated is not None:
                escalated_out.append(updated)
        return escalated_out

    async def _maybe_escalate_by_age(self, task: Task, now: datetime) -> Optional[Task]:
        """根据 (now - due_at) 决定是否升级到店长或区经。

        返回 None 表示无需升级（尚未超阈值或链路已走完）。
        """
        if task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
            return None

        age = now - task.due_at
        chain = task.payload.get(ESCALATION_CHAIN_KEY) or {}
        store_mgr = chain.get(ESCALATION_STORE_MANAGER_KEY)
        district_mgr = chain.get(ESCALATION_DISTRICT_MANAGER_KEY)

        target_level: Optional[str] = None
        target_employee: Optional[str] = None

        if age >= timedelta(hours=ESCALATION_HOURS_DISTRICT_MANAGER) and district_mgr:
            target_level = "district_manager"
            target_employee = district_mgr
        elif age >= timedelta(hours=ESCALATION_HOURS_STORE_MANAGER) and store_mgr:
            target_level = "store_manager"
            target_employee = store_mgr
        else:
            # 仍未达到任何阈值（可能 store_mgr 缺失但尚未 72h）
            if age >= timedelta(hours=ESCALATION_HOURS_STORE_MANAGER) and not store_mgr and not district_mgr:
                raise EscalationChainMissing(
                    "escalation_chain missing both store_manager and district_manager"
                )
            return None

        # 幂等：已升级到该对象则跳过
        if task.escalated_to_employee_id is not None and str(task.escalated_to_employee_id) == target_employee:
            return None

        return await self.escalate_task(
            task_id=task.task_id,
            escalated_to_employee_id=UUID(target_employee),
            reason=f"overdue_{target_level}",
            tenant_id=task.tenant_id,
            escalation_level=target_level,
        )

    # ── 取消 ────────────────────────────────────────────────────────

    async def cancel_task(
        self,
        *,
        task_id: UUID,
        reason: str,
        tenant_id: UUID,
    ) -> Task:
        """取消任务（需 cancel_reason，1~200 字）。"""
        if not reason or not reason.strip():
            raise CancelReasonRequired("cancel_reason must not be empty")
        if len(reason) > 200:
            raise CancelReasonRequired("cancel_reason length must be <= 200")

        task = await self._require_task(task_id, tenant_id)
        if task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
            raise TaskTerminalStateError(
                f"task {task_id} already in terminal state {task.status.value}"
            )

        now = self._utcnow()
        updated = task.model_copy(
            update={
                "status": TaskStatus.CANCELLED,
                "cancel_reason": reason,
                "updated_at": now,
            }
        )
        await self.repo.update(updated)
        logger.info("task_cancelled", task_id=str(task_id), reason=reason)
        return updated

    # ── 查询 ────────────────────────────────────────────────────────

    async def list_tasks(
        self,
        *,
        tenant_id: UUID,
        assignee_employee_id: Optional[UUID] = None,
        status: Optional[TaskStatus] = None,
        task_type: Optional[TaskType] = None,
        due_before: Optional[datetime] = None,
        customer_id: Optional[UUID] = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[Task]:
        """按多维过滤查询任务清单（统一入口）。"""
        return await self.repo.query(
            TaskQuery(
                tenant_id=tenant_id,
                assignee_employee_id=assignee_employee_id,
                status=status,
                task_type=task_type,
                due_before=due_before,
                customer_id=customer_id,
                limit=limit,
                offset=offset,
            )
        )

    async def list_overdue(
        self,
        *,
        tenant_id: Optional[UUID] = None,
        now: Optional[datetime] = None,
    ) -> list[Task]:
        """查询所有超期未完成（包含 PENDING，不含 ESCALATED/COMPLETED/CANCELLED）。"""
        return await self.repo.query_overdue_pending(now=now or self._utcnow(), tenant_id=tenant_id)

    async def get_task(self, *, task_id: UUID, tenant_id: UUID) -> Task:
        """按 ID 查询单任务（找不到抛 ``TaskNotFound``）。"""
        return await self._require_task(task_id, tenant_id)

    # ── 内部 ────────────────────────────────────────────────────────

    async def _require_task(self, task_id: UUID, tenant_id: UUID) -> Task:
        task = await self.repo.get(task_id, tenant_id)
        if task is None:
            raise TaskNotFound(f"task {task_id} not found under tenant {tenant_id}")
        return task


__all__ = [
    "TaskDispatchService",
    "TaskServiceError",
    "TaskNotFound",
    "TaskTerminalStateError",
    "EscalationChainMissing",
    "CancelReasonRequired",
    "ESCALATION_HOURS_STORE_MANAGER",
    "ESCALATION_HOURS_DISTRICT_MANAGER",
    "SOURCE_SERVICE",
]
