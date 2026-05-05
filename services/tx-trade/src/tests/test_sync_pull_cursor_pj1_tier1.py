"""Tier 1 — PJ.1 sync/pull 三键 cursor + OperationalError 收窄反退化测试

PG.4 PR 上线后 CodeRabbit 发现两处 P1：

  1. 复合游标 (recorded_at, sequence_num) 二元组允许重复 →
     若同一 (ts, seq) 出现多条 events（v147 emit_event 并发场景下
     sequence_num 缺省值 0），客户端拿到 max_seq cursor 后下一轮
     `(ts, seq) > cursor` 比较会跳过同 cursor 剩余事件 → 静默数据丢失。
     修复：引入 events.event_id (UUID PK) 作为第三键 tiebreaker。

  2. except OperationalError: 兜底吞掉所有 DB 故障（连接断、磁盘满、
     lock timeout、无权限等）→ 客户端拿空响应误判同步完成。
     修复：仅当错误包含 "events" + "does not exist" 才走空响应，
     其他 OperationalError 必须 raise，让上游可见。

测试覆盖：
  - SQL 包含 event_id 三键比较与 ORDER BY
  - since_id 参数透传至 SQL params
  - 旧二元组客户端兼容（不传 since_id → 零 UUID）
  - max_event_id 反映本批最大 event_id
  - 同 (ts, seq) 多事件场景下 cursor 推进保留全部条目
  - OperationalError "events does not exist" → 优雅空响应
  - OperationalError 其他原因 → 必须冒泡（不能吞）
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError

from src.routers import sync_ingest_router

# ──────────────── helpers ────────────────


def _exec_result(rows: list[tuple], keys: list[str]) -> Any:
    result = MagicMock()
    result.keys.return_value = keys
    result.all.return_value = rows
    return result


def _make_app() -> tuple[FastAPI, AsyncMock]:
    app = FastAPI()
    app.include_router(sync_ingest_router.router)

    db = AsyncMock()

    async def _override_db():
        yield db

    from shared.ontology.src.database import get_db

    app.dependency_overrides[get_db] = _override_db
    return app, db


TENANT = str(uuid.UUID(int=0xAAAA))
STORE = str(uuid.UUID(int=0x1111))
ZERO_UUID = "00000000-0000-0000-0000-000000000000"

EVENTS_KEYS = [
    "event_id",
    "sequence_num",
    "recorded_at",
    "event_type",
    "stream_id",
    "stream_type",
    "store_id",
    "payload",
    "metadata",
]


def _evt(seq: int, ts: datetime, event_id: str | None = None) -> tuple:
    return (
        event_id or str(uuid.uuid4()),
        seq,
        ts,
        "ORDER.PAID",
        f"order-{seq}",
        "order",
        STORE,
        {"total_fen": 8800},
        {"operator": "u-1"},
    )


# ──────────────────────────────────────────────────────────────────────────
# Bug A 守门：三键 tiebreaker 必须在 SQL 里
# ──────────────────────────────────────────────────────────────────────────


def test_pull_sql_contains_event_id_third_tiebreaker():
    """source-level 检查：sync_ingest_router.py 的 /pull SQL 必须包含 event_id 三键比较。

    防止 PR 回退到 (ts, seq) 二键。
    """
    src = sync_ingest_router.__file__
    with open(src, encoding="utf-8") as f:
        text_body = f.read()

    # 必须有 event_id > :since_id 模式（允许跨行+空白）
    assert re.search(
        r"event_id\s*>\s*CAST\(\s*:since_id",
        text_body,
    ), "SQL 缺少 event_id 第三键比较（PJ.1 数据丢失风险）"

    # ORDER BY 必须有三键
    assert re.search(
        r"ORDER\s+BY\s+recorded_at\s+ASC,\s*sequence_num\s+ASC,\s*event_id\s+ASC",
        text_body,
        flags=re.IGNORECASE,
    ), "SQL ORDER BY 缺少 event_id 第三键（PJ.1）"


# ──────────────────────────────────────────────────────────────────────────
# Bug A 行为：since_id 必须透传到 SQL params
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pull_passes_since_id_to_sql_params():
    """显式 since_id 必须传到 SQL bind params。"""
    app, db = _make_app()
    db.execute = AsyncMock(return_value=_exec_result(rows=[], keys=EVENTS_KEYS))

    custom_id = "11111111-1111-1111-1111-111111111111"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/api/v1/sync/pull",
            params={
                "store_id": STORE,
                "since_ts": "2026-05-04T09:00:00+00:00",
                "since_seq": 42,
                "since_id": custom_id,
            },
            headers={"X-Tenant-ID": TENANT},
        )

    assert resp.status_code == 200
    params = db.execute.await_args.args[1]
    assert params["since_id"] == custom_id
    assert params["since_seq"] == 42


@pytest.mark.asyncio
async def test_pull_legacy_two_key_cursor_defaults_to_zero_uuid():
    """旧客户端不传 since_id → 后端默认零 UUID，行为等价于二键比较。"""
    app, db = _make_app()
    db.execute = AsyncMock(return_value=_exec_result(rows=[], keys=EVENTS_KEYS))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/api/v1/sync/pull",
            params={"store_id": STORE, "since_seq": 99},
            headers={"X-Tenant-ID": TENANT},
        )

    assert resp.status_code == 200
    params = db.execute.await_args.args[1]
    assert params["since_id"] == ZERO_UUID  # 缺省值
    assert params["since_seq"] == 99


# ──────────────────────────────────────────────────────────────────────────
# Bug A 行为：同 (ts, seq) 多事件 cursor 推进必须保留全部条目
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pull_same_ts_seq_advances_cursor_by_event_id():
    """同 (recorded_at, sequence_num=0) 的两条事件，max_event_id 必须等于排序后最后一条。

    这是数据丢失修复的核心：边缘下一轮拉取时用 max_event_id 作为 since_id，
    server 端 `event_id > since_id` 才能取到剩余事件。
    """
    app, db = _make_app()
    ts = datetime(2026, 5, 4, 10, 0, 0, tzinfo=timezone.utc)
    eid_a = "10000000-0000-0000-0000-00000000000a"
    eid_b = "10000000-0000-0000-0000-00000000000b"  # 字典序 > eid_a

    # 模拟数据库按 ORDER BY (ts, seq, event_id) 排序后返回 [A, B]
    db.execute = AsyncMock(
        return_value=_exec_result(
            rows=[
                _evt(0, ts, event_id=eid_a),
                _evt(0, ts, event_id=eid_b),
            ],
            keys=EVENTS_KEYS,
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/api/v1/sync/pull",
            params={"store_id": STORE, "since_seq": 0},
            headers={"X-Tenant-ID": TENANT},
        )

    body = resp.json()["data"]
    assert body["count"] == 2
    assert body["max_seq"] == 0  # 同 seq 重复正常
    assert body["max_event_id"] == eid_b  # 三键 cursor 推进


@pytest.mark.asyncio
async def test_pull_empty_batch_max_event_id_keeps_since_id():
    """空批 → max_event_id == since_id（边缘 cursor 不回退）"""
    app, db = _make_app()
    db.execute = AsyncMock(return_value=_exec_result(rows=[], keys=EVENTS_KEYS))

    custom_id = "22222222-2222-2222-2222-222222222222"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/api/v1/sync/pull",
            params={"store_id": STORE, "since_id": custom_id},
            headers={"X-Tenant-ID": TENANT},
        )

    assert resp.json()["data"]["max_event_id"] == custom_id


# ──────────────────────────────────────────────────────────────────────────
# Bug B 行为：OperationalError 收窄
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pull_operational_error_events_missing_returns_empty():
    """events 表不存在（非 v147+ 环境）→ 优雅空响应（保留兜底）"""
    app, db = _make_app()
    db.execute = AsyncMock(
        side_effect=OperationalError(
            "stmt",
            {},
            Exception('relation "events" does not exist'),
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/api/v1/sync/pull",
            params={"store_id": STORE, "since_seq": 42},
            headers={"X-Tenant-ID": TENANT},
        )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["items"] == []
    assert body["max_seq"] == 42


@pytest.mark.asyncio
async def test_pull_operational_error_unrelated_must_propagate():
    """非 events 表的 OperationalError（连接断/磁盘满/lock 超时）必须冒泡，
    不能吞成空响应骗客户端。

    用 pytest.raises 直接断言异常冒出（ASGITransport 不会转 500）。
    旧 catch-all 行为会吞成 200 + items=[]，新行为必须 raise。
    """
    app, db = _make_app()
    db.execute = AsyncMock(
        side_effect=OperationalError(
            "stmt",
            {},
            Exception("connection to server was lost: server closed the connection unexpectedly"),
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        with pytest.raises(OperationalError):
            await c.get(
                "/api/v1/sync/pull",
                params={"store_id": STORE, "since_seq": 42},
                headers={"X-Tenant-ID": TENANT},
            )


@pytest.mark.asyncio
async def test_pull_operational_error_lock_timeout_must_propagate():
    """lock timeout 是真故障，不能吞。"""
    app, db = _make_app()
    db.execute = AsyncMock(
        side_effect=OperationalError(
            "stmt",
            {},
            Exception("canceling statement due to lock timeout"),
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        with pytest.raises(OperationalError):
            await c.get(
                "/api/v1/sync/pull",
                params={"store_id": STORE},
                headers={"X-Tenant-ID": TENANT},
            )


# ──────────────────────────────────────────────────────────────────────────
# 响应模型：max_event_id 字段必须存在
# ──────────────────────────────────────────────────────────────────────────


def test_pull_response_model_has_max_event_id_field():
    """PullResponse 必须含 max_event_id 字段（边缘 SyncToken 需要它续传）"""
    fields = sync_ingest_router.PullResponse.model_fields
    assert "max_event_id" in fields, "PullResponse 缺 max_event_id（PJ.1 三键 cursor）"
