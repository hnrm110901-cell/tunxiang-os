"""传菜员(Runner)工作流测试

测试覆盖：
1. KDS完成出品 → 任务状态变为ready
2. 传菜员领取 → 状态变为delivering
3. 传菜员送达确认 → 状态变为served，推送通知到web-crew
4. 多道菜同一桌，全部served后触发"本桌已上齐"通知
5. tenant_id隔离
"""
from unittest.mock import AsyncMock, patch

import pytest

from ..src.services.runner_service import (
    STATUS_DELIVERING,
    STATUS_DONE,
    STATUS_READY,
    STATUS_SERVED,
    confirm_served,
    get_runner_queue,
    mark_ready,
    pickup_dish,
)


# ─── Fixtures ───

@pytest.fixture
def mock_db():
    return AsyncMock()


@pytest.fixture(autouse=True)
def clear_runner_store():
    """每个测试前清空内存任务存储"""
    from ..src.services import runner_service
    runner_service._runner_store.clear()
    yield
    runner_service._runner_store.clear()


# ─── 1. KDS完成出品 → ready ───

@pytest.mark.asyncio
async def test_mark_ready_transitions_to_ready():
    """KDS调用mark_ready后，任务状态应变为ready"""
    task_id = "task-001"
    operator_id = "chef-zhang"

    result = await mark_ready(task_id, operator_id)

    assert result["ok"] is True
    assert result["task"]["status"] == STATUS_READY
    assert result["task"]["task_id"] == task_id
    assert result["task"]["ready_at"] is not None


@pytest.mark.asyncio
async def test_mark_ready_records_operator():
    """mark_ready应记录操作人信息"""
    task_id = "task-002"
    operator_id = "chef-li"

    result = await mark_ready(task_id, operator_id)

    timeline = result["task"]["timeline"]
    assert any(e["event"] == "mark_ready" and e["operator_id"] == operator_id for e in timeline)


@pytest.mark.asyncio
async def test_mark_ready_from_done_status():
    """从done状态（KDS完成）转为ready"""
    from ..src.services import runner_service

    task_id = "task-003"
    # 预置done状态（模拟KDS已完成）
    runner_service._runner_store[task_id] = {
        "task_id": task_id,
        "status": STATUS_DONE,
        "store_id": "store-1",
        "table_number": "A01",
        "order_id": "order-1",
        "tenant_id": "tenant-1",
        "dish_name": "剁椒鱼头",
        "ready_at": None,
        "pickup_at": None,
        "served_at": None,
        "runner_id": None,
        "timeline": [],
    }

    result = await mark_ready(task_id, "chef-zhang")

    assert result["ok"] is True
    assert result["task"]["status"] == STATUS_READY


# ─── 2. 传菜员领取 → delivering ───

@pytest.mark.asyncio
async def test_pickup_dish_transitions_to_delivering():
    """传菜员领取后状态应变为delivering"""
    from ..src.services import runner_service

    task_id = "task-010"
    runner_id = "runner-wang"

    runner_service._runner_store[task_id] = _make_ready_task(task_id, "store-1", "A02")

    result = await pickup_dish(task_id, runner_id)

    assert result["ok"] is True
    assert result["task"]["status"] == STATUS_DELIVERING
    assert result["task"]["runner_id"] == runner_id
    assert result["task"]["pickup_at"] is not None


@pytest.mark.asyncio
async def test_pickup_dish_requires_ready_status():
    """只有ready状态的任务才能被领取"""
    from ..src.services import runner_service

    task_id = "task-011"
    runner_service._runner_store[task_id] = _make_ready_task(task_id, "store-1", "A03")
    runner_service._runner_store[task_id]["status"] = "pending"

    result = await pickup_dish(task_id, "runner-001")

    assert result["ok"] is False
    assert "error" in result


@pytest.mark.asyncio
async def test_pickup_records_timeline():
    """领取操作应记录到时间线"""
    from ..src.services import runner_service

    task_id = "task-012"
    runner_id = "runner-chen"
    runner_service._runner_store[task_id] = _make_ready_task(task_id, "store-1", "B01")

    await pickup_dish(task_id, runner_id)

    timeline = runner_service._runner_store[task_id]["timeline"]
    assert any(e["event"] == "pickup" and e["operator_id"] == runner_id for e in timeline)


# ─── 3. 送达确认 → served ───

@pytest.mark.asyncio
@patch("services.tx_trade.src.services.runner_service._push_to_crew", new_callable=AsyncMock)
async def test_confirm_served_transitions_to_served(mock_push):
    """送达确认后状态应变为served"""
    from ..src.services import runner_service

    task_id = "task-020"
    runner_id = "runner-liu"

    runner_service._runner_store[task_id] = _make_delivering_task(
        task_id, "store-1", "C01", "order-xyz", "tenant-t1"
    )

    result = await confirm_served(task_id, runner_id)

    assert result["ok"] is True
    assert result["task"]["status"] == STATUS_SERVED
    assert result["task"]["served_at"] is not None


@pytest.mark.asyncio
@patch("services.tx_trade.src.services.runner_service._push_to_crew", new_callable=AsyncMock)
async def test_confirm_served_requires_delivering_status(mock_push):
    """只有delivering状态的任务才能确认送达"""
    from ..src.services import runner_service

    task_id = "task-021"
    runner_service._runner_store[task_id] = _make_ready_task(task_id, "store-1", "D01")

    result = await confirm_served(task_id, "runner-001")

    assert result["ok"] is False


# ─── 4. 全桌上齐通知 ───

@pytest.mark.asyncio
@patch("services.tx_trade.src.services.runner_service._push_to_crew", new_callable=AsyncMock)
async def test_all_served_triggers_table_complete_notification(mock_push):
    """同一桌所有任务全部served后，应推送'全桌上齐'通知"""
    from ..src.services import runner_service

    tenant_id = "tenant-t2"
    store_id = "store-2"
    order_id = "order-abc"
    table_number = "E05"

    task_id_1 = "task-030"
    task_id_2 = "task-031"

    runner_service._runner_store[task_id_1] = _make_delivering_task(
        task_id_1, store_id, table_number, order_id, tenant_id, "红烧肉"
    )
    runner_service._runner_store[task_id_2] = _make_delivering_task(
        task_id_2, store_id, table_number, order_id, tenant_id, "清蒸鱼"
    )

    # 第一道菜送达，另一道还在delivering，不应触发全桌通知
    await confirm_served(task_id_1, "runner-001")
    table_complete_calls_after_first = [
        call for call in mock_push.call_args_list
        if len(call[0]) > 1 and isinstance(call[0][1], dict)
        and call[0][1].get("type") == "table_all_served"
    ]
    assert len(table_complete_calls_after_first) == 0, "第一道菜送达后不应触发全桌通知"

    # 第二道菜送达，全桌已齐
    mock_push.reset_mock()
    await confirm_served(task_id_2, "runner-001")

    # 验证推送了全桌上齐通知
    table_complete_calls = [
        call for call in mock_push.call_args_list
        if len(call[0]) > 1 and isinstance(call[0][1], dict)
        and call[0][1].get("type") == "table_all_served"
    ]
    assert len(table_complete_calls) == 1, "全部送达后应推送一次 table_all_served 通知"

    notification = table_complete_calls[0][0][1]
    assert notification["table_number"] == table_number
    assert notification["order_id"] == order_id


@pytest.mark.asyncio
@patch("services.tx_trade.src.services.runner_service._push_to_crew", new_callable=AsyncMock)
async def test_partial_served_no_table_complete(mock_push):
    """同一桌部分菜品served，不应触发全桌通知"""
    from ..src.services import runner_service

    tenant_id = "tenant-t3"
    store_id = "store-3"
    order_id = "order-def"
    table_number = "F01"

    task_id_1 = "task-040"
    task_id_2 = "task-041"

    runner_service._runner_store[task_id_1] = _make_delivering_task(
        task_id_1, store_id, table_number, order_id, tenant_id
    )
    runner_service._runner_store[task_id_2] = _make_ready_task(task_id_2, store_id, table_number)
    runner_service._runner_store[task_id_2]["order_id"] = order_id
    runner_service._runner_store[task_id_2]["tenant_id"] = tenant_id

    # 只有一道菜送达
    await confirm_served(task_id_1, "runner-001")

    # 不应有 table_all_served 通知
    table_complete_calls = [
        call for call in mock_push.call_args_list
        if len(call[0]) > 1 and isinstance(call[0][1], dict)
        and call[0][1].get("type") == "table_all_served"
    ]
    assert len(table_complete_calls) == 0, "未全部送达时不应触发全桌通知"


# ─── 5. tenant_id隔离 ───

@pytest.mark.asyncio
async def test_get_runner_queue_tenant_isolation(mock_db):
    """get_runner_queue应只返回指定tenant的ready菜品"""
    from ..src.services import runner_service

    store_id = "store-4"

    task_a = _make_ready_task("task-050", store_id, "G01")
    task_a["tenant_id"] = "tenant-A"

    task_b = _make_ready_task("task-051", store_id, "G02")
    task_b["tenant_id"] = "tenant-B"

    runner_service._runner_store["task-050"] = task_a
    runner_service._runner_store["task-051"] = task_b

    queue_a = await get_runner_queue(store_id, "tenant-A")
    queue_b = await get_runner_queue(store_id, "tenant-B")

    assert all(t["tenant_id"] == "tenant-A" for t in queue_a)
    assert all(t["tenant_id"] == "tenant-B" for t in queue_b)
    assert len(queue_a) == 1
    assert len(queue_b) == 1


@pytest.mark.asyncio
async def test_mark_ready_with_tenant_id():
    """mark_ready的任务应携带tenant_id"""
    from ..src.services import runner_service

    task_id = "task-060"
    tenant_id = "tenant-C"

    runner_service._runner_store[task_id] = _make_ready_task(task_id, "store-5", "H01")
    runner_service._runner_store[task_id]["status"] = STATUS_DONE
    runner_service._runner_store[task_id]["tenant_id"] = tenant_id

    result = await mark_ready(task_id, "chef-001")
    assert result["ok"] is True
    assert result["task"]["tenant_id"] == tenant_id


# ─── 辅助函数 ───

def _make_ready_task(task_id: str, store_id: str, table_number: str) -> dict:
    return {
        "task_id": task_id,
        "status": STATUS_READY,
        "store_id": store_id,
        "table_number": table_number,
        "order_id": f"order-{task_id}",
        "tenant_id": "tenant-default",
        "dish_name": "测试菜品",
        "ready_at": "2026-03-30T10:00:00+00:00",
        "pickup_at": None,
        "served_at": None,
        "runner_id": None,
        "timeline": [],
    }


def _make_delivering_task(
    task_id: str,
    store_id: str,
    table_number: str,
    order_id: str = "order-default",
    tenant_id: str = "tenant-default",
    dish_name: str = "测试菜品",
) -> dict:
    return {
        "task_id": task_id,
        "status": STATUS_DELIVERING,
        "store_id": store_id,
        "table_number": table_number,
        "order_id": order_id,
        "tenant_id": tenant_id,
        "dish_name": dish_name,
        "ready_at": "2026-03-30T10:00:00+00:00",
        "pickup_at": "2026-03-30T10:01:00+00:00",
        "served_at": None,
        "runner_id": "runner-default",
        "timeline": [],
    }
