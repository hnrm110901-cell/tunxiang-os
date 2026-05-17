"""#710 YYYY-MM dedup Phase 2 Lane D — tx-member regression tests

验证 cross_store_settlement 的 parse_year_month 集成：
- 畸形输入 → ValueError（通过 None branch）
- 合法输入 → (year, month) 正确解包
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from ..services import points_engine as pe_mod
from ..services.points_engine import cross_store_settlement


class TestCrossStoreSettlementYYYYMM:
    """cross_store_settlement month 参数解析回归测试"""

    @pytest.mark.asyncio
    async def test_single_digit_month_raises(self):
        """'2026-3' 单月无补零 → parse_year_month 返回 None → ValueError"""
        mock_db = AsyncMock()
        with patch.object(pe_mod, "_set_tenant", new=AsyncMock()):
            with pytest.raises(ValueError, match="month must be YYYY-MM format"):
                await cross_store_settlement(
                    tenant_id="t1",
                    month="2026-3",
                    db=mock_db,
                )

    @pytest.mark.asyncio
    async def test_empty_string_raises(self):
        """'' 空字符串 → parse_year_month 返回 None → ValueError"""
        mock_db = AsyncMock()
        with patch.object(pe_mod, "_set_tenant", new=AsyncMock()):
            with pytest.raises(ValueError, match="month must be YYYY-MM format"):
                await cross_store_settlement(
                    tenant_id="t1",
                    month="",
                    db=mock_db,
                )

    @pytest.mark.asyncio
    async def test_abc_raises(self):
        """'abc' 非日期字符串 → parse_year_month 返回 None → ValueError"""
        mock_db = AsyncMock()
        with patch.object(pe_mod, "_set_tenant", new=AsyncMock()):
            with pytest.raises(ValueError, match="month must be YYYY-MM format"):
                await cross_store_settlement(
                    tenant_id="t1",
                    month="abc",
                    db=mock_db,
                )

    @pytest.mark.asyncio
    async def test_valid_month_proceeds(self):
        """'2026-03' 合法输入 → (2026, 3) 正确解包，函数继续执行到 db.execute"""
        from unittest.mock import MagicMock

        mock_db = AsyncMock()
        # db.execute returns a sync-chainable result (mappings().all() is sync)
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        with patch.object(pe_mod, "_set_tenant", new=AsyncMock()):
            result = await cross_store_settlement(
                tenant_id="t1",
                month="2026-03",
                db=mock_db,
            )
        assert result["month"] == "2026-03"
        assert "store_settlements" in result
        # db.execute 被调用（说明 parse_year_month 通过，函数执行到 SQL 层）
        assert mock_db.execute.called
