"""总部分析 Agent — P0

职责：多门店对比、品牌经营洞察、预警聚合、整改任务生成、周报/月报草拟
适配模式：A（Agent 主导分析和报告生成）
"""
from __future__ import annotations

from .base_specialist import SpecialistAgent, SpecialistResult
from ..scene_session import SessionContext


class HQAnalyticsAgent(SpecialistAgent):
    agent_id = "hq_analytics"
    agent_name = "总部分析 Agent"
    description = "多门店对比、品牌经营洞察、预警聚合、整改任务生成、周报月报草拟"
    priority = "P0"

    def get_supported_actions(self) -> list[str]:
        return [
            "multi_store_compare",
            "generate_report",
            "store_alerts",
            "insight_analysis",
            "general_query",
        ]

    async def execute(
        self, action: str, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        if action == "multi_store_compare":
            return await self._multi_store_compare(params, context)
        elif action == "generate_report":
            return await self._generate_report(params, context)
        elif action == "store_alerts":
            return await self._store_alerts(params, context)
        elif action == "insight_analysis":
            return await self._insight_analysis(params, context)
        elif action == "general_query":
            return await self._general_query(params, context)
        return SpecialistResult(
            success=False, agent_id=self.agent_id, action=action,
            error=f"不支持的动作: {action}",
        )

    async def _multi_store_compare(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        store_ids = params.get("store_ids", [])
        metrics = params.get("metrics", ["revenue", "turnover_rate", "avg_ticket"])
        period = params.get("period", "week")

        result = await self.call_tool("compare_stores", {
            "store_ids": store_ids,
            "metrics": metrics,
            "period": period,
        }, context)

        message = "多门店对比数据"
        if self._router and result.data:
            analysis = await self.llm_reason(
                f"多门店对比数据：{result.data}\n"
                "请分析各门店表现差异，指出表现最好和最差的门店及原因",
                context, task_type="standard_analysis", max_tokens=800,
            )
            if analysis:
                message = analysis

        return SpecialistResult(
            success=result.success, agent_id=self.agent_id, action="multi_store_compare",
            message=message, data=result.data,
            reasoning="多门店经营指标对比分析", confidence=0.85,
        )

    async def _generate_report(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        report_type = params.get("report_type", "weekly")
        period = {"weekly": "week", "monthly": "month", "quarterly": "quarter"}.get(
            report_type, "week",
        )

        sales = await self.call_tool("query_sales_summary", {
            "period": period,
            "start_date": params.get("start_date", ""),
        }, context)
        segments = await self.call_tool("query_member_segments", {}, context)

        combined = {
            "sales": sales.data,
            "member_segments": segments.data,
        }

        if self._router:
            report = await self.llm_reason(
                f"经营数据：{combined}\n报告类型：{report_type}\n"
                "请生成经营报告草稿，包含：\n"
                "1. 核心经营指标总结\n"
                "2. 同比/环比变化\n"
                "3. 重点发现和洞察\n"
                "4. 下期工作重点建议",
                context, task_type="complex_reasoning", max_tokens=1500,
            )
            if report:
                return SpecialistResult(
                    success=True, agent_id=self.agent_id, action="generate_report",
                    message=report, data=combined,
                    reasoning=f"{report_type}报告LLM生成",
                    confidence=0.8,
                )

        return SpecialistResult(
            success=True, agent_id=self.agent_id, action="generate_report",
            message="报告数据已汇总，需要人工补充分析",
            data=combined, confidence=0.4,
        )

    async def _store_alerts(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        kpi = await self.call_tool("query_kpi_dashboard", {}, context)
        tasks = await self.call_tool("query_tasks", {
            "status": "pending",
        }, context)

        combined = {"kpi": kpi.data, "pending_tasks": tasks.data}

        if self._router:
            alerts = await self.llm_reason(
                f"全局KPI数据：{kpi.data}\n未完成任务：{tasks.data}\n"
                "请识别需要预警的门店，按紧急程度排序，给出具体异常指标",
                context, task_type="standard_analysis", max_tokens=600,
            )
            if alerts:
                return SpecialistResult(
                    success=True, agent_id=self.agent_id, action="store_alerts",
                    message=alerts, data=combined, confidence=0.75,
                )

        return SpecialistResult(
            success=True, agent_id=self.agent_id, action="store_alerts",
            message="预警数据已汇总", data=combined, confidence=0.5,
        )

    async def _insight_analysis(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        question = params.get("question", params.get("raw_input", ""))
        sales = await self.call_tool("query_sales_summary", {
            "period": params.get("period", "week"),
            "start_date": params.get("start_date", ""),
        }, context)

        if self._router:
            insight = await self.llm_reason(
                f"用户问题：{question}\n经营数据：{sales.data}\n"
                "请基于数据回答问题，提供数据支撑的洞察和建议",
                context, task_type="complex_reasoning", max_tokens=800,
            )
            if insight:
                return SpecialistResult(
                    success=True, agent_id=self.agent_id, action="insight_analysis",
                    message=insight, data=sales.data,
                    reasoning="基于经营数据的LLM洞察分析", confidence=0.75,
                )

        return SpecialistResult(
            success=True, agent_id=self.agent_id, action="insight_analysis",
            message="需要更多上下文数据来回答此问题",
            data=sales.data, confidence=0.3,
        )

    async def _general_query(
        self, params: dict, context: SessionContext,
    ) -> SpecialistResult:
        sales = await self.call_tool("query_sales_summary", {
            "period": "day", "start_date": "",
        }, context)
        return SpecialistResult(
            success=sales.success, agent_id=self.agent_id, action="general_query",
            message="总部经营数据概览", data=sales.data,
        )
