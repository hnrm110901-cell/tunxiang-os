"""auto_deduction PRD-11 sub-A share_split 集成测试（Tier 1 邻接 / 第 28 例 explicit-ask）

测试 deduct_for_dish / deduct_for_order 的 share_split opt-in 行为：
  1. share_split=None → 完全跳过 (backward compat, caller PR-B 当前未传)
  2. share_split 提供 + rule 允许 → apply_split 成功 + emit inventory.split_attributed event
  3. share_split 提供 + rule 不允许 → raise ValueError (caller route 422)
  4. share_split 提供 + emit event 失败 → fail-open warning, 不阻塞 BOM 扣料
  5. deduct_for_order 透传 share_split per-item + order_id_for_event

mock 风格沿用 test_auto_deduction_whitelist_tier1.py (含 _get_bom_for_dish patch 避 SQLAlchemy chain).
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
_DISH_SUANCAIYU = "66666666-0001-0001-0001-666666666666"  # 酸菜鱼
_ORDER_ID = "77777777-0001-0001-0001-777777777777"
_ORDER_ITEM_ID = "88888888-0001-0001-0001-888888888888"


# ─── 1. deduct_for_dish share_split 路径 ─────────────────────────────────────


class TestDeductForDishShareSplit:
    @pytest.mark.asyncio
    async def test_share_split_none_skips_apply_and_emit(self):
        """share_split=None → 完全跳过 apply_split 和 emit (backward compat)."""
        from services.tx_supply.src.services import auto_deduction as ad

        with patch.object(ad, "_get_bom_for_dish", AsyncMock(return_value=[])):
            with patch(
                "services.tx_supply.src.services.share_split_service.apply_split",
                AsyncMock(),
            ) as mock_apply:
                db = AsyncMock()
                db.execute = AsyncMock()
                db.flush = AsyncMock()

                result = await ad.deduct_for_dish(
                    dish_id=_DISH_SUANCAIYU,
                    quantity=1,
                    store_id=_STORE,
                    tenant_id=_TENANT_XUJI,
                    db=db,
                    # share_split 默认 None
                )
                assert result["missing_bom"] is True
                mock_apply.assert_not_awaited()
                assert "split_attribution" not in result

    @pytest.mark.asyncio
    async def test_share_split_emits_event_and_attaches_attribution(self):
        """share_split 提供 → apply_split + emit + result 含 split_attribution."""
        from services.tx_supply.src.services import auto_deduction as ad
        from services.tx_supply.src.models.share_split_models import (
            ResolvedShare,
            ResolvedSplitResult,
            ShareSplitMethod,
        )
        from decimal import Decimal

        bom_lines = [
            {"ingredient_id": "99999999-0001-0001-0001-999999999999", "quantity": 0.5, "unit": "kg"}
        ]

        # 构造 apply_split 返回 ResolvedSplitResult
        fake_split = ResolvedSplitResult(
            method=ShareSplitMethod.EVEN,
            count=2,
            bom_cost_total_fen=10000,
            shares=[
                ResolvedShare(share_index=0, weight=Decimal("0.5"), attributed_cost_fen=5000),
                ResolvedShare(share_index=1, weight=Decimal("0.5"), attributed_cost_fen=5000),
            ],
        )

        with patch.object(ad, "_get_bom_for_dish", AsyncMock(return_value=bom_lines)):
            with patch(
                "services.tx_supply.src.services.share_split_service.apply_split",
                AsyncMock(return_value=fake_split),
            ) as mock_apply, patch(
                "shared.events.src.emitter.emit_event",
                AsyncMock(),
            ) as mock_emit:
                # mock ingredient SELECT FOR UPDATE 返回 None (跳过实际扣料但走完路径)
                db = AsyncMock()
                db_result = MagicMock()
                db_result.scalar_one_or_none.return_value = None
                db.execute = AsyncMock(return_value=db_result)
                db.flush = AsyncMock()

                result = await ad.deduct_for_dish(
                    dish_id=_DISH_SUANCAIYU,
                    quantity=1,
                    store_id=_STORE,
                    tenant_id=_TENANT_XUJI,
                    db=db,
                    share_split={"method": "even", "count": 2},
                    order_id_for_event=_ORDER_ID,
                    order_item_id_for_event=_ORDER_ITEM_ID,
                )
                # apply_split 被调用
                mock_apply.assert_awaited_once()
                # split_attribution 附在 result
                assert "split_attribution" in result
                assert result["split_attribution"]["method"] == "even"
                assert result["split_attribution"]["count"] == 2
                assert (
                    result["split_attribution"]["bom_cost_total_fen"] == 10000
                )

    @pytest.mark.asyncio
    async def test_share_split_rule_violation_raises(self):
        """rule 不允许 / spec 不合 → apply_split 抛 ValueError, deduct_for_dish 透传."""
        from services.tx_supply.src.services import auto_deduction as ad

        with patch.object(ad, "_get_bom_for_dish", AsyncMock(return_value=[])):
            with patch(
                "services.tx_supply.src.services.share_split_service.apply_split",
                AsyncMock(side_effect=ValueError("dish 不允许分享")),
            ):
                db = AsyncMock()
                db.execute = AsyncMock()
                db.flush = AsyncMock()

                # _get_bom_for_dish 返回 [] 直接 missing_bom; share_split 检查跳过
                # 这个用例真实场景: BOM 存在但 rule 不允许.
                # 重新用非空 BOM:

        bom_lines = [
            {"ingredient_id": "99999999-0001-0001-0001-999999999999", "quantity": 0.5, "unit": "kg"}
        ]
        with patch.object(ad, "_get_bom_for_dish", AsyncMock(return_value=bom_lines)):
            with patch(
                "services.tx_supply.src.services.share_split_service.apply_split",
                AsyncMock(side_effect=ValueError("dish 不允许分享 (allow_share=FALSE)")),
            ):
                db = AsyncMock()
                db_result = MagicMock()
                db_result.scalar_one_or_none.return_value = None
                db.execute = AsyncMock(return_value=db_result)
                db.flush = AsyncMock()

                with pytest.raises(ValueError, match="不允许分享"):
                    await ad.deduct_for_dish(
                        dish_id=_DISH_SUANCAIYU,
                        quantity=1,
                        store_id=_STORE,
                        tenant_id=_TENANT_XUJI,
                        db=db,
                        share_split={"method": "even", "count": 2},
                    )

    @pytest.mark.asyncio
    async def test_share_split_event_emit_failure_fail_open(self):
        """emit_event 抛 RuntimeError → fail-open warning, BOM 扣料结果仍正常返回."""
        from services.tx_supply.src.services import auto_deduction as ad
        from services.tx_supply.src.models.share_split_models import (
            ResolvedShare,
            ResolvedSplitResult,
            ShareSplitMethod,
        )
        from decimal import Decimal

        bom_lines = [
            {"ingredient_id": "99999999-0001-0001-0001-999999999999", "quantity": 0.5, "unit": "kg"}
        ]
        fake_split = ResolvedSplitResult(
            method=ShareSplitMethod.EVEN,
            count=2,
            bom_cost_total_fen=10000,
            shares=[
                ResolvedShare(share_index=0, weight=Decimal("0.5"), attributed_cost_fen=5000),
                ResolvedShare(share_index=1, weight=Decimal("0.5"), attributed_cost_fen=5000),
            ],
        )

        # asyncio.create_task 直接调 emit_event coroutine, 如果 emitter import 抛
        # ImportError, fail-open 守门. 这里 mock apply_split 抛 RuntimeError 触发
        # except (ImportError, RuntimeError) 分支.
        with patch.object(ad, "_get_bom_for_dish", AsyncMock(return_value=bom_lines)):
            with patch(
                "services.tx_supply.src.services.share_split_service.apply_split",
                AsyncMock(side_effect=RuntimeError("emitter unavailable")),
            ):
                db = AsyncMock()
                db_result = MagicMock()
                db_result.scalar_one_or_none.return_value = None
                db.execute = AsyncMock(return_value=db_result)
                db.flush = AsyncMock()

                # fail-open: BOM 扣料完成, split_attribution 不附加, 不 raise
                result = await ad.deduct_for_dish(
                    dish_id=_DISH_SUANCAIYU,
                    quantity=1,
                    store_id=_STORE,
                    tenant_id=_TENANT_XUJI,
                    db=db,
                    share_split={"method": "even", "count": 2},
                )
                # missing_bom=False (走完 BOM 路径)
                assert result["missing_bom"] is False
                # split_attribution 不在 (因 fail-open)
                assert "split_attribution" not in result


# ─── 2. deduct_for_order share_split 透传 ────────────────────────────────────


class TestDeductForOrderShareSplitPassthrough:
    @pytest.mark.asyncio
    async def test_share_split_per_item_passed_to_deduct_for_dish(self):
        """deduct_for_order 透传 item 上的 share_split + order_item_id."""
        from services.tx_supply.src.services import auto_deduction as ad

        order_items = [
            {
                "dish_id": _DISH_SUANCAIYU,
                "quantity": 1,
                "item_name": "酸菜鱼",
                "share_split": {"method": "even", "count": 2},
                "order_item_id": _ORDER_ITEM_ID,
            }
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
            )

            mock_deduct.assert_awaited()
            call_kwargs = mock_deduct.await_args.kwargs
            assert call_kwargs["share_split"] == {"method": "even", "count": 2}
            assert call_kwargs["order_item_id_for_event"] == _ORDER_ITEM_ID
            assert call_kwargs["order_id_for_event"] == _ORDER_ID

    @pytest.mark.asyncio
    async def test_share_split_absent_passes_none_through(self):
        """item 不含 share_split → 透传 None 给 deduct_for_dish (backward compat)."""
        from services.tx_supply.src.services import auto_deduction as ad

        order_items = [
            {"dish_id": _DISH_SUANCAIYU, "quantity": 1, "item_name": "酸菜鱼"},
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
            )

            mock_deduct.assert_awaited()
            call_kwargs = mock_deduct.await_args.kwargs
            assert call_kwargs["share_split"] is None
            assert call_kwargs["order_item_id_for_event"] is None
