"""智能客服 Agent — 增长型 | 云端

自动回答常见问题、客诉处理建议、评价情感分析、生成个性化回复。
通过 ModelRouter (MODERATE) 调用 LLM 生成自然语言回复。
"""

from typing import Any

import structlog

from ..base import ActionConfig, AgentResult, SkillAgent

try:
    from services.tunxiang_api.src.shared.core.model_router import model_router
except ImportError:
    model_router = None  # 独立测试时无跨服务依赖

logger = structlog.get_logger()

# FAQ 知识库（常见问题 -> 答案模板）
FAQ_KNOWLEDGE = {
    "营业时间": {
        "keywords": ["营业时间", "几点开门", "几点关门", "几点营业", "什么时候开", "什么时候关"],
        "template": "您好！我们的营业时间是 {open_time} 至 {close_time}，欢迎光临！",
        "category": "basic_info",
    },
    "预订": {
        "keywords": ["预订", "预约", "订位", "订座", "包间", "定位"],
        "template": "您好！您可以通过以下方式预订：\n1. 拨打门店电话：{phone}\n2. 通过小程序在线预约\n包间最低消费为 {min_charge} 元起。",
        "category": "reservation",
    },
    "菜单": {
        "keywords": ["菜单", "菜品", "有什么菜", "推荐菜", "招牌菜", "特色菜"],
        "template": "我们的招牌菜有：{signature_dishes}。您可以在小程序查看完整菜单。当季推荐：{seasonal_dishes}。",
        "category": "menu",
    },
    "停车": {
        "keywords": ["停车", "车位", "停车场", "泊车"],
        "template": "门店提供 {parking_info}，消费满 {parking_threshold} 元可免费停车 {free_hours} 小时。",
        "category": "basic_info",
    },
    "外卖": {
        "keywords": ["外卖", "配送", "送餐", "打包"],
        "template": "我们支持外卖配送！您可以通过美团/饿了么/小程序下单，配送范围 {delivery_range} 公里内。",
        "category": "delivery",
    },
    "会员": {
        "keywords": ["会员", "积分", "充值", "储值", "折扣卡"],
        "template": "成为会员即享 {member_discount} 折优惠，积分可兑换菜品。充值满 {recharge_threshold} 赠 {recharge_gift}。",
        "category": "membership",
    },
}

# 客诉等级与补偿规则
COMPLAINT_LEVELS = {
    "minor": {
        "label": "轻微",
        "keywords": ["等太久", "上菜慢", "味道一般", "偏咸", "偏辣"],
        "compensation": ["口头致歉", "赠送果盘/饮品"],
        "escalation": False,
    },
    "moderate": {
        "label": "中等",
        "keywords": ["有异物", "菜品有问题", "服务态度差", "上错菜", "少菜"],
        "compensation": ["口头致歉", "免除问题菜品费用", "赠送优惠券"],
        "escalation": False,
    },
    "severe": {
        "label": "严重",
        "keywords": ["食物中毒", "过敏", "受伤", "吃坏", "拉肚子", "虫子"],
        "compensation": ["立即致歉", "免单", "就医协助", "店长亲自处理"],
        "escalation": True,
    },
}

# 情感关键词
SENTIMENT_KEYWORDS = {
    "positive": [
        "好吃",
        "美味",
        "满意",
        "推荐",
        "赞",
        "棒",
        "喜欢",
        "下次再来",
        "不错",
        "环境好",
        "服务好",
        "新鲜",
        "分量足",
        "实惠",
        "划算",
    ],
    "negative": [
        "难吃",
        "差",
        "不好",
        "太贵",
        "不新鲜",
        "慢",
        "态度差",
        "脏",
        "失望",
        "差评",
        "不推荐",
        "坑",
        "不值",
        "冷了",
        "量少",
    ],
}


class SmartCustomerServiceAgent(SkillAgent):
    agent_id = "smart_customer_service"
    agent_name = "智能客服"
    description = "FAQ自动回答、客诉处理建议、评价情感分析、个性化回复生成"
    priority = "P2"
    run_location = "cloud"

    def get_supported_actions(self) -> list[str]:
        return ["answer_faq", "handle_complaint", "analyze_sentiment", "generate_reply"]

    def get_action_config(self, action: str) -> ActionConfig:
        """智能客服 Agent 的 action 级会话策略"""
        configs = {
            # 客诉处理涉及补偿决策，需人工确认
            "handle_complaint": ActionConfig(
                risk_level="medium",
                requires_human_confirm=True,
                max_retries=2,
            ),
            # 回复生成可重试
            "generate_reply": ActionConfig(
                risk_level="low",
                max_retries=2,
            ),
            # FAQ 自动回答
            "answer_faq": ActionConfig(
                risk_level="low",
                max_retries=1,
            ),
            # 情感分析
            "analyze_sentiment": ActionConfig(
                risk_level="low",
                max_retries=1,
            ),
        }
        return configs.get(action, ActionConfig())

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "answer_faq": self._handle_inquiry,
            "handle_complaint": self._handle_complaint,
            "analyze_sentiment": self._sentiment_analysis,
            "generate_reply": self._generate_response,
        }
        handler = dispatch.get(action)
        if handler:
            return await handler(params)
        return AgentResult(success=False, action=action, error=f"不支持的操作: {action}")

    async def _handle_inquiry(self, params: dict) -> AgentResult:
        """自动回答常见问题（营业时间/菜单/预订）"""
        question = params.get("question", "")
        context = params.get("context", {})

        # 匹配FAQ
        best_match = None
        best_score = 0

        for faq_key, faq_info in FAQ_KNOWLEDGE.items():
            hit_count = sum(1 for kw in faq_info["keywords"] if kw in question)
            if hit_count > best_score:
                best_score = hit_count
                best_match = faq_key

        if best_match and best_score > 0:
            faq = FAQ_KNOWLEDGE[best_match]
            template = faq["template"]

            # 填充上下文变量
            try:
                answer = template.format(**context) if context else template
            except KeyError:
                answer = template  # 缺少变量时返回原始模板

            return AgentResult(
                success=True,
                action="answer_faq",
                data={
                    "matched_faq": best_match,
                    "category": faq["category"],
                    "answer": answer,
                    "match_score": best_score,
                    "need_human": False,
                },
                reasoning=f"匹配FAQ: {best_match}，关键词命中 {best_score} 个",
                confidence=min(0.95, 0.6 + best_score * 0.15),
            )

        # 无法匹配，转人工
        return AgentResult(
            success=True,
            action="answer_faq",
            data={
                "matched_faq": None,
                "answer": "抱歉，我暂时无法回答您的问题，正在为您转接人工客服...",
                "need_human": True,
            },
            reasoning=f"未匹配到FAQ，问题: {question[:50]}",
            confidence=0.3,
        )

    async def _handle_complaint(self, params: dict) -> AgentResult:
        """客诉处理建议（补偿方案/升级规则）"""
        complaint = params.get("complaint", "")
        order_id = params.get("order_id", "")
        order_amount_fen = params.get("order_amount_fen", 0)
        customer_level = params.get("customer_level", "normal")  # normal/vip

        # 使用 ModelRouter (MODERATE)
        model = model_router.get_model("customer_service") if model_router else "claude-sonnet-4-6"

        # 识别客诉等级
        complaint_level = "minor"
        matched_keywords = []

        for level, info in COMPLAINT_LEVELS.items():
            for kw in info["keywords"]:
                if kw in complaint:
                    matched_keywords.append(kw)
                    if level == "severe":
                        complaint_level = "severe"
                    elif level == "moderate" and complaint_level != "severe":
                        complaint_level = "moderate"

        level_info = COMPLAINT_LEVELS[complaint_level]

        # VIP客户升级补偿
        compensation = list(level_info["compensation"])
        if customer_level == "vip":
            compensation.append("VIP专属关怀电话")
            if complaint_level == "moderate":
                compensation.append("赠送储值金额")

        # 估算补偿成本
        if complaint_level == "minor":
            estimated_cost_fen = min(2000, int(order_amount_fen * 0.05))
        elif complaint_level == "moderate":
            estimated_cost_fen = min(10000, int(order_amount_fen * 0.3))
        else:
            estimated_cost_fen = order_amount_fen  # 严重投诉: 免单

        return AgentResult(
            success=True,
            action="handle_complaint",
            data={
                "order_id": order_id,
                "complaint_level": complaint_level,
                "level_label": level_info["label"],
                "matched_keywords": matched_keywords,
                "compensation_plan": compensation,
                "estimated_cost_fen": estimated_cost_fen,
                "estimated_cost_yuan": round(estimated_cost_fen / 100, 2),
                "need_escalation": level_info["escalation"],
                "escalation_to": "店长" if level_info["escalation"] else None,
                "response_template": _build_complaint_response(complaint_level, compensation),
            },
            reasoning=(
                f"客诉等级: {level_info['label']}，"
                f"匹配关键词: {'、'.join(matched_keywords) if matched_keywords else '无'}，"
                f"{'需升级处理' if level_info['escalation'] else '可自主处理'}"
            ),
            confidence=0.8 if matched_keywords else 0.5,
        )

    async def _sentiment_analysis(self, params: dict) -> AgentResult:
        """评价情感分析"""
        feedback = params.get("feedback", "")
        feedbacks = params.get("feedbacks", [])

        # 支持批量分析
        if feedbacks:
            items = feedbacks
        elif feedback:
            items = [{"text": feedback, "id": "single"}]
        else:
            return AgentResult(
                success=False,
                action="analyze_sentiment",
                error="缺少 feedback 或 feedbacks 参数",
            )

        results = []
        sentiment_counts = {"positive": 0, "negative": 0, "neutral": 0}

        for item in items:
            text = item.get("text", "") if isinstance(item, dict) else str(item)
            item_id = item.get("id", "") if isinstance(item, dict) else ""

            pos_hits = sum(1 for kw in SENTIMENT_KEYWORDS["positive"] if kw in text)
            neg_hits = sum(1 for kw in SENTIMENT_KEYWORDS["negative"] if kw in text)

            if pos_hits > neg_hits:
                sentiment = "positive"
                score = min(1.0, 0.5 + pos_hits * 0.1)
            elif neg_hits > pos_hits:
                sentiment = "negative"
                score = max(0.0, 0.5 - neg_hits * 0.1)
            else:
                sentiment = "neutral"
                score = 0.5

            sentiment_counts[sentiment] += 1

            # 提取关键词
            found_keywords = []
            for kw in SENTIMENT_KEYWORDS["positive"]:
                if kw in text:
                    found_keywords.append({"keyword": kw, "type": "positive"})
            for kw in SENTIMENT_KEYWORDS["negative"]:
                if kw in text:
                    found_keywords.append({"keyword": kw, "type": "negative"})

            results.append(
                {
                    "id": item_id,
                    "text": text[:200],
                    "sentiment": sentiment,
                    "score": round(score, 2),
                    "keywords": found_keywords,
                }
            )

        total = len(results)
        positive_rate = round(sentiment_counts["positive"] / max(1, total) * 100, 1)

        return AgentResult(
            success=True,
            action="analyze_sentiment",
            data={
                "results": results,
                "total": total,
                "sentiment_distribution": sentiment_counts,
                "positive_rate_pct": positive_rate,
                "avg_score": round(sum(r["score"] for r in results) / max(1, total), 2),
            },
            reasoning=(
                f"分析 {total} 条评价：好评 {sentiment_counts['positive']}、"
                f"差评 {sentiment_counts['negative']}、"
                f"中立 {sentiment_counts['neutral']}，好评率 {positive_rate}%"
            ),
            confidence=0.8,
        )

    async def _generate_response(self, params: dict) -> AgentResult:
        """生成个性化回复"""
        template = params.get("template", "")
        context = params.get("context", {})
        tone = params.get("tone", "friendly")  # friendly/formal/apologetic
        customer_name = params.get("customer_name", "")
        feedback_text = params.get("feedback_text", "")

        # 使用 ModelRouter (MODERATE)
        model = model_router.get_model("customer_service") if model_router else "claude-sonnet-4-6"

        # 语气模板
        tone_prefix = {
            "friendly": "亲爱的" if customer_name else "您好！",
            "formal": "尊敬的" if customer_name else "您好，",
            "apologetic": "非常抱歉，",
        }

        prefix = tone_prefix.get(tone, "您好！")
        if customer_name and tone != "apologetic":
            prefix += f"{customer_name}，"

        # 生成回复
        if template:
            try:
                body = template.format(**context)
            except KeyError:
                body = template
        elif feedback_text:
            # 根据评价内容生成回复
            pos_hits = sum(1 for kw in SENTIMENT_KEYWORDS["positive"] if kw in feedback_text)
            neg_hits = sum(1 for kw in SENTIMENT_KEYWORDS["negative"] if kw in feedback_text)

            if pos_hits > neg_hits:
                body = "感谢您的认可和支持！我们会继续保持品质，期待您的下次光临。"
            elif neg_hits > pos_hits:
                body = "非常感谢您的反馈，我们已认真记录您的意见，将尽快改进。为表歉意，下次到店为您准备一份小礼物。"
            else:
                body = "感谢您的评价，您的每一条反馈都是我们进步的动力。期待再次为您服务！"
        else:
            body = "感谢您的光临，期待下次再见！"

        response = prefix + body

        return AgentResult(
            success=True,
            action="generate_reply",
            data={
                "response": response,
                "tone": tone,
                "customer_name": customer_name,
                "template_used": bool(template),
                "char_count": len(response),
            },
            reasoning=f"生成{tone}语气回复，共 {len(response)} 字",
            confidence=0.85,
        )


def _build_complaint_response(level: str, compensation: list[str]) -> str:
    """构建客诉回复模板"""
    if level == "severe":
        return (
            "非常抱歉给您带来了极差的用餐体验！我们已安排店长为您亲自处理。"
            f"补偿方案：{'、'.join(compensation)}。"
            "我们将全面排查问题，确保不再发生。"
        )
    elif level == "moderate":
        return (
            "非常抱歉影响了您的用餐体验！"
            f"我们将为您提供以下补偿：{'、'.join(compensation)}。"
            "感谢您的反馈，我们会尽快改进。"
        )
    else:
        return f"很抱歉给您带来了不便！我们已为您准备：{'、'.join(compensation)}。感谢您的理解与支持。"
