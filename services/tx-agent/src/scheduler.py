"""Agent 定时任务调度配置与执行器

调度时间点：
- 06:00 生成每日计划
- 08:00 提醒未审批计划
- 08:30 晨推决策
- 09:00 自动执行已审批计划
- 12:00 午推异常
- 17:30 战前推送
- 20:30 晚推回顾
- 22:00 收集决策效果
"""
import time
import uuid
from typing import Any, Optional

import structlog

logger = structlog.get_logger()

# ─── 调度配置 ───

AGENT_SCHEDULES: dict[str, dict[str, Any]] = {
    "daily_plan_generate": {
        "hour": 6,
        "minute": 0,
        "task": "generate_daily_plans_for_all_stores",
        "description": "为所有活跃门店生成今日经营计划",
    },
    "daily_plan_remind": {
        "hour": 8,
        "minute": 0,
        "task": "remind_unapproved_plans",
        "description": "提醒未审批的计划",
    },
    "daily_plan_auto_execute": {
        "hour": 9,
        "minute": 0,
        "task": "auto_execute_approved_plans",
        "description": "自动执行已审批的计划项",
    },
    "decision_outcome_collect": {
        "hour": 22,
        "minute": 0,
        "task": "collect_decision_outcomes",
        "description": "收集当日决策效果数据",
    },
    "pilot_metrics_collect": {
        "hour": 2,
        "minute": 0,
        "task": "collect_pilot_metrics_for_all_tenants",
        "description": "每日凌晨采集所有活跃试点的前一日指标快照",
    },
    # 已有的 4 时间点推送
    "morning_push": {
        "hour": 8,
        "minute": 30,
        "task": "push_morning_decisions",
        "description": "晨推 Top3 决策",
    },
    "noon_push": {
        "hour": 12,
        "minute": 0,
        "task": "push_noon_anomaly",
        "description": "午推异常与损耗",
    },
    "prebattle_push": {
        "hour": 17,
        "minute": 30,
        "task": "push_prebattle_decisions",
        "description": "战前备战核查",
    },
    "evening_push": {
        "hour": 20,
        "minute": 30,
        "task": "push_evening_recap",
        "description": "晚推经营简报",
    },
}

# 所有调度必须包含的字段
REQUIRED_SCHEDULE_FIELDS = {"hour", "minute", "task"}


def validate_schedules(schedules: dict[str, dict] | None = None) -> list[str]:
    """校验调度配置完整性，返回错误列表（空列表 = 全部合法）"""
    schedules = schedules or AGENT_SCHEDULES
    errors: list[str] = []
    seen_tasks: set[str] = set()

    for name, config in schedules.items():
        missing = REQUIRED_SCHEDULE_FIELDS - set(config.keys())
        if missing:
            errors.append(f"{name}: 缺少必填字段 {missing}")

        hour = config.get("hour")
        minute = config.get("minute")
        if hour is not None and not (0 <= hour <= 23):
            errors.append(f"{name}: hour={hour} 超出 0-23 范围")
        if minute is not None and not (0 <= minute <= 59):
            errors.append(f"{name}: minute={minute} 超出 0-59 范围")

        task = config.get("task")
        if task and task in seen_tasks:
            errors.append(f"{name}: task={task} 重复")
        if task:
            seen_tasks.add(task)

    return errors


def get_schedule_timeline(schedules: dict[str, dict] | None = None) -> list[dict]:
    """按时间排序返回调度时间线"""
    schedules = schedules or AGENT_SCHEDULES
    timeline = []
    for name, config in schedules.items():
        timeline.append({
            "name": name,
            "time": f"{config['hour']:02d}:{config['minute']:02d}",
            "task": config["task"],
            "description": config.get("description", ""),
        })
    timeline.sort(key=lambda x: x["time"])
    return timeline


# ─── 纯函数任务实现 ───


def generate_daily_plans_for_all_stores(
    active_store_ids: list[str],
) -> list[dict]:
    """为所有活跃门店生成今日经营计划

    Args:
        active_store_ids: 活跃门店 ID 列表

    Returns:
        每个门店的计划生成结果列表
    """
    results = []
    for store_id in active_store_ids:
        plan_id = f"PLAN_{time.strftime('%Y%m%d')}_{store_id}"
        result = {
            "store_id": store_id,
            "plan_id": plan_id,
            "status": "pending_approval",
            "generated": True,
        }
        results.append(result)
        logger.info("daily_plan_generated", store_id=store_id, plan_id=plan_id)
    return results


def remind_unapproved_plans(
    pending_plans: list[dict],
) -> list[dict]:
    """查找 status=pending_approval 的计划并生成提醒

    Args:
        pending_plans: 待审批的计划列表

    Returns:
        提醒消息列表
    """
    reminders = []
    for plan in pending_plans:
        if plan.get("status") == "pending_approval":
            reminder = {
                "plan_id": plan.get("plan_id", ""),
                "store_id": plan.get("store_id", ""),
                "message": f"计划 {plan.get('plan_id', '')} 尚未审批，请尽快处理",
                "reminded": True,
            }
            reminders.append(reminder)
            logger.info("plan_reminder_sent", plan_id=plan.get("plan_id"))
    return reminders


def auto_execute_approved_plans(
    approved_plans: list[dict],
) -> list[dict]:
    """将 approved 的建议标记为 executing

    Args:
        approved_plans: 已审批的计划列表

    Returns:
        状态变更结果列表
    """
    results = []
    for plan in approved_plans:
        if plan.get("status") == "approved":
            result = {
                "plan_id": plan.get("plan_id", ""),
                "store_id": plan.get("store_id", ""),
                "old_status": "approved",
                "new_status": "executing",
                "executed": True,
            }
            results.append(result)
            logger.info(
                "plan_auto_executed",
                plan_id=plan.get("plan_id"),
                store_id=plan.get("store_id"),
            )
    return results


def collect_decision_outcomes(
    decisions: list[dict],
    current_metrics: dict[str, dict],
) -> list[dict]:
    """收集当日决策效果数据，对比建议前后指标变化

    Args:
        decisions: 当日已执行的决策列表，每条含 decision_id, decision_type, before_data
        current_metrics: 当前指标 {decision_id: {metric: value}}

    Returns:
        每条决策的效果收集结果
    """
    outcomes = []
    for decision in decisions:
        decision_id = decision.get("decision_id", "")
        before_data = decision.get("before_data", {})
        after_data = current_metrics.get(decision_id, {})

        # 计算变化量
        deltas = {}
        for key in before_data:
            if key in after_data:
                before_val = before_data[key]
                after_val = after_data[key]
                if isinstance(before_val, (int, float)) and isinstance(after_val, (int, float)):
                    change = after_val - before_val
                    pct = (change / before_val * 100) if before_val != 0 else 0.0
                    deltas[key] = {"before": before_val, "after": after_val, "change": change, "pct": round(pct, 1)}

        # 简易效果分：基于指标改善幅度
        positive_changes = [d["pct"] for d in deltas.values() if d["pct"] > 0]
        outcome_score = min(100, sum(positive_changes) / max(len(positive_changes), 1))

        outcome = {
            "decision_id": decision_id,
            "decision_type": decision.get("decision_type", ""),
            "metrics_delta": deltas,
            "outcome_score": round(outcome_score, 1),
            "collected": True,
        }
        outcomes.append(outcome)
        logger.info("decision_outcome_collected", decision_id=decision_id, score=outcome_score)

    return outcomes


# ─── 任务注册表 ───

async def collect_pilot_metrics_for_all_tenants(
    active_tenant_ids: list[str],
    db_session: Any = None,
) -> list[dict]:
    """凌晨 02:00 定时任务：为所有活跃租户采集试点指标

    Args:
        active_tenant_ids: 活跃租户 UUID 字符串列表
        db_session: 数据库会话（由调用方注入）

    Returns:
        每个租户的采集结果列表
    """
    from .services.pilot_metrics_collector import PilotMetricsCollector

    results = []
    for tenant_id_str in active_tenant_ids:
        try:
            tid = uuid.UUID(tenant_id_str)
            collector = PilotMetricsCollector(db_session=db_session)
            result = await collector.collect_for_all_active_pilots(tid)
            results.append({"tenant_id": tenant_id_str, "status": "ok", **result})
            logger.info("pilot_metrics_collected", tenant_id=tenant_id_str, pilots=result.get("pilots_processed", 0))
        except Exception as exc:  # noqa: BLE001 — scheduler 每租户独立隔离，捕获所有异常
            logger.error("pilot_metrics_collect_tenant_error", tenant_id=tenant_id_str, error=str(exc), exc_info=True)
            results.append({"tenant_id": tenant_id_str, "status": "error", "error": str(exc)})
    return results


TASK_REGISTRY: dict[str, callable] = {
    "generate_daily_plans_for_all_stores": generate_daily_plans_for_all_stores,
    "remind_unapproved_plans": remind_unapproved_plans,
    "auto_execute_approved_plans": auto_execute_approved_plans,
    "collect_decision_outcomes": collect_decision_outcomes,
    "collect_pilot_metrics_for_all_tenants": collect_pilot_metrics_for_all_tenants,
}


def get_task_function(task_name: str) -> Optional[callable]:
    """根据任务名获取对应的函数"""
    return TASK_REGISTRY.get(task_name)
