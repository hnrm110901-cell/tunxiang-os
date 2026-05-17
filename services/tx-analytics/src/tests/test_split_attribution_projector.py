"""SplitAttributionProjector 测试 (PRD-11 sub-C / 2026-05-16).

测试基于徐记海鲜真实场景 (CLAUDE.md §20):
- 200 桌并发 split_attributed 事件流 projector 消费
- F2 dedup: 重放 → cost_attribution_summary UNIQUE (tenant_id, source_event_id)
  → ON CONFLICT DO NOTHING 静默吞 (本测试用 mock 验证 INSERT 必带 ON CONFLICT 子句)
- payload 边界: malformed / 缺字段 / shares 非数组 — 静默跳过 (不阻塞事件流)
- event_type 注册校验 + registry env-gate

mock 风格: 沿用 PRD-11 sub-B.2 test_index_split_projector_tier1 模式
(AsyncMock + MagicMock conn).
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

if sys.version_info < (3, 10):
    pytest.skip(
        "需要 Python 3.10+（生产环境 3.11）",
        allow_module_level=True,
    )

from services.tx_analytics.src.projectors.split_attribution import (  # noqa: E402
    SplitAttributionProjector,
)

# ─── 测试常量（徐记海鲜场景）──────────────────────────────────────────────

_TENANT_XUJI = "11111111-aaaa-aaaa-aaaa-111111111111"
_STORE_XUJI = "44444444-0001-0001-0001-444444444444"
_DISH_SUANCAIYU = "22222222-0001-0001-0001-222222222222"  # 酸菜鱼
_ORDER_ID = "55555555-0001-0001-0001-555555555555"
_ORDER_ITEM_A = "66666666-aaaa-aaaa-aaaa-666666666666"


def _split_event(
    *,
    event_id: str | None = None,
    method: str = "even",
    share_count: int = 2,
    bom_cost_total_fen: int = 6800,
    shares: list[dict[str, Any]] | None = None,
    event_type: str = "inventory.split_attributed",
    payload_override: dict | None = None,
) -> dict[str, Any]:
    """构造 SPLIT_ATTRIBUTED 事件 row (mimic events 表 SELECT 结果)."""
    eid = event_id or str(uuid.uuid4())
    if shares is None:
        shares = [
            {"share_index": 0, "weight": "0.5", "attributed_cost_fen": 3400},
            {"share_index": 1, "weight": "0.5", "attributed_cost_fen": 3400},
        ]
    payload = payload_override or {
        "order_id": _ORDER_ID,
        "order_item_id": _ORDER_ITEM_A,
        "dish_id": _DISH_SUANCAIYU,
        "method": method,
        "count": share_count,
        "bom_cost_total_fen": bom_cost_total_fen,
        "shares": shares,
    }
    return {
        "event_id": uuid.UUID(eid),
        "event_type": event_type,
        "stream_id": uuid.UUID(_ORDER_ID),
        "stream_type": "inventory",
        "store_id": uuid.UUID(_STORE_XUJI),
        "occurred_at": datetime(2026, 5, 16, 12, 0, 0, tzinfo=timezone.utc),
        "payload": payload,
        "metadata": {},
        "causation_id": None,
    }


def _make_conn_mock() -> MagicMock:
    """projector_base 传入的 asyncpg conn 桩 — 只需 execute 异步方法."""
    conn = MagicMock()
    conn.execute = AsyncMock(return_value=None)
    return conn


# ════════════════════════════════════════════════════════════════════════
# T1: handle() 事件类型路由与基本写入
# ════════════════════════════════════════════════════════════════════════


class TestProjectorRouting:
    @pytest.mark.asyncio
    async def test_writes_summary_for_valid_event(self) -> None:
        """正常 split_attributed 事件 → INSERT cost_attribution_summary."""
        proj = SplitAttributionProjector(tenant_id=_TENANT_XUJI)
        conn = _make_conn_mock()
        event = _split_event()

        await proj.handle(event, conn)

        # 调 2 次: set_config(tenant) + INSERT cost_attribution_summary
        assert conn.execute.await_count == 2
        # 第 1 次: set_config('app.tenant_id', $1, FALSE) RLS context
        set_config_call = conn.execute.await_args_list[0].args
        assert "set_config" in set_config_call[0]
        assert set_config_call[1] == str(proj.tenant_id)
        # 第 2 次: INSERT cost_attribution_summary
        insert_call = conn.execute.await_args_list[1].args
        sql = insert_call[0]
        assert "cost_attribution_summary" in sql
        assert "ON CONFLICT" in sql.upper()  # F2 dedup
        # bound parameters: tenant_id, event_id, order_id, order_item_id, dish_id,
        # method, share_count, bom_cost_total_fen, shares_json, occurred_at
        assert insert_call[1] == proj.tenant_id
        assert insert_call[2] == event["event_id"]
        assert insert_call[6] == "even"  # method
        assert insert_call[7] == 2  # share_count
        assert insert_call[8] == 6800  # bom_cost_total_fen

    @pytest.mark.asyncio
    async def test_ignores_non_split_attributed_event(self) -> None:
        proj = SplitAttributionProjector(tenant_id=_TENANT_XUJI)
        conn = _make_conn_mock()
        event = _split_event(event_type="inventory.consumed")  # 错误类型

        await proj.handle(event, conn)

        assert conn.execute.await_count == 0


# ════════════════════════════════════════════════════════════════════════
# T2: payload 边界 - 静默跳过 (不阻塞事件流)
# ════════════════════════════════════════════════════════════════════════


class TestPayloadBoundaries:
    @pytest.mark.asyncio
    async def test_missing_event_id_skipped(self) -> None:
        proj = SplitAttributionProjector(tenant_id=_TENANT_XUJI)
        conn = _make_conn_mock()
        event = _split_event()
        event["event_id"] = None

        await proj.handle(event, conn)

        assert conn.execute.await_count == 0

    @pytest.mark.asyncio
    async def test_missing_method_skipped(self) -> None:
        proj = SplitAttributionProjector(tenant_id=_TENANT_XUJI)
        conn = _make_conn_mock()
        event = _split_event(
            payload_override={
                "order_id": _ORDER_ID,
                "dish_id": _DISH_SUANCAIYU,
                "count": 2,
                "bom_cost_total_fen": 6800,
                "shares": [],
            }
        )

        await proj.handle(event, conn)

        assert conn.execute.await_count == 0

    @pytest.mark.asyncio
    async def test_missing_count_skipped(self) -> None:
        proj = SplitAttributionProjector(tenant_id=_TENANT_XUJI)
        conn = _make_conn_mock()
        event = _split_event(
            payload_override={
                "order_id": _ORDER_ID,
                "dish_id": _DISH_SUANCAIYU,
                "method": "even",
                "bom_cost_total_fen": 6800,
                "shares": [],
            }
        )

        await proj.handle(event, conn)

        assert conn.execute.await_count == 0

    @pytest.mark.asyncio
    async def test_payload_as_json_string_parsed(self) -> None:
        """projector_base 已 json.loads, 但若仍为 str — projector 自行解析."""
        proj = SplitAttributionProjector(tenant_id=_TENANT_XUJI)
        conn = _make_conn_mock()
        event = _split_event()
        import json as _json

        event["payload"] = _json.dumps(event["payload"])

        await proj.handle(event, conn)

        # str payload 解析后正常写入
        assert conn.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_payload_malformed_json_string_skipped(self) -> None:
        proj = SplitAttributionProjector(tenant_id=_TENANT_XUJI)
        conn = _make_conn_mock()
        event = _split_event()
        event["payload"] = "not-json-{["

        await proj.handle(event, conn)

        assert conn.execute.await_count == 0

    @pytest.mark.asyncio
    async def test_shares_not_list_writes_empty_array(self) -> None:
        """shares 字段不是数组 — 兜底写空 list 占位 (不阻塞 dashboard)."""
        proj = SplitAttributionProjector(tenant_id=_TENANT_XUJI)
        conn = _make_conn_mock()
        event = _split_event(
            payload_override={
                "order_id": _ORDER_ID,
                "dish_id": _DISH_SUANCAIYU,
                "method": "even",
                "count": 2,
                "bom_cost_total_fen": 6800,
                "shares": "not-a-list",  # type: ignore[dict-item]
            }
        )

        await proj.handle(event, conn)

        # 仍 INSERT, 但 shares 是 "[]" JSON
        assert conn.execute.await_count == 2
        insert_call = conn.execute.await_args_list[1].args
        shares_json = insert_call[9]
        assert shares_json == "[]"

    @pytest.mark.asyncio
    async def test_invalid_count_type_skipped(self) -> None:
        proj = SplitAttributionProjector(tenant_id=_TENANT_XUJI)
        conn = _make_conn_mock()
        event = _split_event(
            payload_override={
                "order_id": _ORDER_ID,
                "dish_id": _DISH_SUANCAIYU,
                "method": "even",
                "count": "not-a-number",
                "bom_cost_total_fen": 6800,
                "shares": [],
            }
        )

        await proj.handle(event, conn)

        assert conn.execute.await_count == 0


# ════════════════════════════════════════════════════════════════════════
# T3: event_type / event_types 集合校验
# ════════════════════════════════════════════════════════════════════════


class TestEventTypeRegistration:
    def test_split_attributed_in_inventory_event_type(self) -> None:
        from shared.events.src.event_types import InventoryEventType

        assert (
            InventoryEventType.SPLIT_ATTRIBUTED.value == "inventory.split_attributed"
        )

    def test_projector_subscribes_only_split_attributed(self) -> None:
        proj = SplitAttributionProjector(tenant_id=_TENANT_XUJI)
        assert proj.event_types == {"inventory.split_attributed"}
        assert proj.name == "cost_attribution_summary"


# ════════════════════════════════════════════════════════════════════════
# T4: Registry helper — env gate + idempotent + stop
# ════════════════════════════════════════════════════════════════════════


class TestProjectorRegistry:
    @pytest.mark.asyncio
    async def test_disabled_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """env 未设 + SDK 评估 OFF → start 静默 return, 不创建 task."""
        from services.tx_analytics.src.projectors import registry

        monkeypatch.delenv(
            "TX_ANALYTICS_ENABLE_SPLIT_ATTRIBUTION_PROJECTOR", raising=False
        )
        # PR #734 改 is_enabled() 加入 feature_flags SDK 路径后, env 未设 → 走 SDK;
        # CI 默认 TUNXIANG_ENV/TX_ENV 未设 → SDK env fallback "dev" → environments.dev=true
        # → flag ON → task 创建. Mock SDK 还原"默认 disabled"语义 (与 tx-supply 同 fix).
        monkeypatch.setattr(registry, "_ff_is_enabled", lambda *_a, **_k: False)
        registry._PROJECTOR_TASKS.clear()
        await registry.start_split_attribution_projector(_TENANT_XUJI)
        assert _TENANT_XUJI not in registry._PROJECTOR_TASKS

    @pytest.mark.asyncio
    async def test_stop_no_task_is_noop(self) -> None:
        from services.tx_analytics.src.projectors import registry

        registry._PROJECTOR_TASKS.clear()
        # 不应 raise
        await registry.stop_split_attribution_projector(_TENANT_XUJI)

    @pytest.mark.asyncio
    async def test_is_enabled_env_variants(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """env 显式 truthy/falsy → _env_override; "" → 走 SDK fallback (PR #734 后新语义)."""
        from services.tx_analytics.src.projectors import registry

        for v in ("true", "TRUE", "1", "yes", "on"):
            monkeypatch.setenv(
                "TX_ANALYTICS_ENABLE_SPLIT_ATTRIBUTION_PROJECTOR", v
            )
            assert registry.is_enabled() is True
        for v in ("false", "0", "no", "off"):
            monkeypatch.setenv(
                "TX_ANALYTICS_ENABLE_SPLIT_ATTRIBUTION_PROJECTOR", v
            )
            assert registry.is_enabled() is False
        # 空字符串 "" 不在 _env_override 显式列表 → 返 None → 走 SDK fallback.
        # CI 默认 TUNXIANG_ENV/TX_ENV 未设 → SDK env="dev" → environments.dev=true → True.
        # Mock SDK OFF 还原 "" 在 _env_override 的预期 falsy 语义 (与 test_disabled_by_default 同 fix).
        monkeypatch.setattr(registry, "_ff_is_enabled", lambda *_a, **_k: False)
        monkeypatch.setenv("TX_ANALYTICS_ENABLE_SPLIT_ATTRIBUTION_PROJECTOR", "")
        assert registry.is_enabled() is False

    @pytest.mark.asyncio
    async def test_stop_all_empties_tasks_dict(self) -> None:
        from services.tx_analytics.src.projectors import registry

        registry._PROJECTOR_TASKS.clear()
        # 不应 raise (空 dict 直接 noop)
        await registry.stop_all_split_attribution_projectors()
        assert registry._PROJECTOR_TASKS == {}
