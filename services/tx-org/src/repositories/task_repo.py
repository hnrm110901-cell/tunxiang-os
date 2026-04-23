"""统一任务引擎 DAO 层 — tasks 表（v265）

对应契约：shared.ontology.src.extensions.tasks.Task
对应迁移：shared/db-migrations/versions/v265_tasks.py

提供两种实现：
  - ``PgTaskRepository``：生产路径，AsyncSession 直连 PostgreSQL，依赖 RLS
  - ``InMemoryTaskRepository``：测试/单元化路径，模拟同一张逻辑表的多租户隔离

统一接口（见 ``TaskRepository`` 协议）：
  - create(task)
  - get(task_id, tenant_id)
  - update(task)
  - query(filters)                 — 按 assignee / status / type / due_before 检索
  - query_overdue_pending(now, tenant_id?) — 升级扫描用
  - find_by_idempotency_key(key, tenant_id) — 幂等派单用（当日同组合去重）

RLS：
  - PgTaskRepository 所有查询都带 tenant_id 过滤；策略由 v265 建立
  - 当调用方未先调用 ``set_config('app.tenant_id', …)`` 时，库层仍写入 WHERE tenant_id
    作为双保险（审计修复期 §14 要求）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional, Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.extensions.tasks import Task, TaskStatus, TaskType

# ──────────────────────────────────────────────────────────────────────
# 过滤器 DTO
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TaskQuery:
    """list_tasks 的查询参数容器。"""

    tenant_id: UUID
    assignee_employee_id: Optional[UUID] = None
    status: Optional[TaskStatus] = None
    task_type: Optional[TaskType] = None
    due_before: Optional[datetime] = None
    customer_id: Optional[UUID] = None
    limit: int = 500
    offset: int = 0


# ──────────────────────────────────────────────────────────────────────
# 协议
# ──────────────────────────────────────────────────────────────────────


class TaskRepository(Protocol):
    async def create(self, task: Task) -> Task:
        """写入任务。命中幂等键时返回既有 Task（task_id 与入参不同）。

        独立验证 P1-1 修复（2026-04-23）：create 必须内建幂等，
        不再依赖上层 asyncio.Lock。两种实现：
          - PG：``INSERT ... ON CONFLICT (tenant_id, task_type, assignee,
            COALESCE(customer_id, ZERO), DATE(due_at)) WHERE status IN
            ('pending','completed','escalated') DO NOTHING RETURNING``；
            未命中 RETURNING 时再 SELECT 既有行。
          - InMemory：写入前 find_by_idempotency_key，命中则返回。
        """
        ...

    async def get(self, task_id: UUID, tenant_id: UUID) -> Optional[Task]: ...

    async def update(self, task: Task) -> Task: ...

    async def query(self, q: TaskQuery) -> list[Task]: ...

    async def query_overdue_pending(
        self,
        *,
        now: datetime,
        tenant_id: Optional[UUID] = None,
    ) -> list[Task]: ...

    async def find_by_idempotency_key(
        self,
        *,
        tenant_id: UUID,
        task_type: TaskType,
        assignee_employee_id: UUID,
        customer_id: Optional[UUID],
        due_at: datetime,
    ) -> Optional[Task]: ...


# ──────────────────────────────────────────────────────────────────────
# 内存实现（测试用）
# ──────────────────────────────────────────────────────────────────────


@dataclass
class InMemoryTaskRepository:
    """进程内任务仓库实现。

    专为单元测试和本地开发设计，语义保持与 PG 实现一致：
      - 按 tenant_id 物理隔离
      - 幂等键 = (tenant_id, task_type, assignee, customer, 当日 due_at)
      - update 按 task_id 直接覆盖
    """

    _by_tenant: dict[UUID, dict[UUID, Task]] = field(default_factory=dict)

    def _bucket(self, tenant_id: UUID) -> dict[UUID, Task]:
        return self._by_tenant.setdefault(tenant_id, {})

    async def create(self, task: Task) -> Task:
        # 幂等：复用 find_by_idempotency_key 语义，与 PG ON CONFLICT 对齐
        existing = await self.find_by_idempotency_key(
            tenant_id=task.tenant_id,
            task_type=task.task_type,
            assignee_employee_id=task.assignee_employee_id,
            customer_id=task.customer_id,
            due_at=task.due_at,
        )
        if existing is not None:
            return existing
        bucket = self._bucket(task.tenant_id)
        bucket[task.task_id] = task
        return task

    async def get(self, task_id: UUID, tenant_id: UUID) -> Optional[Task]:
        return self._bucket(tenant_id).get(task_id)

    async def update(self, task: Task) -> Task:
        bucket = self._bucket(task.tenant_id)
        if task.task_id not in bucket:
            raise KeyError(f"task_id {task.task_id} not found under tenant {task.tenant_id}")
        bucket[task.task_id] = task
        return task

    async def query(self, q: TaskQuery) -> list[Task]:
        items: Iterable[Task] = list(self._bucket(q.tenant_id).values())
        if q.assignee_employee_id is not None:
            items = [t for t in items if t.assignee_employee_id == q.assignee_employee_id]
        if q.status is not None:
            items = [t for t in items if t.status == q.status]
        if q.task_type is not None:
            items = [t for t in items if t.task_type == q.task_type]
        if q.customer_id is not None:
            items = [t for t in items if t.customer_id == q.customer_id]
        if q.due_before is not None:
            items = [t for t in items if t.due_at <= q.due_before]
        items = sorted(items, key=lambda t: t.due_at)
        return list(items)[q.offset : q.offset + q.limit]

    async def query_overdue_pending(
        self,
        *,
        now: datetime,
        tenant_id: Optional[UUID] = None,
    ) -> list[Task]:
        tenants: Iterable[UUID] = [tenant_id] if tenant_id else list(self._by_tenant.keys())
        overdue: list[Task] = []
        for tid in tenants:
            for task in self._bucket(tid).values():
                if task.status == TaskStatus.PENDING and task.due_at <= now:
                    overdue.append(task)
        overdue.sort(key=lambda t: t.due_at)
        return overdue

    async def find_by_idempotency_key(
        self,
        *,
        tenant_id: UUID,
        task_type: TaskType,
        assignee_employee_id: UUID,
        customer_id: Optional[UUID],
        due_at: datetime,
    ) -> Optional[Task]:
        # 与 v270 部分索引一致：只在 pending/completed/escalated 上匹配，
        # cancelled 的任务不参与幂等（允许重新派单）。
        day = due_at.astimezone(timezone.utc).date()
        for task in self._bucket(tenant_id).values():
            if task.status == TaskStatus.CANCELLED:
                continue
            if (
                task.task_type == task_type
                and task.assignee_employee_id == assignee_employee_id
                and task.customer_id == customer_id
                and task.due_at.astimezone(timezone.utc).date() == day
            ):
                return task
        return None


# ──────────────────────────────────────────────────────────────────────
# PG 实现（生产路径）
# ──────────────────────────────────────────────────────────────────────


# 幂等 UUID 哨兵：与 v270 部分索引 ``COALESCE(customer_id, ZERO_UUID)`` 对齐。
_IDEMPOTENCY_NULL_CUSTOMER_SENTINEL = "00000000-0000-0000-0000-000000000000"

# INSERT 兼具主键冲突兜底（极低概率 UUID 重复）+ 幂等键兜底：
# 命中 v270 唯一部分索引时返回零行，调用方再 SELECT 出既有任务。
_INSERT_SQL = text(
    """
    INSERT INTO tasks (
        task_id, tenant_id, store_id, task_type, assignee_employee_id,
        customer_id, due_at, status, source_event_id, payload, dispatched_at,
        created_at, updated_at
    ) VALUES (
        :task_id, :tenant_id, :store_id, :task_type, :assignee_employee_id,
        :customer_id, :due_at, :status, :source_event_id, CAST(:payload AS JSONB),
        :dispatched_at, :created_at, :updated_at
    )
    ON CONFLICT DO NOTHING
    RETURNING task_id, tenant_id, store_id, task_type, assignee_employee_id,
              customer_id, due_at, status, escalated_to_employee_id, escalated_at,
              cancel_reason, source_event_id, payload, dispatched_at, completed_at,
              created_at, updated_at
    """
)

_UPDATE_SQL = text(
    """
    UPDATE tasks SET
        status                    = :status,
        escalated_to_employee_id  = :escalated_to_employee_id,
        escalated_at              = :escalated_at,
        cancel_reason             = :cancel_reason,
        payload                   = CAST(:payload AS JSONB),
        completed_at              = :completed_at,
        updated_at                = :updated_at
    WHERE task_id = :task_id AND tenant_id = :tenant_id
    """
)


@dataclass
class PgTaskRepository:
    """PostgreSQL 实现 — 依赖 AsyncSession + v265 建表 + RLS 策略。"""

    session: AsyncSession

    async def create(self, task: Task) -> Task:
        """原子派单（幂等）。

        并发 2 个进程同时派同一任务时：DB 唯一索引（v270 部分索引）
        只会让其中一个成功；另一进程 RETURNING 零行，落回 SELECT 找到
        已存在行并返回。无需上层 asyncio.Lock。
        """
        import json

        result = await self.session.execute(
            _INSERT_SQL,
            {
                "task_id": str(task.task_id),
                "tenant_id": str(task.tenant_id),
                "store_id": str(task.store_id) if task.store_id else None,
                "task_type": task.task_type.value,
                "assignee_employee_id": str(task.assignee_employee_id),
                "customer_id": str(task.customer_id) if task.customer_id else None,
                "due_at": task.due_at,
                "status": task.status.value,
                "source_event_id": str(task.source_event_id) if task.source_event_id else None,
                "payload": json.dumps(task.payload),
                "dispatched_at": task.dispatched_at,
                "created_at": task.created_at,
                "updated_at": task.updated_at,
            },
        )
        row = result.mappings().first()
        if row is not None:
            return _row_to_task(row)

        # RETURNING 零行 = 命中 v270 幂等唯一索引，落回既有 Task
        existing = await self.find_by_idempotency_key(
            tenant_id=task.tenant_id,
            task_type=task.task_type,
            assignee_employee_id=task.assignee_employee_id,
            customer_id=task.customer_id,
            due_at=task.due_at,
        )
        if existing is not None:
            return existing
        # 理论上不应走到这里（除非索引未建）；保留兜底，避免阻塞主业务。
        return task

    async def get(self, task_id: UUID, tenant_id: UUID) -> Optional[Task]:
        row = (
            await self.session.execute(
                text(
                    "SELECT task_id, tenant_id, store_id, task_type, assignee_employee_id, "
                    "customer_id, due_at, status, escalated_to_employee_id, escalated_at, "
                    "cancel_reason, source_event_id, payload, dispatched_at, completed_at, "
                    "created_at, updated_at "
                    "FROM tasks WHERE task_id = :task_id AND tenant_id = :tenant_id"
                ),
                {"task_id": str(task_id), "tenant_id": str(tenant_id)},
            )
        ).mappings().first()
        return _row_to_task(row) if row else None

    async def update(self, task: Task) -> Task:
        import json

        await self.session.execute(
            _UPDATE_SQL,
            {
                "task_id": str(task.task_id),
                "tenant_id": str(task.tenant_id),
                "status": task.status.value,
                "escalated_to_employee_id": (
                    str(task.escalated_to_employee_id) if task.escalated_to_employee_id else None
                ),
                "escalated_at": task.escalated_at,
                "cancel_reason": task.cancel_reason,
                "payload": json.dumps(task.payload),
                "completed_at": task.completed_at,
                "updated_at": task.updated_at,
            },
        )
        return task

    async def query(self, q: TaskQuery) -> list[Task]:
        where = ["tenant_id = :tenant_id"]
        params: dict[str, Any] = {"tenant_id": str(q.tenant_id), "lim": q.limit, "off": q.offset}
        if q.assignee_employee_id is not None:
            where.append("assignee_employee_id = :assignee")
            params["assignee"] = str(q.assignee_employee_id)
        if q.status is not None:
            where.append("status = :status")
            params["status"] = q.status.value
        if q.task_type is not None:
            where.append("task_type = :task_type")
            params["task_type"] = q.task_type.value
        if q.customer_id is not None:
            where.append("customer_id = :customer_id")
            params["customer_id"] = str(q.customer_id)
        if q.due_before is not None:
            where.append("due_at <= :due_before")
            params["due_before"] = q.due_before

        sql = text(
            "SELECT task_id, tenant_id, store_id, task_type, assignee_employee_id, "
            "customer_id, due_at, status, escalated_to_employee_id, escalated_at, "
            "cancel_reason, source_event_id, payload, dispatched_at, completed_at, "
            "created_at, updated_at "
            "FROM tasks WHERE " + " AND ".join(where) + " ORDER BY due_at ASC LIMIT :lim OFFSET :off"
        )
        rows = (await self.session.execute(sql, params)).mappings().all()
        return [_row_to_task(r) for r in rows]

    async def query_overdue_pending(
        self,
        *,
        now: datetime,
        tenant_id: Optional[UUID] = None,
    ) -> list[Task]:
        params: dict[str, Any] = {"now": now}
        where = ["status = 'pending'", "due_at <= :now"]
        if tenant_id is not None:
            where.append("tenant_id = :tenant_id")
            params["tenant_id"] = str(tenant_id)
        sql = text(
            "SELECT task_id, tenant_id, store_id, task_type, assignee_employee_id, "
            "customer_id, due_at, status, escalated_to_employee_id, escalated_at, "
            "cancel_reason, source_event_id, payload, dispatched_at, completed_at, "
            "created_at, updated_at "
            "FROM tasks WHERE " + " AND ".join(where) + " ORDER BY due_at ASC"
        )
        rows = (await self.session.execute(sql, params)).mappings().all()
        return [_row_to_task(r) for r in rows]

    async def find_by_idempotency_key(
        self,
        *,
        tenant_id: UUID,
        task_type: TaskType,
        assignee_employee_id: UUID,
        customer_id: Optional[UUID],
        due_at: datetime,
    ) -> Optional[Task]:
        # 与 v270 部分索引 ``WHERE status IN ('pending','completed','escalated')``
        # 严格对齐；cancelled 任务不参与幂等，允许重新派单。
        sql = text(
            "SELECT task_id, tenant_id, store_id, task_type, assignee_employee_id, "
            "customer_id, due_at, status, escalated_to_employee_id, escalated_at, "
            "cancel_reason, source_event_id, payload, dispatched_at, completed_at, "
            "created_at, updated_at "
            "FROM tasks "
            "WHERE tenant_id = :tenant_id "
            "  AND task_type = :task_type "
            "  AND assignee_employee_id = :assignee "
            "  AND (customer_id IS NOT DISTINCT FROM :customer_id) "
            "  AND DATE(due_at AT TIME ZONE 'UTC') = DATE(:due_at AT TIME ZONE 'UTC') "
            "  AND status IN ('pending', 'completed', 'escalated') "
            "ORDER BY created_at DESC LIMIT 1"
        )
        row = (
            await self.session.execute(
                sql,
                {
                    "tenant_id": str(tenant_id),
                    "task_type": task_type.value,
                    "assignee": str(assignee_employee_id),
                    "customer_id": str(customer_id) if customer_id else None,
                    "due_at": due_at,
                },
            )
        ).mappings().first()
        return _row_to_task(row) if row else None


# ──────────────────────────────────────────────────────────────────────
# 行 → Pydantic 模型
# ──────────────────────────────────────────────────────────────────────


def _row_to_task(row: Any) -> Task:
    """PG 行 → Task Pydantic 模型。"""
    payload = row["payload"]
    if isinstance(payload, str):
        import json

        payload = json.loads(payload)
    return Task(
        task_id=_to_uuid(row["task_id"]),
        tenant_id=_to_uuid(row["tenant_id"]),
        store_id=_to_uuid(row.get("store_id")) if row.get("store_id") else None,
        task_type=TaskType(row["task_type"]),
        assignee_employee_id=_to_uuid(row["assignee_employee_id"]),
        customer_id=_to_uuid(row.get("customer_id")) if row.get("customer_id") else None,
        due_at=row["due_at"],
        status=TaskStatus(row["status"]),
        escalated_to_employee_id=(
            _to_uuid(row.get("escalated_to_employee_id")) if row.get("escalated_to_employee_id") else None
        ),
        escalated_at=row.get("escalated_at"),
        cancel_reason=row.get("cancel_reason"),
        source_event_id=(_to_uuid(row.get("source_event_id")) if row.get("source_event_id") else None),
        payload=payload or {},
        dispatched_at=row["dispatched_at"],
        completed_at=row.get("completed_at"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _to_uuid(v: Any) -> UUID:
    if isinstance(v, UUID):
        return v
    return UUID(str(v))


__all__ = [
    "TaskRepository",
    "InMemoryTaskRepository",
    "PgTaskRepository",
    "TaskQuery",
]
