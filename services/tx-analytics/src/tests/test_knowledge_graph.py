"""知识图谱 + 自然语言查询 完整测试"""
import pytest

from ..services.knowledge_graph import (
    KnowledgeGraphService,
    NLQueryResult,
    QueryIntent,
    seed_knowledge_graph,
)


# ─── Fixtures ───


@pytest.fixture
def kg() -> KnowledgeGraphService:
    """空的知识图谱"""
    return KnowledgeGraphService()


@pytest.fixture
def seeded_kg() -> KnowledgeGraphService:
    """预填充种子数据的知识图谱"""
    return seed_knowledge_graph()


# ══════════════════════════════════════
# 1. 图谱构建与遍历
# ══════════════════════════════════════


class TestGraphConstruction:
    def test_add_and_get_entity(self, kg: KnowledgeGraphService) -> None:
        result = kg.add_entity("store", "s1", {"name": "测试店", "city": "长沙"})
        assert result["ok"] is True

        entity = kg.get_entity("store", "s1")
        assert entity["name"] == "测试店"
        assert entity["city"] == "长沙"
        assert entity["_type"] == "store"
        assert entity["_id"] == "s1"

    def test_get_nonexistent_entity(self, kg: KnowledgeGraphService) -> None:
        entity = kg.get_entity("store", "nonexistent")
        assert entity == {}

    def test_add_relationship(self, kg: KnowledgeGraphService) -> None:
        kg.add_entity("store", "s1", {"name": "芙蓉路店"})
        kg.add_entity("city", "changsha", {"name": "长沙"})

        result = kg.add_relationship("store", "s1", "LOCATED_IN", "city", "changsha")
        assert result["ok"] is True
        assert result["relationship"] == "LOCATED_IN"

    def test_get_neighbors_out(self, kg: KnowledgeGraphService) -> None:
        kg.add_entity("store", "s1", {"name": "芙蓉路店"})
        kg.add_entity("dish", "d1", {"name": "剁椒鱼头"})
        kg.add_entity("dish", "d2", {"name": "清蒸鲈鱼"})
        kg.add_relationship("store", "s1", "SERVES", "dish", "d1")
        kg.add_relationship("store", "s1", "SERVES", "dish", "d2")

        neighbors = kg.get_neighbors("store", "s1", rel_type="SERVES")
        assert len(neighbors) == 2
        names = {n["entity"]["name"] for n in neighbors}
        assert "剁椒鱼头" in names
        assert "清蒸鲈鱼" in names

    def test_get_neighbors_in(self, kg: KnowledgeGraphService) -> None:
        kg.add_entity("store", "s1", {"name": "芙蓉路店"})
        kg.add_entity("dish", "d1", {"name": "剁椒鱼头"})
        kg.add_relationship("store", "s1", "SERVES", "dish", "d1")

        neighbors = kg.get_neighbors("dish", "d1", direction="in")
        assert len(neighbors) == 1
        assert neighbors[0]["entity"]["name"] == "芙蓉路店"

    def test_get_neighbors_both(self, kg: KnowledgeGraphService) -> None:
        kg.add_entity("store", "s1", {"name": "芙蓉路店"})
        kg.add_entity("city", "cs", {"name": "长沙"})
        kg.add_entity("dish", "d1", {"name": "剁椒鱼头"})
        kg.add_relationship("store", "s1", "LOCATED_IN", "city", "cs")
        kg.add_relationship("store", "s1", "SERVES", "dish", "d1")

        # 门店的所有邻居（out方向）
        neighbors = kg.get_neighbors("store", "s1", direction="out")
        assert len(neighbors) == 2

    def test_get_neighbors_filter_rel_type(self, kg: KnowledgeGraphService) -> None:
        kg.add_entity("store", "s1", {"name": "芙蓉路店"})
        kg.add_entity("city", "cs", {"name": "长沙"})
        kg.add_entity("dish", "d1", {"name": "剁椒鱼头"})
        kg.add_relationship("store", "s1", "LOCATED_IN", "city", "cs")
        kg.add_relationship("store", "s1", "SERVES", "dish", "d1")

        neighbors = kg.get_neighbors("store", "s1", rel_type="LOCATED_IN")
        assert len(neighbors) == 1
        assert neighbors[0]["entity"]["name"] == "长沙"

    def test_delete_entity(self, kg: KnowledgeGraphService) -> None:
        kg.add_entity("store", "s1", {"name": "测试店"})
        kg.add_entity("dish", "d1", {"name": "剁椒鱼头"})
        kg.add_relationship("store", "s1", "SERVES", "dish", "d1")

        result = kg.delete_entity("store", "s1")
        assert result["ok"] is True

        assert kg.get_entity("store", "s1") == {}
        # 菜品仍然存在
        assert kg.get_entity("dish", "d1")["name"] == "剁椒鱼头"

    def test_delete_nonexistent_entity(self, kg: KnowledgeGraphService) -> None:
        result = kg.delete_entity("store", "nonexistent")
        assert result["ok"] is False


# ══════════════════════════════════════
# 2. 知识注入
# ══════════════════════════════════════


class TestKnowledgeIngestion:
    def test_ingest_store_data(self, kg: KnowledgeGraphService) -> None:
        data = {
            "store": {
                "id": "s1", "name": "测试店", "city": "长沙",
                "brand": "尝在一起", "business_type": "海鲜酒楼",
            },
            "dishes": [
                {"id": "d1", "name": "剁椒鱼头", "category": "热菜", "price": 128, "cost": 42,
                 "ingredients": [{"id": "i1", "name": "鳙鱼头"}]},
                {"id": "d2", "name": "清蒸鲈鱼", "category": "热菜", "price": 98, "cost": 35},
            ],
            "metrics": [
                {"id": "m1", "date": "2026-03-01", "revenue": 30000, "turnover_rate": 2.3},
            ],
        }
        result = kg.ingest_store_data(data)
        assert result["ok"] is True

        counts = result["ingested"]
        assert counts["stores"] == 1
        assert counts["dishes"] == 2
        assert counts["ingredients"] == 1
        assert counts["metrics"] == 1

        # 验证实体
        assert kg.get_entity("store", "s1")["name"] == "测试店"
        assert kg.get_entity("dish", "d1")["name"] == "剁椒鱼头"
        assert kg.get_entity("city", "长沙")["name"] == "长沙"
        assert kg.get_entity("brand", "尝在一起")["name"] == "尝在一起"

        # 验证关系
        neighbors = kg.get_neighbors("store", "s1", rel_type="SERVES")
        assert len(neighbors) == 2

    def test_ingest_decision_data(self, kg: KnowledgeGraphService) -> None:
        kg.add_entity("store", "s1", {"name": "测试店"})
        decision = {
            "id": "dec_001",
            "agent_id": "discount_guard",
            "agent_name": "折扣守护Agent",
            "store_id": "s1",
            "date": "2026-03-01",
            "description": "检测到异常折扣",
            "metric": "profit_margin",
            "action": "拦截折扣",
            "outcome": {"improvement_pct": 3.2, "applied": True},
        }
        result = kg.ingest_decision_data(decision)
        assert result["ok"] is True

        # 验证决策实体
        dec = kg.get_entity("decision", "dec_001")
        assert dec["description"] == "检测到异常折扣"

        # 验证关系
        neighbors = kg.get_neighbors("decision", "dec_001", rel_type="ABOUT")
        assert len(neighbors) == 1
        assert neighbors[0]["entity"]["name"] == "测试店"

    def test_ingest_best_practice(self, kg: KnowledgeGraphService) -> None:
        kg.add_entity("store", "s1", {"name": "测试店"})
        practice = {
            "id": "bp_001",
            "title": "午高峰提前备菜",
            "description": "11点前完成80%备料",
            "metric": "turnover_rate",
            "improvement_pct": 15,
            "discovered_at_store": "s1",
            "applicable_to": ["海鲜酒楼", "中餐厅"],
        }
        result = kg.ingest_best_practice(practice)
        assert result["ok"] is True

        bp = kg.get_entity("best_practice", "bp_001")
        assert bp["title"] == "午高峰提前备菜"

    def test_graph_stats(self, seeded_kg: KnowledgeGraphService) -> None:
        stats = seeded_kg.get_graph_stats()
        assert stats["total_entities"] > 0
        assert stats["total_relationships"] > 0
        assert "store" in stats["entities_by_type"]
        assert stats["entities_by_type"]["store"] == 5
        assert stats["entities_by_type"]["dish"] == 30
        assert stats["last_updated"] is not None


# ══════════════════════════════════════
# 3. 种子数据完整性
# ══════════════════════════════════════


class TestSeedData:
    def test_seed_stores(self, seeded_kg: KnowledgeGraphService) -> None:
        stores = seeded_kg._entities.get("store", {})
        assert len(stores) == 5
        store_names = {s["name"] for s in stores.values()}
        assert "长沙芙蓉路店" in store_names
        assert "深圳南山店" in store_names
        assert "北京国贸店" in store_names

    def test_seed_dishes(self, seeded_kg: KnowledgeGraphService) -> None:
        dishes = seeded_kg._entities.get("dish", {})
        assert len(dishes) == 30
        dish_names = {d["name"] for d in dishes.values()}
        assert "剁椒鱼头" in dish_names
        assert "清蒸鲈鱼" in dish_names

    def test_seed_metrics(self, seeded_kg: KnowledgeGraphService) -> None:
        metrics = seeded_kg._entities.get("store_metric", {})
        # 5 stores * 30 days = 150 metrics
        assert len(metrics) == 150

    def test_seed_decisions(self, seeded_kg: KnowledgeGraphService) -> None:
        decisions = seeded_kg._entities.get("decision", {})
        assert len(decisions) == 20

    def test_seed_best_practices(self, seeded_kg: KnowledgeGraphService) -> None:
        practices = seeded_kg._entities.get("best_practice", {})
        assert len(practices) == 5

    def test_seed_suppliers(self, seeded_kg: KnowledgeGraphService) -> None:
        suppliers = seeded_kg._entities.get("supplier", {})
        assert len(suppliers) == 5

    def test_seed_ingredients(self, seeded_kg: KnowledgeGraphService) -> None:
        ingredients = seeded_kg._entities.get("ingredient", {})
        assert len(ingredients) >= 10


# ══════════════════════════════════════
# 4. 意图解析
# ══════════════════════════════════════


class TestIntentParsing:
    def test_parse_aggregate_metric_with_city(self, seeded_kg: KnowledgeGraphService) -> None:
        intent = seeded_kg.parse_query_intent("长沙地区海鲜酒楼的平均翻台率是多少？")
        assert intent.intent_type == "aggregate_metric"
        assert intent.entities.get("city") == "长沙"
        assert intent.entities.get("business_type") == "海鲜酒楼"
        assert intent.metric == "turnover_rate"

    def test_parse_aggregate_metric_simple(self, seeded_kg: KnowledgeGraphService) -> None:
        intent = seeded_kg.parse_query_intent("翻台率平均是多少")
        assert intent.intent_type == "aggregate_metric"
        assert intent.metric == "turnover_rate"

    def test_parse_dish_pricing(self, seeded_kg: KnowledgeGraphService) -> None:
        intent = seeded_kg.parse_query_intent("剁椒鱼头的最优定价区间是多少？")
        assert intent.intent_type == "dish_analysis"
        assert intent.entities.get("dish") == "剁椒鱼头"

    def test_parse_dish_performance(self, seeded_kg: KnowledgeGraphService) -> None:
        intent = seeded_kg.parse_query_intent("剁椒鱼头卖得怎么样")
        assert intent.intent_type == "dish_analysis"
        assert intent.entities.get("dish") == "剁椒鱼头"

    def test_parse_dish_cost(self, seeded_kg: KnowledgeGraphService) -> None:
        intent = seeded_kg.parse_query_intent("剁椒鱼头的毛利率")
        assert intent.intent_type == "dish_analysis"
        assert intent.entities.get("dish") == "剁椒鱼头"

    def test_parse_ranking(self, seeded_kg: KnowledgeGraphService) -> None:
        intent = seeded_kg.parse_query_intent("哪些门店的人效最高？")
        assert intent.intent_type == "ranking"
        assert intent.metric == "labor_efficiency"

    def test_parse_ranking_lowest(self, seeded_kg: KnowledgeGraphService) -> None:
        intent = seeded_kg.parse_query_intent("哪些门店的翻台率最低？")
        assert intent.intent_type == "ranking"
        assert intent.metric == "turnover_rate"
        assert "bottom" in intent.aggregation

    def test_parse_trend_decline(self, seeded_kg: KnowledgeGraphService) -> None:
        intent = seeded_kg.parse_query_intent("上周营业额为什么下降了？")
        assert intent.intent_type == "trend"
        assert intent.metric == "revenue"

    def test_parse_trend_recent(self, seeded_kg: KnowledgeGraphService) -> None:
        intent = seeded_kg.parse_query_intent("最近客流量变化趋势")
        assert intent.intent_type == "trend"
        assert intent.metric == "customer_count"

    def test_parse_recommendation(self, seeded_kg: KnowledgeGraphService) -> None:
        intent = seeded_kg.parse_query_intent("推荐适合200人宴会的菜单")
        assert intent.intent_type == "recommendation"
        assert intent.entities.get("guest_count") == 200
        assert intent.entities.get("event_type") == "宴会"

    def test_parse_benchmark(self, seeded_kg: KnowledgeGraphService) -> None:
        intent = seeded_kg.parse_query_intent("我们的毛利率跟行业平均比怎么样？")
        assert intent.intent_type == "benchmark"
        assert intent.metric == "profit_margin"

    def test_parse_benchmark_industry(self, seeded_kg: KnowledgeGraphService) -> None:
        intent = seeded_kg.parse_query_intent("行业平均翻台率")
        assert intent.intent_type == "benchmark"
        assert intent.metric == "turnover_rate"

    def test_parse_best_practice(self, seeded_kg: KnowledgeGraphService) -> None:
        intent = seeded_kg.parse_query_intent("翻台率怎么提升？")
        assert intent.intent_type == "best_practice"
        assert intent.metric == "turnover_rate"

    def test_parse_best_practice_how_to(self, seeded_kg: KnowledgeGraphService) -> None:
        intent = seeded_kg.parse_query_intent("如何改善人效？")
        assert intent.intent_type == "best_practice"
        assert intent.metric == "labor_efficiency"

    def test_parse_unknown(self, seeded_kg: KnowledgeGraphService) -> None:
        intent = seeded_kg.parse_query_intent("今天天气怎么样？")
        assert intent.intent_type == "unknown"


# ══════════════════════════════════════
# 5. 自然语言查询端到端
# ══════════════════════════════════════


class TestNLQueryEndToEnd:
    def test_query_changsha_turnover(self, seeded_kg: KnowledgeGraphService) -> None:
        """长沙地区海鲜酒楼的平均翻台率是多少？"""
        result = seeded_kg.query_natural_language("长沙地区海鲜酒楼的平均翻台率是多少？")
        assert isinstance(result, NLQueryResult)
        assert result.confidence >= 0.5
        assert "翻台率" in result.answer
        assert result.query_ms >= 0
        assert result.data["type"] == "aggregate"
        # 应该只包含长沙的2家门店
        assert result.data["result"]["count"] == 2

    def test_query_dish_pricing(self, seeded_kg: KnowledgeGraphService) -> None:
        """剁椒鱼头的最优定价区间是多少？"""
        result = seeded_kg.query_natural_language("剁椒鱼头的最优定价区间是多少？")
        assert "剁椒鱼头" in result.answer
        assert result.data["found"] is True
        price_range = result.data.get("price_range", {})
        assert price_range.get("optimal_low", 0) > 0
        assert price_range.get("optimal_high", 0) > price_range.get("optimal_low", 0)

    def test_query_labor_efficiency_ranking(self, seeded_kg: KnowledgeGraphService) -> None:
        """哪些门店的人效最高？"""
        result = seeded_kg.query_natural_language("哪些门店的人效最高？")
        assert "人效" in result.answer
        assert result.data["type"] == "ranking"
        items = result.data.get("items", [])
        assert len(items) >= 1
        # 验证按降序排列
        if len(items) >= 2:
            assert items[0]["value"] >= items[1]["value"]

    def test_query_revenue_trend(self, seeded_kg: KnowledgeGraphService) -> None:
        """上周营业额为什么下降了？"""
        result = seeded_kg.query_natural_language("上周营业额为什么下降了？")
        assert "营业额" in result.answer
        assert result.data["type"] == "trend"
        assert "possible_causes" in result.data
        assert len(result.data["possible_causes"]) > 0

    def test_query_menu_recommendation(self, seeded_kg: KnowledgeGraphService) -> None:
        """推荐适合200人宴会的菜单"""
        result = seeded_kg.query_natural_language("推荐适合200人宴会的菜单")
        assert "200" in result.answer
        assert result.data["type"] == "recommendation"
        assert result.data["guest_count"] == 200
        assert result.data["event_type"] == "宴会"
        menu = result.data.get("menu", [])
        assert len(menu) > 0
        assert result.data["total_price"] > 0
        assert result.data["per_person"] > 0

    def test_query_benchmark_comparison(self, seeded_kg: KnowledgeGraphService) -> None:
        """我们的毛利率跟行业平均比怎么样？"""
        result = seeded_kg.query_natural_language("我们的毛利率跟行业平均比怎么样？")
        assert "毛利率" in result.answer
        assert result.data["type"] == "benchmark"
        benchmark = result.data.get("benchmark", {})
        assert "avg" in benchmark
        assert "p50" in benchmark
        assert "p90" in benchmark

    def test_query_best_practice(self, seeded_kg: KnowledgeGraphService) -> None:
        """翻台率怎么提升？"""
        result = seeded_kg.query_natural_language("翻台率怎么提升？")
        assert "翻台率" in result.answer
        assert result.data["type"] == "best_practice"
        practices = result.data.get("practices", [])
        assert len(practices) >= 1
        # 应该找到"午高峰提前备菜制度"
        titles = [p.get("title", "") for p in practices]
        assert any("备菜" in t for t in titles)

    def test_query_has_suggestions(self, seeded_kg: KnowledgeGraphService) -> None:
        """查询结果应包含后续推荐问题"""
        result = seeded_kg.query_natural_language("翻台率平均是多少")
        assert len(result.suggestions) > 0

    def test_query_has_sources(self, seeded_kg: KnowledgeGraphService) -> None:
        """查询结果应包含数据来源"""
        result = seeded_kg.query_natural_language("哪些门店的人效最高？")
        assert len(result.sources) > 0

    def test_query_unknown_fallback(self, seeded_kg: KnowledgeGraphService) -> None:
        """无法理解的问题应返回兜底回答"""
        result = seeded_kg.query_natural_language("这是一个随机问题abc")
        assert result.confidence < 0.5
        assert "抱歉" in result.answer


# ══════════════════════════════════════
# 6. 答案生成质量
# ══════════════════════════════════════


class TestAnswerGeneration:
    def test_aggregate_answer_format(self, seeded_kg: KnowledgeGraphService) -> None:
        result = seeded_kg.query_natural_language("翻台率平均是多少")
        assert "翻台率" in result.answer
        assert "次/天" in result.answer
        assert "门店" in result.answer

    def test_dish_answer_contains_price(self, seeded_kg: KnowledgeGraphService) -> None:
        result = seeded_kg.query_natural_language("剁椒鱼头的最优定价区间是多少？")
        assert "定价" in result.answer or "价" in result.answer
        assert "元" in result.answer

    def test_ranking_answer_numbered_list(self, seeded_kg: KnowledgeGraphService) -> None:
        result = seeded_kg.query_natural_language("哪些门店的人效最高？")
        assert "1." in result.answer
        assert "元/人/天" in result.answer

    def test_benchmark_answer_percentile(self, seeded_kg: KnowledgeGraphService) -> None:
        result = seeded_kg.query_natural_language("我们的毛利率跟行业平均比怎么样？")
        assert "行业" in result.answer
        assert "%" in result.answer

    def test_recommendation_answer_has_categories(self, seeded_kg: KnowledgeGraphService) -> None:
        result = seeded_kg.query_natural_language("推荐适合200人宴会的菜单")
        # 答案应包含菜品分类
        assert "热菜" in result.answer or "凉菜" in result.answer
        assert "人均" in result.answer

    def test_table_format(self, seeded_kg: KnowledgeGraphService) -> None:
        """表格格式输出"""
        intent = seeded_kg.parse_query_intent("哪些门店的人效最高？")
        query_result = seeded_kg.execute_graph_query(intent)
        table = seeded_kg.generate_answer("哪些门店的人效最高？", query_result, format="table")
        assert "| 排名 |" in table
        assert "| 1 |" in table

    def test_chart_data_format(self, seeded_kg: KnowledgeGraphService) -> None:
        """图表数据格式输出"""
        intent = seeded_kg.parse_query_intent("哪些门店的人效最高？")
        query_result = seeded_kg.execute_graph_query(intent)
        chart = seeded_kg.generate_answer("哪些门店的人效最高？", query_result, format="chart_data")
        assert "ranking" in chart  # JSON 字符串中应包含 type


# ══════════════════════════════════════
# 7. 最佳实践发现
# ══════════════════════════════════════


class TestBestPracticeDiscovery:
    def test_discover_practices_for_turnover(self, seeded_kg: KnowledgeGraphService) -> None:
        practices = seeded_kg.discover_best_practices("turnover_rate", min_improvement=0.05)
        assert len(practices) >= 1
        # 所有发现的实践应有正的改善
        for p in practices:
            assert p["improvement_pct"] > 0

    def test_discover_practices_sorted(self, seeded_kg: KnowledgeGraphService) -> None:
        practices = seeded_kg.discover_best_practices("profit_margin", min_improvement=0.01)
        if len(practices) >= 2:
            assert practices[0]["improvement_pct"] >= practices[1]["improvement_pct"]

    def test_get_applicable_practices_existing_store(self, seeded_kg: KnowledgeGraphService) -> None:
        practices = seeded_kg.get_applicable_practices("store_cs_furong")
        assert len(practices) >= 1
        # 海鲜酒楼的实践应该被返回
        for p in practices:
            applicable = p.get("applicable_to", [])
            assert "海鲜酒楼" in applicable or "all" in applicable

    def test_get_applicable_practices_nonexistent(self, seeded_kg: KnowledgeGraphService) -> None:
        practices = seeded_kg.get_applicable_practices("nonexistent_store")
        assert practices == []


# ══════════════════════════════════════
# 8. 行业基准
# ══════════════════════════════════════


class TestBenchmark:
    def test_get_benchmark_turnover(self, seeded_kg: KnowledgeGraphService) -> None:
        benchmark = seeded_kg.get_benchmark("turnover_rate")
        assert "avg" in benchmark
        assert "p25" in benchmark
        assert "p50" in benchmark
        assert "p75" in benchmark
        assert "p90" in benchmark
        assert "best_in_class" in benchmark
        assert benchmark["avg"] > 0
        assert benchmark["p25"] <= benchmark["p50"] <= benchmark["p75"] <= benchmark["p90"]

    def test_get_benchmark_with_city_filter(self, seeded_kg: KnowledgeGraphService) -> None:
        benchmark = seeded_kg.get_benchmark("revenue", city="长沙")
        assert benchmark["sample_size"] == 2  # 长沙有2家店

    def test_get_benchmark_unknown_metric_returns_default(self, seeded_kg: KnowledgeGraphService) -> None:
        benchmark = seeded_kg.get_benchmark("nonexistent_metric")
        # 没有数据时返回默认基准
        assert "avg" in benchmark

    def test_compare_to_benchmark(self, seeded_kg: KnowledgeGraphService) -> None:
        result = seeded_kg.compare_to_benchmark(
            "store_bj_guomao", ["turnover_rate", "revenue"]
        )
        assert result["ok"] is True
        comparisons = result["comparisons"]
        assert "turnover_rate" in comparisons
        assert "revenue" in comparisons
        # 北京国贸店指标最高，应该排名靠前
        tr = comparisons["turnover_rate"]
        assert tr["store_value"] is not None
        assert "行业" in tr["comparison"]

    def test_compare_nonexistent_store(self, seeded_kg: KnowledgeGraphService) -> None:
        result = seeded_kg.compare_to_benchmark("nonexistent", ["revenue"])
        assert result["ok"] is False


# ══════════════════════════════════════
# 9. 图查询执行
# ══════════════════════════════════════


class TestGraphQueryExecution:
    def test_execute_aggregate_query(self, seeded_kg: KnowledgeGraphService) -> None:
        intent = QueryIntent(
            intent_type="aggregate_metric",
            metric="turnover_rate",
            filters={"city": "长沙"},
        )
        result = seeded_kg.execute_graph_query(intent)
        assert result["type"] == "aggregate"
        assert result["result"]["count"] == 2

    def test_execute_ranking_query(self, seeded_kg: KnowledgeGraphService) -> None:
        intent = QueryIntent(
            intent_type="ranking",
            metric="revenue",
            aggregation="top_3",
        )
        result = seeded_kg.execute_graph_query(intent)
        assert result["type"] == "ranking"
        assert len(result["items"]) <= 3

    def test_execute_dish_query(self, seeded_kg: KnowledgeGraphService) -> None:
        intent = QueryIntent(
            intent_type="dish_analysis",
            entities={"dish": "剁椒鱼头"},
        )
        result = seeded_kg.execute_graph_query(intent)
        assert result["type"] == "dish_analysis"
        assert result["found"] is True

    def test_execute_trend_query(self, seeded_kg: KnowledgeGraphService) -> None:
        intent = QueryIntent(
            intent_type="trend",
            metric="revenue",
        )
        result = seeded_kg.execute_graph_query(intent)
        assert result["type"] == "trend"
        assert "data_points" in result
        assert len(result["data_points"]) > 0

    def test_execute_recommendation_query(self, seeded_kg: KnowledgeGraphService) -> None:
        intent = QueryIntent(
            intent_type="recommendation",
            entities={"guest_count": 50, "event_type": "商务"},
        )
        result = seeded_kg.execute_graph_query(intent)
        assert result["type"] == "recommendation"
        assert result["guest_count"] == 50
        assert len(result["menu"]) > 0

    def test_execute_unknown_query(self, seeded_kg: KnowledgeGraphService) -> None:
        intent = QueryIntent(intent_type="unknown")
        result = seeded_kg.execute_graph_query(intent)
        assert result["type"] == "unknown"


# ══════════════════════════════════════
# 10. 边界情况
# ══════════════════════════════════════


class TestEdgeCases:
    def test_empty_graph_query(self, kg: KnowledgeGraphService) -> None:
        """空图谱查询不应崩溃"""
        result = kg.query_natural_language("翻台率平均是多少")
        assert isinstance(result, NLQueryResult)
        assert "暂无" in result.answer or result.answer != ""

    def test_empty_graph_stats(self, kg: KnowledgeGraphService) -> None:
        stats = kg.get_graph_stats()
        assert stats["total_entities"] == 0
        assert stats["total_relationships"] == 0

    def test_dish_not_found(self, seeded_kg: KnowledgeGraphService) -> None:
        result = seeded_kg.query_natural_language("满汉全席的最优定价区间是多少？")
        assert "未找到" in result.answer

    def test_multiple_queries_consistent(self, seeded_kg: KnowledgeGraphService) -> None:
        """多次相同查询结果一致"""
        r1 = seeded_kg.query_natural_language("翻台率平均是多少")
        r2 = seeded_kg.query_natural_language("翻台率平均是多少")
        assert r1.data == r2.data

    def test_ingest_missing_id(self, kg: KnowledgeGraphService) -> None:
        result = kg.ingest_decision_data({"description": "no id"})
        assert result["ok"] is False

    def test_ingest_best_practice_missing_id(self, kg: KnowledgeGraphService) -> None:
        result = kg.ingest_best_practice({"title": "no id"})
        assert result["ok"] is False
