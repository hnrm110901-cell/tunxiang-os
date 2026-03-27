"""Agent 实时运行服务 — 从 Demo 到 Production

Sprint 7: discount_guard 上线 (Level 1)
Sprint 8+: 更多 Agent 逐步上线

三级自治机制：
  Level 1: 仅建议（suggest only），人工决定是否执行
  Level 2: 自动执行 + 30 分钟回滚窗口（auto + rollback）
  Level 3: 完全自主执行（fully autonomous）

升级条件：Level 1 累计 100+ 决策且采纳率 > 80% 方可升到 Level 2。
"""
from __future__ import annotations

import time
import uuid
from copy import deepcopy
from typing import Any, Optional

import structlog

logger = structlog.get_logger()


# ── Agent 注册表 ──────────────────────────────────────────────
LIVE_AGENTS: dict[str, dict[str, Any]] = {
    "discount_guard": {"level": 1, "enabled": True, "sprint": 7},
    "inventory_alert": {"level": 1, "enabled": False, "sprint": 8},
    "smart_menu": {"level": 1, "enabled": False, "sprint": 9},
    "serve_dispatch": {"level": 1, "enabled": False, "sprint": 9},
    "member_insight": {"level": 1, "enabled": False, "sprint": 10},
    "finance_audit": {"level": 1, "enabled": False, "sprint": 10},
    "store_inspect": {"level": 1, "enabled": False, "sprint": 11},
    "smart_cs": {"level": 1, "enabled": False, "sprint": 11},
    "private_ops": {"level": 1, "enabled": False, "sprint": 12},
}

# 升级所需最低 Level-1 决策次数
MIN_L1_DECISIONS_FOR_UPGRADE = 100
# 升级所需最低采纳率
MIN_ADOPTION_RATE_FOR_UPGRADE = 80.0

# 企微推送批次时间点（24h 格式）
WECOM_BATCH_HOURS = [9, 12, 17, 21]


class AgentLiveService:
    """Agent 实时运行服务 — 管理 Agent 上线/下线、执行、回滚、升级"""

    def __init__(self) -> None:
        # 运行时状态（内存，生产环境持久化到 DB）
        self._registry: dict[str, dict[str, Any]] = deepcopy(LIVE_AGENTS)
        # decision_id -> {agent_id, action, params, result, store_id, created_at, rollback_id, rolled_back}
        self._decisions: list[dict[str, Any]] = []
        # rollback_id -> decision record
        self._rollback_index: dict[str, dict[str, Any]] = {}
        # 企微推送历史
        self._push_history: list[dict[str, Any]] = []
        # Agent 实例缓存（agent_id -> SkillAgent instance）
        self._agent_instances: dict[str, Any] = {}

    # ─── Agent 实例注册 ───────────────────────────────────────

    def register_agent_instance(self, agent_id: str, agent_instance: Any) -> None:
        """注册 Agent 实例，供 execute_live 调用"""
        self._agent_instances[agent_id] = agent_instance

    # ─── 激活 / 停用 ─────────────────────────────────────────

    def activate_agent(self, agent_id: str, level: int = 1) -> dict:
        """激活 Agent 进入 live 模式

        Args:
            agent_id: Agent 标识
            level: 自治等级 1/2/3

        Returns:
            激活结果
        """
        if agent_id not in self._registry:
            return {"ok": False, "error": f"未知 Agent: {agent_id}"}
        if level not in (1, 2, 3):
            return {"ok": False, "error": f"无效等级: {level}，仅支持 1/2/3"}

        self._registry[agent_id]["enabled"] = True
        self._registry[agent_id]["level"] = level
        self._registry[agent_id]["activated_at"] = time.time()

        logger.info("agent_activated", agent_id=agent_id, level=level)
        return {"ok": True, "agent_id": agent_id, "level": level, "status": "live"}

    def deactivate_agent(self, agent_id: str) -> dict:
        """停用 Agent"""
        if agent_id not in self._registry:
            return {"ok": False, "error": f"未知 Agent: {agent_id}"}

        self._registry[agent_id]["enabled"] = False
        self._registry[agent_id]["deactivated_at"] = time.time()

        logger.info("agent_deactivated", agent_id=agent_id)
        return {"ok": True, "agent_id": agent_id, "status": "offline"}

    # ─── 状态查询 ─────────────────────────────────────────────

    def get_live_status(self) -> list[dict]:
        """获取所有 Agent 的实时状态"""
        result = []
        for agent_id, info in self._registry.items():
            agent_decisions = [d for d in self._decisions if d["agent_id"] == agent_id]
            last_exec = agent_decisions[-1]["created_at"] if agent_decisions else None
            result.append({
                "agent_id": agent_id,
                "enabled": info["enabled"],
                "level": info["level"],
                "sprint": info["sprint"],
                "decision_count": len(agent_decisions),
                "last_execution": last_exec,
            })
        return result

    # ─── 核心执行 ─────────────────────────────────────────────

    async def execute_live(
        self,
        agent_id: str,
        action: str,
        params: dict[str, Any],
        store_id: str,
    ) -> dict:
        """在 live 模式下执行 Agent

        Level 1: 返回建议，不真正执行
        Level 2: 执行 + 创建回滚点（30 分钟窗口）
        Level 3: 立即执行，无回滚

        Args:
            agent_id: Agent 标识
            action: 动作名
            params: 动作参数
            store_id: 门店 ID

        Returns:
            执行结果
        """
        reg = self._registry.get(agent_id)
        if not reg:
            return {"ok": False, "error": f"未知 Agent: {agent_id}"}
        if not reg["enabled"]:
            return {"ok": False, "error": f"Agent {agent_id} 未激活"}

        agent_instance = self._agent_instances.get(agent_id)
        if not agent_instance:
            return {"ok": False, "error": f"Agent {agent_id} 未注册实例"}

        level = reg["level"]
        agent_instance.agent_level = level

        # 执行 Agent
        result = await agent_instance.run(action, params)

        decision_id = str(uuid.uuid4())
        rollback_id = result.rollback_id if level == 2 else ""

        decision_record = {
            "decision_id": decision_id,
            "agent_id": agent_id,
            "action": action,
            "params": params,
            "store_id": store_id,
            "level": level,
            "rollback_id": rollback_id,
            "created_at": time.time(),
            "rolled_back": False,
            "result": {
                "success": result.success,
                "data": result.data,
                "reasoning": result.reasoning,
                "confidence": result.confidence,
                "constraints_passed": result.constraints_passed,
                "agent_level": result.agent_level,
            },
            "status": "suggested" if level == 1 else "executed",
        }

        self._decisions.append(decision_record)
        if rollback_id:
            self._rollback_index[rollback_id] = decision_record

        logger.info(
            "agent_live_executed",
            agent_id=agent_id,
            action=action,
            level=level,
            decision_id=decision_id,
            store_id=store_id,
            rollback_id=rollback_id,
        )

        response: dict[str, Any] = {
            "ok": True,
            "decision_id": decision_id,
            "agent_id": agent_id,
            "level": level,
            "result": decision_record["result"],
            "status": decision_record["status"],
        }
        if level == 1:
            response["message"] = "建议已生成，等待人工确认"
        elif level == 2:
            response["rollback_id"] = rollback_id
            response["rollback_window_min"] = 30
            response["message"] = "已自动执行，30分钟内可回滚"
        else:
            response["message"] = "已完全自主执行"

        return response

    # ─── 回滚 ─────────────────────────────────────────────────

    def rollback_decision(self, rollback_id: str) -> dict:
        """回滚 Level 2 的自动执行决策

        必须在 30 分钟回滚窗口内。

        Args:
            rollback_id: 回滚标识

        Returns:
            回滚结果
        """
        record = self._rollback_index.get(rollback_id)
        if not record:
            return {"ok": False, "error": f"未找到回滚记录: {rollback_id}"}

        if record.get("rolled_back"):
            return {"ok": False, "error": "该决策已被回滚"}

        if record["level"] != 2:
            return {"ok": False, "error": "仅 Level 2 决策支持回滚"}

        elapsed_min = (time.time() - record["created_at"]) / 60
        if elapsed_min > 30:
            return {
                "ok": False,
                "error": f"回滚窗口已过期（已过 {elapsed_min:.1f} 分钟，上限 30 分钟）",
            }

        record["rolled_back"] = True
        record["rolled_back_at"] = time.time()
        record["status"] = "rolled_back"

        logger.info(
            "decision_rolled_back",
            rollback_id=rollback_id,
            decision_id=record["decision_id"],
            elapsed_min=round(elapsed_min, 1),
        )

        return {
            "ok": True,
            "rollback_id": rollback_id,
            "decision_id": record["decision_id"],
            "elapsed_min": round(elapsed_min, 1),
            "status": "rolled_back",
        }

    # ─── 升级 ─────────────────────────────────────────────────

    def upgrade_agent_level(self, agent_id: str, new_level: int) -> dict:
        """升级 Agent 自治等级

        条件：Level 1 累计 >= 100 次决策，且采纳率 > 80%。

        Args:
            agent_id: Agent 标识
            new_level: 目标等级

        Returns:
            升级结果
        """
        reg = self._registry.get(agent_id)
        if not reg:
            return {"ok": False, "error": f"未知 Agent: {agent_id}"}
        if new_level not in (1, 2, 3):
            return {"ok": False, "error": f"无效目标等级: {new_level}"}
        if new_level <= reg["level"]:
            return {"ok": False, "error": f"目标等级 {new_level} 不高于当前等级 {reg['level']}"}

        readiness = self.get_agent_readiness(agent_id)
        if not readiness["ready_for_upgrade"]:
            return {
                "ok": False,
                "error": "不满足升级条件",
                "readiness": readiness,
            }

        old_level = reg["level"]
        reg["level"] = new_level
        reg["upgraded_at"] = time.time()

        logger.info(
            "agent_level_upgraded",
            agent_id=agent_id,
            old_level=old_level,
            new_level=new_level,
        )

        return {
            "ok": True,
            "agent_id": agent_id,
            "old_level": old_level,
            "new_level": new_level,
            "readiness": readiness,
        }

    def get_agent_readiness(self, agent_id: str) -> dict:
        """评估 Agent 是否达到升级条件

        Returns:
            {decision_count, adoption_rate, effectiveness_score, ready_for_upgrade}
        """
        agent_decisions = [d for d in self._decisions if d["agent_id"] == agent_id]
        total = len(agent_decisions)
        adopted = sum(
            1 for d in agent_decisions
            if d.get("status") in ("executed", "adopted", "approved")
        )
        adoption_rate = round(adopted / total * 100, 1) if total > 0 else 0.0

        # 效果评分：取有 confidence 的决策平均值
        scores = [
            d["result"]["confidence"]
            for d in agent_decisions
            if d.get("result", {}).get("confidence", 0) > 0
        ]
        effectiveness_score = round(sum(scores) / len(scores) * 100, 1) if scores else 0.0

        ready = (
            total >= MIN_L1_DECISIONS_FOR_UPGRADE
            and adoption_rate >= MIN_ADOPTION_RATE_FOR_UPGRADE
        )

        return {
            "agent_id": agent_id,
            "decision_count": total,
            "adopted_count": adopted,
            "adoption_rate": adoption_rate,
            "effectiveness_score": effectiveness_score,
            "min_decisions_required": MIN_L1_DECISIONS_FOR_UPGRADE,
            "min_adoption_rate_required": MIN_ADOPTION_RATE_FOR_UPGRADE,
            "ready_for_upgrade": ready,
        }

    # ─── 企微推送 ─────────────────────────────────────────────

    def push_to_wecom(
        self,
        store_id: str,
        decision_summary: str,
        urgency: str = "normal",
    ) -> dict:
        """将 Agent 决策推送到企业微信

        Args:
            store_id: 门店 ID
            decision_summary: 决策摘要
            urgency: "critical" 立即推送 / "normal" 在 4 个时间点批量推送

        Returns:
            推送结果
        """
        if urgency not in ("critical", "normal"):
            return {"ok": False, "error": f"无效紧急程度: {urgency}"}

        message_id = str(uuid.uuid4())
        channel = "wecom_bot" if urgency == "critical" else "wecom_batch"

        push_record = {
            "message_id": message_id,
            "store_id": store_id,
            "decision_summary": decision_summary,
            "urgency": urgency,
            "channel": channel,
            "sent_at": time.time(),
            "status": "sent",
            "batch_hours": WECOM_BATCH_HOURS if urgency == "normal" else None,
        }

        self._push_history.append(push_record)

        logger.info(
            "wecom_push_sent",
            message_id=message_id,
            store_id=store_id,
            urgency=urgency,
            channel=channel,
        )

        return {
            "ok": True,
            "sent": True,
            "message_id": message_id,
            "channel": channel,
            "urgency": urgency,
        }

    def get_push_history(self, store_id: str, days: int = 7) -> list[dict]:
        """获取门店企微推送历史

        Args:
            store_id: 门店 ID
            days: 查询天数

        Returns:
            推送记录列表
        """
        cutoff = time.time() - days * 86400
        return [
            p for p in self._push_history
            if p["store_id"] == store_id and p["sent_at"] >= cutoff
        ]

    # ─── 内部辅助 ─────────────────────────────────────────────

    def _get_decisions_for_agent(self, agent_id: str) -> list[dict]:
        """获取某 Agent 的全部决策记录"""
        return [d for d in self._decisions if d["agent_id"] == agent_id]

    def _inject_decisions(self, decisions: list[dict]) -> None:
        """注入历史决策（用于测试和数据迁移）"""
        self._decisions.extend(decisions)
        for d in decisions:
            if d.get("rollback_id"):
                self._rollback_index[d["rollback_id"]] = d
