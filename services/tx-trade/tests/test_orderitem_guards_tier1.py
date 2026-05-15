"""§17-D1 OrderItem defensive guards Tier 1 测试

3 项 follow-up bundle (§17-C round-1 P2 残留):
  - P2-1: cashier_engine.update_item / remove_item OrderItem SELECT
    必须含 `OrderItem.tenant_id == self.tenant_id` 显式过滤 (cashier 类不调 _set_tenant)
  - P2-2: order_service.update_item_quantity / remove_item 接受 optional order_id
    参数, provided 时校验 `item.order_id == UUID(order_id)` 防 caller 误传
  - P2-3: 二次 remove 同 item 应抛 ValueError "OrderItem not found" (regression guard,
    防未来重构 silent 成功后果)

业务背景:
  - cashier_engine 类既定不调 _set_tenant — 通过显式 WHERE tenant_id 实现租户
    隔离 (与 _release_table §17-A P0-1 修复同模式)
  - order_service 路由层有 order_id 路径参数, service 层若不校验 item.order_id
    归属, 跨 order item_id 误传可静默命中改错 order
  - 二次 remove 行为已经是 "raise NotFound" (item 已 delete), 但缺测试 lock-in

关联:
  - §17-C PR #655 round-1 P2-1/2/3 落 §17-D follow-up bundle
  - 修复参考范本: services/tx-member/src/services/stored_value_service.py (显式 tenant_id)
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
OTHER_ORDER_ID = uuid.UUID("00000000-0000-0000-0000-000000000099")
ITEM_ID = uuid.UUID("00000000-0000-0000-0000-000000000004")


def _select_orderitem_compiled(stmt) -> str | None:
    """如果 stmt 是 SELECT FROM order_items → 返回编译后 SQL 大写; 否则 None."""
    try:
        from sqlalchemy.dialects import postgresql
        from sqlalchemy.sql.selectable import Select

        if not isinstance(stmt, Select):
            return None
        compiled = str(stmt.compile(dialect=postgresql.dialect())).upper()
        if "FROM ORDER_ITEMS" not in compiled:
            return None
        return compiled
    except Exception:
        return None


def _make_order(**kw):
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
    """构造 AsyncSession mock + capture stmts."""
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


# ─── P2-1: cashier OrderItem SELECT 含 tenant_id 显式过滤 ─────────────────────


class TestCashierOrderItemTenantIdFilter:
    """§17-D1 P2-1: cashier 类不调 _set_tenant, OrderItem SELECT 必须显式
    `tenant_id == self.tenant_id` 防 internal session 跨租户命中 (与 _release_table
    §17-A P0-1 修复同模式)."""

    @pytest.mark.asyncio
    async def test_update_item_orderitem_select_has_tenant_id_filter(self):
        """cashier_engine.update_item SELECT OrderItem WHERE 必须含 tenant_id."""
        order = _make_order()
        item = _make_item()
        db, captured = _build_db_capture(order=order, item=item)
        eng = _make_engine(db)

        await eng.update_item(
            order_id=str(ORDER_ID),
            item_id=str(ITEM_ID),
            quantity=3,
        )

        orderitem_selects = [
            s for s in (_select_orderitem_compiled(s) for s in captured) if s
        ]
        assert orderitem_selects, "update_item 必须 SELECT order_items"
        # 检测 tenant_id 出现在 OrderItem SELECT WHERE clause
        has_tenant_filter = any("TENANT_ID" in sql for sql in orderitem_selects)
        assert has_tenant_filter, (
            "cashier_engine.update_item SELECT OrderItem WHERE 必须含 tenant_id 显式过滤 "
            "(cashier 类不调 _set_tenant, defense-in-depth)"
        )

    @pytest.mark.asyncio
    async def test_remove_item_orderitem_select_has_tenant_id_filter(self):
        """cashier_engine.remove_item SELECT OrderItem WHERE 必须含 tenant_id."""
        order = _make_order()
        item = _make_item()
        db, captured = _build_db_capture(order=order, item=item)
        eng = _make_engine(db)

        await eng.remove_item(
            order_id=str(ORDER_ID),
            item_id=str(ITEM_ID),
            reason="测试",
        )

        orderitem_selects = [
            s for s in (_select_orderitem_compiled(s) for s in captured) if s
        ]
        assert orderitem_selects, "remove_item 必须 SELECT order_items"
        has_tenant_filter = any("TENANT_ID" in sql for sql in orderitem_selects)
        assert has_tenant_filter, (
            "cashier_engine.remove_item SELECT OrderItem WHERE 必须含 tenant_id 显式过滤"
        )


# ─── P2-2: order_service order_id 归属校验 ────────────────────────────────────


class TestOrderServiceOrderIdGuard:
    """§17-D1 P2-2: order_service.update_item_quantity / remove_item 接受 optional
    order_id 参数. provided 时校验 `item.order_id == UUID(order_id)`."""

    @pytest.mark.asyncio
    async def test_update_item_quantity_raises_on_order_id_mismatch(self):
        """update_item_quantity 传不属于该 item 的 order_id → raise ValueError."""
        # item.order_id = ORDER_ID, caller 传 OTHER_ORDER_ID → mismatch
        item = _make_item(order_id=ORDER_ID)
        db, _ = _build_db_capture(item=item)
        svc = _make_service(db)
        svc._set_tenant = AsyncMock()

        with pytest.raises(ValueError, match="不属于 Order"):
            await svc.update_item_quantity(
                item_id=str(ITEM_ID),
                new_quantity=3,
                order_id=str(OTHER_ORDER_ID),
            )

    @pytest.mark.asyncio
    async def test_update_item_quantity_passes_on_order_id_match(self):
        """update_item_quantity 传匹配 order_id → 正常 mutation 不抛."""
        item = _make_item(order_id=ORDER_ID)
        db, _ = _build_db_capture(item=item)
        svc = _make_service(db)
        svc._set_tenant = AsyncMock()

        result = await svc.update_item_quantity(
            item_id=str(ITEM_ID),
            new_quantity=3,
            order_id=str(ORDER_ID),  # 匹配
        )
        assert result["new_quantity"] == 3

    @pytest.mark.asyncio
    async def test_update_item_quantity_backward_compat_no_order_id(self):
        """update_item_quantity 不传 order_id (旧 caller) → 跳过校验保兼容."""
        item = _make_item(order_id=ORDER_ID)
        db, _ = _build_db_capture(item=item)
        svc = _make_service(db)
        svc._set_tenant = AsyncMock()

        # 不传 order_id, 旧 caller 兼容
        result = await svc.update_item_quantity(
            item_id=str(ITEM_ID),
            new_quantity=3,
        )
        assert result["new_quantity"] == 3

    @pytest.mark.asyncio
    async def test_remove_item_raises_on_order_id_mismatch(self):
        """remove_item 传不属于该 item 的 order_id → raise ValueError."""
        item = _make_item(order_id=ORDER_ID)
        db, _ = _build_db_capture(item=item)
        svc = _make_service(db)
        svc._set_tenant = AsyncMock()

        with pytest.raises(ValueError, match="不属于 Order"):
            await svc.remove_item(
                item_id=str(ITEM_ID),
                order_id=str(OTHER_ORDER_ID),
            )

    @pytest.mark.asyncio
    async def test_remove_item_passes_on_order_id_match(self):
        """remove_item 传匹配 order_id → 正常 delete."""
        item = _make_item(order_id=ORDER_ID)
        db, _ = _build_db_capture(item=item)
        svc = _make_service(db)
        svc._set_tenant = AsyncMock()

        result = await svc.remove_item(
            item_id=str(ITEM_ID),
            order_id=str(ORDER_ID),  # 匹配
        )
        assert result["removed_item_id"] == str(ITEM_ID)


# ─── P2-3: 二次 remove NotFound 测试 ─────────────────────────────────────────


class TestSecondRemoveRaisesNotFound:
    """§17-D1 P2-3: 二次 remove 同 item 应抛 ValueError "OrderItem not found"
    (regression guard, 防未来重构 silent 成功后果).

    场景: race 输者重试 remove 已被 race 赢者 delete 的 item — 应抛 NotFound 而非
    silent 成功 (silent 成功会让客户端误以为操作成功 → 数据不一致).
    """

    @pytest.mark.asyncio
    async def test_second_remove_raises_not_found_order_service(self):
        """order_service.remove_item 第二次 remove 同 item → ValueError."""
        # 模拟第二次 remove: item 已不存在 (前一次 race 赢者 DELETE)
        db, _ = _build_db_capture(item=None)
        svc = _make_service(db)
        svc._set_tenant = AsyncMock()

        with pytest.raises(ValueError, match="OrderItem not found"):
            await svc.remove_item(item_id=str(ITEM_ID))

    @pytest.mark.asyncio
    async def test_second_remove_raises_not_found_cashier(self):
        """cashier_engine.remove_item 第二次 remove 同 item → ValueError."""
        order = _make_order()
        db, _ = _build_db_capture(order=order, item=None)
        eng = _make_engine(db)

        with pytest.raises(ValueError, match="菜品明细不存在"):
            await eng.remove_item(
                order_id=str(ORDER_ID),
                item_id=str(ITEM_ID),
                reason="二次 remove",
            )
