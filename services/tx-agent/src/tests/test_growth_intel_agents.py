"""测试 16 个增长Agent + 情报Agent

每个Agent至少测试2个action，共32+个测试用例。
"""

import pytest
from agents.skills.banquet_growth import BanquetGrowthAgent
from agents.skills.competitor_watch import CompetitorWatchAgent
from agents.skills.content_generation import ContentGenerationAgent
from agents.skills.dormant_recall import DormantRecallAgent
from agents.skills.high_value_member import HighValueMemberAgent
from agents.skills.ingredient_radar import IngredientRadarAgent
from agents.skills.intel_reporter import IntelReporterAgent
from agents.skills.menu_advisor import MenuAdvisorAgent
from agents.skills.new_customer_convert import NewCustomerConvertAgent
from agents.skills.new_product_scout import NewProductScoutAgent
from agents.skills.off_peak_traffic import OffPeakTrafficAgent
from agents.skills.pilot_recommender import PilotRecommenderAgent
from agents.skills.referral_growth import ReferralGrowthAgent
from agents.skills.review_insight import ReviewInsightAgent
from agents.skills.seasonal_campaign import SeasonalCampaignAgent
from agents.skills.trend_discovery import TrendDiscoveryAgent

TENANT_ID = "test-tenant-001"
STORE_ID = "store-001"


# ==================== 增长Agent ====================


class TestNewCustomerConvertAgent:
    @pytest.fixture
    def agent(self):
        return NewCustomerConvertAgent(tenant_id=TENANT_ID, store_id=STORE_ID)

    @pytest.mark.asyncio
    async def test_identify_new_customers(self, agent):
        result = await agent.execute(
            "identify_new_customers",
            {
                "customers": [
                    {
                        "customer_id": "c1",
                        "name": "张三",
                        "total_visits": 1,
                        "first_visit_days_ago": 3,
                        "avg_spend_fen": 12000,
                        "has_registered": True,
                        "source_channel": "美团",
                    },
                    {
                        "customer_id": "c2",
                        "name": "李四",
                        "total_visits": 1,
                        "first_visit_days_ago": 5,
                        "avg_spend_fen": 5000,
                        "has_registered": False,
                        "source_channel": "门店自然到店",
                    },
                    {
                        "customer_id": "c3",
                        "name": "王五",
                        "total_visits": 10,
                        "first_visit_days_ago": 90,
                        "avg_spend_fen": 20000,
                        "has_registered": True,
                    },
                ],
                "lookback_days": 7,
            },
        )
        assert result.success
        assert result.data["total"] == 2
        assert result.data["new_customers"][0]["customer_id"] == "c1"
        assert result.confidence > 0

    @pytest.mark.asyncio
    async def test_generate_welcome_offer(self, agent):
        result = await agent.execute(
            "generate_welcome_offer",
            {
                "customer_id": "c1",
                "avg_spend_fen": 16000,
                "preferences": ["火锅", "甜品"],
            },
        )
        assert result.success
        assert result.data["tier"] == "high_spend"
        assert len(result.data["bonus_items"]) == 2

    @pytest.mark.asyncio
    async def test_predict_conversion_probability(self, agent):
        result = await agent.execute(
            "predict_conversion_probability",
            {
                "customers": [
                    {
                        "customer_id": "c1",
                        "first_spend_fen": 15000,
                        "dwell_minutes": 70,
                        "ordered_items": 5,
                        "has_registered": True,
                        "source_channel": "老客推荐",
                    },
                    {
                        "customer_id": "c2",
                        "first_spend_fen": 3000,
                        "dwell_minutes": 20,
                        "ordered_items": 2,
                        "has_registered": False,
                        "source_channel": "美团",
                    },
                ],
            },
        )
        assert result.success
        assert result.data["total"] == 2
        assert result.data["predictions"][0]["conversion_prob"] > result.data["predictions"][1]["conversion_prob"]


class TestDormantRecallAgent:
    @pytest.fixture
    def agent(self):
        return DormantRecallAgent(tenant_id=TENANT_ID, store_id=STORE_ID)

    @pytest.mark.asyncio
    async def test_detect_dormant_users(self, agent):
        result = await agent.execute(
            "detect_dormant_users",
            {
                "members": [
                    {
                        "customer_id": "c1",
                        "name": "张三",
                        "last_visit_days_ago": 20,
                        "total_spent_fen": 50000,
                        "visit_count": 5,
                    },
                    {
                        "customer_id": "c2",
                        "name": "李四",
                        "last_visit_days_ago": 45,
                        "total_spent_fen": 30000,
                        "visit_count": 3,
                    },
                    {
                        "customer_id": "c3",
                        "name": "王五",
                        "last_visit_days_ago": 80,
                        "total_spent_fen": 100000,
                        "visit_count": 20,
                    },
                    {
                        "customer_id": "c4",
                        "name": "赵六",
                        "last_visit_days_ago": 5,
                        "total_spent_fen": 10000,
                        "visit_count": 2,
                    },
                ],
            },
        )
        assert result.success
        assert result.data["total"] == 3
        assert result.data["tier_distribution"]["deep"] == 1
        assert result.data["tier_distribution"]["medium"] == 1
        assert result.data["tier_distribution"]["light"] == 1

    @pytest.mark.asyncio
    async def test_generate_recall_strategy(self, agent):
        result = await agent.execute(
            "generate_recall_strategy",
            {
                "tier": "deep",
                "reason": "价格敏感",
                "customer_id": "c3",
                "customer_name": "王五",
            },
        )
        assert result.success
        assert result.data["tier"] == "deep"
        assert result.data["extra_offer"] is not None
        assert "加大优惠力度" in result.data["extra_offer"]["type"]

    @pytest.mark.asyncio
    async def test_predict_churn_risk(self, agent):
        result = await agent.execute(
            "predict_churn_risk",
            {
                "members": [
                    {
                        "customer_id": "c1",
                        "name": "高风险",
                        "last_visit_days_ago": 100,
                        "monthly_frequency": 0,
                        "spend_trend": -30,
                        "complaint_count": 2,
                    },
                    {
                        "customer_id": "c2",
                        "name": "低风险",
                        "last_visit_days_ago": 5,
                        "monthly_frequency": 8,
                        "spend_trend": 10,
                        "complaint_count": 0,
                    },
                ],
            },
        )
        assert result.success
        assert result.data["predictions"][0]["risk_level"] in ("极高", "高")
        assert result.data["predictions"][-1]["risk_level"] == "低"


class TestBanquetGrowthAgent:
    @pytest.fixture
    def agent(self):
        return BanquetGrowthAgent(tenant_id=TENANT_ID, store_id=STORE_ID)

    @pytest.mark.asyncio
    async def test_recommend_banquet_package(self, agent):
        result = await agent.execute(
            "recommend_banquet_package",
            {
                "banquet_type": "wedding",
                "table_count": 20,
            },
        )
        assert result.success
        assert len(result.data["packages"]) == 3
        assert result.data["banquet_type_name"] == "婚宴"

    @pytest.mark.asyncio
    async def test_analyze_banquet_revenue(self, agent):
        result = await agent.execute(
            "analyze_banquet_revenue",
            {
                "banquets": [
                    {"banquet_type": "wedding", "revenue_fen": 5000000, "cost_fen": 2000000},
                    {"banquet_type": "birthday", "revenue_fen": 1500000, "cost_fen": 600000},
                ],
            },
        )
        assert result.success
        assert result.data["total_banquets"] == 2
        assert result.data["gross_margin_pct"] > 0


class TestSeasonalCampaignAgent:
    @pytest.fixture
    def agent(self):
        return SeasonalCampaignAgent(tenant_id=TENANT_ID, store_id=STORE_ID)

    @pytest.mark.asyncio
    async def test_get_seasonal_calendar(self, agent):
        result = await agent.execute("get_seasonal_calendar", {"month": 9})
        assert result.success
        assert len(result.data["events"]) > 0
        assert any(e["name"] == "中秋节" for e in result.data["events"])

    @pytest.mark.asyncio
    async def test_recommend_seasonal_dishes(self, agent):
        result = await agent.execute(
            "recommend_seasonal_dishes",
            {
                "event_id": "mid_autumn",
                "existing_menu": ["月饼"],
            },
        )
        assert result.success
        assert len(result.data["recommendations"]) > 0
        assert result.data["event_name"] == "中秋节"


class TestReferralGrowthAgent:
    @pytest.fixture
    def agent(self):
        return ReferralGrowthAgent(tenant_id=TENANT_ID, store_id=STORE_ID)

    @pytest.mark.asyncio
    async def test_design_referral_campaign(self, agent):
        result = await agent.execute(
            "design_referral_campaign",
            {
                "template": "invite_reward",
                "target_new_customers": 100,
                "budget_fen": 1000000,
            },
        )
        assert result.success
        assert result.data["template_name"] == "邀请有礼"
        assert result.data["max_affordable_customers"] > 0

    @pytest.mark.asyncio
    async def test_select_seed_users(self, agent):
        result = await agent.execute(
            "select_seed_users",
            {
                "members": [
                    {
                        "customer_id": "c1",
                        "name": "大V",
                        "wechat_friends": 500,
                        "past_referrals": 10,
                        "social_shares": 20,
                        "visit_count": 15,
                        "avg_rating": 5,
                    },
                    {
                        "customer_id": "c2",
                        "name": "普通",
                        "wechat_friends": 50,
                        "past_referrals": 0,
                        "social_shares": 0,
                        "visit_count": 2,
                        "avg_rating": 3,
                    },
                ],
                "top_n": 5,
            },
        )
        assert result.success
        assert result.data["seed_users"][0]["name"] == "大V"
        assert result.data["seed_users"][0]["seed_score"] > result.data["seed_users"][1]["seed_score"]


class TestHighValueMemberAgent:
    @pytest.fixture
    def agent(self):
        return HighValueMemberAgent(tenant_id=TENANT_ID, store_id=STORE_ID)

    @pytest.mark.asyncio
    async def test_identify_high_value_members(self, agent):
        result = await agent.execute(
            "identify_high_value_members",
            {
                "members": [
                    {"customer_id": "c1", "name": "VIP", "annual_spend_fen": 6000000, "visit_count": 50},
                    {"customer_id": "c2", "name": "金卡", "annual_spend_fen": 2500000, "visit_count": 20},
                    {"customer_id": "c3", "name": "普通", "annual_spend_fen": 100000, "visit_count": 3},
                ],
            },
        )
        assert result.success
        assert result.data["tier_distribution"]["diamond"] == 1
        assert result.data["tier_distribution"]["gold"] == 1

    @pytest.mark.asyncio
    async def test_alert_high_value_churn(self, agent):
        result = await agent.execute(
            "alert_high_value_churn",
            {
                "members": [
                    {
                        "customer_id": "c1",
                        "name": "VIP",
                        "annual_spend_fen": 6000000,
                        "last_visit_days_ago": 45,
                        "frequency_decline_pct": 50,
                        "spend_decline_pct": 30,
                        "recent_complaint": True,
                    },
                    {"customer_id": "c2", "name": "普通", "annual_spend_fen": 100000, "last_visit_days_ago": 60},
                ],
            },
        )
        assert result.success
        assert result.data["total_alerts"] == 1
        assert result.data["alerts"][0]["name"] == "VIP"


class TestOffPeakTrafficAgent:
    @pytest.fixture
    def agent(self):
        return OffPeakTrafficAgent(tenant_id=TENANT_ID, store_id=STORE_ID)

    @pytest.mark.asyncio
    async def test_identify_off_peak_slots_default(self, agent):
        result = await agent.execute("identify_off_peak_slots", {})
        assert result.success
        assert len(result.data["off_peak_slots"]) > 0

    @pytest.mark.asyncio
    async def test_design_off_peak_offer(self, agent):
        result = await agent.execute(
            "design_off_peak_offer",
            {
                "slot": "afternoon",
                "current_utilization_pct": 15,
                "target_utilization_pct": 50,
                "avg_ticket_fen": 8000,
            },
        )
        assert result.success
        assert result.data["discount_rate"] < 1.0
        assert result.data["slot"] == "afternoon"


class TestContentGenerationAgent:
    @pytest.fixture
    def agent(self):
        return ContentGenerationAgent(tenant_id=TENANT_ID, store_id=STORE_ID)

    @pytest.mark.asyncio
    async def test_generate_marketing_copy(self, agent):
        result = await agent.execute(
            "generate_marketing_copy",
            {
                "campaign_type": "new_customer",
                "brand_name": "尝在一起",
                "offer": "新客立减20元",
                "tone": "warm",
            },
        )
        assert result.success
        assert len(result.data["copies"]) >= 3
        assert "尝在一起" in result.data["copies"][0]["text"]

    @pytest.mark.asyncio
    async def test_generate_video_script(self, agent):
        result = await agent.execute(
            "generate_video_script",
            {
                "topic": "湘菜探店",
                "duration_seconds": 15,
                "brand_name": "尝在一起",
                "featured_dish": "剁椒鱼头",
            },
        )
        assert result.success
        assert result.data["total_scenes"] >= 3
        assert result.data["duration_seconds"] == 15


# ==================== 情报Agent ====================


class TestCompetitorWatchAgent:
    @pytest.fixture
    def agent(self):
        return CompetitorWatchAgent(tenant_id=TENANT_ID, store_id=STORE_ID)

    @pytest.mark.asyncio
    async def test_scan_competitor_updates(self, agent):
        result = await agent.execute(
            "scan_competitor_updates",
            {
                "competitors": [
                    {
                        "name": "海底捞",
                        "recent_events": [
                            {
                                "type": "price_drop_major",
                                "title": "全线降价10%",
                                "detail": "主力菜品降价",
                                "date": "2026-03-20",
                            },
                            {"type": "new_product", "title": "新品上线", "detail": "春季新菜3款", "date": "2026-03-22"},
                        ],
                    },
                    {
                        "name": "西贝",
                        "recent_events": [
                            {"type": "campaign", "title": "会员日活动", "detail": "会员全场8折", "date": "2026-03-21"},
                        ],
                    },
                ],
            },
        )
        assert result.success
        assert result.data["total"] == 3
        assert result.data["competitors_scanned"] == 2

    @pytest.mark.asyncio
    async def test_detect_price_change(self, agent):
        result = await agent.execute(
            "detect_price_change",
            {
                "competitor_prices": [
                    {"competitor": "海底捞", "dish": "番茄锅底", "old_price_fen": 5800, "new_price_fen": 4800},
                    {"competitor": "西贝", "dish": "莜面鱼鱼", "old_price_fen": 3800, "new_price_fen": 3800},
                ],
                "our_prices": {"番茄锅底": 5500},
            },
        )
        assert result.success
        assert result.data["price_drops"] == 1


class TestReviewInsightAgent:
    @pytest.fixture
    def agent(self):
        return ReviewInsightAgent(tenant_id=TENANT_ID, store_id=STORE_ID)

    @pytest.mark.asyncio
    async def test_extract_review_topics(self, agent):
        result = await agent.execute(
            "extract_review_topics",
            {
                "reviews": [
                    {"text": "味道好吃，服务态度也好", "rating": 5},
                    {"text": "环境不错，就是上菜太慢了", "rating": 3},
                    {"text": "菜品味道很鲜，分量足", "rating": 5},
                    {"text": "太贵了，不值这个价", "rating": 2},
                ],
            },
        )
        assert result.success
        assert result.data["total_reviews"] == 4
        assert len(result.data["topics"]) > 0

    @pytest.mark.asyncio
    async def test_analyze_bad_review_root_cause(self, agent):
        result = await agent.execute(
            "analyze_bad_review_root_cause",
            {
                "bad_reviews": [
                    {"text": "服务态度太差了，等了一小时都没上菜", "rating": 1},
                    {"text": "太贵了味道又不好", "rating": 2},
                    {"text": "上菜慢，服务员态度差", "rating": 1},
                ],
            },
        )
        assert result.success
        assert result.data["total_bad_reviews"] == 3
        assert len(result.data["root_causes"]) > 0


class TestTrendDiscoveryAgent:
    @pytest.fixture
    def agent(self):
        return TrendDiscoveryAgent(tenant_id=TENANT_ID, store_id=STORE_ID)

    @pytest.mark.asyncio
    async def test_analyze_search_hot_words(self, agent):
        result = await agent.execute(
            "analyze_search_hot_words",
            {
                "search_data": [
                    {
                        "keyword": "小龙虾",
                        "search_volume": 50000,
                        "trend": "上升",
                        "growth_pct": 30,
                        "category": "海鲜",
                    },
                    {"keyword": "火锅", "search_volume": 80000, "trend": "持平", "growth_pct": 2, "category": "火锅"},
                    {
                        "keyword": "轻食",
                        "search_volume": 30000,
                        "trend": "上升",
                        "growth_pct": 50,
                        "category": "轻食沙拉",
                    },
                ],
                "platform": "美团",
            },
        )
        assert result.success
        assert result.data["hot_words"][0]["keyword"] == "火锅"
        assert result.data["total_keywords_analyzed"] == 3

    @pytest.mark.asyncio
    async def test_predict_category_trend(self, agent):
        result = await agent.execute(
            "predict_category_trend",
            {
                "categories": [
                    {"name": "小龙虾", "recent_growth_pct": 25, "search_trend": "上升", "store_growth_pct": 10},
                    {"name": "预制菜", "recent_growth_pct": -5, "search_trend": "下降", "store_growth_pct": -3},
                ],
            },
        )
        assert result.success
        assert len(result.data["predictions"]) == 2
        assert "小龙虾" in result.data["rising_categories"]


class TestNewProductScoutAgent:
    @pytest.fixture
    def agent(self):
        return NewProductScoutAgent(tenant_id=TENANT_ID, store_id=STORE_ID)

    @pytest.mark.asyncio
    async def test_assess_feasibility(self, agent):
        result = await agent.execute(
            "assess_feasibility",
            {
                "dish_name": "松露炒饭",
                "ingredients": ["松露", "米饭", "鸡蛋", "葱"],
                "required_skills": ["中式炒锅"],
                "required_equipment": ["炒锅", "蒸柜"],
                "estimated_cost_fen": 2000,
                "expected_price_fen": 6800,
                "available_ingredients": ["米饭", "鸡蛋", "葱"],
                "chef_skills": ["中式炒锅", "烘焙"],
                "existing_equipment": ["炒锅", "蒸柜", "烤箱"],
            },
        )
        assert result.success
        assert result.data["feasibility"] in ("高", "中", "低")
        assert result.data["estimated_margin_pct"] > 0

    @pytest.mark.asyncio
    async def test_suggest_pricing(self, agent):
        result = await agent.execute(
            "suggest_pricing",
            {
                "dish_name": "松露炒饭",
                "cost_fen": 2000,
                "target_margin_pct": 65,
                "competitor_prices": [{"price_fen": 5800}, {"price_fen": 6200}],
                "category_avg_price_fen": 5500,
            },
        )
        assert result.success
        assert result.data["suggested_price_yuan"] > 0
        assert result.data["actual_margin_pct"] > 0


class TestIngredientRadarAgent:
    @pytest.fixture
    def agent(self):
        return IngredientRadarAgent(tenant_id=TENANT_ID, store_id=STORE_ID)

    @pytest.mark.asyncio
    async def test_compare_suppliers(self, agent):
        result = await agent.execute(
            "compare_suppliers",
            {
                "ingredient": "五花肉",
                "suppliers": [
                    {
                        "name": "长沙肉联厂",
                        "price_per_kg_fen": 4500,
                        "quality_score": 90,
                        "avg_delivery_days": 1,
                        "on_time_rate_pct": 95,
                    },
                    {
                        "name": "网上批发",
                        "price_per_kg_fen": 3800,
                        "quality_score": 70,
                        "avg_delivery_days": 3,
                        "on_time_rate_pct": 80,
                    },
                ],
            },
        )
        assert result.success
        assert result.data["total_compared"] == 2
        assert result.data["recommended"] is not None

    @pytest.mark.asyncio
    async def test_check_compliance(self, agent):
        result = await agent.execute(
            "check_compliance",
            {
                "ingredient": "辣椒酱",
                "certifications": ["SC"],
                "additives": ["山梨酸钾"],
                "origin": "贵州",
                "shelf_life_days": 365,
            },
        )
        assert result.success
        assert result.data["overall_status"] == "合规"
        assert len(result.data["issues"]) == 0


class TestMenuAdvisorAgent:
    @pytest.fixture
    def agent(self):
        return MenuAdvisorAgent(tenant_id=TENANT_ID, store_id=STORE_ID)

    @pytest.mark.asyncio
    async def test_analyze_dish_quadrant(self, agent):
        result = await agent.execute(
            "analyze_dish_quadrant",
            {
                "dishes": [
                    {"dish_name": "剁椒鱼头", "monthly_sales": 500, "margin_pct": 70, "revenue_fen": 3500000},
                    {"dish_name": "凉拌黄瓜", "monthly_sales": 300, "margin_pct": 85, "revenue_fen": 540000},
                    {"dish_name": "可乐鸡翅", "monthly_sales": 400, "margin_pct": 40, "revenue_fen": 1200000},
                    {"dish_name": "松鼠桂鱼", "monthly_sales": 50, "margin_pct": 30, "revenue_fen": 350000},
                ],
            },
        )
        assert result.success
        assert result.data["total_dishes"] == 4
        assert sum(q["count"] for q in result.data["quadrants"].values()) == 4

    @pytest.mark.asyncio
    async def test_diagnose_menu_structure(self, agent):
        result = await agent.execute(
            "diagnose_menu_structure",
            {
                "total_dishes": 120,
                "categories": [
                    {"name": "热菜", "dish_count": 50, "avg_margin_pct": 60, "revenue_contribution_pct": 55},
                    {"name": "凉菜", "dish_count": 20, "avg_margin_pct": 75, "revenue_contribution_pct": 10},
                    {"name": "汤品", "dish_count": 10, "avg_margin_pct": 65, "revenue_contribution_pct": 8},
                    {"name": "饮品", "dish_count": 40, "avg_margin_pct": 80, "revenue_contribution_pct": 27},
                ],
            },
        )
        assert result.success
        assert result.data["total_dishes"] == 120
        assert len(result.data["issues"]) > 0  # 120 dishes is too many


class TestPilotRecommenderAgent:
    @pytest.fixture
    def agent(self):
        return PilotRecommenderAgent(tenant_id=TENANT_ID, store_id=STORE_ID)

    @pytest.mark.asyncio
    async def test_recommend_pilot_stores(self, agent):
        result = await agent.execute(
            "recommend_pilot_stores",
            {
                "stores": [
                    {
                        "store_id": "s1",
                        "store_name": "五一广场店",
                        "city": "长沙",
                        "district": "芙蓉区",
                        "daily_traffic": 300,
                        "avg_rating": 4.8,
                        "member_pct": 60,
                        "manager_score": 90,
                        "has_full_equipment": True,
                        "is_representative": True,
                    },
                    {
                        "store_id": "s2",
                        "store_name": "河西店",
                        "city": "长沙",
                        "district": "岳麓区",
                        "daily_traffic": 150,
                        "avg_rating": 4.2,
                        "member_pct": 30,
                        "manager_score": 70,
                        "has_full_equipment": True,
                        "is_representative": False,
                    },
                    {
                        "store_id": "s3",
                        "store_name": "星沙店",
                        "city": "长沙",
                        "district": "长沙县",
                        "daily_traffic": 100,
                        "avg_rating": 3.8,
                        "member_pct": 20,
                        "manager_score": 50,
                        "has_full_equipment": False,
                        "is_representative": False,
                    },
                ],
                "project_type": "新品试销",
                "pilot_count": 2,
            },
        )
        assert result.success
        assert result.data["pilot_count"] == 2
        assert result.data["recommended"][0]["store_name"] == "五一广场店"

    @pytest.mark.asyncio
    async def test_cluster_stores(self, agent):
        result = await agent.execute(
            "cluster_stores",
            {
                "stores": [
                    {"store_id": "s1", "store_name": "A", "daily_traffic": 400, "avg_ticket_fen": 12000},
                    {"store_id": "s2", "store_name": "B", "daily_traffic": 100, "avg_ticket_fen": 15000},
                    {"store_id": "s3", "store_name": "C", "daily_traffic": 350, "avg_ticket_fen": 6000},
                    {"store_id": "s4", "store_name": "D", "daily_traffic": 80, "avg_ticket_fen": 5000},
                ],
            },
        )
        assert result.success
        assert result.data["total_stores"] == 4
        assert sum(c["count"] for c in result.data["clusters"].values()) == 4


class TestIntelReporterAgent:
    @pytest.fixture
    def agent(self):
        return IntelReporterAgent(tenant_id=TENANT_ID, store_id=STORE_ID)

    @pytest.mark.asyncio
    async def test_generate_competitor_weekly(self, agent):
        result = await agent.execute(
            "generate_competitor_weekly",
            {
                "week": "2026-W13",
                "competitors": [{"name": "海底捞"}, {"name": "西贝"}],
                "price_changes": [{"item": "锅底", "direction": "降价"}],
                "new_products": [{"name": "春季新品"}],
                "campaigns": [],
                "store_changes": [],
            },
        )
        assert result.success
        assert "竞对动态周报" in result.data["title"]
        assert result.data["summary_stats"]["competitors_monitored"] == 2

    @pytest.mark.asyncio
    async def test_generate_monthly_report(self, agent):
        result = await agent.execute(
            "generate_monthly_report",
            {
                "month": "2026年3月",
                "competitor_summary": {"threat_level": "升高", "price_changes": 8},
                "demand_summary": {"overall_trend": "上升"},
                "product_summary": {"hot_products": 5},
                "ingredient_summary": {"cost_trend": "上涨", "rising_count": 12},
                "district_summary": {"growing_districts": 3},
            },
        )
        assert result.success
        assert "月度市场情报报告" in result.data["report"]["title"]
        assert len(result.data["report"]["sections"]) == 5


# ==================== Agent元信息测试 ====================


class TestAgentMetadata:
    """验证所有16个Agent的元信息正确"""

    @pytest.mark.parametrize(
        "agent_cls,expected_id,expected_priority",
        [
            (NewCustomerConvertAgent, "new_customer_convert", "P0"),
            (DormantRecallAgent, "dormant_recall", "P0"),
            (BanquetGrowthAgent, "banquet_growth", "P1"),
            (SeasonalCampaignAgent, "seasonal_campaign", "P1"),
            (ReferralGrowthAgent, "referral_growth", "P1"),
            (HighValueMemberAgent, "high_value_member", "P0"),
            (OffPeakTrafficAgent, "off_peak_traffic", "P1"),
            (ContentGenerationAgent, "content_generation", "P1"),
            (CompetitorWatchAgent, "competitor_watch", "P1"),
            (ReviewInsightAgent, "review_insight", "P1"),
            (TrendDiscoveryAgent, "trend_discovery", "P1"),
            (NewProductScoutAgent, "new_product_scout", "P1"),
            (IngredientRadarAgent, "ingredient_radar", "P1"),
            (MenuAdvisorAgent, "menu_advisor", "P1"),
            (PilotRecommenderAgent, "pilot_recommender", "P1"),
            (IntelReporterAgent, "intel_reporter", "P1"),
        ],
    )
    def test_agent_info(self, agent_cls, expected_id, expected_priority):
        agent = agent_cls(tenant_id=TENANT_ID)
        info = agent.get_info()
        assert info["agent_id"] == expected_id
        assert info["priority"] == expected_priority
        assert info["run_location"] == "cloud"
        assert len(info["supported_actions"]) >= 5

    @pytest.mark.parametrize(
        "agent_cls",
        [
            NewCustomerConvertAgent,
            DormantRecallAgent,
            BanquetGrowthAgent,
            SeasonalCampaignAgent,
            ReferralGrowthAgent,
            HighValueMemberAgent,
            OffPeakTrafficAgent,
            ContentGenerationAgent,
            CompetitorWatchAgent,
            ReviewInsightAgent,
            TrendDiscoveryAgent,
            NewProductScoutAgent,
            IngredientRadarAgent,
            MenuAdvisorAgent,
            PilotRecommenderAgent,
            IntelReporterAgent,
        ],
    )
    @pytest.mark.asyncio
    async def test_unsupported_action(self, agent_cls):
        agent = agent_cls(tenant_id=TENANT_ID)
        result = await agent.execute("nonexistent_action", {})
        assert not result.success
        assert "不支持" in result.error
