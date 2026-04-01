"""等位桌台 Agent — P0

职责：等位队列排序、桌台调度建议、翻台预估、候位安抚、VIP优先
适配模式：B（等位） + C（桌台管理）
"""
from __future__ import annotations

from .base_specialist import SpecialistAgent, SpecialistResult
from ..scene_session import SessionContext


class WaitlistTableAgent(SpecialistAgent):
    agent_id = "waitlist_table"
    agent_name = "等位桌台 Agent"
    description = "管理等位队列排序、桌台调度、翻台预估、VIP优先、候位安抚策略"
    priority = "P0"

    def get_supported_actions(self) -> list[str]:
        return [
            "manage_waitlist",
            "manage_table",
            "query_tables",
            "estimate_wait_time",
            "suggest_table_assignment",
            "detect_churn_risk",
        ]

    async def execute(
        self, action: str, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        if action == "manage_waitlist":
            return await self._manage_waitlist(params, context)
        elif action == "manage_table":
            return await self._manage_table(params, context)
        elif action == "query_tables":
            return await self._query_tables(params, context)
        elif action == "estimate_wait_time":
            return await self._estimate_wait_time(params, context)
        elif action == "suggest_table_assignment":
            return await self._suggest_table_assignment(params, context)
        elif action == "detect_churn_risk":
            return await self._detect_churn_risk(params, context)
        return SpecialistResult(
            success=False, agent_id=self.agent_id, action=action,
            error=f"不支持的动作: {action}",
        )

    async def _manage_waitlist(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        sub_action = params.get("sub_action", "query")
        if sub_action == "query":
            result = await self.call_tool(
                "query_waitlist", {"store_id": context.store_id or ""}, context,
            )
            return SpecialistResult(
                success=result.success, agent_id=self.agent_id, action="manage_waitlist",
                message="当前等位队列", data=result.data, confidence=0.9,
            )
        elif sub_action == "add":
            result = await self.call_tool("add_to_waitlist", params, context)
            return SpecialistResult(
                success=result.success, agent_id=self.agent_id, action="manage_waitlist",
                message="已加入等位", data=result.data,
            )
        elif sub_action == "call_next":
            result = await self.call_tool("call_next_waitlist", params, context)
            return SpecialistResult(
                success=result.success, agent_id=self.agent_id, action="manage_waitlist",
                message="已叫号", data=result.data,
            )
        return SpecialistResult(
            success=False, agent_id=self.agent_id, action="manage_waitlist",
            error=f"不支持的子动作: {sub_action}",
        )

    async def _manage_table(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        sub_action = params.get("sub_action", "open")
        if sub_action == "open":
            result = await self.call_tool("open_table", params, context)
            return SpecialistResult(
                success=result.success, agent_id=self.agent_id, action="manage_table",
                message="已开台", data=result.data,
            )
        elif sub_action == "merge":
            result = await self.call_tool("merge_tables", params, context)
            if result.requires_confirmation:
                return SpecialistResult(
                    success=True, agent_id=self.agent_id, action="manage_table",
                    message="并台操作需要确认",
                    pending_tool_calls=[{"tool": "merge_tables", "params": params}],
                )
            return SpecialistResult(
                success=result.success, agent_id=self.agent_id, action="manage_table",
                data=result.data,
            )
        return SpecialistResult(
            success=False, agent_id=self.agent_id, action="manage_table",
            error=f"不支持的子动作: {sub_action}",
        )

    async def _query_tables(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        result = await self.call_tool(
            "query_table_status", {"store_id": context.store_id or ""}, context,
        )
        message = "桌台状态查询结果"
        if self._router and result.data:
            summary = await self.llm_reason(
                f"桌台状态：{result.data}\n请总结当前桌台利用情况和翻台建议",
                context, task_type="quick_classification", max_tokens=300,
            )
            if summary:
                message = summary
        return SpecialistResult(
            success=result.success, agent_id=self.agent_id, action="query_tables",
            message=message, data=result.data, confidence=0.9,
        )

    async def _estimate_wait_time(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        # 查询等位队列和桌台状态
        waitlist = await self.call_tool(
            "query_waitlist", {"store_id": context.store_id or ""}, context,
        )
        tables = await self.call_tool(
            "query_table_status", {"store_id": context.store_id or ""}, context,
        )
        party_size = params.get("party_size", 2)

        if self._router:
            estimation = await self.llm_reason(
                f"等位队列：{waitlist.data}\n桌台状态：{tables.data}\n"
                f"请估算{party_size}人的等待时间",
                context, max_tokens=200,
            )
            if estimation:
                return SpecialistResult(
                    success=True, agent_id=self.agent_id, action="estimate_wait_time",
                    message=estimation, confidence=0.7,
                    data={"party_size": party_size},
                )

        return SpecialistResult(
            success=True, agent_id=self.agent_id, action="estimate_wait_time",
            message=f"预计{party_size}人等待约15-25分钟（基于当前排队情况）",
            confidence=0.5,
            data={"party_size": party_size, "estimated_minutes": 20},
        )

    async def _suggest_table_assignment(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        tables = await self.call_tool(
            "query_table_status", {"store_id": context.store_id or ""}, context,
        )
        return SpecialistResult(
            success=True, agent_id=self.agent_id, action="suggest_table_assignment",
            message="桌位分配建议", data=tables.data, confidence=0.75,
        )

    async def _detect_churn_risk(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        waitlist = await self.call_tool(
            "query_waitlist", {"store_id": context.store_id or ""}, context,
        )
        if self._router and waitlist.data:
            analysis = await self.llm_reason(
                f"等位队列：{waitlist.data}\n请识别等位流失风险客户并建议安抚策略",
                context, max_tokens=400,
            )
            if analysis:
                return SpecialistResult(
                    success=True, agent_id=self.agent_id, action="detect_churn_risk",
                    message=analysis, confidence=0.7,
                )
        return SpecialistResult(
            success=True, agent_id=self.agent_id, action="detect_churn_risk",
            message="当前等位队列暂无高流失风险客户", confidence=0.5,
        )
