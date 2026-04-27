"""S1W2 流失预测评分模块测试"""

import uuid

TENANT_ID = str(uuid.uuid4())
CUSTOMER_ID = str(uuid.uuid4())


class TestChurnScorerUnit:
    """评分计算纯逻辑测试"""

    def test_recency_interpolation_7_days(self):
        """7天内到店 → 0分"""
        from services.churn_scorer import ChurnScorer

        scorer = ChurnScorer()
        assert scorer._interpolate_recency(5) == 0

    def test_recency_interpolation_30_days(self):
        """30天 → 30分"""
        from services.churn_scorer import ChurnScorer

        scorer = ChurnScorer()
        assert scorer._interpolate_recency(30) == 30

    def test_recency_interpolation_90_days(self):
        """90天 → 80分"""
        from services.churn_scorer import ChurnScorer

        scorer = ChurnScorer()
        assert scorer._interpolate_recency(90) == 80

    def test_classify_tier_warm(self):
        from services.churn_scorer import ChurnScorer

        assert ChurnScorer._classify_tier(45) == "warm"

    def test_classify_tier_urgent(self):
        from services.churn_scorer import ChurnScorer

        assert ChurnScorer._classify_tier(65) == "urgent"

    def test_classify_tier_critical(self):
        from services.churn_scorer import ChurnScorer

        assert ChurnScorer._classify_tier(85) == "critical"

    def test_calculate_score_active_customer(self):
        """活跃客户 → 低分"""
        from services.churn_scorer import ChurnScorer

        scorer = ChurnScorer()
        signals = {
            "days_since_last": 5,
            "frequency_trend": 0.2,
            "monetary_trend": 0.1,
            "cancel_rate": 0.0,
            "complaint_count": 0,
            "nps_score": None,
        }
        score = scorer._calculate_score(signals)
        assert score < 40, f"活跃客户评分应<40, got {score}"

    def test_calculate_score_churning_customer(self):
        """流失中客户 → 高分"""
        from services.churn_scorer import ChurnScorer

        scorer = ChurnScorer()
        signals = {
            "days_since_last": 90,
            "frequency_trend": -0.8,
            "monetary_trend": -0.6,
            "cancel_rate": 0.3,
            "complaint_count": 3,
            "nps_score": 4,
        }
        score = scorer._calculate_score(signals)
        assert score >= 70, f"流失客户评分应>=70, got {score}"

    def test_infer_root_cause_service(self):
        """投诉>=2 → service"""
        from services.churn_scorer import ChurnScorer

        cause = ChurnScorer._infer_root_cause(
            {"complaint_count": 3, "monetary_trend": 0, "frequency_trend": 0, "cancel_rate": 0}
        )
        assert cause == "service"

    def test_infer_root_cause_price(self):
        """消费额降50%+ → price"""
        from services.churn_scorer import ChurnScorer

        cause = ChurnScorer._infer_root_cause(
            {"complaint_count": 0, "monetary_trend": -0.6, "frequency_trend": 0, "cancel_rate": 0}
        )
        assert cause == "price"


class TestChurnJourneyTemplates:
    """旅程模板测试"""

    def test_get_warm_journey(self):
        from templates.churn_journey_templates import get_journey_for_tier

        j = get_journey_for_tier("warm")
        assert j is not None
        assert j["intervention_type"] == "warm_touch"
        assert len(j["steps"]) >= 2

    def test_get_critical_journey(self):
        from templates.churn_journey_templates import get_journey_for_tier

        j = get_journey_for_tier("critical")
        assert j is not None
        assert j["intervention_type"] == "manager_invite"
        assert any(s["action"] == "create_task" for s in j["steps"])

    def test_all_templates_have_required_fields(self):
        from templates.churn_journey_templates import get_all_templates

        templates = get_all_templates()
        assert len(templates) == 3
        for t in templates:
            assert "tier" in t
            assert "name" in t
            assert "steps_count" in t
