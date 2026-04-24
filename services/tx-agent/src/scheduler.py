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

# ─── Feature Flag SDK（可选依赖，ImportError时全部Flag默认为enabled）───
try:
    from shared.feature_flags import is_enabled as _ff_is_enabled
    from shared.feature_flags.flag_names import AgentFlags as _AgentFlags

    _FEATURE_FLAGS_AVAILABLE = True
except ImportError:
    _FEATURE_FLAGS_AVAILABLE = False
    logger.warning(
        "feature_flags_sdk_not_available",
        reason="import failed, all agent flags default to enabled",
    )


def _agent_flag_enabled(flag: str) -> bool:
    """检查Agent Feature Flag是否开启。
    SDK不可用时返回True（降级为全部开启），不影响现有逻辑。
    """
    if not _FEATURE_FLAGS_AVAILABLE:
        return True
    return _ff_is_enabled(flag)


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
    # ─── 运营专项Agent定时任务 ───
    "closing_pre_check": {
        "hour": 21,
        "minute": 30,
        "task": "closing_pre_check_all_stores",
        "description": "闭店预检（闭店前30分钟）：未结单/未闭班/现金差异检测",
    },
    "closing_daily_brief": {
        "hour": 22,
        "minute": 30,
        "task": "generate_closing_reports",
        "description": "生成闭店报告 + AI经营日报",
    },
    "billing_daily_audit": {
        "hour": 23,
        "minute": 0,
        "task": "billing_daily_risk_scan",
        "description": "收银异常日终审计：反结账/漏单/挂账超期汇总",
    },
    # ─── Phase S4: 记忆进化闭环定时任务 ───
    "memory_evolution": {
        "hour": 2,
        "minute": 0,
        "task": "run_memory_evolution",
        "description": "每日记忆进化：信号分析+偏好推断+记忆写入",
    },
    "memory_consolidation": {
        "hour": 3,
        "minute": 30,
        "task": "run_memory_consolidation",
        "description": "每日记忆整合：衰减+整合+清理过期记忆",
    },
    # ─── Phase S3: AI运营教练定时任务 ───
    "baseline_update": {
        "hour": 3,
        "minute": 0,
        "task": "run_baseline_update",
        "description": "每周基线更新：基于过去4周数据更新门店基线（周一执行）",
    },
}

# ─── 高频定时任务（秒级间隔，需要独立调度器运行） ───

INTERVAL_SCHEDULES: dict[str, dict[str, Any]] = {
    "kitchen_overtime_scan": {
        "interval_seconds": 60,
        "task": "scan_kitchen_overtime_items",
        "description": "后厨超时扫描：每60秒检测所有门店的超时出餐项",
        "agent_id": "kitchen_overtime",
        "action": "scan_overtime_items",
    },
    "queue_wait_update": {
        "interval_seconds": 120,
        "task": "update_queue_wait_predictions",
        "description": "排队等位时间更新：每2分钟刷新所有门店的等位预测",
        "agent_id": "queue_seating",
        "action": "predict_wait_time",
    },
    # ─── Phase S1: SOP节拍定时任务 ───
    "sop_tick": {
        "interval_seconds": 900,
        "task": "run_sop_tick",
        "description": "SOP 15分钟节拍：检查所有门店的待执行/超时任务",
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
        timeline.append(
            {
                "name": name,
                "time": f"{config['hour']:02d}:{config['minute']:02d}",
                "task": config["task"],
                "description": config.get("description", ""),
            }
        )
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
    # Feature Flag 检查：AgentFlags.HR_SHIFT_SUGGEST
    # 关闭时跳过排班建议生成，降级为仅记录日志，不影响其他计划生成逻辑
    if not _agent_flag_enabled(
        _AgentFlags.HR_SHIFT_SUGGEST if _FEATURE_FLAGS_AVAILABLE else "agent.hr.shift_suggest.enable"
    ):
        logger.info(
            "hr_shift_suggest_agent_disabled",
            reason="feature_flag_disabled",
            flag="agent.hr.shift_suggest.enable",
        )
        return []

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
    # Feature Flag 检查：AgentFlags.HR_SHIFT_AUTO_EXECUTE（高风险 — L2自治级别）
    # 关闭时跳过自动执行，计划停留在 approved 状态等待人工处理
    # 注意：此Flag默认关闭，仅L2级别门店经三级审批后方可开启
    if not _agent_flag_enabled(
        _AgentFlags.HR_SHIFT_AUTO_EXECUTE if _FEATURE_FLAGS_AVAILABLE else "agent.hr.shift_suggest.auto_execute"
    ):
        logger.info(
            "hr_shift_auto_execute_disabled",
            reason="feature_flag_disabled",
            flag="agent.hr.shift_suggest.auto_execute",
            pending_plans=len(approved_plans),
        )
        return []

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


# ─── APScheduler 定时任务注册（Phase S1-S4 新增） ───
# 以下函数在 lifespan 中由 APScheduler 调用
# 使用 lazy import 避免循环依赖


async def _run_sop_tick() -> None:
    """SOP 15分钟节拍 — 检查所有门店的待执行/超时任务"""
    from .workers.sop_tick_worker import SOPTickWorker

    worker = SOPTickWorker()
    await worker.run()


async def _run_memory_consolidation() -> None:
    """每日记忆整合（凌晨3:30）— 衰减 + 整合 + 清理过期记忆"""
    from .workers.memory_consolidation_worker import MemoryConsolidationWorker

    worker = MemoryConsolidationWorker()
    await worker.run()


async def _run_memory_evolution() -> None:
    """每日记忆进化（凌晨2:00）— 信号分析 + 偏好推断 + 记忆写入"""
    from .workers.memory_evolution_worker import MemoryEvolutionWorker

    worker = MemoryEvolutionWorker()
    await worker.run()


async def _run_baseline_update() -> None:
    """每周基线更新（周一凌晨3:00）— 基于过去4周数据更新门店基线"""
    from .workers.baseline_updater_worker import BaselineUpdaterWorker

    worker = BaselineUpdaterWorker()
    await worker.run()


def register_apscheduler_jobs(_scheduler: Any) -> None:
    """向 APScheduler 实例注册所有定时任务

    调用方式（在 lifespan 中）：
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        scheduler = AsyncIOScheduler()
        register_apscheduler_jobs(scheduler)
        scheduler.start()

    Args:
        _scheduler: APScheduler 的 AsyncIOScheduler 实例
    """
    import asyncio

    # SOP 15分钟节拍
    _scheduler.add_job(
        lambda: asyncio.create_task(_run_sop_tick()),
        "interval",
        minutes=15,
        id="sop_tick",
        replace_existing=True,
    )

    # 每日记忆进化（凌晨2:00）
    _scheduler.add_job(
        lambda: asyncio.create_task(_run_memory_evolution()),
        "cron",
        hour=2,
        minute=0,
        id="memory_evolution",
        replace_existing=True,
    )

    # 每日记忆整合（凌晨3:30）
    _scheduler.add_job(
        lambda: asyncio.create_task(_run_memory_consolidation()),
        "cron",
        hour=3,
        minute=30,
        id="memory_consolidation",
        replace_existing=True,
    )

    # 每周基线更新（周一凌晨3:00）
    _scheduler.add_job(
        lambda: asyncio.create_task(_run_baseline_update()),
        "cron",
        day_of_week="mon",
        hour=3,
        minute=0,
        id="baseline_update",
        replace_existing=True,
    )

    logger.info(
        "apscheduler_jobs_registered",
        jobs=["sop_tick", "memory_evolution", "memory_consolidation", "baseline_update"],
    )
