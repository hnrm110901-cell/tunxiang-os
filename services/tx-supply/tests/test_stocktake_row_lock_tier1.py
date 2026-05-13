"""Tier 1 行锁测试：stocktake_service.finalize_stocktake 必须 with_for_update + 按 ingredient_id 升序锁

关联：
  - docs/security/tier1-row-lock-audit-2026-05.md §4.3 (tx-supply stocktake P0 verifier 转 P0)
  - PR #538 (audit doc), Issue #532, PR-B of 6-PR fix roadmap

业务影响（audit doc §4.3 P0）：
  - finalize_stocktake (库存调整): 两路并发 finalize 同一 stocktake，或与并发
    issue_stock/receive_stock 撞 → ingredient 数量错乱（食安/成本）.
  - 验收场景：店长盘点结账与服务员临时叫菜并发，盘点必须锁定 ingredient.

死锁防御：
  - 一次盘点可调整多个 ingredient → 按 ingredient_id 升序锁防 ABBA.
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
STOCKTAKE_ID = uuid.UUID("00000000-0000-0000-0000-000000000099")

# 模拟一次盘点涉及 3 个 ingredient — 故意倒序提供
ING_A = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
ING_B = uuid.UUID("00000000-0000-0000-0000-0000000000bb")
ING_C = uuid.UUID("00000000-0000-0000-0000-0000000000cc")


def _select_has_for_update(stmt) -> bool:
    if not isinstance(stmt, Select):
        return False
    try:
        compiled = str(stmt.compile(dialect=postgresql.dialect()))
        return "FOR UPDATE" in compiled.upper()
    except Exception:
        return getattr(stmt, "_for_update_arg", None) is not None


def _extract_ingredient_id_from_select(stmt) -> uuid.UUID | None:
    if not isinstance(stmt, Select):
        return None
    try:
        compiled = stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
        sql = str(compiled).upper()
        for ing_id in (ING_A, ING_B, ING_C):
            if str(ing_id).upper() in sql:
                return ing_id
    except Exception:
        try:
            params = stmt.compile().params
            for v in params.values():
                if isinstance(v, uuid.UUID) and v in (ING_A, ING_B, ING_C):
                    return v
        except Exception:
            pass
    return None


def _make_ingredient(ing_id: uuid.UUID, **kw):
    ing = MagicMock()
    ing.id = ing_id
    ing.tenant_id = kw.get("tenant_id", TENANT_ID)
    ing.store_id = kw.get("store_id", STORE_ID)
    ing.ingredient_name = kw.get("ingredient_name", f"原料-{str(ing_id)[-4:]}")
    ing.current_quantity = kw.get("current_quantity", 50.0)
    ing.min_quantity = kw.get("min_quantity", 5.0)
    ing.unit_price_fen = kw.get("unit_price_fen", 200)
    ing.unit = kw.get("unit", "kg")
    ing.status = kw.get("status", "normal")
    return ing


class TestStocktakeRowLockTier1:
    """finalize_stocktake 必须 with_for_update + 按 ingredient_id 升序锁."""

    @pytest.mark.asyncio
    async def test_finalize_stocktake_locks_ingredient_in_id_ascending_order(self):
        """店长盘点结账与服务员临时出库并发 — 必须锁 ingredient + 按 id 升序防死锁.

        Race 场景（audit doc §4.3 P0）：
          - 两路并发 finalize 同一 stocktake → 各读相同 ingredient.current_quantity →
            各自 SET = actual_qty → 后写覆盖前（虽然 actual_qty 相同，但 status 计算
            + IngredientTransaction 双写）.
          - finalize 与 issue_stock/receive_stock 撞 → 实盘数被中途出入库覆盖.
          - 多 ingredient 并发 finalize → 必须按 ingredient_id 升序锁防 ABBA.
        """
        from services.tx_supply.src.services import stocktake_service

        # 强制 DB 模式以走 raw SQL + SELECT Ingredient 路径
        stocktake_service._db_mode = True

        # 倒序提供 items（C → A → B），期望服务层锁顺序为 A → B → C
        items_rows = [
            {
                "ingredient_id": ING_C,
                "ingredient_name": "酱油",
                "unit": "L",
                "expected_qty": 10.0,
                "actual_qty": 8.0,  # 盘亏，触发调整路径
                "cost_price": 5.0,
            },
            {
                "ingredient_id": ING_A,
                "ingredient_name": "葱姜蒜",
                "unit": "kg",
                "expected_qty": 5.0,
                "actual_qty": 4.5,
                "cost_price": 3.0,
            },
            {
                "ingredient_id": ING_B,
                "ingredient_name": "鱼",
                "unit": "kg",
                "expected_qty": 20.0,
                "actual_qty": 18.0,
                "cost_price": 50.0,
            },
        ]
        ingredients_by_id = {
            ING_A: _make_ingredient(ING_A),
            ING_B: _make_ingredient(ING_B),
            ING_C: _make_ingredient(ING_C),
        }

        captured = []
        db = AsyncMock()

        # finalize_stocktake 调用顺序：
        # 1. SELECT stocktakes header (raw text)
        # 2. SELECT stocktake_items (raw text) → 我们 mock 它走 items_rows
        # 3. For each item with variance: SELECT Ingredient (ORM Select) — 这是要加锁的
        # 4. UPDATE stocktakes SET status='completed' (raw text)
        call_count = {"n": 0}

        async def mock_execute(stmt, *args, **kwargs):
            captured.append(stmt)
            call_count["n"] += 1
            result = MagicMock()

            # raw text 调用：返回 mock 数据
            if not isinstance(stmt, Select):
                if call_count["n"] == 1:
                    # _set_tenant SELECT set_config — 走默认
                    result.mappings = MagicMock()
                    result.mappings.return_value.one_or_none = MagicMock(return_value=None)
                    result.mappings.return_value.all = MagicMock(return_value=[])
                    return result
                if call_count["n"] == 2:
                    # SELECT stocktakes header
                    header = MagicMock()
                    header.__getitem__ = lambda self, k: {
                        "id": STOCKTAKE_ID,
                        "store_id": STORE_ID,
                        "status": "in_progress",
                    }[k]
                    mappings_proxy = MagicMock()
                    mappings_proxy.one_or_none = MagicMock(return_value=header)
                    mappings_proxy.all = MagicMock(return_value=[])
                    result.mappings = MagicMock(return_value=mappings_proxy)
                    return result
                if call_count["n"] == 3:
                    # SELECT stocktake_items
                    mappings_proxy = MagicMock()
                    mappings_proxy.one_or_none = MagicMock(return_value=None)
                    mappings_proxy.all = MagicMock(return_value=items_rows)
                    result.mappings = MagicMock(return_value=mappings_proxy)
                    return result
                # UPDATE 等其他 raw text
                result.mappings = MagicMock()
                result.mappings.return_value.one_or_none = MagicMock(return_value=None)
                result.mappings.return_value.all = MagicMock(return_value=[])
                return result

            # ORM Select Ingredient — 返回对应 mock
            ing_id = _extract_ingredient_id_from_select(stmt)
            ingredient = ingredients_by_id.get(ing_id) if ing_id else None
            result.scalar_one_or_none = MagicMock(return_value=ingredient)
            return result

        db.execute = mock_execute
        db.flush = AsyncMock()
        db.add = MagicMock()

        # AsyncMock.begin_nested 返回的需要是 async context manager
        nested_cm = AsyncMock()
        nested_cm.__aenter__ = AsyncMock(return_value=None)
        nested_cm.__aexit__ = AsyncMock(return_value=None)
        db.begin_nested = MagicMock(return_value=nested_cm)

        try:
            await stocktake_service.finalize_stocktake(
                stocktake_id=str(STOCKTAKE_ID),
                tenant_id=str(TENANT_ID),
                db=db,
            )
        finally:
            stocktake_service._db_mode = None  # 重置 cache 不影响其他测试

        # 必须至少 1 个 FOR UPDATE SELECT
        locked = [s for s in captured if _select_has_for_update(s)]
        assert locked, (
            "finalize_stocktake 调整库存的 SELECT Ingredient 必须 with_for_update — "
            "audit doc §4.3 P0 盘点终结 race（食安/成本）"
        )

        # 锁顺序必须按 ingredient_id 升序：A → B → C
        lock_order = []
        for s in captured:
            if _select_has_for_update(s):
                ing_id = _extract_ingredient_id_from_select(s)
                if ing_id:
                    lock_order.append(ing_id)
        assert lock_order == [ING_A, ING_B, ING_C], (
            f"盘点 items 锁顺序必须按 ingredient_id 升序防 ABBA 死锁，实际 = {lock_order}, "
            f"期望 = [ING_A, ING_B, ING_C]"
        )
