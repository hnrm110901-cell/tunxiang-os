"""Sprint R1 Track B — TaskEngine Tier 1 测试（TDD 先写）

测试场景（对齐 docs/reservation-r1-contracts.md §5.2 + CLAUDE.md §17/§20）：

  1. test_dispatch_task_writes_event
     — 派单后 tasks 行写入成功 + emit_event 被以 TaskEventType.DISPATCHED 调用
  2. test_complete_task_updates_status_and_event
     — 完成任务：status=completed + completed_at 写入 + task.completed 事件
  3. test_escalate_overdue_24h_raises_to_store_manager
     — due_at + 24h 未完成由扫描升级到店长（escalation_chain payload）
  4. test_escalate_overdue_72h_raises_to_district_manager
     — due_at + 72h 未完成升级到区经
  5. test_idempotent_dispatch_same_payload_dedupes
     — 同日 (task_type, assignee, customer, due_at) 重复派单返回同一任务
  6. test_200_concurrent_dispatch_no_deadlock
     — 200 笔并发派单不死锁（基于内存仓库，检验锁粒度）
  7. test_tenant_isolation_rls
     — 租户 A 列表不能返回租户 B 的任务
  8. test_10_task_types_all_dispatchable
     — TaskType 枚举 10 种均可派单成功
  9. test_cancelled_task_not_escalated
     — status=cancelled 的任务即使超期也不触发升级（契约 §5.2 场景 4）
 10. test_list_tasks_filters
     — 按 assignee / status / type / due_before 过滤

运行模式：
  - 使用内存仓库（InMemoryTaskRepository）替代 DB，专注业务逻辑
  - emit_event 被 monkeypatch 为 AsyncMock，捕获事件参数
  - 测试保持独立性：每个用例新建独立 Service
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

# 路径插入：方便以 services.tx_org.src.* 导入（与 tests/ 同级）
_THIS_DIR = os.path.dirname(__file__)
_SRC_DIR = os.path.join(_THIS_DIR, "..")
_ROOT = os.path.join(_THIS_DIR, "..", "..", "..", "..")
for _p in (_SRC_DIR, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from repositories.task_repo import InMemoryTaskRepository  # noqa: E402
from services.task_dispatch_service import TaskDispatchService  # noqa: E402

from shared.events.src.event_types import TaskEventType  # noqa: E402
from shared.ontology.src.extensions.tasks import TaskStatus, TaskType  # noqa: E402

# ──────────────────────────────────────────────────────────────────────
# anyio 选择 asyncio 后端
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# ──────────────────────────────────────────────────────────────────────
# 公用工厂
# ──────────────────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_service(monkeypatch) -> tuple[TaskDispatchService, AsyncMock, InMemoryTaskRepository]:
    """构造带 mock emit_event 的 Service。"""
    repo = InMemoryTaskRepository()
    emit_mock = AsyncMock(return_value=str(uuid4()))
    # monkeypatch 直接替换 service 模块里引入的 emit_event 名称
    import services.task_dispatch_service as svc_mod

    monkeypatch.setattr(svc_mod, "emit_event", emit_mock)
    service = TaskDispatchService(repo=repo)
    return service, emit_mock, repo


async def _drain_tasks() -> None:
    """等待 asyncio.create_task 调度的副作用任务执行完。"""
    # 让出两次 event loop，保证 create_task 里的协程被驱动
    await asyncio.sleep(0)
    await asyncio.sleep(0)


# ──────────────────────────────────────────────────────────────────────
# 1. 派单写事件
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_dispatch_task_writes_event(monkeypatch):
    service, emit_mock, repo = _make_service(monkeypatch)

    tenant_id = uuid4()
    assignee = uuid4()
    customer_id = uuid4()
    due_at = _utcnow() + timedelta(hours=2)

    task = await service.dispatch_task(
        task_type=TaskType.CONFIRM_ARRIVAL,
        assignee_employee_id=assignee,
        customer_id=customer_id,
        due_at=due_at,
        payload={"reservation_id": str(uuid4())},
        tenant_id=tenant_id,
    )

    assert task.task_id is not None
    assert task.status == TaskStatus.PENDING
    assert task.task_type == TaskType.CONFIRM_ARRIVAL
    assert task.assignee_employee_id == assignee
    assert task.tenant_id == tenant_id

    # 等副作用事件任务执行
    await _drain_tasks()
    assert emit_mock.await_count == 1
    kwargs = emit_mock.await_args.kwargs
    assert kwargs["event_type"] == TaskEventType.DISPATCHED
    assert kwargs["tenant_id"] == tenant_id
    assert kwargs["stream_id"] == str(task.task_id)
    assert kwargs["source_service"] == "tx-org"
    assert kwargs["payload"]["task_type"] == TaskType.CONFIRM_ARRIVAL.value
    assert kwargs["payload"]["assignee_employee_id"] == str(assignee)


# ──────────────────────────────────────────────────────────────────────
# 2. 完成
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_complete_task_updates_status_and_event(monkeypatch):
    service, emit_mock, repo = _make_service(monkeypatch)

    tenant_id = uuid4()
    task = await service.dispatch_task(
        task_type=TaskType.BIRTHDAY,
        assignee_employee_id=uuid4(),
        customer_id=uuid4(),
        due_at=_utcnow() + timedelta(days=1),
        payload={},
        tenant_id=tenant_id,
    )
    await _drain_tasks()
    emit_mock.reset_mock()

    completed = await service.complete_task(
        task_id=task.task_id,
        outcome_code="contacted",
        notes="客户接听并确认",
        operator_id=task.assignee_employee_id,
        tenant_id=tenant_id,
    )

    assert completed.status == TaskStatus.COMPLETED
    assert completed.completed_at is not None

    await _drain_tasks()
    assert emit_mock.await_count == 1
    kwargs = emit_mock.await_args.kwargs
    assert kwargs["event_type"] == TaskEventType.COMPLETED
    assert kwargs["payload"]["outcome_code"] == "contacted"


# ──────────────────────────────────────────────────────────────────────
# 3/4. 升级规则（24h → 店长，72h → 区经）
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_escalate_overdue_24h_raises_to_store_manager(monkeypatch):
    service, emit_mock, repo = _make_service(monkeypatch)

    tenant_id = uuid4()
    store_mgr = uuid4()
    district_mgr = uuid4()
    assignee = uuid4()

    # 任务 25 小时前到期、仍 pending
    due_at = _utcnow() - timedelta(hours=25)
    task = await service.dispatch_task(
        task_type=TaskType.DORMANT_RECALL,
        assignee_employee_id=assignee,
        customer_id=uuid4(),
        due_at=due_at,
        payload={
            "escalation_chain": {
                "store_manager_employee_id": str(store_mgr),
                "district_manager_employee_id": str(district_mgr),
            }
        },
        tenant_id=tenant_id,
    )
    await _drain_tasks()
    emit_mock.reset_mock()

    # 扫描升级
    escalated = await service.scan_and_escalate(tenant_id=tenant_id, now=_utcnow())
    assert len(escalated) == 1
    e = escalated[0]
    assert e.task_id == task.task_id
    assert e.status == TaskStatus.ESCALATED
    assert e.escalated_to_employee_id == store_mgr  # 24h 档升到店长

    await _drain_tasks()
    assert emit_mock.await_count >= 1
    assert emit_mock.await_args.kwargs["event_type"] == TaskEventType.ESCALATED
    assert emit_mock.await_args.kwargs["payload"]["escalation_level"] == "store_manager"


@pytest.mark.anyio
async def test_escalate_overdue_72h_raises_to_district_manager(monkeypatch):
    service, emit_mock, repo = _make_service(monkeypatch)

    tenant_id = uuid4()
    store_mgr = uuid4()
    district_mgr = uuid4()
    assignee = uuid4()

    # 73 小时前到期
    due_at = _utcnow() - timedelta(hours=73)
    task = await service.dispatch_task(
        task_type=TaskType.LEAD_FOLLOW_UP,
        assignee_employee_id=assignee,
        customer_id=uuid4(),
        due_at=due_at,
        payload={
            "escalation_chain": {
                "store_manager_employee_id": str(store_mgr),
                "district_manager_employee_id": str(district_mgr),
            }
        },
        tenant_id=tenant_id,
    )
    await _drain_tasks()

    escalated = await service.scan_and_escalate(tenant_id=tenant_id, now=_utcnow())
    assert len(escalated) == 1
    assert escalated[0].escalated_to_employee_id == district_mgr  # 72h 档升到区经
    assert escalated[0].status == TaskStatus.ESCALATED

    # 幂等：再次扫描不会重复升级
    again = await service.scan_and_escalate(tenant_id=tenant_id, now=_utcnow())
    assert again == []


# ──────────────────────────────────────────────────────────────────────
# 5. 幂等派单
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_idempotent_dispatch_same_payload_dedupes(monkeypatch):
    service, emit_mock, repo = _make_service(monkeypatch)

    tenant_id = uuid4()
    assignee = uuid4()
    customer = uuid4()
    due_at = _utcnow() + timedelta(hours=6)

    kwargs = {
        "task_type": TaskType.NEW_CUSTOMER,
        "assignee_employee_id": assignee,
        "customer_id": customer,
        "due_at": due_at,
        "payload": {"note": "首次派单"},
        "tenant_id": tenant_id,
    }

    t1 = await service.dispatch_task(**kwargs)
    t2 = await service.dispatch_task(**kwargs)

    assert t1.task_id == t2.task_id
    assert len(await service.list_tasks(tenant_id=tenant_id)) == 1

    await _drain_tasks()
    # 第二次派单因为幂等命中，不重复发事件
    assert emit_mock.await_count == 1


# ──────────────────────────────────────────────────────────────────────
# 6. 并发派单无死锁
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_200_concurrent_dispatch_no_deadlock(monkeypatch):
    service, emit_mock, repo = _make_service(monkeypatch)
    tenant_id = uuid4()
    base_due = _utcnow() + timedelta(hours=1)

    async def _one(i: int):
        return await service.dispatch_task(
            task_type=TaskType.DORMANT_RECALL,
            assignee_employee_id=uuid4(),  # 不同员工避免幂等去重
            customer_id=uuid4(),
            due_at=base_due + timedelta(seconds=i),
            payload={"i": i},
            tenant_id=tenant_id,
        )

    results = await asyncio.wait_for(
        asyncio.gather(*[_one(i) for i in range(200)]),
        timeout=10.0,
    )
    assert len(results) == 200
    assert len({t.task_id for t in results}) == 200


# ──────────────────────────────────────────────────────────────────────
# 7. 租户隔离
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_tenant_isolation_rls(monkeypatch):
    service, emit_mock, repo = _make_service(monkeypatch)

    tenant_a = uuid4()
    tenant_b = uuid4()

    await service.dispatch_task(
        task_type=TaskType.BIRTHDAY,
        assignee_employee_id=uuid4(),
        customer_id=uuid4(),
        due_at=_utcnow() + timedelta(hours=1),
        payload={},
        tenant_id=tenant_a,
    )
    await service.dispatch_task(
        task_type=TaskType.BIRTHDAY,
        assignee_employee_id=uuid4(),
        customer_id=uuid4(),
        due_at=_utcnow() + timedelta(hours=1),
        payload={},
        tenant_id=tenant_b,
    )

    a_list = await service.list_tasks(tenant_id=tenant_a)
    b_list = await service.list_tasks(tenant_id=tenant_b)

    assert len(a_list) == 1
    assert len(b_list) == 1
    assert a_list[0].tenant_id == tenant_a
    assert b_list[0].tenant_id == tenant_b


# ──────────────────────────────────────────────────────────────────────
# 8. 10 种类型全可派单
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_10_task_types_all_dispatchable(monkeypatch):
    service, emit_mock, repo = _make_service(monkeypatch)
    tenant_id = uuid4()

    assert len(list(TaskType)) == 10

    for idx, t in enumerate(TaskType):
        task = await service.dispatch_task(
            task_type=t,
            assignee_employee_id=uuid4(),
            customer_id=uuid4(),
            due_at=_utcnow() + timedelta(hours=idx + 1),
            payload={"idx": idx},
            tenant_id=tenant_id,
        )
        assert task.task_type == t
        assert task.status == TaskStatus.PENDING

    all_tasks = await service.list_tasks(tenant_id=tenant_id)
    assert len(all_tasks) == 10


# ──────────────────────────────────────────────────────────────────────
# 9. cancelled 任务不升级（契约 §5.2 场景 4）
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_cancelled_task_not_escalated(monkeypatch):
    service, emit_mock, repo = _make_service(monkeypatch)

    tenant_id = uuid4()
    due_at = _utcnow() - timedelta(hours=50)
    task = await service.dispatch_task(
        task_type=TaskType.ADHOC,
        assignee_employee_id=uuid4(),
        customer_id=uuid4(),
        due_at=due_at,
        payload={"escalation_chain": {"store_manager_employee_id": str(uuid4())}},
        tenant_id=tenant_id,
    )

    # 取消（模拟业务操作：直接更新仓库）
    cancelled = await service.cancel_task(
        task_id=task.task_id,
        reason="客户已电话达成",
        tenant_id=tenant_id,
    )
    assert cancelled.status == TaskStatus.CANCELLED
    assert cancelled.cancel_reason == "客户已电话达成"

    escalated = await service.scan_and_escalate(tenant_id=tenant_id, now=_utcnow())
    assert escalated == []


# ──────────────────────────────────────────────────────────────────────
# 10. list_tasks 过滤
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_list_tasks_filters(monkeypatch):
    service, emit_mock, repo = _make_service(monkeypatch)
    tenant_id = uuid4()
    employee_a = uuid4()
    employee_b = uuid4()
    now = _utcnow()

    t_a_pending = await service.dispatch_task(
        task_type=TaskType.BIRTHDAY,
        assignee_employee_id=employee_a,
        customer_id=uuid4(),
        due_at=now + timedelta(hours=1),
        payload={},
        tenant_id=tenant_id,
    )
    t_a_done = await service.dispatch_task(
        task_type=TaskType.ANNIVERSARY,
        assignee_employee_id=employee_a,
        customer_id=uuid4(),
        due_at=now + timedelta(hours=2),
        payload={},
        tenant_id=tenant_id,
    )
    await service.complete_task(
        task_id=t_a_done.task_id,
        outcome_code="done",
        notes=None,
        operator_id=employee_a,
        tenant_id=tenant_id,
    )
    t_b_pending = await service.dispatch_task(
        task_type=TaskType.BIRTHDAY,
        assignee_employee_id=employee_b,
        customer_id=uuid4(),
        due_at=now + timedelta(hours=3),
        payload={},
        tenant_id=tenant_id,
    )

    by_assignee = await service.list_tasks(tenant_id=tenant_id, assignee_employee_id=employee_a)
    assert {t.task_id for t in by_assignee} == {t_a_pending.task_id, t_a_done.task_id}

    by_status = await service.list_tasks(tenant_id=tenant_id, status=TaskStatus.PENDING)
    assert {t.task_id for t in by_status} == {t_a_pending.task_id, t_b_pending.task_id}

    by_type = await service.list_tasks(tenant_id=tenant_id, task_type=TaskType.BIRTHDAY)
    assert {t.task_id for t in by_type} == {t_a_pending.task_id, t_b_pending.task_id}

    due_before = await service.list_tasks(tenant_id=tenant_id, due_before=now + timedelta(hours=2, minutes=30))
    # 截至 2.5h 之前：t_a_pending (1h) + t_a_done (2h)
    assert {t.task_id for t in due_before} == {t_a_pending.task_id, t_a_done.task_id}


# ──────────────────────────────────────────────────────────────────────
# 11. 独立验证 P1-1：移除 asyncio.Lock 后 200 并发仍正确
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_200_concurrent_dispatch_no_asyncio_lock(monkeypatch):
    """独立验证 P1-1：asyncio.Lock 移除后，200 并发派单依然：
       - 不死锁
       - 产出 200 个不同 task_id（每个都是新派的）
       - 派单服务无 _locks / _lock_for 属性残留
    """
    service, emit_mock, repo = _make_service(monkeypatch)

    # 行为级断言：lock 相关属性已被彻底移除
    assert not hasattr(service, "_locks"), (
        "independent review P1-1: asyncio.Lock 大锁必须删除"
    )
    assert not hasattr(service, "_lock_for"), (
        "independent review P1-1: _lock_for 工具方法必须删除"
    )

    tenant_id = uuid4()
    base_due = _utcnow() + timedelta(hours=1)

    async def _one(i: int):
        return await service.dispatch_task(
            task_type=TaskType.DINING_FOLLOWUP,  # 模拟 200 桌结账后派回访
            assignee_employee_id=uuid4(),  # 不同员工避免幂等去重
            customer_id=uuid4(),
            due_at=base_due + timedelta(seconds=i),
            payload={"table_no": i},
            tenant_id=tenant_id,
        )

    results = await asyncio.wait_for(
        asyncio.gather(*[_one(i) for i in range(200)]),
        timeout=10.0,
    )
    assert len(results) == 200
    assert len({t.task_id for t in results}) == 200, (
        "200 笔派单应产出 200 个不同 task_id，无重复"
    )


@pytest.mark.anyio
async def test_idempotent_dispatch_uses_db_unique_not_lock(monkeypatch):
    """独立验证 P1-1：模拟 2 个进程同时派同一任务，由仓库层兜底幂等，
    不依赖 asyncio.Lock 也不发两次事件。

    对应生产路径：PgTaskRepository 使用 v270 唯一部分索引 + ON CONFLICT
    DO NOTHING RETURNING；内存路径由 find_by_idempotency_key 保证同语义。
    """
    service, emit_mock, repo = _make_service(monkeypatch)

    tenant_id = uuid4()
    assignee = uuid4()
    customer = uuid4()
    due_at = _utcnow() + timedelta(hours=3)

    kwargs = {
        "task_type": TaskType.DORMANT_RECALL,
        "assignee_employee_id": assignee,
        "customer_id": customer,
        "due_at": due_at,
        "payload": {"probe": "concurrent"},
        "tenant_id": tenant_id,
    }

    # 并发两笔同幂等键派单 —— DB 索引兜底应让二者产出同一 task_id
    t1, t2 = await asyncio.gather(
        service.dispatch_task(**kwargs),
        service.dispatch_task(**kwargs),
    )
    assert t1.task_id == t2.task_id, (
        "独立验证 P1-1：同幂等键两次派单必须返回同一 task_id"
    )

    # 仓库里只有 1 条
    rows = await service.list_tasks(tenant_id=tenant_id)
    assert len(rows) == 1

    # 事件只发 1 次（第二次是幂等命中，不重发）
    await _drain_tasks()
    assert emit_mock.await_count == 1, (
        "独立验证 P1-1：幂等命中不应重复发射 DISPATCHED 事件"
    )


# ──────────────────────────────────────────────────────────────────────
# 兜底：导出任务类型数量保持 10
# ──────────────────────────────────────────────────────────────────────


def test_task_type_enum_has_ten_members():
    assert len(list(TaskType)) == 10
    # 契约规定的精确命名
    names = {t.value for t in TaskType}
    assert names == {
        "lead_follow_up",
        "banquet_stage",
        "dining_followup",
        "birthday",
        "anniversary",
        "dormant_recall",
        "new_customer",
        "confirm_arrival",
        "adhoc",
        "banquet_followup",
    }


def test_uuid_types_roundtrip():
    tid = uuid4()
    assert isinstance(tid, UUID)
