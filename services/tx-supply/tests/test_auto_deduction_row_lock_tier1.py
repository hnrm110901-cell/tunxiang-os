"""Tier 1 行锁测试：auto_deduction.deduct_for_dish 必须 with_for_update + BOM 行排序防死锁

关联：
  - docs/security/tier1-row-lock-audit-2026-05.md §4.3 (tx-supply auto_deduction P0)
  - PR #538 (audit doc), Issue #532, PR-B of 6-PR fix roadmap
  - 修复参考范本：services/tx-member/src/services/stored_value_service.py transfer
    (2 卡同锁排序防死锁)

业务影响（audit doc §4.3 P0）：
  - deduct_for_dish: 订单完成 BOM 扣料 race — 两单同时完成同菜品 → 读相同 old_qty →
    计算 new_qty → flush 后写覆盖 → BOM 扣料两份但库存只下降一份 → 负库存累积.
  - 直接威胁毛利底线计算 + 食安合规硬约束（CLAUDE.md §17 Tier 1 三条硬约束）.
  - deduct_for_order 由订单完成事件触发，是 Tier 1 资金路径下游必经之路.

死锁防御：
  - 一道菜的 BOM 可包含多个 ingredient（如红烧鱼 = 鱼 + 葱姜蒜 + 酱油 + 糖）.
  - 两单同时完成不同菜品但 BOM 共享 ingredient → 必须按 ingredient_id 升序加锁 → 防 ABBA.
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
DISH_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")

# 模拟红烧鱼 BOM：鱼 (id_b) + 葱姜蒜 (id_a) + 酱油 (id_c)
# 故意倒序提供（先 b 再 a 再 c）以验证服务层会按 id 升序锁
ING_A = uuid.UUID("00000000-0000-0000-0000-0000000000aa")  # 葱姜蒜
ING_B = uuid.UUID("00000000-0000-0000-0000-0000000000bb")  # 鱼
ING_C = uuid.UUID("00000000-0000-0000-0000-0000000000cc")  # 酱油


def _select_has_for_update(stmt) -> bool:
    if not isinstance(stmt, Select):
        return False
    try:
        compiled = str(stmt.compile(dialect=postgresql.dialect()))
        return "FOR UPDATE" in compiled.upper()
    except Exception:
        return getattr(stmt, "_for_update_arg", None) is not None


def _extract_ingredient_id_from_select(stmt) -> uuid.UUID | None:
    """从 SELECT Ingredient WHERE id == X 的 stmt 中提取出 X — 验证锁顺序."""
    if not isinstance(stmt, Select):
        return None
    try:
        compiled = stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
        sql = str(compiled).upper()
        # 找 Ingredient.id = '...' 的 UUID
        for ing_id in (ING_A, ING_B, ING_C):
            if str(ing_id).upper() in sql:
                return ing_id
    except Exception:
        # Fallback：从 binds 找
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


class TestAutoDeductionRowLockTier1:
    """auto_deduction.deduct_for_dish 必须 with_for_update + 按 ingredient_id 升序锁防死锁."""

    @pytest.mark.asyncio
    async def test_deduct_for_dish_locks_ingredient_row(self):
        """同时下单 5 份红烧鱼 — BOM 扣料必须锁定每个 ingredient 防丢更新.

        Race 场景（audit doc §4.3 P0）：
          两单同时完成同菜品 → 读相同 old_qty → flush 后写覆盖 →
          BOM 扣料两份但库存只下降一份 → 负库存累积（食安/毛利底线）.
        """
        from services.tx_supply.src.services import auto_deduction

        captured = []
        ingredients_by_id = {
            ING_A: _make_ingredient(ING_A, current_quantity=10.0),
        }

        async def fake_bom(*args, **kwargs):
            return [{"ingredient_id": str(ING_A), "quantity": 0.5, "unit": "kg"}]

        db = AsyncMock()

        async def mock_execute(stmt, *args, **kwargs):
            captured.append(stmt)
            result = MagicMock()
            ing_id = _extract_ingredient_id_from_select(stmt)
            ingredient = ingredients_by_id.get(ing_id) if ing_id else None
            result.scalar_one_or_none = MagicMock(return_value=ingredient)
            return result

        db.execute = mock_execute
        db.flush = AsyncMock()
        db.add = MagicMock()

        original_bom = auto_deduction._get_bom_for_dish
        auto_deduction._get_bom_for_dish = fake_bom
        try:
            await auto_deduction.deduct_for_dish(
                dish_id=str(DISH_ID),
                quantity=5,
                store_id=str(STORE_ID),
                tenant_id=str(TENANT_ID),
                db=db,
            )
        finally:
            auto_deduction._get_bom_for_dish = original_bom

        locked = [s for s in captured if _select_has_for_update(s)]
        assert locked, (
            "deduct_for_dish 内 SELECT Ingredient 必须 with_for_update — "
            "audit doc §4.3 P0 BOM 扣料并发丢更新（毛利底线 + 食安硬约束）"
        )

    @pytest.mark.asyncio
    async def test_deduct_for_dish_locks_in_id_ascending_order(self):
        """多 BOM 行（如红烧鱼 = 鱼 + 葱姜蒜 + 酱油）必须按 ingredient_id 升序锁 — 防 ABBA 死锁.

        Race 场景：两单 BOM 共享 ingredient，若锁顺序不同 → ABBA 死锁.
        修复模式参考：services/tx-member/src/services/stored_value_service.py
        transfer 函数 2 卡同锁 sorted([from_card_id, to_card_id]).
        """
        from services.tx_supply.src.services import auto_deduction

        # BOM 故意倒序提供：b → a → c，期望服务层锁顺序为 a → b → c
        async def fake_bom(*args, **kwargs):
            return [
                {"ingredient_id": str(ING_B), "quantity": 0.3, "unit": "kg"},
                {"ingredient_id": str(ING_A), "quantity": 0.1, "unit": "kg"},
                {"ingredient_id": str(ING_C), "quantity": 0.05, "unit": "L"},
            ]

        ingredients_by_id = {
            ING_A: _make_ingredient(ING_A),
            ING_B: _make_ingredient(ING_B),
            ING_C: _make_ingredient(ING_C),
        }

        captured = []
        db = AsyncMock()

        async def mock_execute(stmt, *args, **kwargs):
            captured.append(stmt)
            result = MagicMock()
            ing_id = _extract_ingredient_id_from_select(stmt)
            ingredient = ingredients_by_id.get(ing_id) if ing_id else None
            result.scalar_one_or_none = MagicMock(return_value=ingredient)
            return result

        db.execute = mock_execute
        db.flush = AsyncMock()
        db.add = MagicMock()

        original_bom = auto_deduction._get_bom_for_dish
        auto_deduction._get_bom_for_dish = fake_bom
        try:
            await auto_deduction.deduct_for_dish(
                dish_id=str(DISH_ID),
                quantity=1,
                store_id=str(STORE_ID),
                tenant_id=str(TENANT_ID),
                db=db,
            )
        finally:
            auto_deduction._get_bom_for_dish = original_bom

        # 提取 FOR UPDATE 的 SELECT 的 ingredient_id 顺序
        lock_order = []
        for s in captured:
            if _select_has_for_update(s):
                ing_id = _extract_ingredient_id_from_select(s)
                if ing_id:
                    lock_order.append(ing_id)

        assert lock_order == [ING_A, ING_B, ING_C], (
            f"BOM 行锁顺序必须按 ingredient_id 升序防 ABBA 死锁，实际 = {lock_order}, "
            f"期望 = [ING_A, ING_B, ING_C] — 范本 stored_value_service.py transfer 函数"
        )
