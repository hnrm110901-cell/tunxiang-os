"""店长经营 Agent — P0

职责：当班经营播报、午市/晚市复盘、人效与翻台分析、服务异常归因、日清日结建议
适配模式：A（报表分析）+ B（日清日结）
"""
from __future__ import annotations

from .base_specialist import SpecialistAgent, SpecialistResult
from ..scene_session import SessionContext


class StoreOpsAgent(SpecialistAgent):
    agent_id = "store_ops"
    agent_name = "店长经营 Agent"
    description = "当班经营播报、午晚市复盘、人效翻台分析、服务异常归因、日清日结建议、整改任务生成"
    priority = "P0"

    def get_supported_actions(self) -> list[str]:
        return [
            "shift_review",
            "kpi_query",
            "daily_close",
            "generate_improvement",
            "general_query",
        ]

    async def execute(
        self, action: str, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        if action == "shift_review":
            return await self._shift_review(params, context)
        elif action == "kpi_query":
            return await self._kpi_query(params, context)
        elif action == "daily_close":
            return await self._daily_close(params, context)
        elif action == "generate_improvement":
            return await self._generate_improvement(params, context)
        elif action == "general_query":
            return await self._general_query(params, context)
        return SpecialistResult(
            success=False, agent_id=self.agent_id, action=action,
            error=f"不支持的动作: {action}",
        )

    async def _shift_review(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        # 收集经营数据
        sales = await self.call_tool("query_sales_summary", {
            "store_id": context.store_id or "",
            "period": "day",
            "start_date": params.get("date", "today"),
        }, context)
        kpi = await self.call_tool("query_kpi_dashboard", {
            "store_id": context.store_id or "",
            "date": params.get("date", "today"),
        }, context)
        kitchen = await self.call_tool("query_kitchen_status", {
            "store_id": context.store_id or "",
        }, context)

        combined_data = {
            "sales": sales.data,
            "kpi": kpi.data,
            "kitchen": kitchen.data,
        }

        if self._router:
            review = await self.llm_reason(
                f"经营数据：{combined_data}\n班次：{context.shift_period.value}\n"
                "请生成当班经营复盘报告：\n"
                "1. 核心指标表现（营业额、客单价、翻台率）\n"
                "2. 异常发现和原因分析\n"
                "3. 改善建议",
                context, task_type="standard_analysis", max_tokens=800,
            )
            if review:
                return SpecialistResult(
                    success=True, agent_id=self.agent_id, action="shift_review",
                    message=review, data=combined_data,
                    reasoning="综合销售+KPI+厨房数据的LLM复盘分析",
                    confidence=0.8,
                )

        return SpecialistResult(
            success=True, agent_id=self.agent_id, action="shift_review",
            message="经营复盘数据已汇总，详见数据面板",
            data=combined_data, confidence=0.5,
        )

    async def _kpi_query(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        kpi = await self.call_tool("query_kpi_dashboard", {
            "store_id": context.store_id or "",
            "date": params.get("date"),
        }, context)

        message = "KPI 仪表盘数据"
        if self._router and kpi.data:
            summary = await self.llm_reason(
                f"KPI数据：{kpi.data}\n请简要解读关键指标表现和趋势",
                context, task_type="quick_classification", max_tokens=400,
            )
            if summary:
                message = summary

        return SpecialistResult(
            success=kpi.success, agent_id=self.agent_id, action="kpi_query",
            message=message, data=kpi.data, confidence=0.85,
        )

    async def _daily_close(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        # 汇总日结数据
        sales = await self.call_tool("query_sales_summary", {
            "store_id": context.store_id or "",
            "period": "day", "start_date": params.get("date", "today"),
        }, context)
        orders = await self.call_tool("query_orders", {
            "store_id": context.store_id or "",
            "date": params.get("date", "today"),
        }, context)
        tasks = await self.call_tool("query_tasks", {
            "store_id": context.store_id, "status": "pending",
        }, context)

        combined = {
            "sales": sales.data,
            "orders_summary": orders.data,
            "pending_tasks": tasks.data,
        }

        if self._router:
            close_report = await self.llm_reason(
                f"日结数据：{combined}\n"
                "请生成日清日结报告：\n"
                "1. 今日经营总结\n"
                "2. 未完成事项提醒\n"
                "3. 对账差异提示\n"
                "4. 明日准备事项",
                context, task_type="standard_analysis", max_tokens=800,
            )
            if close_report:
                return SpecialistResult(
                    success=True, agent_id=self.agent_id, action="daily_close",
                    message=close_report, data=combined,
                    reasoning="日清日结LLM分析", confidence=0.8,
                )

        return SpecialistResult(
            success=True, agent_id=self.agent_id, action="daily_close",
            message="日结数据已汇总", data=combined, confidence=0.5,
        )

    async def _generate_improvement(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        # 收集经营数据作为改善依据
        kpi = await self.call_tool("query_kpi_dashboard", {
            "store_id": context.store_id or "",
        }, context)

        if self._router and kpi.data:
            plan = await self.llm_reason(
                f"经营数据：{kpi.data}\n"
                f"改善方向：{params.get('focus', '整体提升')}\n"
                "请生成具体的整改任务列表，每个任务包含：\n"
                "- 任务标题\n- 负责人建议\n- 优先级\n- 完成期限",
                context, task_type="complex_reasoning", max_tokens=800,
            )
            if plan:
                return SpecialistResult(
                    success=True, agent_id=self.agent_id, action="generate_improvement",
                    message=plan, data=kpi.data,
                    pending_tool_calls=[{
                        "tool": "create_task",
                        "params": {"auto_generated": True},
                    }],
                    reasoning="基于KPI数据的LLM整改方案生成", confidence=0.7,
                )

        return SpecialistResult(
            success=True, agent_id=self.agent_id, action="generate_improvement",
            message="整改方案需要更多经营数据支持", confidence=0.4,
        )

    async def _general_query(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        kpi = await self.call_tool("query_kpi_dashboard", {
            "store_id": context.store_id or "",
        }, context)
        return SpecialistResult(
            success=kpi.success, agent_id=self.agent_id, action="general_query",
            message="门店经营数据", data=kpi.data,
        )
