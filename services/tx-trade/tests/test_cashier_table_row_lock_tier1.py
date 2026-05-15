"""§17-A cashier 桌台 row-lock Tier 1 mock 测试 — 正面 mode SQL grep

与 tests/concurrent/test_cashier_table_concurrent_tier1.py (负面 mode 真 PG 并发反测)
互补 — audit doc §8.3 「正面/负面 双模式」 模式。

验证 §17-A 实现路径 SELECT 编译后 SQL 含 FOR UPDATE:
  - open_table (1A): SELECT Table FOR UPDATE
  - change_table_status (1A 衍生): SELECT Table FOR UPDATE
  - transfer_table (2A): SELECT Table WHERE table_no IN (old, target) ORDER BY id FOR UPDATE

业务背景：
  audit doc §11.3 决策追踪表 — 创始人锁定 1A (open_table FOR UPDATE +
  TableOccupiedError) + 2A (transfer_table 双锁排序防 ABBA).

关联：
  - docs/security/tier1-row-lock-audit-2026-05.md §11.1-§11.3
  - tests/concurrent/test_cashier_table_concurrent_tier1.py (负面 mode 真 PG 反测)
  - 修复参考范本: services/tx-member/src/services/stored_value_service.py 11 处锁
  - 测试范本: services/tx-trade/tests/test_cashier_engine_row_lock_tier1.py
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


def _select_has_for_update(stmt) -> bool:
    """检测 SQLAlchemy Select 编译后 SQL 是否含 FOR UPDATE."""
    from sqlalchemy.sql.selectable import Select
    from sqlalchemy.dialects import postgresql

    if not isinstance(stmt, Select):
        return False
    try:
        compiled = str(stmt.compile(dialect=postgresql.dialect()))
        return "FOR UPDATE" in compiled.upper()
    except Exception:
        return getattr(stmt, "_for_update_arg", None) is not None


def _select_has_in_clause_and_order_by_id(stmt) -> bool:
    """检测 transfer_table 双锁 SELECT: WHERE table_no IN (...) ORDER BY id."""
    from sqlalchemy.sql.selectable import Select
    from sqlalchemy.dialects import postgresql

    if not isinstance(stmt, Select):
        return False
    try:
        compiled = str(stmt.compile(dialect=postgresql.dialect())).upper()
        return (
            "TABLE_NO IN" in compiled
            and "ORDER BY" in compiled
            and "TABLES.ID" in compiled  # ORDER BY tables.id ASC 防 ABBA
        )
    except Exception:
        return False


def _make_table(**kw):
    """构造 Table mock."""
    table = MagicMock()
    table.id = kw.get("id", uuid.uuid4())
    table.store_id = kw.get("store_id", STORE_ID)
    table.table_no = kw.get("table_no", "A01")
    table.tenant_id = kw.get("tenant_id", TENANT_ID)
    table.status = kw.get("status", "free")  # TableStatus.free.value
    table.current_order_id = kw.get("current_order_id", None)
    table.is_active = kw.get("is_active", True)
    return table


def _make_order_for_transfer(**kw):
    """构造 Order mock 给 transfer_table 用."""
    from shared.ontology.src.enums import OrderStatus

    order = MagicMock()
    order.id = kw.get("id", ORDER_ID)
    order.store_id = kw.get("store_id", STORE_ID)
    order.tenant_id = kw.get("tenant_id", TENANT_ID)
    order.status = kw.get("status", OrderStatus.confirmed.value)
    order.table_number = kw.get("table_number", "A01")
    order.order_no = kw.get("order_no", "TX20260515000001")
    order.order_metadata = kw.get("order_metadata", {})
    order.table_transfer_from = None
    return order


def _make_engine(db):
    from services.tx_trade.src.services.cashier_engine import CashierEngine

    return CashierEngine(db=db, tenant_id=str(TENANT_ID))


def _build_db_capture(table_to_return=None, order_to_return=None, tables_in_clause=None):
    """构造 AsyncSession mock + capture stmts.

    table_to_return: 单 Table 查询 (open_table / change_table_status) 返回值
    order_to_return: Order 查询返回值 (transfer_table 用)
    tables_in_clause: transfer_table 双查 IN (...) 返回的 list[Table]
    """
    db = AsyncMock()
    captured: list = []

    async def mock_execute(stmt, *args, **kwargs):
        captured.append(stmt)
        result = MagicMock()
        stmt_str = str(stmt) if stmt is not None else ""
        is_table_query = "FROM tables" in stmt_str
        is_order_query = (
            "FROM orders" in stmt_str and "FROM tables" not in stmt_str
        )
        is_in_clause = "IN (" in stmt_str.upper() and is_table_query

        if is_in_clause and tables_in_clause is not None:
            scalar_iter = iter(tables_in_clause)
            scalars_obj = MagicMock()
            scalars_obj.__iter__ = lambda self: iter(tables_in_clause)
            result.scalars = MagicMock(return_value=scalars_obj)
        elif is_table_query and table_to_return is not None:
            result.scalar_one_or_none = MagicMock(return_value=table_to_return)
        elif is_order_query and order_to_return is not None:
            result.scalar_one_or_none = MagicMock(return_value=order_to_return)
        else:
            result.scalar_one_or_none = MagicMock(return_value=None)
            scalars_obj = MagicMock()
            scalars_obj.__iter__ = lambda self: iter([])
            result.scalars = MagicMock(return_value=scalars_obj)

        return result

    db.execute = mock_execute
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db, captured


# ─── §17-A 1A: open_table FOR UPDATE ─────────────────────────────────────────


class TestOpenTableRowLock:
    @pytest.mark.asyncio
    async def test_open_table_uses_for_update_row_lock(self):
        """§17-A 1A: open_table SELECT Table 必须 FOR UPDATE 防双开台 race.

        Race (audit §11.2 选择题 1): 双 POS / 前台 + POS 同时开同一桌 →
        两路并发都通过 status='free' 校验 → 各自 UPDATE → 后写者覆盖, 第一个
        订单失去桌台引用. FOR UPDATE 行锁串行化让第二路看到 status='occupied'
        抛 TableOccupiedError.
        """
        table = _make_table(status="free")
        db, captured = _build_db_capture(table_to_return=table)

        # patch Store query to return None (避免 store.config 算术)
        eng = _make_engine(db)
        try:
            await eng.open_table(
                store_id=str(STORE_ID),
                table_no="A01",
                waiter_id=str(uuid.uuid4()),
                guest_count=4,
            )
        except (AttributeError, TypeError):
            # store/customer/event 后续路径 mock 不充分, 不影响 SELECT Table 的 lock 校验
            pass

        # 找 SELECT Table 语句
        table_selects = [
            s for s in captured
            if "FROM tables" in str(s) and not isinstance(s, str)
        ]
        assert table_selects, "open_table 必须 SELECT tables"
        # 至少 1 条 SELECT Table 含 FOR UPDATE
        assert any(_select_has_for_update(s) for s in table_selects), (
            "open_table SELECT Table 必须含 FOR UPDATE 行锁 (1A 强一致)"
        )

    @pytest.mark.asyncio
    async def test_open_table_occupied_raises_typed_error(self):
        """§17-A 1A: 非 free 状态 → raise TableOccupiedError (typed exception).

        上层路由层可 typed catch 区分 "桌台已被并发占用" vs 通用业务错误,
        前端弹窗提示用户刷新桌台地图.
        """
        from services.tx_trade.src.services.cashier_engine import (
            TableOccupiedError,
        )

        table = _make_table(status="occupied")
        db, _ = _build_db_capture(table_to_return=table)
        eng = _make_engine(db)

        with pytest.raises(TableOccupiedError, match="并发占用"):
            await eng.open_table(
                store_id=str(STORE_ID),
                table_no="A01",
                waiter_id=str(uuid.uuid4()),
                guest_count=4,
            )

    def test_table_occupied_error_inherits_value_error(self):
        """TableOccupiedError 继承 ValueError 保兼容 — 现有 except ValueError caller 不破坏."""
        from services.tx_trade.src.services.cashier_engine import (
            TableOccupiedError,
        )

        assert issubclass(TableOccupiedError, ValueError)


# ─── §17-A 1A 衍生: change_table_status FOR UPDATE ──────────────────────────


class TestChangeTableStatusRowLock:
    @pytest.mark.asyncio
    async def test_change_table_status_uses_for_update(self):
        """§17-A 1A 衍生: change_table_status SELECT Table 必须 FOR UPDATE.

        防 state_machine 校验后到 UPDATE 之间并发覆盖窗口 (与 open_table 同
        强一致 pattern, audit §11.1 关联路径).
        """
        table = _make_table(status="free")
        db, captured = _build_db_capture(table_to_return=table)
        eng = _make_engine(db)

        # change_table_status 走 state_machine 校验，free → cleaning 是合法转换
        try:
            await eng.change_table_status(
                store_id=str(STORE_ID),
                table_no="A01",
                target_status="cleaning",
            )
        except (ValueError, AttributeError, TypeError):
            # state_machine 校验或下游 mock 不充分不影响 SELECT lock 校验
            pass

        table_selects = [s for s in captured if "FROM tables" in str(s)]
        assert table_selects, "change_table_status 必须 SELECT tables"
        assert any(_select_has_for_update(s) for s in table_selects), (
            "change_table_status SELECT Table 必须含 FOR UPDATE 行锁 (1A 衍生)"
        )


# ─── §17-A 2A: transfer_table 双锁排序 ──────────────────────────────────────


class TestTransferTableRowLock:
    @pytest.mark.asyncio
    async def test_transfer_table_uses_double_lock_sorted_by_id(self):
        """§17-A 2A: transfer_table 必须双桌按 id ASC FOR UPDATE.

        Race (audit §11.2 选择题 2): 两路 swap (A→B + B→A) 不按 id 排序锁
        会形成 ABBA 死锁. 单条 SELECT WHERE table_no IN (old, target) ORDER BY
        tables.id WITH FOR UPDATE 由 PG 在 ORDER BY 评估后施锁, 锁顺序
        deterministic 安全.
        """
        order = _make_order_for_transfer(table_number="A01")
        # §17-D2 不变量: source.current_order_id 必须 == order.id (transfer 入口 guard)
        source = _make_table(table_no="A01", status="occupied", current_order_id=ORDER_ID)
        target = _make_table(table_no="B01", status="free")

        db, captured = _build_db_capture(
            order_to_return=order,
            tables_in_clause=[source, target],
        )
        eng = _make_engine(db)

        try:
            await eng.transfer_table(
                order_id=str(ORDER_ID),
                target_table_no="B01",
            )
        except (AttributeError, TypeError):
            # 下游 _release_table / order_metadata 等 mock 不充分不影响双锁 SELECT 校验
            pass

        # 找 IN clause + ORDER BY id + FOR UPDATE 的 SELECT
        table_selects = [s for s in captured if "FROM tables" in str(s)]
        assert table_selects, "transfer_table 必须 SELECT tables"

        # 至少 1 条 SELECT Table 是 IN clause + ORDER BY id + FOR UPDATE
        double_lock_selects = [
            s for s in table_selects
            if _select_has_in_clause_and_order_by_id(s) and _select_has_for_update(s)
        ]
        assert double_lock_selects, (
            "transfer_table 必须用 SELECT WHERE table_no IN (...) ORDER BY tables.id "
            "WITH FOR UPDATE (2A 双锁排序防 ABBA 死锁)"
        )

    @pytest.mark.asyncio
    async def test_transfer_table_target_occupied_raises_typed_error(self):
        """§17-A 2A: 目标桌非 free → raise TableOccupiedError (typed)."""
        from services.tx_trade.src.services.cashier_engine import (
            TableOccupiedError,
        )

        order = _make_order_for_transfer(table_number="A01")
        # §17-D2 不变量: source.current_order_id 必须 == order.id
        source = _make_table(table_no="A01", status="occupied", current_order_id=ORDER_ID)
        # 目标桌已 occupied (其他订单)
        target_occupied = _make_table(table_no="B01", status="occupied")

        db, _ = _build_db_capture(
            order_to_return=order,
            tables_in_clause=[source, target_occupied],
        )
        eng = _make_engine(db)

        with pytest.raises(TableOccupiedError, match="并发占用"):
            await eng.transfer_table(
                order_id=str(ORDER_ID),
                target_table_no="B01",
            )


# ─── §17-D2 transfer_table source_table.current_order_id 不变量 ───────────────


class TestTransferTableSourceInvariant:
    """§17-D2: transfer_table source_table.current_order_id 不变量校验.

    §17-A pre-existing scope (PR #652 仅校验 source 存在) + §17-B round-1 P2 落
    follow-up. race 场景: settle 已释放源桌 (current_order_id 切 NULL 或被新 order
    重 occupy), transfer 不应继续把 target 占住 + 改 completed 订单 table_number.

    与 §17-B 3B 幂等下游污染面收紧互补 — §17-B 让 _release_table 旧 order_id
    不污染新 occupy; §17-D2 让 transfer 入口直接拒绝 stale source 引用.

    关联: §17-C PR #655 round-1 P2 / audit doc §11.4 §17-D2.
    """

    @pytest.mark.asyncio
    async def test_transfer_table_raises_when_source_released_by_settle(self):
        """§17-D2: settle 已释放源桌 (source.current_order_id=None) → transfer 拒绝.

        真实场景: 服务员 POS 触发 settle 完成 → 源桌 release → 同时 PWA 触发 transfer
        操作落地; transfer 拿到 source.current_order_id=None ≠ order_uuid → 拒绝.
        """
        order = _make_order_for_transfer(table_number="A01")
        # source 已被 settle 释放: current_order_id=None
        source_released = _make_table(table_no="A01", status="free", current_order_id=None)
        target = _make_table(table_no="B01", status="free")

        db, _ = _build_db_capture(
            order_to_return=order,
            tables_in_clause=[source_released, target],
        )
        eng = _make_engine(db)

        with pytest.raises(ValueError, match="不匹配"):
            await eng.transfer_table(
                order_id=str(ORDER_ID),
                target_table_no="B01",
            )

    @pytest.mark.asyncio
    async def test_transfer_table_raises_when_source_reoccupied_by_other_order(self):
        """§17-D2: source 被新 order 重 occupy → transfer 拒绝, 不污染新 order.

        race 场景: settle 释放源桌 → 新 order 重 occupy → 旧 transfer 重试.
        source.current_order_id = 新 order_id ≠ 旧 order_uuid → 拒绝.
        """
        import uuid as _u

        order = _make_order_for_transfer(table_number="A01")
        # source 已被新 order 重 occupy
        new_order_id = _u.uuid4()
        source_reoccupied = _make_table(
            table_no="A01", status="occupied", current_order_id=new_order_id
        )
        target = _make_table(table_no="B01", status="free")

        db, _ = _build_db_capture(
            order_to_return=order,
            tables_in_clause=[source_reoccupied, target],
        )
        eng = _make_engine(db)

        with pytest.raises(ValueError, match="不匹配"):
            await eng.transfer_table(
                order_id=str(ORDER_ID),
                target_table_no="B01",
            )
