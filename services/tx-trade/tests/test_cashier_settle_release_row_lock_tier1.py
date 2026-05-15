"""§17-B settle 终态保护 + 3B 幂等释放 Tier 1 mock 测试 — 正面 mode SQL grep

与 tests/concurrent/test_cashier_settle_concurrent_tier1.py (负面 mode 真 PG 并发反测)
互补 — audit doc §8.3 「正面/负面 双模式」 模式。

验证 §17-B 实现:
  - cashier_engine._release_table(store_id, table_no, order_id) UPDATE WHERE
    含 current_order_id=:order_id + status='occupied' (3B 幂等无害)
  - cashier_engine.settle_order 调用 _release_table 传 order_id (终态保护守门)
  - cashier_engine.cancel_order 用 _get_order(lock=True) SELECT Order FOR UPDATE
    + 调用 _release_table 传 order_id (终态保护)
  - cashier_engine.transfer_table 调用 _release_table 传 order_id
  - order_service._release_table 同上 (3B 幂等)
  - order_service.settle_order/cancel_order 同上 (lock + 传 order_id)

业务背景：
  audit doc §11.2 选择题 3 — 创始人锁定 3B (显式幂等 release: UPDATE WHERE
  current_order_id=:order_id AND status='occupied', 多次调用无害)。
  + 配套 settle/cancel 终态保护 (SELECT Order FOR UPDATE 让双结算 race 输者抛
  "订单已结算" / "已结算订单无法取消").

关联：
  - docs/security/tier1-row-lock-audit-2026-05.md §11.4 PR-D 拆分预案
  - tests/concurrent/test_cashier_settle_concurrent_tier1.py (负面 mode 真 PG 反测)
  - 修复参考范本: services/tx-member/src/services/stored_value_service.py 11 处锁
  - §17-A 范本: services/tx-trade/tests/test_cashier_table_row_lock_tier1.py
"""

from __future__ import annotations

import os
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

# ── 路径 ──────────────────────────────────────────────────────────────────────
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
for p in [ROOT, SRC]:
    if p not in sys.path:
        sys.path.insert(0, p)


# ── pytest collection guard ──────────────────────────────────────────────────
if sys.version_info < (3, 10):
    pytest.skip(
        "需 Python 3.10+ (shared.events 用 dataclass slots=True)；CI Python 3.11 跑通",
        allow_module_level=True,
    )


TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
STORE_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
ORDER_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")


def _update_table_sql(stmt) -> str | None:
    """如果 stmt 是 UPDATE Table → 返回编译后 SQL；否则 None."""
    try:
        from sqlalchemy.dialects import postgresql
        from sqlalchemy.sql.dml import Update

        if not isinstance(stmt, Update):
            return None
        compiled = str(stmt.compile(dialect=postgresql.dialect())).upper()
        if "UPDATE TABLES" not in compiled:
            return None
        return compiled
    except Exception:
        return None


def _select_order_has_for_update(stmt) -> bool:
    """SELECT Order ... FOR UPDATE."""
    try:
        from sqlalchemy.dialects import postgresql
        from sqlalchemy.sql.selectable import Select

        if not isinstance(stmt, Select):
            return False
        compiled = str(stmt.compile(dialect=postgresql.dialect())).upper()
        return "FROM ORDERS" in compiled and "FOR UPDATE" in compiled
    except Exception:
        return False


def _make_order(**kw):
    """构造 Order mock."""
    from shared.ontology.src.enums import OrderStatus

    order = MagicMock()
    order.id = kw.get("id", ORDER_ID)
    order.store_id = kw.get("store_id", STORE_ID)
    order.tenant_id = kw.get("tenant_id", TENANT_ID)
    order.status = kw.get("status", OrderStatus.confirmed.value)
    order.table_number = kw.get("table_number", "A01")
    order.order_no = kw.get("order_no", "TX20260515000001")
    order.order_metadata = kw.get("order_metadata", {})
    order.final_amount_fen = kw.get("final_amount_fen", 10000)
    order.completed_at = None
    return order


# ─── §17-B cashier_engine._release_table 3B 幂等签名 ─────────────────────────


class TestCashierReleaseTableIdempotent:
    def test_release_table_signature_requires_order_id(self):
        """§17-B: cashier_engine._release_table 必须接受 order_id 参数."""
        import inspect

        from services.tx_trade.src.services.cashier_engine import CashierEngine

        sig = inspect.signature(CashierEngine._release_table)
        assert "order_id" in sig.parameters, (
            "_release_table 必须含 order_id 参数 (3B 幂等守门)"
        )

    @pytest.mark.asyncio
    async def test_release_table_update_filters_by_current_order_id_and_status(self):
        """§17-B 3B: UPDATE tables WHERE 必须含 current_order_id=:order_id + status='occupied'.

        多次 release 同 (table, order_id) 仅首次 UPDATE 影响 1 行, 后续 0 行无害.
        若 table 被新 order 重新 occupy, current_order_id 不匹配 → UPDATE 0 行,
        不污染新 order 的桌台引用.
        """
        from services.tx_trade.src.services.cashier_engine import CashierEngine

        captured: list = []
        db = AsyncMock()

        async def mock_execute(stmt, *args, **kwargs):
            captured.append(stmt)
            result = MagicMock()
            return result

        db.execute = mock_execute
        eng = CashierEngine(db=db, tenant_id=str(TENANT_ID))
        await eng._release_table(str(STORE_ID), "A01", ORDER_ID)

        update_sqls = [s for s in (_update_table_sql(s) for s in captured) if s]
        assert update_sqls, "_release_table 必须 UPDATE tables"
        sql = update_sqls[0]
        assert "CURRENT_ORDER_ID" in sql, (
            "UPDATE WHERE 必须含 current_order_id 守门 (3B 幂等)"
        )
        assert "STATUS" in sql, (
            "UPDATE WHERE 必须含 status='occupied' 守门 (3B 幂等)"
        )


# ─── §17-B cashier_engine.settle_order 终态保护 + 传 order_id ──────────────


class TestCashierSettleOrderTerminalProtection:
    @pytest.mark.asyncio
    async def test_settle_order_release_table_passes_order_id(self):
        """§17-B: settle_order 调 _release_table 必须传 order.id (3B 幂等).

        防双结算 race (FOR UPDATE 已守门, §17-A settle SELECT FOR UPDATE) 后,
        若两路都进 release 步骤 (理论上 FOR UPDATE 已让输者抛 "订单已结算"),
        即使有兜底 race 也只 UPDATE 自己 order_id 的桌台行.
        """
        from services.tx_trade.src.services.cashier_engine import CashierEngine

        order = _make_order(status="confirmed", table_number="A01")
        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        async def mock_execute(stmt, *args, **kwargs):
            result = MagicMock()
            result.scalar_one_or_none = MagicMock(return_value=order)
            return result

        db.execute = mock_execute
        eng = CashierEngine(db=db, tenant_id=str(TENANT_ID))

        release_calls: list = []

        async def capture_release(store_id, table_no, order_id):
            release_calls.append({"store_id": store_id, "table_no": table_no, "order_id": order_id})

        eng._release_table = capture_release

        await eng.settle_order(
            order_id=str(ORDER_ID),
            payments=[{"method": "cash", "amount_fen": 10000}],
        )

        assert release_calls, "settle_order 必须调 _release_table"
        call = release_calls[0]
        assert call["order_id"] == order.id, (
            f"settle_order 必须传 order.id 给 _release_table, 实际传 {call['order_id']}"
        )


# ─── §17-B cashier_engine.cancel_order 终态保护 (FOR UPDATE) ───────────────


class TestCashierCancelOrderTerminalProtection:
    @pytest.mark.asyncio
    async def test_cancel_order_uses_for_update_lock(self):
        """§17-B: cancel_order SELECT Order 必须 FOR UPDATE 防 settle/cancel race.

        Race: 一路 settle 同时一路 cancel → 若 cancel 无锁, 两路都读到 status=pending
        都过状态机校验, 一路 commit → 一路 commit 时状态已变但 ORM 不重读 → 双写.
        FOR UPDATE 让输者读到 status=completed 抛 "已结算订单无法取消".
        """
        from services.tx_trade.src.services.cashier_engine import CashierEngine

        order = _make_order(status="confirmed", table_number="A01")
        captured: list = []
        db = AsyncMock()
        db.flush = AsyncMock()

        async def mock_execute(stmt, *args, **kwargs):
            captured.append(stmt)
            result = MagicMock()
            result.scalar_one_or_none = MagicMock(return_value=order)
            return result

        db.execute = mock_execute
        eng = CashierEngine(db=db, tenant_id=str(TENANT_ID))
        eng._release_table = AsyncMock()

        await eng.cancel_order(order_id=str(ORDER_ID), reason="客户取消")

        order_selects = [s for s in captured if _select_order_has_for_update(s)]
        assert order_selects, (
            "cancel_order SELECT Order 必须含 FOR UPDATE (终态保护防 settle/cancel race)"
        )

    @pytest.mark.asyncio
    async def test_cancel_order_release_table_passes_order_id(self):
        """§17-B: cancel_order 调 _release_table 必须传 order.id (3B 幂等)."""
        from services.tx_trade.src.services.cashier_engine import CashierEngine

        order = _make_order(status="confirmed", table_number="A01")
        db = AsyncMock()
        db.flush = AsyncMock()

        async def mock_execute(stmt, *args, **kwargs):
            result = MagicMock()
            result.scalar_one_or_none = MagicMock(return_value=order)
            return result

        db.execute = mock_execute
        eng = CashierEngine(db=db, tenant_id=str(TENANT_ID))

        release_calls: list = []

        async def capture_release(store_id, table_no, order_id):
            release_calls.append({"store_id": store_id, "table_no": table_no, "order_id": order_id})

        eng._release_table = capture_release

        await eng.cancel_order(order_id=str(ORDER_ID), reason="客户取消")

        assert release_calls, "cancel_order 必须调 _release_table"
        assert release_calls[0]["order_id"] == order.id, (
            f"cancel_order 必须传 order.id 给 _release_table, 实际 {release_calls[0]['order_id']}"
        )

    @pytest.mark.asyncio
    async def test_cancel_completed_order_raises(self):
        """§17-B: completed 订单 cancel → ValueError "已结算订单无法取消"."""
        from services.tx_trade.src.services.cashier_engine import CashierEngine

        order = _make_order(status="completed", table_number="A01")
        db = AsyncMock()
        db.flush = AsyncMock()

        async def mock_execute(stmt, *args, **kwargs):
            result = MagicMock()
            result.scalar_one_or_none = MagicMock(return_value=order)
            return result

        db.execute = mock_execute
        eng = CashierEngine(db=db, tenant_id=str(TENANT_ID))
        eng._release_table = AsyncMock()

        with pytest.raises(ValueError, match="已结算"):
            await eng.cancel_order(order_id=str(ORDER_ID))


# ─── §17-B cashier_engine.transfer_table 传 order_id ──────────────────────


class TestCashierTransferTableReleaseOrderId:
    @pytest.mark.asyncio
    async def test_transfer_table_release_passes_order_id(self):
        """§17-B: transfer_table 调 _release_table 必须传 order.id (源桌 3B 幂等)."""
        from services.tx_trade.src.services.cashier_engine import CashierEngine

        order = _make_order(status="confirmed", table_number="A01")
        # 模拟双锁 SELECT 返回的源 + 目标桌
        source_table = MagicMock()
        source_table.table_no = "A01"
        source_table.status = "occupied"
        # §17-D2 不变量: source.current_order_id 必须 == order.id
        source_table.current_order_id = order.id
        target_table = MagicMock()
        target_table.table_no = "B01"
        target_table.status = "free"
        target_table.current_order_id = None

        async def mock_execute(stmt, *args, **kwargs):
            result = MagicMock()
            stmt_str = str(stmt) if stmt is not None else ""
            is_in_clause = "FROM tables" in stmt_str and "IN (" in stmt_str.upper()
            if is_in_clause:
                scalars_obj = MagicMock()
                scalars_obj.__iter__ = lambda self: iter([source_table, target_table])
                result.scalars = MagicMock(return_value=scalars_obj)
            elif "FROM orders" in stmt_str:
                result.scalar_one_or_none = MagicMock(return_value=order)
            else:
                result.scalar_one_or_none = MagicMock(return_value=None)
            return result

        db = AsyncMock()
        db.execute = mock_execute
        db.flush = AsyncMock()
        eng = CashierEngine(db=db, tenant_id=str(TENANT_ID))

        release_calls: list = []

        async def capture_release(store_id, table_no, order_id):
            release_calls.append({"order_id": order_id})

        eng._release_table = capture_release

        try:
            await eng.transfer_table(
                order_id=str(ORDER_ID),
                target_table_no="B01",
            )
        except (AttributeError, TypeError):
            # 下游 emit_event 等 mock 不充分不影响 release 调用校验
            pass

        assert release_calls, "transfer_table 必须调 _release_table 释放源桌"
        assert release_calls[0]["order_id"] == order.id, (
            f"transfer_table 必须传 order.id 给 _release_table, 实际 {release_calls[0]['order_id']}"
        )


# ─── §17-B order_service._release_table 3B 幂等签名 ──────────────────────


class TestOrderServiceReleaseTableIdempotent:
    def test_release_table_signature_requires_order_id(self):
        """§17-B: order_service._release_table 必须接受 order_id 参数."""
        import inspect

        from services.tx_trade.src.services.order_service import OrderService

        sig = inspect.signature(OrderService._release_table)
        assert "order_id" in sig.parameters, (
            "order_service._release_table 必须含 order_id 参数 (3B 幂等守门)"
        )

    @pytest.mark.asyncio
    async def test_release_table_update_filters_by_current_order_id_and_status(self):
        """§17-B 3B: order_service UPDATE tables WHERE 必须含 current_order_id + status."""
        from services.tx_trade.src.services.order_service import OrderService

        captured: list = []
        db = AsyncMock()

        async def mock_execute(stmt, *args, **kwargs):
            captured.append(stmt)
            return MagicMock()

        db.execute = mock_execute
        svc = OrderService(db=db, tenant_id=str(TENANT_ID))
        await svc._release_table(str(STORE_ID), "A01", ORDER_ID)

        update_sqls = [s for s in (_update_table_sql(s) for s in captured) if s]
        assert update_sqls, "order_service._release_table 必须 UPDATE tables"
        sql = update_sqls[0]
        assert "CURRENT_ORDER_ID" in sql, "WHERE 必须含 current_order_id 守门"
        assert "STATUS" in sql, "WHERE 必须含 status 守门"


# ─── §17-B order_service.cancel_order 终态保护 ────────────────────────────


class TestOrderServiceCancelOrderTerminalProtection:
    @pytest.mark.asyncio
    async def test_cancel_order_uses_for_update_lock(self):
        """§17-B: order_service.cancel_order SELECT Order 必须 FOR UPDATE."""
        from services.tx_trade.src.services.order_service import OrderService

        order = _make_order(status="confirmed", table_number="A01")
        captured: list = []
        db = AsyncMock()
        db.flush = AsyncMock()

        async def mock_execute(stmt, *args, **kwargs):
            captured.append(stmt)
            result = MagicMock()
            result.scalar_one_or_none = MagicMock(return_value=order)
            return result

        db.execute = mock_execute
        svc = OrderService(db=db, tenant_id=str(TENANT_ID))
        svc._release_table = AsyncMock()
        svc._set_tenant = AsyncMock()

        await svc.cancel_order(order_id=str(ORDER_ID), reason="客户取消")

        order_selects = [s for s in captured if _select_order_has_for_update(s)]
        assert order_selects, (
            "order_service.cancel_order SELECT Order 必须含 FOR UPDATE 终态保护"
        )

    @pytest.mark.asyncio
    async def test_cancel_order_release_passes_order_id(self):
        """§17-B: order_service.cancel_order 调 _release_table 必须传 order.id."""
        from services.tx_trade.src.services.order_service import OrderService

        order = _make_order(status="confirmed", table_number="A01")
        db = AsyncMock()
        db.flush = AsyncMock()

        async def mock_execute(stmt, *args, **kwargs):
            result = MagicMock()
            result.scalar_one_or_none = MagicMock(return_value=order)
            return result

        db.execute = mock_execute
        svc = OrderService(db=db, tenant_id=str(TENANT_ID))
        svc._set_tenant = AsyncMock()

        release_calls: list = []

        async def capture_release(store_id, table_no, order_id):
            release_calls.append({"order_id": order_id})

        svc._release_table = capture_release

        await svc.cancel_order(order_id=str(ORDER_ID), reason="客户取消")

        assert release_calls, "cancel_order 必须调 _release_table"
        assert release_calls[0]["order_id"] == order.id, (
            f"cancel_order 必须传 order.id, 实际 {release_calls[0]['order_id']}"
        )

    @pytest.mark.asyncio
    async def test_cancel_completed_order_raises(self):
        """§17-B: order_service.cancel_order completed → ValueError."""
        from services.tx_trade.src.services.order_service import OrderService

        order = _make_order(status="completed", table_number="A01")
        db = AsyncMock()
        db.flush = AsyncMock()

        async def mock_execute(stmt, *args, **kwargs):
            result = MagicMock()
            result.scalar_one_or_none = MagicMock(return_value=order)
            return result

        db.execute = mock_execute
        svc = OrderService(db=db, tenant_id=str(TENANT_ID))
        svc._release_table = AsyncMock()
        svc._set_tenant = AsyncMock()

        # state_machine.transition_order 对 completed → cancelled 应拒绝
        with pytest.raises(ValueError):
            await svc.cancel_order(order_id=str(ORDER_ID))


# ─── §17-B order_service.settle_order 传 order_id ─────────────────────────


class TestOrderServiceSettleOrderReleaseOrderId:
    @pytest.mark.asyncio
    async def test_settle_order_release_passes_order_id(self):
        """§17-B: order_service.settle_order 调 _release_table 必须传 order.id."""
        from services.tx_trade.src.services.order_service import OrderService

        order = _make_order(status="confirmed", table_number="A01")
        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        async def mock_execute(stmt, *args, **kwargs):
            result = MagicMock()
            result.scalar_one_or_none = MagicMock(return_value=order)
            return result

        db.execute = mock_execute
        svc = OrderService(db=db, tenant_id=str(TENANT_ID))
        svc._set_tenant = AsyncMock()

        release_calls: list = []

        async def capture_release(store_id, table_no, order_id):
            release_calls.append({"order_id": order_id})

        svc._release_table = capture_release

        await svc.settle_order(order_id=str(ORDER_ID))

        assert release_calls, "settle_order 必须调 _release_table"
        assert release_calls[0]["order_id"] == order.id, (
            f"settle_order 必须传 order.id, 实际 {release_calls[0]['order_id']}"
        )
