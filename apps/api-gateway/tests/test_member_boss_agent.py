"""
MemberAgent + BossAgent 单元测试 — Sprint 3

测试纯函数 + 服务方法（mock DB）
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
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime


# ── MemberAgent 纯函数 ────────────────────────────────────────────

from src.services.member_agent_service import (
    classify_dormant_urgency,
    generate_wakeup_message,
    compute_wakeup_kpi,
)


class TestClassifyDormantUrgency:
    """沉睡紧急度分级"""

    def test_critical_high_value_long_dormant(self):
        # 90天+ & 2000元+
        assert classify_dormant_urgency(90, 200000) == "critical"
        assert classify_dormant_urgency(120, 500000) == "critical"

    def test_high_60_days(self):
        assert classify_dormant_urgency(60, 5000) == "high"
        assert classify_dormant_urgency(75, 10000) == "high"

    def test_medium_30_days(self):
        assert classify_dormant_urgency(30, 5000) == "medium"
        assert classify_dormant_urgency(45, 10000) == "medium"

    def test_low_recent(self):
        assert classify_dormant_urgency(10, 5000) == "low"
        assert classify_dormant_urgency(0, 0) == "low"

    def test_high_value_but_not_long_enough(self):
        # 高消费但 < 90天 → 不算 critical
        assert classify_dormant_urgency(60, 500000) == "high"


class TestGenerateWakeupMessage:
    """三阶段唤醒文案"""

    def test_step1_loss_aversion(self):
        msg = generate_wakeup_message(1, "张三", "尝在一起")
        assert "张三" in msg
        assert "尝在一起" in msg
        assert "失效" in msg

    def test_step2_social_proof(self):
        msg = generate_wakeup_message(2, "李四")
        assert "李四" in msg
        assert "老顾客" in msg

    def test_step3_minimal_action(self):
        msg = generate_wakeup_message(3, "王五")
        assert "王五" in msg
        assert "好" in msg

    def test_default_name(self):
        msg = generate_wakeup_message(1, None)
        assert "尊敬的会员" in msg

    def test_default_store_name(self):
        msg = generate_wakeup_message(1, "test")
        assert "门店" in msg


class TestComputeWakeupKpi:
    """唤醒 KPI 计算"""

    def test_met_target(self):
        kpi = compute_wakeup_kpi(50)
        assert kpi["kpi_met"] is True
        assert kpi["achievement_rate"] == 1.0
        assert kpi["sent_this_week"] == 50
        assert kpi["weekly_target"] == 50

    def test_below_target(self):
        kpi = compute_wakeup_kpi(30)
        assert kpi["kpi_met"] is False
        assert kpi["achievement_rate"] == 0.6

    def test_above_target(self):
        kpi = compute_wakeup_kpi(80)
        assert kpi["kpi_met"] is True
        assert kpi["achievement_rate"] == 1.6

    def test_zero(self):
        kpi = compute_wakeup_kpi(0)
        assert kpi["kpi_met"] is False
        assert kpi["achievement_rate"] == 0.0

    def test_custom_target(self):
        kpi = compute_wakeup_kpi(10, target=10)
        assert kpi["kpi_met"] is True
        assert kpi["weekly_target"] == 10


# ── BossAgent 纯函数 ──────────────────────────────────────────────

from src.services.boss_agent_service import (
    format_boss_brief,
    compute_member_health_score,
)


class TestFormatBossBrief:
    """老板30秒速览简报"""

    def test_basic_brief(self):
        text = format_boss_brief(
            revenue_yuan=12500,
            order_count=85,
            new_consumers=3,
            dormant_wakeup_sent=10,
            vip_at_risk=2,
            top_issue="回访2位VIP客户",
        )
        assert "¥12,500" in text
        assert "85单" in text
        assert "3位客户" in text
        assert "10条沉睡唤醒" in text
        assert "2位VIP" in text
        assert "回访" in text

    def test_no_new_consumers(self):
        text = format_boss_brief(0, 0, 0, 0, 0, "")
        assert "¥0" in text
        assert "新增" not in text

    def test_200_char_limit(self):
        text = format_boss_brief(
            999999, 999, 999, 999, 999,
            "这是一个非常长的建议行动" * 10,
        )
        assert len(text) <= 200

    def test_no_top_issue(self):
        text = format_boss_brief(1000, 10, 0, 0, 0, "")
        assert "建议行动" not in text


class TestComputeMemberHealthScore:
    """会员健康评分"""

    def test_all_s1_perfect(self):
        score = compute_member_health_score(100, 0, 0, 0, 0)
        assert score == 100.0

    def test_all_s5_zero(self):
        score = compute_member_health_score(0, 0, 0, 0, 100)
        assert score == 0.0

    def test_mixed(self):
        # S1*100 + S2*80 + S3*60 + S4*30 + S5*0
        # (10*100 + 20*80 + 30*60 + 20*30 + 20*0) / 100
        # = (1000 + 1600 + 1800 + 600 + 0) / 100 = 50.0
        score = compute_member_health_score(10, 20, 30, 20, 20)
        assert score == 50.0

    def test_empty(self):
        score = compute_member_health_score(0, 0, 0, 0, 0)
        assert score == 0.0

    def test_s2_only(self):
        score = compute_member_health_score(0, 50, 0, 0, 0)
        assert score == 80.0


# ── MemberAgentService 异步测试 ───────────────────────────────────

from src.services.member_agent_service import MemberAgentService


class TestMemberAgentService:

    @pytest.fixture
    def service(self):
        return MemberAgentService()

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.flush = AsyncMock()
        db.execute = AsyncMock()
        db.scalar = AsyncMock(return_value=0)
        return db

    @pytest.mark.asyncio
    async def test_scan_dormant_empty(self, service, mock_db):
        """无沉睡会员时返回空列表"""
        mock_result = AsyncMock()
        mock_result.all = MagicMock(return_value=[])
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.scan_dormant_members(mock_db, "S001")
        assert result == []

    @pytest.mark.asyncio
    async def test_scan_dormant_with_data(self, service, mock_db):
        """沉睡会员按紧急度返回"""
        member_id = uuid.uuid4()
        consumer_id = uuid.uuid4()
        mock_result = AsyncMock()
        mock_result.all = MagicMock(return_value=[
            (member_id, consumer_id, "13800138000", 90, 200000, 5, "S4", "oXYZ123"),
        ])
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.scan_dormant_members(mock_db, "S001")
        assert len(result) == 1
        assert result[0]["urgency"] == "critical"
        assert result[0]["monetary_yuan"] == 2000.0
        assert result[0]["has_wechat"] is True

    @pytest.mark.asyncio
    async def test_batch_wakeup_dry_run(self, service, mock_db):
        """dry_run 模式只统计不触发"""
        member_id = uuid.uuid4()
        consumer_id = uuid.uuid4()
        mock_result = AsyncMock()
        mock_result.all = MagicMock(return_value=[
            (member_id, consumer_id, "13800138000", 60, 100000, 3, "S4", "oXYZ"),
        ])
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.batch_trigger_wakeup(
            mock_db, "S001", dry_run=True,
        )
        assert result["dry_run"] is True
        assert result["triggered"] == 0
        assert result["eligible"] == 1

    @pytest.mark.asyncio
    async def test_vip_alerts_empty(self, service, mock_db):
        """无VIP预警时返回空"""
        mock_result = AsyncMock()
        mock_result.all = MagicMock(return_value=[])
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.get_vip_protection_alerts(mock_db, "S001")
        assert result == []


# ── BossAgentService 异步测试 ─────────────────────────────────────

from src.services.boss_agent_service import BossAgentService


class TestBossAgentService:

    @pytest.fixture
    def service(self):
        return BossAgentService()

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.flush = AsyncMock()
        db.execute = AsyncMock()
        db.scalar = AsyncMock(return_value=0)
        return db

    @pytest.mark.asyncio
    async def test_member_health_dashboard_empty(self, service, mock_db):
        """无会员时返回零分"""
        mock_result = AsyncMock()
        mock_result.all = MagicMock(return_value=[])
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.scalar = AsyncMock(return_value=0)

        result = await service.get_member_health_dashboard(mock_db)
        assert result["total_members"] == 0
        assert result["health_score"] == 0.0
        assert result["cdp_link_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_multi_store_comparison_empty(self, service, mock_db):
        """无门店数据时返回空列表"""
        mock_result = AsyncMock()
        mock_result.all = MagicMock(return_value=[])
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.get_multi_store_comparison(mock_db)
        assert result == []

    @pytest.mark.asyncio
    async def test_multi_store_comparison_with_data(self, service, mock_db):
        """跨门店对标返回按评分排序"""
        mock_result = AsyncMock()
        mock_result.all = MagicMock(return_value=[
            ("S001", "S1", 50),
            ("S001", "S2", 30),
            ("S001", "S3", 20),
            ("S001", "S4", 0),
            ("S001", "S5", 0),
            ("S002", "S1", 5),
            ("S002", "S4", 40),
            ("S002", "S5", 55),
        ])
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.get_multi_store_comparison(mock_db)
        assert len(result) == 2
        # S002 评分更低，排在前面
        assert result[0]["store_id"] == "S002"
        assert result[0]["needs_attention"] is True
        assert result[1]["store_id"] == "S001"
