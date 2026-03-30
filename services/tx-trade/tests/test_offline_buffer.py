"""离线缓冲区测试套件

覆盖：
1. 断网时新订单写入本地 SQLite 缓冲
2. 恢复连接后增量同步到云端
3. 重复同步不会导致重复 KDS 任务（幂等性）
"""
import asyncio
import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../edge/mac-mini"))

from offline_buffer import OfflineBuffer


# ─── 测试夹具 ───

@pytest.fixture
def tmp_db(tmp_path):
    db_path = str(tmp_path / "test_offline_buffer.db")
    os.environ["OFFLINE_BUFFER_DB"] = db_path
    yield db_path
    if "OFFLINE_BUFFER_DB" in os.environ:
        del os.environ["OFFLINE_BUFFER_DB"]


@pytest.fixture
async def buffer(tmp_db):
    buf = OfflineBuffer(db_path=tmp_db)
    await buf.init_db()
    return buf


def _make_order(order_id: str = "ORD-2026-001", table: str = "A03") -> dict:
    return {
        "order_id": order_id,
        "table_number": table,
        "items": [
            {"dish_id": "DISH-001", "dish_name": "宫保鸡丁", "quantity": 2},
        ],
        "total_fen": 3800,
    }


# ─── Test 1: 断网时新订单写入本地 SQLite 缓冲 ───

@pytest.mark.asyncio
async def test_buffer_order_stores_to_sqlite(buffer):
    """断网缓存：订单应存入 SQLite，synced=False"""
    order = _make_order()
    await buffer.buffer_order(order)

    count = await buffer.get_pending_count()
    assert count == 1


@pytest.mark.asyncio
async def test_buffer_multiple_orders(buffer):
    """多个订单都应写入缓冲区"""
    for i in range(5):
        await buffer.buffer_order(_make_order(order_id=f"ORD-{i:04d}"))

    count = await buffer.get_pending_count()
    assert count == 5


@pytest.mark.asyncio
async def test_buffered_order_data_preserved(buffer):
    """缓冲的订单数据应完整保存"""
    order = _make_order(order_id="ORD-PRESERVE-TEST", table="B07")
    await buffer.buffer_order(order)

    pending = await buffer.get_pending_orders()
    assert len(pending) == 1
    stored = json.loads(pending[0]["order_data_json"])
    assert stored["order_id"] == "ORD-PRESERVE-TEST"
    assert stored["table_number"] == "B07"
    assert stored["items"][0]["dish_name"] == "宫保鸡丁"


# ─── Test 2: 恢复连接后增量同步到云端 ───

@pytest.mark.asyncio
async def test_sync_to_cloud_marks_synced(buffer):
    """成功同步后订单应标记 synced=True"""
    order = _make_order(order_id="ORD-SYNC-001")
    await buffer.buffer_order(order)

    # 模拟云端 API 成功响应
    async def mock_post(url, json_data):
        return {"ok": True}

    await buffer.sync_to_cloud(cloud_api_url="http://fake-cloud/api/v1/orders", post_fn=mock_post)

    count = await buffer.get_pending_count()
    assert count == 0  # 同步后待同步数量应为 0


@pytest.mark.asyncio
async def test_sync_to_cloud_calls_api_for_each_order(buffer):
    """sync_to_cloud 应对每个未同步订单调用云端 API"""
    for i in range(3):
        await buffer.buffer_order(_make_order(order_id=f"ORD-MULTI-{i}"))

    call_args = []

    async def mock_post(url, json_data):
        call_args.append(json_data)
        return {"ok": True}

    await buffer.sync_to_cloud(cloud_api_url="http://fake-cloud/api/v1/orders", post_fn=mock_post)

    assert len(call_args) == 3
    order_ids = {a["order_id"] for a in call_args}
    assert order_ids == {"ORD-MULTI-0", "ORD-MULTI-1", "ORD-MULTI-2"}


@pytest.mark.asyncio
async def test_sync_to_cloud_skips_already_synced(buffer):
    """已同步的订单不应再次发送"""
    order = _make_order(order_id="ORD-ALREADY-SYNCED")
    await buffer.buffer_order(order)

    call_count = 0

    async def mock_post(url, json_data):
        nonlocal call_count
        call_count += 1
        return {"ok": True}

    # 第一次同步
    await buffer.sync_to_cloud(cloud_api_url="http://fake-cloud/api/v1/orders", post_fn=mock_post)
    assert call_count == 1

    # 第二次同步：已同步的不应再调用
    await buffer.sync_to_cloud(cloud_api_url="http://fake-cloud/api/v1/orders", post_fn=mock_post)
    assert call_count == 1  # 仍然是 1，没有重复调用


@pytest.mark.asyncio
async def test_sync_partial_failure_preserves_unsynced(buffer):
    """部分同步失败时，失败的订单应保留在缓冲区"""
    for i in range(3):
        await buffer.buffer_order(_make_order(order_id=f"ORD-PARTIAL-{i}"))

    call_count = 0

    async def mock_post_fail_on_second(url, json_data):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            # 第二个订单同步失败
            return {"ok": False, "error": "云端错误"}
        return {"ok": True}

    await buffer.sync_to_cloud(cloud_api_url="http://fake-cloud/api/v1/orders", post_fn=mock_post_fail_on_second)

    # 应有 1 个未同步（失败的那个）
    remaining = await buffer.get_pending_count()
    assert remaining == 1


# ─── Test 3: 重复同步幂等性 ───

@pytest.mark.asyncio
async def test_idempotent_sync_no_duplicate(buffer):
    """相同 order_id 重复缓冲时，只保留一条记录（幂等）"""
    order = _make_order(order_id="ORD-IDEMPOTENT-001")
    await buffer.buffer_order(order)
    await buffer.buffer_order(order)  # 重复写入同一订单

    count = await buffer.get_pending_count()
    assert count == 1  # 应只有一条


@pytest.mark.asyncio
async def test_idempotent_sync_cloud_dedup(buffer):
    """即使多次执行 sync_to_cloud，云端 API 只被调用一次（幂等）"""
    order = _make_order(order_id="ORD-CLOUD-DEDUP-001")
    await buffer.buffer_order(order)

    call_count = 0

    async def mock_post(url, json_data):
        nonlocal call_count
        call_count += 1
        return {"ok": True}

    # 运行三次同步
    await buffer.sync_to_cloud(cloud_api_url="http://fake-cloud/api/v1/orders", post_fn=mock_post)
    await buffer.sync_to_cloud(cloud_api_url="http://fake-cloud/api/v1/orders", post_fn=mock_post)
    await buffer.sync_to_cloud(cloud_api_url="http://fake-cloud/api/v1/orders", post_fn=mock_post)

    # 云端 API 只应被调用一次
    assert call_count == 1


@pytest.mark.asyncio
async def test_idempotent_buffer_updates_existing(buffer):
    """重复 buffer_order 应更新数据而非新增（防止 order_id 重复触发多条 KDS 任务）"""
    order_v1 = _make_order(order_id="ORD-UPDATE-001")
    order_v2 = {**order_v1, "total_fen": 9999}  # 更新了金额

    await buffer.buffer_order(order_v1)
    await buffer.buffer_order(order_v2)

    pending = await buffer.get_pending_orders()
    assert len(pending) == 1
    # 应保存最新数据
    stored = json.loads(pending[0]["order_data_json"])
    assert stored["total_fen"] == 9999


# ─── get_pending_count 边界测试 ───

@pytest.mark.asyncio
async def test_pending_count_zero_initially(buffer):
    """初始状态下待同步数量应为 0"""
    count = await buffer.get_pending_count()
    assert count == 0


@pytest.mark.asyncio
async def test_pending_count_after_sync(buffer):
    """全部同步成功后待同步数量应为 0"""
    for i in range(4):
        await buffer.buffer_order(_make_order(order_id=f"ORD-COUNT-{i}"))

    async def mock_post(url, json_data):
        return {"ok": True}

    await buffer.sync_to_cloud(cloud_api_url="http://fake-cloud/api/v1/orders", post_fn=mock_post)

    count = await buffer.get_pending_count()
    assert count == 0
