"""经营知识图谱 — 行业级知识库 + 自然语言查询

将所有商户的经营数据、Agent决策、行业知识沉淀为可查询的知识图谱。
支持自然语言提问，返回结构化回答。

Graph Structure:
(Store)-[:BELONGS_TO]->(Brand)-[:OWNED_BY]->(Group)
(Store)-[:LOCATED_IN]->(City)-[:IN]->(Province)
(Store)-[:SERVES]->(Dish)-[:USES]->(Ingredient)
(Dish)-[:HAS_CATEGORY]->(Category)
(Store)-[:HAS_METRIC {date}]->(StoreMetric)
(Employee)-[:WORKS_AT]->(Store)
(Customer)-[:VISITS]->(Store)
(Supplier)-[:SUPPLIES]->(Ingredient)
(Agent)-[:MADE_DECISION {date}]->(Decision)-[:ABOUT]->(Store)
(Decision)-[:HAD_OUTCOME]->(Outcome)
(BestPractice)-[:DISCOVERED_AT]->(Store)-[:APPLICABLE_TO]->(BusinessType)
"""
import re
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import structlog

logger = structlog.get_logger()


# ─── 数据模型 ───


@dataclass
class QueryIntent:
    """自然语言查询意图"""
    intent_type: str  # aggregate/ranking/comparison/trend/root_cause/recommendation/benchmark/best_practice/dish_analysis
    entities: dict = field(default_factory=dict)
    metric: str = ""
    aggregation: str = "avg"
    time_range: dict = field(default_factory=dict)
    filters: dict = field(default_factory=dict)


@dataclass
class NLQueryResult:
    """自然语言查询结果"""
    question: str
    intent: QueryIntent
    answer: str
    data: dict = field(default_factory=dict)
    confidence: float = 0.0
    sources: list = field(default_factory=list)
    suggestions: list = field(default_factory=list)
    query_ms: int = 0


# ─── 指标名称映射 ───

METRIC_NAME_MAP = {
    "翻台率": "turnover_rate",
    "客单价": "avg_check",
    "毛利率": "profit_margin",
    "人效": "labor_efficiency",
    "坪效": "space_efficiency",
    "营业额": "revenue",
    "客流量": "customer_count",
    "满意度": "customer_satisfaction",
    "订单量": "order_count",
    "销量": "sales_volume",
}

METRIC_UNIT_MAP = {
    "turnover_rate": "次/天",
    "avg_check": "元",
    "profit_margin": "%",
    "labor_efficiency": "元/人/天",
    "space_efficiency": "元/平米/天",
    "revenue": "元",
    "customer_count": "人",
    "customer_satisfaction": "分",
    "order_count": "单",
    "sales_volume": "份",
}

METRIC_CN_MAP = {v: k for k, v in METRIC_NAME_MAP.items()}


# ─── 问题模式 ───

QUESTION_PATTERNS = {
    "aggregate_metric": [
        re.compile(
            r"(?P<city>[\u4e00-\u9fff]{2,4})(地区|区域)(?P<type>[\u4e00-\u9fff]+)的(平均)?(?P<metric>翻台率|客单价|毛利率|人效|坪效|营业额|客流量)(是多少|有多少|怎么样)"
        ),
        re.compile(
            r"(?P<metric>翻台率|客单价|毛利率|人效|坪效|营业额|客流量)(平均|总计)?(是多少|有多少)"
        ),
    ],
    "benchmark": [
        re.compile(
            r"我们的(?P<metric>翻台率|客单价|毛利率|人效|坪效|营业额|客流量).*(跟|和|与).*(行业|同行).*(比|对比|相比|怎么样)"
        ),
        re.compile(
            r"(行业|同行|对标)(平均|标准|基准|水平).*?(?P<metric>翻台率|客单价|毛利率|人效|坪效|营业额|客流量)"
        ),
        re.compile(
            r"(?P<metric>翻台率|客单价|毛利率|人效|坪效|营业额|客流量).*(跟|和|与).*(行业|同行)"
        ),
    ],
    "trend": [
        re.compile(
            r"(上周|上月|最近|这周|本月)\s*(?P<metric>翻台率|客单价|毛利率|人效|坪效|营业额|客流量|销量)\s*(变化|趋势|走势|下降|上升|增长)"
        ),
        re.compile(
            r"(?P<metric>翻台率|客单价|毛利率|人效|坪效|营业额|客流量|销量)(为什么|怎么)(下降|上升|变化)了"
        ),
    ],
    "ranking": [
        re.compile(r"哪些门店的?(?P<metric>翻台率|客单价|毛利率|人效|坪效|营业额|客流量|销量|表现|业绩)(最高|最低|最好|最差)"),
        re.compile(
            r"(?P<metric>翻台率|客单价|毛利率|人效|坪效|营业额|客流量|销量)(排名|排行|TOP|top)(?P<n>\d+)?"
        ),
        re.compile(r"(表现|业绩)(最好|最差)的(门店|菜品|员工)"),
    ],
    "dish_analysis": [
        re.compile(
            r"(?P<dish>[\u4e00-\u9fff]{2,6})的(最优|最佳|推荐)?(定价|价格)(区间|范围)?(是多少)?"
        ),
        re.compile(r"(?P<dish>[\u4e00-\u9fff]{2,6})(卖得怎么样|销量|表现|趋势)"),
        re.compile(r"(?P<dish>[\u4e00-\u9fff]{2,6})的(成本|毛利|利润)(率|是多少)?"),
    ],
    "recommendation": [
        re.compile(
            r"(推荐|建议|适合).*?(?P<guest_count>\d+)人.*?(?P<type>宴会|聚餐|商务|生日)"
        ),
        re.compile(r"(什么菜|哪些菜|推荐菜品).*(适合|推荐|应该)"),
    ],
    "best_practice": [
        re.compile(
            r"(最佳实践|成功经验|怎么提升|如何改善).*?(?P<metric>翻台率|客单价|毛利率|人效|坪效|营业额|客流量)"
        ),
        re.compile(
            r"(?P<metric>翻台率|客单价|毛利率|人效|坪效|营业额|客流量)(怎么提升|如何改善|提升方法)"
        ),
    ],
}


# ─── 知识图谱服务 ───


class KnowledgeGraphService:
    """经营知识图谱 — 行业级知识库 + 自然语言查询"""

    def __init__(self) -> None:
        # 图存储：entities[type][id] = properties
        self._entities: dict[str, dict[str, dict]] = {}
        # 关系存储：relationships[(from_type, from_id, rel_type, to_type, to_id)] = properties
        self._relationships: dict[tuple, dict] = {}
        # 反向索引：in_edges[to_type][to_id] = [(from_type, from_id, rel_type, props)]
        self._in_edges: dict[str, dict[str, list]] = {}
        # 正向索引：out_edges[from_type][from_id] = [(to_type, to_id, rel_type, props)]
        self._out_edges: dict[str, dict[str, list]] = {}
        self._last_updated: Optional[datetime] = None

    # ──────────────────────────────────────
    # 1. Graph Construction (图谱构建)
    # ──────────────────────────────────────

    def add_entity(self, entity_type: str, entity_id: str, properties: dict) -> dict:
        """添加实体节点"""
        if entity_type not in self._entities:
            self._entities[entity_type] = {}
        self._entities[entity_type][entity_id] = {
            **properties,
            "_type": entity_type,
            "_id": entity_id,
            "_updated_at": datetime.now().isoformat(),
        }
        self._last_updated = datetime.now()
        return {"ok": True, "entity_type": entity_type, "entity_id": entity_id}

    def add_relationship(
        self,
        from_type: str,
        from_id: str,
        rel_type: str,
        to_type: str,
        to_id: str,
        properties: Optional[dict] = None,
    ) -> dict:
        """添加关系边"""
        props = properties or {}
        key = (from_type, from_id, rel_type, to_type, to_id)
        self._relationships[key] = props

        # 正向索引
        if from_type not in self._out_edges:
            self._out_edges[from_type] = {}
        if from_id not in self._out_edges[from_type]:
            self._out_edges[from_type][from_id] = []
        self._out_edges[from_type][from_id].append(
            (to_type, to_id, rel_type, props)
        )

        # 反向索引
        if to_type not in self._in_edges:
            self._in_edges[to_type] = {}
        if to_id not in self._in_edges[to_type]:
            self._in_edges[to_type][to_id] = []
        self._in_edges[to_type][to_id].append(
            (from_type, from_id, rel_type, props)
        )

        self._last_updated = datetime.now()
        return {"ok": True, "relationship": rel_type, "from": from_id, "to": to_id}

    def get_entity(self, entity_type: str, entity_id: str) -> dict:
        """获取实体"""
        type_store = self._entities.get(entity_type, {})
        entity = type_store.get(entity_id)
        if entity is None:
            return {}
        return dict(entity)

    def get_neighbors(
        self,
        entity_type: str,
        entity_id: str,
        rel_type: Optional[str] = None,
        direction: str = "out",
    ) -> list[dict]:
        """获取邻居节点"""
        results: list[dict] = []

        if direction in ("out", "both"):
            edges = self._out_edges.get(entity_type, {}).get(entity_id, [])
            for to_type, to_id, r_type, props in edges:
                if rel_type and r_type != rel_type:
                    continue
                entity = self.get_entity(to_type, to_id)
                if entity:
                    results.append({
                        "entity": entity,
                        "relationship": r_type,
                        "direction": "out",
                        "properties": props,
                    })

        if direction in ("in", "both"):
            edges = self._in_edges.get(entity_type, {}).get(entity_id, [])
            for from_type, from_id, r_type, props in edges:
                if rel_type and r_type != rel_type:
                    continue
                entity = self.get_entity(from_type, from_id)
                if entity:
                    results.append({
                        "entity": entity,
                        "relationship": r_type,
                        "direction": "in",
                        "properties": props,
                    })

        return results

    def delete_entity(self, entity_type: str, entity_id: str) -> dict:
        """删除实体及其关联关系"""
        type_store = self._entities.get(entity_type, {})
        if entity_id not in type_store:
            return {"ok": False, "error": "entity_not_found"}

        del type_store[entity_id]

        # 清理正向边
        out_edges = self._out_edges.get(entity_type, {}).pop(entity_id, [])
        for to_type, to_id, r_type, _ in out_edges:
            key = (entity_type, entity_id, r_type, to_type, to_id)
            self._relationships.pop(key, None)
            in_list = self._in_edges.get(to_type, {}).get(to_id, [])
            self._in_edges.get(to_type, {})[to_id] = [
                e for e in in_list if not (e[0] == entity_type and e[1] == entity_id)
            ]

        # 清理反向边
        in_edges = self._in_edges.get(entity_type, {}).pop(entity_id, [])
        for from_type, from_id, r_type, _ in in_edges:
            key = (from_type, from_id, r_type, entity_type, entity_id)
            self._relationships.pop(key, None)
            out_list = self._out_edges.get(from_type, {}).get(from_id, [])
            self._out_edges.get(from_type, {})[from_id] = [
                e for e in out_list if not (e[0] == entity_type and e[1] == entity_id)
            ]

        self._last_updated = datetime.now()
        return {"ok": True, "deleted": entity_id}

    # ──────────────────────────────────────
    # 2. Knowledge Ingestion (知识注入)
    # ──────────────────────────────────────

    def ingest_store_data(self, store_data: dict) -> dict:
        """批量导入门店 + 菜品 + 食材 + 指标"""
        counts = {"stores": 0, "dishes": 0, "ingredients": 0, "metrics": 0, "categories": 0}

        store = store_data.get("store", {})
        store_id = store.get("id", "")
        if store_id:
            self.add_entity("store", store_id, store)
            counts["stores"] += 1

            # 城市
            city = store.get("city", "")
            if city:
                self.add_entity("city", city, {"name": city, "province": store.get("province", "")})
                self.add_relationship("store", store_id, "LOCATED_IN", "city", city)

            # 品牌
            brand = store.get("brand", "")
            if brand:
                self.add_entity("brand", brand, {"name": brand})
                self.add_relationship("store", store_id, "BELONGS_TO", "brand", brand)

            # 业态
            biz_type = store.get("business_type", "")
            if biz_type:
                self.add_entity("business_type", biz_type, {"name": biz_type})
                self.add_relationship("store", store_id, "HAS_TYPE", "business_type", biz_type)

        # 菜品
        for dish in store_data.get("dishes", []):
            dish_id = dish.get("id", "")
            if not dish_id:
                continue
            self.add_entity("dish", dish_id, dish)
            counts["dishes"] += 1

            if store_id:
                self.add_relationship("store", store_id, "SERVES", "dish", dish_id)

            cat = dish.get("category", "")
            if cat:
                self.add_entity("category", cat, {"name": cat})
                self.add_relationship("dish", dish_id, "HAS_CATEGORY", "category", cat)
                counts["categories"] += 1

            # 食材关联
            for ing in dish.get("ingredients", []):
                ing_id = ing.get("id", "")
                if ing_id:
                    self.add_entity("ingredient", ing_id, ing)
                    self.add_relationship("dish", dish_id, "USES", "ingredient", ing_id)
                    counts["ingredients"] += 1

        # 指标
        for metric in store_data.get("metrics", []):
            metric_id = metric.get("id", f"{store_id}_{metric.get('date', '')}")
            self.add_entity("store_metric", metric_id, metric)
            if store_id:
                self.add_relationship(
                    "store", store_id, "HAS_METRIC", "store_metric", metric_id,
                    {"date": metric.get("date", "")},
                )
            counts["metrics"] += 1

        return {"ok": True, "ingested": counts}

    def ingest_decision_data(self, decision_data: dict) -> dict:
        """导入 Agent 决策及其结果"""
        decision_id = decision_data.get("id", "")
        if not decision_id:
            return {"ok": False, "error": "missing_decision_id"}

        self.add_entity("decision", decision_id, decision_data)

        agent_id = decision_data.get("agent_id", "")
        if agent_id:
            self.add_entity("agent", agent_id, {
                "name": decision_data.get("agent_name", agent_id),
                "type": "skill_agent",
            })
            self.add_relationship(
                "agent", agent_id, "MADE_DECISION", "decision", decision_id,
                {"date": decision_data.get("date", "")},
            )

        store_id = decision_data.get("store_id", "")
        if store_id:
            self.add_relationship("decision", decision_id, "ABOUT", "store", store_id)

        outcome = decision_data.get("outcome")
        if outcome:
            outcome_id = f"{decision_id}_outcome"
            self.add_entity("outcome", outcome_id, outcome)
            self.add_relationship("decision", decision_id, "HAD_OUTCOME", "outcome", outcome_id)

        return {"ok": True, "decision_id": decision_id}

    def ingest_best_practice(self, practice: dict) -> dict:
        """导入最佳实践"""
        practice_id = practice.get("id", "")
        if not practice_id:
            return {"ok": False, "error": "missing_practice_id"}

        self.add_entity("best_practice", practice_id, practice)

        store_id = practice.get("discovered_at_store", "")
        if store_id:
            self.add_relationship(
                "best_practice", practice_id, "DISCOVERED_AT", "store", store_id
            )

        for btype in practice.get("applicable_to", []):
            self.add_entity("business_type", btype, {"name": btype})
            self.add_relationship(
                "best_practice", practice_id, "APPLICABLE_TO", "business_type", btype
            )

        return {"ok": True, "practice_id": practice_id}

    def get_graph_stats(self) -> dict:
        """图谱统计"""
        entity_counts = {etype: len(ents) for etype, ents in self._entities.items()}
        return {
            "total_entities": sum(entity_counts.values()),
            "entities_by_type": entity_counts,
            "total_relationships": len(self._relationships),
            "last_updated": self._last_updated.isoformat() if self._last_updated else None,
        }

    # ──────────────────────────────────────
    # 3. Natural Language Query (自然语言查询)
    # ──────────────────────────────────────

    def query_natural_language(
        self, question: str, tenant_id: Optional[str] = None
    ) -> NLQueryResult:
        """自然语言查询入口"""
        start = time.perf_counter()

        intent = self.parse_query_intent(question)
        query_result = self.execute_graph_query(intent)
        answer = self.generate_answer(question, query_result, format="text")
        suggestions = self._generate_suggestions(intent)
        sources = self._collect_sources(query_result)

        elapsed_ms = int((time.perf_counter() - start) * 1000)

        confidence = 0.85 if intent.intent_type != "unknown" else 0.2

        logger.info(
            "nl_query",
            question=question,
            intent_type=intent.intent_type,
            confidence=confidence,
            ms=elapsed_ms,
        )

        return NLQueryResult(
            question=question,
            intent=intent,
            answer=answer,
            data=query_result,
            confidence=confidence,
            sources=sources,
            suggestions=suggestions,
            query_ms=elapsed_ms,
        )

    # ──────────────────────────────────────
    # 4. Intent Parsing (意图解析)
    # ──────────────────────────────────────

    def parse_query_intent(self, question: str) -> QueryIntent:
        """解析自然语言问题为结构化意图"""
        for intent_type, patterns in QUESTION_PATTERNS.items():
            for pattern in patterns:
                m = pattern.search(question)
                if m:
                    groups = m.groupdict()
                    return self._build_intent(intent_type, groups, question)

        # 兜底：尝试从问题中提取关键信息
        return QueryIntent(intent_type="unknown", entities={"raw_question": question})

    def _build_intent(self, intent_type: str, groups: dict, question: str) -> QueryIntent:
        """根据正则匹配结果构建意图"""
        entities: dict = {}
        metric_cn = groups.get("metric", "")
        metric = METRIC_NAME_MAP.get(metric_cn, metric_cn)
        filters: dict = {}
        aggregation = "avg"
        time_range: dict = {}

        if "city" in groups and groups["city"]:
            entities["city"] = groups["city"]
            filters["city"] = groups["city"]
        if "type" in groups and groups["type"]:
            entities["business_type"] = groups["type"]
            filters["business_type"] = groups["type"]
        if "dish" in groups and groups["dish"]:
            entities["dish"] = groups["dish"]
        if "guest_count" in groups and groups["guest_count"]:
            entities["guest_count"] = int(groups["guest_count"])
        if "type" in groups and groups["type"]:
            entities["event_type"] = groups["type"]
        if "n" in groups and groups["n"]:
            aggregation = f"top_{groups['n']}"

        # 时间范围
        if "上周" in question:
            now = datetime.now()
            start = now - timedelta(days=now.weekday() + 7)
            end = start + timedelta(days=6)
            time_range = {"start": start.strftime("%Y-%m-%d"), "end": end.strftime("%Y-%m-%d"), "period": "week"}
        elif "上月" in question:
            now = datetime.now()
            first_this = now.replace(day=1)
            last_month_end = first_this - timedelta(days=1)
            last_month_start = last_month_end.replace(day=1)
            time_range = {"start": last_month_start.strftime("%Y-%m-%d"), "end": last_month_end.strftime("%Y-%m-%d"), "period": "month"}
        elif "本月" in question or "这个月" in question:
            now = datetime.now()
            time_range = {"start": now.replace(day=1).strftime("%Y-%m-%d"), "end": now.strftime("%Y-%m-%d"), "period": "month"}
        elif "最近" in question:
            now = datetime.now()
            time_range = {"start": (now - timedelta(days=7)).strftime("%Y-%m-%d"), "end": now.strftime("%Y-%m-%d"), "period": "week"}

        # 聚合方式
        if "总计" in question or "总共" in question:
            aggregation = "sum"
        elif "最高" in question or "最好" in question:
            aggregation = "top_5"
        elif "最低" in question or "最差" in question:
            aggregation = "bottom_5"

        return QueryIntent(
            intent_type=intent_type,
            entities=entities,
            metric=metric,
            aggregation=aggregation,
            time_range=time_range,
            filters=filters,
        )

    # ──────────────────────────────────────
    # 5. Graph Query Execution (图查询执行)
    # ──────────────────────────────────────

    def execute_graph_query(self, intent: QueryIntent) -> dict:
        """将意图转化为图遍历，返回原始结果"""
        handler_map = {
            "aggregate_metric": self._query_aggregate,
            "dish_analysis": self._query_dish,
            "ranking": self._query_ranking,
            "trend": self._query_trend,
            "recommendation": self._query_recommendation,
            "benchmark": self._query_benchmark,
            "best_practice": self._query_best_practice,
        }

        handler = handler_map.get(intent.intent_type, self._query_fallback)
        return handler(intent)

    def _query_aggregate(self, intent: QueryIntent) -> dict:
        """聚合指标查询"""
        stores = self._filter_stores(intent.filters)
        metric_key = intent.metric
        values: list[float] = []
        store_details: list[dict] = []

        for store_id, store in stores.items():
            metrics = self._get_store_metrics(store_id, intent.time_range)
            metric_vals = [m.get(metric_key, 0) for m in metrics if metric_key in m]
            if metric_vals:
                avg_val = statistics.mean(metric_vals)
                values.append(avg_val)
                store_details.append({"store": store.get("name", store_id), "value": round(avg_val, 2)})

        if not values:
            return {"type": "aggregate", "metric": metric_key, "result": None, "count": 0}

        return {
            "type": "aggregate",
            "metric": metric_key,
            "result": {
                "avg": round(statistics.mean(values), 2),
                "min": round(min(values), 2),
                "max": round(max(values), 2),
                "count": len(values),
                "median": round(statistics.median(values), 2),
            },
            "stores": store_details,
        }

    def _query_dish(self, intent: QueryIntent) -> dict:
        """菜品分析查询"""
        dish_name = intent.entities.get("dish", "")
        dishes = self._entities.get("dish", {})
        matched: list[dict] = []

        for dish_id, dish in dishes.items():
            if dish_name in dish.get("name", ""):
                matched.append(dish)

        if not matched:
            return {"type": "dish_analysis", "dish": dish_name, "found": False}

        # 汇总定价和成本数据
        prices = [d.get("price", 0) for d in matched if d.get("price")]
        costs = [d.get("cost", 0) for d in matched if d.get("cost")]
        margins = []
        for d in matched:
            p = d.get("price", 0)
            c = d.get("cost", 0)
            if p > 0:
                margins.append(round((p - c) / p * 100, 1))

        result: dict = {
            "type": "dish_analysis",
            "dish": dish_name,
            "found": True,
            "count": len(matched),
            "details": matched,
        }
        if prices:
            result["price_range"] = {
                "min": min(prices),
                "max": max(prices),
                "avg": round(statistics.mean(prices), 1),
                "optimal_low": round(statistics.mean(prices) * 0.9, 1),
                "optimal_high": round(statistics.mean(prices) * 1.1, 1),
            }
        if margins:
            result["margin"] = {
                "avg": round(statistics.mean(margins), 1),
                "min": round(min(margins), 1),
                "max": round(max(margins), 1),
            }
        if costs:
            result["cost"] = {
                "avg": round(statistics.mean(costs), 1),
                "min": min(costs),
                "max": max(costs),
            }

        return result

    def _query_ranking(self, intent: QueryIntent) -> dict:
        """排名查询"""
        metric_key = intent.metric
        if not metric_key:
            metric_key = "revenue"

        stores = self._filter_stores(intent.filters)
        ranking: list[dict] = []

        for store_id, store in stores.items():
            metrics = self._get_store_metrics(store_id, intent.time_range)
            vals = [m.get(metric_key, 0) for m in metrics if metric_key in m]
            if vals:
                ranking.append({
                    "store_id": store_id,
                    "store_name": store.get("name", store_id),
                    "value": round(statistics.mean(vals), 2),
                })

        descending = "bottom" not in intent.aggregation
        ranking.sort(key=lambda x: x["value"], reverse=descending)

        # 取 top N
        n = 5
        agg = intent.aggregation
        if agg.startswith("top_") or agg.startswith("bottom_"):
            parts = agg.split("_")
            if len(parts) > 1 and parts[1].isdigit():
                n = int(parts[1])

        return {
            "type": "ranking",
            "metric": metric_key,
            "order": "desc" if descending else "asc",
            "items": ranking[:n],
            "total": len(ranking),
        }

    def _query_trend(self, intent: QueryIntent) -> dict:
        """趋势/原因分析查询"""
        metric_key = intent.metric
        if not metric_key:
            metric_key = "revenue"

        stores = self._filter_stores(intent.filters)
        all_metrics: list[dict] = []

        for store_id, store in stores.items():
            metrics = self._get_store_metrics(store_id, intent.time_range)
            for m in metrics:
                if metric_key in m:
                    all_metrics.append({
                        "date": m.get("date", ""),
                        "store": store.get("name", store_id),
                        "value": m[metric_key],
                    })

        all_metrics.sort(key=lambda x: x["date"])

        # 计算变化
        if len(all_metrics) >= 2:
            first_half = all_metrics[: len(all_metrics) // 2]
            second_half = all_metrics[len(all_metrics) // 2:]
            avg_first = statistics.mean([m["value"] for m in first_half]) if first_half else 0
            avg_second = statistics.mean([m["value"] for m in second_half]) if second_half else 0
            change_pct = ((avg_second - avg_first) / avg_first * 100) if avg_first else 0
        else:
            change_pct = 0
            avg_first = 0
            avg_second = 0

        # 查找可能原因（相关决策）
        causes: list[str] = []
        decisions = self._entities.get("decision", {})
        for dec_id, dec in decisions.items():
            dec_metric = dec.get("metric", "")
            if dec_metric == metric_key or metric_key in dec.get("description", ""):
                outcome = dec.get("outcome", {})
                if outcome:
                    causes.append(dec.get("description", str(dec_id)))

        # 如果没有关联决策，添加通用原因
        if not causes:
            if change_pct < -5:
                causes = ["天气变化导致客流减少", "周边竞品活动影响", "菜品结构调整影响"]
            elif change_pct > 5:
                causes = ["营销活动效果显现", "新品推出带动增长", "服务改善提升口碑"]

        return {
            "type": "trend",
            "metric": metric_key,
            "data_points": all_metrics,
            "change_pct": round(change_pct, 1),
            "avg_previous": round(avg_first, 2),
            "avg_current": round(avg_second, 2),
            "possible_causes": causes,
        }

    def _query_recommendation(self, intent: QueryIntent) -> dict:
        """推荐查询"""
        guest_count = intent.entities.get("guest_count", 10)
        event_type = intent.entities.get("event_type", "聚餐")

        dishes = self._entities.get("dish", {})
        categories_needed = {
            "宴会": {"凉菜": 4, "热菜": 8, "汤": 2, "主食": 2, "甜点": 2},
            "聚餐": {"凉菜": 3, "热菜": 5, "汤": 1, "主食": 2, "甜点": 1},
            "商务": {"凉菜": 2, "热菜": 4, "汤": 1, "主食": 1, "甜点": 1},
            "生日": {"凉菜": 2, "热菜": 4, "汤": 1, "主食": 1, "甜点": 2},
        }
        needs = categories_needed.get(event_type, categories_needed["聚餐"])

        # 按类别分组
        by_category: dict[str, list[dict]] = {}
        for dish_id, dish in dishes.items():
            cat = dish.get("category", "热菜")
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(dish)

        # 每个类别选高分/高毛利菜品
        recommended: list[dict] = []
        total_price = 0.0
        for cat, count in needs.items():
            available = by_category.get(cat, [])
            # 按毛利率排序
            available.sort(
                key=lambda d: (d.get("price", 0) - d.get("cost", 0)) / max(d.get("price", 1), 1),
                reverse=True,
            )
            selected = available[:count]
            for dish in selected:
                price = dish.get("price", 0)
                recommended.append({
                    "name": dish.get("name", ""),
                    "category": cat,
                    "price": price,
                    "serves": dish.get("serves", "4-6人"),
                })
                total_price += price

        per_person = total_price / max(guest_count, 1)

        return {
            "type": "recommendation",
            "guest_count": guest_count,
            "event_type": event_type,
            "menu": recommended,
            "total_price": round(total_price, 0),
            "per_person": round(per_person, 0),
            "dish_count": len(recommended),
        }

    def _query_benchmark(self, intent: QueryIntent) -> dict:
        """行业基准查询"""
        metric_key = intent.metric
        benchmark = self.get_benchmark(metric_key)

        # 获取自己的平均值
        stores = self._filter_stores(intent.filters)
        own_values: list[float] = []
        for store_id in stores:
            metrics = self._get_store_metrics(store_id, intent.time_range)
            vals = [m.get(metric_key, 0) for m in metrics if metric_key in m]
            own_values.extend(vals)

        own_avg = round(statistics.mean(own_values), 2) if own_values else None

        return {
            "type": "benchmark",
            "metric": metric_key,
            "benchmark": benchmark,
            "own_avg": own_avg,
            "comparison": self._compare_value(own_avg, benchmark) if own_avg is not None else "无数据",
        }

    def _query_best_practice(self, intent: QueryIntent) -> dict:
        """最佳实践查询"""
        metric_key = intent.metric
        practices = self._entities.get("best_practice", {})
        matched: list[dict] = []

        for pid, practice in practices.items():
            p_metric = practice.get("metric", "")
            if p_metric == metric_key or METRIC_CN_MAP.get(metric_key, "") in practice.get("description", ""):
                matched.append(practice)

        # 同时查找高绩效门店
        top_stores = self._query_ranking(QueryIntent(
            intent_type="ranking", metric=metric_key, aggregation="top_3",
        ))

        return {
            "type": "best_practice",
            "metric": metric_key,
            "practices": matched,
            "top_performers": top_stores.get("items", [])[:3],
        }

    def _query_fallback(self, intent: QueryIntent) -> dict:
        """兜底查询"""
        return {
            "type": "unknown",
            "raw": intent.entities.get("raw_question", ""),
            "suggestion": "请尝试用更具体的问法，如'长沙地区海鲜酒楼的平均翻台率是多少'",
        }

    # ──────────────────────────────────────
    # 6. Answer Generation (答案生成)
    # ──────────────────────────────────────

    def generate_answer(self, question: str, query_result: dict, format: str = "text") -> str:
        """根据查询结果生成自然语言答案"""
        result_type = query_result.get("type", "unknown")

        generator_map = {
            "aggregate": self._answer_aggregate,
            "dish_analysis": self._answer_dish,
            "ranking": self._answer_ranking,
            "trend": self._answer_trend,
            "recommendation": self._answer_recommendation,
            "benchmark": self._answer_benchmark,
            "best_practice": self._answer_best_practice,
            "unknown": self._answer_unknown,
        }

        generator = generator_map.get(result_type, self._answer_unknown)
        answer = generator(query_result)

        if format == "table":
            return self._format_as_table(query_result, answer)
        elif format == "chart_data":
            return self._format_as_chart_data(query_result)

        return answer

    def _answer_aggregate(self, result: dict) -> str:
        metric = result.get("metric", "")
        metric_cn = METRIC_CN_MAP.get(metric, metric)
        unit = METRIC_UNIT_MAP.get(metric, "")
        agg = result.get("result")

        if agg is None:
            return f"抱歉，暂无{metric_cn}相关数据。"

        answer = f"当前{metric_cn}平均为{agg['avg']}{unit}"
        answer += f"（最低{agg['min']}{unit}，最高{agg['max']}{unit}，中位数{agg['median']}{unit}）"
        answer += f"，共统计{agg['count']}家门店。"

        stores = result.get("stores", [])
        if stores:
            sorted_stores = sorted(stores, key=lambda x: x["value"], reverse=True)
            top = sorted_stores[0]
            answer += f"\n表现最好的是{top['store']}，{metric_cn}{top['value']}{unit}。"

        return answer

    def _answer_dish(self, result: dict) -> str:
        dish = result.get("dish", "")
        if not result.get("found"):
            return f"抱歉，未找到「{dish}」的相关数据。"

        answer = f"关于「{dish}」的分析：\n"

        price_info = result.get("price_range")
        if price_info:
            answer += f"- 当前定价范围：{price_info['min']}~{price_info['max']}元"
            answer += f"（平均{price_info['avg']}元）\n"
            answer += f"- 建议最优定价区间：{price_info['optimal_low']}~{price_info['optimal_high']}元\n"

        margin_info = result.get("margin")
        if margin_info:
            answer += f"- 毛利率：平均{margin_info['avg']}%"
            answer += f"（{margin_info['min']}%~{margin_info['max']}%）\n"

        cost_info = result.get("cost")
        if cost_info:
            answer += f"- 食材成本：平均{cost_info['avg']}元\n"

        return answer

    def _answer_ranking(self, result: dict) -> str:
        metric = result.get("metric", "")
        metric_cn = METRIC_CN_MAP.get(metric, metric)
        unit = METRIC_UNIT_MAP.get(metric, "")
        items = result.get("items", [])
        order = result.get("order", "desc")
        label = "最高" if order == "desc" else "最低"

        if not items:
            return f"抱歉，暂无{metric_cn}排名数据。"

        answer = f"{metric_cn}{label}的门店排名：\n"
        for i, item in enumerate(items, 1):
            answer += f"{i}. {item['store_name']}：{item['value']}{unit}\n"

        return answer

    def _answer_trend(self, result: dict) -> str:
        metric = result.get("metric", "")
        metric_cn = METRIC_CN_MAP.get(metric, metric)
        change_pct = result.get("change_pct", 0)
        causes = result.get("possible_causes", [])
        avg_prev = result.get("avg_previous", 0)
        avg_curr = result.get("avg_current", 0)
        unit = METRIC_UNIT_MAP.get(metric, "")

        direction = "上升" if change_pct > 0 else "下降" if change_pct < 0 else "持平"
        answer = f"{metric_cn}近期{direction}了{abs(change_pct)}%"
        answer += f"（从{avg_prev}{unit}变为{avg_curr}{unit}）。\n"

        if causes:
            answer += "可能原因：\n"
            for i, cause in enumerate(causes, 1):
                answer += f"{i}. {cause}\n"

        return answer

    def _answer_recommendation(self, result: dict) -> str:
        guest_count = result.get("guest_count", 0)
        event_type = result.get("event_type", "")
        menu = result.get("menu", [])
        total = result.get("total_price", 0)
        per_person = result.get("per_person", 0)

        answer = f"为{guest_count}人{event_type}推荐以下菜单（共{len(menu)}道菜）：\n\n"

        current_cat = ""
        for dish in menu:
            cat = dish.get("category", "")
            if cat != current_cat:
                current_cat = cat
                answer += f"【{cat}】\n"
            answer += f"  - {dish['name']}（{dish['price']}元）\n"

        answer += f"\n预估总价：{total}元，人均约{per_person}元。"
        return answer

    def _answer_benchmark(self, result: dict) -> str:
        metric = result.get("metric", "")
        metric_cn = METRIC_CN_MAP.get(metric, metric)
        unit = METRIC_UNIT_MAP.get(metric, "")
        benchmark = result.get("benchmark", {})
        own_avg = result.get("own_avg")
        comparison = result.get("comparison", "")

        answer = f"行业{metric_cn}基准数据：\n"
        answer += f"- 行业平均：{benchmark.get('avg', 'N/A')}{unit}\n"
        answer += f"- 25分位：{benchmark.get('p25', 'N/A')}{unit}\n"
        answer += f"- 50分位（中位数）：{benchmark.get('p50', 'N/A')}{unit}\n"
        answer += f"- 75分位：{benchmark.get('p75', 'N/A')}{unit}\n"
        answer += f"- 90分位（标杆）：{benchmark.get('p90', 'N/A')}{unit}\n"

        if own_avg is not None:
            answer += f"\n您的{metric_cn}为{own_avg}{unit}，{comparison}。"

        return answer

    def _answer_best_practice(self, result: dict) -> str:
        metric = result.get("metric", "")
        metric_cn = METRIC_CN_MAP.get(metric, metric)
        practices = result.get("practices", [])
        top_performers = result.get("top_performers", [])

        answer = f"提升{metric_cn}的最佳实践：\n\n"

        if practices:
            for i, p in enumerate(practices, 1):
                answer += f"{i}. {p.get('title', '')}：{p.get('description', '')}\n"
                improvement = p.get("improvement_pct", 0)
                if improvement:
                    answer += f"   预期提升：{improvement}%\n"
        else:
            answer += "暂无已记录的最佳实践。\n"

        if top_performers:
            answer += f"\n{metric_cn}表现最好的门店可供参考：\n"
            unit = METRIC_UNIT_MAP.get(metric, "")
            for i, s in enumerate(top_performers, 1):
                answer += f"{i}. {s['store_name']}：{s['value']}{unit}\n"

        return answer

    def _answer_unknown(self, result: dict) -> str:
        suggestion = result.get("suggestion", "")
        return f"抱歉，我暂时无法理解这个问题。{suggestion}"

    def _format_as_table(self, query_result: dict, text_answer: str) -> str:
        """将结果格式化为表格"""
        items = query_result.get("items") or query_result.get("stores") or []
        if not items:
            return text_answer

        header = "| 排名 | 名称 | 数值 |\n|------|------|------|\n"
        rows = ""
        for i, item in enumerate(items, 1):
            name = item.get("store_name", item.get("store", item.get("name", "")))
            value = item.get("value", "")
            rows += f"| {i} | {name} | {value} |\n"

        return header + rows

    def _format_as_chart_data(self, query_result: dict) -> str:
        """将结果格式化为图表数据JSON"""
        import json
        return json.dumps(query_result, ensure_ascii=False, default=str)

    # ──────────────────────────────────────
    # 7. Best Practice Discovery (最佳实践发现)
    # ──────────────────────────────────────

    def discover_best_practices(
        self, metric: str, min_improvement: float = 0.1
    ) -> list[dict]:
        """发现最佳实践"""
        decisions = self._entities.get("decision", {})
        practices: list[dict] = []

        for dec_id, dec in decisions.items():
            outcome = dec.get("outcome", {})
            if not outcome:
                # 检查 outcome 实体
                outcome_neighbors = self.get_neighbors("decision", dec_id, "HAD_OUTCOME")
                if outcome_neighbors:
                    outcome = outcome_neighbors[0].get("entity", {})

            improvement = outcome.get("improvement_pct", 0)
            dec_metric = dec.get("metric", "")

            if dec_metric == metric and improvement >= min_improvement * 100:
                practices.append({
                    "decision_id": dec_id,
                    "description": dec.get("description", ""),
                    "store_id": dec.get("store_id", ""),
                    "metric": metric,
                    "improvement_pct": improvement,
                    "action": dec.get("action", ""),
                })

        practices.sort(key=lambda x: x.get("improvement_pct", 0), reverse=True)
        return practices

    def get_applicable_practices(self, store_id: str) -> list[dict]:
        """获取适用于指定门店的最佳实践"""
        store = self.get_entity("store", store_id)
        if not store:
            return []

        store_type = store.get("business_type", "")
        store_city = store.get("city", "")

        practices = self._entities.get("best_practice", {})
        applicable: list[dict] = []

        for pid, practice in practices.items():
            applicable_types = practice.get("applicable_to", [])
            # 通用实践或匹配业态
            if not applicable_types or store_type in applicable_types or "all" in applicable_types:
                applicable.append(practice)

        return applicable

    # ──────────────────────────────────────
    # 8. Industry Benchmarks (行业基准)
    # ──────────────────────────────────────

    def get_benchmark(
        self,
        metric: str,
        business_type: Optional[str] = None,
        city: Optional[str] = None,
    ) -> dict:
        """获取行业基准"""
        filters: dict = {}
        if business_type:
            filters["business_type"] = business_type
        if city:
            filters["city"] = city

        stores = self._filter_stores(filters)
        values: list[float] = []

        for store_id in stores:
            metrics = self._get_store_metrics(store_id, {})
            vals = [m.get(metric, 0) for m in metrics if metric in m]
            if vals:
                values.append(statistics.mean(vals))

        if not values:
            # 返回行业默认基准
            return self._get_default_benchmark(metric)

        values.sort()
        n = len(values)
        return {
            "avg": round(statistics.mean(values), 2),
            "p25": round(values[max(0, n // 4 - 1)], 2),
            "p50": round(statistics.median(values), 2),
            "p75": round(values[min(n - 1, n * 3 // 4)], 2),
            "p90": round(values[min(n - 1, int(n * 0.9))], 2),
            "best_in_class": round(max(values), 2),
            "sample_size": n,
        }

    def compare_to_benchmark(self, store_id: str, metrics: list[str]) -> dict:
        """将门店指标与行业基准对比"""
        store = self.get_entity("store", store_id)
        if not store:
            return {"ok": False, "error": "store_not_found"}

        results: dict = {}
        for metric in metrics:
            store_metrics = self._get_store_metrics(store_id, {})
            vals = [m.get(metric, 0) for m in store_metrics if metric in m]
            store_avg = statistics.mean(vals) if vals else None

            benchmark = self.get_benchmark(metric, store.get("business_type"))
            comparison = self._compare_value(store_avg, benchmark) if store_avg is not None else "无数据"

            results[metric] = {
                "store_value": round(store_avg, 2) if store_avg is not None else None,
                "benchmark": benchmark,
                "comparison": comparison,
            }

        return {"ok": True, "store_id": store_id, "comparisons": results}

    # ──────────────────────────────────────
    # 内部辅助方法
    # ──────────────────────────────────────

    def _filter_stores(self, filters: dict) -> dict[str, dict]:
        """根据过滤条件筛选门店"""
        stores = self._entities.get("store", {})
        if not filters:
            return dict(stores)

        result: dict[str, dict] = {}
        for store_id, store in stores.items():
            match = True
            if "city" in filters:
                store_city = store.get("city", "")
                if filters["city"] not in store_city:
                    match = False
            if "business_type" in filters:
                store_type = store.get("business_type", "")
                if filters["business_type"] not in store_type:
                    match = False
            if match:
                result[store_id] = store

        return result

    def _get_store_metrics(self, store_id: str, time_range: dict) -> list[dict]:
        """获取门店指标数据"""
        neighbors = self.get_neighbors("store", store_id, "HAS_METRIC")
        metrics: list[dict] = []

        start = time_range.get("start", "")
        end = time_range.get("end", "")

        for n in neighbors:
            entity = n.get("entity", {})
            date = entity.get("date", "")
            if start and date < start:
                continue
            if end and date > end:
                continue
            metrics.append(entity)

        return metrics

    def _compare_value(self, value: Optional[float], benchmark: dict) -> str:
        """将一个值与基准对比，返回中文描述"""
        if value is None:
            return "无数据"
        p90 = benchmark.get("p90", float("inf"))
        p75 = benchmark.get("p75", float("inf"))
        p50 = benchmark.get("p50", 0)
        p25 = benchmark.get("p25", 0)

        if value >= p90:
            return "处于行业领先水平（超过90%同行）"
        elif value >= p75:
            return "处于行业优秀水平（超过75%同行）"
        elif value >= p50:
            return "处于行业中等偏上水平"
        elif value >= p25:
            return "低于行业中位数，有提升空间"
        else:
            return "低于行业平均，需要重点关注改善"

    def _get_default_benchmark(self, metric: str) -> dict:
        """行业默认基准（当数据不足时使用）"""
        defaults = {
            "turnover_rate": {"avg": 2.1, "p25": 1.5, "p50": 2.0, "p75": 2.6, "p90": 3.2, "best_in_class": 4.0, "sample_size": 0},
            "avg_check": {"avg": 85, "p25": 55, "p50": 80, "p75": 110, "p90": 150, "best_in_class": 220, "sample_size": 0},
            "profit_margin": {"avg": 62, "p25": 52, "p50": 60, "p75": 68, "p90": 75, "best_in_class": 82, "sample_size": 0},
            "labor_efficiency": {"avg": 480, "p25": 320, "p50": 450, "p75": 580, "p90": 720, "best_in_class": 950, "sample_size": 0},
            "space_efficiency": {"avg": 45, "p25": 28, "p50": 42, "p75": 58, "p90": 75, "best_in_class": 110, "sample_size": 0},
            "revenue": {"avg": 28000, "p25": 15000, "p50": 25000, "p75": 38000, "p90": 55000, "best_in_class": 85000, "sample_size": 0},
            "customer_count": {"avg": 220, "p25": 120, "p50": 200, "p75": 300, "p90": 420, "best_in_class": 600, "sample_size": 0},
        }
        return defaults.get(metric, {"avg": 0, "p25": 0, "p50": 0, "p75": 0, "p90": 0, "best_in_class": 0, "sample_size": 0})

    def _generate_suggestions(self, intent: QueryIntent) -> list[str]:
        """根据当前意图生成推荐后续问题"""
        suggestions_map = {
            "aggregate_metric": [
                "哪些门店的表现最好？",
                "跟行业平均相比怎么样？",
                "最近一周的趋势是什么？",
            ],
            "dish_analysis": [
                "这道菜的毛利率是多少？",
                "哪些门店卖得最好？",
                "推荐类似的高毛利菜品",
            ],
            "ranking": [
                "第一名是怎么做到的？",
                "跟行业基准对比如何？",
                "有什么最佳实践可以参考？",
            ],
            "trend": [
                "哪些门店下降最明显？",
                "有没有相关的成功经验？",
                "跟去年同期对比如何？",
            ],
            "recommendation": [
                "能否控制在人均100元以内？",
                "有什么特色菜推荐？",
                "适合哪些酒水搭配？",
            ],
            "benchmark": [
                "怎么提升到行业前25%？",
                "最佳实践有哪些？",
                "哪些门店已经达标？",
            ],
            "best_practice": [
                "最成功的案例是哪个门店？",
                "预计多久能见效？",
                "需要哪些资源投入？",
            ],
        }
        return suggestions_map.get(intent.intent_type, ["试试问其他指标", "查看门店排名", "对标行业基准"])

    def _collect_sources(self, query_result: dict) -> list[str]:
        """收集查询结果的数据来源"""
        sources: list[str] = []
        if "stores" in query_result:
            for s in query_result["stores"]:
                sources.append(f"store:{s.get('store', s.get('store_name', ''))}")
        if "items" in query_result:
            for s in query_result["items"]:
                sources.append(f"store:{s.get('store_name', '')}")
        if "details" in query_result:
            for d in query_result["details"]:
                sources.append(f"dish:{d.get('name', '')}")
        if "practices" in query_result:
            for p in query_result["practices"]:
                sources.append(f"practice:{p.get('title', p.get('id', ''))}")
        return sources[:10]


# ─── 种子数据工厂 ───


def seed_knowledge_graph() -> KnowledgeGraphService:
    """创建并填充种子数据的知识图谱"""
    import random
    random.seed(42)

    kg = KnowledgeGraphService()

    # ── 5 家门店 ──
    stores = [
        {"id": "store_cs_furong", "name": "长沙芙蓉路店", "city": "长沙", "province": "湖南",
         "brand": "尝在一起", "business_type": "海鲜酒楼", "area_sqm": 350, "seats": 180, "staff_count": 28},
        {"id": "store_cs_wuyi", "name": "长沙五一店", "city": "长沙", "province": "湖南",
         "brand": "尝在一起", "business_type": "海鲜酒楼", "area_sqm": 280, "seats": 140, "staff_count": 22},
        {"id": "store_wh_guanggu", "name": "武汉光谷店", "city": "武汉", "province": "湖北",
         "brand": "尝在一起", "business_type": "海鲜酒楼", "area_sqm": 320, "seats": 160, "staff_count": 25},
        {"id": "store_sz_nanshan", "name": "深圳南山店", "city": "深圳", "province": "广东",
         "brand": "尝在一起", "business_type": "海鲜酒楼", "area_sqm": 400, "seats": 200, "staff_count": 32},
        {"id": "store_bj_guomao", "name": "北京国贸店", "city": "北京", "province": "北京",
         "brand": "尝在一起", "business_type": "海鲜酒楼", "area_sqm": 450, "seats": 220, "staff_count": 35},
    ]

    # ── 30 道菜品 ──
    dishes = [
        # 凉菜
        {"id": "dish_01", "name": "凉拌海蜇", "category": "凉菜", "price": 38, "cost": 12, "serves": "2-4人"},
        {"id": "dish_02", "name": "蒜泥白肉", "category": "凉菜", "price": 32, "cost": 10, "serves": "2-4人"},
        {"id": "dish_03", "name": "口水鸡", "category": "凉菜", "price": 36, "cost": 11, "serves": "2-4人"},
        {"id": "dish_04", "name": "皮蛋豆腐", "category": "凉菜", "price": 22, "cost": 6, "serves": "2-4人"},
        {"id": "dish_05", "name": "凉拌木耳", "category": "凉菜", "price": 18, "cost": 5, "serves": "2-4人"},
        # 热菜
        {"id": "dish_06", "name": "剁椒鱼头", "category": "热菜", "price": 128, "cost": 42, "serves": "4-6人",
         "ingredients": [
             {"id": "ing_01", "name": "鳙鱼头", "unit_price": 28, "unit": "kg"},
             {"id": "ing_02", "name": "剁椒酱", "unit_price": 15, "unit": "kg"},
             {"id": "ing_03", "name": "小葱", "unit_price": 6, "unit": "kg"},
         ]},
        {"id": "dish_07", "name": "清蒸鲈鱼", "category": "热菜", "price": 98, "cost": 35, "serves": "2-4人",
         "ingredients": [
             {"id": "ing_04", "name": "鲈鱼", "unit_price": 32, "unit": "kg"},
         ]},
        {"id": "dish_08", "name": "蒜蓉粉丝蒸扇贝", "category": "热菜", "price": 68, "cost": 22, "serves": "2-4人"},
        {"id": "dish_09", "name": "香辣蟹", "category": "热菜", "price": 168, "cost": 65, "serves": "4-6人"},
        {"id": "dish_10", "name": "白灼基围虾", "category": "热菜", "price": 88, "cost": 38, "serves": "2-4人"},
        {"id": "dish_11", "name": "红烧肉", "category": "热菜", "price": 58, "cost": 18, "serves": "2-4人"},
        {"id": "dish_12", "name": "水煮鱼", "category": "热菜", "price": 78, "cost": 28, "serves": "4-6人"},
        {"id": "dish_13", "name": "糖醋排骨", "category": "热菜", "price": 62, "cost": 22, "serves": "2-4人"},
        {"id": "dish_14", "name": "宫保鸡丁", "category": "热菜", "price": 42, "cost": 14, "serves": "2-4人"},
        {"id": "dish_15", "name": "铁板牛柳", "category": "热菜", "price": 78, "cost": 30, "serves": "2-4人"},
        {"id": "dish_16", "name": "干锅牛蛙", "category": "热菜", "price": 88, "cost": 32, "serves": "2-4人"},
        {"id": "dish_17", "name": "蒸蛋", "category": "热菜", "price": 18, "cost": 4, "serves": "1-2人"},
        {"id": "dish_18", "name": "麻婆豆腐", "category": "热菜", "price": 28, "cost": 6, "serves": "2-4人"},
        {"id": "dish_19", "name": "回锅肉", "category": "热菜", "price": 48, "cost": 16, "serves": "2-4人"},
        {"id": "dish_20", "name": "东坡肘子", "category": "热菜", "price": 98, "cost": 35, "serves": "4-6人"},
        # 汤
        {"id": "dish_21", "name": "番茄蛋汤", "category": "汤", "price": 18, "cost": 4, "serves": "2-4人"},
        {"id": "dish_22", "name": "酸菜鱼汤", "category": "汤", "price": 58, "cost": 20, "serves": "4-6人"},
        {"id": "dish_23", "name": "老鸭汤", "category": "汤", "price": 68, "cost": 25, "serves": "4-6人"},
        {"id": "dish_24", "name": "紫菜蛋花汤", "category": "汤", "price": 12, "cost": 3, "serves": "2-4人"},
        # 主食
        {"id": "dish_25", "name": "扬州炒饭", "category": "主食", "price": 22, "cost": 5, "serves": "1人"},
        {"id": "dish_26", "name": "担担面", "category": "主食", "price": 18, "cost": 4, "serves": "1人"},
        {"id": "dish_27", "name": "葱油拌面", "category": "主食", "price": 15, "cost": 3, "serves": "1人"},
        # 甜点
        {"id": "dish_28", "name": "杨枝甘露", "category": "甜点", "price": 28, "cost": 8, "serves": "1人"},
        {"id": "dish_29", "name": "红糖糍粑", "category": "甜点", "price": 22, "cost": 5, "serves": "2-4人"},
        {"id": "dish_30", "name": "冰粉", "category": "甜点", "price": 12, "cost": 3, "serves": "1人"},
    ]

    # ── 10 种食材 + 供应商 ──
    suppliers = [
        {"id": "sup_01", "name": "湘江水产", "type": "水产"},
        {"id": "sup_02", "name": "辣妹子调料厂", "type": "调料"},
        {"id": "sup_03", "name": "城东蔬菜批发", "type": "蔬菜"},
        {"id": "sup_04", "name": "金牛肉联厂", "type": "肉类"},
        {"id": "sup_05", "name": "南海冻品", "type": "冻品"},
    ]

    ingredients_extra = [
        {"id": "ing_05", "name": "五花肉", "unit_price": 22, "unit": "kg", "supplier_id": "sup_04"},
        {"id": "ing_06", "name": "基围虾", "unit_price": 55, "unit": "kg", "supplier_id": "sup_01"},
        {"id": "ing_07", "name": "螃蟹", "unit_price": 68, "unit": "kg", "supplier_id": "sup_01"},
        {"id": "ing_08", "name": "鸡胸肉", "unit_price": 18, "unit": "kg", "supplier_id": "sup_04"},
        {"id": "ing_09", "name": "豆腐", "unit_price": 4, "unit": "kg", "supplier_id": "sup_03"},
        {"id": "ing_10", "name": "排骨", "unit_price": 35, "unit": "kg", "supplier_id": "sup_04"},
    ]

    # 导入供应商
    for sup in suppliers:
        kg.add_entity("supplier", sup["id"], sup)

    # 导入额外食材及供应商关系
    for ing in ingredients_extra:
        kg.add_entity("ingredient", ing["id"], ing)
        if "supplier_id" in ing:
            kg.add_relationship("supplier", ing["supplier_id"], "SUPPLIES", "ingredient", ing["id"])

    # 同样给前面的食材加供应商关系
    kg.add_relationship("supplier", "sup_01", "SUPPLIES", "ingredient", "ing_01")
    kg.add_relationship("supplier", "sup_02", "SUPPLIES", "ingredient", "ing_02")
    kg.add_relationship("supplier", "sup_03", "SUPPLIES", "ingredient", "ing_03")
    kg.add_relationship("supplier", "sup_01", "SUPPLIES", "ingredient", "ing_04")

    # ── 为每家门店导入数据 ──
    base_metrics = {
        "store_cs_furong": {"revenue": 32000, "order_count": 180, "turnover_rate": 2.4, "avg_check": 95, "labor_efficiency": 580, "profit_margin": 65, "customer_count": 260},
        "store_cs_wuyi": {"revenue": 25000, "order_count": 150, "turnover_rate": 2.0, "avg_check": 82, "labor_efficiency": 480, "profit_margin": 60, "customer_count": 210},
        "store_wh_guanggu": {"revenue": 28000, "order_count": 160, "turnover_rate": 2.2, "avg_check": 88, "labor_efficiency": 520, "profit_margin": 62, "customer_count": 230},
        "store_sz_nanshan": {"revenue": 45000, "order_count": 220, "turnover_rate": 2.8, "avg_check": 120, "labor_efficiency": 650, "profit_margin": 68, "customer_count": 310},
        "store_bj_guomao": {"revenue": 52000, "order_count": 250, "turnover_rate": 3.0, "avg_check": 135, "labor_efficiency": 720, "profit_margin": 70, "customer_count": 350},
    }

    # 30天指标
    base_date = datetime(2026, 2, 24)
    for store in stores:
        sid = store["id"]
        base = base_metrics[sid]
        metrics_list: list[dict] = []

        for day_offset in range(30):
            date = base_date + timedelta(days=day_offset)
            date_str = date.strftime("%Y-%m-%d")
            is_weekend = date.weekday() >= 5
            weekend_mult = 1.25 if is_weekend else 1.0

            # 加入随机波动
            jitter = 1 + (random.random() - 0.5) * 0.15
            wk_jitter = weekend_mult * jitter

            metrics_list.append({
                "id": f"{sid}_{date_str}",
                "date": date_str,
                "revenue": round(base["revenue"] * wk_jitter),
                "order_count": round(base["order_count"] * wk_jitter),
                "turnover_rate": round(base["turnover_rate"] * wk_jitter, 2),
                "avg_check": round(base["avg_check"] * (1 + (random.random() - 0.5) * 0.08), 1),
                "labor_efficiency": round(base["labor_efficiency"] * wk_jitter),
                "profit_margin": round(base["profit_margin"] + (random.random() - 0.5) * 6, 1),
                "customer_count": round(base["customer_count"] * wk_jitter),
            })

        store_data = {
            "store": store,
            "dishes": dishes,
            "metrics": metrics_list,
        }
        kg.ingest_store_data(store_data)

    # ── 20 条 Agent 决策 ──
    decision_templates = [
        {"agent": "discount_guard", "agent_name": "折扣守护Agent", "desc": "检测到异常折扣：桌号15，折扣幅度超过40%", "metric": "profit_margin", "action": "拦截折扣并通知店长", "improvement": 3.2},
        {"agent": "discount_guard", "agent_name": "折扣守护Agent", "desc": "VIP客户折扣合理性校验", "metric": "profit_margin", "action": "允许VIP折扣，毛利在底线之上", "improvement": 0},
        {"agent": "menu_planner", "agent_name": "智能排菜Agent", "desc": "周三下午茶套餐推荐", "metric": "revenue", "action": "推出下午茶套餐68元/位", "improvement": 8.5},
        {"agent": "menu_planner", "agent_name": "智能排菜Agent", "desc": "低毛利菜品预警：水煮鱼成本上涨", "metric": "profit_margin", "action": "建议调整水煮鱼定价至85元", "improvement": 5.1},
        {"agent": "dispatch", "agent_name": "出餐调度Agent", "desc": "午高峰出餐延迟预警", "metric": "turnover_rate", "action": "建议提前备菜，增加一名帮厨", "improvement": 12.0},
        {"agent": "dispatch", "agent_name": "出餐调度Agent", "desc": "晚高峰桌台调度优化", "metric": "turnover_rate", "action": "启用快速翻台模式", "improvement": 8.0},
        {"agent": "member_insight", "agent_name": "会员洞察Agent", "desc": "沉睡会员召回建议", "metric": "customer_count", "action": "向120名沉睡会员发送定向优惠券", "improvement": 6.5},
        {"agent": "member_insight", "agent_name": "会员洞察Agent", "desc": "高价值客户流失预警", "metric": "customer_count", "action": "为3名高价值客户安排店长回访", "improvement": 2.0},
        {"agent": "inventory", "agent_name": "库存预警Agent", "desc": "鳙鱼头库存不足，预计明天售罄", "metric": "revenue", "action": "紧急补货50kg鳙鱼头", "improvement": 0},
        {"agent": "inventory", "agent_name": "库存预警Agent", "desc": "基围虾临近保质期", "metric": "profit_margin", "action": "今日推出基围虾特价套餐消化库存", "improvement": 4.0},
        {"agent": "finance_audit", "agent_name": "财务稽核Agent", "desc": "发现收银差异：现金收入与系统记录不符", "metric": "revenue", "action": "触发收银稽核流程", "improvement": 1.5},
        {"agent": "finance_audit", "agent_name": "财务稽核Agent", "desc": "供应商账单异常：蔬菜价格偏离市场价20%", "metric": "profit_margin", "action": "建议与供应商重新议价", "improvement": 3.8},
        {"agent": "patrol", "agent_name": "巡店质检Agent", "desc": "后厨卫生检查评分偏低", "metric": "customer_satisfaction", "action": "安排深度清洁并重新培训", "improvement": 0},
        {"agent": "patrol", "agent_name": "巡店质检Agent", "desc": "前厅服务评分下降", "metric": "customer_satisfaction", "action": "组织服务标准化培训", "improvement": 5.0},
        {"agent": "menu_planner", "agent_name": "智能排菜Agent", "desc": "季节性菜品调整建议", "metric": "revenue", "action": "上线3道春季新品，下线2道冬季菜", "improvement": 6.2},
        {"agent": "dispatch", "agent_name": "出餐调度Agent", "desc": "外卖高峰出餐优化", "metric": "turnover_rate", "action": "外卖单独设置出餐通道", "improvement": 10.0},
        {"agent": "member_insight", "agent_name": "会员洞察Agent", "desc": "生日营销建议", "metric": "customer_count", "action": "本周生日会员推送专属套餐", "improvement": 3.0},
        {"agent": "inventory", "agent_name": "库存预警Agent", "desc": "调料库存充足，建议减少采购频次", "metric": "profit_margin", "action": "将调料采购频次从每周改为双周", "improvement": 1.2},
        {"agent": "discount_guard", "agent_name": "折扣守护Agent", "desc": "团购券核销异常", "metric": "profit_margin", "action": "暂停异常团购券并人工复核", "improvement": 2.5},
        {"agent": "menu_planner", "agent_name": "智能排菜Agent", "desc": "剁椒鱼头定价优化", "metric": "revenue", "action": "建议将剁椒鱼头从128元调至138元", "improvement": 7.8},
    ]

    store_ids = [s["id"] for s in stores]
    for i, tmpl in enumerate(decision_templates):
        sid = store_ids[i % len(store_ids)]
        date = (base_date + timedelta(days=i % 30)).strftime("%Y-%m-%d")
        decision = {
            "id": f"dec_{i+1:03d}",
            "agent_id": tmpl["agent"],
            "agent_name": tmpl["agent_name"],
            "store_id": sid,
            "date": date,
            "description": tmpl["desc"],
            "metric": tmpl["metric"],
            "action": tmpl["action"],
            "outcome": {
                "improvement_pct": tmpl["improvement"],
                "applied": tmpl["improvement"] > 0,
                "result_description": f"实施后{METRIC_CN_MAP.get(tmpl['metric'], tmpl['metric'])}提升{tmpl['improvement']}%" if tmpl["improvement"] > 0 else "已执行",
            },
        }
        kg.ingest_decision_data(decision)

    # ── 5 条最佳实践 ──
    best_practices = [
        {
            "id": "bp_001",
            "title": "午高峰提前备菜制度",
            "description": "在11:00前完成80%热门菜品的备料工作，减少高峰期出餐时间。实施后翻台率平均提升15%。",
            "metric": "turnover_rate",
            "improvement_pct": 15,
            "discovered_at_store": "store_bj_guomao",
            "applicable_to": ["海鲜酒楼", "中餐厅", "all"],
        },
        {
            "id": "bp_002",
            "title": "动态定价策略",
            "description": "根据食材成本波动和客流量动态调整菜品价格，非高峰时段推出限时特价套餐。营业额平均提升10%。",
            "metric": "revenue",
            "improvement_pct": 10,
            "discovered_at_store": "store_sz_nanshan",
            "applicable_to": ["海鲜酒楼", "all"],
        },
        {
            "id": "bp_003",
            "title": "员工交叉培训计划",
            "description": "服务员掌握基本传菜技能，厨师了解前厅忙闲状态。高峰期灵活调配人力，人效提升20%。",
            "metric": "labor_efficiency",
            "improvement_pct": 20,
            "discovered_at_store": "store_cs_furong",
            "applicable_to": ["海鲜酒楼", "中餐厅", "all"],
        },
        {
            "id": "bp_004",
            "title": "会员精准营销体系",
            "description": "基于RFM模型分层运营会员，高价值会员专属服务，沉睡会员定向召回。客流量平均提升12%。",
            "metric": "customer_count",
            "improvement_pct": 12,
            "discovered_at_store": "store_sz_nanshan",
            "applicable_to": ["海鲜酒楼", "all"],
        },
        {
            "id": "bp_005",
            "title": "食材联合采购与损耗管控",
            "description": "多店联合采购降低单价，建立每日损耗追踪机制。毛利率平均提升5个百分点。",
            "metric": "profit_margin",
            "improvement_pct": 5,
            "discovered_at_store": "store_wh_guanggu",
            "applicable_to": ["海鲜酒楼", "中餐厅", "all"],
        },
    ]

    for bp in best_practices:
        kg.ingest_best_practice(bp)

    return kg
