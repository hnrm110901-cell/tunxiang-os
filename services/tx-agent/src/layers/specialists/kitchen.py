"""厨房协同 Agent — P1

职责：堵塞工位识别、出菜超时预警、催菜影响判断、缺货联动停售建议、出菜节奏建议
适配模式：C（系统主导出品流转，Agent 辅助优化）
"""
from __future__ import annotations

from .base_specialist import SpecialistAgent, SpecialistResult
from ..scene_session import SessionContext


class KitchenAgent(SpecialistAgent):
    agent_id = "kitchen"
    agent_name = "厨房协同 Agent"
    description = "堵塞工位识别、出菜超时预警、催菜判断、缺货停售建议、出菜节奏优化"
    priority = "P1"

    def get_supported_actions(self) -> list[str]:
        return [
            "kitchen_status",
            "manage_availability",
            "detect_bottleneck",
            "expedite_order",
            "suggest_pace",
        ]

    async def execute(
        self, action: str, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        if action == "kitchen_status":
            return await self._kitchen_status(params, context)
        elif action == "manage_availability":
            return await self._manage_availability(params, context)
        elif action == "detect_bottleneck":
            return await self._detect_bottleneck(params, context)
        elif action == "expedite_order":
            return await self._expedite_order(params, context)
        elif action == "suggest_pace":
            return await self._suggest_pace(params, context)
        return SpecialistResult(
            success=False, agent_id=self.agent_id, action=action,
            error=f"不支持的动作: {action}",
        )

    async def _kitchen_status(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        result = await self.call_tool(
            "query_kitchen_status", {"store_id": context.store_id or ""}, context,
        )
        message = "厨房出品状态"
        if self._router and result.data:
            analysis = await self.llm_reason(
                f"厨房状态：{result.data}\n请分析当前厨房运行状况，指出瓶颈和超时风险",
                context, task_type="quick_classification", max_tokens=400,
            )
            if analysis:
                message = analysis
        return SpecialistResult(
            success=result.success, agent_id=self.agent_id, action="kitchen_status",
            message=message, data=result.data, confidence=0.85,
        )

    async def _manage_availability(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        result = await self.call_tool("set_dish_availability", params, context)
        if result.requires_confirmation:
            return SpecialistResult(
                success=True, agent_id=self.agent_id, action="manage_availability",
                message=result.confirmation_message or "菜品停售/恢复需要确认",
                pending_tool_calls=[{"tool": "set_dish_availability", "params": params}],
            )
        return SpecialistResult(
            success=result.success, agent_id=self.agent_id,
            action="manage_availability", data=result.data,
        )

    async def _detect_bottleneck(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        status = await self.call_tool(
            "query_kitchen_status", {"store_id": context.store_id or ""}, context,
        )
        if self._router and status.data:
            analysis = await self.llm_reason(
                f"厨房状态：{status.data}\n请识别拥塞工位和可能的出品延迟",
                context, max_tokens=400,
            )
            if analysis:
                return SpecialistResult(
                    success=True, agent_id=self.agent_id, action="detect_bottleneck",
                    message=analysis, data=status.data, confidence=0.7,
                )
        return SpecialistResult(
            success=True, agent_id=self.agent_id, action="detect_bottleneck",
            message="暂未检测到明显拥塞", data=status.data, confidence=0.5,
        )

    async def _expedite_order(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        result = await self.call_tool("expedite_dish", {
            "order_item_id": params.get("order_item_id", ""),
            "reason": params.get("reason", "客户催单"),
        }, context)
        return SpecialistResult(
            success=result.success, agent_id=self.agent_id, action="expedite_order",
            message="已催菜" if result.success else "催菜失败",
            data=result.data,
        )

    async def _suggest_pace(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        status = await self.call_tool(
            "query_kitchen_status", {"store_id": context.store_id or ""}, context,
        )
        orders = await self.call_tool("query_orders", {
            "store_id": context.store_id or "", "status": "preparing",
        }, context)

        if self._router:
            suggestion = await self.llm_reason(
                f"厨房状态：{status.data}\n在制订单：{orders.data}\n"
                "请建议出菜节奏调整方案",
                context, max_tokens=400,
            )
            if suggestion:
                return SpecialistResult(
                    success=True, agent_id=self.agent_id, action="suggest_pace",
                    message=suggestion, confidence=0.7,
                )
        return SpecialistResult(
            success=True, agent_id=self.agent_id, action="suggest_pace",
            message="建议维持当前出菜节奏", confidence=0.5,
        )
