"""搜索趋势洞察 Agent — P1 | 云端

搜索热词分析、趋势变化检测、消费者需求洞察、区域热度对比、品类趋势预测、热点事件关联。
"""

from typing import Any

from ..base import AgentResult, SkillAgent

# 餐饮搜索趋势品类
FOOD_CATEGORIES = [
    "火锅",
    "烧烤",
    "湘菜",
    "川菜",
    "粤菜",
    "日料",
    "西餐",
    "面食",
    "奶茶",
    "咖啡",
    "小龙虾",
    "螺蛳粉",
    "预制菜",
    "轻食沙拉",
    "露营烧烤",
]


class TrendDiscoveryAgent(SkillAgent):
    agent_id = "trend_discovery"
    agent_name = "搜索趋势洞察"
    description = "搜索热词分析、趋势变化检测、消费者需求洞察、区域热度对比、品类趋势预测、热点关联"
    priority = "P1"
    run_location = "cloud"

    def get_supported_actions(self) -> list[str]:
        return [
            "analyze_search_hot_words",
            "detect_trend_change",
            "discover_consumer_demand",
            "compare_regional_heat",
            "predict_category_trend",
            "correlate_hot_events",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "analyze_search_hot_words": self._analyze_hot_words,
            "detect_trend_change": self._detect_trend_change,
            "discover_consumer_demand": self._discover_demand,
            "compare_regional_heat": self._compare_regional,
            "predict_category_trend": self._predict_category,
            "correlate_hot_events": self._correlate_events,
        }
        handler = dispatch.get(action)
        if handler:
            return await handler(params)
        return AgentResult(success=False, action=action, error=f"不支持的操作: {action}")

    async def _analyze_hot_words(self, params: dict) -> AgentResult:
        """搜索热词分析"""
        search_data = params.get("search_data", [])
        platform = params.get("platform", "美团")
        period = params.get("period", "week")

        ranked = sorted(search_data, key=lambda x: x.get("search_volume", 0), reverse=True)
        total_volume = sum(s.get("search_volume", 0) for s in search_data)

        hot_words = []
        for i, item in enumerate(ranked[:20]):
            hot_words.append(
                {
                    "rank": i + 1,
                    "keyword": item.get("keyword", ""),
                    "search_volume": item.get("search_volume", 0),
                    "volume_pct": round(item.get("search_volume", 0) / max(1, total_volume) * 100, 1),
                    "trend": item.get("trend", "持平"),
                    "growth_pct": item.get("growth_pct", 0),
                    "related_category": item.get("category", "其他"),
                }
            )

        return AgentResult(
            success=True,
            action="analyze_search_hot_words",
            data={
                "hot_words": hot_words,
                "platform": platform,
                "period": period,
                "total_keywords_analyzed": len(search_data),
                "top_keyword": hot_words[0]["keyword"] if hot_words else "无",
            },
            reasoning=f"{platform}搜索热词 TOP1: {hot_words[0]['keyword'] if hot_words else '无'}，"
            f"分析 {len(search_data)} 个关键词",
            confidence=0.8,
        )

    async def _detect_trend_change(self, params: dict) -> AgentResult:
        """趋势变化检测"""
        current_trends = params.get("current_trends", [])
        previous_trends = params.get("previous_trends", [])

        prev_map = {t.get("keyword"): t.get("rank", 999) for t in previous_trends}
        changes = []

        for trend in current_trends:
            keyword = trend.get("keyword", "")
            current_rank = trend.get("rank", 999)
            prev_rank = prev_map.get(keyword, 0)

            if prev_rank == 0:
                change_type = "新上榜"
                rank_change = 0
            elif current_rank < prev_rank:
                change_type = "上升"
                rank_change = prev_rank - current_rank
            elif current_rank > prev_rank:
                change_type = "下降"
                rank_change = prev_rank - current_rank
            else:
                change_type = "持平"
                rank_change = 0

            if change_type != "持平":
                changes.append(
                    {
                        "keyword": keyword,
                        "current_rank": current_rank,
                        "previous_rank": prev_rank if prev_rank > 0 else None,
                        "change_type": change_type,
                        "rank_change": rank_change,
                        "volume_change_pct": trend.get("volume_change_pct", 0),
                    }
                )

        # 消失的热词
        current_keywords = {t.get("keyword") for t in current_trends}
        dropped = [
            {"keyword": t.get("keyword"), "change_type": "下榜", "previous_rank": t.get("rank")}
            for t in previous_trends
            if t.get("keyword") not in current_keywords
        ]

        return AgentResult(
            success=True,
            action="detect_trend_change",
            data={
                "rising": [c for c in changes if c["change_type"] in ("上升", "新上榜")],
                "falling": [c for c in changes if c["change_type"] == "下降"],
                "dropped": dropped[:10],
                "total_changes": len(changes),
            },
            reasoning=f"趋势变化: {sum(1 for c in changes if c['change_type'] in ('上升', '新上榜'))} 上升，"
            f"{sum(1 for c in changes if c['change_type'] == '下降')} 下降，"
            f"{len(dropped)} 下榜",
            confidence=0.75,
        )

    async def _discover_demand(self, params: dict) -> AgentResult:
        """消费者需求洞察"""
        search_queries = params.get("search_queries", [])
        review_keywords = params.get("review_keywords", [])

        demand_signals = {
            "flavor_demand": [],
            "scene_demand": [],
            "price_demand": [],
            "health_demand": [],
        }

        flavor_words = ["辣", "酸", "甜", "鲜", "清淡", "重口"]
        scene_words = ["聚餐", "约会", "家庭", "商务", "一人食", "外卖"]
        price_words = ["便宜", "实惠", "性价比", "人均"]
        health_words = ["低卡", "养生", "无糖", "有机", "轻食"]

        all_text = [q.get("query", "") for q in search_queries] + [k.get("keyword", "") for k in review_keywords]

        for text in all_text:
            for word in flavor_words:
                if word in text and word not in [d.get("signal") for d in demand_signals["flavor_demand"]]:
                    demand_signals["flavor_demand"].append(
                        {"signal": word, "mentions": sum(1 for t in all_text if word in t)}
                    )
            for word in scene_words:
                if word in text and word not in [d.get("signal") for d in demand_signals["scene_demand"]]:
                    demand_signals["scene_demand"].append(
                        {"signal": word, "mentions": sum(1 for t in all_text if word in t)}
                    )
            for word in price_words:
                if word in text and word not in [d.get("signal") for d in demand_signals["price_demand"]]:
                    demand_signals["price_demand"].append(
                        {"signal": word, "mentions": sum(1 for t in all_text if word in t)}
                    )
            for word in health_words:
                if word in text and word not in [d.get("signal") for d in demand_signals["health_demand"]]:
                    demand_signals["health_demand"].append(
                        {"signal": word, "mentions": sum(1 for t in all_text if word in t)}
                    )

        # 排序
        for key in demand_signals:
            demand_signals[key].sort(key=lambda x: x["mentions"], reverse=True)

        return AgentResult(
            success=True,
            action="discover_consumer_demand",
            data={
                "demand_signals": demand_signals,
                "total_data_points": len(all_text),
                "top_flavor": demand_signals["flavor_demand"][0]["signal"] if demand_signals["flavor_demand"] else "无",
                "top_scene": demand_signals["scene_demand"][0]["signal"] if demand_signals["scene_demand"] else "无",
            },
            reasoning=f"消费需求洞察: 口味偏好 {demand_signals['flavor_demand'][0]['signal'] if demand_signals['flavor_demand'] else '无'}，"
            f"场景偏好 {demand_signals['scene_demand'][0]['signal'] if demand_signals['scene_demand'] else '无'}",
            confidence=0.7,
        )

    async def _compare_regional(self, params: dict) -> AgentResult:
        """区域热度对比"""
        regions = params.get("regions", [])
        category = params.get("category", "")

        ranked = sorted(regions, key=lambda x: x.get("heat_index", 0), reverse=True)
        max_heat = ranked[0].get("heat_index", 1) if ranked else 1

        comparisons = []
        for r in ranked:
            comparisons.append(
                {
                    "region": r.get("region", ""),
                    "heat_index": r.get("heat_index", 0),
                    "normalized_heat": round(r.get("heat_index", 0) / max(1, max_heat) * 100, 1),
                    "store_count": r.get("store_count", 0),
                    "avg_rating": r.get("avg_rating", 0),
                    "search_volume": r.get("search_volume", 0),
                }
            )

        return AgentResult(
            success=True,
            action="compare_regional_heat",
            data={
                "category": category,
                "regions": comparisons,
                "hottest_region": comparisons[0]["region"] if comparisons else "无",
                "total_regions": len(comparisons),
            },
            reasoning=f"「{category}」区域热度: TOP1 {comparisons[0]['region'] if comparisons else '无'}",
            confidence=0.75,
        )

    async def _predict_category(self, params: dict) -> AgentResult:
        """品类趋势预测"""
        categories = params.get("categories", [])
        predictions = []

        for cat in categories:
            name = cat.get("name", "")
            growth_rate = cat.get("recent_growth_pct", 0)
            search_trend = cat.get("search_trend", "持平")
            store_growth = cat.get("store_growth_pct", 0)

            # 简化预测模型
            momentum = growth_rate * 0.4 + store_growth * 0.3
            if search_trend == "上升":
                momentum += 10
            elif search_trend == "下降":
                momentum -= 10

            predictions.append(
                {
                    "category": name,
                    "current_growth_pct": growth_rate,
                    "predicted_next_quarter_growth": round(momentum * 0.8, 1),
                    "trend_direction": "上升" if momentum > 5 else "下降" if momentum < -5 else "持平",
                    "confidence": 0.7 if abs(momentum) > 10 else 0.5,
                    "recommendation": "重点布局"
                    if momentum > 15
                    else "持续关注"
                    if momentum > 5
                    else "谨慎投入"
                    if momentum > -5
                    else "收缩调整",
                }
            )

        predictions.sort(key=lambda x: x["predicted_next_quarter_growth"], reverse=True)

        return AgentResult(
            success=True,
            action="predict_category_trend",
            data={
                "predictions": predictions,
                "rising_categories": [p["category"] for p in predictions if p["trend_direction"] == "上升"],
                "declining_categories": [p["category"] for p in predictions if p["trend_direction"] == "下降"],
            },
            reasoning=f"品类预测: 上升 {sum(1 for p in predictions if p['trend_direction'] == '上升')} 个，"
            f"下降 {sum(1 for p in predictions if p['trend_direction'] == '下降')} 个",
            confidence=0.65,
        )

    async def _correlate_events(self, params: dict) -> AgentResult:
        """热点事件关联"""
        hot_events = params.get("hot_events", [])
        our_categories = params.get("our_categories", [])

        correlations = []
        for event in hot_events:
            event_name = event.get("name", "")
            event_keywords = event.get("keywords", [])
            heat = event.get("heat_score", 0)

            related_categories = []
            for cat in our_categories:
                cat_keywords = cat.get("keywords", [])
                overlap = len(set(event_keywords) & set(cat_keywords))
                if overlap > 0:
                    related_categories.append(
                        {
                            "category": cat.get("name", ""),
                            "relevance": round(overlap / max(1, len(event_keywords)), 2),
                        }
                    )

            if related_categories:
                correlations.append(
                    {
                        "event": event_name,
                        "heat_score": heat,
                        "related_categories": sorted(related_categories, key=lambda x: x["relevance"], reverse=True),
                        "marketing_opportunity": heat >= 70 and len(related_categories) > 0,
                        "suggested_action": "借势营销" if heat >= 70 else "内容关联" if heat >= 40 else "观望",
                    }
                )

        return AgentResult(
            success=True,
            action="correlate_hot_events",
            data={
                "correlations": correlations,
                "total_events": len(hot_events),
                "opportunities": sum(1 for c in correlations if c["marketing_opportunity"]),
            },
            reasoning=f"发现 {sum(1 for c in correlations if c['marketing_opportunity'])} 个热点借势机会",
            confidence=0.65,
        )
