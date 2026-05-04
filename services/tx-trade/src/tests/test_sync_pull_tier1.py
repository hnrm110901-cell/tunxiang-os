"""Tier 1 — PG.4 云端 /api/v1/sync/pull SyncToken 双键增量契约测试

边缘 Mac mini 通过 (since_ts, since_seq) 复合游标拉取云端 events。
本套测试覆盖：

  1. 复合游标语义：返回 (ts > since_ts) OR (ts = since_ts AND seq > since_seq)
  2. 跨租户隔离：tenant_A 的 X-Tenant-ID 不能拉到 tenant_B 的事件
  3. 跨门店隔离：store_a 的 store_id 参数不能拉到 store_b 的事件
  4. max_seq 反映本批最大 sequence_num（边缘据此推进 SyncToken）
  5. 缺 X-Tenant-ID → 400
  6. 非法 since_ts → 400
  7. events 表不存在时 graceful 返回空（非 v147+ 环境兜底）

测试模式：mock AsyncSession.execute side_effect，验证传入 SQL 参数正确，
不依赖真实 PG。同 test_corporate_orders.py 模式。
"""

from __future__ import annotations

import json
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


def _row(**fields: Any) -> Any:
    """构造一条 events 行：同时支持 dict(zip(keys, row))"""
    return tuple(fields[k] for k in fields)


def _exec_result(rows: list[tuple], keys: list[str]) -> Any:
    """构造 result.all() / result.keys() 返回值"""
    result = MagicMock()
    result.keys.return_value = keys
    result.all.return_value = rows
    return result


def _make_app() -> tuple[FastAPI, AsyncMock]:
    """构建只挂 sync_ingest_router 的 mini FastAPI app + 注入 mock db"""
    app = FastAPI()
    app.include_router(sync_ingest_router.router)

    db = AsyncMock()

    async def _override_db():
        yield db

    # 反查 sync_ingest_router 实际依赖的 get_db
    from shared.ontology.src.database import get_db

    app.dependency_overrides[get_db] = _override_db
    return app, db


TENANT_A = str(uuid.UUID(int=0xAAAA))
TENANT_B = str(uuid.UUID(int=0xBBBB))
STORE_A = str(uuid.UUID(int=0x1111))
STORE_B = str(uuid.UUID(int=0x2222))

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


def _evt(seq: int, ts: datetime, store_id: str = STORE_A) -> tuple:
    return (
        str(uuid.uuid4()),
        seq,
        ts,
        "ORDER.PAID",
        f"order-{seq}",
        "order",
        store_id,
        {"total_fen": 8800},
        {"operator": "u-1"},
    )


# ──────────────────────────────────────────────────────────────────────────
# 场景 1：复合游标语义（since_ts + since_seq）
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pull_compound_cursor_filters_correctly():
    """SQL 参数应包含 since_ts/since_seq + tenant + store；返回 max_seq。"""
    app, db = _make_app()
    ts1 = datetime(2026, 5, 4, 10, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 5, 4, 10, 0, 1, tzinfo=timezone.utc)
    db.execute = AsyncMock(
        return_value=_exec_result(
            rows=[_evt(101, ts1), _evt(102, ts2)],
            keys=EVENTS_KEYS,
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/api/v1/sync/pull",
            params={
                "store_id": STORE_A,
                "since_ts": "2026-05-04T09:59:00+00:00",
                "since_seq": 100,
            },
            headers={"X-Tenant-ID": TENANT_A},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["count"] == 2
    assert data["max_seq"] == 102  # max(101, 102)
    assert data["items"][0]["seq"] == 101
    assert data["items"][1]["seq"] == 102
    assert data["items"][0]["event_type"] == "ORDER.PAID"

    # 验证 SQL 入参
    call_args = db.execute.await_args
    params = call_args.args[1]
    assert params["tenant_id"] == TENANT_A
    assert params["store_id"] == STORE_A
    assert params["since_seq"] == 100
    assert isinstance(params["since_ts"], datetime)
    assert params["since_ts"].tzinfo is not None  # 时区未丢失


# ──────────────────────────────────────────────────────────────────────────
# 场景 2：tenant 隔离 — header tenant 必须传到 SQL WHERE
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pull_tenant_isolation_via_sql_param():
    """tenant_A 请求时，SQL params.tenant_id 必须是 A 而非任何其他值。"""
    app, db = _make_app()
    db.execute = AsyncMock(return_value=_exec_result(rows=[], keys=EVENTS_KEYS))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/api/v1/sync/pull",
            params={"store_id": STORE_A},
            headers={"X-Tenant-ID": TENANT_B},
        )

    assert resp.status_code == 200
    params = db.execute.await_args.args[1]
    assert params["tenant_id"] == TENANT_B
    assert params["tenant_id"] != TENANT_A


# ──────────────────────────────────────────────────────────────────────────
# 场景 3：store 隔离 — store_id query 必须传到 SQL WHERE
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pull_store_isolation_via_sql_param():
    app, db = _make_app()
    db.execute = AsyncMock(return_value=_exec_result(rows=[], keys=EVENTS_KEYS))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/api/v1/sync/pull",
            params={"store_id": STORE_B},
            headers={"X-Tenant-ID": TENANT_A},
        )

    assert resp.status_code == 200
    params = db.execute.await_args.args[1]
    assert params["store_id"] == STORE_B


# ──────────────────────────────────────────────────────────────────────────
# 场景 4：max_seq 推进 — 仅看到本批最大 sequence_num
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pull_max_seq_reflects_batch_maximum():
    """max_seq = max(items.seq) 用于边缘推进 SyncToken。空批返回 since_seq。"""
    app, db = _make_app()
    ts = datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc)
    db.execute = AsyncMock(
        return_value=_exec_result(
            rows=[_evt(50, ts), _evt(75, ts), _evt(60, ts)],  # 乱序 max=75
            keys=EVENTS_KEYS,
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/api/v1/sync/pull",
            params={"store_id": STORE_A, "since_seq": 49},
            headers={"X-Tenant-ID": TENANT_A},
        )

    assert resp.json()["data"]["max_seq"] == 75


@pytest.mark.asyncio
async def test_pull_empty_batch_keeps_since_seq_as_max():
    """空批 → max_seq == since_seq，边缘 SyncToken 不会回退"""
    app, db = _make_app()
    db.execute = AsyncMock(return_value=_exec_result(rows=[], keys=EVENTS_KEYS))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/api/v1/sync/pull",
            params={"store_id": STORE_A, "since_seq": 999},
            headers={"X-Tenant-ID": TENANT_A},
        )

    body = resp.json()["data"]
    assert body["count"] == 0
    assert body["max_seq"] == 999


# ──────────────────────────────────────────────────────────────────────────
# 场景 5：缺 X-Tenant-ID → 400
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pull_missing_tenant_returns_400():
    app, _db = _make_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/v1/sync/pull", params={"store_id": STORE_A})

    assert resp.status_code == 400
    assert "X-Tenant-ID" in resp.json()["detail"]


# ──────────────────────────────────────────────────────────────────────────
# 场景 6：非法 since_ts → 400
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pull_invalid_since_ts_returns_400():
    app, _db = _make_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/api/v1/sync/pull",
            params={"store_id": STORE_A, "since_ts": "not-a-timestamp"},
            headers={"X-Tenant-ID": TENANT_A},
        )

    assert resp.status_code == 400
    assert "since_ts" in resp.json()["detail"]


# ──────────────────────────────────────────────────────────────────────────
# 场景 7：events 表不存在 → 优雅返回空（非 v147+ 兜底）
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pull_events_table_missing_returns_empty():
    app, db = _make_app()
    db.execute = AsyncMock(side_effect=OperationalError("stmt", {}, Exception("relation 'events' does not exist")))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/api/v1/sync/pull",
            params={"store_id": STORE_A, "since_seq": 42},
            headers={"X-Tenant-ID": TENANT_A},
        )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["items"] == []
    assert body["count"] == 0
    assert body["max_seq"] == 42  # 不回退


# ──────────────────────────────────────────────────────────────────────────
# 场景 8：payload/metadata JSON string 也能被反序列化
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pull_payload_string_jsonb_deserialized():
    """部分驱动会把 JSONB 返成 str — 路由必须 json.loads 而不是直接挂 str"""
    app, db = _make_app()
    ts = datetime(2026, 5, 4, 13, 0, 0, tzinfo=timezone.utc)
    row = (
        str(uuid.uuid4()),  # event_id
        77,  # sequence_num
        ts,
        "ORDER.PAID",
        "order-77",
        "order",
        STORE_A,
        json.dumps({"total_fen": 12300}),  # payload as str
        json.dumps({"channel": "dine-in"}),  # metadata as str
    )
    db.execute = AsyncMock(return_value=_exec_result(rows=[row], keys=EVENTS_KEYS))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(
            "/api/v1/sync/pull",
            params={"store_id": STORE_A},
            headers={"X-Tenant-ID": TENANT_A},
        )

    item = resp.json()["data"]["items"][0]
    assert item["payload"] == {"total_fen": 12300}
    assert item["metadata"] == {"channel": "dine-in"}
