"""迎宾预订 Agent — P0

职责：预订确认、改期改桌建议、顾客偏好识别、包厢/桌位推荐、到店提醒
适配模式：B（Agent + 状态机协同）
"""
from __future__ import annotations

from .base_specialist import SpecialistAgent, SpecialistResult
from ..scene_session import SessionContext


class ReceptionAgent(SpecialistAgent):
    agent_id = "reception"
    agent_name = "迎宾预订 Agent"
    description = "处理预订确认、改期改桌、VIP识别、包厢推荐、到店提醒"
    priority = "P0"

    def get_supported_actions(self) -> list[str]:
        return [
            "handle_reservation",
            "modify_reservation",
            "query_reservations",
            "recommend_table",
            "identify_vip",
            "send_arrival_reminder",
        ]

    async def execute(
        self, action: str, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        if action == "query_reservations":
            return await self._query_reservations(params, context)
        elif action == "handle_reservation":
            return await self._handle_reservation(params, context)
        elif action == "modify_reservation":
            return await self._modify_reservation(params, context)
        elif action == "recommend_table":
            return await self._recommend_table(params, context)
        elif action == "identify_vip":
            return await self._identify_vip(params, context)
        elif action == "send_arrival_reminder":
            return await self._send_arrival_reminder(params, context)
        return SpecialistResult(
            success=False, agent_id=self.agent_id, action=action,
            error=f"不支持的动作: {action}",
        )

    async def _query_reservations(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        tool_result = await self.call_tool(
            "query_reservations",
            {"date": params.get("date", "today"), "store_id": context.store_id},
            context,
        )
        if not tool_result.success:
            return SpecialistResult(
                success=False, agent_id=self.agent_id, action="query_reservations",
                error=tool_result.error,
            )

        # 如有 LLM，生成自然语言摘要
        message = "预订查询结果已返回"
        if self._router and tool_result.data:
            summary = await self.llm_reason(
                f"请简要总结今日预订情况：{tool_result.data}",
                context,
                task_type="quick_classification",
                max_tokens=300,
            )
            if summary:
                message = summary

        return SpecialistResult(
            success=True, agent_id=self.agent_id, action="query_reservations",
            message=message, data=tool_result.data, confidence=0.9,
        )

    async def _handle_reservation(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        # 先查会员信息
        phone = params.get("customer_phone", "")
        if phone:
            member_result = await self.call_tool(
                "query_member_profile", {"phone": phone}, context,
            )
            if member_result.success and member_result.data:
                params["member_info"] = member_result.data

        # 创建预订（需确认）
        tool_result = await self.call_tool("create_reservation", params, context)
        if tool_result.requires_confirmation:
            return SpecialistResult(
                success=True, agent_id=self.agent_id, action="handle_reservation",
                message=tool_result.confirmation_message or "预订需要确认",
                pending_tool_calls=[{
                    "tool": "create_reservation",
                    "params": params,
                }],
                confidence=0.85,
            )
        return SpecialistResult(
            success=tool_result.success, agent_id=self.agent_id,
            action="handle_reservation",
            message="预订已创建" if tool_result.success else "预订创建失败",
            data=tool_result.data,
        )

    async def _modify_reservation(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        tool_result = await self.call_tool("modify_reservation", params, context)
        if tool_result.requires_confirmation:
            return SpecialistResult(
                success=True, agent_id=self.agent_id, action="modify_reservation",
                message=tool_result.confirmation_message or "修改预订需要确认",
                pending_tool_calls=[{"tool": "modify_reservation", "params": params}],
            )
        return SpecialistResult(
            success=tool_result.success, agent_id=self.agent_id,
            action="modify_reservation", data=tool_result.data,
        )

    async def _recommend_table(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        # 查询桌台状态
        tables = await self.call_tool(
            "query_table_status", {"store_id": context.store_id or ""}, context,
        )
        party_size = params.get("party_size", 2)

        message = f"根据{party_size}人用餐，推荐以下桌位"
        if self._router and tables.data:
            suggestion = await self.llm_reason(
                f"门店桌台状态：{tables.data}\n请为{party_size}人用餐推荐最佳桌位",
                context, max_tokens=300,
            )
            if suggestion:
                message = suggestion

        return SpecialistResult(
            success=True, agent_id=self.agent_id, action="recommend_table",
            message=message, data=tables.data, confidence=0.8,
        )

    async def _identify_vip(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        phone = params.get("phone", "")
        member = await self.call_tool(
            "query_member_profile", {"phone": phone}, context,
        )
        is_vip = member.data.get("rfm_level", "S5") in ("S1", "S2") if member.success else False
        return SpecialistResult(
            success=True, agent_id=self.agent_id, action="identify_vip",
            message="VIP 客户" if is_vip else "普通客户",
            data={"is_vip": is_vip, "member": member.data},
            confidence=0.95,
        )

    async def _send_arrival_reminder(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        tool_result = await self.call_tool("send_notification", {
            "target_type": "customer",
            "target_id": params.get("customer_id", ""),
            "template": "arrival_reminder",
            "params": params,
        }, context)
        if tool_result.requires_confirmation:
            return SpecialistResult(
                success=True, agent_id=self.agent_id, action="send_arrival_reminder",
                message="到店提醒需要确认发送",
                pending_tool_calls=[{"tool": "send_notification", "params": params}],
            )
        return SpecialistResult(
            success=tool_result.success, agent_id=self.agent_id,
            action="send_arrival_reminder", data=tool_result.data,
        )
