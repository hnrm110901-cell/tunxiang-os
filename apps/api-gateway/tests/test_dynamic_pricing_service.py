"""
DynamicPricingService 单元测试

覆盖：
  - _is_peak_hour（纯函数）
  - recommend：各马斯洛层级策略 + 平峰让利 + 无会员降级 + DB 失败降级
  - _load_profile：正常加载 / 会员不存在 / DB 异常
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("APP_ENV", "test")

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.dynamic_pricing_service import DynamicPricingService


# ════════════════════════════════════════════════════════════════════════════════
# _is_peak_hour（纯函数）
# ════════════════════════════════════════════════════════════════════════════════


class TestIsPeakHour:
    def test_lunch_peak(self):
        assert DynamicPricingService._is_peak_hour(datetime(2024, 1, 1, 11, 30)) is True

    def test_dinner_peak(self):
        assert DynamicPricingService._is_peak_hour(datetime(2024, 1, 1, 18, 0)) is True

    def test_off_peak_morning(self):
        assert DynamicPricingService._is_peak_hour(datetime(2024, 1, 1, 9, 0)) is False

    def test_off_peak_afternoon(self):
        assert DynamicPricingService._is_peak_hour(datetime(2024, 1, 1, 15, 0)) is False

    def test_boundary_lunch_end(self):
        """13:00 不再是高峰（右开区间）。"""
        assert DynamicPricingService._is_peak_hour(datetime(2024, 1, 1, 13, 0)) is False

    def test_boundary_dinner_start(self):
        assert DynamicPricingService._is_peak_hour(datetime(2024, 1, 1, 17, 0)) is True


# ════════════════════════════════════════════════════════════════════════════════
# recommend — 各层级策略
# ════════════════════════════════════════════════════════════════════════════════


def _mock_db_for_member(frequency: int, monetary: int, recency_days=None, lifecycle_state=None):
    """构造返回指定会员数据的 mock DB。"""
    db = AsyncMock()
    row = MagicMock()
    row.__getitem__ = lambda self, i: [frequency, monetary, recency_days, lifecycle_state][i]
    db.execute.return_value.fetchone.return_value = row
    return db


class TestRecommend:
    # 高峰时段
    PEAK_TIME = datetime(2024, 1, 1, 12, 0)
    # 平峰时段
    OFF_PEAK_TIME = datetime(2024, 1, 1, 15, 0)

    @pytest.mark.asyncio
    async def test_l1_no_discount(self):
        """L1（未消费）→ 品质故事，无折扣。"""
        db = _mock_db_for_member(0, 0)
        svc = DynamicPricingService()
        offer = await svc.recommend("S001", "C001", db, at=self.PEAK_TIME)

        assert offer.maslow_level == 1
        assert offer.offer_type == "quality_story"
        assert offer.discount_pct == 0.0

    @pytest.mark.asyncio
    async def test_l2_discount_peak(self):
        """L2（消费1次）高峰 → 88折。"""
        db = _mock_db_for_member(1, 5000)
        svc = DynamicPricingService()
        offer = await svc.recommend("S001", "C001", db, at=self.PEAK_TIME)

        assert offer.maslow_level == 2
        assert offer.offer_type == "discount_coupon"
        assert offer.discount_pct == 8.8
        assert offer.is_peak_hour is True

    @pytest.mark.asyncio
    async def test_l2_extra_discount_off_peak(self):
        """L2 平峰 → 88折 额外加码 → 78折。"""
        db = _mock_db_for_member(1, 5000)
        svc = DynamicPricingService()
        offer = await svc.recommend("S001", "C001", db, at=self.OFF_PEAK_TIME)

        assert offer.maslow_level == 2
        assert offer.discount_pct == 7.8
        assert offer.is_peak_hour is False
        assert "平峰" in offer.description

    @pytest.mark.asyncio
    async def test_l3_group_bundle_peak(self):
        """L3（消费2-5次）高峰 → 78折聚餐套餐。"""
        db = _mock_db_for_member(3, 20000)
        svc = DynamicPricingService()
        offer = await svc.recommend("S001", "C001", db, at=self.PEAK_TIME)

        assert offer.maslow_level == 3
        assert offer.offer_type == "group_bundle"
        assert offer.discount_pct == 7.8

    @pytest.mark.asyncio
    async def test_l3_extra_discount_off_peak(self):
        """L3 平峰 → 78折再加码 → 68折。"""
        db = _mock_db_for_member(4, 15000)
        svc = DynamicPricingService()
        offer = await svc.recommend("S001", "C001", db, at=self.OFF_PEAK_TIME)

        assert offer.maslow_level == 3
        assert offer.discount_pct == 6.8

    @pytest.mark.asyncio
    async def test_l4_no_discount(self):
        """L4（高频 < ¥500）→ 专属礼遇，无折扣。"""
        db = _mock_db_for_member(8, 30000)  # 300元 < 500元
        svc = DynamicPricingService()
        offer = await svc.recommend("S001", "C001", db, at=self.OFF_PEAK_TIME)

        assert offer.maslow_level == 4
        assert offer.offer_type == "exclusive_access"
        assert offer.discount_pct == 0.0

    @pytest.mark.asyncio
    async def test_l5_experience(self):
        """L5（高频 ≥ ¥500）→ 主厨体验，无折扣。"""
        db = _mock_db_for_member(10, 60000)  # 600元 ≥ 500元
        svc = DynamicPricingService()
        offer = await svc.recommend("S001", "C001", db, at=self.PEAK_TIME)

        assert offer.maslow_level == 5
        assert offer.offer_type == "experience"
        assert offer.discount_pct == 0.0

    @pytest.mark.asyncio
    async def test_confidence_grows_with_frequency(self):
        """消费次数越多置信度越高。"""
        db_low = _mock_db_for_member(1, 5000)
        db_high = _mock_db_for_member(10, 50000)
        svc = DynamicPricingService()

        offer_low = await svc.recommend("S001", "C001", db_low, at=self.PEAK_TIME)
        offer_high = await svc.recommend("S001", "C002", db_high, at=self.PEAK_TIME)

        assert offer_high.confidence > offer_low.confidence

    @pytest.mark.asyncio
    async def test_confidence_capped_at_1(self):
        """置信度上限为 1.0。"""
        db = _mock_db_for_member(100, 500000)
        svc = DynamicPricingService()
        offer = await svc.recommend("S001", "C001", db, at=self.PEAK_TIME)

        assert offer.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_member_not_found_defaults_to_l1(self):
        """会员不存在 → 降级 L1。"""
        db = AsyncMock()
        db.execute.return_value.fetchone.return_value = None
        svc = DynamicPricingService()
        offer = await svc.recommend("S001", "NONEXIST", db, at=self.PEAK_TIME)

        assert offer.maslow_level == 1

    @pytest.mark.asyncio
    async def test_db_error_defaults_to_l1(self):
        """DB 异常 → 静默降级 L1，不抛出。"""
        db = AsyncMock()
        db.execute.side_effect = Exception("connection error")
        svc = DynamicPricingService()
        offer = await svc.recommend("S001", "C001", db, at=self.PEAK_TIME)

        assert offer.maslow_level == 1

    @pytest.mark.asyncio
    async def test_l4_off_peak_no_extra_discount(self):
        """L4/L5 平峰不追加折扣（折扣本来就是 0）。"""
        db = _mock_db_for_member(8, 30000)
        svc = DynamicPricingService()
        offer = await svc.recommend("S001", "C001", db, at=self.OFF_PEAK_TIME)

        assert offer.maslow_level == 4
        assert offer.discount_pct == 0.0
        assert "平峰" not in offer.description
