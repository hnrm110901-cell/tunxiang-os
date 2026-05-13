"""Tier 1 行锁测试：inventory_io 3 路径必须 with_for_update 防并发丢更新

关联：
  - docs/security/tier1-row-lock-audit-2026-05.md §4.3 (tx-supply inventory_io 3 路径全裸)
  - PR #538 (audit doc), Issue #532 (audit parent), PR-B of 6-PR fix roadmap
  - 修复参考范本：services/tx-member/src/services/stored_value_service.py 11 处 with_for_update
  - PR-A 范本：services/tx-finance/tests/test_invoice_row_lock_tier1.py

业务影响（audit doc §4.3）：
  - receive_stock (P0)：加权平均并发错算 — 两路并发入库读相同 old →
    各算加权 → 后写覆盖前者 → unit_price 错 + total qty 丢一次（毛利底线 + 食安）
  - issue_stock (P0)：FIFO 出库丢更新 — 两路读相同 current_quantity + 批次明细 →
    ORM 属性赋值后第二 commit 覆盖 → 库存比期望多（食安/成本）
  - adjust_stock (P1)：盘点调整与日常出入库并发可能丢更新
"""

from __future__ import annotations

import os
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.selectable import Select

# ── 路径 ───────────────────────────────────────────────────────────────────────
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SUPPLY_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
for p in [ROOT, SUPPLY_SRC]:
    if p not in sys.path:
        sys.path.insert(0, p)


TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
STORE_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
INGREDIENT_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")


def _select_has_for_update(stmt) -> bool:
    """检测 SQLAlchemy Select 编译后 SQL 是否含 FOR UPDATE.

    用 postgresql 方言 compile 而非检查私有属性 `_for_update_arg`，
    更稳定（属性名在 SQLAlchemy 主版本间可能变化）。PR-A 已验证此模式。
    """
    if not isinstance(stmt, Select):
        return False
    try:
        compiled = str(stmt.compile(dialect=postgresql.dialect()))
        return "FOR UPDATE" in compiled.upper()
    except Exception:
        return getattr(stmt, "_for_update_arg", None) is not None


def _make_ingredient(**kw):
    """构造 Ingredient mock — 模拟 200 桌并发场景下的同一批原料."""
    ing = MagicMock()
    ing.id = kw.get("id", INGREDIENT_ID)
    ing.tenant_id = kw.get("tenant_id", TENANT_ID)
    ing.store_id = kw.get("store_id", STORE_ID)
    ing.ingredient_name = kw.get("ingredient_name", "洋葱")
    ing.current_quantity = kw.get("current_quantity", 100.0)
    ing.min_quantity = kw.get("min_quantity", 10.0)
    ing.max_quantity = kw.get("max_quantity", 200.0)
    ing.unit_price_fen = kw.get("unit_price_fen", 500)  # 5 元/kg
    ing.unit = kw.get("unit", "kg")
    ing.status = kw.get("status", "normal")
    return ing


def _build_db_mock(ingredient_to_return, batch_remaining=None):
    """构造 AsyncSession mock，capture 所有 execute 的 stmt.

    batch_remaining: issue_stock 的批次查询返回值（None 表示无需）
    """
    db = AsyncMock()
    captured = []

    async def mock_execute(stmt, *args, **kwargs):
        captured.append(stmt)
        result = MagicMock()
        # _set_tenant 的 text() 不是 Select，scalar_one_or_none 返回 None 也无害
        result.scalar_one_or_none = MagicMock(return_value=ingredient_to_return)
        # 批次查询走 .all() — 给个空 list 即可，因 issue_stock 实际调用 _get_batch_remaining
        result.all = MagicMock(return_value=[])
        return result

    db.execute = mock_execute
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db, captured


class TestInventoryIORowLockTier1:
    """inventory_io.py 3 路径必须 with_for_update 防并发丢更新.

    与 services/tx-member/src/services/stored_value_service.py 模式对齐
    （11 处 .with_for_update()）— 全仓 row-lock 最严谨服务.
    """

    @pytest.mark.asyncio
    async def test_receive_stock_locks_ingredient_row(self):
        """200 桌并发入库同一批洋葱 — 加权平均单价必须串行计算.

        Race 场景（audit doc §4.3 P0）：
          两路并发 receive_stock 同一 ingredient → 各读相同 old_qty/old_price →
          各算加权平均 → 后 flush 覆盖前 → unit_price 错算 + 总量丢一次.
          直接威胁毛利底线硬约束（CLAUDE.md §17）.
        """
        from services.tx_supply.src.services import inventory_io

        ingredient = _make_ingredient(current_quantity=100.0, unit_price_fen=500)
        db, captured = _build_db_mock(ingredient)

        await inventory_io.receive_stock(
            ingredient_id=str(INGREDIENT_ID),
            quantity=50.0,
            unit_cost_fen=600,
            batch_no="B-20260513-001",
            expiry_date=None,
            store_id=str(STORE_ID),
            tenant_id=str(TENANT_ID),
            db=db,
            performed_by="test",
        )

        locked = [s for s in captured if _select_has_for_update(s)]
        assert locked, (
            "receive_stock 内 SELECT Ingredient 必须 with_for_update — "
            "audit doc §4.3 P0 加权平均并发错算（毛利底线硬约束）"
        )

    @pytest.mark.asyncio
    async def test_issue_stock_locks_ingredient_row(self):
        """200 桌并发出库同一批食材 — FIFO 库存数量必须串行扣减.

        Race 场景（audit doc §4.3 P0）：
          两路并发 issue_stock 同一 ingredient → 各读相同 current_quantity →
          各自 -= deduct → 后 flush 覆盖前 → 库存比期望多（食安/成本）.
        """
        from services.tx_supply.src.services import inventory_io

        ingredient = _make_ingredient(current_quantity=100.0, unit_price_fen=500)
        db, captured = _build_db_mock(ingredient)

        # issue_stock 会调 _get_batch_remaining，需要至少一个批次才能扣
        # 用 monkeypatch 替代 _get_batch_remaining 返回一个批次
        async def fake_batches(*args, **kwargs):
            return [
                {
                    "batch_no": "B-20260513-001",
                    "remaining": 100.0,
                    "unit_cost_fen": 500,
                    "expiry_date": None,
                    "created_at": None,
                }
            ]

        original = inventory_io._get_batch_remaining
        inventory_io._get_batch_remaining = fake_batches
        try:
            await inventory_io.issue_stock(
                ingredient_id=str(INGREDIENT_ID),
                quantity=10.0,
                reason="usage",
                store_id=str(STORE_ID),
                tenant_id=str(TENANT_ID),
                db=db,
                performed_by="test",
            )
        finally:
            inventory_io._get_batch_remaining = original

        locked = [s for s in captured if _select_has_for_update(s)]
        assert locked, (
            "issue_stock 内 SELECT Ingredient 必须 with_for_update — "
            "audit doc §4.3 P0 FIFO 并发丢更新（食安/成本）"
        )

    @pytest.mark.asyncio
    async def test_adjust_stock_locks_ingredient_row(self):
        """店长盘点调整与服务员临时出库并发 — 盘点调整必须锁定 ingredient.

        Race 场景（audit doc §4.3 P1）：
          盘点调整 + 日常出入库并发可能丢更新（食安/成本，P1 比 receive/issue P0 轻）.
          仍加锁以统一所有 mutation 路径（与 PR-A invoice reprint P3 同思路）.
        """
        from services.tx_supply.src.services import inventory_io

        ingredient = _make_ingredient(current_quantity=100.0, unit_price_fen=500)
        db, captured = _build_db_mock(ingredient)

        await inventory_io.adjust_stock(
            ingredient_id=str(INGREDIENT_ID),
            quantity=-5.0,  # 盘亏 5kg
            reason="盘亏",
            store_id=str(STORE_ID),
            tenant_id=str(TENANT_ID),
            db=db,
            performed_by="test",
        )

        locked = [s for s in captured if _select_has_for_update(s)]
        assert locked, (
            "adjust_stock 内 SELECT Ingredient 必须 with_for_update — "
            "audit doc §4.3 P1 盘点调整与日常 IO 并发丢更新"
        )

    @pytest.mark.asyncio
    async def test_get_ingredient_helper_lock_param_default_no_lock(self):
        """_get_ingredient helper 默认 lock=False，保留 read-only 入口能力.

        本测验证 helper 的 lock 参数语义：默认不加锁，调用方显式 lock=True 才加.
        receive/issue/adjust 三个 mutation 路径都必须显式传 lock=True（前 3 个测试已覆盖）.
        """
        from services.tx_supply.src.services import inventory_io

        ingredient = _make_ingredient()
        db, captured = _build_db_mock(ingredient)

        # 默认调用（lock=False）— 模拟 read-only get_stock_balance 入口
        await inventory_io._get_ingredient(
            db, str(INGREDIENT_ID), str(STORE_ID), str(TENANT_ID)
        )
        select_stmts = [s for s in captured if isinstance(s, Select)]
        assert select_stmts, "_get_ingredient 必须 execute 至少一条 select"
        assert not _select_has_for_update(select_stmts[0]), (
            "_get_ingredient 默认 lock=False 时 SELECT 不应含 FOR UPDATE"
        )

        # 显式 lock=True
        captured.clear()
        await inventory_io._get_ingredient(
            db, str(INGREDIENT_ID), str(STORE_ID), str(TENANT_ID), lock=True
        )
        select_stmts = [s for s in captured if isinstance(s, Select)]
        assert select_stmts, "_get_ingredient(lock=True) 必须 execute select"
        assert _select_has_for_update(select_stmts[0]), (
            "_get_ingredient(lock=True) SELECT 必须含 FOR UPDATE"
        )
