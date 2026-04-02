"""消费需求洞察引擎 — 从零散反馈变成结构化主题

信号来源：评价、反馈、搜索趋势、社交媒体、预订备注、员工上报。
"""
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import structlog

logger = structlog.get_logger()


# ─── 常量 ───

INSIGHT_CATEGORIES = {
    "scenario": "场景需求",
    "health": "健康需求",
    "flavor": "口味变化",
    "price": "价格敏感",
    "service": "服务体验",
    "convenience": "便利需求",
    "festival": "节日需求",
}

SOURCE_TYPES = [
    "review", "feedback", "search_trend", "social_media",
    "reservation_note", "staff_report",
]

# ─── 关键词 → 主题映射（模拟 NLP） ───

_KEYWORD_TOPIC_MAP: dict[str, tuple[str, str]] = {
    # (category, topic_name)
    "家庭": ("scenario", "家庭聚餐"),
    "小孩": ("scenario", "亲子用餐"),
    "儿童": ("scenario", "亲子用餐"),
    "宝宝椅": ("scenario", "亲子用餐"),
    "商务": ("scenario", "商务宴请"),
    "请客": ("scenario", "商务宴请"),
    "朋友": ("scenario", "朋友聚会"),
    "闺蜜": ("scenario", "朋友聚会"),
    "同学": ("scenario", "朋友聚会"),
    "一个人": ("scenario", "单人用餐"),
    "独食": ("scenario", "单人用餐"),
    "减脂": ("health", "减脂餐需求"),
    "低糖": ("health", "低糖饮食"),
    "低盐": ("health", "低盐饮食"),
    "有机": ("health", "有机食材"),
    "健康": ("health", "健康饮食"),
    "养生": ("health", "养生需求"),
    "辣": ("flavor", "辣度偏好"),
    "不辣": ("flavor", "不辣需求"),
    "微辣": ("flavor", "微辣偏好"),
    "清淡": ("flavor", "清淡口味"),
    "酸汤": ("flavor", "酸汤热潮"),
    "融合": ("flavor", "融合菜创新"),
    "性价比": ("price", "性价比诉求"),
    "太贵": ("price", "价格偏高感知"),
    "便宜": ("price", "低价需求"),
    "套餐": ("price", "套餐需求"),
    "优惠": ("price", "优惠敏感"),
    "团购": ("price", "团购需求"),
    "服务态度": ("service", "服务态度"),
    "服务好": ("service", "服务好评"),
    "服务差": ("service", "服务投诉"),
    "等位": ("service", "等位体验"),
    "排队": ("service", "排队时间"),
    "环境": ("service", "就餐环境"),
    "外卖": ("convenience", "外卖需求"),
    "打包": ("convenience", "打包需求"),
    "预订": ("convenience", "预订需求"),
    "停车": ("convenience", "停车便利"),
    "春节": ("festival", "春节聚餐"),
    "年夜饭": ("festival", "年夜饭需求"),
    "中秋": ("festival", "中秋团圆"),
    "情人节": ("festival", "情人节浪漫"),
    "母亲节": ("festival", "母亲节感恩"),
    "生日": ("festival", "生日宴"),
}


# ─── 数据模型 ───

@dataclass
class Signal:
    """消费信号"""
    signal_id: str
    source_type: str
    content: str
    city: str
    store_id: str
    topics: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    sentiment: float = 0.0  # -1 to 1
    ingested_at: str = ""


@dataclass
class InsightTopic:
    """洞察主题"""
    topic_id: str
    category: str
    topic_name: str
    signal_count: int = 0
    trend_direction: str = "stable"  # rising/stable/declining
    trend_score: float = 0.0
    cities: list[str] = field(default_factory=list)
    first_seen: str = ""
    last_seen: str = ""
    sample_signals: list[str] = field(default_factory=list)


# ─── 种子信号 ───

_SEED_SIGNALS: list[dict] = [
    {"source_type": "review", "content": "带小孩来吃，希望有儿童套餐，等位太久了", "city": "长沙", "store_id": "S001"},
    {"source_type": "review", "content": "辣椒炒肉很好吃但太辣了，希望有微辣选项", "city": "长沙", "store_id": "S001"},
    {"source_type": "review", "content": "朋友聚会很开心，环境不错，性价比高", "city": "深圳", "store_id": "S005"},
    {"source_type": "feedback", "content": "能不能出减脂餐套餐？现在很多人都在控制饮食", "city": "深圳", "store_id": "S005"},
    {"source_type": "search_trend", "content": "酸汤火锅搜索量本周环比增长35%", "city": "全国", "store_id": ""},
    {"source_type": "social_media", "content": "小红书上低糖湘菜的笔记增长200%，年轻女性关注", "city": "全国", "store_id": ""},
    {"source_type": "reservation_note", "content": "商务宴请8人，需要包间，预算人均150", "city": "广州", "store_id": "S010"},
    {"source_type": "staff_report", "content": "最近很多客人问有没有一人食套餐，尤其午市", "city": "长沙", "store_id": "S002"},
    {"source_type": "review", "content": "停车太难了，转了三圈才找到车位", "city": "深圳", "store_id": "S006"},
    {"source_type": "review", "content": "年夜饭套餐很丰盛，全家都满意，明年还来", "city": "长沙", "store_id": "S001"},
    {"source_type": "social_media", "content": "抖音上养生湘菜话题播放量破亿，枸杞煲汤系列火了", "city": "全国", "store_id": ""},
    {"source_type": "review", "content": "服务态度很好，但菜量有点少，性价比一般", "city": "广州", "store_id": "S010"},
    {"source_type": "feedback", "content": "外卖包装希望能改进，汤洒了一桌", "city": "武汉", "store_id": "S015"},
    {"source_type": "review", "content": "团购套餐品质下降了，和正价点的不一样", "city": "深圳", "store_id": "S005"},
    {"source_type": "search_trend", "content": "预制菜负面搜索增加，消费者对预制菜排斥情绪上升", "city": "全国", "store_id": ""},
    {"source_type": "staff_report", "content": "周末家庭客群明显增多，儿童椅不够用", "city": "长沙", "store_id": "S003"},
    {"source_type": "review", "content": "清淡口味选择太少，不是所有人都能吃辣", "city": "上海", "store_id": "S020"},
    {"source_type": "social_media", "content": "微博上生日宴打卡湘菜馆成为新趋势", "city": "全国", "store_id": ""},
    {"source_type": "review", "content": "排队等了40分钟，体验很差，建议增加预订功能", "city": "长沙", "store_id": "S001"},
    {"source_type": "feedback", "content": "希望有健康轻食系列，现在的菜偏油腻", "city": "深圳", "store_id": "S006"},
]


class ConsumerInsightService:
    """消费需求洞察引擎 — 从零散反馈变成结构化主题"""

    def __init__(self) -> None:
        self._signals: list[Signal] = []
        self._topics: dict[str, InsightTopic] = {}
        self._load_seed_data()

    def _load_seed_data(self) -> None:
        for seed in _SEED_SIGNALS:
            self.ingest_signal(
                source_type=seed["source_type"],
                content=seed["content"],
                city=seed.get("city", ""),
                store_id=seed.get("store_id", ""),
            )
        logger.info("consumer_insight_seed_loaded", signals=len(self._signals),
                     topics=len(self._topics))

    # ─── 信号摄入 ───

    def ingest_signal(
        self,
        source_type: str,
        content: str,
        city: Optional[str] = None,
        store_id: Optional[str] = None,
    ) -> dict:
        """摄入消费信号"""
        if source_type not in SOURCE_TYPES:
            raise ValueError(f"Invalid source_type: {source_type}, must be one of {SOURCE_TYPES}")

        signal_id = uuid.uuid4().hex[:12]
        topics_found, categories_found = self._extract_topics_from_content(content)
        sentiment = self._estimate_sentiment(content)

        signal = Signal(
            signal_id=signal_id,
            source_type=source_type,
            content=content,
            city=city or "",
            store_id=store_id or "",
            topics=topics_found,
            categories=categories_found,
            sentiment=sentiment,
            ingested_at=datetime.now(timezone.utc).isoformat(),
        )
        self._signals.append(signal)

        # 更新主题计数
        for i, topic_name in enumerate(topics_found):
            cat = categories_found[i] if i < len(categories_found) else "scenario"
            self._update_topic(cat, topic_name, signal)

        return {
            "signal_id": signal_id,
            "topics_extracted": topics_found,
            "categories": categories_found,
            "sentiment": sentiment,
            "status": "ingested",
        }

    def _extract_topics_from_content(self, content: str) -> tuple[list[str], list[str]]:
        """从内容中提取主题（模拟 NLP）"""
        topics: list[str] = []
        categories: list[str] = []
        for keyword, (cat, topic) in _KEYWORD_TOPIC_MAP.items():
            if keyword in content:
                if topic not in topics:
                    topics.append(topic)
                    categories.append(cat)
        return topics, categories

    def _estimate_sentiment(self, content: str) -> float:
        """简单情感评估（模拟）"""
        positive_words = ["好吃", "满意", "开心", "不错", "好", "丰盛", "喜欢", "推荐", "棒"]
        negative_words = ["差", "难", "慢", "贵", "少", "排斥", "太久", "洒", "下降", "投诉"]
        pos = sum(1 for w in positive_words if w in content)
        neg = sum(1 for w in negative_words if w in content)
        total = pos + neg
        if total == 0:
            return 0.0
        return round((pos - neg) / total, 2)

    def _update_topic(self, category: str, topic_name: str, signal: Signal) -> None:
        """更新或创建主题"""
        # 用 category+topic_name 作为唯一键
        topic_key = f"{category}:{topic_name}"
        existing = None
        for t in self._topics.values():
            if t.category == category and t.topic_name == topic_name:
                existing = t
                break

        if existing:
            existing.signal_count += 1
            existing.last_seen = signal.ingested_at
            if signal.city and signal.city not in existing.cities:
                existing.cities.append(signal.city)
            if len(existing.sample_signals) < 5:
                existing.sample_signals.append(signal.content[:80])
        else:
            tid = uuid.uuid4().hex[:12]
            self._topics[tid] = InsightTopic(
                topic_id=tid,
                category=category,
                topic_name=topic_name,
                signal_count=1,
                trend_direction="rising",
                trend_score=1.0,
                cities=[signal.city] if signal.city else [],
                first_seen=signal.ingested_at,
                last_seen=signal.ingested_at,
                sample_signals=[signal.content[:80]],
            )

    # ─── 主题提取 ───

    def extract_topics(self, signals: list[dict]) -> list[dict]:
        """从一批信号中提取主题"""
        all_topics: list[str] = []
        all_categories: list[str] = []
        for sig in signals:
            topics, cats = self._extract_topics_from_content(sig.get("content", ""))
            all_topics.extend(topics)
            all_categories.extend(cats)

        counter = Counter(all_topics)
        results = []
        for topic_name, count in counter.most_common():
            idx = all_topics.index(topic_name)
            cat = all_categories[idx] if idx < len(all_categories) else "scenario"
            results.append({
                "topic_name": topic_name,
                "category": cat,
                "category_cn": INSIGHT_CATEGORIES.get(cat, cat),
                "mention_count": count,
            })
        return results

    # ─── 趋势主题 ───

    def get_trending_topics(
        self,
        category: Optional[str] = None,
        city: Optional[str] = None,
        days: int = 30,
    ) -> list[dict]:
        """获取趋势主题"""
        results = []
        for t in self._topics.values():
            if category and t.category != category:
                continue
            if city and city not in t.cities:
                continue
            results.append({
                "topic_id": t.topic_id,
                "category": t.category,
                "category_cn": INSIGHT_CATEGORIES.get(t.category, t.category),
                "topic_name": t.topic_name,
                "signal_count": t.signal_count,
                "trend_direction": t.trend_direction,
                "trend_score": t.trend_score,
                "cities": t.cities,
            })
        results.sort(key=lambda x: x["signal_count"], reverse=True)
        return results

    def get_topic_detail(self, topic_id: str) -> dict:
        """获取主题详情"""
        t = self._topics.get(topic_id)
        if not t:
            raise KeyError(f"Topic not found: {topic_id}")
        return {
            "topic_id": t.topic_id,
            "category": t.category,
            "category_cn": INSIGHT_CATEGORIES.get(t.category, t.category),
            "topic_name": t.topic_name,
            "signal_count": t.signal_count,
            "trend_direction": t.trend_direction,
            "trend_score": t.trend_score,
            "cities": t.cities,
            "first_seen": t.first_seen,
            "last_seen": t.last_seen,
            "sample_signals": t.sample_signals,
        }

    # ─── 需求变化摘要 ───

    def get_demand_change_summary(self, period: str = "week") -> dict:
        """周度/月度需求变化摘要"""
        cat_counts: dict[str, int] = {}
        for t in self._topics.values():
            cn = INSIGHT_CATEGORIES.get(t.category, t.category)
            cat_counts[cn] = cat_counts.get(cn, 0) + t.signal_count

        total_signals = len(self._signals)
        top_topics = sorted(self._topics.values(), key=lambda x: x.signal_count, reverse=True)[:5]

        rising = [t for t in self._topics.values() if t.trend_direction == "rising"]
        rising_names = [t.topic_name for t in sorted(rising, key=lambda x: x.signal_count, reverse=True)[:3]]

        return {
            "period": period,
            "total_signals": total_signals,
            "total_topics": len(self._topics),
            "category_distribution": cat_counts,
            "top_topics": [
                {"topic_name": t.topic_name, "category": t.category, "signal_count": t.signal_count}
                for t in top_topics
            ],
            "rising_topics": rising_names,
            "summary": (
                f"本{('周' if period == 'week' else '月')}共收集{total_signals}条消费信号，"
                f"提取{len(self._topics)}个主题。"
                f"上升趋势：{'、'.join(rising_names) if rising_names else '无'}。"
            ),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # ─── 城市对比 ───

    def compare_cities(self, cities: list[str], metric: str = "signal_count") -> dict:
        """城市间消费需求对比"""
        city_data: dict[str, dict] = {c: {"total_signals": 0, "top_topics": Counter()} for c in cities}

        for sig in self._signals:
            if sig.city in city_data:
                city_data[sig.city]["total_signals"] += 1
                for topic in sig.topics:
                    city_data[sig.city]["top_topics"][topic] += 1

        comparison = {}
        for c in cities:
            top3 = city_data[c]["top_topics"].most_common(3)
            comparison[c] = {
                "total_signals": city_data[c]["total_signals"],
                "top_topics": [{"topic": t, "count": cnt} for t, cnt in top3],
            }

        return {
            "cities_compared": cities,
            "metric": metric,
            "comparison": comparison,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # ─── 新兴需求检测 ───

    def detect_emerging_needs(self) -> list[dict]:
        """自动检测新兴或快速增长的消费需求"""
        emerging: list[dict] = []
        for t in self._topics.values():
            if t.trend_direction == "rising" and t.signal_count >= 2:
                emerging.append({
                    "topic_id": t.topic_id,
                    "topic_name": t.topic_name,
                    "category": t.category,
                    "category_cn": INSIGHT_CATEGORIES.get(t.category, t.category),
                    "signal_count": t.signal_count,
                    "cities": t.cities,
                    "recommendation": self._generate_recommendation(t),
                })

        emerging.sort(key=lambda x: x["signal_count"], reverse=True)
        return emerging

    def _generate_recommendation(self, topic: InsightTopic) -> str:
        """根据主题生成建议"""
        recs = {
            "亲子用餐": "建议增加儿童套餐、儿童椅配置，周末推出亲子活动",
            "减脂餐需求": "建议开发低卡湘菜系列，标注热量信息",
            "低糖饮食": "建议饮品线增加无糖/低糖选项",
            "不辣需求": "建议菜单标注辣度等级，增加不辣/微辣菜品",
            "单人用餐": "建议推出午市一人食套餐，优化单人用餐体验",
            "性价比诉求": "建议优化套餐组合，提升感知价值",
            "商务宴请": "建议完善包间服务，推出商务宴请套餐",
            "酸汤热潮": "建议研发酸汤系列菜品，跟上市场热点",
            "养生需求": "建议开发养生汤品系列，突出食材功效",
            "等位体验": "建议优化排号系统，增加等位小食/游戏",
            "外卖需求": "建议改进外卖包装，优化外卖专用菜品",
            "停车便利": "建议增加停车指引，与周边停车场合作",
        }
        return recs.get(topic.topic_name, f"建议关注{topic.topic_name}趋势，评估是否需要产品/服务调整")
