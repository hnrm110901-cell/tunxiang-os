"""Tier 1: 跨平台库存同步 — 防超卖测试

测试用例基于徐记海鲜真实运营场景：
- 菜品售罄后，所有平台必须同步下架（stock=0）
- 单个平台同步失败不影响其他平台
- 库存恢复后各平台自动恢复可售
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from services.tx_supply.src.services.inventory_sync_service import (
    InventorySyncService,
    PLATFORM_ORDER,
)


class TestInventorySyncTier1:
    """跨平台库存同步 — Tier 1 级（资金安全相关）"""

    async def test_sync_to_all_platforms_zero_stock(self):
        """菜品售罄：sku_id=SKU001, stock=0 → 所有平台收到 stock=0"""
        svc = InventorySyncService()
        with patch.object(svc, "sync_stock_to_platform", new_callable=AsyncMock) as mock_sync:
            mock_sync.return_value = True
            results = await svc.sync_stock_to_all_platforms("SKU001", 0)
            assert mock_sync.call_count == len(PLATFORM_ORDER)
            for platform in PLATFORM_ORDER:
                assert results[platform] is True

    async def test_one_platform_failure_does_not_block_others(self):
        """美团同步失败时，饿了吗/抖音/高德/淘宝不受影响"""
        svc = InventorySyncService()
        async def fail_meituan(sku_id, stock, platform, store_id=""):
            if platform == "meituan":
                raise ConnectionError("meituan API timeout")
            return True

        with patch.object(svc, "sync_stock_to_platform", side_effect=fail_meituan):
            results = await svc.sync_stock_to_all_platforms("SKU002", 10)
            assert results["meituan"] is False
            assert results["eleme"] is True
            assert results["douyin"] is True

    async def test_stock_restore_syncs_to_all_platforms(self):
        """库存恢复：sku_id=SKU003, stock=50 → 所有平台恢复可售"""
        svc = InventorySyncService()
        with patch.object(svc, "sync_stock_to_platform", new_callable=AsyncMock) as mock_sync:
            mock_sync.return_value = True
            results = await svc.sync_stock_to_all_platforms("SKU003", 50)
            assert len(results) == len(PLATFORM_ORDER)
            assert all(results.values())

    async def test_inventory_consumed_event_handler(self):
        """INVENTORY.CONSUMED 事件触发 → 自动同步到所有平台"""
        svc = InventorySyncService()
        event = {"sku_id": "SKU004", "remaining": 0, "store_id": "S001"}
        with patch.object(svc, "sync_stock_to_all_platforms", new_callable=AsyncMock) as mock_all:
            mock_all.return_value = {p: True for p in PLATFORM_ORDER}
            await svc.handle_inventory_consumed(event)
            mock_all.assert_called_once_with("SKU004", 0, "S001")

    async def test_empty_sku_id_skips_sync(self):
        """事件中没有 sku_id → 跳过同步，不崩溃"""
        svc = InventorySyncService()
        with patch.object(svc, "sync_stock_to_all_platforms", new_callable=AsyncMock) as mock_all:
            await svc.handle_inventory_consumed({"remaining": 0})
            mock_all.assert_not_called()
