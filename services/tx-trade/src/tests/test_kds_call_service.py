"""KDS 等叫三态 & 出单模式配置测试

覆盖 8 个场景：
1. cooking → calling 状态流转成功
2. pending → calling 被拒绝（错误状态流转）
3. calling → done 确认上桌
4. done → calling 被拒绝（已完成任务不可回退）
5. 等叫等待时间计算正确
6. 等叫统计：数量 + 平均等待分钟
7. 出单模式默认 IMMEDIATE
8. POST_PAYMENT 模式：下单不推，收银后推
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─── 工具 ───

def _uid() -> str:
    return str(uuid.uuid4())


TENANT_ID = _uid()
STORE_ID  = _uid()
ORDER_ID  = _uid()
DEPT_ID   = _uid()


class FakeResult:
    """模拟 SQLAlchemy execute() 返回值。"""
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def one_or_none(self):
        return self._rows[0] if self._rows else None


def _fake_db():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=FakeResult())
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _make_task(status: str, called_at: datetime | None = None) -> MagicMock:
    """构造一个最小化 KDSTask mock 对象。"""
    task = MagicMock()
    task.id = uuid.uuid4()
    task.tenant_id = uuid.UUID(TENANT_ID)
    task.dept_id = uuid.UUID(DEPT_ID)
    task.order_item_id = uuid.uuid4()
    task.status = status
    task.called_at = called_at
    task.call_count = 0
    task.served_at = None
    task.completed_at = None
    task.created_at = datetime.now(timezone.utc)
    task.is_deleted = False
    return task


# ─── 场景 1: cooking → calling 成功 ───

@pytest.mark.asyncio
async def test_mark_calling_from_cooking_succeeds():
    """cooking 状态的任务可以成功转为 calling，call_count +1。"""
    from services.kds_call_service import KdsCallService

    task_id = _uid()
    task = _make_task("cooking")

    db = _fake_db()
    db.execute = AsyncMock(return_value=FakeResult(scalar=task))

    with patch("services.kds_call_service._broadcast", new=AsyncMock()):
        result = await KdsCallService.mark_calling(task_id, TENANT_ID, db)

    assert result.status == "calling"
    assert result.called_at is not None
    assert result.call_count == 1


# ─── 场景 2: pending → calling 被拒绝 ───

@pytest.mark.asyncio
async def test_mark_calling_from_pending_raises():
    """pending 状态的任务不允许直接转为 calling，应抛出 RuntimeError。"""
    from services.kds_call_service import KdsCallService

    task_id = _uid()
    task = _make_task("pending")

    db = _fake_db()
    db.execute = AsyncMock(return_value=FakeResult(scalar=task))

    with pytest.raises(RuntimeError, match="cooking"):
        await KdsCallService.mark_calling(task_id, TENANT_ID, db)


# ─── 场景 3: calling → done 确认上桌 ───

@pytest.mark.asyncio
async def test_confirm_served_from_calling_succeeds():
    """calling 状态的任务可以成功转为 done，served_at 有值。"""
    from services.kds_call_service import KdsCallService

    task_id = _uid()
    called_at = datetime.now(timezone.utc) - timedelta(minutes=3)
    task = _make_task("calling", called_at=called_at)

    db = _fake_db()
    db.execute = AsyncMock(return_value=FakeResult(scalar=task))

    with patch("services.kds_call_service._broadcast", new=AsyncMock()):
        result = await KdsCallService.confirm_served(task_id, TENANT_ID, db)

    assert result.status == "done"
    assert result.served_at is not None
    assert result.completed_at is not None


# ─── 场景 4: done → calling 被拒绝（confirm_served 也验证状态来源） ───

@pytest.mark.asyncio
async def test_confirm_served_from_done_raises():
    """已完成（done）的任务不可再次确认上桌，应抛出 RuntimeError。"""
    from services.kds_call_service import KdsCallService

    task_id = _uid()
    task = _make_task("done")

    db = _fake_db()
    db.execute = AsyncMock(return_value=FakeResult(scalar=task))

    with pytest.raises(RuntimeError, match="calling"):
        await KdsCallService.confirm_served(task_id, TENANT_ID, db)


# ─── 场景 5: 等叫等待时间计算正确 ───

@pytest.mark.asyncio
async def test_calling_stats_wait_time_calculation():
    """等叫统计的 avg_waiting_minutes 应准确反映 called_at 到现在的时长。"""
    from services.kds_call_service import CallingStats, KdsCallService

    # 构造两个 calling 任务，等待时间分别为 4 分钟和 8 分钟
    now = datetime.now(timezone.utc)
    t1 = _make_task("calling", called_at=now - timedelta(minutes=4))
    t2 = _make_task("calling", called_at=now - timedelta(minutes=8))

    with patch.object(KdsCallService, "get_calling_tasks", new=AsyncMock(return_value=[t1, t2])):
        stats: CallingStats = await KdsCallService.get_calling_stats(STORE_ID, TENANT_ID, _fake_db())

    assert stats.calling_count == 2
    # 平均应在 5.9–6.1 之间（受函数调用耗时影响，放宽到 ±0.5）
    assert 5.5 <= stats.avg_waiting_minutes <= 6.5


# ─── 场景 6: 批量等叫任务查询 ───

@pytest.mark.asyncio
async def test_get_calling_tasks_returns_list():
    """get_calling_tasks 应返回所有 calling 状态任务的列表。"""
    from services.kds_call_service import KdsCallService

    now = datetime.now(timezone.utc)
    tasks = [
        _make_task("calling", called_at=now - timedelta(minutes=i))
        for i in range(3)
    ]

    db = _fake_db()
    mock_result = FakeResult()
    mock_result._rows = tasks
    db.execute = AsyncMock(return_value=mock_result)

    result = await KdsCallService.get_calling_tasks(STORE_ID, TENANT_ID, db)

    assert len(result) == 3


# ─── 场景 7: 出单模式默认 IMMEDIATE ───

@pytest.mark.asyncio
async def test_order_push_mode_default_is_immediate():
    """未配置时 get_store_mode 应返回 IMMEDIATE，should_push_on_order 返回 True。"""
    from services.order_push_config import OrderPushConfigService, OrderPushMode

    db = _fake_db()
    # 模拟数据库没有该门店的配置记录
    db.execute = AsyncMock(return_value=FakeResult(rows=[]))

    mode = await OrderPushConfigService.get_store_mode(STORE_ID, TENANT_ID, db)
    assert mode == OrderPushMode.IMMEDIATE

    # should_push_on_order 应返回 True
    db2 = _fake_db()
    db2.execute = AsyncMock(return_value=FakeResult(rows=[]))
    should_push = await OrderPushConfigService.should_push_on_order(STORE_ID, TENANT_ID, db2)
    assert should_push is True


# ─── 场景 8: POST_PAYMENT 模式 ───

@pytest.mark.asyncio
async def test_post_payment_mode_no_push_then_deferred():
    """POST_PAYMENT 模式下，should_push_on_order 为 False；
    收银完成后 push_deferred_tasks 激活 pending 任务。"""
    from services.order_push_config import OrderPushConfigService, OrderPushMode

    # 1) 模拟数据库返回 post_payment 配置行
    db_check = _fake_db()
    db_check.execute = AsyncMock(return_value=FakeResult(rows=[("post_payment",)]))

    mode = await OrderPushConfigService.get_store_mode(STORE_ID, TENANT_ID, db_check)
    assert mode == OrderPushMode.POST_PAYMENT

    db_push_check = _fake_db()
    db_push_check.execute = AsyncMock(return_value=FakeResult(rows=[("post_payment",)]))
    should_push = await OrderPushConfigService.should_push_on_order(STORE_ID, TENANT_ID, db_push_check)
    assert should_push is False

    # 2) push_deferred_tasks 激活该订单下的 pending 任务
    fake_task_id = uuid.uuid4()
    db_deferred = _fake_db()

    call_count = 0

    async def _execute_side_effect(stmt, params=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # 第一次 execute：SELECT pending tasks
            return FakeResult(rows=[(fake_task_id,)])
        # 第二次 execute：UPDATE
        return FakeResult()

    db_deferred.execute = AsyncMock(side_effect=_execute_side_effect)


    with patch("services.order_push_config.OrderPushConfigService.get_store_mode",
               new=AsyncMock(return_value=OrderPushMode.POST_PAYMENT)), patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=MagicMock(status_code=200))
        mock_client_cls.return_value = mock_client

        count = await OrderPushConfigService.push_deferred_tasks(
            ORDER_ID, TENANT_ID, db_deferred
        )

    assert count == 1
    db_deferred.flush.assert_called_once()
