"""个性化Agent — 千人千面推荐理由生成 + 问候语 + Banner选择

职责：
- 为推荐菜品生成个性化理由（"因为您喜欢辣，这道口味虾是绝配"）
- 根据用户画像生成个性化问候语
- 选择最佳Banner展示给特定用户群
- 批量模式：一次为Top10菜品生成理由，缓存Redis 24h

成本：Haiku ¥0.002/次，日5万次=¥100/日
"""

from typing import Any

import structlog

from ..base import AgentResult, SkillAgent

logger = structlog.get_logger()


class PersonalizationAgent(SkillAgent):
    agent_id = "personalization"
    agent_name = "千人千面个性化"
    description = "推荐理由生成、个性化问候、Banner定向选择"
    priority = "P1"
    run_location = "cloud"
    agent_level = 3  # 完全自主（生成文案无需审批）

    # Sprint D1 / PR 批次 3：个性化推荐倾向推高毛利菜品，需 margin 校验避免推销滞销低毛利品
    constraint_scope = {"margin"}

    def get_supported_actions(self) -> list[str]:
        return [
            "generate_dish_reason",
            "generate_batch_reasons",
            "generate_greeting",
            "select_banner",
            "generate_reorder_prompt",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "generate_dish_reason": self._generate_dish_reason,
            "generate_batch_reasons": self._generate_batch_reasons,
            "generate_greeting": self._generate_greeting,
            "select_banner": self._select_banner,
            "generate_reorder_prompt": self._generate_reorder_prompt,
        }
        handler = dispatch.get(action)
        if not handler:
            return AgentResult(success=False, action=action, error=f"Unsupported: {action}")
        return await handler(params)

    async def _generate_dish_reason(self, params: dict) -> AgentResult:
        """为单道菜品生成个性化推荐理由"""
        dish_name = params.get("dish_name", "")
        user_prefs = params.get("user_prefs", {})
        reason_type = params.get("reason_type", "history")

        # 尝试云端生成（Haiku，最低成本）
        ai_reason = None
        if self._router:
            spicy = user_prefs.get("spicy", 0)
            favorites = user_prefs.get("top_dishes", [])
            try:
                prompt = (
                    f"用户偏好：辣度{spicy}/3，常点{','.join(favorites[:3]) if favorites else '未知'}。"
                    f"为菜品'{dish_name}'生成10字以内的推荐理由，要自然亲切。"
                )
                resp = await self._router.complete(prompt=prompt, max_tokens=30, task_type="quick_classification")
                if resp:
                    ai_reason = resp.strip().strip('"').strip("'")
            except (ValueError, RuntimeError, ConnectionError, TimeoutError):
                pass

        # 降级：规则生成
        if not ai_reason:
            fallback_map = {
                "history": f"您常点的{dish_name}",
                "hot": "本时段热销",
                "association": "和您的菜搭配更好",
                "margin": "主厨推荐",
            }
            ai_reason = fallback_map.get(reason_type, "推荐尝试")

        return AgentResult(
            success=True,
            action="generate_dish_reason",
            data={"dish_name": dish_name, "reason": ai_reason, "source": "ai" if self._router else "rule"},
            reasoning=f"为{dish_name}生成理由: {ai_reason}",
            confidence=0.85 if self._router else 0.6,
            inference_layer="cloud" if self._router else "edge",
        )

    async def _generate_batch_reasons(self, params: dict) -> AgentResult:
        """批量生成Top N菜品推荐理由"""
        dishes = params.get("dishes", [])
        user_prefs = params.get("user_prefs", {})

        if not dishes:
            return AgentResult(success=True, action="generate_batch_reasons", data={"reasons": {}})

        reasons: dict[str, str] = {}

        if self._router:
            # 一次prompt批量生成，降低API调用次数
            dish_names = [d.get("name", "") for d in dishes[:10]]
            spicy = user_prefs.get("spicy", 0)
            favorites = ", ".join(user_prefs.get("top_dishes", [])[:3]) or "未知"

            try:
                prompt = (
                    f"用户偏好：辣度{spicy}/3，常点{favorites}。\n"
                    f"请为以下菜品各生成一句10字以内的推荐理由（自然亲切），格式为'菜品名:理由'，每行一个：\n"
                    + "\n".join(dish_names)
                )
                resp = await self._router.complete(prompt=prompt, max_tokens=200, task_type="quick_classification")
                if resp:
                    for line in resp.strip().split("\n"):
                        if ":" in line or "：" in line:
                            parts = line.replace("：", ":").split(":", 1)
                            if len(parts) == 2:
                                name = parts[0].strip()
                                reason = parts[1].strip().strip('"').strip("'")
                                reasons[name] = reason
            except (ValueError, RuntimeError, ConnectionError, TimeoutError):
                pass

        # 补充未生成的用规则
        for dish in dishes:
            name = dish.get("name", "")
            if name not in reasons:
                reasons[name] = f"推荐尝试{name}"

        return AgentResult(
            success=True,
            action="generate_batch_reasons",
            data={"reasons": reasons, "count": len(reasons), "source": "ai" if self._router else "rule"},
            reasoning=f"批量生成{len(reasons)}条推荐理由",
            confidence=0.8,
            inference_layer="cloud" if self._router else "edge",
        )

    async def _generate_greeting(self, params: dict) -> AgentResult:
        """生成个性化问候语"""
        nickname = params.get("nickname", "美食家")
        segment = params.get("segment", "S3")
        last_dish = params.get("last_dish", "")
        days_since = params.get("days_since_last_visit", 0)

        if self._router and last_dish:
            try:
                prompt = (
                    f"顾客'{nickname}'，{days_since}天前来过，上次点了'{last_dish}'。"
                    f"会员等级{segment}。生成一句15字以内的亲切问候（不用'您好'开头）。"
                )
                resp = await self._router.complete(prompt=prompt, max_tokens=40, task_type="quick_classification")
                if resp:
                    return AgentResult(
                        success=True,
                        action="generate_greeting",
                        data={"greeting": resp.strip(), "source": "ai"},
                        reasoning=f"AI问候: {resp.strip()}",
                        confidence=0.9,
                        inference_layer="cloud",
                    )
            except (ValueError, RuntimeError, ConnectionError, TimeoutError):
                pass

        # 降级
        hour = __import__("datetime").datetime.now().hour
        time_g = "早上好" if hour < 11 else "中午好" if hour < 14 else "下午好" if hour < 18 else "晚上好"
        greeting = f"{time_g}，{nickname}！" + (f"上次的{last_dish}还满意吗？" if last_dish else "欢迎光临！")

        return AgentResult(
            success=True,
            action="generate_greeting",
            data={"greeting": greeting, "source": "rule"},
            reasoning=f"规则问候: {greeting}",
            confidence=0.6,
            inference_layer="edge",
        )

    async def _select_banner(self, params: dict) -> AgentResult:
        """为用户选择最佳Banner"""
        segment = params.get("segment", "S3")
        available_banners = params.get("banners", [])

        if not available_banners:
            return AgentResult(success=True, action="select_banner", data={"selected": None})

        # 匹配目标分群的Banner
        matched = [b for b in available_banners if not b.get("target_segment") or b.get("target_segment") == segment]
        if not matched:
            matched = available_banners  # 无定向Banner则展示全部

        return AgentResult(
            success=True,
            action="select_banner",
            data={"selected": matched[:3], "segment": segment, "total_available": len(available_banners)},
            reasoning=f"为{segment}用户选择{len(matched[:3])}个Banner",
            confidence=0.9,
            inference_layer="edge",
        )

    async def _generate_reorder_prompt(self, params: dict) -> AgentResult:
        """生成复购提示文案"""
        nickname = params.get("nickname", "")
        last_dishes = params.get("last_dishes", [])
        days_ago = params.get("days_ago", 0)
        store_name = params.get("store_name", "")

        if self._router and last_dishes:
            try:
                prompt = (
                    f"顾客'{nickname}'，{days_ago}天前在'{store_name}'点了{','.join(last_dishes[:3])}。"
                    f"生成一句20字以内的复购提醒（不要用'亲'字，要自然）。"
                )
                resp = await self._router.complete(prompt=prompt, max_tokens=40, task_type="quick_classification")
                if resp:
                    return AgentResult(
                        success=True,
                        action="generate_reorder_prompt",
                        data={"prompt": resp.strip(), "source": "ai"},
                        confidence=0.85,
                        inference_layer="cloud",
                    )
            except (ValueError, RuntimeError, ConnectionError, TimeoutError):
                pass

        # 降级
        top_dish = last_dishes[0] if last_dishes else "美食"
        prompt_text = f"{days_ago}天前在{store_name}点了{top_dish}，再来一单？"

        return AgentResult(
            success=True,
            action="generate_reorder_prompt",
            data={"prompt": prompt_text, "source": "rule"},
            confidence=0.6,
            inference_layer="edge",
        )
