"""新客转化 Agent — P0 | 云端

识别新到店客户，生成欢迎权益，创建首访触达旅程，预测转化概率，分析来源渠道。
"""

import uuid
from typing import Any

from ..base import AgentResult, SkillAgent

# 新客欢迎权益模板
WELCOME_OFFER_TEMPLATES = {
    "high_spend": {"offer": "满200减50", "type": "coupon", "threshold_fen": 20000, "discount_fen": 5000},
    "mid_spend": {"offer": "满100减20", "type": "coupon", "threshold_fen": 10000, "discount_fen": 2000},
    "low_spend": {"offer": "满50减10", "type": "coupon", "threshold_fen": 5000, "discount_fen": 1000},
    "default": {"offer": "赠送甜品一份", "type": "gift", "threshold_fen": 0, "discount_fen": 0},
}

# 首访后触达旅程节点
FIRST_VISIT_JOURNEY = [
    {"step": 1, "delay_hours": 2, "channel": "wechat", "content": "感谢首次光临，期待再次相见"},
    {"step": 2, "delay_hours": 48, "channel": "sms", "content": "新客专属优惠券已到账，7天内有效"},
    {"step": 3, "delay_hours": 168, "channel": "wechat", "content": "想念您的味蕾，本周特惠菜品推荐"},
    {"step": 4, "delay_hours": 360, "channel": "sms", "content": "15天未见，送您一张召回券"},
]

# 来源渠道权重
SOURCE_CHANNELS = ["美团", "大众点评", "抖音", "小红书", "微信朋友圈", "门店自然到店", "老客推荐", "外卖转堂食"]


class NewCustomerConvertAgent(SkillAgent):
    agent_id = "new_customer_convert"
    agent_name = "新客转化"
    description = "新客识别、欢迎权益生成、首访旅程创建、转化概率预测、来源渠道分析"
    priority = "P0"
    run_location = "cloud"

    # Sprint D1 / PR 批次 3：新客权益 = 让利成本，需 margin 校验避免首单深度亏损
    constraint_scope = {"margin"}

    def get_supported_actions(self) -> list[str]:
        return [
            "identify_new_customers",
            "generate_welcome_offer",
            "create_first_visit_journey",
            "predict_conversion_probability",
            "analyze_new_customer_source",
            "get_new_customer_stats",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "identify_new_customers": self._identify_new_customers,
            "generate_welcome_offer": self._generate_welcome_offer,
            "create_first_visit_journey": self._create_first_visit_journey,
            "predict_conversion_probability": self._predict_conversion_probability,
            "analyze_new_customer_source": self._analyze_new_customer_source,
            "get_new_customer_stats": self._get_new_customer_stats,
        }
        handler = dispatch.get(action)
        if handler:
            return await handler(params)
        return AgentResult(success=False, action=action, error=f"不支持的操作: {action}")

    async def _identify_new_customers(self, params: dict) -> AgentResult:
        """识别新到店客户（7天内首次到店）"""
        customers = params.get("customers", [])
        lookback_days = params.get("lookback_days", 7)

        new_customers = []
        for c in customers:
            visit_count = c.get("total_visits", 0)
            first_visit_days_ago = c.get("first_visit_days_ago", 0)
            if visit_count <= 1 and first_visit_days_ago <= lookback_days:
                avg_spend_fen = c.get("avg_spend_fen", 0)
                spend_tier = (
                    "high_spend" if avg_spend_fen >= 15000 else "mid_spend" if avg_spend_fen >= 8000 else "low_spend"
                )
                new_customers.append(
                    {
                        "customer_id": c.get("customer_id"),
                        "name": c.get("name", ""),
                        "first_visit_date": c.get("first_visit_date", ""),
                        "source_channel": c.get("source_channel", "未知"),
                        "spend_fen": avg_spend_fen,
                        "spend_tier": spend_tier,
                        "has_registered": c.get("has_registered", False),
                    }
                )

        return AgentResult(
            success=True,
            action="identify_new_customers",
            data={
                "new_customers": new_customers[:100],
                "total": len(new_customers),
                "lookback_days": lookback_days,
                "registration_rate": round(
                    sum(1 for nc in new_customers if nc["has_registered"]) / max(1, len(new_customers)) * 100, 1
                ),
            },
            reasoning=f"过去{lookback_days}天识别到 {len(new_customers)} 位新客，"
            f"注册率 {sum(1 for nc in new_customers if nc['has_registered']) / max(1, len(new_customers)) * 100:.1f}%",
            confidence=0.9,
        )

    async def _generate_welcome_offer(self, params: dict) -> AgentResult:
        """生成新客欢迎权益（根据客单和消费偏好）"""
        spend_fen = params.get("avg_spend_fen", 0)
        preferences = params.get("preferences", [])
        customer_id = params.get("customer_id", "")

        if spend_fen >= 15000:
            tier = "high_spend"
        elif spend_fen >= 8000:
            tier = "mid_spend"
        elif spend_fen >= 3000:
            tier = "low_spend"
        else:
            tier = "default"

        template = WELCOME_OFFER_TEMPLATES[tier]
        offer_id = str(uuid.uuid4())[:8]

        # 偏好加成
        bonus_items = []
        if "火锅" in preferences:
            bonus_items.append({"item": "锅底升级券", "type": "upgrade"})
        if "甜品" in preferences:
            bonus_items.append({"item": "甜品买一赠一", "type": "bogo"})
        if "酒水" in preferences:
            bonus_items.append({"item": "指定饮品半价", "type": "half_price"})

        return AgentResult(
            success=True,
            action="generate_welcome_offer",
            data={
                "offer_id": offer_id,
                "customer_id": customer_id,
                "tier": tier,
                "main_offer": template,
                "bonus_items": bonus_items,
                "valid_days": 7,
                "channels": ["wechat", "sms"],
            },
            reasoning=f"新客权益: {template['offer']}，消费档位 {tier}，附加 {len(bonus_items)} 项偏好加成",
            confidence=0.85,
        )

    async def _create_first_visit_journey(self, params: dict) -> AgentResult:
        """创建首访后触达旅程（2h/48h/7d/15d）"""
        customer_id = params.get("customer_id", "")
        customer_name = params.get("customer_name", "")
        source_channel = params.get("source_channel", "门店自然到店")

        journey_id = str(uuid.uuid4())[:8]
        steps = []
        for node in FIRST_VISIT_JOURNEY:
            steps.append(
                {
                    "step": node["step"],
                    "delay_hours": node["delay_hours"],
                    "channel": node["channel"],
                    "content": node["content"],
                    "status": "pending",
                }
            )

        return AgentResult(
            success=True,
            action="create_first_visit_journey",
            data={
                "journey_id": journey_id,
                "customer_id": customer_id,
                "customer_name": customer_name,
                "source_channel": source_channel,
                "steps": steps,
                "total_steps": len(steps),
                "status": "active",
            },
            reasoning=f"为新客 {customer_name} 创建首访旅程，共 {len(steps)} 个触达节点",
            confidence=0.9,
        )

    async def _predict_conversion_probability(self, params: dict) -> AgentResult:
        """预测新客转化为复购客的概率"""
        customers = params.get("customers", [])
        predictions = []

        for c in customers:
            spend_fen = c.get("first_spend_fen", 0)
            dwell_minutes = c.get("dwell_minutes", 0)
            ordered_items = c.get("ordered_items", 0)
            registered = c.get("has_registered", False)
            source = c.get("source_channel", "未知")

            # 多因子评分模型
            score = 0.3  # 基础分
            if spend_fen >= 10000:
                score += 0.15
            elif spend_fen >= 5000:
                score += 0.08
            if dwell_minutes >= 60:
                score += 0.1
            elif dwell_minutes >= 30:
                score += 0.05
            if ordered_items >= 4:
                score += 0.1
            if registered:
                score += 0.2
            if source in ["老客推荐", "微信朋友圈"]:
                score += 0.1
            elif source in ["美团", "大众点评"]:
                score += 0.05

            score = min(0.95, score)

            predictions.append(
                {
                    "customer_id": c.get("customer_id"),
                    "conversion_prob": round(score, 2),
                    "level": "高" if score >= 0.7 else "中" if score >= 0.5 else "低",
                    "key_factors": [],
                }
            )
            if registered:
                predictions[-1]["key_factors"].append("已注册会员")
            if spend_fen >= 10000:
                predictions[-1]["key_factors"].append("首单高消费")
            if source in ["老客推荐"]:
                predictions[-1]["key_factors"].append("老客推荐来源")

        high_count = sum(1 for p in predictions if p["level"] == "高")
        return AgentResult(
            success=True,
            action="predict_conversion_probability",
            data={
                "predictions": predictions[:50],
                "total": len(predictions),
                "high_conversion_count": high_count,
                "avg_prob": round(sum(p["conversion_prob"] for p in predictions) / max(1, len(predictions)), 2),
            },
            reasoning=f"预测 {len(predictions)} 位新客转化概率，高转化 {high_count} 人",
            confidence=0.75,
        )

    async def _analyze_new_customer_source(self, params: dict) -> AgentResult:
        """分析新客来源渠道"""
        customers = params.get("customers", [])
        channel_stats: dict[str, dict] = {}

        for c in customers:
            channel = c.get("source_channel", "未知")
            if channel not in channel_stats:
                channel_stats[channel] = {"count": 0, "total_spend_fen": 0, "registered": 0}
            channel_stats[channel]["count"] += 1
            channel_stats[channel]["total_spend_fen"] += c.get("first_spend_fen", 0)
            if c.get("has_registered"):
                channel_stats[channel]["registered"] += 1

        total = len(customers)
        channels = []
        for name, stats in sorted(channel_stats.items(), key=lambda x: x[1]["count"], reverse=True):
            channels.append(
                {
                    "channel": name,
                    "count": stats["count"],
                    "pct": round(stats["count"] / max(1, total) * 100, 1),
                    "avg_spend_yuan": round(stats["total_spend_fen"] / max(1, stats["count"]) / 100, 2),
                    "registration_rate": round(stats["registered"] / max(1, stats["count"]) * 100, 1),
                }
            )

        return AgentResult(
            success=True,
            action="analyze_new_customer_source",
            data={
                "channels": channels,
                "total_new_customers": total,
                "top_channel": channels[0]["channel"] if channels else "无",
            },
            reasoning=f"分析 {total} 位新客来源，TOP渠道: {channels[0]['channel'] if channels else '无'}"
            f"（{channels[0]['pct'] if channels else 0}%）",
            confidence=0.85,
        )

    async def _get_new_customer_stats(self, params: dict) -> AgentResult:
        """新客数据统计（日/周/月）"""
        period = params.get("period", "week")
        new_count = params.get("new_count", 0)
        total_customers = params.get("total_customers", 0)
        converted_count = params.get("converted_count", 0)
        total_spend_fen = params.get("total_spend_fen", 0)
        prev_new_count = params.get("prev_new_count", 0)

        conversion_rate = round(converted_count / max(1, new_count) * 100, 1)
        avg_spend = round(total_spend_fen / max(1, new_count) / 100, 2)
        growth_rate = round((new_count - prev_new_count) / max(1, prev_new_count) * 100, 1)

        return AgentResult(
            success=True,
            action="get_new_customer_stats",
            data={
                "period": period,
                "new_count": new_count,
                "prev_new_count": prev_new_count,
                "growth_rate_pct": growth_rate,
                "conversion_rate_pct": conversion_rate,
                "avg_first_spend_yuan": avg_spend,
                "new_customer_share_pct": round(new_count / max(1, total_customers) * 100, 1),
                "status": "增长" if growth_rate > 0 else "下降" if growth_rate < 0 else "持平",
            },
            reasoning=f"{period}新客 {new_count} 人，环比{'增长' if growth_rate > 0 else '下降'} {abs(growth_rate)}%，"
            f"转化率 {conversion_rate}%",
            confidence=0.9,
        )
