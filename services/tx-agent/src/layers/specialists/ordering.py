"""点单服务 Agent — P1

职责：菜品推荐、套餐搭配、忌口提醒、加菜建议、客诉前置信号识别
适配模式：C（系统主导，Agent 辅助推荐）
"""
from __future__ import annotations

from .base_specialist import SpecialistAgent, SpecialistResult
from ..scene_session import SessionContext


class OrderingAgent(SpecialistAgent):
    agent_id = "ordering"
    agent_name = "点单服务 Agent"
    description = "菜品推荐、套餐搭配、忌口提醒、加菜upsell建议、客诉前置信号识别"
    priority = "P1"

    def get_supported_actions(self) -> list[str]:
        return [
            "recommend_dishes",
            "check_dietary",
            "suggest_combo",
            "suggest_upsell",
            "general_query",
        ]

    async def execute(
        self, action: str, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        if action == "recommend_dishes":
            return await self._recommend_dishes(params, context)
        elif action == "check_dietary":
            return await self._check_dietary(params, context)
        elif action == "suggest_combo":
            return await self._suggest_combo(params, context)
        elif action == "suggest_upsell":
            return await self._suggest_upsell(params, context)
        elif action == "general_query":
            return await self._general_query(params, context)
        return SpecialistResult(
            success=False, agent_id=self.agent_id, action=action,
            error=f"不支持的动作: {action}",
        )

    async def _recommend_dishes(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        # 查询会员偏好
        customer_id = params.get("customer_id")
        member_data = {}
        if customer_id:
            member = await self.call_tool(
                "query_member_profile", {"customer_id": customer_id}, context,
            )
            if member.success:
                member_data = member.data

        # 调用推荐工具
        result = await self.call_tool("recommend_dishes", {
            "customer_id": customer_id,
            "party_size": params.get("party_size"),
            "preferences": params.get("preferences", []),
        }, context)

        message = "为您推荐以下菜品"
        if self._router:
            prompt = f"顾客画像：{member_data}\n菜品数据：{result.data}\n请给出个性化推荐理由"
            suggestion = await self.llm_reason(prompt, context, max_tokens=400)
            if suggestion:
                message = suggestion

        return SpecialistResult(
            success=True, agent_id=self.agent_id, action="recommend_dishes",
            message=message, data=result.data, confidence=0.8,
        )

    async def _check_dietary(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        customer_id = params.get("customer_id")
        if customer_id:
            member = await self.call_tool(
                "query_member_profile", {"customer_id": customer_id}, context,
            )
            restrictions = member.data.get("dietary_restrictions", []) if member.success else []
            return SpecialistResult(
                success=True, agent_id=self.agent_id, action="check_dietary",
                message=f"忌口信息：{', '.join(restrictions) if restrictions else '无特殊忌口'}",
                data={"restrictions": restrictions}, confidence=0.9,
            )
        return SpecialistResult(
            success=True, agent_id=self.agent_id, action="check_dietary",
            message="未找到顾客忌口记录", data={"restrictions": []},
        )

    async def _suggest_combo(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        menu = await self.call_tool("query_menu", {
            "category": params.get("category", "combo"),
        }, context)
        return SpecialistResult(
            success=True, agent_id=self.agent_id, action="suggest_combo",
            message="推荐套餐搭配", data=menu.data, confidence=0.75,
        )

    async def _suggest_upsell(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        order_id = params.get("order_id")
        orders = await self.call_tool("query_orders", {
            "store_id": context.store_id or "",
        }, context)

        if self._router:
            suggestion = await self.llm_reason(
                f"当前订单：{orders.data}\n请推荐加菜建议（考虑人数和已点菜品）",
                context, max_tokens=300,
            )
            if suggestion:
                return SpecialistResult(
                    success=True, agent_id=self.agent_id, action="suggest_upsell",
                    message=suggestion, confidence=0.7,
                )
        return SpecialistResult(
            success=True, agent_id=self.agent_id, action="suggest_upsell",
            message="可考虑加点招牌甜品或时令蔬菜", confidence=0.5,
        )

    async def _general_query(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        menu = await self.call_tool("query_menu", params, context)
        return SpecialistResult(
            success=menu.success, agent_id=self.agent_id, action="general_query",
            message="菜单查询结果", data=menu.data,
        )
