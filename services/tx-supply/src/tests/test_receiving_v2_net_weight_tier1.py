"""Tier 1 — receiving_v2 自动扣秤集成契约测试（PRD-02 / 毛利底线硬约束）

测试 apply_weight_deduction_for_item enhancement layer：
  1. gross_weight_kg 给出 + 单类 ice 8% 标 → accepted_quantity = 92kg（毛重 100kg）
  2. gross_weight_kg 为 None → 跳过扣秤（向后兼容主流程）
  3. 多扣秤项叠加：ice 8% + packaging 0.3kg → 净 91.7kg
  4. Anomaly emit：超 tolerance → asyncio.create_task 旁路异步发射

不打到真 DB — AsyncMock 拦截 select / insert / update。
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if sys.version_info < (3, 10):
    pytest.skip(
        "需要 Python 3.10+（生产环境为 3.11）— 本机 3.9 跳过避免 sys.modules 污染",
        allow_module_level=True,
    )

from services.tx_supply.src.services.receiving_v2_service import (  # noqa: E402
    apply_weight_deduction_for_item,
)


# ─── 常量（徐记海鲜场景）─────────────────────────────────────────────────────

_TENANT_XUJI = "11111111-aaaa-aaaa-aaaa-111111111111"
_INGREDIENT_FISH = "aaaaaaaa-0001-0001-0001-aaaaaaaaaaaa"
_ORDER_ID = "bbbbbbbb-0002-0002-0002-bbbbbbbbbbbb"
_ITEM_ID = "cccccccc-0003-0003-0003-cccccccccccc"
_USER_FINANCE = "dddddddd-0004-0004-0004-dddddddddddd"


def _std_row(
    *,
    deduct_type: str = "ice",
    deduct_method: str = "percentage",
    deduct_value: Decimal = Decimal("8.0"),
    tolerance_pct: Decimal = Decimal("2.0"),
) -> dict:
    return {
        "id": "eeeeeeee-0005-0005-0005-eeeeeeeeeeee",
        "tenant_id": _TENANT_XUJI,
        "ingredient_id": _INGREDIENT_FISH,
        "deduct_type": deduct_type,
        "deduct_method": deduct_method,
        "deduct_value": deduct_value,
        "tolerance_pct": tolerance_pct,
        "effective_from": date(2026, 5, 1),
        "effective_to": None,
        "approved_by": _USER_FINANCE,
        "approved_at": datetime(2026, 5, 14, tzinfo=timezone.utc),
        "notes": None,
        "created_by": _USER_FINANCE,
        "created_at": datetime(2026, 5, 14, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 5, 14, tzinfo=timezone.utc),
        "is_deleted": False,
    }


def _mk_db(*, standards: list[dict]) -> AsyncMock:
    """Mock DB：list_weight_standards 返回 standards / INSERT / UPDATE / select item all OK。"""
    db = AsyncMock()

    item = MagicMock()
    item.id = _ITEM_ID
    item.status = "pending"
    item.actual_quantity = Decimal("0")
    item.accepted_quantity = Decimal("0")
    item.rejected_quantity = Decimal("0")

    async def execute_side_effect(query, params=None):
        sql = str(query)
        result = MagicMock()

        if "set_config" in sql:
            return MagicMock()

        # weight_standard_service.list_weight_standards SELECT
        if "SELECT" in sql.upper() and "ingredient_weight_standards" in sql:
            result.mappings.return_value.__iter__ = lambda self: iter(standards)
            return result

        # weight_standard_service.record_weight_deduction INSERT
        if "INSERT INTO receiving_weight_deductions" in sql:
            return MagicMock()

        # ReceivingOrderItem select FOR UPDATE — SQLAlchemy ORM 路径
        if "receiving_order_items" in sql and "FOR UPDATE" in sql:
            result.scalar_one_or_none = MagicMock(return_value=item)
            return result

        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)
    db.flush = AsyncMock()
    return db, item


# ─── 1. gross_weight_kg 给出 + 单类 ice 8% 标 ───────────────────────────────


class TestSingleDeduction:
    @pytest.mark.asyncio
    async def test_gross_100kg_ice_8pct_net_92kg(self):
        """毛重 100kg + ice 8% 标 → net=92kg, accepted_quantity=92。"""
        db, item = _mk_db(standards=[_std_row()])

        # 拦截 ReceivingOrderItem ORM query — receiving_v2_service 用 select() 的路径
        # 由于 scalar_one_or_none 已 patch 在 result 上，需要 db.execute 路径分支匹配
        with patch(
            "services.tx_supply.src.services.receiving_v2_service.select"
        ) as mock_select:
            mock_q = MagicMock()
            mock_q.where.return_value = mock_q
            mock_q.with_for_update.return_value = mock_q
            mock_select.return_value = mock_q

            scalar_result = MagicMock()
            scalar_result.scalar_one_or_none = MagicMock(return_value=item)
            db.execute = AsyncMock(side_effect=_make_execute_with_item(item, [_std_row()], scalar_result))

            result = await apply_weight_deduction_for_item(
                order_id=_ORDER_ID,
                item_id=_ITEM_ID,
                tenant_id=_TENANT_XUJI,
                ingredient_id=_INGREDIENT_FISH,
                gross_weight_kg=Decimal("100"),
                db=db,
            )

        assert result is not None
        assert result["net_weight_kg"] == Decimal("92.0000")
        assert item.accepted_quantity == Decimal("92.0000"), "ReceivingOrderItem.accepted_quantity 必须 = net"
        assert item.actual_quantity == Decimal("100"), "actual_quantity 必须 = gross"
        assert item.status == "accepted"
        assert len(result["deductions"]) == 1


def _make_execute_with_item(item, standards, scalar_result):
    """统一 db.execute 副作用 — 区分 ingredient_weight_standards / receiving_weight_deductions / ReceivingOrderItem 三路径。"""

    async def side_effect(query, params=None):
        sql = str(query)
        result = MagicMock()

        if "set_config" in sql:
            return MagicMock()

        if "SELECT" in sql.upper() and "ingredient_weight_standards" in sql:
            result.mappings.return_value.__iter__ = lambda self: iter(standards)
            return result

        if "INSERT INTO receiving_weight_deductions" in sql:
            return MagicMock()

        # 默认假设是 ReceivingOrderItem ORM query
        return scalar_result

    return side_effect


# ─── 2. gross_weight_kg 为 None → 跳过扣秤（向后兼容） ─────────────────────


class TestBackwardCompat:
    @pytest.mark.asyncio
    async def test_no_gross_weight_returns_none_skip(self):
        """gross_weight_kg=None → 直接返回 None，不查 DB（向后兼容现有 receiving 路径）。"""
        db = AsyncMock()
        result = await apply_weight_deduction_for_item(
            order_id=_ORDER_ID,
            item_id=_ITEM_ID,
            tenant_id=_TENANT_XUJI,
            ingredient_id=_INGREDIENT_FISH,
            gross_weight_kg=None,
            db=db,
        )
        assert result is None
        # 不应该调用 db.execute（fast path）
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_negative_gross_weight_raises(self):
        """gross_weight_kg <= 0 → ValueError。"""
        db = AsyncMock()
        with pytest.raises(ValueError, match="gross_weight_kg 必须 > 0"):
            await apply_weight_deduction_for_item(
                order_id=_ORDER_ID,
                item_id=_ITEM_ID,
                tenant_id=_TENANT_XUJI,
                ingredient_id=_INGREDIENT_FISH,
                gross_weight_kg=Decimal("0"),
                db=db,
            )


# ─── 3. 多扣秤项叠加 ────────────────────────────────────────────────────────


class TestMultiDeductions:
    @pytest.mark.asyncio
    async def test_ice_plus_packaging_stack(self):
        """ice 8% + packaging 0.3kg 同 ingredient → 净 91.7kg。"""
        item = MagicMock()
        item.status = "pending"
        item.actual_quantity = Decimal("0")
        item.accepted_quantity = Decimal("0")
        item.rejected_quantity = Decimal("0")

        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none = MagicMock(return_value=item)

        standards = [
            _std_row(deduct_type="ice", deduct_method="percentage", deduct_value=Decimal("8.0")),
            _std_row(
                deduct_type="packaging", deduct_method="fixed_kg", deduct_value=Decimal("0.3")
            ),
        ]

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=_make_execute_with_item(item, standards, scalar_result))
        db.flush = AsyncMock()

        result = await apply_weight_deduction_for_item(
            order_id=_ORDER_ID,
            item_id=_ITEM_ID,
            tenant_id=_TENANT_XUJI,
            ingredient_id=_INGREDIENT_FISH,
            gross_weight_kg=Decimal("100"),
            db=db,
        )
        assert result is not None
        assert result["net_weight_kg"] == Decimal("91.7000")
        assert len(result["deductions"]) == 2, "两个扣秤项都必须叠加"
        assert item.accepted_quantity == Decimal("91.7000")


# ─── 4. Anomaly emit event ──────────────────────────────────────────────────


class TestAnomalyEmit:
    @pytest.mark.asyncio
    async def test_anomaly_detected_when_actual_exceeds_tolerance(self):
        """actual_total_deduction 偏差超 tolerance → result["anomaly_detected"]=True + create_task 调用。

        旁路异步发射不阻塞主流程 — 验证 anomaly_detected 标记即可，emit 失败 fail-open。
        """
        item = MagicMock()
        item.status = "pending"
        item.actual_quantity = Decimal("0")
        item.accepted_quantity = Decimal("0")
        item.rejected_quantity = Decimal("0")

        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none = MagicMock(return_value=item)

        # 标 8%，毛 100kg → 标准扣 8kg；实测扣 11kg → 偏差 3% > tolerance 2%
        standards = [_std_row(tolerance_pct=Decimal("2.0"))]

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=_make_execute_with_item(item, standards, scalar_result))
        db.flush = AsyncMock()

        # patch asyncio.create_task 防止真的 schedule（避免 RuntimeError: no running event loop）
        with patch(
            "services.tx_supply.src.services.receiving_v2_service.asyncio.create_task"
        ) as mock_create_task:
            result = await apply_weight_deduction_for_item(
                order_id=_ORDER_ID,
                item_id=_ITEM_ID,
                tenant_id=_TENANT_XUJI,
                ingredient_id=_INGREDIENT_FISH,
                gross_weight_kg=Decimal("100"),
                actual_total_deduction_kg=Decimal("11"),
                db=db,
            )

        assert result is not None
        assert result["anomaly_detected"] is True, "偏差超 tolerance 必须 anomaly_detected=True"
        assert mock_create_task.called, "anomaly 必须 asyncio.create_task 旁路发射事件"
