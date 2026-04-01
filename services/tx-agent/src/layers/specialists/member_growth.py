"""会员增长 Agent — P1

职责：会员识别、券推荐、沉睡唤醒、复购策略、人群分层与活动建议
适配模式：B（会员识别）+ A（营销触达）
"""
from __future__ import annotations

from .base_specialist import SpecialistAgent, SpecialistResult
from ..scene_session import SessionContext


class MemberGrowthAgent(SpecialistAgent):
    agent_id = "member_growth"
    agent_name = "会员增长 Agent"
    description = "会员识别、券推荐、沉睡唤醒、复购策略、人群分层与营销触达编排"
    priority = "P1"

    def get_supported_actions(self) -> list[str]:
        return [
            "member_service",
            "member_campaign",
            "segment_analysis",
            "dormant_recall",
            "coupon_recommend",
        ]

    async def execute(
        self, action: str, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        if action == "member_service":
            return await self._member_service(params, context)
        elif action == "member_campaign":
            return await self._member_campaign(params, context)
        elif action == "segment_analysis":
            return await self._segment_analysis(params, context)
        elif action == "dormant_recall":
            return await self._dormant_recall(params, context)
        elif action == "coupon_recommend":
            return await self._coupon_recommend(params, context)
        return SpecialistResult(
            success=False, agent_id=self.agent_id, action=action,
            error=f"不支持的动作: {action}",
        )

    async def _member_service(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        phone = params.get("phone", "")
        customer_id = params.get("customer_id", "")
        result = await self.call_tool("query_member_profile", {
            "phone": phone, "customer_id": customer_id,
        }, context)

        message = "会员信息查询结果"
        if self._router and result.data:
            summary = await self.llm_reason(
                f"会员画像：{result.data}\n请生成简要会员摘要，包括价值等级和推荐服务策略",
                context, task_type="quick_classification", max_tokens=300,
            )
            if summary:
                message = summary

        return SpecialistResult(
            success=result.success, agent_id=self.agent_id, action="member_service",
            message=message, data=result.data, confidence=0.9,
        )

    async def _member_campaign(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        segments = await self.call_tool("query_member_segments", {
            "store_id": context.store_id,
        }, context)

        if self._router:
            strategy = await self.llm_reason(
                f"会员分群数据：{segments.data}\n"
                "请设计一套营销触达方案，包括目标人群、优惠力度、触达渠道、预期ROI",
                context, task_type="complex_reasoning", max_tokens=800,
            )
            if strategy:
                return SpecialistResult(
                    success=True, agent_id=self.agent_id, action="member_campaign",
                    message=strategy, data=segments.data,
                    reasoning="基于会员分群数据的LLM营销策略生成",
                    confidence=0.75,
                )

        return SpecialistResult(
            success=True, agent_id=self.agent_id, action="member_campaign",
            message="营销活动建议需要更多会员数据支持",
            data=segments.data, confidence=0.4,
        )

    async def _segment_analysis(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        result = await self.call_tool("query_member_segments", {
            "segment_type": params.get("segment_type"),
            "store_id": context.store_id,
        }, context)
        return SpecialistResult(
            success=result.success, agent_id=self.agent_id, action="segment_analysis",
            message="会员分群分析", data=result.data, confidence=0.85,
        )

    async def _dormant_recall(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        segments = await self.call_tool("query_member_segments", {
            "segment_type": "dormant", "store_id": context.store_id,
        }, context)

        if self._router and segments.data:
            strategy = await self.llm_reason(
                f"沉睡会员数据：{segments.data}\n"
                "请设计召回方案：哪些人优先召回、用什么优惠、通过什么渠道",
                context, max_tokens=600,
            )
            if strategy:
                return SpecialistResult(
                    success=True, agent_id=self.agent_id, action="dormant_recall",
                    message=strategy, confidence=0.7,
                )

        return SpecialistResult(
            success=True, agent_id=self.agent_id, action="dormant_recall",
            message="建议对30天未到店的会员发送专属回馈券",
            confidence=0.5,
        )

    async def _coupon_recommend(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        customer_id = params.get("customer_id", "")
        member = await self.call_tool(
            "query_member_profile", {"customer_id": customer_id}, context,
        )

        if self._router and member.data:
            recommendation = await self.llm_reason(
                f"会员画像：{member.data}\n请推荐最适合此会员的优惠券类型和面额",
                context, max_tokens=300,
            )
            if recommendation:
                return SpecialistResult(
                    success=True, agent_id=self.agent_id, action="coupon_recommend",
                    message=recommendation, data=member.data, confidence=0.75,
                )

        return SpecialistResult(
            success=True, agent_id=self.agent_id, action="coupon_recommend",
            message="推荐发放满100减20通用券", data=member.data, confidence=0.5,
        )
