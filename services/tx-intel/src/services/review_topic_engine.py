"""口碑主题抽取引擎 — 把评价系统转成经营问题与卖点来源

从大量顾客评价中抽取结构化主题，区分好评/差评，
识别菜品提及、服务提及、卫生问题等，输出可执行的改进建议和营销素材。
"""
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog

logger = structlog.get_logger()


# ─── 常量 ───

TOPIC_TYPES = {
    "positive": "好评主题",
    "negative": "差评主题",
    "dish_mention": "菜品提及",
    "service_mention": "服务提及",
    "hygiene": "卫生/整洁",
    "wait_time": "等待时间",
    "value_for_money": "性价比",
}

# ─── 关键词提取规则（模拟 NLP） ───

_POSITIVE_KEYWORDS = [
    "好吃", "美味", "鲜嫩", "入味", "惊艳", "推荐", "回头客", "满意",
    "服务好", "态度好", "热情", "干净", "整洁", "快", "划算", "值",
    "正宗", "地道", "分量足", "新鲜", "环境好", "氛围好",
]

_NEGATIVE_KEYWORDS = [
    "难吃", "太咸", "太辣", "太油", "不新鲜", "冷了", "分量少",
    "服务差", "态度差", "忽视", "脏", "不干净", "油腻", "苍蝇",
    "慢", "等太久", "贵", "不值", "坑", "失望", "差评",
    "头发", "异物", "拉肚子",
]

_DISH_KEYWORDS = {
    "辣椒炒肉": "招牌菜",
    "小炒黄牛肉": "招牌菜",
    "剁椒鱼头": "招牌菜",
    "酸汤肥牛": "热门菜",
    "口味虾": "季节菜",
    "臭豆腐": "特色菜",
    "糖油粑粑": "小吃",
    "米饭": "主食",
    "紫苏桃子姜": "凉菜",
    "农家小炒肉": "家常菜",
    "外婆菜": "家常菜",
    "腊味合蒸": "招牌菜",
    "酸豆角": "配菜",
    "土鸡汤": "汤品",
    "甜品": "甜品",
    "饮料": "饮品",
}

_SERVICE_KEYWORDS = [
    "服务", "服务员", "态度", "热情", "微笑", "倒水", "加菜",
    "催菜", "上菜", "等位", "排队", "预订", "包间",
]

_HYGIENE_KEYWORDS = [
    "干净", "整洁", "卫生", "脏", "油腻", "异物", "头发",
    "苍蝇", "蟑螂", "桌面", "地面", "洗手间", "餐具",
]

# ─── 种子评价数据 ───

_SEED_REVIEWS: list[dict] = [
    {"store_id": "S001", "rating": 5, "content": "辣椒炒肉很正宗，肉嫩入味，服务态度好，环境干净整洁，下次还来"},
    {"store_id": "S001", "rating": 4, "content": "剁椒鱼头很鲜嫩，但等位等了30分钟，建议优化排队系统"},
    {"store_id": "S001", "rating": 2, "content": "小炒黄牛肉太咸了，分量也少，服务员态度一般，性价比不高"},
    {"store_id": "S001", "rating": 5, "content": "口味虾太好吃了！推荐推荐！朋友聚会首选"},
    {"store_id": "S001", "rating": 1, "content": "菜里发现头发，太恶心了，卫生堪忧，差评"},
    {"store_id": "S002", "rating": 4, "content": "酸汤肥牛很开胃，米饭管够，服务热情，划算"},
    {"store_id": "S002", "rating": 3, "content": "菜品味道还行，但上菜太慢了，等了40分钟才上齐"},
    {"store_id": "S002", "rating": 5, "content": "腊味合蒸地道，土鸡汤鲜美，分量足，回头客"},
    {"store_id": "S002", "rating": 2, "content": "外婆菜太油了，桌面有点脏，餐具也不太干净"},
    {"store_id": "S005", "rating": 4, "content": "环境好，适合商务宴请，辣椒炒肉分量足，推荐"},
    {"store_id": "S005", "rating": 3, "content": "价格偏贵，菜量一般，服务还可以，性价比一般"},
    {"store_id": "S005", "rating": 5, "content": "紫苏桃子姜很惊艳，甜品也不错，氛围好，闺蜜聚会很开心"},
    {"store_id": "S005", "rating": 2, "content": "催了三次菜才上，服务员态度差，太失望了"},
    {"store_id": "S010", "rating": 4, "content": "臭豆腐正宗，糖油粑粑好吃，有长沙味道，值得一来"},
    {"store_id": "S010", "rating": 3, "content": "饮料种类少，甜品一般，但主菜水平在线"},
    {"store_id": "S010", "rating": 1, "content": "地面很油腻，洗手间不干净，菜冷了也不换，差评"},
]


# ─── 数据模型 ───

@dataclass
class ReviewAnalysis:
    """单条评价分析结果"""
    review_id: str
    store_id: str
    rating: int
    content: str
    sentiment: float  # -1 to 1
    topics: list[dict] = field(default_factory=list)
    dishes_mentioned: list[str] = field(default_factory=list)
    is_actionable: bool = False
    analyzed_at: str = ""


@dataclass
class TopicAggregate:
    """主题聚合"""
    topic_type: str
    topic_name: str
    mention_count: int = 0
    avg_sentiment: float = 0.0
    store_ids: list[str] = field(default_factory=list)
    sample_reviews: list[str] = field(default_factory=list)
    trend: str = "stable"


class ReviewTopicEngine:
    """口碑主题抽取引擎 — 把评价系统转成经营问题与卖点来源"""

    def __init__(self) -> None:
        self._analyses: list[ReviewAnalysis] = []
        self._topic_aggregates: dict[str, TopicAggregate] = {}
        self._load_seed_data()

    def _load_seed_data(self) -> None:
        self.analyze_reviews(_SEED_REVIEWS)
        logger.info("review_topic_seed_loaded", analyses=len(self._analyses),
                     topic_aggregates=len(self._topic_aggregates))

    # ─── 评价分析 ───

    def analyze_reviews(self, reviews: list[dict]) -> dict:
        """批量分析评价：提取主题、情感、实体"""
        results: list[dict] = []
        topic_counter: Counter = Counter()
        dish_counter: Counter = Counter()
        sentiments: list[float] = []

        for review in reviews:
            analysis = self._analyze_single(review)
            self._analyses.append(analysis)
            results.append({
                "review_id": analysis.review_id,
                "store_id": analysis.store_id,
                "sentiment": analysis.sentiment,
                "topics": analysis.topics,
                "dishes_mentioned": analysis.dishes_mentioned,
                "is_actionable": analysis.is_actionable,
            })
            sentiments.append(analysis.sentiment)
            for t in analysis.topics:
                topic_counter[t["topic_name"]] += 1
                self._update_aggregate(t["topic_type"], t["topic_name"],
                                       analysis.sentiment, analysis.store_id,
                                       analysis.content)
            for d in analysis.dishes_mentioned:
                dish_counter[d] += 1

        avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else 0.0

        return {
            "total_analyzed": len(reviews),
            "avg_sentiment": round(avg_sentiment, 2),
            "top_topics": [{"topic": t, "count": c} for t, c in topic_counter.most_common(5)],
            "top_dishes_mentioned": [{"dish": d, "count": c} for d, c in dish_counter.most_common(5)],
            "actionable_count": sum(1 for r in results if r["is_actionable"]),
            "results": results,
        }

    def _analyze_single(self, review: dict) -> ReviewAnalysis:
        """分析单条评价"""
        content = review.get("content", "")
        rating = review.get("rating", 3)
        store_id = review.get("store_id", "")

        # 情感分析
        pos = sum(1 for w in _POSITIVE_KEYWORDS if w in content)
        neg = sum(1 for w in _NEGATIVE_KEYWORDS if w in content)
        total = pos + neg
        sentiment = (pos - neg) / total if total > 0 else 0.0
        # 结合评分
        rating_sentiment = (rating - 3) / 2.0
        sentiment = round((sentiment + rating_sentiment) / 2, 2)

        # 主题提取
        topics: list[dict] = []

        # 好评/差评主题
        for kw in _POSITIVE_KEYWORDS:
            if kw in content:
                topics.append({"topic_type": "positive", "topic_name": kw, "keyword": kw})
        for kw in _NEGATIVE_KEYWORDS:
            if kw in content:
                topics.append({"topic_type": "negative", "topic_name": kw, "keyword": kw})

        # 菜品提及
        dishes_mentioned: list[str] = []
        for dish, cat in _DISH_KEYWORDS.items():
            if dish in content:
                dishes_mentioned.append(dish)
                topics.append({"topic_type": "dish_mention", "topic_name": dish, "dish_category": cat})

        # 服务提及
        for kw in _SERVICE_KEYWORDS:
            if kw in content:
                topics.append({"topic_type": "service_mention", "topic_name": kw, "keyword": kw})
                break  # 只记一次

        # 卫生提及
        for kw in _HYGIENE_KEYWORDS:
            if kw in content:
                is_negative = any(nw in content for nw in ["脏", "油腻", "异物", "头发", "苍蝇", "蟑螂", "不干净"])
                topics.append({
                    "topic_type": "hygiene",
                    "topic_name": "卫生问题" if is_negative else "卫生好评",
                    "keyword": kw,
                })
                break

        # 等待时间
        if any(kw in content for kw in ["等位", "排队", "等了", "太慢", "上菜慢", "催菜"]):
            topics.append({"topic_type": "wait_time", "topic_name": "等待时间过长", "keyword": "等位"})

        # 性价比
        if any(kw in content for kw in ["性价比", "值", "划算", "贵", "不值", "坑"]):
            is_good = any(w in content for w in ["划算", "值", "性价比高"])
            topics.append({
                "topic_type": "value_for_money",
                "topic_name": "性价比好" if is_good else "性价比差",
            })

        # 是否可执行
        is_actionable = rating <= 2 or any(t["topic_type"] in ("negative", "hygiene", "wait_time") for t in topics)

        return ReviewAnalysis(
            review_id=uuid.uuid4().hex[:12],
            store_id=store_id,
            rating=rating,
            content=content,
            sentiment=sentiment,
            topics=topics,
            dishes_mentioned=dishes_mentioned,
            is_actionable=is_actionable,
            analyzed_at=datetime.now(timezone.utc).isoformat(),
        )

    def _update_aggregate(self, topic_type: str, topic_name: str,
                          sentiment: float, store_id: str, content: str) -> None:
        """更新主题聚合"""
        key = f"{topic_type}:{topic_name}"
        if key not in self._topic_aggregates:
            self._topic_aggregates[key] = TopicAggregate(
                topic_type=topic_type,
                topic_name=topic_name,
            )
        agg = self._topic_aggregates[key]
        old_total = agg.mention_count * agg.avg_sentiment
        agg.mention_count += 1
        agg.avg_sentiment = round((old_total + sentiment) / agg.mention_count, 2)
        if store_id and store_id not in agg.store_ids:
            agg.store_ids.append(store_id)
        if len(agg.sample_reviews) < 3:
            agg.sample_reviews.append(content[:60])

    # ─── 主题摘要 ───

    def get_topic_summary(
        self,
        store_id: Optional[str] = None,
        topic_type: Optional[str] = None,
        days: int = 30,
    ) -> dict:
        """获取主题摘要"""
        filtered: list[TopicAggregate] = []
        for agg in self._topic_aggregates.values():
            if topic_type and agg.topic_type != topic_type:
                continue
            if store_id and store_id not in agg.store_ids:
                continue
            filtered.append(agg)

        filtered.sort(key=lambda x: x.mention_count, reverse=True)

        return {
            "store_id": store_id or "全部门店",
            "topic_type": topic_type or "全部类型",
            "period_days": days,
            "total_topics": len(filtered),
            "topics": [
                {
                    "topic_type": a.topic_type,
                    "topic_type_cn": TOPIC_TYPES.get(a.topic_type, a.topic_type),
                    "topic_name": a.topic_name,
                    "mention_count": a.mention_count,
                    "avg_sentiment": a.avg_sentiment,
                    "store_count": len(a.store_ids),
                    "sample_reviews": a.sample_reviews,
                }
                for a in filtered[:20]
            ],
        }

    # ─── 菜品提及 ───

    def get_dish_mentions(
        self, store_id: Optional[str] = None, days: int = 30
    ) -> list[dict]:
        """获取菜品提及排行"""
        dish_data: dict[str, dict] = {}
        for analysis in self._analyses:
            if store_id and analysis.store_id != store_id:
                continue
            for dish in analysis.dishes_mentioned:
                if dish not in dish_data:
                    dish_data[dish] = {
                        "dish_name": dish,
                        "total_mentions": 0,
                        "positive_mentions": 0,
                        "negative_mentions": 0,
                        "avg_rating": 0.0,
                        "ratings_sum": 0,
                    }
                dish_data[dish]["total_mentions"] += 1
                dish_data[dish]["ratings_sum"] += analysis.rating
                if analysis.sentiment > 0.2:
                    dish_data[dish]["positive_mentions"] += 1
                elif analysis.sentiment < -0.2:
                    dish_data[dish]["negative_mentions"] += 1

        results = []
        for d in dish_data.values():
            d["avg_rating"] = round(d["ratings_sum"] / d["total_mentions"], 1) if d["total_mentions"] > 0 else 0
            d["positive_rate"] = round(d["positive_mentions"] / d["total_mentions"] * 100, 1) if d["total_mentions"] > 0 else 0
            del d["ratings_sum"]
            results.append(d)

        results.sort(key=lambda x: x["total_mentions"], reverse=True)
        return results

    # ─── 门店口碑对比 ───

    def compare_stores_reputation(self, store_ids: list[str]) -> dict:
        """门店间口碑对比"""
        store_data: dict[str, dict] = {}
        for sid in store_ids:
            analyses = [a for a in self._analyses if a.store_id == sid]
            if not analyses:
                store_data[sid] = {"review_count": 0, "avg_sentiment": 0, "avg_rating": 0,
                                   "top_positive": [], "top_negative": []}
                continue

            avg_sent = sum(a.sentiment for a in analyses) / len(analyses)
            avg_rating = sum(a.rating for a in analyses) / len(analyses)

            pos_topics: Counter = Counter()
            neg_topics: Counter = Counter()
            for a in analyses:
                for t in a.topics:
                    if t["topic_type"] == "positive":
                        pos_topics[t["topic_name"]] += 1
                    elif t["topic_type"] == "negative":
                        neg_topics[t["topic_name"]] += 1

            store_data[sid] = {
                "review_count": len(analyses),
                "avg_sentiment": round(avg_sent, 2),
                "avg_rating": round(avg_rating, 1),
                "top_positive": [{"topic": t, "count": c} for t, c in pos_topics.most_common(3)],
                "top_negative": [{"topic": t, "count": c} for t, c in neg_topics.most_common(3)],
            }

        return {
            "stores_compared": store_ids,
            "comparison": store_data,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # ─── 可执行问题 ───

    def get_actionable_issues(self, store_id: Optional[str] = None) -> list[dict]:
        """获取需要解决的问题（反复出现的差评主题）"""
        issues: list[dict] = []
        for key, agg in self._topic_aggregates.items():
            if agg.topic_type not in ("negative", "hygiene", "wait_time"):
                continue
            if agg.avg_sentiment > -0.1:
                continue
            if store_id and store_id not in agg.store_ids:
                continue
            if agg.mention_count < 1:
                continue

            severity = "high" if agg.mention_count >= 3 else ("medium" if agg.mention_count >= 2 else "low")

            issues.append({
                "topic_type": agg.topic_type,
                "topic_type_cn": TOPIC_TYPES.get(agg.topic_type, agg.topic_type),
                "topic_name": agg.topic_name,
                "mention_count": agg.mention_count,
                "avg_sentiment": agg.avg_sentiment,
                "severity": severity,
                "affected_stores": agg.store_ids,
                "sample_reviews": agg.sample_reviews,
                "suggested_action": self._suggest_action(agg),
            })

        issues.sort(key=lambda x: {"high": 0, "medium": 1, "low": 2}[x["severity"]])
        return issues

    def _suggest_action(self, agg: TopicAggregate) -> str:
        """根据问题主题生成建议"""
        action_map = {
            "太咸": "与厨师长沟通调味标准，增加试味环节",
            "太辣": "增加辣度等级选项（不辣/微辣/中辣/特辣），菜单标注辣度",
            "太油": "调整烹饪用油量，推出清爽系列",
            "分量少": "核查出品标准克数，确保与菜单描述一致",
            "服务差": "加强服务培训，建立服务评分机制",
            "态度差": "开展服务态度培训，设置顾客满意度KPI",
            "脏": "加强卫生检查频次，制定清洁SOP",
            "不干净": "加强餐具消毒和台面清洁，增加巡检频次",
            "头发": "严格执行厨房帽子佩戴规范，加强后厨管理",
            "异物": "加强出品检查流程，设置上菜前最终检验",
            "等待时间过长": "优化出品流程，增加高峰时段人手",
            "卫生问题": "全面卫生大检查，加强日常巡检",
            "慢": "优化出品动线，预估高峰时段备菜量",
            "贵": "评估定价策略，优化套餐组合提升感知价值",
            "不值": "提升菜品品质和服务体验，改善性价比感知",
        }
        return action_map.get(agg.topic_name, f"针对'{agg.topic_name}'问题制定专项整改方案")

    # ─── 营销亮点 ───

    def get_marketing_highlights(self, store_id: Optional[str] = None) -> list[dict]:
        """获取适合营销宣传的好评主题"""
        highlights: list[dict] = []
        for key, agg in self._topic_aggregates.items():
            if agg.topic_type not in ("positive", "dish_mention"):
                continue
            if agg.avg_sentiment < 0.3:
                continue
            if store_id and store_id not in agg.store_ids:
                continue

            highlights.append({
                "topic_type": agg.topic_type,
                "topic_name": agg.topic_name,
                "mention_count": agg.mention_count,
                "avg_sentiment": agg.avg_sentiment,
                "marketing_angle": self._marketing_angle(agg),
                "sample_reviews": agg.sample_reviews,
            })

        highlights.sort(key=lambda x: x["mention_count"], reverse=True)
        return highlights

    def _marketing_angle(self, agg: TopicAggregate) -> str:
        """生成营销角度建议"""
        angles = {
            "好吃": "口碑传播：顾客真实好评",
            "正宗": "品牌定位：正宗湘菜",
            "地道": "品牌定位：地道风味",
            "推荐": "口碑传播：顾客主动推荐",
            "回头客": "复购率高：回头客认可",
            "新鲜": "食材品质：新鲜保证",
            "服务好": "服务体验：贴心服务",
            "干净": "环境卫生：放心就餐",
            "环境好": "就餐环境：舒适氛围",
            "划算": "性价比：超值体验",
        }
        if agg.topic_type == "dish_mention":
            return f"招牌推荐：{agg.topic_name}好评如潮"
        return angles.get(agg.topic_name, f"亮点：{agg.topic_name}")

    # ─── 主题趋势追踪 ───

    def track_topic_trend(self, topic_name: str, days: int = 90) -> list[dict]:
        """追踪特定主题的趋势变化"""
        # 模拟按周聚合
        weeks = days // 7
        trend_data: list[dict] = []
        now = datetime.now(timezone.utc)

        # 统计该主题的总提及次数
        total_mentions = 0
        for agg in self._topic_aggregates.values():
            if agg.topic_name == topic_name:
                total_mentions = agg.mention_count
                break

        # 模拟趋势数据
        base = max(1, total_mentions // max(1, weeks))
        for w in range(weeks, 0, -1):
            week_start = now - timedelta(weeks=w)
            # 模拟递增趋势
            count = max(0, base + (weeks - w))
            trend_data.append({
                "week_start": week_start.strftime("%Y-%m-%d"),
                "mention_count": count,
                "sentiment_avg": round(0.3 + (weeks - w) * 0.02, 2),
            })

        return trend_data
