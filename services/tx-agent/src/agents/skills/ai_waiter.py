"""AI服务员 Agent — P1 | 云端

能力：智能菜品推荐、回答菜品问题、加购建议
根据顾客人数/预算/偏好/历史消费进行智能推荐。
"""

from typing import Any

import structlog

from ..base import AgentResult, SkillAgent

logger = structlog.get_logger()


# ── 菜品分类 ────────────────────────────────────────────
CATEGORY_ORDER = ["凉菜", "热菜", "海鲜", "汤品", "主食", "酒水", "甜品"]

# 每人建议菜品数（按人数区间）
DISH_PER_PERSON = {
    (1, 2): 3,
    (3, 4): 4,
    (5, 6): 6,
    (7, 8): 8,
    (9, 99): 10,
}

# 分类配比建议（按比例）
CATEGORY_RATIO = {
    "凉菜": 0.15,
    "热菜": 0.40,
    "海鲜": 0.15,
    "汤品": 0.10,
    "主食": 0.10,
    "酒水": 0.05,
    "甜品": 0.05,
}

# 常见问题知识库（兜底）
FAQ_KNOWLEDGE = {
    "辣": "我们的辣度分为微辣、中辣、特辣三个等级，可以根据您的口味调整。",
    "过敏": "请告诉我您的过敏原，我们会为您标注含该过敏原的菜品。常见过敏原包括：花生、海鲜、麸质、乳制品等。",
    "忌口": "我们支持标注忌口信息，常见忌口包括：不吃辣、不吃葱姜蒜、素食、清真等。请告诉我您的需求。",
    "招牌": "我们的招牌菜包括：剁椒鱼头、红烧肉、清蒸鲈鱼，都是顾客好评率最高的菜品。",
    "素食": "我们有多款素食菜品：清炒时蔬、凉拌黄瓜、麻婆豆腐（素版）、素什锦等。",
    "儿童": "我们有适合儿童的菜品：番茄炒蛋、清蒸鱼、蛋炒饭，口味清淡少油少盐。",
}

# 经典搭配规则
PAIRING_RULES: list[dict[str, Any]] = [
    {"trigger": "鱼头", "suggest": "米饭", "reason": "鱼头汤汁拌饭是绝配"},
    {"trigger": "鱼", "suggest": "米饭", "reason": "鲜鱼配米饭更美味"},
    {"trigger": "烤", "suggest": "啤酒", "reason": "烧烤配啤酒是经典组合"},
    {"trigger": "火锅", "suggest": "酸梅汤", "reason": "火锅配酸梅汤解腻开胃"},
    {"trigger": "辣", "suggest": "凉茶", "reason": "辣菜配凉茶去火"},
    {"trigger": "海鲜", "suggest": "白酒", "reason": "海鲜配白酒提鲜"},
    {"trigger": "红烧肉", "suggest": "梅菜扣肉", "reason": "经典湘菜双拼"},
    {"trigger": "龙虾", "suggest": "啤酒", "reason": "小龙虾配啤酒，夏日标配"},
]


class AIWaiterAgent(SkillAgent):
    """AI服务员 Agent

    智能推荐菜品、回答菜品问题、提供加购建议。
    """

    agent_id = "ai_waiter"
    agent_name = "AI服务员"
    description = "智能菜品推荐（按人数/预算/偏好）、回答菜品问题、加购建议"
    priority = "P1"
    run_location = "cloud"

    # Sprint D1 / PR H 批次 2：点菜推荐影响整桌出餐节奏（体验）+ 毛利最大化（推高毛利菜）
    constraint_scope = {"margin", "experience"}

    def get_supported_actions(self) -> list[str]:
        return ["suggest_dishes", "answer_question", "upsell_suggestion"]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "suggest_dishes": self._suggest_dishes,
            "answer_question": self._answer_question,
            "upsell_suggestion": self._upsell_suggestion,
        }
        handler = dispatch.get(action)
        if not handler:
            return AgentResult(success=False, action=action, error=f"Unsupported: {action}")
        return await handler(params)

    # ── Action: 智能推荐 ──────────────────────────────────
    async def _suggest_dishes(self, params: dict) -> AgentResult:
        """根据人数/预算/偏好/历史推荐菜品组合

        params:
          - guest_count: 就餐人数
          - budget_fen: 总预算（分）, 可选
          - preferences: 偏好列表 (如 ["不辣", "海鲜"])
          - history_dishes: 历史点过的菜品ID列表
          - available_dishes: 当前可用菜品列表
        """
        guest_count: int = params.get("guest_count", 2)
        budget_fen: int = params.get("budget_fen", 0)
        preferences: list[str] = params.get("preferences", [])
        history_dishes: list[str] = params.get("history_dishes", [])
        available_dishes: list[dict] = params.get("available_dishes", [])

        if not available_dishes:
            return AgentResult(
                success=False,
                action="suggest_dishes",
                error="缺少 available_dishes 参数",
            )

        # 计算推荐菜品数量
        target_count = 3
        for (lo, hi), count in DISH_PER_PERSON.items():
            if lo <= guest_count <= hi:
                target_count = count
                break

        # 过滤偏好
        filtered = self._filter_by_preferences(available_dishes, preferences)

        # 按分类分组
        by_category: dict[str, list[dict]] = {}
        for dish in filtered:
            cat = dish.get("category", "热菜")
            by_category.setdefault(cat, []).append(dish)

        # 按配比选择菜品
        selected: list[dict] = []
        for cat in CATEGORY_ORDER:
            ratio = CATEGORY_RATIO.get(cat, 0.1)
            cat_count = max(1, round(target_count * ratio))
            cat_dishes = by_category.get(cat, [])
            # 按人气排序
            cat_dishes.sort(key=lambda d: d.get("popularity_score", 0), reverse=True)
            # 优先选没点过的
            for dish in cat_dishes:
                if len(selected) >= target_count:
                    break
                if dish.get("dish_id") not in history_dishes:
                    selected.append(dish)
                    cat_count -= 1
                    if cat_count <= 0:
                        break

        # 如果还没选够，补充热门菜
        if len(selected) < target_count:
            remaining = [d for d in filtered if d not in selected]
            remaining.sort(key=lambda d: d.get("popularity_score", 0), reverse=True)
            for dish in remaining:
                if len(selected) >= target_count:
                    break
                selected.append(dish)

        # 预算检查
        total_fen = sum(d.get("price_fen", 0) for d in selected)
        budget_ok = budget_fen <= 0 or total_fen <= budget_fen

        if not budget_ok and budget_fen > 0:
            # 替换贵的菜
            selected.sort(key=lambda d: d.get("price_fen", 0), reverse=True)
            while total_fen > budget_fen and len(selected) > 1:
                removed = selected.pop(0)
                total_fen -= removed.get("price_fen", 0)

        suggestion = {
            "guest_count": guest_count,
            "recommended_dishes": [
                {
                    "dish_id": d.get("dish_id", ""),
                    "name": d.get("name", ""),
                    "category": d.get("category", ""),
                    "price_fen": d.get("price_fen", 0),
                    "reason": self._get_recommend_reason(d, preferences, history_dishes),
                }
                for d in selected
            ],
            "total_fen": sum(d.get("price_fen", 0) for d in selected),
            "dish_count": len(selected),
            "budget_ok": budget_ok,
        }
        suggestion["total_yuan"] = round(suggestion["total_fen"] / 100, 2)

        logger.info("ai_waiter_suggest", tenant_id=self.tenant_id, guest_count=guest_count, dish_count=len(selected))

        return AgentResult(
            success=True,
            action="suggest_dishes",
            data=suggestion,
            reasoning=f"为 {guest_count} 人推荐 {len(selected)} 道菜，合计 ¥{suggestion['total_yuan']}",
            confidence=0.85,
        )

    def _filter_by_preferences(self, dishes: list[dict], preferences: list[str]) -> list[dict]:
        """根据偏好过滤菜品"""
        if not preferences:
            return dishes

        filtered = []
        for dish in dishes:
            tags = dish.get("tags", [])
            name = dish.get("name", "")
            skip = False
            for pref in preferences:
                if pref == "不辣" and ("辣" in name or "辣" in " ".join(tags)):
                    skip = True
                    break
                if pref == "素食" and dish.get("category") not in ["凉菜", "主食", "甜品"]:
                    if "素" not in name and "蔬" not in name and "豆腐" not in name:
                        skip = True
                        break
            if not skip:
                filtered.append(dish)

        return filtered if filtered else dishes  # 如果过滤后为空，返回全部

    def _get_recommend_reason(self, dish: dict, preferences: list[str], history: list[str]) -> str:
        """生成推荐理由"""
        reasons = []
        if dish.get("popularity_score", 0) >= 85:
            reasons.append("人气菜品")
        if dish.get("dish_id") in history:
            reasons.append("您之前点过")
        if dish.get("margin_rate", 0) >= 0.6:
            reasons.append("性价比高")
        if not reasons:
            reasons.append("主厨推荐")
        return "、".join(reasons)

    # ── Action: 回答问题 ──────────────────────────────────
    async def _answer_question(self, params: dict) -> AgentResult:
        """回答顾客关于菜品的问题

        params:
          - question: 问题文本
          - dish_context: 可选，关联菜品信息
        """
        question: str = params.get("question", "").strip()
        dish_context: dict = params.get("dish_context", {})

        if not question:
            return AgentResult(
                success=False,
                action="answer_question",
                error="缺少 question 参数",
            )

        # 先匹配 FAQ
        answer = self._match_faq(question)

        # 如果有菜品上下文，补充具体信息
        if dish_context:
            dish_name = dish_context.get("name", "")
            if "辣" in question and dish_context.get("spicy_level"):
                answer = f"{dish_name}的辣度为{dish_context['spicy_level']}级，{answer}"
            if "过敏" in question and dish_context.get("allergens"):
                allergens = "、".join(dish_context["allergens"])
                answer = f"{dish_name}含有以下过敏原：{allergens}。{answer}"
            if "热量" in question and dish_context.get("calories"):
                answer = f"{dish_name}的热量约为 {dish_context['calories']} 千卡。"

        if not answer:
            answer = "抱歉，我暂时无法回答这个问题，让我为您叫一下服务员。"

        logger.info("ai_waiter_answer", tenant_id=self.tenant_id, question=question)

        return AgentResult(
            success=True,
            action="answer_question",
            data={
                "question": question,
                "answer": answer,
                "source": "faq" if answer != "抱歉，我暂时无法回答这个问题，让我为您叫一下服务员。" else "fallback",
            },
            reasoning=f"回答顾客问题: '{question}'",
            confidence=0.8 if answer else 0.3,
        )

    def _match_faq(self, question: str) -> str:
        """匹配常见问题"""
        for keyword, answer in FAQ_KNOWLEDGE.items():
            if keyword in question:
                return answer
        return ""

    # ── Action: 加购建议 ──────────────────────────────────
    async def _upsell_suggestion(self, params: dict) -> AgentResult:
        """根据当前已点菜品给出加购建议

        params:
          - current_order: 当前已点菜品列表
          - available_dishes: 可用菜品列表（可选）
        """
        current_order: list[dict] = params.get("current_order", [])

        if not current_order:
            return AgentResult(
                success=False,
                action="upsell_suggestion",
                error="当前订单为空，无法给出加购建议",
            )

        suggestions: list[dict] = []
        order_names = [item.get("name", item.get("dish_name", "")) for item in current_order]
        order_text = " ".join(order_names)

        # 基于搭配规则推荐
        already_suggested: set[str] = set()
        for rule in PAIRING_RULES:
            trigger = rule["trigger"]
            if trigger in order_text and rule["suggest"] not in order_text:
                if rule["suggest"] not in already_suggested:
                    suggestions.append(
                        {
                            "dish_name": rule["suggest"],
                            "reason": rule["reason"],
                            "type": "pairing",
                        }
                    )
                    already_suggested.add(rule["suggest"])

        # 检查是否缺少主食
        has_staple = any(item.get("category") == "主食" for item in current_order)
        if not has_staple and len(current_order) >= 2:
            suggestions.append(
                {
                    "dish_name": "米饭",
                    "reason": "您还没有点主食，建议搭配米饭",
                    "type": "category_fill",
                }
            )

        # 检查是否缺少饮品
        has_drink = any(item.get("category") == "酒水" for item in current_order)
        if not has_drink and len(current_order) >= 3:
            suggestions.append(
                {
                    "dish_name": "饮品",
                    "reason": "点了这么多好菜，来点饮品搭配吧",
                    "type": "category_fill",
                }
            )

        logger.info("ai_waiter_upsell", tenant_id=self.tenant_id, suggestion_count=len(suggestions))

        return AgentResult(
            success=True,
            action="upsell_suggestion",
            data={
                "current_order_count": len(current_order),
                "suggestions": suggestions,
                "suggestion_count": len(suggestions),
            },
            reasoning=f"基于 {len(current_order)} 道已点菜品给出 {len(suggestions)} 条加购建议",
            confidence=0.75,
        )
