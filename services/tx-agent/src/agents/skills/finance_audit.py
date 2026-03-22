"""#6 财务稽核 Agent — P1 | 云端

来源：FctAgent + DecisionAgent + business_intel(5子Agent)
能力：财务报表、营收异常、KPI分析、订单预测、经营洞察
"""
from typing import Any
from ..base import SkillAgent, AgentResult


class FinanceAuditAgent(SkillAgent):
    agent_id = "finance_audit"
    agent_name = "财务稽核"
    description = "财务报表、营收异常分析、KPI快照、经营洞察、场景识别"
    priority = "P1"
    run_location = "cloud"

    def get_supported_actions(self) -> list[str]:
        return [
            "get_financial_report",       # 7种财务报表
            "detect_revenue_anomaly",     # 营收异常检测
            "snapshot_kpi",               # KPI健康度快照
            "forecast_orders",            # 订单量预测
            "generate_biz_insight",       # 经营洞察
            "match_scenario",             # 场景识别
            "analyze_order_trend",        # 订单趋势分析
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        return AgentResult(success=True, action=action, data={"message": f"{action} ready"}, confidence=0.8)
