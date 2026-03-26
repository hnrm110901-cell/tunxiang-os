"""沉睡召回 Agent — P0 | 云端

检测沉睡用户，分析沉睡原因，生成召回策略，执行召回活动，追踪召回效果，预测流失风险。
"""
import uuid
from typing import Any
from ..base import SkillAgent, AgentResult


# 沉睡分层定义（天数）
DORMANT_TIERS = {
    "light": {"min_days": 15, "max_days": 29, "label": "轻度沉睡", "urgency": "low"},
    "medium": {"min_days": 30, "max_days": 59, "label": "中度沉睡", "urgency": "medium"},
    "deep": {"min_days": 60, "max_days": 999, "label": "深度沉睡", "urgency": "high"},
}

# 召回策略模板
RECALL_STRATEGIES = {
    "light": {
        "offer": "满100减15", "offer_fen": 1500, "threshold_fen": 10000,
        "channels": ["wechat"], "content": "好久不见，为您准备了一份小惊喜",
    },
    "medium": {
        "offer": "满80减25", "offer_fen": 2500, "threshold_fen": 8000,
        "channels": ["wechat", "sms"], "content": "想念您的味蕾，特惠回馈老朋友",
    },
    "deep": {
        "offer": "满60减30+赠甜品", "offer_fen": 3000, "threshold_fen": 6000,
        "channels": ["wechat", "sms", "phone"], "content": "诚意满满的回归礼，期待与您重逢",
    },
}

# 沉睡原因分类
DORMANT_REASONS = ["价格敏感", "口味不合", "服务不满", "竞对吸引", "搬迁/出差", "季节性", "未知"]


class DormantRecallAgent(SkillAgent):
    agent_id = "dormant_recall"
    agent_name = "沉睡召回"
    description = "沉睡用户检测、原因分析、召回策略生成、活动执行、效果追踪、流失预测"
    priority = "P0"
    run_location = "cloud"

    def get_supported_actions(self) -> list[str]:
        return [
            "detect_dormant_users",
            "analyze_dormant_reason",
            "generate_recall_strategy",
            "execute_recall_campaign",
            "track_recall_effectiveness",
            "predict_churn_risk",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "detect_dormant_users": self._detect_dormant_users,
            "analyze_dormant_reason": self._analyze_dormant_reason,
            "generate_recall_strategy": self._generate_recall_strategy,
            "execute_recall_campaign": self._execute_recall_campaign,
            "track_recall_effectiveness": self._track_recall_effectiveness,
            "predict_churn_risk": self._predict_churn_risk,
        }
        handler = dispatch.get(action)
        if handler:
            return await handler(params)
        return AgentResult(success=False, action=action, error=f"不支持的操作: {action}")

    async def _detect_dormant_users(self, params: dict) -> AgentResult:
        """检测沉睡用户（15天/30天/60天未到店）"""
        members = params.get("members", [])
        min_days = params.get("min_days", 15)

        tier_counts = {"light": 0, "medium": 0, "deep": 0}
        dormant_list = []

        for m in members:
            last_visit_days = m.get("last_visit_days_ago", 0)
            if last_visit_days < min_days:
                continue

            if last_visit_days >= 60:
                tier = "deep"
            elif last_visit_days >= 30:
                tier = "medium"
            else:
                tier = "light"

            tier_counts[tier] += 1
            dormant_list.append({
                "customer_id": m.get("customer_id"),
                "name": m.get("name", ""),
                "last_visit_days_ago": last_visit_days,
                "tier": tier,
                "tier_label": DORMANT_TIERS[tier]["label"],
                "total_spent_yuan": round(m.get("total_spent_fen", 0) / 100, 2),
                "visit_count": m.get("visit_count", 0),
                "urgency": DORMANT_TIERS[tier]["urgency"],
            })

        dormant_list.sort(key=lambda x: x["last_visit_days_ago"], reverse=True)
        total = len(dormant_list)

        return AgentResult(
            success=True, action="detect_dormant_users",
            data={
                "dormant_users": dormant_list[:100],
                "total": total,
                "tier_distribution": tier_counts,
                "dormant_rate_pct": round(total / max(1, len(members)) * 100, 1),
            },
            reasoning=f"检测到 {total} 位沉睡用户：轻度{tier_counts['light']}、"
                      f"中度{tier_counts['medium']}、深度{tier_counts['deep']}",
            confidence=0.9,
        )

    async def _analyze_dormant_reason(self, params: dict) -> AgentResult:
        """分析沉睡原因（价格/口味/服务/竞对）"""
        customer_id = params.get("customer_id", "")
        last_orders = params.get("last_orders", [])
        reviews = params.get("reviews", [])
        competitor_visits = params.get("competitor_visits", 0)

        reasons = []
        confidence_map = {}

        # 价格敏感：最后几单频繁使用优惠券
        coupon_usage = sum(1 for o in last_orders if o.get("used_coupon"))
        if coupon_usage >= len(last_orders) * 0.7 and last_orders:
            reasons.append("价格敏感")
            confidence_map["价格敏感"] = 0.8

        # 口味不合：差评关键词
        taste_keywords = ["难吃", "味道差", "不好吃", "口味", "太咸", "太辣", "不新鲜"]
        for r in reviews:
            text = r.get("text", "")
            if any(kw in text for kw in taste_keywords):
                reasons.append("口味不合")
                confidence_map["口味不合"] = 0.75
                break

        # 服务不满
        service_keywords = ["服务差", "态度", "等太久", "慢", "不理人"]
        for r in reviews:
            text = r.get("text", "")
            if any(kw in text for kw in service_keywords):
                reasons.append("服务不满")
                confidence_map["服务不满"] = 0.7
                break

        # 竞对吸引
        if competitor_visits >= 3:
            reasons.append("竞对吸引")
            confidence_map["竞对吸引"] = 0.65

        if not reasons:
            reasons.append("未知")
            confidence_map["未知"] = 0.4

        primary_reason = reasons[0]
        return AgentResult(
            success=True, action="analyze_dormant_reason",
            data={
                "customer_id": customer_id,
                "primary_reason": primary_reason,
                "all_reasons": reasons,
                "confidence_map": confidence_map,
                "evidence": {
                    "coupon_usage_rate": round(coupon_usage / max(1, len(last_orders)) * 100, 1),
                    "negative_reviews": len([r for r in reviews if r.get("rating", 5) <= 2]),
                    "competitor_visits": competitor_visits,
                },
            },
            reasoning=f"沉睡主因: {primary_reason}，置信度 {confidence_map.get(primary_reason, 0):.0%}",
            confidence=confidence_map.get(primary_reason, 0.5),
        )

    async def _generate_recall_strategy(self, params: dict) -> AgentResult:
        """生成召回策略（权益+内容+渠道）"""
        tier = params.get("tier", "light")
        reason = params.get("reason", "未知")
        customer_id = params.get("customer_id", "")
        customer_name = params.get("customer_name", "")

        base_strategy = RECALL_STRATEGIES.get(tier, RECALL_STRATEGIES["light"])
        strategy_id = str(uuid.uuid4())[:8]

        # 根据原因调整策略
        extra_offer = None
        if reason == "价格敏感":
            extra_offer = {"type": "加大优惠力度", "detail": "额外赠送10元无门槛券"}
        elif reason == "口味不合":
            extra_offer = {"type": "新品体验", "detail": "赠送当季新品试吃券"}
        elif reason == "服务不满":
            extra_offer = {"type": "服务升级", "detail": "专人接待+免费升级包间"}
        elif reason == "竞对吸引":
            extra_offer = {"type": "差异化权益", "detail": "会员专属菜品+积分翻倍"}

        return AgentResult(
            success=True, action="generate_recall_strategy",
            data={
                "strategy_id": strategy_id,
                "customer_id": customer_id,
                "customer_name": customer_name,
                "tier": tier,
                "reason": reason,
                "main_offer": base_strategy["offer"],
                "offer_fen": base_strategy["offer_fen"],
                "threshold_fen": base_strategy["threshold_fen"],
                "channels": base_strategy["channels"],
                "content_template": base_strategy["content"],
                "extra_offer": extra_offer,
                "valid_days": 14,
            },
            reasoning=f"为{DORMANT_TIERS.get(tier, {}).get('label', tier)}用户 {customer_name} "
                      f"生成召回策略: {base_strategy['offer']}",
            confidence=0.8,
        )

    async def _execute_recall_campaign(self, params: dict) -> AgentResult:
        """执行召回活动"""
        strategy_id = params.get("strategy_id", "")
        target_customer_ids = params.get("target_customer_ids", [])
        channels = params.get("channels", ["wechat"])
        scheduled_time = params.get("scheduled_time", "即时发送")

        campaign_id = str(uuid.uuid4())[:8]
        target_count = len(target_customer_ids)

        channel_status = {}
        for ch in channels:
            channel_status[ch] = {"status": "queued", "target_count": target_count}

        return AgentResult(
            success=True, action="execute_recall_campaign",
            data={
                "campaign_id": campaign_id,
                "strategy_id": strategy_id,
                "target_count": target_count,
                "channels": channel_status,
                "scheduled_time": scheduled_time,
                "status": "executing",
                "estimated_reach_rate": 0.75,
            },
            reasoning=f"召回活动已启动: {target_count} 人，渠道 {', '.join(channels)}",
            confidence=0.85,
        )

    async def _track_recall_effectiveness(self, params: dict) -> AgentResult:
        """追踪召回效果"""
        campaign_id = params.get("campaign_id", "")
        sent_count = params.get("sent_count", 0)
        opened_count = params.get("opened_count", 0)
        clicked_count = params.get("clicked_count", 0)
        returned_count = params.get("returned_count", 0)
        total_spend_fen = params.get("returned_spend_fen", 0)
        cost_fen = params.get("campaign_cost_fen", 0)

        open_rate = round(opened_count / max(1, sent_count) * 100, 1)
        click_rate = round(clicked_count / max(1, opened_count) * 100, 1)
        return_rate = round(returned_count / max(1, sent_count) * 100, 1)
        roi = round((total_spend_fen - cost_fen) / max(1, cost_fen), 2)

        return AgentResult(
            success=True, action="track_recall_effectiveness",
            data={
                "campaign_id": campaign_id,
                "sent_count": sent_count,
                "open_rate_pct": open_rate,
                "click_rate_pct": click_rate,
                "return_rate_pct": return_rate,
                "returned_count": returned_count,
                "returned_spend_yuan": round(total_spend_fen / 100, 2),
                "campaign_cost_yuan": round(cost_fen / 100, 2),
                "roi": roi,
                "effectiveness": "优秀" if return_rate >= 15 else "良好" if return_rate >= 8 else "一般" if return_rate >= 3 else "较差",
            },
            reasoning=f"召回效果: 触达{sent_count}人，回流{returned_count}人（{return_rate}%），ROI {roi}",
            confidence=0.85,
        )

    async def _predict_churn_risk(self, params: dict) -> AgentResult:
        """预测流失风险分"""
        members = params.get("members", [])
        predictions = []

        for m in members:
            last_days = m.get("last_visit_days_ago", 0)
            frequency = m.get("monthly_frequency", 0)
            spend_trend = m.get("spend_trend", 0)  # 正=增长 负=下降
            complaint_count = m.get("complaint_count", 0)

            # 多因子风险模型
            risk = 0.1
            risk += min(0.4, last_days / 150)
            if frequency <= 1:
                risk += 0.15
            elif frequency <= 2:
                risk += 0.05
            if spend_trend < -20:
                risk += 0.15
            elif spend_trend < -10:
                risk += 0.08
            if complaint_count >= 2:
                risk += 0.2
            elif complaint_count >= 1:
                risk += 0.1

            risk = min(0.98, risk)

            predictions.append({
                "customer_id": m.get("customer_id"),
                "name": m.get("name", ""),
                "churn_risk": round(risk, 2),
                "risk_level": "极高" if risk >= 0.8 else "高" if risk >= 0.6 else "中" if risk >= 0.4 else "低",
                "key_signals": [],
            })
            if last_days >= 30:
                predictions[-1]["key_signals"].append(f"已{last_days}天未到店")
            if spend_trend < -10:
                predictions[-1]["key_signals"].append(f"消费趋势下降{abs(spend_trend)}%")
            if complaint_count >= 1:
                predictions[-1]["key_signals"].append(f"近期投诉{complaint_count}次")

        predictions.sort(key=lambda x: x["churn_risk"], reverse=True)
        high_risk = sum(1 for p in predictions if p["risk_level"] in ("极高", "高"))

        return AgentResult(
            success=True, action="predict_churn_risk",
            data={
                "predictions": predictions[:50],
                "total": len(predictions),
                "high_risk_count": high_risk,
                "avg_risk": round(sum(p["churn_risk"] for p in predictions) / max(1, len(predictions)), 2),
            },
            reasoning=f"预测 {len(predictions)} 人流失风险，高风险 {high_risk} 人",
            confidence=0.75,
        )
