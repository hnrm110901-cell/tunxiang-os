"""Tier 1 — bom_service ↔ yield_standard 集成测试（PRD-06 / 毛利底线硬约束）

验证 bom_purchase_qty_with_yield helper：
  - active standard 存在时按 yield_rate 反算
  - standard 缺失时 fallback 用 BOM 原值
  - 多季节标按优先级（具体 > all）选最优
  - actual_yield_rate 超 tolerance 时 anomaly_detected=True

mock 风格：参考 test_yield_standard_service_tier1.py。
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

if sys.version_info < (3, 10):
    pytest.skip(
        "需要 Python 3.10+（生产环境为 3.11）— 本机 3.9 跳过避免 sys.modules 污染",
        allow_module_level=True,
    )

from services.tx_supply.src.services.bom_service import (  # noqa: E402
    bom_purchase_qty_with_yield,
)


_TENANT_XUJI = "11111111-aaaa-aaaa-aaaa-111111111111"
_INGREDIENT_SPINACH = "aaaaaaaa-0001-0001-0001-aaaaaaaaaaaa"
_STORE = "99999999-9999-9999-9999-999999999999"
_USER_FINANCE = "dddddddd-0004-0004-0004-dddddddddddd"


def _row(
    *,
    yield_rate: Decimal,
    season: str = "all",
    tolerance_pct: Decimal = Decimal("5.0"),
    approved_by: str | None = _USER_FINANCE,
    std_id: str = "eeeeeeee-0005-0005-0005-eeeeeeeeeeee",
) -> dict:
    return {
        "id": std_id,
        "tenant_id": _TENANT_XUJI,
        "ingredient_id": _INGREDIENT_SPINACH,
        "process_id": None,
        "yield_rate": yield_rate,
        "season": season,
        "effective_from": date(2026, 5, 1),
        "effective_to": None,
        "tolerance_pct": tolerance_pct,
        "approved_by": approved_by,
        "approved_at": datetime(2026, 5, 14, tzinfo=timezone.utc) if approved_by else None,
        "notes": None,
        "created_by": "cccccccc-0003-0003-0003-cccccccccccc",
        "created_at": datetime(2026, 5, 14, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 5, 14, tzinfo=timezone.utc),
        "is_deleted": False,
    }


def _mk_db_with_rows(rows: list[dict]) -> AsyncMock:
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        result = MagicMock()
        if "set_config" in sql:
            return MagicMock()
        if "SELECT" in sql.upper() and "ingredient_yield_standards" in sql:
            result.mappings.return_value.__iter__ = lambda self: iter(rows)
            return result
        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db


class TestBOMYieldIntegration:
    @pytest.mark.asyncio
    async def test_bom_uses_yield_rate_to_reverse_calc(self):
        """active standard 存在 → BOM 用量自动除以 yield_rate。

        场景：BOM 需 60kg 净菠菜 + active standard yield_rate=0.65
              → 应采购 ≈ 92.3077kg 毛菜
        """
        db = _mk_db_with_rows([_row(yield_rate=Decimal("0.6500"))])

        result = await bom_purchase_qty_with_yield(
            db=db,
            tenant_id=_TENANT_XUJI,
            ingredient_id=_INGREDIENT_SPINACH,
            bom_qty_kg=Decimal("60"),
            store_id=_STORE,
            season="all",
        )
        assert result["purchase_qty_kg"] == Decimal("92.3077")
        assert result["yield_rate"] == Decimal("0.6500")
        assert result["season_matched"] == "all"
        assert result["anomaly_detected"] is False

    @pytest.mark.asyncio
    async def test_bom_fallback_when_no_standard(self):
        """yield_standard 缺失时 fallback 原值（不阻塞 BOM 主流程）。

        场景：菠菜无任何 active 标 → purchase_qty_kg 直接等于 bom_qty_kg
        """
        db = _mk_db_with_rows([])  # 无 standard

        result = await bom_purchase_qty_with_yield(
            db=db,
            tenant_id=_TENANT_XUJI,
            ingredient_id=_INGREDIENT_SPINACH,
            bom_qty_kg=Decimal("60"),
            season="all",
        )
        assert result["purchase_qty_kg"] == Decimal("60.0000"), "fallback 原值"
        assert result["standard_id"] is None
        assert result["yield_rate"] is None
        assert result["anomaly_detected"] is False

    @pytest.mark.asyncio
    async def test_bom_multi_season_picks_specific(self):
        """多季节标按优先级（具体 > all）— BOM 反算选 winter 而非 all。"""
        rows = [
            _row(yield_rate=Decimal("0.7000"), season="winter",
                 std_id="ffffffff-0006-0006-0006-ffffffffffff"),
            _row(yield_rate=Decimal("0.6000"), season="all"),
        ]
        db = _mk_db_with_rows(rows)

        result = await bom_purchase_qty_with_yield(
            db=db,
            tenant_id=_TENANT_XUJI,
            ingredient_id=_INGREDIENT_SPINACH,
            bom_qty_kg=Decimal("70"),
            season="winter",
        )
        # 70 / 0.7 = 100kg（用 winter 0.7，不是 all 0.6）
        assert result["purchase_qty_kg"] == Decimal("100.0000")
        assert result["season_matched"] == "winter"

    @pytest.mark.asyncio
    async def test_bom_anomaly_flag_when_actual_exceeds_tolerance(self):
        """actual_yield_rate 与 standard 偏差超 tolerance_pct → anomaly_detected=True。

        场景：standard 0.65 tolerance 5%，实测 0.55（偏差 15.38% > 5%）→ anomaly 触发
        """
        db = _mk_db_with_rows([
            _row(yield_rate=Decimal("0.6500"), tolerance_pct=Decimal("5.0"))
        ])

        result = await bom_purchase_qty_with_yield(
            db=db,
            tenant_id=_TENANT_XUJI,
            ingredient_id=_INGREDIENT_SPINACH,
            bom_qty_kg=Decimal("60"),
            season="all",
            actual_yield_rate=Decimal("0.55"),
        )
        assert result["anomaly_detected"] is True, "actual 偏差超 tolerance 必须 flag"
        assert result["purchase_qty_kg"] == Decimal("92.3077"), "anomaly 不影响反算"
