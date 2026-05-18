"""W3 D2 PR-1 测试: tx_events_emit_total Counter 行为验证

战略 plan §6 真 Outbox 决策矩阵分母 — 验证:
1. emit_event 同步路径 .inc(result="success") 触发 1 次 (sync path: await emit_event(...))
2. asyncio.create_task fire-and-forget 路径 .inc(result="success") 触发 1 次
3. PG 写入失败 silent swallow 路径 .inc(result="exception") + return None (fail-open 契约)
4. tenant_id_short cardinality 稳定性: 同 tenant_id 多次 emit → labels 一致
5. (round-2 critic P1-2) prometheus_client .inc() raise → emit_event 仍 return event_id 不抛
6. (round-2 critic P1-2) PG raise → inc(result="exception") + return None

对齐 feedback_multiline_grep_kwargs.md: mock 必抓跨行 await kwargs.
对齐 feedback_async_session_select_pollution.md / feedback_asyncpg_rollback_after_integrity_error.md:
exception 路径 return None 不污染 caller, emit_event 是 fire-and-forget 旁路.
"""

from __future__ import annotations

from unittest.mock import ANY, AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from shared.events.src.emitter import _tenant_id_short, emit_event

TENANT_A = UUID("11111111-1111-1111-1111-111111111111")
TENANT_B = UUID("22222222-2222-2222-2222-222222222222")
STORE_X = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


# ──────────────────────────────────────────────────────────────────────
# tenant_id_short 哈希稳定性
# ──────────────────────────────────────────────────────────────────────


class TestTenantIdShort:
    def test_same_uuid_same_hash(self) -> None:
        """同 UUID 多次调用 → 哈希一致 (Prometheus label cardinality 防爆)."""
        h1 = _tenant_id_short(TENANT_A)
        h2 = _tenant_id_short(TENANT_A)
        h3 = _tenant_id_short(TENANT_A)
        assert h1 == h2 == h3

    def test_different_uuid_different_hash(self) -> None:
        """不同 UUID → 哈希不同 (collision 极不可能于 8 hex × <100 tenant)."""
        assert _tenant_id_short(TENANT_A) != _tenant_id_short(TENANT_B)

    def test_hash_length_8_hex(self) -> None:
        """哈希为 8 字符 hex (sha256[:8])."""
        h = _tenant_id_short(TENANT_A)
        assert len(h) == 8
        assert all(c in "0123456789abcdef" for c in h)

    def test_string_tenant_id_supported(self) -> None:
        """tenant_id 可为 str (向后兼容 emit_event signature: UUID | str)."""
        h_uuid = _tenant_id_short(TENANT_A)
        h_str = _tenant_id_short(str(TENANT_A))
        assert h_uuid == h_str

    def test_none_tenant_id_returns_fallback(self) -> None:
        """(round-2 P2-3) tenant_id=None → fallback "unknown_" (8 char), 不 raise."""
        h = _tenant_id_short(None)
        assert h == "unknown_"
        assert len(h) == 8


# ──────────────────────────────────────────────────────────────────────
# emit_event Counter .inc() 触发验证
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestEmitEventCounter:
    async def test_sync_path_increments_counter_once_with_result_success(self) -> None:
        """await emit_event(...) 正常路径 → .inc() 触发 1 次, result="success"."""
        mock_counter = MagicMock()
        mock_labels = MagicMock()
        mock_counter.labels.return_value = mock_labels

        with (
            patch("shared.events.src.emitter.tx_events_emit_total", mock_counter),
            patch(
                "shared.events.src.emitter.PgEventStore.append",
                new_callable=AsyncMock,
                return_value="event-id-1",
            ),
            patch(
                "shared.events.src.emitter._publish_to_redis",
                new_callable=AsyncMock,
            ),
        ):
            event_id = await emit_event(
                event_type="order.paid",
                tenant_id=TENANT_A,
                stream_id="order-123",
                payload={"total_fen": 8800},
                store_id=STORE_X,
                source_service="tx-trade",
            )

        assert event_id == "event-id-1"
        assert mock_counter.labels.call_count == 1
        mock_counter.labels.assert_called_once_with(
            tenant_id_short=_tenant_id_short(TENANT_A),
            event_type="order.paid",
            source_service="tx-trade",
            result="success",
        )
        assert mock_labels.inc.call_count == 1

    async def test_fire_and_forget_path_increments_counter_once(self) -> None:
        """asyncio.create_task(emit_event(...)) → .inc(result="success") 触发 1 次.

        per CLAUDE.md §15 事件总线规范: 业务代码用 create_task 旁路写入.
        """
        import asyncio

        mock_counter = MagicMock()
        mock_labels = MagicMock()
        mock_counter.labels.return_value = mock_labels

        with (
            patch("shared.events.src.emitter.tx_events_emit_total", mock_counter),
            patch(
                "shared.events.src.emitter.PgEventStore.append",
                new_callable=AsyncMock,
                return_value="event-id-2",
            ),
            patch(
                "shared.events.src.emitter._publish_to_redis",
                new_callable=AsyncMock,
            ),
        ):
            task = asyncio.create_task(
                emit_event(
                    event_type="discount.applied",
                    tenant_id=TENANT_A,
                    stream_id="order-456",
                    payload={"discount_fen": 1200},
                    source_service="tx-trade",
                )
            )
            await task

        assert mock_labels.inc.call_count == 1
        mock_counter.labels.assert_called_once_with(
            tenant_id_short=_tenant_id_short(TENANT_A),
            event_type="discount.applied",
            source_service="tx-trade",
            result="success",
        )

    async def test_pg_returns_none_still_increments_success(self) -> None:
        """PG 写入静默返回 None (PgEventStore 内部 swallow) → .inc(result="success") 仍触发.

        决策矩阵分母语义: PgEventStore.append 已在内部 silent swallow 写入失败 (return None);
        emit_event 视角看是正常 await 完成 = success. 真异常路径见
        test_pg_raise_increments_exception_result.
        """
        mock_counter = MagicMock()
        mock_labels = MagicMock()
        mock_counter.labels.return_value = mock_labels

        with (
            patch("shared.events.src.emitter.tx_events_emit_total", mock_counter),
            patch(
                "shared.events.src.emitter.PgEventStore.append",
                new_callable=AsyncMock,
                return_value=None,  # PG silent fallback returns None
            ),
            patch(
                "shared.events.src.emitter._publish_to_redis",
                new_callable=AsyncMock,
            ),
        ):
            event_id = await emit_event(
                event_type="payment.confirmed",
                tenant_id=TENANT_A,
                stream_id="order-789",
                payload={"amount_fen": 5000},
                source_service="tx-trade",
            )

        # PG returns None (not raise) → emit_event 视角为 success
        assert event_id is None
        assert mock_labels.inc.call_count == 1
        mock_counter.labels.assert_called_once_with(
            tenant_id_short=_tenant_id_short(TENANT_A),
            event_type="payment.confirmed",
            source_service="tx-trade",
            result="success",
        )

    async def test_event_type_enum_value_extracted_for_label(self) -> None:
        """event_type 是 enum (有 .value 属性) → label 用 .value 字符串.

        per CLAUDE.md §15 事件类型规则: 用 event_types.py 枚举, 不硬编码字符串.
        """

        class _MockEnum:
            value = "inventory.consumed"

        mock_counter = MagicMock()
        mock_labels = MagicMock()
        mock_counter.labels.return_value = mock_labels

        with (
            patch("shared.events.src.emitter.tx_events_emit_total", mock_counter),
            patch(
                "shared.events.src.emitter.PgEventStore.append",
                new_callable=AsyncMock,
                return_value="event-id-3",
            ),
            patch(
                "shared.events.src.emitter._publish_to_redis",
                new_callable=AsyncMock,
            ),
        ):
            await emit_event(
                event_type=_MockEnum(),
                tenant_id=TENANT_A,
                stream_id="ingr-001",
                payload={"qty": 5},
                source_service="tx-supply",
            )

        mock_counter.labels.assert_called_once_with(
            tenant_id_short=_tenant_id_short(TENANT_A),
            event_type="inventory.consumed",  # 从 enum.value 提取
            source_service="tx-supply",
            result="success",
        )

    async def test_cardinality_stable_for_same_tenant_multiple_emits(self) -> None:
        """同 tenant_id 多次 emit → labels(tenant_id_short=...) 调用值一致.

        Prometheus label cardinality 稳定性核心约束: tenant active < 100,
        若 tenant_id_short 不稳定则单 tenant 创建多个 time series 爆 cardinality.
        """
        mock_counter = MagicMock()
        mock_labels = MagicMock()
        mock_counter.labels.return_value = mock_labels

        with (
            patch("shared.events.src.emitter.tx_events_emit_total", mock_counter),
            patch(
                "shared.events.src.emitter.PgEventStore.append",
                new_callable=AsyncMock,
                return_value="event-id-4",
            ),
            patch(
                "shared.events.src.emitter._publish_to_redis",
                new_callable=AsyncMock,
            ),
        ):
            for i in range(5):
                await emit_event(
                    event_type="order.paid",
                    tenant_id=TENANT_A,
                    stream_id=f"order-{i}",
                    payload={"total_fen": 8800},
                    source_service="tx-trade",
                )

        # 5 次 emit → 5 次 .labels() 调用
        assert mock_counter.labels.call_count == 5

        # 所有 .labels() 调用的 tenant_id_short 值必须相同, result 都是 success
        expected_short = _tenant_id_short(TENANT_A)
        for call in mock_counter.labels.call_args_list:
            assert call.kwargs["tenant_id_short"] == expected_short
            assert call.kwargs["result"] == "success"

        # 5 次 .inc()
        assert mock_labels.inc.call_count == 5

    # ──────────────────────────────────────────────────────────────────
    # round-2 critic P1-2: contract regression tests
    # ──────────────────────────────────────────────────────────────────

    async def test_counter_raise_does_not_break_emit_event(self) -> None:
        """(round-2 critic P0-1 契约): prometheus_client .inc() raise → emit_event 仍 return event_id 不抛.

        极少 raise 场景 (registry corruption / label cardinality 爆) 不可破 emit_event
        fail-open 契约; 内层 try/except 包 .inc() 仅 logger.warning 不传播.
        """
        mock_counter = MagicMock()
        mock_counter.labels.return_value.inc.side_effect = RuntimeError(
            "fake prom registry corruption"
        )

        with (
            patch("shared.events.src.emitter.tx_events_emit_total", mock_counter),
            patch(
                "shared.events.src.emitter.PgEventStore.append",
                new_callable=AsyncMock,
                return_value="event-id-counter-raise",
            ),
            patch(
                "shared.events.src.emitter._publish_to_redis",
                new_callable=AsyncMock,
            ),
        ):
            result = await emit_event(
                event_type="order.paid",
                tenant_id=TENANT_A,
                stream_id="order-counter-raise",
                payload={"total_fen": 1000},
                source_service="tx-trade",
            )

        # 契约保: counter 抛不影响业务 return
        assert result == "event-id-counter-raise"
        # 仍尝试 inc (虽然 raise)
        assert mock_counter.labels.return_value.inc.call_count == 1

    async def test_pg_raise_increments_exception_result(self) -> None:
        """(round-2 critic P0-2 result label): PG fail → inc(result="exception") + return None.

        外层 try/except 捕 PG raise; emit_event 返 None (fail-open 契约 — 旁路写入不抛);
        Counter 标 result="exception" 让决策矩阵公式可算: 失败率 = relay / sum(result="success").
        """
        mock_counter = MagicMock()
        mock_labels = MagicMock()
        mock_counter.labels.return_value = mock_labels

        with (
            patch("shared.events.src.emitter.tx_events_emit_total", mock_counter),
            patch(
                "shared.events.src.emitter.PgEventStore.append",
                new_callable=AsyncMock,
                side_effect=RuntimeError("PG connection lost"),
            ),
            patch(
                "shared.events.src.emitter._publish_to_redis",
                new_callable=AsyncMock,
            ),
        ):
            result = await emit_event(
                event_type="order.paid",
                tenant_id=TENANT_A,
                stream_id="order-pg-raise",
                payload={"total_fen": 1000},
                source_service="tx-trade",
            )

        # fail-open: return None 不抛
        assert result is None
        # exception 路径 .inc() 触发 1 次, result="exception"
        assert mock_labels.inc.call_count == 1
        mock_counter.labels.assert_called_with(
            tenant_id_short=ANY,
            event_type="order.paid",
            source_service="tx-trade",
            result="exception",
        )


# ──────────────────────────────────────────────────────────────────────
# Counter 模块级符号导出验证 (caller 可 import)
# ──────────────────────────────────────────────────────────────────────


def test_tx_events_emit_total_is_importable() -> None:
    """tx_events_emit_total 必须是 shared.events.src.emitter 模块级符号.

    下游 tx-event-relay / dashboard 可能直接引用此 Counter 对象.
    """
    from shared.events.src import emitter

    assert hasattr(emitter, "tx_events_emit_total")
    # 真 Counter 或 no-op stub 都至少有 .labels 属性
    assert hasattr(emitter.tx_events_emit_total, "labels")
