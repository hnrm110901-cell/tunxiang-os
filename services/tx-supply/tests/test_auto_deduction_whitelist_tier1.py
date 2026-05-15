"""auto_deduction PRD-08 dept_id 白名单校验集成测试（Tier 1 邻接 / 第 27 例 explicit-ask）

测试 deduct_for_dish / deduct_for_order 的 dept_id 可选参数行为：
  1. dept_id=None → 跳过白名单校验（backward compat，caller (tx-trade) 当前路径）
  2. dept_id 提供 + BOM 行 ingredient 在白名单 → 正常扣料
  3. dept_id 提供 + 任一 BOM 行 ingredient 不在白名单 → raise IngredientNotAllowedError
     （食安总监 demo 场景：早餐档接到含龙虾的订单 → 系统拒绝扣料 + savepoint 回滚）

mock 风格沿用 test_auto_deduction_row_lock_tier1.py — 单元级 mock。
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if sys.version_info < (3, 10):
    pytest.skip(
        "需要 Python 3.10+（生产环境为 3.11）— 本机 3.9 跳过避免 sys.modules 污染",
        allow_module_level=True,
    )


# ─── 测试常量（徐记海鲜场景）────────────────────────────────────────────────

_TENANT_XUJI = "11111111-aaaa-aaaa-aaaa-111111111111"
_STORE = "55555555-0001-0001-0001-555555555555"
_DEPT_BREAKFAST = "22222222-0001-0001-0001-222222222222"
_DEPT_SEAFOOD = "22222222-0002-0002-0002-222222222222"
_DISH_LOBSTER_ROLL = "66666666-0001-0001-0001-666666666666"  # 龙虾卷
_INGREDIENT_LOBSTER = "33333333-0001-0001-0001-333333333333"
_ORDER_ID = "77777777-0001-0001-0001-777777777777"


# ─── 1. deduct_for_dish dept_id 路径 ──────────────────────────────────────────


class TestDeductForDishWhitelistGuard:
    @pytest.mark.asyncio
    async def test_dept_id_none_skips_whitelist_check(self):
        """dept_id=None → 完全跳过白名单 service 调用（caller backward compat）。"""
        from services.tx_supply.src.services import auto_deduction as ad

        # mock _get_bom_for_dish 返回空 → 走早期 missing_bom 路径
        with patch.object(ad, "_get_bom_for_dish", AsyncMock(return_value=[])):
            with patch(
                "services.tx_supply.src.services.dept_whitelist_service.validate_ingredient_allowed",
                AsyncMock(),
            ) as mock_validate:
                db = AsyncMock()
                db.execute = AsyncMock()

                result = await ad.deduct_for_dish(
                    dish_id=_DISH_LOBSTER_ROLL,
                    quantity=1,
                    store_id=_STORE,
                    tenant_id=_TENANT_XUJI,
                    db=db,
                    # dept_id 默认 None
                )
                assert result["missing_bom"] is True
                mock_validate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_dept_id_provided_calls_validate_for_each_bom_line(self):
        """dept_id 提供时，BOM 每行 ingredient 经 validate_ingredient_allowed 校验。"""
        from services.tx_supply.src.services import auto_deduction as ad

        bom_lines = [
            {"ingredient_id": _INGREDIENT_LOBSTER, "quantity": 0.5, "unit": "kg"},
            {"ingredient_id": "99999999-0002-0002-0002-999999999999", "quantity": 0.05, "unit": "kg"},
        ]
        with patch.object(ad, "_get_bom_for_dish", AsyncMock(return_value=bom_lines)):
            with patch(
                "services.tx_supply.src.services.dept_whitelist_service.validate_ingredient_allowed",
                AsyncMock(),
            ) as mock_validate:
                # _get_bom_for_dish mock 之后, BOM 走完校验 → 进入扣料循环
                # ingredient SELECT FOR UPDATE 返回 None (ingredient_not_in_store)
                # 不影响白名单校验断言
                db = AsyncMock()
                db_result = MagicMock()
                db_result.scalar_one_or_none.return_value = None
                db.execute = AsyncMock(return_value=db_result)
                db.flush = AsyncMock()

                await ad.deduct_for_dish(
                    dish_id=_DISH_LOBSTER_ROLL,
                    quantity=2,
                    store_id=_STORE,
                    tenant_id=_TENANT_XUJI,
                    db=db,
                    dept_id=_DEPT_SEAFOOD,
                )
                # 2 BOM lines × 1 call each
                assert mock_validate.await_count == 2
                # 校验首次 call 的关键参数
                first_call_kwargs = mock_validate.await_args_list[0].kwargs
                assert first_call_kwargs["dept_id"] == _DEPT_SEAFOOD
                assert first_call_kwargs["ingredient_id"] == _INGREDIENT_LOBSTER
                # qty = 0.5 (BOM) × 2 (份数) = 1.0
                from decimal import Decimal as _D
                assert first_call_kwargs["qty"] == _D("1.0")
                assert first_call_kwargs["raise_on_violation"] is True

    @pytest.mark.asyncio
    async def test_dept_id_breakfast_lobster_raises(self):
        """早餐档收到含龙虾的菜 → validate 抛 IngredientNotAllowedError → 扣料被阻断。"""
        from services.tx_supply.src.services import auto_deduction as ad
        from services.tx_supply.src.models.dept_whitelist_models import (
            IngredientNotAllowedError,
        )

        bom_lines = [
            {"ingredient_id": _INGREDIENT_LOBSTER, "quantity": 0.5, "unit": "kg"},
        ]
        with patch.object(ad, "_get_bom_for_dish", AsyncMock(return_value=bom_lines)):
            with patch(
                "services.tx_supply.src.services.dept_whitelist_service.validate_ingredient_allowed",
                AsyncMock(
                    side_effect=IngredientNotAllowedError(
                        dept_id=_DEPT_BREAKFAST,
                        ingredient_id=_INGREDIENT_LOBSTER,
                        ingredient_name="波士顿龙虾",
                    )
                ),
            ):
                db = AsyncMock()
                db.execute = AsyncMock()

                with pytest.raises(IngredientNotAllowedError) as exc_info:
                    await ad.deduct_for_dish(
                        dish_id=_DISH_LOBSTER_ROLL,
                        quantity=1,
                        store_id=_STORE,
                        tenant_id=_TENANT_XUJI,
                        db=db,
                        dept_id=_DEPT_BREAKFAST,
                    )
                assert exc_info.value.dept_id == _DEPT_BREAKFAST
                assert exc_info.value.ingredient_id == _INGREDIENT_LOBSTER


# ─── 2. deduct_for_order dept_id 透传路径 ────────────────────────────────────


class TestDeductForOrderWhitelistPassthrough:
    """deduct_for_order dept_id 透传到 deduct_for_dish.

    测试同时 patch _get_bom_for_dish (避免 BOM SELECT 通过 MagicMock 走完 .scalars().all()
    chain 导致 coroutine.attribute 异常) + deduct_for_dish (拦截真实 BOM 锁路径).
    """

    @pytest.mark.asyncio
    async def test_dept_id_passed_to_deduct_for_dish(self):
        """deduct_for_order dept_id 必须透传到每次 deduct_for_dish 调用。"""
        from services.tx_supply.src.services import auto_deduction as ad

        order_items = [
            {"dish_id": _DISH_LOBSTER_ROLL, "quantity": 1, "item_name": "龙虾卷"},
        ]

        with patch.object(ad, "_get_bom_for_dish", AsyncMock(return_value=[])), patch.object(
            ad,
            "deduct_for_dish",
            AsyncMock(
                return_value={
                    "deducted": [],
                    "missing_bom": False,
                    "insufficient_stock": [],
                }
            ),
        ) as mock_deduct:
            # mock db / begin_nested 走通
            db = AsyncMock()
            db.execute = AsyncMock()
            db.flush = AsyncMock()
            # begin_nested 是 async context manager
            db.begin_nested = MagicMock()
            db.begin_nested.return_value.__aenter__ = AsyncMock(return_value=None)
            db.begin_nested.return_value.__aexit__ = AsyncMock(return_value=None)

            await ad.deduct_for_order(
                order_id=_ORDER_ID,
                order_items=order_items,
                store_id=_STORE,
                tenant_id=_TENANT_XUJI,
                db=db,
                dept_id=_DEPT_SEAFOOD,
            )

            mock_deduct.assert_awaited()
            call_kwargs = mock_deduct.await_args.kwargs
            assert call_kwargs["dept_id"] == _DEPT_SEAFOOD

    @pytest.mark.asyncio
    async def test_dept_id_none_passes_through_as_none(self):
        """dept_id=None (default) 透传 None 到 deduct_for_dish — backward compat。"""
        from services.tx_supply.src.services import auto_deduction as ad

        order_items = [
            {"dish_id": _DISH_LOBSTER_ROLL, "quantity": 1, "item_name": "龙虾卷"},
        ]

        with patch.object(ad, "_get_bom_for_dish", AsyncMock(return_value=[])), patch.object(
            ad,
            "deduct_for_dish",
            AsyncMock(
                return_value={
                    "deducted": [],
                    "missing_bom": False,
                    "insufficient_stock": [],
                }
            ),
        ) as mock_deduct:
            db = AsyncMock()
            db.execute = AsyncMock()
            db.flush = AsyncMock()
            db.begin_nested = MagicMock()
            db.begin_nested.return_value.__aenter__ = AsyncMock(return_value=None)
            db.begin_nested.return_value.__aexit__ = AsyncMock(return_value=None)

            await ad.deduct_for_order(
                order_id=_ORDER_ID,
                order_items=order_items,
                store_id=_STORE,
                tenant_id=_TENANT_XUJI,
                db=db,
                # dept_id 不传 — default None
            )

            mock_deduct.assert_awaited()
            call_kwargs = mock_deduct.await_args.kwargs
            assert call_kwargs["dept_id"] is None
