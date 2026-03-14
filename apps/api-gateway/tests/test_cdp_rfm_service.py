"""
CDP RFM Service + WeChat Channel 单元测试 — Sprint 2

测试 RFM 纯函数 + 重算服务 + 企微通道
"""
import os
for _k, _v in {
    "APP_ENV": "test",
    "DATABASE_URL": "postgresql+asyncpg://test:test@localhost/test",
    "REDIS_URL": "redis://localhost:6379/0",
    "CELERY_BROKER_URL": "redis://localhost:6379/0",
    "CELERY_RESULT_BACKEND": "redis://localhost:6379/0",
    "SECRET_KEY": "test-secret-key",
    "JWT_SECRET": "test-jwt-secret",
}.items():
    os.environ.setdefault(_k, _v)

import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from src.services.cdp_rfm_service import (
    CDPRFMService,
    score_recency,
    score_frequency,
    score_monetary,
    classify_rfm_level,
    compute_risk_score,
)
from src.services.cdp_wechat_channel import CDPWeChatChannel
from src.models.consumer_identity import ConsumerIdentity
from src.models.private_domain import PrivateDomainMember


# ── RFM 纯函数测试 ────────────────────────────────────────────────

class TestScoreRecency:
    """R评分：距最近消费天数 → 1-5"""

    def test_within_7_days(self):
        assert score_recency(0) == 5
        assert score_recency(3) == 5
        assert score_recency(7) == 5

    def test_within_14_days(self):
        assert score_recency(8) == 4
        assert score_recency(14) == 4

    def test_within_30_days(self):
        assert score_recency(15) == 3
        assert score_recency(30) == 3

    def test_within_60_days(self):
        assert score_recency(31) == 2
        assert score_recency(60) == 2

    def test_over_60_days(self):
        assert score_recency(61) == 1
        assert score_recency(365) == 1


class TestScoreFrequency:
    """F评分：消费频次 → 1-5"""

    def test_high_frequency(self):
        assert score_frequency(20) == 5
        assert score_frequency(50) == 5

    def test_medium_high(self):
        assert score_frequency(10) == 4
        assert score_frequency(19) == 4

    def test_medium(self):
        assert score_frequency(5) == 3
        assert score_frequency(9) == 3

    def test_low(self):
        assert score_frequency(2) == 2
        assert score_frequency(4) == 2

    def test_very_low(self):
        assert score_frequency(0) == 1
        assert score_frequency(1) == 1


class TestScoreMonetary:
    """M评分：消费金额（分）→ 1-5"""

    def test_very_high(self):
        assert score_monetary(500000) == 5  # 5000 yuan
        assert score_monetary(1000000) == 5

    def test_high(self):
        assert score_monetary(200000) == 4  # 2000 yuan
        assert score_monetary(499999) == 4

    def test_medium(self):
        assert score_monetary(80000) == 3  # 800 yuan
        assert score_monetary(199999) == 3

    def test_low(self):
        assert score_monetary(20000) == 2  # 200 yuan
        assert score_monetary(79999) == 2

    def test_very_low(self):
        assert score_monetary(0) == 1
        assert score_monetary(19999) == 1


class TestClassifyRFMLevel:
    """RFM → S1-S5 等级"""

    def test_s1_core(self):
        assert classify_rfm_level(5, 5, 5) == "S1"  # 15
        assert classify_rfm_level(5, 4, 4) == "S1"  # 13

    def test_s2_growth(self):
        assert classify_rfm_level(4, 3, 3) == "S2"  # 10
        assert classify_rfm_level(5, 3, 4) == "S2"  # 12

    def test_s3_normal(self):
        assert classify_rfm_level(3, 2, 2) == "S3"  # 7
        assert classify_rfm_level(3, 3, 3) == "S3"  # 9

    def test_s4_at_risk(self):
        assert classify_rfm_level(2, 1, 1) == "S4"  # 4
        assert classify_rfm_level(2, 2, 2) == "S4"  # 6

    def test_s5_lost(self):
        assert classify_rfm_level(1, 1, 1) == "S5"  # 3


class TestComputeRiskScore:
    """流失风险分 0-1"""

    def test_high_risk_low_rfm(self):
        risk = compute_risk_score(1, 1, 1)
        assert risk == 1.0

    def test_low_risk_high_rfm(self):
        risk = compute_risk_score(5, 5, 5)
        assert risk == 0.0

    def test_medium_risk(self):
        risk = compute_risk_score(3, 3, 3)
        assert 0.3 < risk < 0.7

    def test_r_weighted_60_percent(self):
        """R 占 60% 权重"""
        risk_low_r = compute_risk_score(1, 5, 5)  # R=1 高风险
        risk_high_r = compute_risk_score(5, 1, 1)  # R=5 低风险（近期消费）
        assert risk_low_r > risk_high_r


# ── CDPRFMService 测试 ──────────────────────────────────────────

class TestCDPRFMService:

    @pytest.fixture
    def service(self):
        return CDPRFMService()

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.flush = AsyncMock()
        db.execute = AsyncMock()
        db.scalar = AsyncMock(return_value=0)
        db.get = AsyncMock(return_value=None)
        return db

    @pytest.mark.asyncio
    async def test_recalculate_empty(self, service, mock_db):
        """无数据时返回零"""
        mock_result = AsyncMock()
        mock_result.all = MagicMock(return_value=[])
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.recalculate_all(mock_db)
        assert result["consumers_updated"] == 0
        assert result["members_updated"] == 0


# ── CDPWeChatChannel 测试 ───────────────────────────────────────

class TestCDPWeChatChannel:

    @pytest.fixture
    def channel(self):
        return CDPWeChatChannel()

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        db.get = AsyncMock(return_value=None)
        db.scalar = AsyncMock(return_value=0)
        return db

    @pytest.mark.asyncio
    async def test_send_consumer_not_found(self, channel, mock_db):
        """consumer 不存在 → not sent"""
        result = await channel.send_to_consumer(
            mock_db, uuid.uuid4(), "text", "hello",
        )
        assert result["sent"] is False
        assert result["reason"] == "consumer_not_found"

    @pytest.mark.asyncio
    async def test_send_no_openid(self, channel, mock_db):
        """无 wechat_openid → 跳过"""
        consumer = ConsumerIdentity(
            id=uuid.uuid4(),
            primary_phone="13800138000",
            wechat_openid=None,
        )
        mock_db.get = AsyncMock(return_value=consumer)
        # PrivateDomainMember 也无 openid
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await channel.send_to_consumer(
            mock_db, consumer.id, "text", "hello",
        )
        assert result["sent"] is False
        assert result["reason"] == "no_wechat_openid"

    @pytest.mark.asyncio
    async def test_batch_dry_run(self, channel, mock_db):
        """dry_run 模式只统计不发送"""
        mock_result = AsyncMock()
        mock_result.all = MagicMock(return_value=[
            (uuid.uuid4(), "oXYZ1", "phone1"),
            (uuid.uuid4(), "oXYZ2", "phone2"),
        ])
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await channel.batch_send_by_rfm(
            mock_db, "S001", ["S4", "S5"], "text", "唤醒消息",
            dry_run=True,
        )
        assert result["target_count"] == 2
        assert result["sent_count"] == 0
        assert result["dry_run"] is True

    @pytest.mark.asyncio
    async def test_channel_stats_empty(self, channel, mock_db):
        """空库统计"""
        mock_db.scalar = AsyncMock(return_value=0)

        result = await channel.get_channel_stats(mock_db)
        assert result["total_members"] == 0
        assert result["wechat_coverage_rate"] == 0.0
        assert result["cdp_link_rate"] == 0.0


# ── PrivateDomainMember 模型扩展 ─────────────────────────────────

class TestPrivateDomainMemberCDP:

    def test_has_consumer_id_field(self):
        """验证 consumer_id 字段已添加"""
        m = PrivateDomainMember(
            store_id="S001",
            customer_id="13800138000",
        )
        assert hasattr(m, "consumer_id")
        assert hasattr(m, "r_score")
        assert hasattr(m, "f_score")
        assert hasattr(m, "m_score")
