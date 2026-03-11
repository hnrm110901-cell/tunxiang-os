"""
私域运营Agent单元测试
覆盖：RFM分层、信号感知、旅程引擎、四象限、差评处理、execute分发
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
# base_agent lives in apps/api-gateway/src/core
sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent.parent.parent.parent / "apps" / "api-gateway" / "src" / "core"),
)

import pytest
from agent import (
    PrivateDomainAgent,
    RFMLevel,
    StoreQuadrant,
    SignalType,
    JourneyType,
    JourneyStatus,
    REACTIVATION_STEPS,
    _REACTIVATION_STEP_DELAYS,
    NEW_CUSTOMER_JOURNEY_STEPS,
    COMPETITOR_DEFENSE_PLAYBOOK,
)


@pytest.fixture
def agent():
    return PrivateDomainAgent(store_id="S001")


# ─────────────────────────── RFM 分层 ───────────────────────────

class TestClassifyRFM:
    def test_s1_high_value(self, agent):
        assert agent._classify_rfm(recency_days=5, frequency=3, monetary=15000) == RFMLevel.S1.value

    def test_s2_potential(self, agent):
        assert agent._classify_rfm(recency_days=20, frequency=1, monetary=5000) == RFMLevel.S2.value

    def test_s3_dormant(self, agent):
        assert agent._classify_rfm(recency_days=45, frequency=0, monetary=0) == RFMLevel.S3.value

    def test_s4_churn_warning(self, agent):
        assert agent._classify_rfm(recency_days=75, frequency=0, monetary=0) == RFMLevel.S4.value

    def test_s5_churned(self, agent):
        assert agent._classify_rfm(recency_days=100, frequency=0, monetary=0) == RFMLevel.S5.value

    def test_boundary_s1_exact_threshold(self, agent):
        # 恰好满足 S1 条件
        result = agent._classify_rfm(
            recency_days=30,
            frequency=agent.s1_min_frequency,
            monetary=agent.s1_min_monetary,
        )
        assert result == RFMLevel.S1.value

    def test_boundary_s3_day60(self, agent):
        assert agent._classify_rfm(recency_days=60, frequency=0, monetary=0) == RFMLevel.S3.value

    def test_boundary_s4_day90(self, agent):
        assert agent._classify_rfm(recency_days=90, frequency=0, monetary=0) == RFMLevel.S4.value


# ─────────────────────────── 流失风险分 ───────────────────────────

class TestChurnRisk:
    def test_recent_active_low_risk(self, agent):
        score = agent._calculate_churn_risk(recency_days=3, frequency=5)
        assert score < 0.3

    def test_long_absent_high_risk(self, agent):
        score = agent._calculate_churn_risk(recency_days=90, frequency=0)
        assert score >= 0.7

    def test_score_range(self, agent):
        for r in range(0, 120, 10):
            for f in range(0, 10, 2):
                score = agent._calculate_churn_risk(r, f)
                assert 0.0 <= score <= 1.0

    def test_higher_frequency_lowers_risk(self, agent):
        low_freq = agent._calculate_churn_risk(recency_days=30, frequency=0)
        high_freq = agent._calculate_churn_risk(recency_days=30, frequency=8)
        assert high_freq < low_freq


# ─────────────────────────── 动态标签 ───────────────────────────

class TestDynamicTags:
    def test_high_spend_tag(self, agent):
        c = {"monetary": agent.s1_min_monetary * 3, "frequency": 1, "recency_days": 5, "avg_order_time": 12}
        tags = agent._infer_dynamic_tags(c)
        assert "高消费" in tags

    def test_high_frequency_tag(self, agent):
        c = {"monetary": 1000, "frequency": 5, "recency_days": 5, "avg_order_time": 12}
        tags = agent._infer_dynamic_tags(c)
        assert "高频" in tags

    def test_recent_active_tag(self, agent):
        c = {"monetary": 1000, "frequency": 1, "recency_days": 3, "avg_order_time": 12}
        tags = agent._infer_dynamic_tags(c)
        assert "近期活跃" in tags

    def test_lunch_preference_tag(self, agent):
        c = {"monetary": 1000, "frequency": 1, "recency_days": 20, "avg_order_time": 12}
        tags = agent._infer_dynamic_tags(c)
        assert "午餐偏好" in tags

    def test_dinner_preference_tag(self, agent):
        c = {"monetary": 1000, "frequency": 1, "recency_days": 20, "avg_order_time": 19}
        tags = agent._infer_dynamic_tags(c)
        assert "晚餐偏好" in tags

    def test_default_tag_when_no_match(self, agent):
        c = {"monetary": 500, "frequency": 0, "recency_days": 50, "avg_order_time": 9}
        tags = agent._infer_dynamic_tags(c)
        assert tags == ["普通用户"]


# ─────────────────────────── 四象限 ───────────────────────────

class TestStoreQuadrant:
    @pytest.mark.asyncio
    async def test_benchmark_high_penetration_low_competition(self, agent):
        result = await agent.calculate_store_quadrant(
            competition_density=2.0,
            member_count=400,
            estimated_population=1000,
        )
        assert result["quadrant"] == StoreQuadrant.BENCHMARK.value
        assert "strategy" in result

    @pytest.mark.asyncio
    async def test_defensive_high_penetration_high_competition(self, agent):
        result = await agent.calculate_store_quadrant(
            competition_density=8.0,
            member_count=400,
            estimated_population=1000,
        )
        assert result["quadrant"] == StoreQuadrant.DEFENSIVE.value

    @pytest.mark.asyncio
    async def test_potential_low_penetration_low_competition(self, agent):
        result = await agent.calculate_store_quadrant(
            competition_density=2.0,
            member_count=50,
            estimated_population=1000,
        )
        assert result["quadrant"] == StoreQuadrant.POTENTIAL.value

    @pytest.mark.asyncio
    async def test_breakthrough_low_penetration_high_competition(self, agent):
        result = await agent.calculate_store_quadrant(
            competition_density=8.0,
            member_count=50,
            estimated_population=1000,
        )
        assert result["quadrant"] == StoreQuadrant.BREAKTHROUGH.value

    @pytest.mark.asyncio
    async def test_penetration_rate_calculated_correctly(self, agent):
        result = await agent.calculate_store_quadrant(
            competition_density=2.0,
            member_count=300,
            estimated_population=1000,
        )
        assert result["member_penetration"] == pytest.approx(0.3, abs=0.001)

    @pytest.mark.asyncio
    async def test_zero_population_no_division_error(self, agent):
        result = await agent.calculate_store_quadrant(
            competition_density=0.0,
            member_count=0,
            estimated_population=0,
        )
        assert "quadrant" in result


# ─────────────────────────── 旅程引擎 ───────────────────────────

class TestJourneyEngine:
    @pytest.mark.asyncio
    async def test_trigger_new_customer_journey(self, agent):
        record = await agent.trigger_journey(JourneyType.NEW_CUSTOMER.value, "C001")
        assert record["journey_type"] == JourneyType.NEW_CUSTOMER.value
        assert record["customer_id"] == "C001"
        assert record["store_id"] == "S001"
        assert record["status"] == JourneyStatus.RUNNING.value
        assert record["total_steps"] == 4
        assert record["current_step"] == 1
        assert record["journey_id"].startswith("JRN_NEW_CUSTOMER_C001")

    @pytest.mark.asyncio
    async def test_trigger_vip_retention_journey(self, agent):
        record = await agent.trigger_journey(JourneyType.VIP_RETENTION.value, "C002")
        assert record["total_steps"] == 4

    @pytest.mark.asyncio
    async def test_trigger_reactivation_journey(self, agent):
        record = await agent.trigger_journey(JourneyType.REACTIVATION.value, "C003")
        assert record["total_steps"] == 3

    @pytest.mark.asyncio
    async def test_trigger_review_repair_journey(self, agent):
        record = await agent.trigger_journey(JourneyType.REVIEW_REPAIR.value, "C004")
        assert record["total_steps"] == 4

    @pytest.mark.asyncio
    async def test_get_journeys_all(self, agent):
        # 无 DB 配置时返回空列表（结构测试）
        journeys = await agent.get_journeys()
        assert isinstance(journeys, list)

    @pytest.mark.asyncio
    async def test_get_journeys_filter_by_status(self, agent):
        running = await agent.get_journeys(status=JourneyStatus.RUNNING.value)
        for j in running:
            assert j["status"] == JourneyStatus.RUNNING.value

    @pytest.mark.asyncio
    async def test_get_journeys_completed_filter(self, agent):
        completed = await agent.get_journeys(status=JourneyStatus.COMPLETED.value)
        for j in completed:
            assert j["status"] == JourneyStatus.COMPLETED.value


# ─────────────────────────── 信号感知 ───────────────────────────

class TestSignalDetection:
    @pytest.mark.asyncio
    async def test_detect_signals_returns_list(self, agent):
        signals = await agent.detect_signals()
        assert isinstance(signals, list)
        assert len(signals) <= 20

    @pytest.mark.asyncio
    async def test_signals_have_required_fields(self, agent):
        signals = await agent.detect_signals()
        for s in signals:
            assert "signal_id" in s
            assert "signal_type" in s
            assert "store_id" in s
            assert s["store_id"] == "S001"

    @pytest.mark.asyncio
    async def test_churn_risk_signals_detected(self, agent):
        signals = await agent.detect_signals()
        types = {s["signal_type"] for s in signals}
        assert SignalType.CHURN_RISK.value in types

    @pytest.mark.asyncio
    async def test_get_signals_filter_by_type(self, agent):
        signals = await agent.get_signals(signal_type=SignalType.CHURN_RISK.value)
        for s in signals:
            assert s["signal_type"] == SignalType.CHURN_RISK.value

    @pytest.mark.asyncio
    async def test_get_signals_limit(self, agent):
        signals = await agent.get_signals(limit=5)
        assert len(signals) <= 5


# ─────────────────────────── RFM 分析 ───────────────────────────

class TestAnalyzeRFM:
    @pytest.mark.asyncio
    async def test_analyze_rfm_returns_segments(self, agent):
        segments = await agent.analyze_rfm(30)
        assert len(segments) > 0

    @pytest.mark.asyncio
    async def test_segments_have_valid_rfm_levels(self, agent):
        valid_levels = {l.value for l in RFMLevel}
        segments = await agent.analyze_rfm(30)
        for s in segments:
            assert s["rfm_level"] in valid_levels

    @pytest.mark.asyncio
    async def test_segments_risk_score_in_range(self, agent):
        segments = await agent.analyze_rfm(30)
        for s in segments:
            assert 0.0 <= s["risk_score"] <= 1.0

    @pytest.mark.asyncio
    async def test_get_churn_risks_subset_of_rfm(self, agent):
        all_segments = await agent.analyze_rfm(30)
        churn_risks = await agent.get_churn_risks()
        churn_ids = {s["customer_id"] for s in churn_risks}
        all_ids = {s["customer_id"] for s in all_segments}
        assert churn_ids.issubset(all_ids)

    @pytest.mark.asyncio
    async def test_churn_risks_are_s3_s4_s5_or_high_risk(self, agent):
        churn_risks = await agent.get_churn_risks()
        for s in churn_risks:
            assert s["rfm_level"] in ("S3", "S4", "S5") or s["risk_score"] >= 0.6


# ─────────────────────────── 差评处理 ───────────────────────────

class TestBadReviewProcessing:
    @pytest.mark.asyncio
    async def test_process_bad_review_with_customer(self, agent):
        result = await agent.process_bad_review(
            review_id="REV001",
            customer_id="C001",
            rating=1,
            content="菜品太咸",
        )
        assert result["handled"] is True
        assert result["journey_triggered"] is True
        assert result["journey_id"] is not None
        assert result["compensation_issued"] is True  # rating <= 2

    @pytest.mark.asyncio
    async def test_process_bad_review_without_customer(self, agent):
        result = await agent.process_bad_review(
            review_id="REV002",
            customer_id=None,
            rating=2,
            content="服务慢",
        )
        assert result["handled"] is True
        assert result["journey_triggered"] is False

    @pytest.mark.asyncio
    async def test_process_review_rating_3_no_compensation(self, agent):
        result = await agent.process_bad_review(
            review_id="REV003",
            customer_id="C002",
            rating=3,
            content="一般",
        )
        assert result["compensation_issued"] is False


# ─────────────────────────── execute 分发 ───────────────────────────

class TestExecuteDispatch:
    @pytest.mark.asyncio
    async def test_execute_get_dashboard(self, agent):
        resp = await agent.execute("get_dashboard", {})
        assert resp.success is True
        assert resp.data is not None
        assert "store_id" in resp.data

    @pytest.mark.asyncio
    async def test_execute_analyze_rfm(self, agent):
        resp = await agent.execute("analyze_rfm", {"days": 30})
        assert resp.success is True
        assert isinstance(resp.data, list)

    @pytest.mark.asyncio
    async def test_execute_detect_signals(self, agent):
        resp = await agent.execute("detect_signals", {})
        assert resp.success is True

    @pytest.mark.asyncio
    async def test_execute_calculate_store_quadrant(self, agent):
        resp = await agent.execute("calculate_store_quadrant", {
            "competition_density": 3.0,
            "member_count": 200,
            "estimated_population": 800,
        })
        assert resp.success is True
        assert "quadrant" in resp.data

    @pytest.mark.asyncio
    async def test_execute_trigger_journey(self, agent):
        resp = await agent.execute("trigger_journey", {
            "journey_type": JourneyType.NEW_CUSTOMER.value,
            "customer_id": "C999",
        })
        assert resp.success is True

    @pytest.mark.asyncio
    async def test_execute_get_churn_risks(self, agent):
        resp = await agent.execute("get_churn_risks", {})
        assert resp.success is True
        assert isinstance(resp.data, list)

    @pytest.mark.asyncio
    async def test_execute_unsupported_action(self, agent):
        resp = await agent.execute("nonexistent_action", {})
        assert resp.success is False
        assert resp.error is not None

    @pytest.mark.asyncio
    async def test_execute_process_bad_review(self, agent):
        resp = await agent.execute("process_bad_review", {
            "review_id": "REV_TEST",
            "customer_id": "C001",
            "rating": 1,
            "content": "测试差评",
        })
        assert resp.success is True
        assert resp.data["handled"] is True


# ─────────────────────────── 看板 ───────────────────────────

class TestDashboard:
    @pytest.mark.asyncio
    async def test_dashboard_fields(self, agent):
        dashboard = await agent.get_dashboard()
        assert dashboard["store_id"] == "S001"
        assert "total_members" in dashboard
        assert "active_members" in dashboard
        assert "rfm_distribution" in dashboard
        assert "pending_signals" in dashboard
        assert "running_journeys" in dashboard
        assert "monthly_repurchase_rate" in dashboard
        assert "churn_risk_count" in dashboard
        assert "bad_review_count" in dashboard
        assert "store_quadrant" in dashboard
        assert "roi_estimate" in dashboard

    @pytest.mark.asyncio
    async def test_dashboard_repurchase_rate_range(self, agent):
        dashboard = await agent.get_dashboard()
        assert 0.0 <= dashboard["monthly_repurchase_rate"] <= 1.0

    @pytest.mark.asyncio
    async def test_dashboard_active_lte_total(self, agent):
        dashboard = await agent.get_dashboard()
        assert dashboard["active_members"] <= dashboard["total_members"]

    @pytest.mark.asyncio
    async def test_dashboard_rfm_distribution_sums_to_total(self, agent):
        dashboard = await agent.get_dashboard()
        dist_sum = sum(dashboard["rfm_distribution"].values())
        assert dist_sum == dashboard["total_members"]


# ── A2 损失厌恶唤醒旅程测试 ───────────────────────────────────────────────────

class TestReactivationSteps:
    """方向六：损失厌恶分级触达策略——三步框架验证。"""

    def test_three_steps_defined(self):
        assert len(REACTIVATION_STEPS) == 3

    def test_steps_in_ascending_order(self):
        for i, step in enumerate(REACTIVATION_STEPS, start=1):
            assert step["step"] == i

    def test_each_step_has_required_fields(self):
        required = {"step", "timing_days", "framework", "label", "message_principle",
                    "template", "psychology"}
        for step in REACTIVATION_STEPS:
            assert required <= set(step.keys()), f"Step {step['step']} 缺少字段"

    def test_step3_has_no_response_action_agent_exit(self):
        step3 = REACTIVATION_STEPS[2]
        assert step3["no_response_action"] == "agent_exit"

    def test_step_delays_ascending(self):
        delays = [_REACTIVATION_STEP_DELAYS[i] for i in (1, 2, 3)]
        assert delays == sorted(delays), "步骤延迟天数必须递增"

    def test_step1_uses_ownership_framework(self):
        assert REACTIVATION_STEPS[0]["framework"] == "ownership_effect"

    def test_step2_uses_social_proof_framework(self):
        assert REACTIVATION_STEPS[1]["framework"] == "social_proof"

    def test_step3_uses_minimum_action_framework(self):
        assert REACTIVATION_STEPS[2]["framework"] == "minimum_action"

    def test_step1_template_contains_benefit_placeholder(self):
        tpl = REACTIVATION_STEPS[0]["template"]
        assert "{benefit_name}" in tpl
        assert "{expire_days}" in tpl

    def test_step3_template_minimal(self):
        """Step3 模板要极简（只要一个字），不包含折扣词。"""
        tpl = REACTIVATION_STEPS[2]["template"]
        assert "折" not in tpl
        assert "%" not in tpl

    @pytest.mark.asyncio
    async def test_trigger_reactivation_uses_step1_delay(self, agent):
        """触发沉睡唤醒旅程时，next_action_at 按 step1 延迟天数计算。"""
        from datetime import datetime, timedelta
        record = await agent.trigger_journey(JourneyType.REACTIVATION.value, "C_REACT")
        assert record["status"] == JourneyStatus.RUNNING.value
        assert record["current_step"] == 1
        expected_delay = _REACTIVATION_STEP_DELAYS[1]
        started = datetime.fromisoformat(record["started_at"])
        next_at = datetime.fromisoformat(record["next_action_at"])
        actual_days = (next_at - started).days
        assert actual_days == expected_delay

    @pytest.mark.asyncio
    async def test_advance_reactivation_responded_moves_to_step2(self, agent):
        """有响应时旅程推进到 step 2，next_action_at 约为 now + delay2 天。"""
        from datetime import datetime, timedelta, timezone
        record = await agent.trigger_journey(JourneyType.REACTIVATION.value, "C_ADV1")
        before_advance = datetime.utcnow()
        advanced = await agent.advance_reactivation_journey(record, responded=True)
        assert advanced["current_step"] == 2
        assert advanced["status"] == JourneyStatus.RUNNING.value
        delay2 = _REACTIVATION_STEP_DELAYS[2]
        next_at = datetime.fromisoformat(advanced["next_action_at"])
        expected = before_advance + timedelta(days=delay2)
        # 允许 2 秒的执行误差
        assert abs((next_at - expected).total_seconds()) < 2

    @pytest.mark.asyncio
    async def test_advance_reactivation_no_response_step3_exits(self, agent):
        """step3 无响应时旅程进入 agent_exit，停止自动触达。"""
        record = await agent.trigger_journey(JourneyType.REACTIVATION.value, "C_EXIT")
        # 强制推进到 step 3
        record["current_step"] = 3
        exited = await agent.advance_reactivation_journey(record, responded=False)
        assert exited["status"] == JourneyStatus.AGENT_EXIT.value
        assert exited["completed_at"] is not None

    @pytest.mark.asyncio
    async def test_advance_reactivation_no_response_step1_continues(self, agent):
        """step1/2 无响应时旅程继续推进（不提前 exit）。"""
        record = await agent.trigger_journey(JourneyType.REACTIVATION.value, "C_CONT")
        # step1 无响应
        advanced = await agent.advance_reactivation_journey(record, responded=False)
        assert advanced["status"] == JourneyStatus.RUNNING.value
        assert advanced["current_step"] == 2


# ── A3 差评四阶修复协议测试 ───────────────────────────────────────────────────

class TestBadReviewRepairProtocol:
    """方向四：差评四阶心理修复协议——评分路由与字段验证。"""

    @pytest.mark.asyncio
    async def test_rating1_window_is_15min(self, agent):
        result = await agent.process_bad_review("R1", "C1", rating=1, content="很差")
        assert result["response_window_minutes"] == 15

    @pytest.mark.asyncio
    async def test_rating2_window_is_30min(self, agent):
        result = await agent.process_bad_review("R2", "C2", rating=2, content="一般")
        assert result["response_window_minutes"] == 30

    @pytest.mark.asyncio
    async def test_rating3_window_is_30min(self, agent):
        result = await agent.process_bad_review("R3", "C3", rating=3, content="不好")
        assert result["response_window_minutes"] == 30

    @pytest.mark.asyncio
    async def test_rating1_has_4_steps(self, agent):
        result = await agent.process_bad_review("R4", "C4", rating=1, content="极差")
        assert result["total_repair_steps"] == 4

    @pytest.mark.asyncio
    async def test_rating2_has_2_steps(self, agent):
        result = await agent.process_bad_review("R5", "C5", rating=2, content="失望")
        assert result["total_repair_steps"] == 2

    @pytest.mark.asyncio
    async def test_rating1_severity_is_critical(self, agent):
        result = await agent.process_bad_review("R6", None, rating=1, content="")
        assert result["severity"] == "critical"

    @pytest.mark.asyncio
    async def test_rating3_severity_is_warning(self, agent):
        result = await agent.process_bad_review("R7", None, rating=3, content="")
        assert result["severity"] == "warning"

    @pytest.mark.asyncio
    async def test_result_contains_step_sequence(self, agent):
        result = await agent.process_bad_review("R8", None, rating=1, content="")
        steps = result["step_sequence"]
        assert len(steps) == 4
        assert all("step" in s and "timing" in s and "channel" in s for s in steps)

    @pytest.mark.asyncio
    async def test_compensation_type_dish_voucher_when_favorite_dish(self, agent):
        """有最爱菜品时补偿类型应为 dish_voucher（个性化互惠 > 通用折扣）。"""
        result = await agent.process_bad_review(
            "R9", "C9", rating=2, content="",
            customer_history={"favorite_dish": "清蒸鲈鱼", "monetary": 3000},
        )
        assert result["compensation_type"] == "dish_voucher"

    @pytest.mark.asyncio
    async def test_compensation_type_credit_when_no_history(self, agent):
        result = await agent.process_bad_review(
            "R10", "C10", rating=2, content="",
            customer_history=None,
        )
        assert result["compensation_type"] == "credit"

    @pytest.mark.asyncio
    async def test_journey_triggered_when_customer_id_provided(self, agent):
        result = await agent.process_bad_review("R11", "C11", rating=1, content="")
        assert result["journey_triggered"] is True
        assert result["journey_id"] is not None

    @pytest.mark.asyncio
    async def test_no_journey_when_anonymous(self, agent):
        result = await agent.process_bad_review("R12", None, rating=2, content="")
        assert result["journey_triggered"] is False
        assert result["journey_id"] is None

    @pytest.mark.asyncio
    async def test_first_step_channel_is_store_manager_for_rating1(self, agent):
        """rating=1 的第一步必须是店长真人渠道（非机器人模板）。"""
        result = await agent.process_bad_review("R13", None, rating=1, content="")
        first_step = result["step_sequence"][0]
        assert "store_manager" in first_step["channel"]

    @pytest.mark.asyncio
    async def test_handled_at_is_iso_format(self, agent):
        result = await agent.process_bad_review("R14", None, rating=3, content="")
        from datetime import datetime
        dt = datetime.fromisoformat(result["handled_at"])
        assert isinstance(dt, datetime)


# ── B2 Hook化新客激活旅程 ──────────────────────────────────────────────────────


class TestNewCustomerJourneySteps:
    """B2·方向二：Hook模型四步结构验证。"""

    def test_has_four_steps(self):
        assert len(NEW_CUSTOMER_JOURNEY_STEPS) == 4

    def test_step_numbers_are_1_to_4(self):
        numbers = [s["step"] for s in NEW_CUSTOMER_JOURNEY_STEPS]
        assert numbers == [1, 2, 3, 4]

    def test_each_step_has_required_fields(self):
        required = {"step", "timing", "mechanism", "channel", "action",
                    "message_principle", "psychology"}
        for s in NEW_CUSTOMER_JOURNEY_STEPS:
            missing = required - set(s.keys())
            assert not missing, f"Step {s['step']} 缺少字段: {missing}"

    def test_hook_mechanisms_cover_four_layers(self):
        mechanisms = [s["mechanism"] for s in NEW_CUSTOMER_JOURNEY_STEPS]
        assert any("触发" in m for m in mechanisms)
        assert any("行动" in m for m in mechanisms)
        assert any("奖励" in m for m in mechanisms)
        assert any("投入" in m for m in mechanisms)

    def test_step1_triggers_within_hours(self):
        """Step1 必须在消费后当天触达，不能延迟到次日。"""
        step1 = NEW_CUSTOMER_JOURNEY_STEPS[0]
        assert "小时" in step1["timing"] or "Day 0" in step1["timing"] or "2h" in step1["timing"]

    def test_step3_uses_variable_reward(self):
        """Step3 必须是变比率强化（多变奖励），不能是固定优惠。"""
        step3 = NEW_CUSTOMER_JOURNEY_STEPS[2]
        assert "多变" in step3["mechanism"] or "variable" in step3["action"]

    def test_step4_deepens_investment(self):
        step4 = NEW_CUSTOMER_JOURNEY_STEPS[3]
        assert "投入" in step4["mechanism"] or "investment" in step4["action"]

    @pytest.mark.asyncio
    async def test_trigger_new_customer_journey_uses_hook_steps(self, agent):
        journey = await agent.trigger_journey(JourneyType.NEW_CUSTOMER.value, "C001")
        assert journey["total_steps"] == len(NEW_CUSTOMER_JOURNEY_STEPS)

    @pytest.mark.asyncio
    async def test_trigger_new_customer_has_step_actions(self, agent):
        journey = await agent.trigger_journey(JourneyType.NEW_CUSTOMER.value, "C002")
        assert journey.get("step_actions") is not None
        assert len(journey["step_actions"]) == 4

    @pytest.mark.asyncio
    async def test_trigger_new_customer_next_action_is_immediate(self, agent):
        """Step1 在消费后2小时内，next_action_at 应与 started_at 同天（delay=0）。"""
        from datetime import datetime
        journey = await agent.trigger_journey(JourneyType.NEW_CUSTOMER.value, "C003")
        started = datetime.fromisoformat(journey["started_at"])
        next_at = datetime.fromisoformat(journey["next_action_at"])
        delta_days = (next_at - started).total_seconds() / 86400
        assert delta_days < 1  # 不超过1天延迟

    @pytest.mark.asyncio
    async def test_trigger_other_journey_no_step_actions(self, agent):
        """非 NEW_CUSTOMER 旅程不应有 step_actions。"""
        journey = await agent.trigger_journey(JourneyType.VIP_RETENTION.value, "C004")
        assert journey.get("step_actions") is None

    @pytest.mark.asyncio
    async def test_trigger_new_customer_step_actions_match_constant(self, agent):
        journey = await agent.trigger_journey(JourneyType.NEW_CUSTOMER.value, "C005")
        assert journey["step_actions"] == NEW_CUSTOMER_JOURNEY_STEPS


# ── B4 竞品防御信号检测 ────────────────────────────────────────────────────────


class TestCompetitorDefensePlaybook:
    """B4·方向九：竞品防御剧本结构验证。"""

    def test_has_two_scenarios(self):
        assert len(COMPETITOR_DEFENSE_PLAYBOOK) >= 2

    def test_each_scenario_has_required_fields(self):
        for scenario, pb in COMPETITOR_DEFENSE_PLAYBOOK.items():
            assert "wrong_action" in pb, f"{scenario} 缺少 wrong_action"
            assert "right_actions" in pb, f"{scenario} 缺少 right_actions"
            assert "forbidden" in pb, f"{scenario} 缺少 forbidden"

    def test_right_actions_non_empty(self):
        for scenario, pb in COMPETITOR_DEFENSE_PLAYBOOK.items():
            assert len(pb["right_actions"]) >= 1

    def test_new_opening_forbidden_mentions_competitor_mention(self):
        """《定位》：提及竞品等于帮对方打广告。"""
        pb = COMPETITOR_DEFENSE_PLAYBOOK["竞品新开业"]
        assert "竞争对手" in pb["forbidden"] or "竞品" in pb["forbidden"]

    def test_no_discount_in_right_actions(self):
        """正确防守策略中不应包含折扣手段。"""
        import re
        discount_pattern = re.compile(r"\d折|优惠券|打折|价格战")
        for scenario, pb in COMPETITOR_DEFENSE_PLAYBOOK.items():
            for action in pb["right_actions"]:
                msg = action.get("message_principle", "")
                assert not discount_pattern.search(msg), (
                    f"{scenario} 防守策略包含折扣: {msg}"
                )

    def test_each_right_action_has_target_and_psychology(self):
        for scenario, pb in COMPETITOR_DEFENSE_PLAYBOOK.items():
            for action in pb["right_actions"]:
                assert "target" in action, f"{scenario} action 缺少 target"
                assert "psychology" in action, f"{scenario} action 缺少 psychology"


class TestDetectCompetitorSignals:
    """B4：detect_competitor_signals 方法测试。"""

    @pytest.mark.asyncio
    async def test_no_signal_when_drop_below_15(self, agent):
        signals = await agent.detect_competitor_signals(revenue_drop_pct=10.0)
        assert signals == []

    @pytest.mark.asyncio
    async def test_signal_triggered_when_drop_above_15(self, agent):
        signals = await agent.detect_competitor_signals(revenue_drop_pct=20.0)
        assert len(signals) == 1
        assert signals[0]["signal_type"] == SignalType.COMPETITOR.value

    @pytest.mark.asyncio
    async def test_severity_medium_for_15_to_30_drop(self, agent):
        signals = await agent.detect_competitor_signals(revenue_drop_pct=20.0)
        assert signals[0]["severity"] == "medium"

    @pytest.mark.asyncio
    async def test_severity_high_for_drop_above_30(self, agent):
        signals = await agent.detect_competitor_signals(revenue_drop_pct=35.0)
        assert signals[0]["severity"] == "high"

    @pytest.mark.asyncio
    async def test_no_signal_on_holiday(self, agent):
        """节假日下降不算竞品信号。"""
        signals = await agent.detect_competitor_signals(
            revenue_drop_pct=25.0, is_holiday=True
        )
        assert signals == []

    @pytest.mark.asyncio
    async def test_signal_description_contains_drop_pct(self, agent):
        signals = await agent.detect_competitor_signals(revenue_drop_pct=22.5)
        assert "22.5" in signals[0]["description"]

    @pytest.mark.asyncio
    async def test_signal_store_id_matches_agent(self, agent):
        signals = await agent.detect_competitor_signals(revenue_drop_pct=20.0)
        assert signals[0]["store_id"] == agent.store_id

    @pytest.mark.asyncio
    async def test_signal_has_triggered_at(self, agent):
        signals = await agent.detect_competitor_signals(revenue_drop_pct=20.0)
        assert signals[0]["triggered_at"] is not None
