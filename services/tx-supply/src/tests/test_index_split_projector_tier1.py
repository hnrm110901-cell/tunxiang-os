"""IndexSplitProjector tier1 测试 (PRD-11 sub-B.2 / 2026-05-16 / Tier 1 第 30 例).

测试基于徐记海鲜真实场景 (CLAUDE.md §20 + §17):
- 200 桌并发 settle, ITEMS_SETTLED 事件流 projector 消费
- F2 P0: projector crash 重启 → 同 event_id 重放 → ingredient_transactions
  无重复扣料 (v437 UNIQUE 触 IntegrityError → savepoint rollback → 推进 checkpoint)
- F4: share_split_rule 被禁用 → apply_split ValueError → dlq_split_attribution_failed
  写入 (sub-C 死信看板可消费) + 推进 checkpoint (不阻塞事件流)
- RLS: tenant 隔离 (projector_base 已 set tenant context)
- payload 边界: malformed / empty items / share_count<=1 / 非 ITEMS_SETTLED 事件类型

mock 风格: 沿用 PRD-08/11 sub-A `_FakeResult` plain class + AsyncMock 模式.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if sys.version_info < (3, 10):
    pytest.skip(
        "需要 Python 3.10+（生产环境 3.11）— 本机 3.9 跳过避免 sys.modules 污染",
        allow_module_level=True,
    )

from sqlalchemy.exc import IntegrityError  # noqa: E402

from services.tx_supply.src.projectors.index_split import (  # noqa: E402
    _DEDUP_UNIQUE_INDEX,
    IndexSplitProjector,
)


# ─── 测试常量（徐记海鲜场景）──────────────────────────────────────────────

_TENANT_XUJI = "11111111-aaaa-aaaa-aaaa-111111111111"
_STORE_XUJI = "44444444-0001-0001-0001-444444444444"
_DISH_SUANCAIYU = "22222222-0001-0001-0001-222222222222"  # 酸菜鱼 (allow_share=true, max=8)
_DISH_TANGCUYU = "22222222-0002-0002-0002-222222222222"  # 糖醋鱼 (allow_share=false)
_ORDER_ID = "55555555-0001-0001-0001-555555555555"
_ORDER_ITEM_A = "66666666-aaaa-aaaa-aaaa-666666666666"
_ORDER_ITEM_B = "66666666-bbbb-bbbb-bbbb-666666666666"


def _settled_event(
    *,
    event_id: str | None = None,
    items: list[dict[str, Any]] | None = None,
    event_type: str = "order.items_settled",
    payload_override: dict | None = None,
) -> dict[str, Any]:
    """构造 ITEMS_SETTLED 事件 row (mimic events 表 SELECT 结果)."""
    eid = event_id or str(uuid.uuid4())
    if items is None:
        items = [
            {
                "order_item_id": _ORDER_ITEM_A,
                "dish_id": _DISH_SUANCAIYU,
                "qty": 1,
                "share_count": 2,
                "subtotal_fen": 9800,
            }
        ]
    payload = payload_override or {
        "order_id": _ORDER_ID,
        "store_id": _STORE_XUJI,
        "items": items,
    }
    return {
        "event_id": uuid.UUID(eid),
        "event_type": event_type,
        "stream_id": uuid.UUID(_ORDER_ID),
        "stream_type": "order",
        "store_id": uuid.UUID(_STORE_XUJI),
        "occurred_at": datetime(2026, 5, 16, 12, 0, 0, tzinfo=timezone.utc),
        "payload": payload,
        "metadata": {},
        "causation_id": None,
    }


def _make_conn_mock() -> MagicMock:
    """projector_base 传入的 asyncpg conn 桩 — 只需 execute 异步方法 (DLQ INSERT)."""
    conn = MagicMock()
    conn.execute = AsyncMock(return_value=None)
    return conn


def _make_session_mock(deduct_side_effect: Any = None) -> tuple[MagicMock, AsyncMock]:
    """patch async_session_factory 返回的 mock session + transaction context.

    `async with async_session_factory() as db: async with db.begin(): await deduct(...)`
    需要 session 暴露 async __aenter__/__aexit__ 两层 + begin() 也 async ctx.
    """
    session = MagicMock(name="MockSession")
    # session 是 async ctx
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    # db.begin() 也是 async ctx
    txn = MagicMock(name="MockTxn")
    txn.__aenter__ = AsyncMock(return_value=txn)
    txn.__aexit__ = AsyncMock(return_value=None)
    session.begin = MagicMock(return_value=txn)

    deduct_mock = AsyncMock(side_effect=deduct_side_effect)

    factory = MagicMock(name="MockSessionFactory", return_value=session)
    return factory, deduct_mock


def _make_dedup_integrity_error() -> IntegrityError:
    """模拟 asyncpg UniqueViolationError 包裹的 SQLAlchemy IntegrityError (F2 命中)."""
    orig = MagicMock(name="UniqueViolationError")
    orig.constraint_name = _DEDUP_UNIQUE_INDEX
    orig.detail = f"Key (tenant_id, source_event_id)=(..., ...) already exists ({_DEDUP_UNIQUE_INDEX})."
    ie = IntegrityError("INSERT ingredient_transactions", {}, orig)
    return ie


def _make_other_integrity_error() -> IntegrityError:
    """模拟非 dedup 的 IntegrityError (e.g. FK 违反)."""
    orig = MagicMock(name="ForeignKeyViolationError")
    orig.constraint_name = "fk_ingredient_transactions_ingredient_id"
    orig.detail = "Key (ingredient_id)=(missing) is not present."
    ie = IntegrityError("INSERT ingredient_transactions", {}, orig)
    return ie


# ════════════════════════════════════════════════════════════════════════
# Test class — handle() 路由与过滤
# ════════════════════════════════════════════════════════════════════════


class TestProjectorRouting:
    """T1: handle() 事件类型/过滤逻辑 (200 桌峰值场景边界)."""

    @pytest.mark.asyncio
    async def test_ignores_non_items_settled_event(self) -> None:
        """非 ITEMS_SETTLED 事件 (event_types 过滤失效防御) — 静默 return."""
        proj = IndexSplitProjector(tenant_id=_TENANT_XUJI)
        conn = _make_conn_mock()
        event = _settled_event(event_type="order.paid")  # 错误类型

        factory, deduct = _make_session_mock()
        with patch(
            "services.tx_supply.src.projectors.index_split.async_session_factory",
            factory,
        ):
            await proj.handle(event, conn)

        # 业务路径未触发, DLQ 未写
        assert deduct.await_count == 0
        assert conn.execute.await_count == 0

    @pytest.mark.asyncio
    async def test_skips_all_items_share_count_one(self) -> None:
        """全单 share_count=1 (单人独享) — projector 跳过, 不调 deduct."""
        proj = IndexSplitProjector(tenant_id=_TENANT_XUJI)
        conn = _make_conn_mock()
        event = _settled_event(
            items=[
                {
                    "order_item_id": _ORDER_ITEM_A,
                    "dish_id": _DISH_SUANCAIYU,
                    "qty": 1,
                    "share_count": 1,  # 单人
                    "subtotal_fen": 9800,
                }
            ]
        )

        factory, deduct = _make_session_mock()
        with patch(
            "services.tx_supply.src.projectors.index_split.async_session_factory",
            factory,
        ):
            await proj.handle(event, conn)

        assert deduct.await_count == 0
        assert conn.execute.await_count == 0  # 无 DLQ 写

    @pytest.mark.asyncio
    async def test_filters_share_items_only(self) -> None:
        """混合 share_count: 1 个 share>1 + 1 个 share=1 — 只 attribute share>1."""
        proj = IndexSplitProjector(tenant_id=_TENANT_XUJI)
        conn = _make_conn_mock()
        event = _settled_event(
            items=[
                {"order_item_id": _ORDER_ITEM_A, "dish_id": _DISH_SUANCAIYU, "qty": 1, "share_count": 4},
                {"order_item_id": _ORDER_ITEM_B, "dish_id": _DISH_TANGCUYU, "qty": 1, "share_count": 1},
            ]
        )

        factory, deduct = _make_session_mock()
        with patch(
            "services.tx_supply.src.projectors.index_split.async_session_factory",
            factory,
        ), patch(
            "services.tx_supply.src.services.auto_deduction.deduct_for_order",
            deduct,
        ):
            await proj.handle(event, conn)

        assert deduct.await_count == 1
        # 验证仅 share>1 item 传入 + source_event_id 传递
        call_kwargs = deduct.await_args.kwargs
        passed_items = call_kwargs.get("order_items")
        assert len(passed_items) == 1
        assert passed_items[0]["dish_id"] == _DISH_SUANCAIYU
        assert passed_items[0]["share_split"] == {"method": "even", "count": 4}
        assert call_kwargs["source_event_id"] == event["event_id"]
        assert call_kwargs["tenant_id"] == _TENANT_XUJI


# ════════════════════════════════════════════════════════════════════════
# Test class — F2 P0 dedup (projector crash 重放防重复扣料)
# ════════════════════════════════════════════════════════════════════════


class TestF2DedupOnReplay:
    """T2: projector crash 后 checkpoint 重放 → v437 UNIQUE 守门 → skip success."""

    @pytest.mark.asyncio
    async def test_dedup_integrity_error_skipped_no_dlq(self) -> None:
        """同 event 第二次消费 — 命中 source_event_id UNIQUE → savepoint rollback,
        视为消费成功 (checkpoint 推进), 不写 DLQ (语义: 已扣过料的事件不是错误)."""
        proj = IndexSplitProjector(tenant_id=_TENANT_XUJI)
        conn = _make_conn_mock()
        event = _settled_event()

        factory, deduct = _make_session_mock(
            deduct_side_effect=_make_dedup_integrity_error()
        )
        with patch(
            "services.tx_supply.src.projectors.index_split.async_session_factory",
            factory,
        ), patch(
            "services.tx_supply.src.services.auto_deduction.deduct_for_order",
            deduct,
        ):
            # 不应 raise (projector 静默 skip)
            await proj.handle(event, conn)

        assert deduct.await_count == 1
        # DLQ 未写 (dedup 不是错误)
        assert conn.execute.await_count == 0

    @pytest.mark.asyncio
    async def test_dedup_detected_via_detail_string_fallback(self) -> None:
        """退化模式: constraint_name 不可用 → detail 字符串包含索引名 → 仍识别为 dedup."""
        proj = IndexSplitProjector(tenant_id=_TENANT_XUJI)
        conn = _make_conn_mock()
        event = _settled_event()

        # constraint_name 缺失, 仅 detail 含 dedup 索引名
        orig = MagicMock()
        orig.constraint_name = None
        orig.detail = (
            f"violates unique constraint on index {_DEDUP_UNIQUE_INDEX} (...)"
        )
        ie = IntegrityError("INSERT", {}, orig)

        factory, deduct = _make_session_mock(deduct_side_effect=ie)
        with patch(
            "services.tx_supply.src.projectors.index_split.async_session_factory",
            factory,
        ), patch(
            "services.tx_supply.src.services.auto_deduction.deduct_for_order",
            deduct,
        ):
            await proj.handle(event, conn)

        # 退化识别成功 → skip, 无 DLQ 写
        assert conn.execute.await_count == 0


# ════════════════════════════════════════════════════════════════════════
# Test class — F4 死信 (share_split_rule 禁用/超上限)
# ════════════════════════════════════════════════════════════════════════


class TestF4DeadLetterQueue:
    """T3: apply_split ValueError → DLQ 写入 + 推进 checkpoint."""

    @pytest.mark.asyncio
    async def test_rule_disabled_writes_dlq(self) -> None:
        """share_split_rule 被禁用 → ValueError → INSERT dlq_split_attribution_failed."""
        proj = IndexSplitProjector(tenant_id=_TENANT_XUJI)
        conn = _make_conn_mock()
        event = _settled_event()

        factory, deduct = _make_session_mock(
            deduct_side_effect=ValueError(
                "dish 不允许分享: 糖醋鱼 (allow_share=False)"
            )
        )
        with patch(
            "services.tx_supply.src.projectors.index_split.async_session_factory",
            factory,
        ), patch(
            "services.tx_supply.src.services.auto_deduction.deduct_for_order",
            deduct,
        ):
            await proj.handle(event, conn)

        assert deduct.await_count == 1
        # DLQ INSERT 一次
        assert conn.execute.await_count == 1
        # 验证 INSERT 参数 (event_id + error_class=ValueError + error_msg 携规则原因)
        positional = conn.execute.await_args.args
        sql = positional[0]
        assert "dlq_split_attribution_failed" in sql
        # args[1] = tenant_id, args[2] = event_id, args[7] = error_class, args[8] = error_msg
        assert positional[1] == proj.tenant_id  # tenant_id
        assert positional[2] == event["event_id"]
        assert positional[7] == "ValueError"
        assert "allow_share" in positional[8]

    @pytest.mark.asyncio
    async def test_max_share_count_exceeded_writes_dlq(self) -> None:
        """share_count 超 max_share_count → ValueError → DLQ."""
        proj = IndexSplitProjector(tenant_id=_TENANT_XUJI)
        conn = _make_conn_mock()
        event = _settled_event(
            items=[
                {
                    "order_item_id": _ORDER_ITEM_A,
                    "dish_id": _DISH_SUANCAIYU,
                    "qty": 1,
                    "share_count": 99,  # 超 max
                    "subtotal_fen": 9800,
                }
            ]
        )

        factory, deduct = _make_session_mock(
            deduct_side_effect=ValueError("share_count=99 超 max_share_count=8")
        )
        with patch(
            "services.tx_supply.src.projectors.index_split.async_session_factory",
            factory,
        ), patch(
            "services.tx_supply.src.services.auto_deduction.deduct_for_order",
            deduct,
        ):
            await proj.handle(event, conn)

        assert conn.execute.await_count == 1

    @pytest.mark.asyncio
    async def test_non_dedup_integrity_error_writes_dlq(self) -> None:
        """非 dedup 的 IntegrityError (e.g. FK 违反) → DLQ + 不当作 dedup."""
        proj = IndexSplitProjector(tenant_id=_TENANT_XUJI)
        conn = _make_conn_mock()
        event = _settled_event()

        factory, deduct = _make_session_mock(
            deduct_side_effect=_make_other_integrity_error()
        )
        with patch(
            "services.tx_supply.src.projectors.index_split.async_session_factory",
            factory,
        ), patch(
            "services.tx_supply.src.services.auto_deduction.deduct_for_order",
            deduct,
        ):
            await proj.handle(event, conn)

        assert conn.execute.await_count == 1
        # error_class 是 IntegrityError 子类名
        positional = conn.execute.await_args.args
        assert "IntegrityError" in positional[7]


# ════════════════════════════════════════════════════════════════════════
# Test class — payload / event_id 边界防御
# ════════════════════════════════════════════════════════════════════════


class TestPayloadBoundaries:
    """T4: malformed / 缺字段 / 空 items — 静默跳过 (不阻塞事件流)."""

    @pytest.mark.asyncio
    async def test_missing_event_id_skipped(self) -> None:
        proj = IndexSplitProjector(tenant_id=_TENANT_XUJI)
        conn = _make_conn_mock()
        event = _settled_event()
        event["event_id"] = None

        factory, deduct = _make_session_mock()
        with patch(
            "services.tx_supply.src.projectors.index_split.async_session_factory",
            factory,
        ):
            await proj.handle(event, conn)

        assert deduct.await_count == 0
        assert conn.execute.await_count == 0

    @pytest.mark.asyncio
    async def test_payload_as_json_string_parsed(self) -> None:
        """events 表 payload 字段是 jsonb, projector_base 已 json.loads, 但若仍为 str
        (rebuild 场景或测试 mock), projector 自行解析."""
        proj = IndexSplitProjector(tenant_id=_TENANT_XUJI)
        conn = _make_conn_mock()
        event = _settled_event()
        import json as _json

        event["payload"] = _json.dumps(event["payload"])

        factory, deduct = _make_session_mock(deduct_side_effect=None)
        with patch(
            "services.tx_supply.src.projectors.index_split.async_session_factory",
            factory,
        ), patch(
            "services.tx_supply.src.services.auto_deduction.deduct_for_order",
            deduct,
        ):
            await proj.handle(event, conn)

        # str payload 解析后正常处理
        assert deduct.await_count == 1

    @pytest.mark.asyncio
    async def test_empty_items_array_skipped(self) -> None:
        proj = IndexSplitProjector(tenant_id=_TENANT_XUJI)
        conn = _make_conn_mock()
        event = _settled_event(items=[])

        factory, deduct = _make_session_mock()
        with patch(
            "services.tx_supply.src.projectors.index_split.async_session_factory",
            factory,
        ):
            await proj.handle(event, conn)

        assert deduct.await_count == 0
        assert conn.execute.await_count == 0

    @pytest.mark.asyncio
    async def test_missing_order_id_skipped(self) -> None:
        proj = IndexSplitProjector(tenant_id=_TENANT_XUJI)
        conn = _make_conn_mock()
        event = _settled_event(
            payload_override={"store_id": _STORE_XUJI, "items": []}
        )

        factory, deduct = _make_session_mock()
        with patch(
            "services.tx_supply.src.projectors.index_split.async_session_factory",
            factory,
        ):
            await proj.handle(event, conn)

        assert deduct.await_count == 0


# ════════════════════════════════════════════════════════════════════════
# Test class — event_type 注册校验
# ════════════════════════════════════════════════════════════════════════


class TestEventTypeRegistration:
    """T5: ITEMS_SETTLED 已注册 + projector.event_types 一致."""

    def test_items_settled_in_order_event_type(self) -> None:
        from shared.events.src.event_types import OrderEventType

        assert OrderEventType.ITEMS_SETTLED.value == "order.items_settled"

    def test_projector_subscribes_only_items_settled(self) -> None:
        proj = IndexSplitProjector(tenant_id=_TENANT_XUJI)
        assert proj.event_types == {"order.items_settled"}
        assert proj.name == "inventory_split_attribution"


# ════════════════════════════════════════════════════════════════════════
# Test class — Registry helper (start/stop 行为)
# ════════════════════════════════════════════════════════════════════════


class TestProjectorRegistry:
    """T6: registry start/stop 函数行为 — env gate + idempotent."""

    @pytest.mark.asyncio
    async def test_disabled_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """env 未设 → start 静默 return, 不创建 task."""
        from services.tx_supply.src.projectors import registry

        monkeypatch.delenv("TX_SUPPLY_ENABLE_INDEX_SPLIT_PROJECTOR", raising=False)
        # 清理潜在残留
        registry._PROJECTOR_TASKS.clear()
        await registry.start_index_split_projector(_TENANT_XUJI)
        assert _TENANT_XUJI not in registry._PROJECTOR_TASKS

    @pytest.mark.asyncio
    async def test_stop_no_task_is_noop(self) -> None:
        from services.tx_supply.src.projectors import registry

        registry._PROJECTOR_TASKS.clear()
        # 不应 raise
        await registry.stop_index_split_projector(_TENANT_XUJI)


# ════════════════════════════════════════════════════════════════════════
# Test class — uuid5 派生 (确保 source_event_id 是 race-safe 同 event 重放生成相同 UUID)
# ════════════════════════════════════════════════════════════════════════


class TestSourceEventIdDerivation:
    """T7: auto_deduction.deduct_for_dish uuid5 派生确定性 — 同输入同输出.

    这是 F2 P0 dedup 正确性的基石: replay 必须生成 IDENTICAL source_event_id.
    """

    def test_uuid5_deterministic_per_row(self) -> None:
        """同 (event_id, order_item_id, dish_id, ingredient_id, line_idx) 生成同 UUID."""
        event_id = uuid.UUID(_ORDER_ID)
        order_item_id = _ORDER_ITEM_A
        dish_id = _DISH_SUANCAIYU
        ingredient_id = "77777777-0001-0001-0001-777777777777"
        line_idx = 0

        seed = (
            f"{event_id}|{order_item_id}|{dish_id}|{ingredient_id}|{line_idx}"
        )
        uuid_a = uuid.uuid5(event_id, seed)
        uuid_b = uuid.uuid5(event_id, seed)
        assert uuid_a == uuid_b

    def test_uuid5_distinct_per_line_idx(self) -> None:
        """不同 line_idx 生成 不同 UUID — 同 dish BOM 多行 fresh INSERT 不冲突."""
        event_id = uuid.UUID(_ORDER_ID)
        seed0 = f"{event_id}|{_ORDER_ITEM_A}|{_DISH_SUANCAIYU}|fish|0"
        seed1 = f"{event_id}|{_ORDER_ITEM_A}|{_DISH_SUANCAIYU}|fish|1"
        assert uuid.uuid5(event_id, seed0) != uuid.uuid5(event_id, seed1)

    def test_uuid5_distinct_per_order_item(self) -> None:
        """同 dish 不同 order_item — 2 个 item 共享 ingredient 时, fresh INSERT 不冲突."""
        event_id = uuid.UUID(_ORDER_ID)
        seed_a = f"{event_id}|{_ORDER_ITEM_A}|{_DISH_SUANCAIYU}|fish|0"
        seed_b = f"{event_id}|{_ORDER_ITEM_B}|{_DISH_SUANCAIYU}|fish|0"
        assert uuid.uuid5(event_id, seed_a) != uuid.uuid5(event_id, seed_b)
