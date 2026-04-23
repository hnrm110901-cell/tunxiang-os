"""D7 自动派单引擎 — Agent异常预警 → 自动创建任务 → 派发到人 → 跟踪闭环

闭环流程:
  Agent 检测异常 → process_agent_alert → 创建 issue → 派发 assignee → 通知 → SLA 监控 → 超时升级

SLA 定义:
  普通(normal)  30 分钟
  严重(severe)  15 分钟
  紧急(urgent)   5 分钟
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import structlog

log = structlog.get_logger(__name__)

# ─── SLA 配置(分钟) ───

SLA_MINUTES: Dict[str, int] = {
    "normal": 30,
    "severe": 15,
    "urgent": 5,
}

# ─── 预警类型 → 派单规则默认映射 ───

ALERT_TYPE_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "discount_anomaly": {
        "assignee_roles": ["store_manager"],
        "severity": "severe",
        "issue_type": "discount",
        "description_template": "折扣异常预警: {summary}",
    },
    "cooking_timeout": {
        "assignee_roles": ["head_chef"],
        "severity": "severe",
        "issue_type": "service",
        "description_template": "出餐超时预警: {summary}",
    },
    "stockout": {
        "assignee_roles": ["purchaser"],
        "severity": "normal",
        "issue_type": "shortage",
        "description_template": "缺货预警: {summary}",
    },
    "food_safety": {
        "assignee_roles": ["food_safety_officer", "regional_manager"],
        "severity": "urgent",
        "issue_type": "food_safety",
        "description_template": "食品安全预警: {summary}",
    },
    "cashier_anomaly": {
        "assignee_roles": ["finance"],
        "severity": "severe",
        "issue_type": "cashier",
        "description_template": "收银异常预警: {summary}",
    },
    "margin_drop": {
        "assignee_roles": ["store_manager", "regional_manager"],
        "severity": "severe",
        "issue_type": "cost",
        "description_template": "毛利下降预警: {summary}",
    },
}

# 角色 → 升级角色
ESCALATION_CHAIN: Dict[str, str] = {
    "store_manager": "regional_manager",
    "head_chef": "store_manager",
    "purchaser": "store_manager",
    "food_safety_officer": "regional_manager",
    "finance": "store_manager",
    "regional_manager": "ops_director",
    "ops_director": "ops_director",  # 顶层不再升级
}

# ─── 内存存储(生产环境替换为 DB) ───

_dispatch_rules: Dict[str, Dict[str, Any]] = {}  # key: "{tenant_id}:{alert_type}"
_dispatch_tasks: List[Dict[str, Any]] = []  # 派单任务列表


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  注册异常→任务映射规则
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def register_alert_handler(
    alert_type: str,
    handler_config: Dict[str, Any],
) -> Dict[str, Any]:
    """注册异常类型 → 任务映射规则。

    Args:
        alert_type: 预警类型 (discount_anomaly/cooking_timeout/stockout/...)
        handler_config: 处理配置
            {
                "assignee_roles": ["store_manager"],
                "severity": "severe",
                "issue_type": "discount",
                "description_template": "...",
            }

    Returns:
        {"registered": True, "alert_type": str, "config": dict}
    """
    ALERT_TYPE_DEFAULTS[alert_type] = handler_config

    log.info(
        "alert_handler_registered",
        alert_type=alert_type,
        assignee_roles=handler_config.get("assignee_roles"),
        severity=handler_config.get("severity"),
    )

    return {
        "registered": True,
        "alert_type": alert_type,
        "config": handler_config,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  处理 Agent 预警 → 自动创建任务 + 派发
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def process_agent_alert(
    alert: Dict[str, Any],
    tenant_id: str,
    db: Any,
) -> Dict[str, Any]:
    """Agent 预警 → 自动创建任务 + 派发。

    Args:
        alert: Agent 发出的预警
            {
                "alert_type": "discount_anomaly",
                "store_id": "store_001",
                "source_agent": "discount_guard",
                "summary": "员工张三连续3单折扣>50%",
                "detail": {...},
                "severity": "severe",        # 可选, 覆盖默认
            }
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        {
            "task_id": str,
            "alert_type": str,
            "assignee_roles": [str],
            "severity": str,
            "sla_deadline": str,
            "status": "pending",
        }

    Raises:
        ValueError: 未知的预警类型且无自定义规则
    """
    alert_type = alert.get("alert_type", "")
    store_id = alert.get("store_id", "")
    source_agent = alert.get("source_agent", "unknown")
    summary = alert.get("summary", "")

    # 查找规则: 先看租户自定义, 再看默认
    rule_key = f"{tenant_id}:{alert_type}"
    rule = _dispatch_rules.get(rule_key) or ALERT_TYPE_DEFAULTS.get(alert_type)

    if rule is None:
        raise ValueError(
            f"Unknown alert_type '{alert_type}'. Register with register_alert_handler() or set_dispatch_rule() first."
        )

    # 严重级别: alert 可覆盖, 否则用规则
    severity = alert.get("severity") or rule.get("severity", "normal")
    assignee_roles = rule.get("assignee_roles", ["store_manager"])
    issue_type = rule.get("issue_type", "other")
    desc_template = rule.get("description_template", "{summary}")

    # 计算 SLA 截止时间
    sla_minutes = SLA_MINUTES.get(severity, 30)
    now = datetime.utcnow()
    sla_deadline = now + timedelta(minutes=sla_minutes)

    task_id = f"task_{store_id}_{uuid.uuid4().hex[:8]}"

    task = {
        "task_id": task_id,
        "tenant_id": tenant_id,
        "store_id": store_id,
        "alert_type": alert_type,
        "source_agent": source_agent,
        "issue_type": issue_type,
        "description": desc_template.format(summary=summary),
        "severity": severity,
        "assignee_roles": assignee_roles,
        "sla_minutes": sla_minutes,
        "sla_deadline": sla_deadline.isoformat(),
        "status": "pending",
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "escalated": False,
        "escalation_history": [],
        "resolution": None,
        "resolved_at": None,
        "alert_detail": alert.get("detail", {}),
    }

    _dispatch_tasks.append(task)

    log.info(
        "dispatch_task_created",
        task_id=task_id,
        tenant_id=tenant_id,
        store_id=store_id,
        alert_type=alert_type,
        severity=severity,
        assignee_roles=assignee_roles,
        sla_minutes=sla_minutes,
        source_agent=source_agent,
    )

    return task


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  获取 / 设置派单规则
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def get_dispatch_rules(
    tenant_id: str,
    db: Any,
) -> Dict[str, Any]:
    """获取该租户的派单规则。

    Args:
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        {"tenant_id": str, "rules": {alert_type: config}, "defaults": {alert_type: config}}
    """
    tenant_rules: Dict[str, Any] = {}
    prefix = f"{tenant_id}:"
    for key, val in _dispatch_rules.items():
        if key.startswith(prefix):
            alert_type = key[len(prefix) :]
            tenant_rules[alert_type] = val

    log.info(
        "dispatch_rules_queried",
        tenant_id=tenant_id,
        custom_count=len(tenant_rules),
    )

    return {
        "tenant_id": tenant_id,
        "rules": tenant_rules,
        "defaults": ALERT_TYPE_DEFAULTS,
    }


async def set_dispatch_rule(
    alert_type: str,
    assignee_role: str,
    escalation_minutes: int,
    tenant_id: str,
    db: Any,
) -> Dict[str, Any]:
    """配置租户级派单规则。

    Args:
        alert_type: 预警类型
        assignee_role: 指派角色
        escalation_minutes: 超时升级时间(分钟)
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        {"saved": True, "alert_type": str, "assignee_role": str, "escalation_minutes": int}
    """
    # 推算 severity
    if escalation_minutes <= 5:
        severity = "urgent"
    elif escalation_minutes <= 15:
        severity = "severe"
    else:
        severity = "normal"

    rule_key = f"{tenant_id}:{alert_type}"
    rule = {
        "assignee_roles": [assignee_role],
        "severity": severity,
        "escalation_minutes": escalation_minutes,
        "issue_type": alert_type,
        "description_template": f"自定义预警({alert_type}): {{summary}}",
    }
    _dispatch_rules[rule_key] = rule

    log.info(
        "dispatch_rule_saved",
        tenant_id=tenant_id,
        alert_type=alert_type,
        assignee_role=assignee_role,
        escalation_minutes=escalation_minutes,
        severity=severity,
    )

    return {
        "saved": True,
        "alert_type": alert_type,
        "assignee_role": assignee_role,
        "escalation_minutes": escalation_minutes,
        "severity": severity,
        "tenant_id": tenant_id,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SLA 检查 — 超时未处理自动升级
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def check_sla(
    tenant_id: str,
    db: Any,
    *,
    now: Optional[datetime] = None,
    tasks: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """SLA 检查: 找出已超时的任务并自动升级。

    Args:
        tenant_id: 租户 ID
        db: 数据库会话
        now: 当前时间(测试注入用)
        tasks: 任务列表(测试注入用)

    Returns:
        {"checked": int, "escalated": [task_id], "ok": [task_id]}
    """
    now_ = now or datetime.utcnow()
    all_tasks = tasks if tasks is not None else _dispatch_tasks

    escalated_ids: List[str] = []
    ok_ids: List[str] = []

    for task in all_tasks:
        if task.get("tenant_id") != tenant_id:
            continue
        if task.get("status") in ("resolved", "cancelled"):
            continue

        sla_deadline_str = task.get("sla_deadline", "")
        try:
            sla_deadline = datetime.fromisoformat(sla_deadline_str)
        except (ValueError, TypeError):
            continue

        if now_ > sla_deadline and task.get("status") == "pending":
            # 超时 → 自动升级
            current_roles = task.get("assignee_roles", [])
            escalated_roles = []
            for role in current_roles:
                upper = ESCALATION_CHAIN.get(role, "ops_director")
                if upper not in escalated_roles:
                    escalated_roles.append(upper)

            task["status"] = "escalated"
            task["escalated"] = True
            task["assignee_roles"] = escalated_roles
            task["updated_at"] = now_.isoformat()
            task.setdefault("escalation_history", []).append(
                {
                    "from_roles": current_roles,
                    "to_roles": escalated_roles,
                    "escalated_at": now_.isoformat(),
                    "reason": "SLA timeout",
                }
            )

            escalated_ids.append(task["task_id"])

            log.warning(
                "sla_breach_escalated",
                task_id=task["task_id"],
                tenant_id=tenant_id,
                from_roles=current_roles,
                to_roles=escalated_roles,
            )
        else:
            ok_ids.append(task["task_id"])

    log.info(
        "sla_check_completed",
        tenant_id=tenant_id,
        checked=len(escalated_ids) + len(ok_ids),
        escalated_count=len(escalated_ids),
    )

    return {
        "tenant_id": tenant_id,
        "checked": len(escalated_ids) + len(ok_ids),
        "escalated": escalated_ids,
        "ok": ok_ids,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  派单看板
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def get_dispatch_dashboard(
    store_id: str,
    tenant_id: str,
    db: Any,
    *,
    now: Optional[datetime] = None,
    tasks: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """派单看板 — 待处理 / 处理中 / 已超时 / 已完成。

    Args:
        store_id: 门店 ID
        tenant_id: 租户 ID
        db: 数据库会话
        now: 当前时间(测试注入用)
        tasks: 任务列表(测试注入用)

    Returns:
        {
            "store_id", "tenant_id",
            "pending": [...], "in_progress": [...],
            "overdue": [...], "resolved": [...],
            "summary": {"pending": int, "in_progress": int, "overdue": int, "resolved": int}
        }
    """
    now_ = now or datetime.utcnow()
    all_tasks = tasks if tasks is not None else _dispatch_tasks

    pending: List[Dict[str, Any]] = []
    in_progress: List[Dict[str, Any]] = []
    overdue: List[Dict[str, Any]] = []
    resolved: List[Dict[str, Any]] = []

    for task in all_tasks:
        if task.get("store_id") != store_id or task.get("tenant_id") != tenant_id:
            continue

        status = task.get("status", "pending")

        if status in ("resolved", "cancelled"):
            resolved.append(task)
            continue

        # 检查是否超时
        sla_deadline_str = task.get("sla_deadline", "")
        is_overdue = False
        try:
            sla_deadline = datetime.fromisoformat(sla_deadline_str)
            if now_ > sla_deadline:
                is_overdue = True
        except (ValueError, TypeError):
            pass

        if is_overdue or status == "escalated":
            overdue.append(task)
        elif status == "in_progress":
            in_progress.append(task)
        else:
            pending.append(task)

    log.info(
        "dispatch_dashboard_queried",
        store_id=store_id,
        tenant_id=tenant_id,
        pending=len(pending),
        in_progress=len(in_progress),
        overdue=len(overdue),
        resolved=len(resolved),
    )

    return {
        "store_id": store_id,
        "tenant_id": tenant_id,
        "pending": pending,
        "in_progress": in_progress,
        "overdue": overdue,
        "resolved": resolved,
        "summary": {
            "pending": len(pending),
            "in_progress": len(in_progress),
            "overdue": len(overdue),
            "resolved": len(resolved),
            "total": len(pending) + len(in_progress) + len(overdue) + len(resolved),
        },
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  辅助: 清空内存(测试用)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _reset_store() -> None:
    """清空内存存储(测试用)。"""
    _dispatch_rules.clear()
    _dispatch_tasks.clear()
