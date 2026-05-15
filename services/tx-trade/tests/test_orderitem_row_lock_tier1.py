"""§17-C OrderItem row-lock Tier 1 mock 测试 — 正面 mode SQL grep

与 tests/concurrent/test_cashier_orderitem_concurrent_tier1.py (负面 mode 真 PG)
互补 — audit doc §8.3 「正面/负面 双模式」 模式。

验证 §17-C 实现:
  - cashier_engine.update_item: SELECT OrderItem FOR UPDATE + _get_order(lock=True)
    (Python-side `new_total = order.total + diff` UPDATE Order 不是 PG 原子)
  - cashier_engine.remove_item: SELECT OrderItem FOR UPDATE + _get_order(lock=True)
  - order_service.update_item_quantity: SELECT OrderItem FOR UPDATE 仅
    (Order UPDATE 用 raw arithmetic `Order.total_amount_fen + diff` 是 PG 原子)
  - order_service.remove_item: SELECT OrderItem FOR UPDATE 仅

业务背景：
  audit doc §4.1 漏锁详单 — cashier_engine.py update_item L462 / remove_item L520 +
  order_service.py update_item_quantity L279 / remove_item L302 全是 SELECT OrderItem
  无锁 + ORM property 改 quantity/subtotal_fen + Order.total 重算.

  Race (200 桌徐记海鲜峰值):
    - 两服务员 PWA 并发改同 item: 都读 subtotal_fen=400 → 各算 diff → 各 mutate
      → Order.total 在 cashier 端 (Python recalc) 后写覆盖前 → 资金错算
    - cashier 端"半安全"指 OrderItem 单独 race + Order Python recalc race 双重风险

关联：
  - docs/security/tier1-row-lock-audit-2026-05.md §4.1 + §7 verifier #1
  - tests/concurrent/test_cashier_orderitem_concurrent_tier1.py (负面 mode 真 PG)
  - 修复参考范本: services/tx-member/src/services/stored_value_service.py 11 处锁
  - §17-A/§17-B 范本: test_cashier_table_row_lock_tier1.py +
    test_cashier_settle_release_row_lock_tier1.py
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
ITEM_ID = uuid.UUID("00000000-0000-0000-0000-000000000004")


def _select_order_has_for_update(stmt) -> bool:
    """SELECT FROM orders ... FOR UPDATE."""
    try:
        from sqlalchemy.dialects import postgresql
        from sqlalchemy.sql.selectable import Select

        if not isinstance(stmt, Select):
            return False
        compiled = str(stmt.compile(dialect=postgresql.dialect())).upper()
        return "FROM ORDERS" in compiled and "FOR UPDATE" in compiled
    except Exception:
        return False


def _select_orderitem_has_for_update(stmt) -> bool:
    """SELECT FROM order_items ... FOR UPDATE."""
    try:
        from sqlalchemy.dialects import postgresql
        from sqlalchemy.sql.selectable import Select

        if not isinstance(stmt, Select):
            return False
        compiled = str(stmt.compile(dialect=postgresql.dialect())).upper()
        return "FROM ORDER_ITEMS" in compiled and "FOR UPDATE" in compiled
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
    order.total_amount_fen = kw.get("total_amount_fen", 10000)
    order.discount_amount_fen = kw.get("discount_amount_fen", 0)
    order.final_amount_fen = kw.get("final_amount_fen", 10000)
    order.table_number = kw.get("table_number", "A01")
    return order


def _make_item(**kw):
    """构造 OrderItem mock — 默认 quantity=2 subtotal=400 unit=200 fixed pricing."""
    item = MagicMock()
    item.id = kw.get("id", ITEM_ID)
    item.order_id = kw.get("order_id", ORDER_ID)
    item.tenant_id = kw.get("tenant_id", TENANT_ID)
    item.quantity = kw.get("quantity", 2)
    item.unit_price_fen = kw.get("unit_price_fen", 200)
    item.subtotal_fen = kw.get("subtotal_fen", 400)
    item.pricing_mode = kw.get("pricing_mode", "fixed")
    item.weight_value = kw.get("weight_value", None)
    item.return_flag = kw.get("return_flag", False)
    item.return_reason = kw.get("return_reason", None)
    item.notes = kw.get("notes", "")
    return item


def _build_db_capture(*, order=None, item=None):
    """构造 AsyncSession mock + capture stmts.

    OrderItem 查询返回 item, Order 查询返回 order. 其他查询返回 None.
    """
    db = AsyncMock()
    captured: list = []

    async def mock_execute(stmt, *args, **kwargs):
        captured.append(stmt)
        result = MagicMock()
        stmt_str = str(stmt) if stmt is not None else ""
        is_orderitem = "FROM order_items" in stmt_str
        is_order = "FROM orders" in stmt_str and "FROM order_items" not in stmt_str
        if is_orderitem and item is not None:
            result.scalar_one_or_none = MagicMock(return_value=item)
        elif is_order and order is not None:
            result.scalar_one_or_none = MagicMock(return_value=order)
        else:
            result.scalar_one_or_none = MagicMock(return_value=None)
        return result

    db.execute = mock_execute
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    return db, captured


def _make_engine(db):
    from services.tx_trade.src.services.cashier_engine import CashierEngine

    return CashierEngine(db=db, tenant_id=str(TENANT_ID))


def _make_service(db):
    from services.tx_trade.src.services.order_service import OrderService

    return OrderService(db=db, tenant_id=str(TENANT_ID))


# ─── §17-C cashier_engine.update_item: OrderItem FOR UPDATE + Order FOR UPDATE ─


class TestCashierUpdateItemRowLock:
    @pytest.mark.asyncio
    async def test_update_item_locks_orderitem(self):
        """§17-C: cashier_engine.update_item SELECT OrderItem 必须 FOR UPDATE.

        Race (audit §4.1 P1, 200 桌徐记海鲜峰值):
          两服务员 PWA 并发改同 item.quantity → 都读 subtotal=400 → 各算 diff
          → 第二个 commit 用过期 diff 算 Order.total → 资金错算.
        FOR UPDATE 让第二路读到第一路 commit 后的 subtotal_fen, 算正确 diff.
        """
        order = _make_order(total_amount_fen=10000)
        item = _make_item(quantity=2, subtotal_fen=400)
        db, captured = _build_db_capture(order=order, item=item)
        eng = _make_engine(db)

        await eng.update_item(
            order_id=str(ORDER_ID),
            item_id=str(ITEM_ID),
            quantity=3,
        )

        item_selects = [s for s in captured if _select_orderitem_has_for_update(s)]
        assert item_selects, (
            "cashier_engine.update_item SELECT OrderItem 必须含 FOR UPDATE "
            "(audit §4.1 P1 OrderItem 漏锁)"
        )

    @pytest.mark.asyncio
    async def test_update_item_locks_order_for_python_recalc(self):
        """§17-C: cashier_engine.update_item _get_order 必须 lock=True.

        cashier_engine.update_item L488-496 是 SELECT-then-UPDATE 模式:
          new_total = order.total_amount_fen + diff  # Python-side
          UPDATE Order SET total_amount_fen = new_total  # literal value
        非 PG 原子, 两路并发可能读相同 old total → 各算 → 后写覆盖前.
        Order FOR UPDATE 串行化让 Python recalc 安全.
        """
        order = _make_order(total_amount_fen=10000)
        item = _make_item(quantity=2, subtotal_fen=400)
        db, captured = _build_db_capture(order=order, item=item)
        eng = _make_engine(db)

        await eng.update_item(
            order_id=str(ORDER_ID),
            item_id=str(ITEM_ID),
            quantity=3,
        )

        order_selects = [s for s in captured if _select_order_has_for_update(s)]
        assert order_selects, (
            "cashier_engine.update_item _get_order 必须 lock=True (Python-side recalc 不是 PG 原子)"
        )


# ─── §17-C cashier_engine.remove_item: OrderItem FOR UPDATE + Order FOR UPDATE ─


class TestCashierRemoveItemRowLock:
    @pytest.mark.asyncio
    async def test_remove_item_locks_orderitem(self):
        """§17-C: cashier_engine.remove_item SELECT OrderItem 必须 FOR UPDATE."""
        order = _make_order(total_amount_fen=10000)
        item = _make_item(subtotal_fen=400)
        db, captured = _build_db_capture(order=order, item=item)
        eng = _make_engine(db)

        await eng.remove_item(
            order_id=str(ORDER_ID),
            item_id=str(ITEM_ID),
            reason="客户不要",
        )

        item_selects = [s for s in captured if _select_orderitem_has_for_update(s)]
        assert item_selects, (
            "cashier_engine.remove_item SELECT OrderItem 必须含 FOR UPDATE"
        )

    @pytest.mark.asyncio
    async def test_remove_item_locks_order_for_python_recalc(self):
        """§17-C: cashier_engine.remove_item _get_order 必须 lock=True."""
        order = _make_order(total_amount_fen=10000)
        item = _make_item(subtotal_fen=400)
        db, captured = _build_db_capture(order=order, item=item)
        eng = _make_engine(db)

        await eng.remove_item(
            order_id=str(ORDER_ID),
            item_id=str(ITEM_ID),
            reason="客户不要",
        )

        order_selects = [s for s in captured if _select_order_has_for_update(s)]
        assert order_selects, (
            "cashier_engine.remove_item _get_order 必须 lock=True"
        )


# ─── §17-C order_service.update_item_quantity: OrderItem FOR UPDATE 仅 ────────


class TestOrderServiceUpdateItemQuantityRowLock:
    @pytest.mark.asyncio
    async def test_update_item_quantity_locks_orderitem(self):
        """§17-C: order_service.update_item_quantity SELECT OrderItem 必须 FOR UPDATE.

        Order UPDATE 用 raw arithmetic `Order.total_amount_fen + diff` 是 PG 原子,
        不需 Order FOR UPDATE; OrderItem 仍需锁 (diff 计算依赖 stale subtotal).
        """
        item = _make_item(quantity=2, subtotal_fen=400)
        db, captured = _build_db_capture(item=item)
        svc = _make_service(db)
        svc._set_tenant = AsyncMock()

        await svc.update_item_quantity(item_id=str(ITEM_ID), new_quantity=3)

        item_selects = [s for s in captured if _select_orderitem_has_for_update(s)]
        assert item_selects, (
            "order_service.update_item_quantity SELECT OrderItem 必须含 FOR UPDATE"
        )


# ─── §17-C order_service.remove_item: OrderItem FOR UPDATE 仅 ─────────────────


class TestOrderServiceRemoveItemRowLock:
    @pytest.mark.asyncio
    async def test_remove_item_locks_orderitem(self):
        """§17-C: order_service.remove_item SELECT OrderItem 必须 FOR UPDATE."""
        item = _make_item(subtotal_fen=400)
        db, captured = _build_db_capture(item=item)
        svc = _make_service(db)
        svc._set_tenant = AsyncMock()

        await svc.remove_item(item_id=str(ITEM_ID))

        item_selects = [s for s in captured if _select_orderitem_has_for_update(s)]
        assert item_selects, (
            "order_service.remove_item SELECT OrderItem 必须含 FOR UPDATE"
        )
