"""测试 3 个新增增长Agent: 企业客户激活、智能客服、增长归因

每个Agent至少测试2个action，共9个测试用例。
"""
import pytest
from agents.skills.enterprise_activation import EnterpriseActivationAgent
from agents.skills.growth_attribution import GrowthAttributionAgent
from agents.skills.smart_customer_service import SmartCustomerServiceAgent

TENANT_ID = "test-tenant-001"
STORE_ID = "store-001"


# ==================== 企业客户激活Agent ====================

class TestEnterpriseActivationAgent:
    @pytest.fixture
    def agent(self):
        return EnterpriseActivationAgent(tenant_id=TENANT_ID, store_id=STORE_ID)

    @pytest.mark.asyncio
    async def test_identify_enterprise_prospects(self, agent):
        result = await agent.execute("identify", {
            "store_id": STORE_ID,
            "nearby_companies": [
                {"company_id": "comp1", "company_name": "腾讯科技", "employee_count": 500,
                 "distance_km": 0.8, "industry": "科技"},
                {"company_id": "comp2", "company_name": "小区物业", "employee_count": 10,
                 "distance_km": 0.3, "industry": "物业"},
                {"company_id": "comp3", "company_name": "律师事务所", "employee_count": 60,
                 "distance_km": 1.5, "industry": "法律"},
            ],
            "existing_enterprise_ids": [],
            "radius_km": 3,
        })
        assert result.success
        assert result.data["total"] == 3
        assert result.data["high_value_count"] >= 1
        # 腾讯科技应排第一(大企业+近距离+高价值行业)
        assert result.data["prospects"][0]["company_id"] == "comp1"
        assert result.confidence > 0

    @pytest.mark.asyncio
    async def test_design_enterprise_package_margin_safe(self, agent):
        """套餐毛利率高于底线"""
        result = await agent.execute("design_package", {
            "enterprise_type": "business_banquet",
            "pax": 10,
            "budget_per_person_fen": 15000,
            "available_dishes": [
                {"dish_id": "d1", "name": "龙虾", "category": "热菜",
                 "price_fen": 18800, "cost_fen": 8000, "popularity_score": 90},
                {"dish_id": "d2", "name": "佛跳墙", "category": "热菜",
                 "price_fen": 28800, "cost_fen": 12000, "popularity_score": 85},
                {"dish_id": "d3", "name": "凉拌海蜇", "category": "凉菜",
                 "price_fen": 3800, "cost_fen": 1200, "popularity_score": 70},
                {"dish_id": "d4", "name": "炒时蔬", "category": "凉菜",
                 "price_fen": 2800, "cost_fen": 800, "popularity_score": 65},
                {"dish_id": "d5", "name": "米饭", "category": "主食",
                 "price_fen": 500, "cost_fen": 100, "popularity_score": 80},
                {"dish_id": "d6", "name": "面条", "category": "主食",
                 "price_fen": 1800, "cost_fen": 500, "popularity_score": 60},
                {"dish_id": "d7", "name": "芒果布丁", "category": "甜品",
                 "price_fen": 2800, "cost_fen": 800, "popularity_score": 75},
            ],
        })
        assert result.success
        assert result.data["margin_safe"] is True
        assert result.data["margin_rate"] >= 0.15
        assert result.confidence > 0

    @pytest.mark.asyncio
    async def test_track_enterprise_lifecycle_churn_warning(self, agent):
        """企业客户流失预警"""
        result = await agent.execute("track_lifecycle", {
            "enterprise_id": "ent-001",
            "enterprise_name": "某科技公司",
            "contract_signed": True,
            "last_order_days_ago": 60,
            "total_spent_fen": 300000,
            "order_count": 8,
            "orders": [
                {"amount_fen": 50000},
                {"amount_fen": 45000},
                {"amount_fen": 20000},
            ],
        })
        assert result.success
        assert result.data["churn_warning"] is True
        assert result.data["stage"] == "churn_warning"
        assert len(result.data["churn_signals"]) > 0
        assert "紧急回访" in result.data["recommended_actions"]
        assert result.confidence > 0


# ==================== 智能客服Agent ====================

class TestSmartCustomerServiceAgent:
    @pytest.fixture
    def agent(self):
        return SmartCustomerServiceAgent(tenant_id=TENANT_ID, store_id=STORE_ID)

    @pytest.mark.asyncio
    async def test_answer_faq_matched(self, agent):
        result = await agent.execute("answer_faq", {
            "question": "你们几点开门营业时间是什么",
            "context": {
                "open_time": "10:00",
                "close_time": "22:00",
            },
        })
        assert result.success
        assert result.data["matched_faq"] == "营业时间"
        assert result.data["need_human"] is False
        assert "10:00" in result.data["answer"]
        assert result.confidence >= 0.6

    @pytest.mark.asyncio
    async def test_answer_faq_no_match(self, agent):
        result = await agent.execute("answer_faq", {
            "question": "你们老板是谁",
        })
        assert result.success
        assert result.data["need_human"] is True
        assert result.confidence < 0.5

    @pytest.mark.asyncio
    async def test_handle_complaint_severe(self, agent):
        result = await agent.execute("handle_complaint", {
            "complaint": "菜里面有虫子，太恶心了",
            "order_id": "order-123",
            "order_amount_fen": 20000,
            "customer_level": "vip",
        })
        assert result.success
        assert result.data["complaint_level"] == "severe"
        assert result.data["need_escalation"] is True
        assert "免单" in result.data["compensation_plan"]
        assert result.confidence > 0

    @pytest.mark.asyncio
    async def test_analyze_sentiment_batch(self, agent):
        result = await agent.execute("analyze_sentiment", {
            "feedbacks": [
                {"text": "菜品好吃，环境好，下次再来", "id": "f1"},
                {"text": "太贵了，味道差，不推荐", "id": "f2"},
                {"text": "一般般吧", "id": "f3"},
            ],
        })
        assert result.success
        assert result.data["total"] == 3
        assert result.data["sentiment_distribution"]["positive"] >= 1
        assert result.data["sentiment_distribution"]["negative"] >= 1
        assert result.confidence > 0


# ==================== 增长归因Agent ====================

class TestGrowthAttributionAgent:
    @pytest.fixture
    def agent(self):
        return GrowthAttributionAgent(tenant_id=TENANT_ID, store_id=STORE_ID)

    @pytest.mark.asyncio
    async def test_attribute_revenue_growth(self, agent):
        result = await agent.execute("attribute", {
            "store_id": STORE_ID,
            "period": "month",
            "current_revenue_fen": 1200000,
            "previous_revenue_fen": 1000000,
            "new_customer_revenue_fen": 150000,
            "repeat_revenue_fen": 900000,
            "current_avg_ticket_fen": 8000,
            "previous_avg_ticket_fen": 7500,
            "current_customer_count": 150,
            "previous_customer_count": 133,
            "channel_revenue": {"堂食": 800000, "外卖": 300000, "小程序": 100000},
            "previous_channel_revenue": {"堂食": 750000, "外卖": 200000, "小程序": 50000},
        })
        assert result.success
        assert result.data["growth_yuan"] == 2000.0
        assert result.data["growth_rate"] > 0
        assert "new_customer" in result.data["attributions"]
        assert result.data["primary_source"] is not None
        assert result.confidence > 0

    @pytest.mark.asyncio
    async def test_evaluate_campaign_roi(self, agent):
        result = await agent.execute("evaluate_roi", {
            "campaign_id": "camp-001",
            "campaign_name": "春季满减活动",
            "campaign_cost_fen": 50000,
            "incremental_revenue_fen": 300000,
            "new_customers_acquired": 25,
            "coupons_issued": 200,
            "coupons_redeemed": 80,
            "reach_count": 1000,
            "order_count": 60,
        })
        assert result.success
        assert result.data["roi"] == 5.0
        assert result.data["roi_grade"] == "excellent"
        assert result.data["conversion_rate_pct"] == 6.0
        assert result.confidence > 0

    @pytest.mark.asyncio
    async def test_predict_growth_trajectory(self, agent):
        result = await agent.execute("predict", {
            "store_id": STORE_ID,
            "historical_revenue_fen": [
                800000, 850000, 900000, 950000, 1000000, 1050000,
            ],
            "predict_months": 3,
        })
        assert result.success
        assert result.data["trend"] == "growing"
        assert len(result.data["predictions"]) == 3
        # 增长趋势下，预测应递增
        preds = result.data["predictions"]
        assert preds[0]["predicted_revenue_fen"] > 0
        assert result.confidence > 0

    @pytest.mark.asyncio
    async def test_predict_insufficient_data(self, agent):
        """历史数据不足应报错"""
        result = await agent.execute("predict", {
            "store_id": STORE_ID,
            "historical_revenue_fen": [800000, 850000],
            "predict_months": 3,
        })
        assert not result.success
        assert "至少需要3个月" in result.error
