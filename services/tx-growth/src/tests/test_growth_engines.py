"""增长中枢 — 全引擎测试

覆盖：
- 品牌策略 CRUD + 内容校验
- 客户分群创建 + 用户分类 + 统计
- 旅程编排生命周期 (create → publish → execute → stats)
- 内容生成（10种类型）
- 优惠创建 + 资格判断 + 毛利合规
- 渠道发送 + 频率限制
- ROI 归因（5种模型）
- 端到端：分群 → 旅程 → 发送 → 转化 → ROI
"""
import os
import sys

# 确保可以从 src 目录导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from services.audience_segmentation import (
    AudienceSegmentationService,
    add_users_to_segment,
    clear_all_segments,
)
from services.brand_strategy import BrandStrategyService, _brand_strategies
from services.channel_engine import (
    ChannelEngine,
)
from services.content_engine import (
    ContentEngine,
)
from services.journey_orchestrator import (
    JourneyOrchestratorService,
    clear_all_journeys,
)
from services.offer_engine import (
    OfferEngine,
)

# ---------------------------------------------------------------------------
# v144 DB化兼容存根 — 仅供此测试文件的内存测试使用
# 生产代码已移至 async DB；以下存根维持旧测试的同步行为
# ---------------------------------------------------------------------------

# 内存存储（仅测试用）
_test_offers: dict = {}
_test_offer_redemptions: dict = {}
_test_send_logs: list = []
_test_daily_counts: dict = {}
_test_templates: dict = {}
_test_content_perf: dict = {}
_test_channel_configs: dict = {}


def clear_all_offers() -> None:
    _test_offers.clear()
    _test_offer_redemptions.clear()


def record_redemption(offer_id: str, user_id: str, order_total_fen: int, discount_fen: int) -> None:
    if offer_id not in _test_offer_redemptions:
        _test_offer_redemptions[offer_id] = []
    _test_offer_redemptions[offer_id].append({
        "user_id": user_id, "order_total_fen": order_total_fen,
        "discount_fen": discount_fen,
    })
    if offer_id in _test_offers:
        _test_offers[offer_id]["stats"]["redeemed_count"] += 1
        _test_offers[offer_id]["stats"]["total_discount_fen"] += discount_fen
        _test_offers[offer_id]["stats"]["total_revenue_fen"] = (
            _test_offers[offer_id]["stats"].get("total_revenue_fen", 0) + order_total_fen
        )


def set_offer_issued_count(offer_id: str, count: int) -> None:
    if offer_id in _test_offers:
        _test_offers[offer_id]["stats"]["issued_count"] = count


def clear_all_content() -> None:
    _test_templates.clear()
    _test_content_perf.clear()


def record_content_performance(content_id: str, metrics: dict) -> None:
    _test_content_perf[content_id] = {"content_id": content_id, **metrics}


def clear_all_channel_data() -> None:
    _test_send_logs.clear()
    _test_daily_counts.clear()
    _test_channel_configs.clear()


from services.roi_attribution import (
    ROIAttributionService,
    clear_all_attribution_data,
    set_campaign_cost,
)


# ---------------------------------------------------------------------------
# 测试专用内存版 Engine（向后兼容旧的同步 API）
# v144 DB化后，生产 Engine 变为 async；这些内存版本仅供单元测试使用
# ---------------------------------------------------------------------------

import uuid as _uuid
from datetime import datetime as _dt, timezone as _tz


class _MemOfferEngine(OfferEngine):
    """内存版优惠引擎（单元测试用），兼容旧的同步 API"""

    def create_offer(self, name, offer_type, discount_rules, validity_days,
                     target_segments, stores, time_slots, margin_floor, **kw):
        if offer_type not in self.OFFER_TYPES:
            return {"error": f"不支持的优惠类型: {offer_type}"}
        oid = str(_uuid.uuid4())[:8]
        now = _dt.now(_tz.utc).isoformat()
        defaults = self._TYPE_DEFAULTS.get(offer_type, {})
        offer = {
            "offer_id": oid, "name": name, "offer_type": offer_type,
            "description": defaults.get("description", ""),
            "goal": defaults.get("goal", "general"),
            "discount_rules": discount_rules, "validity_days": validity_days,
            "target_segments": target_segments, "stores": stores,
            "time_slots": time_slots, "margin_floor": margin_floor,
            "max_per_user": kw.get("max_per_user", 1),
            "status": "active", "created_at": now, "updated_at": now,
            "stats": {"issued_count": 0, "redeemed_count": 0,
                      "total_discount_fen": 0, "total_revenue_fen": 0},
        }
        _test_offers[oid] = offer
        return offer

    def evaluate_offer_eligibility(self, user_id, offer_id):
        offer = _test_offers.get(offer_id)
        if not offer:
            return {"eligible": False, "reason": f"优惠不存在: {offer_id}"}
        if offer["status"] != "active":
            return {"eligible": False, "reason": f"优惠已{offer['status']}"}
        redemptions = _test_offer_redemptions.get(offer_id, [])
        user_count = sum(1 for r in redemptions if r.get("user_id") == user_id)
        if user_count >= offer.get("max_per_user", 1):
            return {"eligible": False, "reason": "已达使用上限"}
        return {"eligible": True, "offer_id": offer_id, "user_id": user_id,
                "discount_rules": offer["discount_rules"],
                "validity_days": offer["validity_days"]}

    def calculate_offer_cost(self, offer_id):
        offer = _test_offers.get(offer_id)
        if not offer:
            return {"error": f"优惠不存在: {offer_id}"}
        return super().calculate_offer_cost(offer["discount_rules"])

    def check_margin_compliance(self, offer_id, order_data):
        offer = _test_offers.get(offer_id)
        if not offer:
            return {"compliant": False, "reason": f"优惠不存在: {offer_id}"}
        return super().check_margin_compliance(offer["margin_floor"], order_data)

    def get_offer_analytics(self, offer_id):
        offer = _test_offers.get(offer_id)
        if not offer:
            return {"error": f"优惠不存在: {offer_id}"}
        redemptions = _test_offer_redemptions.get(offer_id, [])
        stats = offer.get("stats", {})
        issued = stats.get("issued_count", 0)
        redeemed = len(redemptions)
        total_discount_fen = sum(r.get("discount_fen", 0) for r in redemptions)
        total_revenue_fen = sum(r.get("order_total_fen", 0) for r in redemptions)
        return {
            "offer_id": offer_id, "offer_name": offer.get("name", ""),
            "offer_type": offer.get("offer_type", ""),
            "issued_count": issued, "redeemed_count": redeemed,
            "redemption_rate": round(redeemed / max(1, issued), 4),
            "total_discount_fen": total_discount_fen,
            "total_discount_yuan": round(total_discount_fen / 100, 2),
            "total_revenue_fen": total_revenue_fen,
            "total_revenue_yuan": round(total_revenue_fen / 100, 2),
            "revenue_per_redemption_fen": total_revenue_fen // max(1, redeemed),
            "profit_contribution_fen": total_revenue_fen - total_discount_fen,
            "profit_contribution_yuan": round((total_revenue_fen - total_discount_fen) / 100, 2),
        }


class _MemContentEngine(ContentEngine):
    """内存版内容引擎（单元测试用），兼容旧的同步 list_templates/create_template API"""

    def list_templates(self, content_type=None):
        # 调用父类的纯计算 list（不需要 db）
        items = list(_test_templates.values())
        if content_type:
            items = [t for t in items if t.get("content_type") == content_type]
        return items

    def create_template(self, name, content_type, body_template, variables, **kw):
        tid = str(_uuid.uuid4())[:8]
        now = _dt.now(_tz.utc).isoformat()
        tpl = {
            "template_id": tid, "name": name, "content_type": content_type,
            "body_template": body_template, "variables": variables,
            "is_builtin": False, "created_at": now,
        }
        _test_templates[tid] = tpl
        return tpl

    def get_content_performance(self, content_id):
        perf = _test_content_perf.get(content_id)
        if perf:
            return perf
        return {
            "content_id": content_id, "send_count": 0,
            "open_count": 0, "click_count": 0, "conversion_count": 0,
            "open_rate": 0.0, "click_rate": 0.0, "conversion_rate": 0.0,
        }


class _MemChannelEngine(ChannelEngine):
    """内存版渠道引擎（单元测试用），兼容旧的同步 API"""

    def send_message(self, channel, user_id, content, offer_id=None, **kw):
        if channel not in self.CHANNELS:
            return {"success": False, "error": f"不支持的渠道: {channel}"}
        max_daily = _test_channel_configs.get(channel, {}).get(
            "max_daily", self.CHANNELS[channel]["max_daily"]
        )
        sent = _test_daily_counts.get(user_id, {}).get(channel, 0)
        if sent >= max_daily:
            return {"success": False, "error": f"频率限制：今日已发送 {sent} 次，上限 {max_daily} 次",
                    "channel": channel, "user_id": user_id}
        mid = str(_uuid.uuid4())[:8]
        now = _dt.now(_tz.utc).isoformat()
        _test_send_logs.append({
            "message_id": mid, "channel": channel, "user_id": user_id,
            "content": content[:200], "offer_id": offer_id,
            "status": "sent", "sent_at": now,
        })
        _test_daily_counts.setdefault(user_id, {})[channel] = sent + 1
        return {"success": True, "message_id": mid, "channel": channel,
                "user_id": user_id, "sent_at": now}

    def check_frequency_limit(self, user_id, channel):
        if channel not in self.CHANNELS:
            return {"allowed": False, "reason": f"不支持的渠道: {channel}",
                    "current_count": 0, "max_daily": 0}
        max_daily = _test_channel_configs.get(channel, {}).get(
            "max_daily", self.CHANNELS[channel]["max_daily"]
        )
        current = _test_daily_counts.get(user_id, {}).get(channel, 0)
        allowed = current < max_daily
        return {
            "allowed": allowed, "current_count": current, "max_daily": max_daily,
            "channel": channel, "channel_name": self.CHANNELS[channel]["name"],
            "reason": "" if allowed else f"今日已发送 {current} 次，上限 {max_daily} 次",
        }

    def get_channel_stats(self, channel, date_range):
        if channel not in self.CHANNELS:
            return {"error": f"不支持的渠道: {channel}"}
        logs = [l for l in _test_send_logs if l["channel"] == channel]
        total = len(logs)
        unique = len(set(l["user_id"] for l in logs))
        with_offer = sum(1 for l in logs if l.get("offer_id"))
        return {
            "channel": channel, "channel_name": self.CHANNELS[channel]["name"],
            "date_range": date_range, "total_sent": total,
            "unique_users": unique, "with_offer_count": with_offer,
            "avg_per_user": round(total / max(1, unique), 2),
        }

    def configure_channel(self, channel, settings):
        if channel not in self.CHANNELS:
            return {"error": f"不支持的渠道: {channel}"}
        cfg = _test_channel_configs.get(channel, {})
        cfg.update(settings)
        cfg["channel"] = channel
        if "max_daily" in settings:
            self.CHANNELS[channel]["max_daily"] = settings["max_daily"]
        _test_channel_configs[channel] = cfg
        return cfg

    def get_send_log(self, user_id=None, channel=None, date_range=None):
        logs = list(_test_send_logs)
        if user_id:
            logs = [l for l in logs if l.get("user_id") == user_id]
        if channel:
            logs = [l for l in logs if l.get("channel") == channel]
        return logs


# ===========================================================================
# Fixtures — 真实中餐连锁数据
# ===========================================================================

@pytest.fixture(autouse=True)
def clean_state():
    """每个测试前清空全局状态"""
    _brand_strategies.clear()
    clear_all_segments()
    clear_all_journeys()
    clear_all_content()
    clear_all_offers()
    clear_all_channel_data()
    clear_all_attribution_data()
    yield


@pytest.fixture
def brand_svc():
    return BrandStrategyService()


@pytest.fixture
def segment_svc():
    return AudienceSegmentationService()


@pytest.fixture
def journey_svc():
    return JourneyOrchestratorService()


@pytest.fixture
def content_svc():
    return _MemContentEngine()


@pytest.fixture
def offer_svc():
    return _MemOfferEngine()


@pytest.fixture
def channel_svc():
    return _MemChannelEngine()


@pytest.fixture
def roi_svc():
    return ROIAttributionService()


@pytest.fixture
def sample_brand(brand_svc):
    """创建尝在一起品牌策略"""
    return brand_svc.create_brand_strategy(
        brand_id="changzaiyiqi",
        positioning="社区家庭中餐领导者",
        tone="温暖、亲切、有品质感",
        target_audience=["家庭聚餐", "朋友小聚", "商务简餐"],
        price_range={"min_fen": 5000, "max_fen": 15000, "avg_fen": 8800},
        signature_dishes=[
            {"name": "剁椒鱼头", "price_fen": 12800, "story": "洞庭湖鲜活鳙鱼，自制剁椒"},
            {"name": "小炒黄牛肉", "price_fen": 6800, "story": "湘西放养黄牛，现切现炒"},
            {"name": "农家一碗香", "price_fen": 3800, "story": "奶奶辈传下来的味道"},
        ],
        seasonal_plans=[
            {"season": "spring", "theme": "春笋尝鲜季", "dishes": ["春笋腊肉", "香椿炒蛋"],
             "start_date": "2026-03-01", "end_date": "2026-05-31", "marketing_focus": "时令新鲜"},
            {"season": "summer", "theme": "清凉一夏", "dishes": ["凉拌莴笋", "冰镇绿豆汤"],
             "start_date": "2026-06-01", "end_date": "2026-08-31", "marketing_focus": "消暑开胃"},
        ],
        promo_boundaries={"max_discount_pct": 30, "margin_floor_pct": 45},
        forbidden_expressions=["最低价", "全网最便宜", "免费送", "跳楼价", "清仓"],
    )


@pytest.fixture
def sample_users():
    """真实中餐场景用户数据"""
    return [
        {
            "user_id": "u001", "name": "张大姐",
            "first_order_days": 5, "recency_days": 2, "order_count": 1,
            "avg_order_fen": 8800, "total_spent_fen": 8800,
            "monthly_frequency": 1, "avg_party_size": 4,
            "weekend_ratio": 1.0, "coupon_usage_rate": 0.0,
            "health_dish_ratio": 0.2, "festival_order_ratio": 0.0,
            "has_stored_value": False, "stored_value_balance_fen": 0,
        },
        {
            "user_id": "u002", "name": "李总",
            "first_order_days": 180, "recency_days": 3, "order_count": 24,
            "avg_order_fen": 52000, "total_spent_fen": 1248000,
            "monthly_frequency": 4, "avg_party_size": 8,
            "weekend_ratio": 0.4, "coupon_usage_rate": 0.1,
            "health_dish_ratio": 0.1, "festival_order_ratio": 0.3,
            "has_stored_value": True, "stored_value_balance_fen": 200000,
        },
        {
            "user_id": "u003", "name": "小王",
            "first_order_days": 90, "recency_days": 75, "order_count": 3,
            "avg_order_fen": 6500, "total_spent_fen": 19500,
            "monthly_frequency": 0.5, "avg_party_size": 2,
            "weekend_ratio": 0.3, "coupon_usage_rate": 0.8,
            "health_dish_ratio": 0.5, "festival_order_ratio": 0.0,
            "has_stored_value": False, "stored_value_balance_fen": 0,
        },
        {
            "user_id": "u004", "name": "王阿姨",
            "first_order_days": 365, "recency_days": 5, "order_count": 48,
            "avg_order_fen": 7200, "total_spent_fen": 345600,
            "monthly_frequency": 5, "avg_party_size": 3,
            "weekend_ratio": 0.7, "coupon_usage_rate": 0.3,
            "health_dish_ratio": 0.4, "festival_order_ratio": 0.2,
            "has_stored_value": True, "stored_value_balance_fen": 50000,
        },
        {
            "user_id": "u005", "name": "刘先生",
            "first_order_days": 20, "recency_days": 18, "order_count": 1,
            "avg_order_fen": 16000, "total_spent_fen": 16000,
            "monthly_frequency": 0, "avg_party_size": 2,
            "weekend_ratio": 0.5, "coupon_usage_rate": 0.0,
            "health_dish_ratio": 0.1, "festival_order_ratio": 0.0,
            "has_stored_value": False, "stored_value_balance_fen": 0,
        },
    ]


# ===========================================================================
# 1. 品牌策略引擎测试
# ===========================================================================

class TestBrandStrategy:

    def test_create_brand_strategy(self, brand_svc):
        result = brand_svc.create_brand_strategy(
            brand_id="zuiqianxian",
            positioning="贵州酸汤鱼专门店",
            tone="热情、地道、原生态",
            target_audience=["年轻白领", "美食爱好者"],
            price_range={"min_fen": 6000, "max_fen": 20000, "avg_fen": 10000},
            signature_dishes=[
                {"name": "酸汤鱼", "price_fen": 16800, "story": "凯里红酸汤"},
            ],
            seasonal_plans=[],
            promo_boundaries={"max_discount_pct": 25, "margin_floor_pct": 50},
            forbidden_expressions=["便宜", "低价"],
        )
        assert result["brand_id"] == "zuiqianxian"
        assert result["positioning"] == "贵州酸汤鱼专门店"
        assert len(result["signature_dishes"]) == 1

    def test_get_brand_strategy(self, brand_svc, sample_brand):
        result = brand_svc.get_brand_strategy("changzaiyiqi")
        assert result["positioning"] == "社区家庭中餐领导者"
        assert len(result["signature_dishes"]) == 3

    def test_get_nonexistent_brand(self, brand_svc):
        result = brand_svc.get_brand_strategy("nonexistent")
        assert "error" in result

    def test_update_brand_strategy(self, brand_svc, sample_brand):
        result = brand_svc.update_brand_strategy("changzaiyiqi", {
            "tone": "温暖、亲切、高品质",
            "forbidden_expressions": ["最低价", "全网最便宜", "免费送", "跳楼价", "清仓", "甩卖"],
        })
        assert result["tone"] == "温暖、亲切、高品质"
        assert "甩卖" in result["forbidden_expressions"]

    def test_create_city_strategy(self, brand_svc, sample_brand):
        result = brand_svc.create_city_strategy(
            brand_id="changzaiyiqi",
            city="长沙",
            district_strategies=[
                {"district": "岳麓区", "competitor_density": "high",
                 "price_adjustment_pct": -5, "focus_segments": ["高校学生", "家庭"]},
                {"district": "芙蓉区", "competitor_density": "medium",
                 "price_adjustment_pct": 0, "focus_segments": ["商务白领"]},
            ],
        )
        assert result["city"] == "长沙"
        assert len(result["district_strategies"]) == 2

    def test_seasonal_calendar(self, brand_svc, sample_brand):
        calendar = brand_svc.get_seasonal_calendar("changzaiyiqi")
        assert len(calendar) == 2
        assert calendar[0]["season"] == "spring"
        assert "春笋腊肉" in calendar[0]["dishes"]

    def test_validate_content_clean(self, brand_svc, sample_brand):
        result = brand_svc.validate_content_against_brand(
            "changzaiyiqi",
            "周末带家人来尝尝我们的剁椒鱼头吧，温暖你的胃",
        )
        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_validate_content_forbidden(self, brand_svc, sample_brand):
        result = brand_svc.validate_content_against_brand(
            "changzaiyiqi",
            "全网最便宜！跳楼价清仓大甩卖！",
        )
        assert result["valid"] is False
        assert len(result["errors"]) >= 2

    def test_validate_content_tone_warning(self, brand_svc, sample_brand):
        result = brand_svc.validate_content_against_brand(
            "changzaiyiqi",
            "便宜到哭！低价甩卖进行中！",
        )
        assert len(result["warnings"]) > 0

    def test_strategy_card(self, brand_svc, sample_brand):
        card = brand_svc.generate_strategy_card("changzaiyiqi")
        assert card["brand_id"] == "changzaiyiqi"
        assert card["positioning"] == "社区家庭中餐领导者"
        assert "剁椒鱼头" in card["top_dishes"]
        assert card["max_discount_pct"] == 30
        assert card["margin_floor_pct"] == 45
        assert card["price_range_yuan"]["avg"] == 88.0


# ===========================================================================
# 2. 客户分群引擎测试
# ===========================================================================

class TestAudienceSegmentation:

    def test_system_segments_initialized(self, segment_svc):
        segments = segment_svc.list_segments()
        assert len(segments) >= 11
        names = {s["name"] for s in segments}
        assert "新客" in names
        assert "沉睡客" in names
        assert "高频复购客" in names

    def test_create_custom_segment(self, segment_svc):
        segment = segment_svc.create_segment(
            name="午市套餐常客",
            rules={
                "conditions": [
                    {"field": "weekday_lunch_ratio", "op": ">=", "value": 0.6},
                    {"field": "monthly_frequency", "op": ">=", "value": 6},
                ],
                "logic": "and",
            },
        )
        assert segment["name"] == "午市套餐常客"
        assert segment["segment_type"] == "custom"
        assert "segment_id" in segment

    def test_classify_new_customer(self, segment_svc, sample_users):
        """张大姐：首单5天，应属于 new_customer"""
        matched = segment_svc.classify_user(sample_users[0])
        assert "new_customer" in matched

    def test_classify_high_value_banquet(self, segment_svc, sample_users):
        """李总：客单价52000分，8人聚餐，应属于 high_value_banquet"""
        matched = segment_svc.classify_user(sample_users[1])
        assert "high_value_banquet" in matched

    def test_classify_dormant(self, segment_svc, sample_users):
        """小王：75天未消费，3次订单，应属于 dormant"""
        matched = segment_svc.classify_user(sample_users[2])
        assert "dormant" in matched

    def test_classify_high_frequency(self, segment_svc, sample_users):
        """王阿姨：月均5次，应属于 high_frequency"""
        matched = segment_svc.classify_user(sample_users[3])
        assert "high_frequency" in matched

    def test_classify_high_potential_new(self, segment_svc, sample_users):
        """刘先生：1次消费，客单价16000分，应属于 high_potential_new"""
        matched = segment_svc.classify_user(sample_users[4])
        assert "high_potential_new" in matched

    def test_classify_price_sensitive(self, segment_svc, sample_users):
        """小王：优惠券使用率80%，客单价6500分，应属于 price_sensitive"""
        matched = segment_svc.classify_user(sample_users[2])
        assert "price_sensitive" in matched

    def test_classify_family_dining(self, segment_svc, sample_users):
        """王阿姨：平均3人，周末70%，应属于 family_dining"""
        matched = segment_svc.classify_user(sample_users[3])
        assert "family_dining" in matched

    def test_classify_stored_value(self, segment_svc, sample_users):
        """李总：有储值，余额200000分，应属于 stored_value"""
        matched = segment_svc.classify_user(sample_users[1])
        assert "stored_value" in matched

    def test_segment_stats(self, segment_svc, sample_users):
        add_users_to_segment("high_frequency", [sample_users[3]])
        stats = segment_svc.compute_segment_stats("high_frequency")
        assert stats["count"] == 1
        assert stats["revenue_contribution_fen"] == 345600
        assert stats["repeat_probability"] == 1.0

    def test_segment_users_pagination(self, segment_svc, sample_users):
        add_users_to_segment("dormant", sample_users)
        page1 = segment_svc.get_segment_users("dormant", page=1, size=2)
        assert len(page1["items"]) == 2
        assert page1["total"] == 5
        page3 = segment_svc.get_segment_users("dormant", page=3, size=2)
        assert len(page3["items"]) == 1

    def test_ai_recommend_segments(self, segment_svc):
        recommendations = segment_svc.ai_recommend_segments("changzaiyiqi")
        assert len(recommendations) >= 3
        assert all("name" in r for r in recommendations)
        assert all("marketing_suggestion" in r for r in recommendations)

    def test_lifecycle_distribution(self, segment_svc, sample_users):
        add_users_to_segment("all", sample_users)
        dist = segment_svc.get_lifecycle_distribution()
        assert dist["total"] == 5
        stages = dist["stages"]
        # 张大姐(new) + 李总(loyal) + 小王(dormant) + 王阿姨(loyal) + 刘先生(active)
        assert stages["new"]["count"] >= 1


# ===========================================================================
# 3. 旅程编排引擎测试
# ===========================================================================

class TestJourneyOrchestrator:

    def _create_sample_journey(self, journey_svc):
        return journey_svc.create_journey(
            name="首单未复购48h召回",
            journey_type="retention",
            trigger={"type": "first_visit_no_repeat_48h", "params": {}},
            nodes=[
                {"node_id": "n1", "type": "send_content", "content_type": "wecom_chat",
                 "content_params": {"template": "retention"}, "next": "n2"},
                {"node_id": "n2", "type": "wait", "wait_hours": 24, "next": "n3"},
                {"node_id": "n3", "type": "condition",
                 "condition": {"type": "opened_content"},
                 "true_next": "n4", "false_next": "n5"},
                {"node_id": "n4", "type": "send_offer", "offer_type": "second_visit", "next": None},
                {"node_id": "n5", "type": "notify_staff", "staff_role": "store_manager", "next": None},
            ],
            target_segment_id="first_no_repeat",
        )

    def test_create_journey(self, journey_svc):
        journey = self._create_sample_journey(journey_svc)
        assert journey["name"] == "首单未复购48h召回"
        assert journey["status"] == "draft"
        assert len(journey["nodes"]) == 5

    def test_journey_lifecycle(self, journey_svc):
        """create → publish → pause → publish"""
        journey = self._create_sample_journey(journey_svc)
        jid = journey["journey_id"]

        # 发布
        published = journey_svc.publish_journey(jid)
        assert published["status"] == "published"

        # 暂停
        paused = journey_svc.pause_journey(jid)
        assert paused["status"] == "paused"

        # 重新发布
        republished = journey_svc.publish_journey(jid)
        assert republished["status"] == "published"

    def test_publish_empty_journey_fails(self, journey_svc):
        journey = journey_svc.create_journey(
            name="空旅程", journey_type="test",
            trigger={"type": "no_visit_7d", "params": {}},
            nodes=[], target_segment_id="dormant",
        )
        result = journey_svc.publish_journey(journey["journey_id"])
        assert "error" in result

    def test_update_draft_journey(self, journey_svc):
        journey = self._create_sample_journey(journey_svc)
        updated = journey_svc.update_journey(journey["journey_id"], {"name": "改名旅程"})
        assert updated["name"] == "改名旅程"

    def test_cannot_update_published(self, journey_svc):
        journey = self._create_sample_journey(journey_svc)
        journey_svc.publish_journey(journey["journey_id"])
        result = journey_svc.update_journey(journey["journey_id"], {"name": "不能改"})
        assert "error" in result

    def test_evaluate_triggers(self, journey_svc):
        # 首单未复购 48h
        assert journey_svc.evaluate_trigger(
            "first_visit_no_repeat_48h",
            {"order_count": 1, "recency_days": 3},
        ) is True

        # 7天未到店
        assert journey_svc.evaluate_trigger(
            "no_visit_7d",
            {"recency_days": 10},
        ) is True

        # 生日临近
        assert journey_svc.evaluate_trigger(
            "birthday_approaching",
            {"birthday_in_days": 3},
        ) is True

        # 不触发
        assert journey_svc.evaluate_trigger(
            "no_visit_30d",
            {"recency_days": 5},
        ) is False

    def test_execute_nodes(self, journey_svc):
        journey = self._create_sample_journey(journey_svc)
        jid = journey["journey_id"]
        journey_svc.publish_journey(jid)

        # 执行第一个节点（发送内容）
        r1 = journey_svc.execute_node(jid, "n1", "u001")
        assert r1["success"] is True
        assert r1["action"] == "content_sent"
        assert r1["next_node"] == "n2"

        # 执行等待节点
        r2 = journey_svc.execute_node(jid, "n2", "u001")
        assert r2["action"] == "waiting"
        assert r2["wait_hours"] == 24

        # 执行条件节点
        r3 = journey_svc.execute_node(jid, "n3", "u001")
        assert r3["action"] == "condition_evaluated"

    def test_execute_on_unpublished_fails(self, journey_svc):
        journey = self._create_sample_journey(journey_svc)
        result = journey_svc.execute_node(journey["journey_id"], "n1", "u001")
        assert "error" in result

    def test_journey_stats(self, journey_svc):
        journey = self._create_sample_journey(journey_svc)
        jid = journey["journey_id"]
        journey_svc.publish_journey(jid)

        journey_svc.execute_node(jid, "n1", "u001")
        journey_svc.execute_node(jid, "n1", "u002")
        journey_svc.execute_node(jid, "n4", "u001")  # offer_sent

        stats = journey_svc.get_journey_stats(jid)
        assert stats["executed_count"] == 3
        assert stats["unique_users_reached"] == 2
        assert stats["converted_count"] == 1

    def test_simulate_journey(self, journey_svc):
        journey = self._create_sample_journey(journey_svc)
        sim = journey_svc.simulate_journey(journey["journey_id"])
        assert sim["simulation"] is True
        assert sim["estimated_total_reach"] > 0
        assert len(sim["node_simulations"]) > 0

    def test_list_journeys_by_status(self, journey_svc):
        j1 = self._create_sample_journey(journey_svc)
        j2 = self._create_sample_journey(journey_svc)
        journey_svc.publish_journey(j1["journey_id"])

        drafts = journey_svc.list_journeys(status="draft")
        published = journey_svc.list_journeys(status="published")
        assert len(drafts) == 1
        assert len(published) == 1


# ===========================================================================
# 4. 内容引擎测试
# ===========================================================================

class TestContentEngine:

    def test_generate_all_content_types(self, content_svc):
        """测试10种内容类型全部能正确生成"""
        for ct in ContentEngine.CONTENT_TYPES:
            result = content_svc.generate_content(
                content_type=ct,
                brand_id="changzaiyiqi",
                target_segment="high_frequency",
                dish_name="剁椒鱼头",
                event_name="春笋尝鲜季",
            )
            assert "content_id" in result, f"类型 {ct} 生成失败"
            assert result["content_type"] == ct
            assert len(result["body"]) > 0
            assert len(result["title"]) > 0
            assert "call_to_action" in result

    def test_generate_wecom_chat(self, content_svc):
        result = content_svc.generate_content(
            content_type="wecom_chat",
            brand_id="changzaiyiqi",
            target_segment="dormant",
            dish_name="小炒黄牛肉",
        )
        assert "小炒黄牛肉" in result["body"]
        assert result["content_type"] == "wecom_chat"

    def test_generate_sms(self, content_svc):
        result = content_svc.generate_content(
            content_type="sms",
            brand_id="changzaiyiqi",
            target_segment="dormant",
        )
        assert "退订回T" in result["body"]

    def test_generate_dish_story(self, content_svc):
        result = content_svc.generate_content(
            content_type="dish_story",
            brand_id="changzaiyiqi",
            target_segment="all",
            dish_name="剁椒鱼头",
        )
        assert "剁椒鱼头" in result["body"]
        assert len(result["recommended_image_tags"]) > 0

    def test_invalid_content_type(self, content_svc):
        result = content_svc.generate_content(
            content_type="invalid_type",
            brand_id="changzaiyiqi",
            target_segment="all",
        )
        assert "error" in result

    def test_list_templates(self, content_svc):
        templates = content_svc.list_templates()
        assert len(templates) >= 5

        wecom_templates = content_svc.list_templates(content_type="wecom_chat")
        assert all(t["content_type"] == "wecom_chat" for t in wecom_templates)

    def test_create_custom_template(self, content_svc):
        tpl = content_svc.create_template(
            name="节日问候",
            content_type="sms",
            body_template="【{brand}】{name}，{holiday}快乐！到店享{offer}。退订回T",
            variables=["brand", "name", "holiday", "offer"],
        )
        assert tpl["name"] == "节日问候"
        assert tpl["is_builtin"] is False

    def test_validate_content_clean(self, content_svc):
        result = content_svc.validate_content(
            "changzaiyiqi",
            "欢迎来品尝我们的新菜品，主厨精心烹制",
        )
        assert result["valid"] is True

    def test_validate_content_forbidden_ad_words(self, content_svc):
        result = content_svc.validate_content(
            "changzaiyiqi",
            "我们是第一名的餐厅，保证最低价！100%满意！",
        )
        assert result["valid"] is False
        assert len(result["errors"]) >= 2

    def test_content_performance(self, content_svc):
        content = content_svc.generate_content(
            content_type="wecom_chat",
            brand_id="changzaiyiqi",
            target_segment="all",
        )
        cid = content["content_id"]

        # 初始无数据
        perf = content_svc.get_content_performance(cid)
        assert perf["send_count"] == 0

        # 记录效果数据
        record_content_performance(cid, {
            "send_count": 500, "open_count": 175, "click_count": 60, "conversion_count": 15,
            "open_rate": 0.35, "click_rate": 0.12, "conversion_rate": 0.03,
        })
        perf = content_svc.get_content_performance(cid)
        assert perf["send_count"] == 500
        assert perf["open_rate"] == 0.35


# ===========================================================================
# 5. 优惠引擎测试
# ===========================================================================

class TestOfferEngine:

    def _create_sample_offer(self, offer_svc):
        return offer_svc.create_offer(
            name="新客首单立减20",
            offer_type="new_customer_trial",
            discount_rules={"type": "fixed_amount", "amount_fen": 2000},
            validity_days=7,
            target_segments=["new_customer"],
            stores=["store_001", "store_002"],
            time_slots=[{"start": "11:00", "end": "21:00", "weekdays": [1, 2, 3, 4, 5, 6, 7]}],
            margin_floor=0.45,
        )

    def test_create_offer(self, offer_svc):
        offer = self._create_sample_offer(offer_svc)
        assert offer["name"] == "新客首单立减20"
        assert offer["offer_type"] == "new_customer_trial"
        assert offer["goal"] == "acquisition"
        assert offer["status"] == "active"

    def test_create_all_offer_types(self, offer_svc):
        for ot in OfferEngine.OFFER_TYPES:
            offer = offer_svc.create_offer(
                name=f"测试-{ot}",
                offer_type=ot,
                discount_rules={"type": "fixed_amount", "amount_fen": 1000},
                validity_days=7,
                target_segments=["all"],
                stores=[],
                time_slots=[],
                margin_floor=0.45,
            )
            assert offer["offer_type"] == ot

    def test_invalid_offer_type(self, offer_svc):
        result = offer_svc.create_offer(
            name="无效类型", offer_type="nonexistent",
            discount_rules={}, validity_days=7,
            target_segments=[], stores=[], time_slots=[], margin_floor=0.45,
        )
        assert "error" in result

    def test_eligibility_check(self, offer_svc):
        offer = self._create_sample_offer(offer_svc)
        oid = offer["offer_id"]

        # 首次：可用
        result = offer_svc.evaluate_offer_eligibility("u001", oid)
        assert result["eligible"] is True

        # 模拟已核销
        record_redemption(oid, "u001", 10000, 2000)

        # 再次检查：不可用（已达上限）
        result = offer_svc.evaluate_offer_eligibility("u001", oid)
        assert result["eligible"] is False

    def test_calculate_offer_cost(self, offer_svc):
        offer = self._create_sample_offer(offer_svc)
        cost = offer_svc.calculate_offer_cost(offer["offer_id"])
        assert cost["per_discount_fen"] == 2000
        assert cost["projected_cost_fen"] == 200000
        assert cost["projected_roi"] > 0

    def test_margin_compliance_pass(self, offer_svc):
        offer = self._create_sample_offer(offer_svc)
        result = offer_svc.check_margin_compliance(offer["offer_id"], {
            "total_fen": 15000, "cost_fen": 6000, "discount_fen": 2000,
        })
        # revenue_after = 13000, margin = (13000-6000)/13000 = 0.538 > 0.45
        assert result["compliant"] is True
        assert result["margin_rate"] > 0.45

    def test_margin_compliance_fail(self, offer_svc):
        offer = offer_svc.create_offer(
            name="大力度折扣", offer_type="second_visit",
            discount_rules={"type": "fixed_amount", "amount_fen": 5000},
            validity_days=7, target_segments=["dormant"],
            stores=[], time_slots=[], margin_floor=0.45,
        )
        result = offer_svc.check_margin_compliance(offer["offer_id"], {
            "total_fen": 10000, "cost_fen": 5000, "discount_fen": 5000,
        })
        # revenue_after = 5000, margin = (5000-5000)/5000 = 0.0 < 0.45
        assert result["compliant"] is False

    def test_offer_analytics(self, offer_svc):
        offer = self._create_sample_offer(offer_svc)
        oid = offer["offer_id"]
        set_offer_issued_count(oid, 200)

        record_redemption(oid, "u001", 12000, 2000)
        record_redemption(oid, "u002", 15000, 2000)
        record_redemption(oid, "u003", 9000, 2000)

        analytics = offer_svc.get_offer_analytics(oid)
        assert analytics["issued_count"] == 200
        assert analytics["redeemed_count"] == 3
        assert analytics["total_discount_fen"] == 6000
        assert analytics["total_revenue_fen"] == 36000
        assert analytics["profit_contribution_fen"] == 30000

    def test_recommend_offers_for_segments(self, offer_svc):
        for seg in ["new_customer", "dormant", "high_frequency", "high_value_banquet", "price_sensitive"]:
            recs = offer_svc.recommend_offer_for_segment(seg)
            assert len(recs) >= 1
            assert "offer_type" in recs[0]
            assert "expected_roi" in recs[0]

    def test_recommend_unknown_segment(self, offer_svc):
        recs = offer_svc.recommend_offer_for_segment("unknown_segment")
        assert len(recs) >= 1  # 返回通用推荐


# ===========================================================================
# 6. 渠道引擎测试
# ===========================================================================

class TestChannelEngine:

    def test_send_wecom(self, channel_svc):
        result = channel_svc.send_message(
            channel="wecom", user_id="u001",
            content="张大姐您好，上次您点的剁椒鱼头...",
        )
        assert result["success"] is True
        assert result["channel"] == "wecom"

    def test_send_sms(self, channel_svc):
        result = channel_svc.send_message(
            channel="sms", user_id="u001",
            content="【尝在一起】您有一张新优惠券待领取。退订回T",
        )
        assert result["success"] is True

    def test_send_with_offer(self, channel_svc):
        result = channel_svc.send_message(
            channel="miniapp", user_id="u001",
            content="新品上线", offer_id="offer_001",
        )
        assert result["success"] is True

    def test_invalid_channel(self, channel_svc):
        result = channel_svc.send_message(
            channel="telegram", user_id="u001", content="test",
        )
        assert result["success"] is False

    def test_frequency_limit(self, channel_svc):
        """短信每日上限2次"""
        r1 = channel_svc.send_message("sms", "u001", "消息1")
        r2 = channel_svc.send_message("sms", "u001", "消息2")
        r3 = channel_svc.send_message("sms", "u001", "消息3")

        assert r1["success"] is True
        assert r2["success"] is True
        assert r3["success"] is False
        assert "频率限制" in r3["error"]

    def test_frequency_limit_different_channels(self, channel_svc):
        """不同渠道频控独立"""
        channel_svc.send_message("sms", "u001", "短信1")
        channel_svc.send_message("sms", "u001", "短信2")

        # 短信已满，但企微还可以发
        result = channel_svc.send_message("wecom", "u001", "企微消息")
        assert result["success"] is True

    def test_frequency_check(self, channel_svc):
        check = channel_svc.check_frequency_limit("u001", "wecom")
        assert check["allowed"] is True
        assert check["max_daily"] == 3
        assert check["current_count"] == 0

    def test_channel_stats(self, channel_svc):
        channel_svc.send_message("wecom", "u001", "msg1")
        channel_svc.send_message("wecom", "u002", "msg2")
        channel_svc.send_message("wecom", "u001", "msg3")

        stats = channel_svc.get_channel_stats("wecom", {"start": "", "end": ""})
        assert stats["total_sent"] == 3
        assert stats["unique_users"] == 2

    def test_configure_channel(self, channel_svc):
        config = channel_svc.configure_channel("wecom", {"max_daily": 5, "enabled": True})
        assert config["max_daily"] == 5
        assert channel_svc.CHANNELS["wecom"]["max_daily"] == 5

    def test_send_log(self, channel_svc):
        channel_svc.send_message("wecom", "u001", "msg1")
        channel_svc.send_message("sms", "u001", "msg2")
        channel_svc.send_message("wecom", "u002", "msg3")

        # 按用户过滤
        logs = channel_svc.get_send_log(user_id="u001")
        assert len(logs) == 2

        # 按渠道过滤
        logs = channel_svc.get_send_log(channel="wecom")
        assert len(logs) == 2


# ===========================================================================
# 7. ROI归因引擎测试
# ===========================================================================

class TestROIAttribution:

    def _setup_attribution_data(self, roi_svc):
        """设置归因测试数据"""
        # 活动A：企微推送
        set_campaign_cost("campaign_a", 50000)  # 500元

        # 用户1 路径：企微触达 → 打开 → 点击 → 到店 → 下单
        roi_svc.record_touchpoint("u001", "wecom", "campaign_a", "impression")
        roi_svc.record_touchpoint("u001", "wecom", "campaign_a", "open")
        roi_svc.record_touchpoint("u001", "wecom", "campaign_a", "click")
        roi_svc.record_touchpoint("u001", "wecom", "campaign_a", "visit")
        roi_svc.record_conversion("u001", "order_001", 15000)

        # 用户2 路径：短信触达 → 到店 → 下单
        roi_svc.record_touchpoint("u002", "sms", "campaign_a", "impression")
        roi_svc.record_touchpoint("u002", "sms", "campaign_a", "visit")
        roi_svc.record_conversion("u002", "order_002", 12000)

        # 用户3 路径：多渠道触达 → 下单（企微 + 短信 + 小程序）
        roi_svc.record_touchpoint("u003", "wecom", "campaign_a", "impression")
        roi_svc.record_touchpoint("u003", "sms", "campaign_b", "impression")
        roi_svc.record_touchpoint("u003", "miniapp", "campaign_a", "click")
        roi_svc.record_conversion("u003", "order_003", 20000)

    def test_record_touchpoint(self, roi_svc):
        tp = roi_svc.record_touchpoint("u001", "wecom", "camp1", "impression")
        assert tp["user_id"] == "u001"
        assert tp["channel"] == "wecom"
        assert "touchpoint_id" in tp

    def test_record_conversion(self, roi_svc):
        conv = roi_svc.record_conversion("u001", "order_001", 15000)
        assert conv["user_id"] == "u001"
        assert conv["revenue_fen"] == 15000

    def test_first_touch_attribution(self, roi_svc):
        self._setup_attribution_data(roi_svc)
        result = roi_svc.compute_attribution("campaign_a", model="first_touch")
        assert result["model"] == "first_touch"
        assert result["total_revenue_fen"] > 0
        assert result["total_cost_fen"] == 50000
        assert result["roi"] > 0

    def test_last_touch_attribution(self, roi_svc):
        self._setup_attribution_data(roi_svc)
        result = roi_svc.compute_attribution("campaign_a", model="last_touch")
        assert result["model"] == "last_touch"
        assert result["total_revenue_fen"] > 0

    def test_multi_touch_attribution(self, roi_svc):
        self._setup_attribution_data(roi_svc)
        result = roi_svc.compute_attribution("campaign_a", model="multi_touch")
        assert result["model"] == "multi_touch"
        # 用户3有1个触点在 campaign_b，所以 campaign_a 不会获得全部收入
        assert result["total_revenue_fen"] > 0
        assert result["converted_users"] > 0

    def test_linear_attribution(self, roi_svc):
        self._setup_attribution_data(roi_svc)
        result = roi_svc.compute_attribution("campaign_a", model="linear")
        assert result["model"] == "linear"
        # 线性归因：所有活动平分
        assert result["total_revenue_fen"] > 0

    def test_time_decay_attribution(self, roi_svc):
        self._setup_attribution_data(roi_svc)
        result = roi_svc.compute_attribution("campaign_a", model="time_decay")
        assert result["model"] == "time_decay"
        assert result["total_revenue_fen"] > 0

    def test_invalid_model(self, roi_svc):
        result = roi_svc.compute_attribution("campaign_a", model="nonexistent")
        assert "error" in result

    def test_attribution_path(self, roi_svc):
        self._setup_attribution_data(roi_svc)
        path = roi_svc.get_attribution_path("u001")
        assert len(path) >= 4  # impression + open + click + visit + conversion
        types = [p.get("step") for p in path]
        assert "impression" in types
        assert "conversion" in types

    def test_channel_roi(self, roi_svc):
        self._setup_attribution_data(roi_svc)
        result = roi_svc.get_channel_roi({"start": "", "end": ""})
        assert len(result) >= 2  # wecom + sms
        channels = {r["channel"] for r in result}
        assert "wecom" in channels

    def test_roi_overview(self, roi_svc):
        self._setup_attribution_data(roi_svc)
        overview = roi_svc.get_roi_overview({"start": "", "end": ""})
        assert overview["total_return_fen"] == 47000  # 15000 + 12000 + 20000
        assert overview["total_investment_fen"] == 50000
        assert overview["total_converted_users"] == 3
        assert overview["overall_conversion_rate"] > 0

    def test_campaign_roi_shortcut(self, roi_svc):
        self._setup_attribution_data(roi_svc)
        result = roi_svc.get_campaign_roi("campaign_a")
        assert "roi" in result
        assert result["campaign_id"] == "campaign_a"


# ===========================================================================
# 8. 端到端测试：分群 → 旅程 → 内容 → 优惠 → 发送 → 转化 → ROI
# ===========================================================================

class TestEndToEnd:

    def test_full_growth_flow(
        self, brand_svc, segment_svc, journey_svc,
        content_svc, offer_svc, channel_svc, roi_svc,
        sample_brand, sample_users,
    ):
        """完整增长链路：
        1. 品牌策略 → 2. 用户分群 → 3. 创建旅程 → 4. 生成内容 →
        5. 创建优惠 → 6. 发送消息 → 7. 记录转化 → 8. 归因分析
        """
        # ---- Step 1: 品牌策略已创建 (sample_brand) ----
        card = brand_svc.generate_strategy_card("changzaiyiqi")
        assert card["positioning"] == "社区家庭中餐领导者"

        # ---- Step 2: 分群 ----
        # 将用户分类
        for user in sample_users:
            segments = segment_svc.classify_user(user)
            for seg_id in segments:
                add_users_to_segment(seg_id, [user])

        # 验证分群
        dormant_stats = segment_svc.compute_segment_stats("dormant")
        assert dormant_stats["count"] >= 1

        # ---- Step 3: 创建旅程 ----
        journey = journey_svc.create_journey(
            name="沉睡客召回链路",
            journey_type="reactivation",
            trigger={"type": "no_visit_30d", "params": {}},
            nodes=[
                {"node_id": "n1", "type": "send_content", "content_type": "wecom_chat",
                 "content_params": {}, "next": "n2"},
                {"node_id": "n2", "type": "wait", "wait_hours": 48, "next": "n3"},
                {"node_id": "n3", "type": "send_offer", "offer_type": "second_visit",
                 "next": None},
            ],
            target_segment_id="dormant",
        )
        journey_svc.publish_journey(journey["journey_id"])

        # ---- Step 4: 生成内容 ----
        content = content_svc.generate_content(
            content_type="wecom_chat",
            brand_id="changzaiyiqi",
            target_segment="dormant",
            dish_name="小炒黄牛肉",
        )
        assert "小炒黄牛肉" in content["body"]

        # 品牌合规校验
        validation = brand_svc.validate_content_against_brand("changzaiyiqi", content["body"])
        assert validation["valid"] is True

        # ---- Step 5: 创建优惠 ----
        offer = offer_svc.create_offer(
            name="老客回归-满100减30",
            offer_type="second_visit",
            discount_rules={"type": "threshold", "threshold_fen": 10000, "reduce_fen": 3000},
            validity_days=14,
            target_segments=["dormant"],
            stores=[],
            time_slots=[],
            margin_floor=0.45,
        )
        oid = offer["offer_id"]

        # 毛利合规检查
        margin = offer_svc.check_margin_compliance(oid, {
            "total_fen": 15000, "cost_fen": 5000, "discount_fen": 3000,
        })
        assert margin["compliant"] is True

        # ---- Step 6: 渠道发送 ----
        # 对沉睡客发送企微消息
        dormant_user = sample_users[2]  # 小王
        send_result = channel_svc.send_message(
            channel="wecom",
            user_id=dormant_user["user_id"],
            content=content["body"],
            offer_id=oid,
        )
        assert send_result["success"] is True

        # 执行旅程节点
        jid = journey["journey_id"]
        journey_svc.execute_node(jid, "n1", dormant_user["user_id"])

        # ---- Step 7: 记录归因触点 + 转化 ----
        roi_svc.record_touchpoint(
            dormant_user["user_id"], "wecom", "campaign_dormant_recall", "impression",
        )
        roi_svc.record_touchpoint(
            dormant_user["user_id"], "wecom", "campaign_dormant_recall", "open",
        )
        roi_svc.record_touchpoint(
            dormant_user["user_id"], "wecom", "campaign_dormant_recall", "click",
        )

        # 小王到店下单
        roi_svc.record_touchpoint(
            dormant_user["user_id"], "wecom", "campaign_dormant_recall", "visit",
        )
        roi_svc.record_conversion(
            dormant_user["user_id"], "order_recall_001", 13500,
        )

        # 核销优惠
        record_redemption(oid, dormant_user["user_id"], 13500, 3000)

        # ---- Step 8: ROI 分析 ----
        set_campaign_cost("campaign_dormant_recall", 5000)  # 50元成本

        attribution = roi_svc.compute_attribution("campaign_dormant_recall", model="multi_touch")
        assert attribution["total_revenue_fen"] == 13500
        assert attribution["total_cost_fen"] == 5000
        assert attribution["roi"] > 1.0  # ROI > 1 表示盈利

        # 查看用户归因路径
        path = roi_svc.get_attribution_path(dormant_user["user_id"])
        assert len(path) >= 4  # impression + open + click + visit + conversion

        # 旅程统计
        stats = journey_svc.get_journey_stats(jid)
        assert stats["executed_count"] >= 1

        # 优惠分析
        offer_analytics = offer_svc.get_offer_analytics(oid)
        assert offer_analytics["redeemed_count"] == 1

        # 全局 ROI 总览
        overview = roi_svc.get_roi_overview({"start": "", "end": ""})
        assert overview["total_return_fen"] == 13500
        assert overview["total_converted_users"] == 1

    def test_multi_segment_multi_channel(
        self, segment_svc, content_svc, channel_svc, roi_svc, sample_users,
    ):
        """多分群 × 多渠道的并行营销"""
        # 分群
        new_users = [u for u in sample_users if u["first_order_days"] <= 30]
        dormant_users = [u for u in sample_users if u["recency_days"] >= 60]

        # 新客走企微
        for u in new_users:
            content = content_svc.generate_content("wecom_chat", "brand1", "new_customer")
            channel_svc.send_message("wecom", u["user_id"], content["body"])
            roi_svc.record_touchpoint(u["user_id"], "wecom", "seg_new_welcome", "impression")

        # 沉睡客走短信
        for u in dormant_users:
            content = content_svc.generate_content("sms", "brand1", "dormant")
            channel_svc.send_message("sms", u["user_id"], content["body"])
            roi_svc.record_touchpoint(u["user_id"], "sms", "seg_dormant_recall", "impression")

        # 模拟转化
        if new_users:
            roi_svc.record_conversion(new_users[0]["user_id"], "order_new_001", 8800)
        if dormant_users:
            roi_svc.record_conversion(dormant_users[0]["user_id"], "order_dormant_001", 12000)

        # 渠道统计
        wecom_stats = channel_svc.get_channel_stats("wecom", {"start": "", "end": ""})
        sms_stats = channel_svc.get_channel_stats("sms", {"start": "", "end": ""})
        assert wecom_stats["total_sent"] == len(new_users)
        assert sms_stats["total_sent"] == len(dormant_users)

        # ROI 总览
        overview = roi_svc.get_roi_overview({"start": "", "end": ""})
        assert overview["total_converted_users"] >= 1

    def test_brand_compliance_blocks_bad_content(
        self, brand_svc, content_svc, sample_brand,
    ):
        """品牌合规拦截不当内容"""
        # 生成正常内容
        good = content_svc.generate_content(
            "moments", "changzaiyiqi", "all", dish_name="剁椒鱼头",
        )
        val = brand_svc.validate_content_against_brand("changzaiyiqi", good["body"])
        assert val["valid"] is True

        # 手工编写违规内容
        bad = "全网最便宜！免费送剁椒鱼头！清仓大甩卖！跳楼价！"
        val = brand_svc.validate_content_against_brand("changzaiyiqi", bad)
        assert val["valid"] is False
        assert len(val["errors"]) >= 3

    def test_margin_floor_hard_constraint(self, offer_svc):
        """毛利底线硬约束（三条硬约束之一）"""
        offer = offer_svc.create_offer(
            name="极限折扣", offer_type="new_customer_trial",
            discount_rules={"type": "fixed_amount", "amount_fen": 8000},
            validity_days=3, target_segments=["new_customer"],
            stores=[], time_slots=[], margin_floor=0.45,
        )

        # 低毛利订单 + 大额折扣 → 不合规
        result = offer_svc.check_margin_compliance(offer["offer_id"], {
            "total_fen": 10000, "cost_fen": 4000, "discount_fen": 8000,
        })
        assert result["compliant"] is False
        assert "低于底线" in result["reason"]

        # 高毛利订单 + 小额折扣 → 合规
        offer2 = offer_svc.create_offer(
            name="温和折扣", offer_type="new_customer_trial",
            discount_rules={"type": "fixed_amount", "amount_fen": 1000},
            validity_days=7, target_segments=["new_customer"],
            stores=[], time_slots=[], margin_floor=0.45,
        )
        result2 = offer_svc.check_margin_compliance(offer2["offer_id"], {
            "total_fen": 15000, "cost_fen": 5000, "discount_fen": 1000,
        })
        assert result2["compliant"] is True
