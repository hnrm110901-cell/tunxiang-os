"""小红书营销适配器测试

覆盖 Mock 模式下的核心功能，确保适配器在无凭据时优雅降级。
"""
from __future__ import annotations

import pytest


class TestXiaohongshuMarketingAdapter:
    """XiaohongshuMarketingAdapter Mock 模式测试"""

    @pytest.fixture
    def adapter(self):
        from shared.integrations.xiaohongshu_marketing import XiaohongshuMarketingAdapter
        return XiaohongshuMarketingAdapter()

    def test_mock_mode(self, adapter) -> None:
        """未配置凭据时进入 mock 模式"""
        assert adapter.is_mock is True

    @pytest.mark.asyncio
    async def test_create_brand_note_mock(self, adapter) -> None:
        """Mock 模式下创建品牌笔记返回 mock 数据"""
        result = await adapter.create_brand_note(
            tenant_id="t-001",
            store_id="store-001",
            note_config={
                "title": "探店长沙必吃餐厅",
                "content": "今天来探访这家颇受好评的餐厅，招牌菜果然名不虚传...",
                "images": ["https://example.com/img1.jpg", "https://example.com/img2.jpg"],
                "note_type": "normal",
                "location_name": "屯象示例餐厅",
                "poi_id": "POI_12345",
            },
        )
        assert result["status"] == "mock"
        assert "MOCK_XHS_" in result["note_id"]
        assert result["platform"] == "xiaohongshu"

    @pytest.mark.asyncio
    async def test_get_note_performance_mock(self, adapter) -> None:
        """Mock 模式下获取笔记效果数据"""
        result = await adapter.get_note_performance(
            tenant_id="t-001",
            store_id="store-001",
            note_id="MOCK_XHS_ABCDEF01",
            days=7,
        )
        assert "views" in result
        assert result["views"] > 0
        assert 0 <= result["ctr"] <= 1

    @pytest.mark.asyncio
    async def test_get_store_mentions_mock(self, adapter) -> None:
        """Mock 模式下获取门店被提及数据"""
        result = await adapter.get_store_mentions(
            tenant_id="t-001",
            store_id="store-001",
            days=7,
        )
        assert "total_mentions" in result
        assert "avg_sentiment" in result
        assert 0 <= result["avg_sentiment"] <= 1

    @pytest.mark.asyncio
    async def test_get_ad_data_mock(self, adapter) -> None:
        """Mock 模式下获取广告 ROI 数据"""
        result = await adapter.get_ad_data(
            tenant_id="t-001",
            store_id="store-001",
            start_date="2026-04-01",
            end_date="2026-04-11",
        )
        assert "total_spend_fen" in result
        assert isinstance(result["total_spend_fen"], int)
        assert result["roi"] > 0

    @pytest.mark.asyncio
    async def test_manage_poi_store_mock(self, adapter) -> None:
        """Mock 模式下管理 POI 门店信息"""
        result = await adapter.manage_poi_store(
            tenant_id="t-001",
            store_id="store-001",
            action="get_info",
        )
        assert result["status"] == "mock"
        assert "poi_id" in result
