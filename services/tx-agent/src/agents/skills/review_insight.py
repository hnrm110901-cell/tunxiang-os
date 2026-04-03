"""评论主题洞察 Agent — P1 | 云端

评论主题提取、情感分析、评分趋势监测、差评根因分析、评论关键词云、评论回复建议。
"""
from typing import Any

from ..base import AgentResult, SkillAgent

# 评论主题分类
REVIEW_TOPICS = {
    "taste": {"name": "口味", "keywords": ["好吃", "难吃", "味道", "口味", "咸", "辣", "淡", "鲜", "甜"]},
    "service": {"name": "服务", "keywords": ["服务", "态度", "热情", "冷漠", "服务员", "上菜慢", "等"]},
    "environment": {"name": "环境", "keywords": ["环境", "装修", "干净", "脏", "吵", "安静", "氛围"]},
    "price": {"name": "价格", "keywords": ["贵", "便宜", "性价比", "划算", "值", "不值"]},
    "portion": {"name": "分量", "keywords": ["分量", "少", "多", "够吃", "不够"]},
    "freshness": {"name": "新鲜度", "keywords": ["新鲜", "不新鲜", "冷", "凉", "隔夜"]},
    "speed": {"name": "出餐速度", "keywords": ["快", "慢", "等了", "分钟", "半小时", "上菜"]},
    "hygiene": {"name": "卫生", "keywords": ["卫生", "干净", "脏", "头发", "虫", "异物"]},
}


class ReviewInsightAgent(SkillAgent):
    agent_id = "review_insight"
    agent_name = "评论主题洞察"
    description = "评论主题提取、情感分析、评分趋势、差评根因分析、关键词云、回复建议"
    priority = "P1"
    run_location = "cloud"

    def get_supported_actions(self) -> list[str]:
        return [
            "extract_review_topics",
            "analyze_sentiment",
            "track_rating_trend",
            "analyze_bad_review_root_cause",
            "generate_keyword_cloud",
            "suggest_review_replies",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "extract_review_topics": self._extract_topics,
            "analyze_sentiment": self._analyze_sentiment,
            "track_rating_trend": self._track_trend,
            "analyze_bad_review_root_cause": self._bad_review_root_cause,
            "generate_keyword_cloud": self._keyword_cloud,
            "suggest_review_replies": self._suggest_replies,
        }
        handler = dispatch.get(action)
        if handler:
            return await handler(params)
        return AgentResult(success=False, action=action, error=f"不支持的操作: {action}")

    async def _extract_topics(self, params: dict) -> AgentResult:
        """评论主题提取"""
        reviews = params.get("reviews", [])
        topic_counts: dict[str, dict] = {}

        for topic_key, topic_info in REVIEW_TOPICS.items():
            topic_counts[topic_key] = {"name": topic_info["name"], "positive": 0, "negative": 0, "total": 0}

        for review in reviews:
            text = review.get("text", "")
            rating = review.get("rating", 3)
            sentiment = "positive" if rating >= 4 else "negative"

            for topic_key, topic_info in REVIEW_TOPICS.items():
                if any(kw in text for kw in topic_info["keywords"]):
                    topic_counts[topic_key]["total"] += 1
                    topic_counts[topic_key][sentiment] += 1

        # 排序
        ranked_topics = sorted(topic_counts.items(), key=lambda x: x[1]["total"], reverse=True)
        total_reviews = len(reviews)

        return AgentResult(
            success=True, action="extract_review_topics",
            data={
                "topics": [{
                    "topic": k,
                    "topic_name": v["name"],
                    "mention_count": v["total"],
                    "mention_pct": round(v["total"] / max(1, total_reviews) * 100, 1),
                    "positive": v["positive"],
                    "negative": v["negative"],
                    "sentiment_ratio": round(v["positive"] / max(1, v["total"]), 2),
                } for k, v in ranked_topics if v["total"] > 0],
                "total_reviews": total_reviews,
            },
            reasoning=f"从 {total_reviews} 条评论中提取 "
                      f"{sum(1 for _, v in ranked_topics if v['total'] > 0)} 个主题",
            confidence=0.8,
        )

    async def _analyze_sentiment(self, params: dict) -> AgentResult:
        """情感分析"""
        reviews = params.get("reviews", [])
        positive_keywords = ["好吃", "推荐", "满意", "不错", "赞", "棒", "优秀", "喜欢", "下次还来"]
        negative_keywords = ["差", "难吃", "不满", "失望", "糟糕", "再也不来", "退款", "投诉"]

        results = {"positive": 0, "neutral": 0, "negative": 0}
        review_sentiments = []

        for review in reviews:
            text = review.get("text", "")
            rating = review.get("rating", 3)

            pos_count = sum(1 for kw in positive_keywords if kw in text)
            neg_count = sum(1 for kw in negative_keywords if kw in text)

            # 综合评分和关键词
            if rating >= 4 or pos_count > neg_count:
                sentiment = "positive"
                score = min(1.0, 0.5 + pos_count * 0.1 + (rating - 3) * 0.1)
            elif rating <= 2 or neg_count > pos_count:
                sentiment = "negative"
                score = max(0.0, 0.5 - neg_count * 0.1 - (3 - rating) * 0.1)
            else:
                sentiment = "neutral"
                score = 0.5

            results[sentiment] += 1
            review_sentiments.append({
                "review_id": review.get("review_id", ""),
                "sentiment": sentiment,
                "score": round(score, 2),
                "text_preview": text[:50],
            })

        total = len(reviews)
        return AgentResult(
            success=True, action="analyze_sentiment",
            data={
                "distribution": {k: {"count": v, "pct": round(v / max(1, total) * 100, 1)}
                                for k, v in results.items()},
                "total_reviews": total,
                "overall_sentiment": "正面" if results["positive"] > results["negative"] * 2 else
                                    "负面" if results["negative"] > results["positive"] else "中性",
                "details": review_sentiments[:20],
            },
            reasoning=f"情感分析: 正面{results['positive']}、中性{results['neutral']}、负面{results['negative']}",
            confidence=0.75,
        )

    async def _track_trend(self, params: dict) -> AgentResult:
        """评分趋势监测"""
        period_ratings = params.get("period_ratings", [])

        if not period_ratings:
            return AgentResult(success=False, action="track_rating_trend", error="无评分数据")

        trends = []
        for i, period in enumerate(period_ratings):
            avg = period.get("avg_rating", 0)
            count = period.get("review_count", 0)
            prev_avg = period_ratings[i - 1].get("avg_rating", avg) if i > 0 else avg
            change = round(avg - prev_avg, 2)

            trends.append({
                "period": period.get("period", ""),
                "avg_rating": avg,
                "review_count": count,
                "change": change,
                "direction": "上升" if change > 0.1 else "下降" if change < -0.1 else "持平",
            })

        latest = trends[-1] if trends else {}
        overall_direction = "上升" if len(trends) >= 2 and trends[-1]["avg_rating"] > trends[0]["avg_rating"] else \
                           "下降" if len(trends) >= 2 and trends[-1]["avg_rating"] < trends[0]["avg_rating"] else "持平"

        return AgentResult(
            success=True, action="track_rating_trend",
            data={
                "trends": trends,
                "latest_avg": latest.get("avg_rating", 0),
                "overall_direction": overall_direction,
                "total_periods": len(trends),
                "alert": latest.get("avg_rating", 5) < 4.0,
            },
            reasoning=f"评分趋势: 最新 {latest.get('avg_rating', 0)}，整体{overall_direction}",
            confidence=0.85,
        )

    async def _bad_review_root_cause(self, params: dict) -> AgentResult:
        """差评根因分析"""
        bad_reviews = params.get("bad_reviews", [])
        root_causes: dict[str, dict] = {}

        for review in bad_reviews:
            text = review.get("text", "")
            for topic_key, topic_info in REVIEW_TOPICS.items():
                if any(kw in text for kw in topic_info["keywords"]):
                    if topic_key not in root_causes:
                        root_causes[topic_key] = {"name": topic_info["name"], "count": 0, "examples": []}
                    root_causes[topic_key]["count"] += 1
                    if len(root_causes[topic_key]["examples"]) < 3:
                        root_causes[topic_key]["examples"].append(text[:80])

        ranked = sorted(root_causes.items(), key=lambda x: x[1]["count"], reverse=True)
        total = len(bad_reviews)

        return AgentResult(
            success=True, action="analyze_bad_review_root_cause",
            data={
                "root_causes": [{
                    "cause": k,
                    "cause_name": v["name"],
                    "count": v["count"],
                    "pct": round(v["count"] / max(1, total) * 100, 1),
                    "examples": v["examples"],
                } for k, v in ranked],
                "total_bad_reviews": total,
                "top_cause": ranked[0][1]["name"] if ranked else "无",
            },
            reasoning=f"差评根因: TOP1 {ranked[0][1]['name']}（{ranked[0][1]['count']}次）" if ranked else "无差评数据",
            confidence=0.75,
        )

    async def _keyword_cloud(self, params: dict) -> AgentResult:
        """评论关键词云"""
        reviews = params.get("reviews", [])
        all_keywords: dict[str, int] = {}

        for topic_info in REVIEW_TOPICS.values():
            for kw in topic_info["keywords"]:
                count = sum(1 for r in reviews if kw in r.get("text", ""))
                if count > 0:
                    all_keywords[kw] = count

        # 额外高频词提取
        extra_words = ["好评", "推荐", "朋友", "聚餐", "约会", "家庭", "排队", "打卡", "网红", "老字号"]
        for word in extra_words:
            count = sum(1 for r in reviews if word in r.get("text", ""))
            if count > 0:
                all_keywords[word] = count

        ranked = sorted(all_keywords.items(), key=lambda x: x[1], reverse=True)[:30]

        return AgentResult(
            success=True, action="generate_keyword_cloud",
            data={
                "keywords": [{"word": k, "count": v, "weight": round(v / max(1, len(reviews)), 2)}
                            for k, v in ranked],
                "total_reviews": len(reviews),
                "top_keyword": ranked[0][0] if ranked else "无",
            },
            reasoning=f"从 {len(reviews)} 条评论提取 {len(ranked)} 个关键词，TOP1: {ranked[0][0] if ranked else '无'}",
            confidence=0.8,
        )

    async def _suggest_replies(self, params: dict) -> AgentResult:
        """评论回复建议"""
        reviews = params.get("reviews", [])
        brand_name = params.get("brand_name", "")

        suggestions = []
        for review in reviews[:20]:
            rating = review.get("rating", 3)
            text = review.get("text", "")

            if rating >= 4:
                reply = f"感谢您对{brand_name}的认可，您的支持是我们前进的动力！"
                urgency = "low"
            elif rating >= 3:
                reply = "感谢您的反馈，我们会认真改进，期待为您提供更好的体验。"
                urgency = "medium"
            else:
                # 识别具体问题
                issues = []
                for topic_info in REVIEW_TOPICS.values():
                    if any(kw in text for kw in topic_info["keywords"]):
                        issues.append(topic_info["name"])

                issue_text = "、".join(issues[:2]) if issues else "您反映的问题"
                reply = f"非常抱歉！关于{issue_text}，我们高度重视并将立即改进。请联系我们获取补偿。"
                urgency = "high"

            suggestions.append({
                "review_id": review.get("review_id", ""),
                "rating": rating,
                "suggested_reply": reply,
                "urgency": urgency,
                "platform": review.get("platform", "大众点评"),
            })

        return AgentResult(
            success=True, action="suggest_review_replies",
            data={
                "suggestions": suggestions,
                "total": len(suggestions),
                "urgent_count": sum(1 for s in suggestions if s["urgency"] == "high"),
            },
            reasoning=f"生成 {len(suggestions)} 条回复建议，紧急 {sum(1 for s in suggestions if s['urgency'] == 'high')} 条",
            confidence=0.8,
        )
