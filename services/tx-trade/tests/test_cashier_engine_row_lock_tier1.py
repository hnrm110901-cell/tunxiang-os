"""Tier 1 行锁测试：cashier_engine 3 P0 路径必须 with_for_update 防并发 race

核心约束：200 桌并发收银 / 折扣 / 结算时，同一订单 SELECT 必须 FOR UPDATE
        串行化，防丢更新 / 双结算 / 双扣款。

业务场景（真实餐厅）：
  1) add_item — 桌长在 POS 加菜 + 服务员手机 PWA 同时加菜 → 必须串行写 total
  2) apply_discount — 收银员打折 + 经理改折扣 race → 必须串行 + 毛利底线校验生效
  3) settle_order — POS 重试 / 用户连点结算 → 必须只完成 1 次 + 释放桌台 1 次

关联：
  - docs/security/tier1-row-lock-audit-2026-05.md §4.1 (cashier_engine 全文 0 FOR UPDATE)
  - Issue #532 (audit parent), PR-D of 6-PR fix roadmap
  - 修复参考范本：services/tx-member/src/services/stored_value_service.py 11 处锁
  - PR-A/B 测试范本：services/tx-supply/tests/test_inventory_io_row_lock_tier1.py
  - PR-A/B/C 已 ship：PR #544 (tx-finance) / PR #547 (tx-supply) / PR #553 (payment_saga)
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
# cashier_engine 顶层 import `shared.events`，后者用 `dataclass(slots=True)`
# 仅 Python 3.10+ 支持。本机 3.9 跑会 TypeError；CI Python 3.11 原生通过。
# 用 sys.version_info gate 而非 sys.modules stub（PR-A round-1 教训：
# stub 注入 'shared' 包污染同目录 test_invoice_tier1.py 等真实 shared.* import）。
if sys.version_info < (3, 10):
    pytest.skip(
        "需 Python 3.10+ (shared.events 用 dataclass slots=True)；CI Python 3.11 跑通",
        allow_module_level=True,
    )


TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
STORE_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
ORDER_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")
DISH_ID = uuid.UUID("00000000-0000-0000-0000-000000000004")


def _select_has_for_update(stmt) -> bool:
    """检测 SQLAlchemy Select 编译后 SQL 是否含 FOR UPDATE.

    用 postgresql 方言 compile 而非检查私有属性 `_for_update_arg`，
    更稳定（属性名在 SQLAlchemy 主版本间可能变化）。PR-A/B 已验证此模式。
    """
    from sqlalchemy.sql.selectable import Select
    from sqlalchemy.dialects import postgresql

    if not isinstance(stmt, Select):
        return False
    try:
        compiled = str(stmt.compile(dialect=postgresql.dialect()))
        return "FOR UPDATE" in compiled.upper()
    except Exception:
        return getattr(stmt, "_for_update_arg", None) is not None


def _make_order(**kw):
    """构造 Order mock，含 cashier_engine 业务路径需要的字段."""
    from shared.ontology.src.enums import OrderStatus

    order = MagicMock()
    order.id = kw.get("id", ORDER_ID)
    order.tenant_id = kw.get("tenant_id", TENANT_ID)
    order.store_id = kw.get("store_id", STORE_ID)
    order.status = kw.get("status", OrderStatus.confirmed.value)
    order.total_amount_fen = kw.get("total_amount_fen", 10000)
    order.discount_amount_fen = kw.get("discount_amount_fen", 0)
    order.final_amount_fen = kw.get("final_amount_fen", 10000)
    order.table_number = kw.get("table_number", "A01")
    order.order_no = kw.get("order_no", "TX20260513000001")
    order.order_metadata = kw.get("order_metadata", {})
    order.customer_id = kw.get("customer_id", None)
    order.discount_type = kw.get("discount_type", None)
    order.gross_margin_before = kw.get("gross_margin_before", None)
    order.gross_margin_after = kw.get("gross_margin_after", None)
    order.margin_alert_flag = kw.get("margin_alert_flag", False)
    order.completed_at = kw.get("completed_at", None)
    return order


def _make_engine(db):
    """构造 CashierEngine 实例，注入 mock db."""
    from services.tx_trade.src.services.cashier_engine import CashierEngine

    return CashierEngine(db=db, tenant_id=TENANT_ID)


def _build_db_capture(order_to_return, dish_to_return=None):
    """构造 AsyncSession mock，capture 所有 execute 的 stmt.

    add_item 路径返回 (Order, Dish) row；其他单 SELECT 路径返回 scalar Order.
    """
    db = AsyncMock()
    captured: list = []

    async def mock_execute(stmt, *args, **kwargs):
        captured.append(stmt)
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=order_to_return)
        # add_item 单次查询返回 (Order, Dish) row
        if dish_to_return is not None:
            row = (order_to_return, dish_to_return)
            result.one_or_none = MagicMock(return_value=row)
        else:
            result.one_or_none = MagicMock(return_value=None)
        return result

    db.execute = mock_execute
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    return db, captured


class TestCashierEngineRowLockTier1:
    """cashier_engine.py 3 P0 路径必须 with_for_update 防并发丢更新.

    与 services/tx-member/src/services/stored_value_service.py 模式对齐
    （11 处 .with_for_update()）— 全仓 row-lock 最严谨服务.
    """

    @pytest.mark.asyncio
    async def test_add_item_uses_for_update_row_lock(self):
        """200 桌并发场景：桌长在 POS 加菜 + 服务员 PWA 同时加菜同一桌

        Race（audit doc §4.1 P0）：
          两路并发读 total_amount_fen=10000 → 各算 new_total = 10000 + subtotal
          → 后 flush 覆盖前 → 一道菜钱丢了（直接威胁资金路径）.
        期望：select(Order, Dish) 编译后 SQL 含 FOR UPDATE 锁住 Order 行.
        """
        order = _make_order()
        dish = MagicMock()
        dish.id = DISH_ID
        dish.cost_fen = 300  # BOM 成本
        db, captured = _build_db_capture(order, dish_to_return=dish)
        eng = _make_engine(db)

        await eng.add_item(
            order_id=str(ORDER_ID),
            dish_id=str(DISH_ID),
            dish_name="水煮鱼",
            qty=1,
            unit_price_fen=8800,
            pricing_mode="fixed",
        )

        # 至少一条 captured stmt 是 Select(Order, ...) 且含 FOR UPDATE
        locked_selects = [s for s in captured if _select_has_for_update(s)]
        assert locked_selects, (
            f"add_item 的 SELECT(Order, Dish) 必须含 FOR UPDATE 锁 Order 行，"
            f"防 200 桌并发加菜 total 丢更新。captured: {captured}"
        )

    @pytest.mark.asyncio
    async def test_add_item_without_dish_locks_order(self):
        """加非配方菜（无 dish_id）走 _get_order(lock=True) 分支必须也锁."""
        order = _make_order()
        db, captured = _build_db_capture(order)
        eng = _make_engine(db)

        await eng.add_item(
            order_id=str(ORDER_ID),
            dish_id="",  # 走 _get_order 分支
            dish_name="临时菜",
            qty=1,
            unit_price_fen=5000,
        )

        locked_selects = [s for s in captured if _select_has_for_update(s)]
        assert locked_selects, (
            f"add_item 无 dish_id 分支必须经 _get_order(lock=True) 加 FOR UPDATE，"
            f"captured: {captured}"
        )

    @pytest.mark.asyncio
    async def test_apply_discount_uses_for_update_row_lock(self):
        """收银员打折 + 经理改折扣 race — 必须串行化保毛利底线生效

        Race（audit doc §4.1 P0，毛利底线硬约束）：
          两路并发读 total=10000 → 各算 discount_fen → 各 flush
          → 后写覆盖前 → 折扣金额错 + 毛利底线校验基于过期数据通过 → 资金 + 毛利双失.
        期望：_get_order 路径 SELECT 编译后含 FOR UPDATE.
        """
        from shared.ontology.src.enums import OrderStatus

        order = _make_order(status=OrderStatus.confirmed.value, total_amount_fen=10000)
        db, captured = _build_db_capture(order)
        eng = _make_engine(db)

        # 注入 _calc_order_cost mock（毛利底线校验依赖；避开真 SQL）
        eng._calc_order_cost = AsyncMock(return_value=3000)  # 30% 成本

        await eng.apply_discount(
            order_id=str(ORDER_ID),
            discount_type="amount_off",
            discount_value=1000,  # 减 10 元 — 毛利仍 > 30% 通过
            reason="VIP 折扣",
            approval_id="manual",  # 跳过审批分支
        )

        locked_selects = [s for s in captured if _select_has_for_update(s)]
        assert locked_selects, (
            f"apply_discount 的 _get_order SELECT 必须含 FOR UPDATE，"
            f"防 race 导致毛利底线绕过。captured: {captured}"
        )

    @pytest.mark.asyncio
    async def test_settle_order_uses_for_update_row_lock(self):
        """POS 重试 / 网关回调 / 用户连点 — 必须只完成 1 次结算

        Race（audit doc §4.1 P0，资金路径双结算）：
          两路并发读 status=confirmed → 各创建 payment 记录 + 各 transition_order(completed)
          → 双 payment 入库 + 桌台双释放 → 双扣款 / 桌台 占用错乱.
        期望：_get_order 路径 SELECT 编译后含 FOR UPDATE.
        """
        from shared.ontology.src.enums import OrderStatus

        order = _make_order(
            status=OrderStatus.confirmed.value,
            total_amount_fen=10000,
            final_amount_fen=10000,
        )
        db, captured = _build_db_capture(order)
        eng = _make_engine(db)

        # 注入 _release_table 避免真 SQL
        eng._release_table = AsyncMock()

        await eng.settle_order(
            order_id=str(ORDER_ID),
            payments=[{"method": "cash", "amount_fen": 10000}],
            auto_pay=False,
        )

        locked_selects = [s for s in captured if _select_has_for_update(s)]
        assert locked_selects, (
            f"settle_order 的 _get_order SELECT 必须含 FOR UPDATE，"
            f"防 POS 重试导致双结算 / 桌台双释放。captured: {captured}"
        )


class TestGetOrderHelperContract:
    """_get_order helper 契约：lock kwarg 默认 False 保 read-only 入口性能."""

    @pytest.mark.asyncio
    async def test_get_order_default_no_lock(self):
        """read-only 入口（如查单 / 状态查看）默认不加锁，避免阻塞高频读路径."""
        order = _make_order()
        db, captured = _build_db_capture(order)
        eng = _make_engine(db)

        await eng._get_order(ORDER_ID)

        assert captured, "至少一次 SELECT 应被 capture"
        locked = [s for s in captured if _select_has_for_update(s)]
        assert not locked, (
            f"_get_order 默认 lock=False 不应加 FOR UPDATE，"
            f"保 read-only 路径性能。captured: {captured}"
        )

    @pytest.mark.asyncio
    async def test_get_order_lock_true_adds_for_update(self):
        """Tier 1 mutation 入口显式 lock=True 必须加 FOR UPDATE."""
        order = _make_order()
        db, captured = _build_db_capture(order)
        eng = _make_engine(db)

        await eng._get_order(ORDER_ID, lock=True)

        locked = [s for s in captured if _select_has_for_update(s)]
        assert locked, (
            f"_get_order(lock=True) 必须加 FOR UPDATE。captured: {captured}"
        )
