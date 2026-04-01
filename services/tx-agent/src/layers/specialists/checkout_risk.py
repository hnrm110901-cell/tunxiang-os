"""结账风控 Agent — P1

职责：结账异常识别、大额折扣解释、退款风险提示、客诉补偿建议、发票异常提醒
适配模式：C（系统主导支付，Agent 辅助风控提示）
"""
from __future__ import annotations

from .base_specialist import SpecialistAgent, SpecialistResult
from ..scene_session import SessionContext


class CheckoutRiskAgent(SpecialistAgent):
    agent_id = "checkout_risk"
    agent_name = "结账风控 Agent"
    description = "结账异常识别、大额折扣解释、退款风险提示、客诉补偿建议、发票异常"
    priority = "P1"

    def get_supported_actions(self) -> list[str]:
        return [
            "checkout_query",
            "risk_check",
            "explain_discount",
            "suggest_compensation",
        ]

    async def execute(
        self, action: str, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        if action == "checkout_query":
            return await self._checkout_query(params, context)
        elif action == "risk_check":
            return await self._risk_check(params, context)
        elif action == "explain_discount":
            return await self._explain_discount(params, context)
        elif action == "suggest_compensation":
            return await self._suggest_compensation(params, context)
        return SpecialistResult(
            success=False, agent_id=self.agent_id, action=action,
            error=f"不支持的动作: {action}",
        )

    async def _checkout_query(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        order_id = params.get("order_id", "")
        if order_id:
            payment = await self.call_tool(
                "query_payment_status", {"order_id": order_id}, context,
            )
            return SpecialistResult(
                success=payment.success, agent_id=self.agent_id, action="checkout_query",
                message="支付状态查询结果", data=payment.data, confidence=0.9,
            )
        orders = await self.call_tool("query_orders", {
            "store_id": context.store_id or "",
        }, context)
        return SpecialistResult(
            success=orders.success, agent_id=self.agent_id, action="checkout_query",
            message="订单列表", data=orders.data,
        )

    async def _risk_check(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        orders = await self.call_tool("query_orders", {
            "store_id": context.store_id or "", "status": "paying",
        }, context)

        if self._router and orders.data:
            analysis = await self.llm_reason(
                f"待结账订单：{orders.data}\n"
                "请识别异常折扣、大额免单、可疑挂账等风险信号",
                context, max_tokens=500,
            )
            if analysis:
                return SpecialistResult(
                    success=True, agent_id=self.agent_id, action="risk_check",
                    message=analysis, data=orders.data,
                    reasoning="基于订单数据的风控分析", confidence=0.7,
                )

        return SpecialistResult(
            success=True, agent_id=self.agent_id, action="risk_check",
            message="当前待结账订单未发现明显风险", confidence=0.5,
        )

    async def _explain_discount(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        order_id = params.get("order_id", "")
        order = await self.call_tool("query_orders", {
            "store_id": context.store_id or "",
        }, context)
        member = None
        customer_id = params.get("customer_id")
        if customer_id:
            member = await self.call_tool(
                "query_member_profile", {"customer_id": customer_id}, context,
            )

        if self._router:
            explanation = await self.llm_reason(
                f"订单信息：{order.data}\n"
                f"会员信息：{member.data if member else '无'}\n"
                "请解释此订单的折扣构成和合理性",
                context, max_tokens=400,
            )
            if explanation:
                return SpecialistResult(
                    success=True, agent_id=self.agent_id, action="explain_discount",
                    message=explanation, confidence=0.8,
                )

        return SpecialistResult(
            success=True, agent_id=self.agent_id, action="explain_discount",
            message="折扣明细需要更多订单数据", confidence=0.4,
        )

    async def _suggest_compensation(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        reason = params.get("reason", "")
        customer_id = params.get("customer_id")
        member_data = {}
        if customer_id:
            member = await self.call_tool(
                "query_member_profile", {"customer_id": customer_id}, context,
            )
            if member.success:
                member_data = member.data

        if self._router:
            suggestion = await self.llm_reason(
                f"客诉原因：{reason}\n会员画像：{member_data}\n"
                "请建议合理的补偿方案（券、折扣、赠送等），需考虑毛利底线",
                context, max_tokens=400,
            )
            if suggestion:
                return SpecialistResult(
                    success=True, agent_id=self.agent_id, action="suggest_compensation",
                    message=suggestion, confidence=0.7,
                    data={"reason": reason, "member": member_data},
                )

        return SpecialistResult(
            success=True, agent_id=self.agent_id, action="suggest_compensation",
            message="建议赠送一份小甜品或发放20元代金券作为补偿",
            confidence=0.5,
        )
