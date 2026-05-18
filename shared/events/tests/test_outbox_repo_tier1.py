"""shared.events.outbox_repo helper — Tier 1 邻接单元测试.

W3 D1 PR-1 C 方案 helper-only — 5 测试用 mock AsyncSession, 不真访问 PG:

1. test_insert_returns_uuid                       — happy path
2. test_insert_calls_set_config_for_rls           — RLS set_config 必备
3. test_insert_raises_outbox_error_on_sqlalchemy_error — 异常路径 chained __cause__
4. test_insert_serializes_payload_to_json         — dict → json.dumps 进 INSERT
5. test_insert_passes_optional_fields_as_none     — 可选字段不传 → None (非 'None' 字符串)

文件名带 ``tier1`` 后缀 per memory `feedback_tier1_test_filename_workflow_trigger.md`;
但本 PR 在 ``shared/events/tests/`` 下, tier1-gate.yml glob
``services/**/src/tests/**/*tier1*.py`` **不匹配** → §25 邻接豁免, 与 PR #823 同模式.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from shared.events.src.outbox_repo import OutboxInsertError
from shared.events.src.outbox_repo import insert as outbox_insert


def _mock_db_with_insert_id(insert_id: UUID) -> AsyncMock:
    """构造 mock AsyncSession, INSERT ... RETURNING 返一行 (insert_id,)."""
    db = AsyncMock()
    # set_config 调用返 mock result (不取值)
    set_result = MagicMock()
    # INSERT RETURNING 调用返 mock result with fetchone -> (uuid,)
    insert_result = MagicMock()
    insert_result.fetchone = MagicMock(return_value=(insert_id,))
    db.execute = AsyncMock(side_effect=[set_result, insert_result])
    return db


@pytest.mark.asyncio
async def test_insert_returns_uuid() -> None:
    """happy path: INSERT RETURNING 一行 → outbox_repo.insert() 返 UUID."""
    expected_id = uuid4()
    db = _mock_db_with_insert_id(expected_id)
    tenant_id = uuid4()

    returned = await outbox_insert(
        db=db,
        tenant_id=tenant_id,
        event_type="order.paid",
        stream_id="order-abc-123",
        payload={"total_fen": 8800, "channel": "dine_in"},
        source_service="tx-trade",
    )

    assert isinstance(returned, UUID)
    assert returned == expected_id


@pytest.mark.asyncio
async def test_insert_calls_set_config_for_rls() -> None:
    """RLS 强约束: 第一次 db.execute 必须是 set_config('app.tenant_id', :tid, true)."""
    db = _mock_db_with_insert_id(uuid4())
    tenant_id = uuid4()

    await outbox_insert(
        db=db,
        tenant_id=tenant_id,
        event_type="order.paid",
        stream_id="order-1",
        payload={},
        source_service="tx-trade",
    )

    # 至少 2 次 execute (set_config + INSERT)
    assert db.execute.await_count >= 2, (
        f"expected >= 2 db.execute calls (set_config + INSERT), got {db.execute.await_count}"
    )
    first_call_args = db.execute.await_args_list[0]
    first_sql = str(first_call_args.args[0]).strip()
    assert "set_config" in first_sql, f"first execute should be set_config, got: {first_sql}"
    assert "app.tenant_id" in first_sql
    assert first_call_args.args[1] == {"tid": str(tenant_id)}


@pytest.mark.asyncio
async def test_insert_raises_outbox_error_on_sqlalchemy_error() -> None:
    """SQLAlchemyError → OutboxInsertError, 原异常 chained 在 __cause__."""
    db = AsyncMock()
    set_result = MagicMock()
    original_exc = SQLAlchemyError("simulated PG connection drop")
    # set_config OK, INSERT raise
    db.execute = AsyncMock(side_effect=[set_result, original_exc])

    with pytest.raises(OutboxInsertError) as exc_info:
        await outbox_insert(
            db=db,
            tenant_id=uuid4(),
            event_type="order.paid",
            stream_id="order-fail",
            payload={"total_fen": 100},
            source_service="tx-trade",
        )

    assert exc_info.value.__cause__ is original_exc, (
        "原 SQLAlchemyError 应通过 __cause__ chain 暴露给 caller"
    )
    assert "simulated PG connection drop" in str(exc_info.value)


@pytest.mark.asyncio
async def test_insert_serializes_payload_to_json() -> None:
    """payload dict → json.dumps 进 INSERT 参数, metadata 同样.

    防 caller 误传 bytes / 防字段错位.
    """
    db = _mock_db_with_insert_id(uuid4())
    payload = {"total_fen": 8800, "channel": "dine_in", "nested": {"k": "v"}}
    metadata = {"operator_id": "emp-001", "device": "pos_main"}

    await outbox_insert(
        db=db,
        tenant_id=uuid4(),
        event_type="order.paid",
        stream_id="order-1",
        payload=payload,
        source_service="tx-trade",
        metadata=metadata,
    )

    # 第二次 execute 是 INSERT, 第二个位置参是 params dict
    insert_call = db.execute.await_args_list[1]
    params = insert_call.args[1]
    assert params["payload"] == json.dumps(payload)
    assert params["metadata"] == json.dumps(metadata)


@pytest.mark.asyncio
async def test_insert_passes_optional_fields_as_none() -> None:
    """可选字段 store_id/causation_id/correlation_id 不传 → None (非 'None' string).

    防 caller 看到 ``str(None)='None'`` 误以为 PG UUID 字段会 NULL.
    """
    db = _mock_db_with_insert_id(uuid4())

    await outbox_insert(
        db=db,
        tenant_id=uuid4(),
        event_type="order.paid",
        stream_id="order-1",
        payload={},
        source_service="tx-trade",
        # store_id / causation_id / correlation_id / metadata 全省
    )

    insert_call = db.execute.await_args_list[1]
    params = insert_call.args[1]
    assert params["store_id"] is None
    assert params["causation_id"] is None
    assert params["correlation_id"] is None
    # metadata 不传 → 默认 {} → json.dumps({})
    assert params["metadata"] == json.dumps({})


@pytest.mark.asyncio
async def test_insert_raises_outbox_error_on_set_config_failure() -> None:
    """set_config 抛 SQLAlchemyError 时, 也 wrap 为 OutboxInsertError (P1-1).

    验证 set_config 已在 try 块内: session 污染 (InFailedSqlTransactionError)
    等 SQLAlchemyError 不再裸穿透到 caller, 统一 wrap 为 OutboxInsertError.
    """
    db = AsyncMock()
    original_exc = SQLAlchemyError("RLS set_config failed: connection drop")
    # 第 1 次 execute (set_config) 就抛
    db.execute = AsyncMock(side_effect=original_exc)

    with pytest.raises(OutboxInsertError) as exc_info:
        await outbox_insert(
            db=db,
            tenant_id=uuid4(),
            event_type="order.paid",
            stream_id="ORD-001",
            payload={"amount": 100},
            source_service="tx-trade",
        )

    assert exc_info.value.__cause__ is original_exc, (
        "set_config 异常应通过 __cause__ chain 暴露给 caller"
    )
    assert "outbox INSERT failed" in str(exc_info.value)
