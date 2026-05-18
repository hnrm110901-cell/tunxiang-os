"""W3 D2 PR-1 测试: tx_emit_event_total Counter 行为验证

战略 plan §6 真 Outbox 决策矩阵分母 — 验证:
1. emit_event 同步路径 .inc() 触发 1 次 (sync path: await emit_event(...))
2. asyncio.create_task fire-and-forget 路径 .inc() 触发 1 次 (常见调用模式)
3. PG 写入失败 silent swallow 路径 .inc() 仍触发 (在 try 前调用的设计)
4. tenant_id_short cardinality 稳定性: 同 tenant_id 多次 emit → labels 一致

对齐 feedback_multiline_grep_kwargs.md: mock 必抓跨行 await kwargs.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
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


# ──────────────────────────────────────────────────────────────────────
# emit_event Counter .inc() 触发验证
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestEmitEventCounter:
    async def test_sync_path_increments_counter_once(self) -> None:
        """await emit_event(...) 正常路径 → .inc() 触发 1 次."""
        mock_counter = MagicMock()
        mock_labels = MagicMock()
        mock_counter.labels.return_value = mock_labels

        with (
            patch("shared.events.src.emitter.tx_emit_event_total", mock_counter),
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
        )
        assert mock_labels.inc.call_count == 1

    async def test_fire_and_forget_path_increments_counter_once(self) -> None:
        """asyncio.create_task(emit_event(...)) → .inc() 触发 1 次 (常见模式).

        per CLAUDE.md §15 事件总线规范: 业务代码用 create_task 旁路写入.
        """
        import asyncio

        mock_counter = MagicMock()
        mock_labels = MagicMock()
        mock_counter.labels.return_value = mock_labels

        with (
            patch("shared.events.src.emitter.tx_emit_event_total", mock_counter),
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

    async def test_pg_failure_still_increments_counter(self) -> None:
        """PG 写入失败 → .inc() 仍触发 (algoirthm: .inc() 在 try 前调用).

        决策矩阵分母语义: 算"发起"不算"成功", PG/Redis 失败均不影响分母.
        """
        mock_counter = MagicMock()
        mock_labels = MagicMock()
        mock_counter.labels.return_value = mock_labels

        with (
            patch("shared.events.src.emitter.tx_emit_event_total", mock_counter),
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

        # PG fail → event_id is None, but counter still incremented
        assert event_id is None
        assert mock_labels.inc.call_count == 1

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
            patch("shared.events.src.emitter.tx_emit_event_total", mock_counter),
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
            patch("shared.events.src.emitter.tx_emit_event_total", mock_counter),
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

        # 所有 .labels() 调用的 tenant_id_short 值必须相同
        expected_short = _tenant_id_short(TENANT_A)
        for call in mock_counter.labels.call_args_list:
            assert call.kwargs["tenant_id_short"] == expected_short

        # 5 次 .inc()
        assert mock_labels.inc.call_count == 5


# ──────────────────────────────────────────────────────────────────────
# Counter 模块级符号导出验证 (caller 可 import)
# ──────────────────────────────────────────────────────────────────────


def test_tx_emit_event_total_is_importable() -> None:
    """tx_emit_event_total 必须是 shared.events.src.emitter 模块级符号.

    下游 tx-event-relay / dashboard 可能直接引用此 Counter 对象.
    """
    from shared.events.src import emitter

    assert hasattr(emitter, "tx_emit_event_total")
    # 真 Counter 或 no-op stub 都至少有 .labels 属性
    assert hasattr(emitter.tx_emit_event_total, "labels")
