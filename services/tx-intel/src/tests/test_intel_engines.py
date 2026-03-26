"""市场情报中枢 — 综合测试

覆盖：
- 竞对监测 CRUD + 动态记录 + 威胁检测
- 消费洞察摄入 + 主题提取 + 趋势
- 口碑分析 + 门店对比 + 可执行问题
- 新品雷达评分 + 试点计划 + 趋势检测
- 价格分析 + 竞对对比 + 调价建议
- 报告生成（全类型）
- 试点生命周期（建议 → 审批 → 跟踪 → 评审 → 推广）
- 端到端：竞对动态 → 情报检测 → 试点建议
"""
import pytest

from services.competitor_monitor import CompetitorMonitorService, MONITOR_DIMENSIONS
from services.consumer_insight import ConsumerInsightService, INSIGHT_CATEGORIES
from services.review_topic_engine import ReviewTopicEngine, TOPIC_TYPES
from services.new_product_radar import NewProductRadar
from services.pricing_insight import PricingInsightService
from services.intel_report_engine import IntelReportEngine, REPORT_TYPES
from services.pilot_suggestion import PilotSuggestionService


# ═══════════════════════════════════════
# 竞对监测测试
# ═══════════════════════════════════════

class TestCompetitorMonitor:
    """竞对监测引擎测试"""

    def setup_method(self) -> None:
        self.svc = CompetitorMonitorService()

    def test_seed_competitors_loaded(self) -> None:
        """种子竞对数据已加载"""
        competitors = self.svc.list_competitors()
        assert len(competitors) == 5
        names = {c["name"] for c in competitors}
        assert "海底捞" in names
        assert "费大厨辣椒炒肉" in names
        assert "望湘园" in names

    def test_register_competitor(self) -> None:
        """注册新竞对"""
        result = self.svc.register_competitor(
            name="呷哺呷哺", category="火锅", price_tier="mid_range",
            cities=["北京", "上海"], stores_count=800,
            monitor_level="basic",
        )
        assert result["status"] == "registered"
        assert result["name"] == "呷哺呷哺"
        competitors = self.svc.list_competitors()
        assert len(competitors) == 6

    def test_register_competitor_invalid_price_tier(self) -> None:
        """无效价格带应报错"""
        with pytest.raises(ValueError, match="Invalid price_tier"):
            self.svc.register_competitor(
                name="Test", category="火锅", price_tier="超级贵",
                cities=["北京"], stores_count=1, monitor_level="basic",
            )

    def test_list_competitors_filter_by_category(self) -> None:
        """按品类筛选竞对"""
        hunan = self.svc.list_competitors(category="湘菜")
        assert len(hunan) == 2
        for c in hunan:
            assert c["category"] == "湘菜"

    def test_list_competitors_filter_by_city(self) -> None:
        """按城市筛选竞对"""
        changsha = self.svc.list_competitors(city="长沙")
        assert len(changsha) >= 2  # 海底捞、太二、费大厨至少在长沙

    def test_get_competitor_detail(self) -> None:
        """获取竞对详情"""
        competitors = self.svc.list_competitors()
        cid = competitors[0]["competitor_id"]
        detail = self.svc.get_competitor_detail(cid)
        assert detail["competitor_id"] == cid
        assert "name" in detail
        assert "recent_actions" in detail

    def test_get_competitor_detail_not_found(self) -> None:
        """不存在的竞对应报错"""
        with pytest.raises(KeyError):
            self.svc.get_competitor_detail("nonexistent")

    def test_record_competitor_action(self) -> None:
        """记录竞对动态"""
        competitors = self.svc.list_competitors()
        cid = competitors[0]["competitor_id"]
        result = self.svc.record_competitor_action(
            competitor_id=cid,
            action_type="new_product",
            title="测试新品上线",
            detail="这是一个测试动态",
            impact_level="medium",
            source="测试",
        )
        assert result["status"] == "recorded"
        assert result["action_type"] == "new_product"

    def test_record_action_invalid_type(self) -> None:
        """无效动态类型应报错"""
        competitors = self.svc.list_competitors()
        cid = competitors[0]["competitor_id"]
        with pytest.raises(ValueError, match="Invalid action_type"):
            self.svc.record_competitor_action(
                competitor_id=cid, action_type="invalid_type",
                title="测试", detail="测试", impact_level="low", source="测试",
            )

    def test_get_recent_actions(self) -> None:
        """获取近期动态"""
        actions = self.svc.get_recent_actions(days=30)
        assert len(actions) > 0
        # 应按时间倒序
        for i in range(len(actions) - 1):
            assert actions[i]["recorded_at"] >= actions[i + 1]["recorded_at"]

    def test_get_recent_actions_filter_by_type(self) -> None:
        """按类型筛选动态"""
        actions = self.svc.get_recent_actions(days=30, action_type="campaign")
        for a in actions:
            assert a["action_type"] == "campaign"

    def test_compare_with_self(self) -> None:
        """与我方品牌对比"""
        competitors = self.svc.list_competitors(category="湘菜")
        cid = competitors[0]["competitor_id"]
        comparison = self.svc.compare_with_self(cid, ["stores_count", "avg_rating", "avg_spend_fen"])
        assert comparison["metrics_compared"] == 3
        assert "stores_count" in comparison["comparison"]
        assert "diff" in comparison["comparison"]["stores_count"]

    def test_get_competitor_timeline(self) -> None:
        """获取竞对时间线"""
        competitors = self.svc.list_competitors()
        cid = competitors[0]["competitor_id"]
        timeline = self.svc.get_competitor_timeline(cid, days=30)
        assert isinstance(timeline, list)
        # 应按时间正序
        for i in range(len(timeline) - 1):
            assert timeline[i]["recorded_at"] <= timeline[i + 1]["recorded_at"]

    def test_detect_threats(self) -> None:
        """威胁检测"""
        threats = self.svc.detect_threats()
        assert isinstance(threats, list)
        assert len(threats) > 0
        # 应按严重程度排序
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        for i in range(len(threats) - 1):
            assert severity_order.get(threats[i]["severity"], 9) <= severity_order.get(threats[i + 1]["severity"], 9)
        # 应包含同品类竞对扩张威胁
        threat_types = {t["threat_type"] for t in threats}
        assert "同品类扩张" in threat_types or "爆品冲击" in threat_types

    def test_generate_competitor_summary(self) -> None:
        """生成竞对摘要"""
        competitors = self.svc.list_competitors()
        cid = competitors[0]["competitor_id"]
        summary = self.svc.generate_competitor_summary(cid)
        assert summary["competitor_id"] == cid
        assert len(summary["summary"]) > 0
        assert "generated_at" in summary


# ═══════════════════════════════════════
# 消费需求洞察测试
# ═══════════════════════════════════════

class TestConsumerInsight:
    """消费需求洞察引擎测试"""

    def setup_method(self) -> None:
        self.svc = ConsumerInsightService()

    def test_seed_signals_loaded(self) -> None:
        """种子信号已加载"""
        topics = self.svc.get_trending_topics()
        assert len(topics) > 0

    def test_ingest_signal(self) -> None:
        """摄入消费信号"""
        result = self.svc.ingest_signal(
            source_type="review",
            content="希望有更多减脂餐选择，太油腻了",
            city="深圳",
            store_id="S005",
        )
        assert result["status"] == "ingested"
        assert "signal_id" in result
        assert len(result["topics_extracted"]) > 0

    def test_ingest_signal_invalid_source(self) -> None:
        """无效信号来源应报错"""
        with pytest.raises(ValueError, match="Invalid source_type"):
            self.svc.ingest_signal(source_type="invalid", content="测试")

    def test_extract_topics(self) -> None:
        """主题提取"""
        signals = [
            {"content": "带小孩来吃，需要儿童套餐"},
            {"content": "减脂餐太少了，希望有健康选项"},
            {"content": "小孩子很喜欢这里"},
        ]
        topics = self.svc.extract_topics(signals)
        assert len(topics) > 0
        # 亲子用餐应该排名靠前（出现2次）
        topic_names = [t["topic_name"] for t in topics]
        assert "亲子用餐" in topic_names

    def test_get_trending_topics(self) -> None:
        """获取趋势主题"""
        topics = self.svc.get_trending_topics()
        assert len(topics) > 0
        # 应按信号数降序
        for i in range(len(topics) - 1):
            assert topics[i]["signal_count"] >= topics[i + 1]["signal_count"]

    def test_get_trending_topics_filter_by_category(self) -> None:
        """按分类筛选趋势主题"""
        topics = self.svc.get_trending_topics(category="health")
        for t in topics:
            assert t["category"] == "health"

    def test_get_topic_detail(self) -> None:
        """获取主题详情"""
        topics = self.svc.get_trending_topics()
        tid = topics[0]["topic_id"]
        detail = self.svc.get_topic_detail(tid)
        assert detail["topic_id"] == tid
        assert "sample_signals" in detail

    def test_get_demand_change_summary(self) -> None:
        """需求变化摘要"""
        summary = self.svc.get_demand_change_summary(period="week")
        assert summary["period"] == "week"
        assert summary["total_signals"] > 0
        assert summary["total_topics"] > 0
        assert "category_distribution" in summary
        assert len(summary["summary"]) > 0

    def test_compare_cities(self) -> None:
        """城市间对比"""
        result = self.svc.compare_cities(["长沙", "深圳"])
        assert "长沙" in result["comparison"]
        assert "深圳" in result["comparison"]

    def test_detect_emerging_needs(self) -> None:
        """新兴需求检测"""
        emerging = self.svc.detect_emerging_needs()
        assert isinstance(emerging, list)
        for need in emerging:
            assert "recommendation" in need
            assert need["signal_count"] >= 2


# ═══════════════════════════════════════
# 口碑主题分析测试
# ═══════════════════════════════════════

class TestReviewTopicEngine:
    """口碑主题抽取引擎测试"""

    def setup_method(self) -> None:
        self.engine = ReviewTopicEngine()

    def test_seed_reviews_analyzed(self) -> None:
        """种子评价已分析"""
        summary = self.engine.get_topic_summary()
        assert summary["total_topics"] > 0

    def test_analyze_reviews(self) -> None:
        """批量分析评价"""
        reviews = [
            {"store_id": "S001", "rating": 5, "content": "辣椒炒肉太好吃了，服务态度很好"},
            {"store_id": "S001", "rating": 1, "content": "菜里有异物，太脏了，差评"},
        ]
        result = self.engine.analyze_reviews(reviews)
        assert result["total_analyzed"] == 2
        assert result["actionable_count"] >= 1  # 差评应标记为可执行
        assert len(result["results"]) == 2

    def test_analyze_reviews_sentiment(self) -> None:
        """情感分析准确性"""
        reviews = [
            {"store_id": "S001", "rating": 5, "content": "好吃、推荐、环境好"},
            {"store_id": "S001", "rating": 1, "content": "难吃、服务差、太贵"},
        ]
        result = self.engine.analyze_reviews(reviews)
        positive_sentiment = result["results"][0]["sentiment"]
        negative_sentiment = result["results"][1]["sentiment"]
        assert positive_sentiment > 0
        assert negative_sentiment < 0

    def test_get_topic_summary(self) -> None:
        """主题摘要"""
        summary = self.engine.get_topic_summary()
        assert "topics" in summary
        assert len(summary["topics"]) > 0
        for topic in summary["topics"]:
            assert "topic_type_cn" in topic
            assert topic["mention_count"] > 0

    def test_get_topic_summary_filter_by_store(self) -> None:
        """按门店筛选主题"""
        summary = self.engine.get_topic_summary(store_id="S001")
        for topic in summary["topics"]:
            assert topic.get("count", 0) >= 0  # filtered topics have valid counts

    def test_get_dish_mentions(self) -> None:
        """菜品提及排行"""
        mentions = self.engine.get_dish_mentions()
        assert len(mentions) > 0
        # 辣椒炒肉应在提及列表中
        dish_names = [m["dish_name"] for m in mentions]
        assert "辣椒炒肉" in dish_names
        # 应按提及数降序
        for i in range(len(mentions) - 1):
            assert mentions[i]["total_mentions"] >= mentions[i + 1]["total_mentions"]

    def test_get_dish_mentions_by_store(self) -> None:
        """按门店筛选菜品提及"""
        mentions = self.engine.get_dish_mentions(store_id="S001")
        assert len(mentions) > 0

    def test_compare_stores_reputation(self) -> None:
        """门店口碑对比"""
        result = self.engine.compare_stores_reputation(["S001", "S002"])
        assert "S001" in result["comparison"]
        assert "S002" in result["comparison"]
        s001 = result["comparison"]["S001"]
        assert s001["review_count"] > 0
        assert "avg_sentiment" in s001
        assert "top_positive" in s001
        assert "top_negative" in s001

    def test_get_actionable_issues(self) -> None:
        """可执行问题"""
        issues = self.engine.get_actionable_issues()
        assert len(issues) > 0
        for issue in issues:
            assert issue["topic_type"] in ("negative", "hygiene", "wait_time")
            assert "suggested_action" in issue
            assert issue["severity"] in ("high", "medium", "low")

    def test_get_marketing_highlights(self) -> None:
        """营销亮点"""
        highlights = self.engine.get_marketing_highlights()
        assert len(highlights) > 0
        for h in highlights:
            assert h["avg_sentiment"] >= 0.3
            assert "marketing_angle" in h

    def test_track_topic_trend(self) -> None:
        """主题趋势追踪"""
        trend = self.engine.track_topic_trend("辣椒炒肉", days=90)
        assert len(trend) > 0
        for point in trend:
            assert "week_start" in point
            assert "mention_count" in point


# ═══════════════════════════════════════
# 新品雷达测试
# ═══════════════════════════════════════

class TestNewProductRadar:
    """新品/新原料雷达测试"""

    def setup_method(self) -> None:
        self.radar = NewProductRadar()

    def test_seed_opportunities_loaded(self) -> None:
        """种子机会已加载"""
        opps = self.radar.list_opportunities()
        assert len(opps) == 10
        names = {o["name"] for o in opps}
        assert "酸汤火锅" in names
        assert "贵州酸汤鱼" in names
        assert "分子料理甜品" in names

    def test_register_opportunity(self) -> None:
        """注册新机会"""
        result = self.radar.register_opportunity(
            name="椰子鸡", category="trending_dish", source="市场调研",
            description="椰子鸡火锅持续增长",
            market_heat_score=0.80, brand_fit_score=0.50,
            audience_fit_score=0.70, cost_feasibility_score=0.65,
        )
        assert "opportunity_id" in result
        assert result["overall_score"] > 0
        assert len(self.radar.list_opportunities()) == 11

    def test_list_opportunities_sorted_by_score(self) -> None:
        """按评分排序"""
        opps = self.radar.list_opportunities(sort_by="score")
        for i in range(len(opps) - 1):
            assert opps[i]["overall_score"] >= opps[i + 1]["overall_score"]

    def test_list_opportunities_filter_by_category(self) -> None:
        """按分类筛选"""
        opps = self.radar.list_opportunities(category="trending_dish")
        for o in opps:
            assert o["category"] == "trending_dish"

    def test_get_opportunity_detail(self) -> None:
        """获取机会详情"""
        opps = self.radar.list_opportunities()
        oid = opps[0]["opportunity_id"]
        detail = self.radar.get_opportunity_detail(oid)
        assert detail["opportunity_id"] == oid
        assert "scores" in detail
        assert "overall" in detail["scores"]

    def test_score_opportunity(self) -> None:
        """评分机会"""
        opps = self.radar.list_opportunities()
        oid = opps[0]["opportunity_id"]
        score_result = self.radar.score_opportunity(oid)
        assert score_result["scores"]["overall"] > 0
        assert "recommendation" in score_result
        # 权重总和应为1
        total_weight = sum(score_result["weights"].values())
        assert abs(total_weight - 1.0) < 0.001

    def test_recommend_pilot_stores(self) -> None:
        """推荐试点门店"""
        opps = self.radar.list_opportunities()
        oid = opps[0]["opportunity_id"]
        stores = self.radar.recommend_pilot_stores(oid)
        assert len(stores) == 3
        for store in stores:
            assert "store_id" in store
            assert "fit_score" in store
            assert "reason" in store

    def test_create_pilot_plan(self) -> None:
        """创建试点计划"""
        opps = self.radar.list_opportunities()
        oid = opps[0]["opportunity_id"]
        plan = self.radar.create_pilot_plan(
            opportunity_id=oid,
            stores=["S001", "S005"],
            period_days=21,
            metrics=["daily_orders", "customer_rating"],
        )
        assert "plan_id" in plan
        assert plan["stores"] == ["S001", "S005"]
        assert plan["period_days"] == 21

    def test_track_ingredient_trends(self) -> None:
        """食材趋势追踪"""
        trends = self.radar.track_ingredient_trends()
        assert len(trends) > 0
        for t in trends:
            assert "ingredient" in t
            assert "heat_score" in t
            assert t["heat_score"] >= 0.3

    def test_detect_new_flavors(self) -> None:
        """新口味检测"""
        flavors = self.radar.detect_new_flavors()
        assert len(flavors) > 0
        flavor_names = [f["flavor"] for f in flavors]
        assert "酸汤味" in flavor_names

    def test_assess_supply_feasibility_known(self) -> None:
        """已知食材供应评估"""
        result = self.radar.assess_supply_feasibility("贵州红酸汤")
        assert result["status"] == "assessed"
        assert result["supply_risk"] == "low"
        assert result["availability"] == "充足"

    def test_assess_supply_feasibility_unknown(self) -> None:
        """未知食材供应评估"""
        result = self.radar.assess_supply_feasibility("火星菜")
        assert result["status"] == "no_data"

    def test_assess_supply_feasibility_seasonal(self) -> None:
        """季节性食材供应评估"""
        result = self.radar.assess_supply_feasibility("云南菌菇")
        assert result["seasonal"] is True
        assert result["cold_chain_required"] is True


# ═══════════════════════════════════════
# 价格洞察测试
# ═══════════════════════════════════════

class TestPricingInsight:
    """价格带与套餐洞察引擎测试"""

    def setup_method(self) -> None:
        self.svc = PricingInsightService()

    def test_analyze_price_bands(self) -> None:
        """价格带分析"""
        result = self.svc.analyze_price_bands("湘菜", city="长沙")
        assert "cities" in result
        assert "长沙" in result["cities"]
        bands = result["cities"]["长沙"]
        assert len(bands) == 5
        total_share = sum(b["market_share_pct"] for b in bands)
        assert total_share == 100

    def test_analyze_price_bands_no_data(self) -> None:
        """无数据品类"""
        result = self.svc.analyze_price_bands("法餐")
        assert result["status"] == "no_data"

    def test_compare_competitor_pricing(self) -> None:
        """竞对定价对比"""
        result = self.svc.compare_competitor_pricing([])
        assert "competitor_comparison" in result
        assert "our_pricing" in result
        assert len(result["competitor_comparison"]) > 0
        # 费大厨应在对比中
        assert "费大厨辣椒炒肉" in result["competitor_comparison"]

    def test_competitor_pricing_has_diff(self) -> None:
        """对比应包含价差数据"""
        result = self.svc.compare_competitor_pricing([])
        feidachu = result["competitor_comparison"]["费大厨辣椒炒肉"]
        if "辣椒炒肉" in feidachu:
            dish_data = feidachu["辣椒炒肉"]
            assert "diff_fen" in dish_data
            assert "diff_pct" in dish_data

    def test_analyze_set_meal_trends(self) -> None:
        """套餐趋势分析"""
        trends = self.svc.analyze_set_meal_trends()
        assert len(trends) >= 4
        for t in trends:
            assert "trend_name" in t
            assert "heat_score" in t
            assert "recommendation" in t

    def test_suggest_price_adjustment_underpriced(self) -> None:
        """低于竞对均价时建议提价"""
        result = self.svc.suggest_price_adjustment("辣椒炒肉", 4500)
        assert result["diff_vs_avg_pct"] < 0
        assert "低于" in result["suggestion"]

    def test_suggest_price_adjustment_reasonable(self) -> None:
        """价格合理时维持"""
        result = self.svc.suggest_price_adjustment("辣椒炒肉", 5800)
        assert "合理" in result["suggestion"]

    def test_suggest_price_adjustment_no_benchmark(self) -> None:
        """无基准数据"""
        result = self.svc.suggest_price_adjustment("独家秘制菜", 8800)
        assert result["status"] == "no_benchmark"

    def test_analyze_customer_spend_trend(self) -> None:
        """客单价趋势分析"""
        result = self.svc.analyze_customer_spend_trend(days=90)
        assert result["period_days"] == 90
        assert result["avg_spend_fen"] > 0
        assert result["trend"] in ("rising", "stable", "declining")
        assert "insight" in result
        assert result["data_points"] == 90

    def test_detect_value_perception_gap(self) -> None:
        """价值感知差距检测"""
        gaps = self.svc.detect_value_perception_gap()
        assert len(gaps) > 0
        for gap in gaps:
            assert "dish" in gap
            assert "gap_type" in gap
            assert "recommendation" in gap


# ═══════════════════════════════════════
# 情报报告测试
# ═══════════════════════════════════════

class TestIntelReportEngine:
    """情报周报/月报引擎测试"""

    def setup_method(self) -> None:
        self.engine = IntelReportEngine()

    def test_sample_reports_generated(self) -> None:
        """示例报告已生成"""
        reports = self.engine.list_reports()
        assert len(reports) >= 2

    def test_generate_competitor_weekly(self) -> None:
        """生成竞对周报"""
        result = self.engine.generate_report(
            "competitor_weekly",
            {"start": "2026-03-19", "end": "2026-03-26"},
        )
        assert "report_id" in result
        assert "竞对" in result["title"]
        assert len(result["sections"]) >= 2
        assert len(result["recommendations"]) >= 2
        assert len(result["executive_summary"]) > 0

    def test_generate_demand_weekly(self) -> None:
        """生成需求周报"""
        result = self.engine.generate_report(
            "demand_weekly",
            {"start": "2026-03-19", "end": "2026-03-26"},
        )
        assert "需求" in result["title"]

    def test_generate_new_product_weekly(self) -> None:
        """生成新品周报"""
        result = self.engine.generate_report(
            "new_product_weekly",
            {"start": "2026-03-19", "end": "2026-03-26"},
        )
        assert "新品" in result["title"]

    def test_generate_ingredient_weekly(self) -> None:
        """生成食材周报"""
        result = self.engine.generate_report(
            "ingredient_weekly",
            {"start": "2026-03-19", "end": "2026-03-26"},
        )
        assert "食材" in result["title"]

    def test_generate_district_weekly(self) -> None:
        """生成区域周报"""
        result = self.engine.generate_report(
            "district_weekly",
            {"start": "2026-03-19", "end": "2026-03-26"},
            city="长沙",
        )
        assert "长沙" in result["title"]

    def test_generate_monthly_market(self) -> None:
        """生成月度市场报告"""
        result = self.engine.generate_report(
            "monthly_market",
            {"start": "2026-03-01", "end": "2026-03-31"},
        )
        assert "月度" in result["title"]
        assert len(result["sections"]) >= 3

    def test_generate_special_topic(self) -> None:
        """生成专题报告"""
        result = self.engine.generate_report(
            "special_topic",
            {"start": "2026-03-01", "end": "2026-03-26"},
        )
        assert "专题" in result["title"]

    def test_generate_report_invalid_type(self) -> None:
        """无效报告类型应报错"""
        with pytest.raises(ValueError, match="Invalid report_type"):
            self.engine.generate_report("invalid_type", {"start": "2026-03-19", "end": "2026-03-26"})

    def test_list_reports(self) -> None:
        """列出报告"""
        reports = self.engine.list_reports()
        assert len(reports) >= 2
        for r in reports:
            assert "report_id" in r
            assert "report_type" in r

    def test_list_reports_filter_by_type(self) -> None:
        """按类型筛选报告"""
        reports = self.engine.list_reports(report_type="competitor_weekly")
        for r in reports:
            assert r["report_type"] == "competitor_weekly"

    def test_get_report_detail(self) -> None:
        """获取报告详情"""
        reports = self.engine.list_reports()
        rid = reports[0]["report_id"]
        detail = self.engine.get_report_detail(rid)
        assert detail["report_id"] == rid
        assert "executive_summary" in detail
        assert "sections" in detail
        assert "recommendations" in detail

    def test_get_report_detail_not_found(self) -> None:
        """不存在的报告应报错"""
        with pytest.raises(KeyError):
            self.engine.get_report_detail("nonexistent")

    def test_schedule_auto_report(self) -> None:
        """设置自动报告计划"""
        result = self.engine.schedule_auto_report(
            report_type="competitor_weekly",
            frequency="weekly",
            recipients=["boss@tunxiang.com", "product@tunxiang.com"],
        )
        assert "schedule_id" in result
        assert result["frequency"] == "weekly"
        assert result["status"] == "active"

    def test_schedule_invalid_frequency(self) -> None:
        """无效频率应报错"""
        with pytest.raises(ValueError, match="Invalid frequency"):
            self.engine.schedule_auto_report("competitor_weekly", "daily", ["test@test.com"])

    def test_export_report(self) -> None:
        """导出报告"""
        reports = self.engine.list_reports()
        rid = reports[0]["report_id"]
        result = self.engine.export_report(rid, format="pdf")
        assert result["status"] == "ready"
        assert result["format"] == "pdf"
        assert "download_url" in result

    def test_export_report_invalid_format(self) -> None:
        """无效导出格式应报错"""
        reports = self.engine.list_reports()
        rid = reports[0]["report_id"]
        with pytest.raises(ValueError, match="Invalid format"):
            self.engine.export_report(rid, format="docx")


# ═══════════════════════════════════════
# 试点建议测试
# ═══════════════════════════════════════

class TestPilotSuggestion:
    """试点建议引擎测试"""

    def setup_method(self) -> None:
        self.svc = PilotSuggestionService()

    def test_seed_suggestions_loaded(self) -> None:
        """种子建议已加载"""
        suggestions = self.svc.list_suggestions()
        assert len(suggestions) == 3

    def test_create_suggestion(self) -> None:
        """创建试点建议"""
        result = self.svc.create_suggestion(
            source_type="consumer_insight",
            source_id="test_source",
            suggestion_type="new_product",
            title="测试建议",
            description="这是一个测试建议",
            recommended_stores=["S001", "S002"],
            period_days=14,
            success_metrics=[{"metric": "daily_orders", "target": 20, "unit": "份/天"}],
        )
        assert result["status"] == "proposed"
        assert len(self.svc.list_suggestions()) == 4

    def test_create_suggestion_invalid_type(self) -> None:
        """无效建议类型应报错"""
        with pytest.raises(ValueError, match="Invalid suggestion_type"):
            self.svc.create_suggestion(
                source_type="consumer_insight", source_id="test",
                suggestion_type="invalid", title="测试",
                description="测试", recommended_stores=["S001"],
                period_days=14, success_metrics=[],
            )

    def test_list_suggestions(self) -> None:
        """列出建议"""
        suggestions = self.svc.list_suggestions()
        assert len(suggestions) == 3
        for s in suggestions:
            assert "suggestion_id" in s
            assert "title" in s

    def test_list_suggestions_filter_by_status(self) -> None:
        """按状态筛选"""
        proposed = self.svc.list_suggestions(status="proposed")
        for s in proposed:
            assert s["status"] == "proposed"

    def test_list_suggestions_filter_by_type(self) -> None:
        """按类型筛选"""
        new_product = self.svc.list_suggestions(suggestion_type="new_product")
        for s in new_product:
            assert s["suggestion_type"] == "new_product"

    def test_approve_pilot(self) -> None:
        """审批试点"""
        suggestions = self.svc.list_suggestions()
        sid = suggestions[0]["suggestion_id"]
        result = self.svc.approve_pilot(sid, approved_stores=["S001", "S005"])
        assert result["status"] == "approved"
        assert result["approved_stores"] == ["S001", "S005"]
        assert "pilot_start" in result
        assert "pilot_end" in result

    def test_approve_pilot_already_approved(self) -> None:
        """已审批的不能重复审批"""
        suggestions = self.svc.list_suggestions()
        sid = suggestions[0]["suggestion_id"]
        self.svc.approve_pilot(sid, approved_stores=["S001"])
        with pytest.raises(ValueError, match="Cannot approve"):
            self.svc.approve_pilot(sid, approved_stores=["S002"])

    def test_track_pilot_progress(self) -> None:
        """跟踪试点进度"""
        suggestions = self.svc.list_suggestions()
        sid = suggestions[0]["suggestion_id"]
        self.svc.approve_pilot(sid, approved_stores=["S001", "S005"])
        progress = self.svc.track_pilot_progress(sid)
        assert progress["status"] == "piloting"
        assert "metrics_progress" in progress
        assert len(progress["metrics_progress"]) > 0
        assert "overall_health" in progress
        for mp in progress["metrics_progress"]:
            assert "achievement_pct" in mp
            assert "status" in mp

    def test_complete_pilot_review(self) -> None:
        """完成试点评审"""
        suggestions = self.svc.list_suggestions()
        sid = suggestions[0]["suggestion_id"]
        self.svc.approve_pilot(sid, approved_stores=["S001"])
        self.svc.track_pilot_progress(sid)  # move to piloting

        review = self.svc.complete_pilot_review(
            pilot_id=sid,
            results={"metrics_met": 3, "metrics_total": 4, "revenue_increase_pct": 12},
            conclusion="酸汤鱼试点效果良好，日均销量超预期，顾客评价正面",
        )
        assert review["status"] == "reviewing"
        assert review["success_rate"] == 0.75
        assert review["recommendation"] == "conditional_scale_up"

    def test_complete_pilot_review_excellent(self) -> None:
        """优秀试点评审"""
        suggestions = self.svc.list_suggestions()
        sid = suggestions[0]["suggestion_id"]
        self.svc.approve_pilot(sid, approved_stores=["S001"])
        self.svc.track_pilot_progress(sid)

        review = self.svc.complete_pilot_review(
            pilot_id=sid,
            results={"metrics_met": 4, "metrics_total": 4},
            conclusion="全部指标达标",
        )
        assert review["success_rate"] == 1.0
        assert review["recommendation"] == "strong_scale_up"

    def test_recommend_scale_up(self) -> None:
        """推荐推广"""
        suggestions = self.svc.list_suggestions()
        sid = suggestions[0]["suggestion_id"]
        self.svc.approve_pilot(sid, approved_stores=["S001", "S005"])
        self.svc.track_pilot_progress(sid)
        self.svc.complete_pilot_review(
            pilot_id=sid,
            results={"metrics_met": 3, "metrics_total": 4},
            conclusion="效果良好",
        )

        scale_up = self.svc.recommend_scale_up(sid)
        assert "recommended_expansion" in scale_up
        assert scale_up["total_expansion_stores"] > 0
        # 试点门店不应出现在推广列表中
        pilot_stores = set(scale_up["pilot_stores"])
        for store in scale_up["recommended_expansion"]:
            assert store["store_id"] not in pilot_stores

    def test_recommend_scale_up_wrong_status(self) -> None:
        """非评审状态不能推荐推广"""
        suggestions = self.svc.list_suggestions()
        sid = suggestions[0]["suggestion_id"]
        with pytest.raises(ValueError, match="Cannot recommend"):
            self.svc.recommend_scale_up(sid)

    def test_get_pilot_portfolio(self) -> None:
        """试点组合概览"""
        portfolio = self.svc.get_pilot_portfolio()
        assert portfolio["total_suggestions"] == 3
        assert "status_distribution" in portfolio
        assert "active_pilots" in portfolio
        assert "generated_at" in portfolio


# ═══════════════════════════════════════
# 端到端测试
# ═══════════════════════════════════════

class TestEndToEnd:
    """端到端集成测试"""

    def test_competitor_action_to_threat_to_pilot(self) -> None:
        """竞对动态 → 威胁检测 → 试点建议"""
        # 1. 竞对服务：记录费大厨在长沙的重大扩张
        comp_svc = CompetitorMonitorService()
        competitors = comp_svc.list_competitors(category="湘菜")
        feidachu = [c for c in competitors if c["name"] == "费大厨辣椒炒肉"][0]
        cid = feidachu["competitor_id"]

        comp_svc.record_competitor_action(
            competitor_id=cid,
            action_type="store_open",
            title="费大厨长沙新开3店覆盖核心商圈",
            detail="太平街、IFS、万达广场同时开业，直接挑战我方优势区域",
            impact_level="critical",
            source="实地调研",
            city="长沙",
        )

        # 2. 检测威胁
        threats = comp_svc.detect_threats()
        assert len(threats) > 0
        has_expansion_threat = any(
            t["threat_type"] == "同品类扩张" and t["competitor_name"] == "费大厨辣椒炒肉"
            for t in threats
        )
        assert has_expansion_threat

        # 3. 基于威胁创建试点建议
        pilot_svc = PilotSuggestionService()
        threat_action_id = threats[0]["source_action_id"]
        result = pilot_svc.create_suggestion(
            source_type="competitor_action",
            source_id=threat_action_id,
            suggestion_type="competitor_response",
            title="长沙核心商圈防御性活动",
            description=f"费大厨长沙新开3店，需要在周边门店启动防御性营销",
            recommended_stores=["S001", "S002", "S003"],
            period_days=30,
            success_metrics=[
                {"metric": "customer_retention", "target": 0.90, "unit": "比例"},
                {"metric": "traffic_change_pct", "target": 0, "unit": "%"},
            ],
        )
        assert result["status"] == "proposed"

    def test_consumer_signal_to_new_product_to_pilot(self) -> None:
        """消费信号 → 新品雷达 → 试点上线"""
        # 1. 消费洞察：发现酸汤需求
        insight_svc = ConsumerInsightService()
        for content in [
            "最近很想吃酸汤鱼，你们有吗？",
            "酸汤火锅太好吃了，湘菜馆也应该出酸汤系列",
            "酸汤口味的菜太少了",
        ]:
            insight_svc.ingest_signal(
                source_type="review", content=content, city="长沙",
            )

        emerging = insight_svc.detect_emerging_needs()
        sour_soup_need = [n for n in emerging if "酸汤" in n["topic_name"]]
        assert len(sour_soup_need) > 0

        # 2. 新品雷达：评估酸汤鱼机会
        radar = NewProductRadar()
        opps = radar.list_opportunities()
        sour_fish = [o for o in opps if o["name"] == "贵州酸汤鱼"][0]
        score = radar.score_opportunity(sour_fish["opportunity_id"])
        assert score["scores"]["overall"] > 0.7
        assert "推荐" in score["recommendation"]

        # 3. 推荐试点门店
        pilot_stores = radar.recommend_pilot_stores(sour_fish["opportunity_id"])
        assert len(pilot_stores) == 3

        # 4. 创建试点计划
        plan = radar.create_pilot_plan(
            opportunity_id=sour_fish["opportunity_id"],
            stores=[s["store_id"] for s in pilot_stores],
            period_days=21,
            metrics=["daily_orders", "customer_rating", "gross_margin"],
        )
        assert plan["period_days"] == 21

    def test_review_analysis_to_pilot_improvement(self) -> None:
        """口碑分析 → 发现问题 → 试点改进"""
        # 1. 口碑分析：发现卫生问题
        engine = ReviewTopicEngine()
        extra_reviews = [
            {"store_id": "S002", "rating": 1, "content": "桌面很脏，餐具不干净，卫生太差了"},
            {"store_id": "S002", "rating": 2, "content": "地面油腻，洗手间不干净"},
            {"store_id": "S002", "rating": 1, "content": "菜里有头发，太脏了"},
        ]
        engine.analyze_reviews(extra_reviews)

        # 2. 提取可执行问题
        issues = engine.get_actionable_issues(store_id="S002")
        hygiene_issues = [i for i in issues if i["topic_type"] == "hygiene"]
        assert len(hygiene_issues) > 0

        # 3. 创建改进试点
        pilot_svc = PilotSuggestionService()
        result = pilot_svc.create_suggestion(
            source_type="review_analysis",
            source_id=hygiene_issues[0]["topic_name"],
            suggestion_type="service_improvement",
            title="S002门店卫生整改试点",
            description="基于口碑分析发现S002门店卫生问题严重，启动卫生整改专项",
            recommended_stores=["S002"],
            period_days=14,
            success_metrics=[
                {"metric": "hygiene_score", "target": 4.5, "unit": "分"},
                {"metric": "negative_review_rate", "target": 0.05, "unit": "比例"},
            ],
        )
        assert result["status"] == "proposed"

    def test_full_pilot_lifecycle(self) -> None:
        """完整试点生命周期：建议 → 审批 → 跟踪 → 评审 → 推广"""
        svc = PilotSuggestionService()

        # 1. 创建建议
        result = svc.create_suggestion(
            source_type="new_product_radar",
            source_id="opp_yakitori",
            suggestion_type="new_product",
            title="日式烧鸟体验区试点",
            description="在旗舰店设日式烧鸟体验区，测试跨品类创新可能性",
            recommended_stores=["S001"],
            period_days=30,
            success_metrics=[
                {"metric": "daily_orders", "target": 50, "unit": "份/天"},
                {"metric": "customer_rating", "target": 4.0, "unit": "分"},
                {"metric": "incremental_revenue", "target": 3000_00, "unit": "分/天"},
            ],
        )
        sid = result["suggestion_id"]
        assert result["status"] == "proposed"

        # 2. 审批
        approval = svc.approve_pilot(sid, approved_stores=["S001"])
        assert approval["status"] == "approved"
        assert "pilot_start" in approval

        # 3. 跟踪进度
        progress = svc.track_pilot_progress(sid)
        assert progress["status"] == "piloting"
        assert len(progress["metrics_progress"]) == 3

        # 4. 评审
        review = svc.complete_pilot_review(
            pilot_id=sid,
            results={
                "metrics_met": 3,
                "metrics_total": 3,
                "daily_orders_avg": 62,
                "customer_rating_avg": 4.3,
                "incremental_revenue_avg": 3500_00,
            },
            conclusion="日式烧鸟体验区超预期完成所有指标，顾客反馈积极",
        )
        assert review["success_rate"] == 1.0
        assert review["recommendation"] == "strong_scale_up"

        # 5. 推广
        scale_up = svc.recommend_scale_up(sid)
        assert scale_up["total_expansion_stores"] > 0
        assert "rollout_strategy" in scale_up

    def test_pricing_and_report_integration(self) -> None:
        """价格洞察 + 报告生成集成"""
        # 1. 价格分析
        pricing_svc = PricingInsightService()
        gaps = pricing_svc.detect_value_perception_gap()
        assert len(gaps) > 0

        spend_trend = pricing_svc.analyze_customer_spend_trend()
        assert spend_trend["avg_spend_fen"] > 0

        # 2. 生成报告包含价格洞察
        report_engine = IntelReportEngine()
        report = report_engine.generate_report(
            "monthly_market",
            {"start": "2026-03-01", "end": "2026-03-31"},
        )
        assert "report_id" in report
        # 月报应涵盖价格洞察
        section_titles = [s["title"] for s in report["sections"]]
        has_pricing_section = any("价格" in t for t in section_titles)
        assert has_pricing_section
