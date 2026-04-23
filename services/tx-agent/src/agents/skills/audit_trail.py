"""#29 审计留痕 Agent — P1 | 云端

守门员Agent：记录所有Agent决策和关键业务操作的审计日志。
追踪：谁在什么时间做了什么决策，基于什么数据，结果如何。
支持回溯：按时间/操作人/类型查询审计记录。

输出写入 agent_decision_logs 表（v002已创建）。
"""

from datetime import datetime, timezone
from typing import Any

import structlog

from ..base import AgentResult, SkillAgent

logger = structlog.get_logger()


class AuditTrailAgent(SkillAgent):
    agent_id = "audit_trail"
    agent_name = "审计留痕"
    description = "记录Agent决策审计日志，支持按时间/操作人/类型查询回溯"
    priority = "P1"
    run_location = "cloud"

    # Sprint D1 / PR 批次 6：仅记录其他 Agent 的决策审计日志，自身不做业务决策，豁免
    constraint_scope = set()
    constraint_waived_reason = (
        "审计留痕纯日志记录与查询工具，不触发任何业务决策；"
        "记录的是其他 Agent 的决策过程，自身不涉及毛利/食安/体验维度"
    )

    def get_supported_actions(self) -> list[str]:
        return [
            "log_decision",
            "query_logs",
            "get_decision_detail",
            "summarize_audit",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "log_decision": self._log_decision,
            "query_logs": self._query_logs,
            "get_decision_detail": self._get_decision_detail,
            "summarize_audit": self._summarize_audit,
        }
        handler = dispatch.get(action)
        if not handler:
            return AgentResult(success=False, action=action, error=f"Unsupported: {action}")
        return await handler(params)

    # ─── 记录决策 ───

    async def _log_decision(self, params: dict) -> AgentResult:
        """记录一条Agent决策审计日志 — 写入 agent_decision_logs 表"""
        agent_id = params.get("agent_id", "")
        decision_type = params.get("decision_type", "")
        operator_id = params.get("operator_id", "system")
        input_context = params.get("input_context", {})
        output_action = params.get("output_action", {})
        reasoning = params.get("reasoning", "")
        confidence = params.get("confidence", 0.0)
        constraints_check = params.get("constraints_check", {})

        if not agent_id or not decision_type:
            return AgentResult(
                success=False,
                action="log_decision",
                error="agent_id 和 decision_type 不可为空",
                reasoning="审计日志必须包含 agent_id 和 decision_type",
                confidence=1.0,
            )

        now = datetime.now(timezone.utc)
        log_entry = {
            "agent_id": agent_id,
            "decision_type": decision_type,
            "operator_id": operator_id,
            "input_context": input_context,
            "output_action": output_action,
            "reasoning": reasoning,
            "confidence": confidence,
            "constraints_check": constraints_check,
            "created_at": now.isoformat(),
            "tenant_id": self.tenant_id,
            "store_id": self.store_id,
        }

        # 实际部署时通过 Repository 写入 agent_decision_logs 表
        # 此处构建日志条目，由调用方持久化
        logger.info(
            "audit_decision_logged",
            agent_id=agent_id,
            decision_type=decision_type,
            operator_id=operator_id,
            confidence=confidence,
        )

        return AgentResult(
            success=True,
            action="log_decision",
            data={
                "logged": True,
                "log_entry": log_entry,
                "table": "agent_decision_logs",
            },
            reasoning=f"已记录 {agent_id} 的 {decision_type} 决策，操作人 {operator_id}，置信度 {confidence:.2f}",
            confidence=0.99,
        )

    # ─── 查询审计日志 ───

    async def _query_logs(self, params: dict) -> AgentResult:
        """按条件查询审计日志"""
        # 查询条件
        agent_id = params.get("agent_id")
        operator_id = params.get("operator_id")
        decision_type = params.get("decision_type")
        start_time = params.get("start_time")
        end_time = params.get("end_time")
        page = params.get("page", 1)
        page_size = params.get("page_size", 20)

        # 提供的模拟日志（实际部署时查数据库）
        logs = params.get("logs", [])

        # 应用过滤条件
        filtered = logs
        if agent_id:
            filtered = [l for l in filtered if l.get("agent_id") == agent_id]
        if operator_id:
            filtered = [l for l in filtered if l.get("operator_id") == operator_id]
        if decision_type:
            filtered = [l for l in filtered if l.get("decision_type") == decision_type]
        if start_time:
            filtered = [l for l in filtered if l.get("created_at", "") >= start_time]
        if end_time:
            filtered = [l for l in filtered if l.get("created_at", "") <= end_time]

        total = len(filtered)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        page_items = filtered[start_idx:end_idx]

        query_desc_parts = []
        if agent_id:
            query_desc_parts.append(f"agent={agent_id}")
        if operator_id:
            query_desc_parts.append(f"operator={operator_id}")
        if decision_type:
            query_desc_parts.append(f"type={decision_type}")
        query_desc = ", ".join(query_desc_parts) if query_desc_parts else "全部"

        return AgentResult(
            success=True,
            action="query_logs",
            data={
                "items": page_items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "filters_applied": {
                    "agent_id": agent_id,
                    "operator_id": operator_id,
                    "decision_type": decision_type,
                    "start_time": start_time,
                    "end_time": end_time,
                },
            },
            reasoning=f"查询条件: {query_desc}，返回 {len(page_items)}/{total} 条记录",
            confidence=0.95,
        )

    # ─── 获取决策详情 ───

    async def _get_decision_detail(self, params: dict) -> AgentResult:
        """获取单条决策的完整审计详情"""
        log_id = params.get("log_id", "")
        log_entry = params.get("log_entry")

        if not log_id and not log_entry:
            return AgentResult(
                success=False,
                action="get_decision_detail",
                error="需要提供 log_id 或 log_entry",
                reasoning="查询决策详情需要指定记录",
                confidence=1.0,
            )

        # 实际部署时根据 log_id 查数据库
        if log_entry is None:
            log_entry = {"log_id": log_id, "status": "需要数据库查询"}

        return AgentResult(
            success=True,
            action="get_decision_detail",
            data={
                "log_id": log_id,
                "detail": log_entry,
                "trace": {
                    "input_context": log_entry.get("input_context", {}),
                    "reasoning": log_entry.get("reasoning", ""),
                    "output_action": log_entry.get("output_action", {}),
                    "constraints_check": log_entry.get("constraints_check", {}),
                    "confidence": log_entry.get("confidence", 0),
                },
            },
            reasoning=f"获取决策 {log_id} 的完整审计详情",
            confidence=0.95,
        )

    # ─── 审计汇总 ───

    async def _summarize_audit(self, params: dict) -> AgentResult:
        """汇总一段时间内的审计统计"""
        logs = params.get("logs", [])
        period = params.get("period", "today")

        total = len(logs)
        if total == 0:
            return AgentResult(
                success=True,
                action="summarize_audit",
                data={
                    "period": period,
                    "total_decisions": 0,
                    "by_agent": {},
                    "by_type": {},
                    "constraint_violations": 0,
                    "avg_confidence": 0,
                },
                reasoning=f"{period} 无审计记录",
                confidence=1.0,
            )

        # 按Agent统计
        by_agent: dict[str, int] = {}
        by_type: dict[str, int] = {}
        violation_count = 0
        confidence_sum = 0.0

        for log in logs:
            aid = log.get("agent_id", "unknown")
            by_agent[aid] = by_agent.get(aid, 0) + 1

            dtype = log.get("decision_type", "unknown")
            by_type[dtype] = by_type.get(dtype, 0) + 1

            constraints = log.get("constraints_check", {})
            if not constraints.get("passed", True):
                violation_count += 1

            confidence_sum += log.get("confidence", 0)

        avg_confidence = round(confidence_sum / total, 2) if total > 0 else 0

        return AgentResult(
            success=True,
            action="summarize_audit",
            data={
                "period": period,
                "total_decisions": total,
                "by_agent": by_agent,
                "by_type": by_type,
                "constraint_violations": violation_count,
                "avg_confidence": avg_confidence,
            },
            reasoning=f"{period} 共 {total} 条决策，{violation_count} 条约束违规，平均置信度 {avg_confidence:.2f}",
            confidence=0.92,
        )
