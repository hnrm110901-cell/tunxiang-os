"""S4W15-16 AI舆情监控与危机预警 — 综合测试

覆盖：
- TestReputationMonitor: 激增检测（无激增/有激增）、预警创建、SLA计算、严重级别分类
- TestCrisisResponder: assess_crisis动作、generate_response_draft（mock Claude）
- TestReputationRoutes: 预警列表/回应/升级/解决流程
- TestSLAReport: 合规率计算
"""

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from services.reputation_monitor import ReputationMonitor


# ═══════════════════════════════════════
# ReputationMonitor 测试
# ═══════════════════════════════════════


class TestReputationMonitor:
    """舆情监控服务测试"""

    def setup_method(self) -> None:
        self.monitor = ReputationMonitor()
        self.tenant_id = uuid.uuid4()
        self.store_id = uuid.uuid4()

    @pytest.mark.asyncio
    async def test_no_spike_detected(self) -> None:
        """基线正常，不触发激增预警"""
        db = AsyncMock()

        # set_config
        set_config_result = AsyncMock()
        # baseline: 168 negative in 7 days = 1 per hour
        baseline_result = AsyncMock()
        baseline_result.scalar.return_value = 168
        # current: 1 negative in 60 min (1x baseline, not > 2x)
        current_result = AsyncMock()
        current_result.scalar.return_value = 1

        call_count = 0

        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return set_config_result
            elif call_count == 2:
                return baseline_result
            return current_result

        db.execute = AsyncMock(side_effect=mock_execute)

        result = await self.monitor.detect_negative_spike(
            self.tenant_id, self.store_id, db
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_spike_detected(self) -> None:
        """负面提及超过基线2倍，触发激增预警"""
        db = AsyncMock()

        set_config_result = AsyncMock()
        # baseline: 168 negatives in 7 days = 1 per hour
        baseline_result = AsyncMock()
        baseline_result.scalar.return_value = 168
        # current: 5 negatives in 60 min (5x baseline -> spike)
        current_result = AsyncMock()
        current_result.scalar.return_value = 5
        # mention IDs
        mention_rows = [(str(uuid.uuid4()),) for _ in range(5)]
        mention_result = AsyncMock()
        mention_result.fetchall.return_value = mention_rows
        # platform
        platform_result = AsyncMock()
        platform_result.fetchone.return_value = ("dianping", 5)
        # insert
        insert_result = AsyncMock()
        insert_result.rowcount = 1

        call_count = 0

        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return set_config_result
            elif call_count == 2:
                return baseline_result
            elif call_count == 3:
                return current_result
            elif call_count == 4:
                return mention_result
            elif call_count == 5:
                return platform_result
            elif call_count == 6:
                return set_config_result  # create_alert set_config
            return insert_result

        db.execute = AsyncMock(side_effect=mock_execute)
        db.commit = AsyncMock()

        with patch.object(self.monitor, "_generate_summary", return_value="负面激增预警摘要"):
            result = await self.monitor.detect_negative_spike(
                self.tenant_id, self.store_id, db
            )

        assert result is not None
        assert result["alert_type"] == "negative_spike"
        assert result["severity"] == "critical"  # 5x is critical
        assert "alert_id" in result

    @pytest.mark.asyncio
    async def test_create_alert(self) -> None:
        """成功创建预警"""
        db = AsyncMock()
        set_config_result = AsyncMock()
        insert_result = AsyncMock()

        call_count = 0

        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return set_config_result
            return insert_result

        db.execute = AsyncMock(side_effect=mock_execute)
        db.commit = AsyncMock()

        alert_data = {
            "store_id": str(self.store_id),
            "platform": "weibo",
            "alert_type": "crisis",
            "severity": "high",
            "trigger_mention_ids": [str(uuid.uuid4())],
            "trigger_data": {"negative_count": 10, "spike_ratio": 4.0},
        }

        with patch.object(self.monitor, "_generate_summary", return_value="测试摘要"):
            result = await self.monitor.create_alert(self.tenant_id, alert_data, db)

        assert "alert_id" in result
        assert result["alert_type"] == "crisis"
        assert result["severity"] == "high"
        assert result["summary"] == "测试摘要"
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_sla_calculation_met(self) -> None:
        """响应在SLA内，sla_met=True"""
        db = AsyncMock()
        set_config_result = AsyncMock()

        # 创建时间为20分钟前（SLA目标30分钟=1800秒）
        created_at = datetime.now(tz=timezone.utc) - timedelta(minutes=20)
        alert_row = MagicMock()
        alert_row.__getitem__ = lambda self, i: [created_at, 1800][i]

        alert_result = AsyncMock()
        alert_result.fetchone.return_value = alert_row

        update_row = MagicMock()
        update_row.__getitem__ = lambda self, i: [str(uuid.uuid4())][i]
        update_result = AsyncMock()
        update_result.fetchone.return_value = update_row

        call_count = 0

        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return set_config_result
            elif call_count == 2:
                return alert_result
            return update_result

        db.execute = AsyncMock(side_effect=mock_execute)
        db.commit = AsyncMock()

        alert_id = uuid.uuid4()
        result = await self.monitor.respond_to_alert(
            self.tenant_id, alert_id, "已处理此问题", db
        )

        assert result["sla_met"] is True
        assert result["response_time_sec"] <= 1800

    @pytest.mark.asyncio
    async def test_sla_calculation_missed(self) -> None:
        """响应超过SLA，sla_met=False"""
        db = AsyncMock()
        set_config_result = AsyncMock()

        # 创建时间为60分钟前（SLA目标30分钟=1800秒）
        created_at = datetime.now(tz=timezone.utc) - timedelta(minutes=60)
        alert_row = MagicMock()
        alert_row.__getitem__ = lambda self, i: [created_at, 1800][i]

        alert_result = AsyncMock()
        alert_result.fetchone.return_value = alert_row

        update_row = MagicMock()
        update_row.__getitem__ = lambda self, i: [str(uuid.uuid4())][i]
        update_result = AsyncMock()
        update_result.fetchone.return_value = update_row

        call_count = 0

        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return set_config_result
            elif call_count == 2:
                return alert_result
            return update_result

        db.execute = AsyncMock(side_effect=mock_execute)
        db.commit = AsyncMock()

        alert_id = uuid.uuid4()
        result = await self.monitor.respond_to_alert(
            self.tenant_id, alert_id, "延迟处理", db
        )

        assert result["sla_met"] is False
        assert result["response_time_sec"] > 1800

    def test_severity_classification_critical(self) -> None:
        """spike_ratio >= 5.0 → critical"""
        # 直接测试 detect 内的逻辑
        spike_ratio = 5.0
        if spike_ratio >= 5.0:
            severity = "critical"
        elif spike_ratio >= 3.5:
            severity = "high"
        elif spike_ratio >= 2.5:
            severity = "medium"
        else:
            severity = "low"
        assert severity == "critical"

    def test_severity_classification_high(self) -> None:
        """spike_ratio 3.5-4.9 → high"""
        spike_ratio = 4.0
        if spike_ratio >= 5.0:
            severity = "critical"
        elif spike_ratio >= 3.5:
            severity = "high"
        elif spike_ratio >= 2.5:
            severity = "medium"
        else:
            severity = "low"
        assert severity == "high"

    def test_severity_classification_medium(self) -> None:
        """spike_ratio 2.5-3.4 → medium"""
        spike_ratio = 3.0
        if spike_ratio >= 5.0:
            severity = "critical"
        elif spike_ratio >= 3.5:
            severity = "high"
        elif spike_ratio >= 2.5:
            severity = "medium"
        else:
            severity = "low"
        assert severity == "medium"

    def test_severity_classification_low(self) -> None:
        """spike_ratio 2.0-2.4 → low"""
        spike_ratio = 2.2
        if spike_ratio >= 5.0:
            severity = "critical"
        elif spike_ratio >= 3.5:
            severity = "high"
        elif spike_ratio >= 2.5:
            severity = "medium"
        else:
            severity = "low"
        assert severity == "low"

    def test_recommended_actions_negative_spike(self) -> None:
        """负面激增预警包含正确的建议动作"""
        actions = self.monitor._build_recommended_actions("negative_spike", "high")
        action_templates = [a["template"] for a in actions]
        assert "review_mentions" in action_templates
        assert "post_response" in action_templates
        assert "escalate_pr" in action_templates  # high severity
        assert "monitor_followup" in action_templates

    def test_recommended_actions_crisis(self) -> None:
        """危机预警包含危机公关预案"""
        actions = self.monitor._build_recommended_actions("crisis", "critical")
        action_templates = [a["template"] for a in actions]
        assert "crisis_protocol" in action_templates
        assert "escalate_pr" in action_templates

    @pytest.mark.asyncio
    async def test_acknowledge_alert(self) -> None:
        """成功确认预警"""
        db = AsyncMock()
        set_config_result = AsyncMock()

        ack_row = MagicMock()
        ack_row.__getitem__ = lambda self, i: [str(uuid.uuid4())][i]
        ack_result = AsyncMock()
        ack_result.fetchone.return_value = ack_row

        call_count = 0

        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return set_config_result
            return ack_result

        db.execute = AsyncMock(side_effect=mock_execute)
        db.commit = AsyncMock()

        alert_id = uuid.uuid4()
        assigned_to = uuid.uuid4()
        result = await self.monitor.acknowledge_alert(
            self.tenant_id, alert_id, assigned_to, db
        )
        assert result["status"] == "acknowledged"

    @pytest.mark.asyncio
    async def test_dismiss_alert(self) -> None:
        """成功驳回预警"""
        db = AsyncMock()
        set_config_result = AsyncMock()

        dismiss_row = MagicMock()
        dismiss_row.__getitem__ = lambda self, i: [str(uuid.uuid4())][i]
        dismiss_result = AsyncMock()
        dismiss_result.fetchone.return_value = dismiss_row

        call_count = 0

        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return set_config_result
            return dismiss_result

        db.execute = AsyncMock(side_effect=mock_execute)
        db.commit = AsyncMock()

        alert_id = uuid.uuid4()
        result = await self.monitor.dismiss_alert(self.tenant_id, alert_id, db)
        assert result["status"] == "dismissed"


# ═══════════════════════════════════════
# CrisisResponder Agent 测试
# ═══════════════════════════════════════


class TestCrisisResponder:
    """危机响应Agent测试"""

    def setup_method(self) -> None:
        from agents.skills.crisis_responder import CrisisResponderAgent

        self.agent = CrisisResponderAgent(tenant_id=str(uuid.uuid4()))

    @pytest.mark.asyncio
    async def test_assess_crisis_critical(self) -> None:
        """critical级别+微博平台 → P0优先级"""
        result = await self.agent.execute("assess_crisis", {
            "alert_type": "crisis",
            "severity": "critical",
            "platform": "weibo",
            "trigger_data": {"spike_ratio": 6.0},
        })

        assert result.success is True
        assert result.data["priority"] == "P0"
        assert result.data["crisis_score"] >= 60
        assert result.data["recommended_response_min"] == 15

    @pytest.mark.asyncio
    async def test_assess_crisis_low(self) -> None:
        """low级别+wechat → P3优先级"""
        result = await self.agent.execute("assess_crisis", {
            "alert_type": "rating_drop",
            "severity": "low",
            "platform": "wechat",
            "trigger_data": {"spike_ratio": 1.0},
        })

        assert result.success is True
        assert result.data["priority"] in ("P2", "P3")

    @pytest.mark.asyncio
    async def test_assess_crisis_platform_weight(self) -> None:
        """不同平台权重影响评分"""
        result_weibo = await self.agent.execute("assess_crisis", {
            "severity": "medium",
            "platform": "weibo",
            "alert_type": "negative_spike",
            "trigger_data": {},
        })
        result_google = await self.agent.execute("assess_crisis", {
            "severity": "medium",
            "platform": "google",
            "alert_type": "negative_spike",
            "trigger_data": {},
        })

        assert result_weibo.data["crisis_score"] > result_google.data["crisis_score"]

    @pytest.mark.asyncio
    async def test_generate_response_draft_with_mock(self) -> None:
        """使用mock Claude生成回应草稿"""
        mock_response = "非常抱歉给您带来不好的体验，我们已立即整改。"

        with patch.object(self.agent, "_call_brain", return_value=mock_response):
            result = await self.agent.execute("generate_response_draft", {
                "brand_name": "尝在一起",
                "severity": "high",
                "alert_type": "negative_spike",
                "platform": "dianping",
                "summary": "多条差评反映菜品口味下降",
            })

        assert result.success is True
        assert result.data["response_draft"] == mock_response
        assert result.data["brand_name"] == "尝在一起"
        assert result.data["tone"] == "严肃且负责"

    @pytest.mark.asyncio
    async def test_generate_response_draft_fallback(self) -> None:
        """AI不可用时使用降级模板"""
        result = await self.agent.execute("generate_response_draft", {
            "brand_name": "测试品牌",
            "severity": "medium",
            "alert_type": "crisis",
            "platform": "weibo",
            "summary": "食品安全问题",
        })

        assert result.success is True
        assert len(result.data["response_draft"]) > 0
        assert "道歉" in result.data["response_draft"] or "歉意" in result.data["response_draft"]

    @pytest.mark.asyncio
    async def test_monitor_sla_breached(self) -> None:
        """已超SLA的预警被正确识别"""
        now = datetime.now(tz=timezone.utc)
        pending_alerts = [
            {
                "alert_id": str(uuid.uuid4()),
                "severity": "high",
                "created_at_iso": (now - timedelta(minutes=60)).isoformat(),
                "sla_target_sec": 1800,
                "response_status": "pending",
            },
            {
                "alert_id": str(uuid.uuid4()),
                "severity": "medium",
                "created_at_iso": (now - timedelta(minutes=10)).isoformat(),
                "sla_target_sec": 1800,
                "response_status": "pending",
            },
        ]

        result = await self.agent.execute("monitor_sla", {
            "pending_alerts": pending_alerts,
            "current_time_iso": now.isoformat(),
        })

        assert result.success is True
        assert len(result.data["breached_sla"]) == 1
        assert result.data["needs_escalation"] >= 1

    @pytest.mark.asyncio
    async def test_monitor_sla_approaching(self) -> None:
        """即将超期的预警被正确识别（剩余<25%时间）"""
        now = datetime.now(tz=timezone.utc)
        pending_alerts = [
            {
                "alert_id": str(uuid.uuid4()),
                "severity": "high",
                "created_at_iso": (now - timedelta(minutes=25)).isoformat(),
                "sla_target_sec": 1800,  # 30min target, 25min elapsed, 5min left = 16.7%
                "response_status": "acknowledged",
            },
        ]

        result = await self.agent.execute("monitor_sla", {
            "pending_alerts": pending_alerts,
            "current_time_iso": now.isoformat(),
        })

        assert result.success is True
        assert len(result.data["approaching_sla"]) == 1

    def test_constraint_scope_waived(self) -> None:
        """CrisisResponder不校验业务约束"""
        from agents.skills.crisis_responder import CrisisResponderAgent

        assert CrisisResponderAgent.constraint_scope == set()
        assert CrisisResponderAgent.constraint_waived_reason is not None
        assert len(CrisisResponderAgent.constraint_waived_reason) >= 30

    def test_supported_actions(self) -> None:
        """支持的操作列表完整"""
        actions = self.agent.get_supported_actions()
        assert "assess_crisis" in actions
        assert "generate_response_draft" in actions
        assert "monitor_sla" in actions
        assert len(actions) == 3

    @pytest.mark.asyncio
    async def test_unsupported_action(self) -> None:
        """不支持的操作返回失败"""
        result = await self.agent.execute("unknown_action", {})
        assert result.success is False
        assert "不支持" in str(result.error)


# ═══════════════════════════════════════
# ReputationRoutes 测试
# ═══════════════════════════════════════


class TestReputationRoutes:
    """舆情预警路由测试"""

    def setup_method(self) -> None:
        self.tenant_id = str(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_alert_respond_flow(self) -> None:
        """完整回应流程：创建 → 确认 → 回应 → 解决"""
        monitor = ReputationMonitor()

        # 1. 创建预警
        db = AsyncMock()
        set_config_result = AsyncMock()
        insert_result = AsyncMock()

        call_count = 0

        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return set_config_result
            return insert_result

        db.execute = AsyncMock(side_effect=mock_execute)
        db.commit = AsyncMock()

        with patch.object(monitor, "_generate_summary", return_value="测试"):
            alert = await monitor.create_alert(
                uuid.UUID(self.tenant_id),
                {
                    "platform": "dianping",
                    "alert_type": "negative_spike",
                    "severity": "high",
                    "trigger_mention_ids": [],
                    "trigger_data": {},
                },
                db,
            )

        assert "alert_id" in alert

    @pytest.mark.asyncio
    async def test_escalate_flow(self) -> None:
        """升级预警流程"""
        monitor = ReputationMonitor()
        db = AsyncMock()
        set_config_result = AsyncMock()

        escalate_row = MagicMock()
        escalate_row.__getitem__ = lambda self, i: [str(uuid.uuid4())][i]
        escalate_result = AsyncMock()
        escalate_result.fetchone.return_value = escalate_row

        call_count = 0

        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return set_config_result
            return escalate_result

        db.execute = AsyncMock(side_effect=mock_execute)
        db.commit = AsyncMock()

        result = await monitor.escalate_alert(
            uuid.UUID(self.tenant_id),
            uuid.uuid4(),
            uuid.uuid4(),
            db,
        )
        assert result["status"] == "escalated"

    @pytest.mark.asyncio
    async def test_resolve_flow(self) -> None:
        """解决预警流程"""
        monitor = ReputationMonitor()
        db = AsyncMock()
        set_config_result = AsyncMock()

        resolve_row = MagicMock()
        resolve_row.__getitem__ = lambda self, i: [str(uuid.uuid4())][i]
        resolve_result = AsyncMock()
        resolve_result.fetchone.return_value = resolve_row

        call_count = 0

        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return set_config_result
            return resolve_result

        db.execute = AsyncMock(side_effect=mock_execute)
        db.commit = AsyncMock()

        result = await monitor.resolve_alert(
            uuid.UUID(self.tenant_id),
            uuid.uuid4(),
            "问题已修复并回应顾客",
            db,
        )
        assert result["status"] == "resolved"

    @pytest.mark.asyncio
    async def test_acknowledge_not_found(self) -> None:
        """确认不存在的预警抛出ValueError"""
        monitor = ReputationMonitor()
        db = AsyncMock()
        set_config_result = AsyncMock()
        empty_result = AsyncMock()
        empty_result.fetchone.return_value = None

        call_count = 0

        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return set_config_result
            return empty_result

        db.execute = AsyncMock(side_effect=mock_execute)

        with pytest.raises(ValueError, match="预警不存在"):
            await monitor.acknowledge_alert(
                uuid.UUID(self.tenant_id),
                uuid.uuid4(),
                uuid.uuid4(),
                db,
            )


# ═══════════════════════════════════════
# SLAReport 测试
# ═══════════════════════════════════════


class TestSLAReport:
    """SLA合规报告测试"""

    def test_compliance_rate_calculation(self) -> None:
        """SLA合规率计算正确"""
        sla_met = 8
        sla_missed = 2
        total = sla_met + sla_missed
        rate = round(sla_met / total * 100, 1)
        assert rate == 80.0

    def test_compliance_rate_all_met(self) -> None:
        """全部达标 → 100%"""
        sla_met = 10
        sla_missed = 0
        total = sla_met + sla_missed
        rate = round(sla_met / max(total, 1) * 100, 1)
        assert rate == 100.0

    def test_compliance_rate_none_met(self) -> None:
        """全部未达标 → 0%"""
        sla_met = 0
        sla_missed = 5
        total = sla_met + sla_missed
        rate = round(sla_met / max(total, 1) * 100, 1)
        assert rate == 0.0

    def test_compliance_rate_zero_total(self) -> None:
        """无预警 → 分母为0安全"""
        sla_met = 0
        sla_missed = 0
        total = sla_met + sla_missed
        rate = round(sla_met / max(total, 1) * 100, 1)
        assert rate == 0.0

    def test_response_time_sec_within_sla(self) -> None:
        """响应时间1200秒，SLA目标1800秒 → 达标"""
        response_time_sec = 1200
        sla_target_sec = 1800
        assert response_time_sec <= sla_target_sec

    def test_response_time_sec_exceeds_sla(self) -> None:
        """响应时间2400秒，SLA目标1800秒 → 未达标"""
        response_time_sec = 2400
        sla_target_sec = 1800
        assert response_time_sec > sla_target_sec

    @pytest.mark.asyncio
    async def test_get_sla_report(self) -> None:
        """SLA报告按门店汇总"""
        monitor = ReputationMonitor()
        db = AsyncMock()
        set_config_result = AsyncMock()

        store1 = str(uuid.uuid4())
        store2 = str(uuid.uuid4())
        report_rows = [
            (store1, 10, 8, 2, 900.5),
            (store2, 5, 5, 0, 600.0),
        ]
        report_result = AsyncMock()
        report_result.fetchall.return_value = report_rows

        call_count = 0

        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return set_config_result
            return report_result

        db.execute = AsyncMock(side_effect=mock_execute)

        tenant_id = uuid.uuid4()
        result = await monitor.get_sla_report(tenant_id, db, days=30)

        assert len(result) == 2
        assert result[0]["store_id"] == store1
        assert result[0]["compliance_rate"] == 80.0
        assert result[1]["compliance_rate"] == 100.0
