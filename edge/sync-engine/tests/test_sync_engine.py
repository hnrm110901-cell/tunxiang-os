"""test_sync_engine.py — 数据同步引擎测试套件

覆盖：
  1. 增量同步：只同步 updated_at > last_sync_time 的记录
  2. 全量同步：首次连接或强制重置时的全量同步
  3. 冲突解决：本地和云端都修改了同一记录 → 云端优先（本地终态例外）
  4. 幂等性：重复同步不产生重复数据
  5. 断网恢复：本地操作缓冲 → 恢复连接后增量推送
  6. 大批量：10000 条记录分批同步（每批 500 条）

运行：
  pytest edge/sync-engine/tests/test_sync_engine.py -v
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# 将 src 目录加入 path（无需安装包）
import sys

SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, SRC_DIR)

from conflict_resolver import ConflictResolver  # noqa: E402
from sync_tracker import SyncTracker  # noqa: E402
from sync_engine import SyncEngine, _max_updated_at  # noqa: E402


# ─── 工具函数 ──────────────────────────────────────────────────────────────

def _ts(offset_seconds: int = 0) -> str:
    """生成相对当前时刻 offset_seconds 秒的 ISO 8601 时间戳"""
    dt = datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)
    return dt.isoformat()


def _make_record(
    rid: str = "order-1",
    updated_at: str | None = None,
    status: str = "pending",
    **extra: Any,
) -> dict:
    return {
        "id": rid,
        "updated_at": updated_at or _ts(),
        "status": status,
        "amount": 100,
        **extra,
    }


@pytest.fixture
def tmp_db(tmp_path):
    return str(tmp_path / "test_sync.db")


@pytest_asyncio.fixture
async def tracker(tmp_db):
    t = SyncTracker(db_path=tmp_db)
    await t.init_db()
    return t


# ─── 辅助 Fake Engine ─────────────────────────────────────────────────────

def _make_engine(tracker: SyncTracker, cloud_records_by_table=None, batch_size=500):
    """创建 SyncEngine，注入 mock 的 HTTP 拉取和本地 PG 操作"""
    engine = SyncEngine(
        tracker=tracker,
        local_db_url="postgresql+asyncpg://fake/fake",
        cloud_api_url="http://fake-cloud",
        batch_size=batch_size,
    )
    # 预存云端记录（{table: [record, ...]})
    _cloud = cloud_records_by_table or {}
    _upserted: dict[str, list] = {}

    async def fake_fetch(table, tenant_id, since, page=1, size=500):
        records = _cloud.get(table, [])
        if since and since != "1970-01-01T00:00:00+00:00":
            records = [r for r in records if str(r.get("updated_at", "")) > since]
        start = (page - 1) * size
        return records[start: start + size]

    async def fake_upsert(table, records, resolve_conflicts=True):
        _upserted.setdefault(table, [])
        # 幂等：相同 id 覆盖
        existing = {r["id"]: r for r in _upserted[table]}
        for r in records:
            existing[r["id"]] = r
        _upserted[table] = list(existing.values())

    async def fake_conflict_fetch(table, remote_records):
        return remote_records

    engine._fetch_from_cloud = fake_fetch
    engine._upsert_to_local = fake_upsert
    engine._apply_conflict_resolution = fake_conflict_fetch
    engine._local_pool = MagicMock()  # 避免真实 PG 连接

    return engine, _upserted


# ═══════════════════════════════════════════════════════════════════════════
# 1. 增量同步：只同步 updated_at > last_sync_time 的记录
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_incremental_sync_only_new_records(tracker):
    """增量同步只拉取 updated_at > watermark 的记录"""
    old_ts = _ts(-3600)  # 1 小时前
    new_ts = _ts(-60)    # 1 分钟前

    old_record = _make_record("order-old", updated_at=old_ts)
    new_record = _make_record("order-new", updated_at=new_ts)

    # 设置水位为 30 分钟前（old_record 应该被过滤掉）
    watermark = _ts(-1800)
    await tracker.set_watermark("orders", watermark)

    fetched: list[dict] = []

    engine = SyncEngine(
        tracker=tracker,
        local_db_url="postgresql+asyncpg://fake/fake",
        cloud_api_url="http://fake-cloud",
    )
    engine._local_pool = MagicMock()

    async def fake_fetch(table, tenant_id, since, page=1, size=500):
        # 只返回 updated_at > since 的记录
        records = [old_record, new_record]
        result = [r for r in records if str(r.get("updated_at", "")) > since]
        fetched.extend(result)
        return result

    async def fake_upsert(table, records, resolve_conflicts=True):
        pass

    engine._fetch_from_cloud = fake_fetch
    engine._upsert_to_local = fake_upsert
    engine._apply_conflict_resolution = AsyncMock(side_effect=lambda t, r: asyncio.coroutine(lambda: r)())
    engine._bulk_upsert_to_cloud = AsyncMock(return_value=True)

    result = await engine.incremental_sync("tenant-001")
    assert result["downloaded"] == 1, "只应拉取 1 条新记录"
    assert any(r["id"] == "order-new" for r in fetched)
    assert not any(r["id"] == "order-old" for r in fetched)


# ═══════════════════════════════════════════════════════════════════════════
# 2. 全量同步：首次连接或强制重置时
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_full_sync_resets_watermarks_and_pulls_all(tracker):
    """全量同步重置水位，拉取所有记录"""
    # 预设水位（模拟已有历史）
    await tracker.set_watermark("orders", _ts(-3600))

    records = [_make_record(f"order-{i}") for i in range(10)]
    engine, upserted = _make_engine(
        tracker, cloud_records_by_table={"orders": records}
    )

    # 模拟其他表返回空
    original_fetch = engine._fetch_from_cloud

    async def fake_fetch(table, tenant_id, since, page=1, size=500):
        if table == "orders":
            return await original_fetch(table, tenant_id, since, page, size)
        return []

    engine._fetch_from_cloud = fake_fetch
    engine._bulk_upsert_to_cloud = AsyncMock(return_value=True)

    result = await engine.full_sync("tenant-001")

    assert result["tables"]["orders"] == 10
    # 水位应从 epoch 开始（全量拉取不过滤）
    new_watermark = await tracker.get_watermark("orders")
    assert new_watermark != "1970-01-01T00:00:00+00:00", "全量同步后水位应更新"


@pytest.mark.asyncio
async def test_full_sync_first_run_has_epoch_watermark(tracker):
    """全量同步前，水位应该是 epoch（无历史状态）"""
    watermark = await tracker.get_watermark("orders")
    assert watermark == "1970-01-01T00:00:00+00:00"


# ═══════════════════════════════════════════════════════════════════════════
# 3. 冲突解决：云端优先，保留本地终态
# ═══════════════════════════════════════════════════════════════════════════

class TestConflictResolver:
    def test_remote_wins_by_default(self):
        """默认：云端优先"""
        local = _make_record(updated_at=_ts(-120), status="pending")
        remote = _make_record(updated_at=_ts(-60), status="processing")
        result = ConflictResolver.resolve(local, remote)
        assert result["status"] == "processing"

    def test_local_terminal_beats_remote_pending(self):
        """本地终态（done）不被远端非终态（pending）覆盖"""
        local = _make_record(updated_at=_ts(-30), status="done")
        remote = _make_record(updated_at=_ts(-60), status="pending")
        result = ConflictResolver.resolve(local, remote)
        assert result["status"] == "done"

    def test_local_served_beats_remote_pending(self):
        """本地 served 不被远端 pending 覆盖"""
        local = _make_record(updated_at=_ts(-10), status="served")
        remote = _make_record(updated_at=_ts(-5), status="pending")
        result = ConflictResolver.resolve(local, remote)
        assert result["status"] == "served"

    def test_remote_terminal_replaces_local_pending(self):
        """远端终态（cancelled）可以覆盖本地非终态"""
        local = _make_record(updated_at=_ts(-10), status="pending")
        remote = _make_record(updated_at=_ts(-5), status="cancelled")
        result = ConflictResolver.resolve(local, remote)
        assert result["status"] == "cancelled"

    def test_both_terminal_remote_wins(self):
        """本地和远端都是终态时，云端优先（远端 completed > 本地 done）"""
        local = _make_record(updated_at=_ts(-60), status="done")
        remote = _make_record(updated_at=_ts(-30), status="completed")
        result = ConflictResolver.resolve(local, remote)
        # 远端是终态，本地也是终态，但远端更新 → 远端优先
        assert result["status"] == "completed"

    def test_no_status_field_remote_wins(self):
        """无 status 字段时，云端优先"""
        local = {"id": "x", "updated_at": _ts(-60), "amount": 100}
        remote = {"id": "x", "updated_at": _ts(-30), "amount": 200}
        result = ConflictResolver.resolve(local, remote)
        assert result["amount"] == 200

    def test_local_newer_but_not_terminal_remote_wins(self):
        """本地更新但非终态时，云端优先"""
        local = _make_record(updated_at=_ts(-10), status="processing")
        remote = _make_record(updated_at=_ts(-60), status="pending")
        # local_ts > remote_ts 且 local 不是终态 → 本地也不保留，云端优先
        result = ConflictResolver.resolve(local, remote)
        assert result["status"] == "pending"

    def test_all_terminal_statuses_preserved(self):
        """所有终态关键词都正确识别"""
        for status in ("done", "served", "completed", "cancelled", "refunded", "closed"):
            local = _make_record(updated_at=_ts(-10), status=status)
            remote = _make_record(updated_at=_ts(-5), status="pending")
            result = ConflictResolver.resolve(local, remote)
            assert result["status"] == status, f"终态 {status} 应被保留"


# ═══════════════════════════════════════════════════════════════════════════
# 4. 幂等性：重复同步不产生重复数据
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_idempotent_incremental_sync(tracker):
    """重复运行增量同步，不产生重复记录"""
    records = [_make_record(f"order-{i}", updated_at=_ts(-i * 10)) for i in range(5)]
    engine, upserted = _make_engine(
        tracker, cloud_records_by_table={"orders": records}
    )
    engine._bulk_upsert_to_cloud = AsyncMock(return_value=True)

    # 第一次同步
    await engine.incremental_sync("tenant-001")
    count_after_first = len(upserted.get("orders", []))

    # 第二次同步（相同记录，水位已更新，不应再拉取相同记录）
    await engine.incremental_sync("tenant-001")
    count_after_second = len(upserted.get("orders", []))

    assert count_after_first == count_after_second, "重复同步不应增加记录数"


@pytest.mark.asyncio
async def test_idempotent_change_log(tracker):
    """重复写入 change_log，push 后幂等（已同步不重复推送）"""
    await tracker.log_change("orders", "order-1", "UPDATE", {"id": "order-1", "amount": 200})
    await tracker.log_change("orders", "order-1", "UPDATE", {"id": "order-1", "amount": 200})

    pending = await tracker.get_pending_changes()
    assert len(pending) == 2  # 两条记录（不同 rowid）

    ids = [p["id"] for p in pending]
    await tracker.mark_changes_synced(ids)

    after = await tracker.get_pending_changes()
    assert len(after) == 0


# ═══════════════════════════════════════════════════════════════════════════
# 5. 断网恢复：本地操作缓冲 → 恢复连接后增量推送
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_offline_buffer_and_recovery(tracker):
    """断网期间写入 change_log，恢复后 push_local_changes 发送并清空"""
    # 模拟离线期间 3 个本地变更
    for i in range(3):
        await tracker.log_change(
            "orders",
            f"order-{i}",
            "INSERT",
            _make_record(f"order-{i}"),
        )

    pending_before = await tracker.get_pending_count()
    assert pending_before == 3

    # 创建 engine 并模拟云端推送成功
    engine = SyncEngine(
        tracker=tracker,
        local_db_url="postgresql+asyncpg://fake/fake",
        cloud_api_url="http://fake-cloud",
    )
    engine._local_pool = MagicMock()

    pushed_batches: list[dict] = []

    async def fake_bulk_upsert(table, records, tenant_id):
        pushed_batches.append({"table": table, "records": records})
        return True

    engine._bulk_upsert_to_cloud = fake_bulk_upsert

    synced = await engine.push_local_changes("tenant-001")
    assert synced == 3, "应推送 3 条本地变更"

    pending_after = await tracker.get_pending_count()
    assert pending_after == 0, "推送后变更日志应清空"


@pytest.mark.asyncio
async def test_offline_push_fails_keeps_pending(tracker):
    """云端推送失败时，变更日志保持待同步状态"""
    await tracker.log_change("orders", "order-fail", "UPDATE", {"id": "order-fail"})

    engine = SyncEngine(
        tracker=tracker,
        local_db_url="postgresql+asyncpg://fake/fake",
        cloud_api_url="http://fake-cloud",
    )
    engine._local_pool = MagicMock()
    engine._bulk_upsert_to_cloud = AsyncMock(return_value=False)

    synced = await engine.push_local_changes("tenant-001")
    assert synced == 0

    # 变更日志应保留
    pending = await tracker.get_pending_count()
    assert pending == 1


@pytest.mark.asyncio
async def test_no_cloud_url_skips_push(tracker):
    """未设置 CLOUD_API_URL 时，push_local_changes 直接返回 0"""
    await tracker.log_change("orders", "order-1", "INSERT", {"id": "order-1"})

    engine = SyncEngine(
        tracker=tracker,
        local_db_url="postgresql+asyncpg://fake/fake",
        cloud_api_url="",  # 未设置
    )
    engine._local_pool = MagicMock()

    result = await engine.push_local_changes("tenant-001")
    assert result == 0
    # 变更日志未被清空
    assert await tracker.get_pending_count() == 1


# ═══════════════════════════════════════════════════════════════════════════
# 6. 大批量：10000 条记录分批同步（每批 500 条）
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_large_batch_split_into_pages(tracker):
    """10000 条记录被分批（每批 500）拉取"""
    total_records = 10_000
    records = [
        _make_record(f"order-{i}", updated_at=_ts(-i))
        for i in range(total_records)
    ]

    fetch_calls: list[dict] = []

    engine = SyncEngine(
        tracker=tracker,
        local_db_url="postgresql+asyncpg://fake/fake",
        cloud_api_url="http://fake-cloud",
        batch_size=500,
    )
    engine._local_pool = MagicMock()

    async def fake_fetch(table, tenant_id, since, page=1, size=500):
        fetch_calls.append({"table": table, "page": page, "size": size})
        start = (page - 1) * size
        chunk = records[start: start + size]
        return chunk

    upserted_ids: list[str] = []

    async def fake_upsert(table, batch, resolve_conflicts=True):
        upserted_ids.extend(r["id"] for r in batch)

    engine._fetch_from_cloud = fake_fetch
    engine._upsert_to_local = fake_upsert
    engine._apply_conflict_resolution = AsyncMock(side_effect=lambda t, r: asyncio.coroutine(lambda: r)())
    engine._bulk_upsert_to_cloud = AsyncMock(return_value=True)

    result = await engine.full_sync("tenant-001")

    assert result["tables"]["orders"] == total_records
    assert len(fetch_calls) >= total_records // 500, (
        f"应至少调用 {total_records // 500} 次分页拉取，实际 {len(fetch_calls)} 次"
    )
    # 批次大小不超过 500
    for call in fetch_calls:
        if call["table"] == "orders":
            assert call["size"] == 500


@pytest.mark.asyncio
async def test_large_batch_push(tracker):
    """1000 条本地变更分 2 批推送到云端"""
    for i in range(1000):
        await tracker.log_change(
            "orders", f"order-{i}", "INSERT", _make_record(f"order-{i}")
        )

    engine = SyncEngine(
        tracker=tracker,
        local_db_url="postgresql+asyncpg://fake/fake",
        cloud_api_url="http://fake-cloud",
        batch_size=500,
    )
    engine._local_pool = MagicMock()

    push_call_sizes: list[int] = []

    async def fake_bulk_upsert(table, records, tenant_id):
        push_call_sizes.append(len(records))
        return True

    engine._bulk_upsert_to_cloud = fake_bulk_upsert

    synced = await engine.push_local_changes("tenant-001")
    assert synced == 1000
    assert max(push_call_sizes) <= 500, "单批推送不超过 500 条"
    assert await tracker.get_pending_count() == 0


# ═══════════════════════════════════════════════════════════════════════════
# 7. SyncTracker 单元测试
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_tracker_watermark_default(tracker):
    """未设置水位时返回 epoch"""
    wm = await tracker.get_watermark("non_existent_table")
    assert wm == "1970-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_tracker_set_and_get_watermark(tracker):
    ts = _ts(-600)
    await tracker.set_watermark("orders", ts, record_count=100)
    got = await tracker.get_watermark("orders")
    assert got == ts


@pytest.mark.asyncio
async def test_tracker_reset_watermarks(tracker):
    ts = _ts(-600)
    await tracker.set_watermark("orders", ts)
    await tracker.reset_watermarks(["orders", "members"])
    assert await tracker.get_watermark("orders") == "1970-01-01T00:00:00+00:00"
    assert await tracker.get_watermark("members") == "1970-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_tracker_change_log_lifecycle(tracker):
    """完整变更日志生命周期：写入 → 查询 → 标记已同步"""
    await tracker.log_change("orders", "order-1", "INSERT", {"id": "order-1", "amount": 100})
    await tracker.log_change("orders", "order-2", "UPDATE", {"id": "order-2", "amount": 200})

    pending = await tracker.get_pending_changes()
    assert len(pending) == 2
    assert all(p["table_name"] == "orders" for p in pending)

    ids = [p["id"] for p in pending]
    await tracker.mark_changes_synced(ids)

    assert await tracker.get_pending_count() == 0


# ═══════════════════════════════════════════════════════════════════════════
# 8. 工具函数
# ═══════════════════════════════════════════════════════════════════════════

def test_max_updated_at_basic():
    records = [
        {"updated_at": "2026-01-01T10:00:00+00:00"},
        {"updated_at": "2026-01-01T12:00:00+00:00"},
        {"updated_at": "2026-01-01T11:00:00+00:00"},
    ]
    result = _max_updated_at(records)
    assert result == "2026-01-01T12:00:00+00:00"


def test_max_updated_at_empty():
    result = _max_updated_at([])
    assert result == "1970-01-01T00:00:00+00:00"


def test_max_updated_at_none_values():
    records = [{"updated_at": None}, {"updated_at": "2026-01-01T10:00:00+00:00"}]
    result = _max_updated_at(records)
    assert result == "2026-01-01T10:00:00+00:00"
