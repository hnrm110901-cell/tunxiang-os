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

# 本机 Python 3.9 跳过 — shared.ontology / shared.events 用 PEP 604 `X | None` + dataclass slots=True
# 需 3.10+. CI Python 3.11 真跑. 与 PR-D/E/F (test_cashier_engine_row_lock_tier1.py 等) 同模式
# 避开 PR #547 round-1 stub 污染陷阱 (feedback_pytest_stub_setdefault_pitfall.md).
if sys.version_info < (3, 10):
    pytest.skip(
        "需 Python 3.10+ (shared.ontology PEP 604 union + shared.events dataclass slots=True)；CI Python 3.11 跑通",
        allow_module_level=True,
    )

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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Issue #549: deduct_for_order 跨 dish ABBA 防护
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DISH_1 = uuid.UUID("00000000-0000-0000-0000-000000000111")  # 红烧鱼: [ING_B, ING_A]
DISH_2 = uuid.UUID("00000000-0000-0000-0000-000000000222")  # 麻婆豆腐: [ING_C, ING_A]


class TestDeductForOrderCrossDishABBATier1:
    """auto_deduction.deduct_for_order 跨 dish 必须预聚合 + 升序锁防 ABBA 死锁 (Issue #549).

    反例 (PR-B §19 reviewer P1#1):
      - 订单 A = [dish1 (ing_X, ing_Y), dish2 (ing_Z)]
      - 订单 B = [dish2 (ing_Z), dish1 (ing_X, ing_Y)]
      - A 锁序: X → Y → Z (dish1 内部 sorted X→Y, 然后 dish2 锁 Z)
      - B 锁序: Z → X → Y (dish2 优先锁 Z, 然后 dish1 锁 X→Y)
      - A 持 X+Y 等 Z; B 持 Z 等 X → 经典 ABBA 死锁

    防御 (方案 B, architect 评估推荐):
      deduct_for_order 在 begin_nested() 入口处:
      1. 遍历所有 order_items 调 _get_bom_for_dish 聚合 BOM (不锁)
      2. 跨 dish 收集 ingredient_id 去重 + sorted(key=str) 升序锁定 (SELECT FOR UPDATE)
      3. 然后保持现有 for-item 循环 (deduct_for_dish 内部 sorted 是 reentrant 同事务无害)

    范本: services/tx-member/src/services/stored_value_service.py transfer 2 卡 sorted([from, to])
    """

    @pytest.mark.asyncio
    async def test_deduct_for_order_pre_locks_all_ingredients_in_id_ascending_order(self):
        """订单跨 dish 必须按 ingredient_id 升序预锁所有 ingredient (跨 dish 全局锁顺序一致防 ABBA).

        反例: 订单 A=[dish1(B,A), dish2(C,A)] 现实 deduct_for_dish 内部锁序 A→B (dish1) 再 A→C (dish2,
        A 已 reentrant). 但若另一并发订单 B=[dish2(C,A), dish1(B,A)] 锁 A→C 再 A→B → A 已锁但 C 等
        ↔ A 已锁但 B 等 → ABBA 死锁 (跨 dish 锁序由 dish 出现顺序决定, 非全局一致).

        修复后: deduct_for_order 入口处预锁 sorted(去重)=[A,B,C], 锁完后再做 deduct_for_dish 业务循环.
        无论订单 dish 顺序如何, 全局锁顺序恒为 [A,B,C].
        """
        from services.tx_supply.src.services import auto_deduction

        # 订单 = [dish1 BOM=[B, A]倒序, dish2 BOM=[C, A]倒序] — 故意倒序看预锁是否生效
        boms = {
            DISH_1: [
                {"ingredient_id": str(ING_B), "quantity": 0.3, "unit": "kg"},
                {"ingredient_id": str(ING_A), "quantity": 0.1, "unit": "kg"},
            ],
            DISH_2: [
                {"ingredient_id": str(ING_C), "quantity": 0.05, "unit": "L"},
                {"ingredient_id": str(ING_A), "quantity": 0.05, "unit": "kg"},
            ],
        }

        async def fake_bom(db_arg, dish_uuid, tenant_uuid_arg):
            return boms.get(dish_uuid, [])

        ingredients_by_id = {
            ING_A: _make_ingredient(ING_A, current_quantity=100.0),
            ING_B: _make_ingredient(ING_B, current_quantity=50.0),
            ING_C: _make_ingredient(ING_C, current_quantity=20.0),
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
        # begin_nested 是 async context manager 必须 mock
        db.begin_nested = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=None), __aexit__=AsyncMock(return_value=None)))

        original_bom = auto_deduction._get_bom_for_dish
        auto_deduction._get_bom_for_dish = fake_bom
        try:
            await auto_deduction.deduct_for_order(
                order_id=str(uuid.uuid4()),
                order_items=[
                    {"dish_id": str(DISH_1), "quantity": 1, "item_name": "红烧鱼"},
                    {"dish_id": str(DISH_2), "quantity": 1, "item_name": "麻婆豆腐"},
                ],
                store_id=str(STORE_ID),
                tenant_id=str(TENANT_ID),
                db=db,
            )
        finally:
            auto_deduction._get_bom_for_dish = original_bom

        # 提取所有 FOR UPDATE 的 SELECT 的 ingredient_id 顺序
        lock_order = []
        for s in captured:
            if _select_has_for_update(s):
                ing_id = _extract_ingredient_id_from_select(s)
                if ing_id:
                    lock_order.append(ing_id)

        # 关键断言: 前 3 把锁必须按 [A, B, C] 升序 — deduct_for_order 入口的预锁阶段
        # (后续 deduct_for_dish 内部循环对已锁行的 reentrant SELECT FOR UPDATE 是 no-op 但也会被 mock 记录)
        assert len(lock_order) >= 3, (
            f"deduct_for_order 必须 pre-lock 至少 3 个去重 ingredient (A,B,C), 实际 = {lock_order}"
        )
        assert lock_order[:3] == [ING_A, ING_B, ING_C], (
            f"预锁顺序必须按 ingredient_id 升序防跨 dish ABBA, 实际前 3 = {lock_order[:3]}, "
            f"期望 = [ING_A, ING_B, ING_C] (sorted by str(uuid)) — Issue #549 architect 推荐方案 B"
        )

    @pytest.mark.asyncio
    async def test_deduct_for_order_shared_ingredient_dedup_locked_once_in_prelock(self):
        """跨 dish 共享同 ingredient 必须在预锁阶段去重 — 只 SELECT FOR UPDATE 一次防重复 round trip.

        场景: 订单 = [dish1(B, A), dish2(C, A)] — A 被 dish1 + dish2 共享.
        预锁阶段唯一锁 [A, B, C] (3 次), 而非按 dish 平铺 [B, A, C, A] (4 次).
        最终扣减必须正确: A 累计 = 0.1+0.05=0.15, B = 0.3, C = 0.05 (跨 dish 累加).
        """
        from services.tx_supply.src.services import auto_deduction

        boms = {
            DISH_1: [
                {"ingredient_id": str(ING_B), "quantity": 0.3, "unit": "kg"},
                {"ingredient_id": str(ING_A), "quantity": 0.1, "unit": "kg"},
            ],
            DISH_2: [
                {"ingredient_id": str(ING_C), "quantity": 0.05, "unit": "L"},
                {"ingredient_id": str(ING_A), "quantity": 0.05, "unit": "kg"},  # 与 dish1 共享 A
            ],
        }

        async def fake_bom(db_arg, dish_uuid, tenant_uuid_arg):
            return boms.get(dish_uuid, [])

        ingredients_by_id = {
            ING_A: _make_ingredient(ING_A, current_quantity=100.0),
            ING_B: _make_ingredient(ING_B, current_quantity=50.0),
            ING_C: _make_ingredient(ING_C, current_quantity=20.0),
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
        db.begin_nested = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=None), __aexit__=AsyncMock(return_value=None)))

        original_bom = auto_deduction._get_bom_for_dish
        auto_deduction._get_bom_for_dish = fake_bom
        try:
            result = await auto_deduction.deduct_for_order(
                order_id=str(uuid.uuid4()),
                order_items=[
                    {"dish_id": str(DISH_1), "quantity": 1, "item_name": "红烧鱼"},
                    {"dish_id": str(DISH_2), "quantity": 1, "item_name": "麻婆豆腐"},
                ],
                store_id=str(STORE_ID),
                tenant_id=str(TENANT_ID),
                db=db,
            )
        finally:
            auto_deduction._get_bom_for_dish = original_bom

        # 预锁阶段共发出 3 次 FOR UPDATE (A,B,C 去重), 后续 deduct_for_dish 内部 reentrant SELECT
        # 也会被 mock 记录, 总数 = 3 + 4 (dish1 BOM 2 行 + dish2 BOM 2 行) = 7
        # 关键: 预锁阶段去重必须 = 3 而非 4 (A 不能被预锁 2 次)
        # 简化断言: 前 3 把锁必须是 sorted 去重 [A, B, C]
        lock_order = []
        for s in captured:
            if _select_has_for_update(s):
                ing_id = _extract_ingredient_id_from_select(s)
                if ing_id:
                    lock_order.append(ing_id)

        assert lock_order[:3] == [ING_A, ING_B, ING_C], (
            f"预锁阶段必须按 sorted 去重锁 [A,B,C], 实际前 3 = {lock_order[:3]}. "
            f"共享 ingredient (A) 不能被预锁 2 次 — N+1 性能 + 锁顺序一致性双重要求"
        )

        # A 跨 dish 累加扣减: dish1=0.1 + dish2=0.05 = 0.15
        # ingredient_by_id[A] current_quantity 应从 100.0 → 99.85
        assert abs(ingredients_by_id[ING_A].current_quantity - 99.85) < 0.001, (
            f"跨 dish 共享 ingredient 必须累加扣减: A 期望 100.0 - 0.15 = 99.85, "
            f"实际 = {ingredients_by_id[ING_A].current_quantity}"
        )

    @pytest.mark.asyncio
    async def test_deduct_for_dish_internal_sort_still_works_when_called_directly(self):
        """defense in depth: deduct_for_dish 单 dish 直接调用 (非 deduct_for_order 路径) 内部 sorted 仍生效.

        场景: BOM = [B(倒序), A, C], 直接调 deduct_for_dish — 必须仍按 [A, B, C] 锁.
        意义: 若未来有人在非 deduct_for_order 路径调 deduct_for_dish, 内部 L131 sorted 是
        BOM 内多 ingredient 防 ABBA 的最后防线. PR #549 修 deduct_for_order 后, 不能让
        deduct_for_dish 防御回归.
        """
        from services.tx_supply.src.services import auto_deduction

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
            # 直接调 deduct_for_dish — 不走 deduct_for_order, 内部 sorted 必须仍生效
            await auto_deduction.deduct_for_dish(
                dish_id=str(DISH_ID),
                quantity=1,
                store_id=str(STORE_ID),
                tenant_id=str(TENANT_ID),
                db=db,
            )
        finally:
            auto_deduction._get_bom_for_dish = original_bom

        lock_order = []
        for s in captured:
            if _select_has_for_update(s):
                ing_id = _extract_ingredient_id_from_select(s)
                if ing_id:
                    lock_order.append(ing_id)

        # defense in depth: 单 dish 直接路径必须仍按 sorted [A, B, C] 锁
        assert lock_order == [ING_A, ING_B, ING_C], (
            f"deduct_for_dish 直接调用 (非 deduct_for_order) 内部 sorted 必须仍生效防 ABBA. "
            f"实际锁序 = {lock_order}, 期望 = [A, B, C]. PR #549 修 deduct_for_order 不能让"
            f"deduct_for_dish 防御回归 (defense in depth)"
        )
