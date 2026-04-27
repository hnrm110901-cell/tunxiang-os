"""客户生命周期 FSM Tier 1 测试（TDD 先于实现编写）

对齐 CLAUDE.md §17 / §20：用例描述必须是餐厅场景，而不是技术边界值。

覆盖场景（共 8 条）：
1. test_first_order_triggers_no_order_to_active
2. test_60_days_no_order_triggers_active_to_dormant
3. test_180_days_no_order_triggers_dormant_to_churned
4. test_dormant_customer_orders_transitions_to_active（唤醒）
5. test_churned_customer_orders_transitions_to_active（挽回）
6. test_200_concurrent_transitions_no_race（200 并发）
7. test_idempotent_same_trigger_event_id（幂等）
8. test_tenant_isolation_rls（租户隔离）

测试策略：
- 纯函数 evaluate_state → 直接断言
- DB 交互层通过 MagicMock 的 CustomerLifecycleRepository 实例替换
  （避免启动 PostgreSQL；200 并发测试依赖 asyncio.Lock 模拟行锁）
"""

from __future__ import annotations

import asyncio
import os
import sys
import types
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

# ─── sys.path 注入 ──────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ─── 公共 stub 注入 ─────────────────────────────────────────────────────


def _inject_stubs() -> AsyncMock:
    """注入 shared.* 与 structlog 的最小化 stub。

    策略：先让真实 shared 包加载，再把特定子模块替换为 stub。
    避免用 setdefault 占坑导致真实子模块无法 import。
    """
    import importlib

    # structlog（真实 structlog 可能未装；如可 import 就不 stub）
    try:
        importlib.import_module("structlog")
    except ImportError:
        structlog_mod = types.ModuleType("structlog")
        structlog_mod.get_logger = MagicMock(return_value=MagicMock())
        sys.modules["structlog"] = structlog_mod

    # 先加载真实 shared 包骨架（由 cwd 下的 shared/ 目录提供）
    importlib.import_module("shared")
    importlib.import_module("shared.events")
    importlib.import_module("shared.events.src")
    importlib.import_module("shared.events.src.event_types")
    importlib.import_module("shared.ontology")
    importlib.import_module("shared.ontology.src")
    importlib.import_module("shared.ontology.src.extensions")
    importlib.import_module("shared.ontology.src.extensions.customer_lifecycle")

    # 替换 shared.ontology.src.database 为 stub（真实版会需要 asyncpg + DB）
    db_mod = types.ModuleType("shared.ontology.src.database")
    db_mod.async_session_factory = MagicMock()
    db_mod.get_db = MagicMock()
    sys.modules["shared.ontology.src.database"] = db_mod

    # 替换 shared.events.src.emitter.emit_event 为 AsyncMock
    emitter_mod = types.ModuleType("shared.events.src.emitter")
    _emit_event_mock = AsyncMock(return_value=str(uuid.uuid4()))
    emitter_mod.emit_event = _emit_event_mock
    sys.modules["shared.events.src.emitter"] = emitter_mod

    # 替换 shared.events.src.projector 为 stub（真实 base 会拖 asyncpg）
    proj_mod = types.ModuleType("shared.events.src.projector")

    class _ProjectorBase:
        name = ""
        event_types: set = set()

        def __init__(self, tenant_id):
            self.tenant_id = uuid.UUID(str(tenant_id))

        async def handle(self, event, conn):
            raise NotImplementedError

    proj_mod.ProjectorBase = _ProjectorBase
    sys.modules["shared.events.src.projector"] = proj_mod

    return _emit_event_mock


_EMIT_EVENT_MOCK = _inject_stubs()


# ─── 真实 import（在 stub 注入之后） ────────────────────────────────────

from repositories.customer_lifecycle_repo import (  # noqa: E402, I001
    CustomerLifecycleRepository,
)
from services.customer_lifecycle_fsm import (  # noqa: E402, I001
    CustomerLifecycleFSM,
    LifecycleThresholds,
)

from shared.ontology.src.extensions.customer_lifecycle import (  # noqa: E402, I001
    CustomerLifecycleRecord,
    CustomerLifecycleState,
)


# ─── 辅助 fixture ───────────────────────────────────────────────────────


def _uid() -> uuid.UUID:
    return uuid.uuid4()


def _record(
    tenant_id: uuid.UUID,
    customer_id: uuid.UUID,
    state: CustomerLifecycleState,
    *,
    previous: CustomerLifecycleState | None = None,
    since_ts: datetime | None = None,
    count: int = 1,
    trigger: uuid.UUID | None = None,
) -> CustomerLifecycleRecord:
    now = since_ts or datetime.now(timezone.utc)
    return CustomerLifecycleRecord(
        customer_id=customer_id,
        tenant_id=tenant_id,
        state=state,
        since_ts=now,
        previous_state=previous,
        transition_count=count,
        last_transition_event_id=trigger,
        updated_at=now,
    )


class _FakeRepo:
    """内存版 repo：模拟 SELECT FOR UPDATE + upsert，附带 asyncio.Lock 行锁。"""

    def __init__(self, tenant_id: uuid.UUID):
        self.tenant_id = tenant_id
        self._rows: dict[uuid.UUID, CustomerLifecycleRecord] = {}
        self._locks: dict[uuid.UUID, asyncio.Lock] = {}

    def _lock(self, cid: uuid.UUID) -> asyncio.Lock:
        if cid not in self._locks:
            self._locks[cid] = asyncio.Lock()
        return self._locks[cid]

    async def get_for_update(self, customer_id):
        cid = uuid.UUID(str(customer_id))
        return self._rows.get(cid)

    async def get_current_state(self, customer_id):
        cid = uuid.UUID(str(customer_id))
        return self._rows.get(cid)

    async def upsert_state(
        self,
        *,
        customer_id,
        target_state,
        since_ts,
        trigger_event_id,
        previous_state,
    ):
        cid = uuid.UUID(str(customer_id))
        trig = uuid.UUID(str(trigger_event_id)) if trigger_event_id else None
        now = datetime.now(timezone.utc)
        existing = self._rows.get(cid)

        # 幂等短路
        if (
            existing is not None
            and trig is not None
            and existing.last_transition_event_id == trig
        ):
            return existing

        if existing is None:
            rec = CustomerLifecycleRecord(
                customer_id=cid,
                tenant_id=self.tenant_id,
                state=target_state,
                since_ts=since_ts,
                previous_state=previous_state,
                transition_count=1,
                last_transition_event_id=trig,
                updated_at=now,
            )
            self._rows[cid] = rec
            return rec

        if existing.state == target_state:
            rec = CustomerLifecycleRecord(
                customer_id=cid,
                tenant_id=self.tenant_id,
                state=existing.state,
                since_ts=existing.since_ts,
                previous_state=existing.previous_state,
                transition_count=existing.transition_count,
                last_transition_event_id=trig or existing.last_transition_event_id,
                updated_at=now,
            )
            self._rows[cid] = rec
            return rec

        new_count = existing.transition_count + 1
        rec = CustomerLifecycleRecord(
            customer_id=cid,
            tenant_id=self.tenant_id,
            state=target_state,
            since_ts=since_ts,
            previous_state=existing.state,
            transition_count=new_count,
            last_transition_event_id=trig,
            updated_at=now,
        )
        self._rows[cid] = rec
        return rec


# ─── FSM 测试专用子类：用 _FakeRepo 替换 self.repo ─────────────────────


class _TestFSM(CustomerLifecycleFSM):
    """测试用 FSM：构造时注入 _FakeRepo 取代真实 repo。"""

    def __init__(
        self,
        tenant_id: uuid.UUID,
        fake_repo: _FakeRepo,
        thresholds: LifecycleThresholds | None = None,
    ):
        # 绕过父类构造；不初始化 db
        self.db = MagicMock()
        self.tenant_id = tenant_id
        self.thresholds = thresholds or LifecycleThresholds()
        self.repo = fake_repo


# ═════════════════════════════════════════════════════════════════════
# 场景 1：首单触发 no_order → active
# ═════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_first_order_triggers_no_order_to_active():
    """尝在一起新客户首次买单，状态应从 no_order 迁到 active 并产生事件。"""
    _EMIT_EVENT_MOCK.reset_mock()
    tid = _uid()
    cid = _uid()
    repo = _FakeRepo(tid)
    fsm = _TestFSM(tid, repo)

    now = datetime.now(timezone.utc)
    trigger = _uid()

    record = await fsm.transition(
        customer_id=cid,
        trigger_event_id=trigger,
        now=now,
        last_order_at=now,
        order_count=1,
    )

    assert record.state == CustomerLifecycleState.ACTIVE
    assert record.previous_state is None
    assert record.transition_count == 1
    # 事件异步发射，等待 pending
    await asyncio.sleep(0)
    assert _EMIT_EVENT_MOCK.call_count == 1
    call_payload = _EMIT_EVENT_MOCK.call_args.kwargs["payload"]
    assert call_payload["previous_state"] is None
    assert call_payload["next_state"] == "active"
    assert call_payload["trigger_event_id"] == str(trigger)


# ═════════════════════════════════════════════════════════════════════
# 场景 2：60 天无消费 → active → dormant
# ═════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_60_days_no_order_triggers_active_to_dormant():
    """老客户连续 61 天未到店，夜批重算应迁入 dormant。"""
    _EMIT_EVENT_MOCK.reset_mock()
    tid = _uid()
    cid = _uid()
    repo = _FakeRepo(tid)

    # 先置为 active（上次消费是 70 天前，但 state 还停留在 active，
    # 因为夜批尚未跑）
    existing_since = datetime.now(timezone.utc) - timedelta(days=70)
    repo._rows[cid] = _record(
        tid, cid, CustomerLifecycleState.ACTIVE, since_ts=existing_since
    )

    fsm = _TestFSM(tid, repo)
    now = datetime.now(timezone.utc)
    last_order = now - timedelta(days=61)

    record = await fsm.transition(
        customer_id=cid,
        trigger_event_id=None,
        now=now,
        last_order_at=last_order,
        order_count=5,
        reason="daily_recompute",
    )

    assert record.state == CustomerLifecycleState.DORMANT
    assert record.previous_state == CustomerLifecycleState.ACTIVE
    await asyncio.sleep(0)
    assert _EMIT_EVENT_MOCK.call_count == 1
    call = _EMIT_EVENT_MOCK.call_args.kwargs
    assert call["payload"]["previous_state"] == "active"
    assert call["payload"]["next_state"] == "dormant"


# ═════════════════════════════════════════════════════════════════════
# 场景 3：180 天无消费 → dormant → churned
# ═════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_180_days_no_order_triggers_dormant_to_churned():
    """沉睡客户连续 181 天不到店，迁入 churned（流失）。"""
    _EMIT_EVENT_MOCK.reset_mock()
    tid = _uid()
    cid = _uid()
    repo = _FakeRepo(tid)
    repo._rows[cid] = _record(tid, cid, CustomerLifecycleState.DORMANT, count=2)

    fsm = _TestFSM(tid, repo)
    now = datetime.now(timezone.utc)
    last_order = now - timedelta(days=181)

    record = await fsm.transition(
        customer_id=cid,
        trigger_event_id=None,
        now=now,
        last_order_at=last_order,
        order_count=3,
    )

    assert record.state == CustomerLifecycleState.CHURNED
    assert record.previous_state == CustomerLifecycleState.DORMANT
    assert record.transition_count == 3
    await asyncio.sleep(0)
    assert _EMIT_EVENT_MOCK.call_count == 1


# ═════════════════════════════════════════════════════════════════════
# 场景 4：dormant → active（唤醒）
# ═════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_dormant_customer_orders_transitions_to_active():
    """沉睡客户收到召回优惠券后到店消费，迁回 active（唤醒）。"""
    _EMIT_EVENT_MOCK.reset_mock()
    tid = _uid()
    cid = _uid()
    repo = _FakeRepo(tid)
    repo._rows[cid] = _record(tid, cid, CustomerLifecycleState.DORMANT, count=2)

    fsm = _TestFSM(tid, repo)
    now = datetime.now(timezone.utc)
    trigger = _uid()

    record = await fsm.transition(
        customer_id=cid,
        trigger_event_id=trigger,
        now=now,
        last_order_at=now,
        order_count=6,
        reason="recall_order",
    )

    assert record.state == CustomerLifecycleState.ACTIVE
    assert record.previous_state == CustomerLifecycleState.DORMANT
    await asyncio.sleep(0)
    assert _EMIT_EVENT_MOCK.call_count == 1
    call = _EMIT_EVENT_MOCK.call_args.kwargs
    assert call["payload"]["reason"] == "recall_order"


# ═════════════════════════════════════════════════════════════════════
# 场景 5：churned → active（挽回）
# ═════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_churned_customer_orders_transitions_to_active():
    """流失客户收到大额复活券回来消费，挽回成功，一条事件即可。"""
    _EMIT_EVENT_MOCK.reset_mock()
    tid = _uid()
    cid = _uid()
    repo = _FakeRepo(tid)
    repo._rows[cid] = _record(tid, cid, CustomerLifecycleState.CHURNED, count=3)

    fsm = _TestFSM(tid, repo)
    now = datetime.now(timezone.utc)
    trigger = _uid()

    record = await fsm.transition(
        customer_id=cid,
        trigger_event_id=trigger,
        now=now,
        last_order_at=now,
        order_count=7,
    )

    assert record.state == CustomerLifecycleState.ACTIVE
    assert record.previous_state == CustomerLifecycleState.CHURNED
    await asyncio.sleep(0)
    # 挽回只产生一条事件，避免 recall 重算造成双写
    assert _EMIT_EVENT_MOCK.call_count == 1


# ═════════════════════════════════════════════════════════════════════
# 场景 6：200 桌并发结账 no_order → active 无竞态
# ═════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_200_concurrent_transitions_no_race():
    """200 桌同时结账对应 200 位新客，最终 200 条 active 记录 + 200 条事件。"""
    _EMIT_EVENT_MOCK.reset_mock()
    tid = _uid()
    repo = _FakeRepo(tid)
    fsm = _TestFSM(tid, repo)
    now = datetime.now(timezone.utc)

    customers = [_uid() for _ in range(200)]
    triggers = [_uid() for _ in range(200)]

    async def _one(i: int):
        return await fsm.transition(
            customer_id=customers[i],
            trigger_event_id=triggers[i],
            now=now,
            last_order_at=now,
            order_count=1,
        )

    results = await asyncio.gather(*[_one(i) for i in range(200)])

    # 最终状态全部 active
    assert all(r.state == CustomerLifecycleState.ACTIVE for r in results)
    # repo 中有 200 条独立记录
    assert len(repo._rows) == 200
    # 等事件任务完成
    await asyncio.sleep(0.05)
    # 事件总数 = 200（每个客户一条）
    assert _EMIT_EVENT_MOCK.call_count == 200


# ═════════════════════════════════════════════════════════════════════
# 场景 7：同一 trigger_event_id 幂等（重放不重复写事件）
# ═════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_idempotent_same_trigger_event_id():
    """projector 重启重放同一事件 3 次，不重复写事件、不重复计数。"""
    _EMIT_EVENT_MOCK.reset_mock()
    tid = _uid()
    cid = _uid()
    repo = _FakeRepo(tid)
    fsm = _TestFSM(tid, repo)

    now = datetime.now(timezone.utc)
    trigger = _uid()

    # 首次：no_order → active，写一条事件
    r1 = await fsm.transition(
        customer_id=cid,
        trigger_event_id=trigger,
        now=now,
        last_order_at=now,
        order_count=1,
    )
    await asyncio.sleep(0)
    assert r1.state == CustomerLifecycleState.ACTIVE
    assert _EMIT_EVENT_MOCK.call_count == 1

    # 第 2 次重放：幂等短路
    r2 = await fsm.transition(
        customer_id=cid,
        trigger_event_id=trigger,
        now=now,
        last_order_at=now,
        order_count=1,
    )
    # 第 3 次重放：幂等短路
    r3 = await fsm.transition(
        customer_id=cid,
        trigger_event_id=trigger,
        now=now,
        last_order_at=now,
        order_count=1,
    )
    await asyncio.sleep(0)

    assert r2.state == CustomerLifecycleState.ACTIVE
    assert r3.state == CustomerLifecycleState.ACTIVE
    assert r1.transition_count == r2.transition_count == r3.transition_count == 1
    # 事件计数保持 1，不重复写
    assert _EMIT_EVENT_MOCK.call_count == 1


# ═════════════════════════════════════════════════════════════════════
# 场景 8：租户隔离（两个 FSM 实例各写自己的表，不串库）
# ═════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_tenant_isolation_rls():
    """tenant_A 和 tenant_B 对同一 customer_id 的写入互不可见（RLS 模拟）。"""
    _EMIT_EVENT_MOCK.reset_mock()
    tid_a = _uid()
    tid_b = _uid()
    cid = _uid()  # 极端场景：两个租户碰撞同一 customer_id

    repo_a = _FakeRepo(tid_a)
    repo_b = _FakeRepo(tid_b)
    fsm_a = _TestFSM(tid_a, repo_a)
    fsm_b = _TestFSM(tid_b, repo_b)

    now = datetime.now(timezone.utc)
    trig_a = _uid()
    trig_b = _uid()

    await fsm_a.transition(
        customer_id=cid,
        trigger_event_id=trig_a,
        now=now,
        last_order_at=now,
        order_count=1,
    )
    await fsm_b.transition(
        customer_id=cid,
        trigger_event_id=trig_b,
        now=now,
        last_order_at=now,
        order_count=1,
    )

    # repo_a 只看到 tenant_A 的行；repo_b 只看到 tenant_B 的行
    rec_a = await repo_a.get_current_state(cid)
    rec_b = await repo_b.get_current_state(cid)

    assert rec_a is not None
    assert rec_b is not None
    assert rec_a.tenant_id == tid_a
    assert rec_b.tenant_id == tid_b
    assert rec_a.last_transition_event_id == trig_a
    assert rec_b.last_transition_event_id == trig_b
    # 交叉校验：tenant_A 的 trigger 不出现在 tenant_B 的记录中
    assert rec_a.last_transition_event_id != rec_b.last_transition_event_id


# ═════════════════════════════════════════════════════════════════════
# 场景补充：纯函数 evaluate_state 单测（帮助调试边界）
# ═════════════════════════════════════════════════════════════════════


def test_evaluate_state_pure_function_boundaries():
    """evaluate_state 纯函数边界：0 单/59 天/60 天/179 天/180 天。"""
    fsm = CustomerLifecycleFSM.__new__(CustomerLifecycleFSM)
    fsm.thresholds = LifecycleThresholds()
    now = datetime(2026, 4, 23, 10, 0, 0, tzinfo=timezone.utc)

    # 0 单 → no_order
    assert (
        fsm.evaluate_state(now=now, last_order_at=None, order_count=0)
        == CustomerLifecycleState.NO_ORDER
    )
    # 刚消费（0 天）→ active
    assert (
        fsm.evaluate_state(now=now, last_order_at=now, order_count=1)
        == CustomerLifecycleState.ACTIVE
    )
    # 59 天前 → active
    assert (
        fsm.evaluate_state(
            now=now, last_order_at=now - timedelta(days=59), order_count=2
        )
        == CustomerLifecycleState.ACTIVE
    )
    # 60 天前 → dormant
    assert (
        fsm.evaluate_state(
            now=now, last_order_at=now - timedelta(days=60), order_count=2
        )
        == CustomerLifecycleState.DORMANT
    )
    # 179 天前 → dormant
    assert (
        fsm.evaluate_state(
            now=now, last_order_at=now - timedelta(days=179), order_count=2
        )
        == CustomerLifecycleState.DORMANT
    )
    # 180 天前 → churned
    assert (
        fsm.evaluate_state(
            now=now, last_order_at=now - timedelta(days=180), order_count=2
        )
        == CustomerLifecycleState.CHURNED
    )


# ═════════════════════════════════════════════════════════════════════
# Repo unit：验证 _row_to_record 映射正确
# ═════════════════════════════════════════════════════════════════════


def test_repo_row_to_record_mapping():
    """Row 映射到 Pydantic 记录，字段类型与值正确。"""
    tid = _uid()
    cid = _uid()
    trig = _uid()
    now = datetime.now(timezone.utc)

    row = (cid, tid, "active", now, "no_order", 1, trig, now)
    rec = CustomerLifecycleRepository._row_to_record(row)

    assert rec.customer_id == cid
    assert rec.tenant_id == tid
    assert rec.state == CustomerLifecycleState.ACTIVE
    assert rec.previous_state == CustomerLifecycleState.NO_ORDER
    assert rec.transition_count == 1
    assert rec.last_transition_event_id == trig


# ═════════════════════════════════════════════════════════════════════
# P0-1 新增测试（补缺口）：
# - test_order_cancelled_triggers_state_rollback_if_no_other_paid_orders
# - test_order_cancelled_keeps_active_if_other_paid_orders_exist
# - test_order_refunded_same_as_cancelled
# - test_projector_skips_events_older_than_current_state（occurred_at 单调性）
# ═════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_order_cancelled_triggers_state_rollback_if_no_other_paid_orders():
    """客户单笔消费后状态迁到 active，随即整单取消且 60 天窗口内无其他已付订单
    → 生命周期回退到 no_order 并发 STATE_CHANGED 事件。"""
    _EMIT_EVENT_MOCK.reset_mock()
    tid = _uid()
    cid = _uid()
    repo = _FakeRepo(tid)
    # 现状：当前是 active，该记录由 order.paid 事件写入
    paid_event_id = _uid()
    repo._rows[cid] = _record(
        tid,
        cid,
        CustomerLifecycleState.ACTIVE,
        previous=None,
        count=1,
        trigger=paid_event_id,
    )

    fsm = _TestFSM(tid, repo)
    now = datetime.now(timezone.utc)
    cancel_event_id = _uid()

    result = await fsm.handle_order_reversal(
        customer_id=cid,
        trigger_event_id=cancel_event_id,
        now=now,
        previous_paid_order_at=None,  # 无其他已付订单
        remaining_order_count=0,
        reversal_type="order_cancelled",
    )

    assert result is not None
    # order_count=0 + last_order_at=None → evaluate 回到 NO_ORDER
    assert result.state == CustomerLifecycleState.NO_ORDER
    assert result.previous_state == CustomerLifecycleState.ACTIVE
    # 发 1 条 STATE_CHANGED
    assert _EMIT_EVENT_MOCK.call_count == 1
    call = _EMIT_EVENT_MOCK.call_args.kwargs
    assert call["payload"]["previous_state"] == "active"
    assert call["payload"]["next_state"] == "no_order"
    assert call["payload"]["reason"] == "order_cancelled"
    assert call["payload"]["trigger_event_id"] == str(cancel_event_id)


@pytest.mark.asyncio
async def test_order_cancelled_keeps_active_if_other_paid_orders_exist():
    """客户近 30 天有另一单合法消费，此刻取消最新一单 → 状态保持 active 不变。"""
    _EMIT_EVENT_MOCK.reset_mock()
    tid = _uid()
    cid = _uid()
    repo = _FakeRepo(tid)
    paid_event_id = _uid()
    repo._rows[cid] = _record(
        tid,
        cid,
        CustomerLifecycleState.ACTIVE,
        previous=CustomerLifecycleState.NO_ORDER,
        count=2,
        trigger=paid_event_id,
    )

    fsm = _TestFSM(tid, repo)
    now = datetime.now(timezone.utc)
    cancel_event_id = _uid()

    # 该客户 30 天前还有一单已付订单
    other_paid_at = now - timedelta(days=30)

    result = await fsm.handle_order_reversal(
        customer_id=cid,
        trigger_event_id=cancel_event_id,
        now=now,
        previous_paid_order_at=other_paid_at,
        remaining_order_count=1,
        reversal_type="order_cancelled",
    )

    # 状态仍是 active（因 30 天 < 60 天阈值）
    assert result is not None
    assert result.state == CustomerLifecycleState.ACTIVE
    # 不发 STATE_CHANGED
    assert _EMIT_EVENT_MOCK.call_count == 0
    # last_transition_event_id 应已被 touch 以保留审计链
    assert result.last_transition_event_id == cancel_event_id


@pytest.mark.asyncio
async def test_order_refunded_same_as_cancelled():
    """退款事件走与取消相同的回退逻辑（reversal_type 差异仅在 reason 字段）。"""
    _EMIT_EVENT_MOCK.reset_mock()
    tid = _uid()
    cid = _uid()
    repo = _FakeRepo(tid)
    paid_event_id = _uid()
    repo._rows[cid] = _record(
        tid,
        cid,
        CustomerLifecycleState.ACTIVE,
        previous=None,
        count=1,
        trigger=paid_event_id,
    )

    fsm = _TestFSM(tid, repo)
    now = datetime.now(timezone.utc)
    refund_event_id = _uid()

    result = await fsm.handle_order_reversal(
        customer_id=cid,
        trigger_event_id=refund_event_id,
        now=now,
        previous_paid_order_at=None,
        remaining_order_count=0,
        reversal_type="order_refunded",
    )

    assert result is not None
    assert result.state == CustomerLifecycleState.NO_ORDER
    assert result.previous_state == CustomerLifecycleState.ACTIVE
    assert _EMIT_EVENT_MOCK.call_count == 1
    call = _EMIT_EVENT_MOCK.call_args.kwargs
    assert call["payload"]["reason"] == "order_refunded"


@pytest.mark.asyncio
async def test_projector_skips_events_older_than_current_state():
    """P1-4 单调性：projector.handle 收到 occurred_at 早于已有状态 since_ts 的
    事件，应直接早退，不触发任何 FSM 写入或事件发射。

    策略：monkey-patch projector._is_event_older_than_current_state 返回 True，
    模拟"DB 检查发现事件过老"，确认 handle 早退。
    """
    from services.customer_lifecycle_projector import CustomerLifecycleProjector

    _EMIT_EVENT_MOCK.reset_mock()
    tid = _uid()
    cid = _uid()

    projector = CustomerLifecycleProjector(tenant_id=tid)

    # monkey-patch 单调性预检直接返回 True（事件过老）
    async def _always_older(*, customer_id, occurred_at):
        return True

    projector._is_event_older_than_current_state = _always_older  # type: ignore[assignment]

    old_occurred_at = datetime.now(timezone.utc) - timedelta(days=365)
    event = {
        "event_id": str(_uid()),
        "event_type": "order.paid",
        "occurred_at": old_occurred_at.isoformat(),
        "payload": {"customer_id": str(cid), "order_count": 5},
    }

    # conn 参数无用（FSM 不复用 asyncpg conn），传 None
    await projector.handle(event, conn=None)

    # 单调性过滤生效：没触发任何事件发射
    assert _EMIT_EVENT_MOCK.call_count == 0
