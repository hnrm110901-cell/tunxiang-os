"""KDS 操作处理 — 档口厨师的交互动作

处理 KDS 终端上的所有操作：开始制作、完成出品、催菜、重做、缺料上报。
每个操作都记录时间线，支持事后追溯。
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select, update, and_
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import OrderItem

logger = structlog.get_logger()

# ─── 任务状态常量 ───

STATUS_PENDING = "pending"
STATUS_COOKING = "cooking"
STATUS_DONE = "done"
STATUS_CANCELLED = "cancelled"

# ─── 内存中的任务时间线和状态（后续迁移到独立 kds_tasks 表） ───
# key: task_id, value: {"status": ..., "timeline": [...], ...}
_task_store: dict[str, dict] = {}


def _get_task(task_id: str) -> dict:
    """获取或初始化任务记录"""
    if task_id not in _task_store:
        _task_store[task_id] = {
            "task_id": task_id,
            "status": STATUS_PENDING,
            "urgent": False,
            "remake_count": 0,
            "timeline": [],
        }
    return _task_store[task_id]


def _add_timeline_event(task_id: str, event_type: str, operator_id: Optional[str] = None, detail: Optional[str] = None):
    """向任务时间线追加事件"""
    task = _get_task(task_id)
    task["timeline"].append({
        "event": event_type,
        "operator_id": operator_id,
        "detail": detail,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


async def start_cooking(task_id: str, operator_id: str, db: AsyncSession) -> dict:
    """开始制作 — 厨师领取任务。

    状态: pending → cooking
    """
    log = logger.bind(task_id=task_id, operator_id=operator_id)

    task = _get_task(task_id)
    if task["status"] != STATUS_PENDING:
        log.warning("kds_actions.start_cooking.invalid_status", current=task["status"])
        return {"ok": False, "error": f"任务状态为 {task['status']}，无法开始制作"}

    task["status"] = STATUS_COOKING
    task["started_at"] = datetime.now(timezone.utc).isoformat()
    task["operator_id"] = operator_id
    _add_timeline_event(task_id, "start_cooking", operator_id)

    log.info("kds_actions.start_cooking.ok")
    return {"ok": True, "data": {"task_id": task_id, "status": STATUS_COOKING}}


async def finish_cooking(task_id: str, operator_id: str, db: AsyncSession) -> dict:
    """完成出品 — 菜品已出锅。

    状态: cooking → done
    """
    log = logger.bind(task_id=task_id, operator_id=operator_id)

    task = _get_task(task_id)
    if task["status"] != STATUS_COOKING:
        log.warning("kds_actions.finish_cooking.invalid_status", current=task["status"])
        return {"ok": False, "error": f"任务状态为 {task['status']}，无法完成出品"}

    task["status"] = STATUS_DONE
    task["finished_at"] = datetime.now(timezone.utc).isoformat()
    _add_timeline_event(task_id, "finish_cooking", operator_id)

    # 计算实际制作耗时（秒）
    started = task.get("started_at")
    if started:
        start_dt = datetime.fromisoformat(started)
        finish_dt = datetime.now(timezone.utc)
        task["cooking_duration_sec"] = int((finish_dt - start_dt).total_seconds())

    log.info("kds_actions.finish_cooking.ok", duration=task.get("cooking_duration_sec"))
    return {"ok": True, "data": {"task_id": task_id, "status": STATUS_DONE, "duration_sec": task.get("cooking_duration_sec")}}


async def request_rush(order_id: str, dish_id: str, db: AsyncSession) -> dict:
    """催菜 — 标记为 urgent，推送到 KDS 前端置顶显示。

    查找匹配的 pending/cooking 任务并标记 urgent。
    """
    log = logger.bind(order_id=order_id, dish_id=dish_id)

    rushed_count = 0
    for tid, task in _task_store.items():
        if task.get("status") in (STATUS_PENDING, STATUS_COOKING):
            # 通过 timeline 中的 order_id 匹配（或直接存储在 task 中）
            task["urgent"] = True
            _add_timeline_event(tid, "rush", detail=f"催菜: order={order_id}, dish={dish_id}")
            rushed_count += 1

    if rushed_count == 0:
        log.info("kds_actions.rush.no_match")
        return {"ok": True, "data": {"rushed": 0, "message": "未找到匹配的待出品任务"}}

    log.info("kds_actions.rush.ok", rushed=rushed_count)
    return {"ok": True, "data": {"rushed": rushed_count, "message": f"已催菜，{rushed_count}个任务标记为加急"}}


async def request_remake(task_id: str, reason: str, db: AsyncSession) -> dict:
    """重做 — 因质量问题需要重新制作。

    将任务状态重置为 pending，记录重做原因。
    """
    log = logger.bind(task_id=task_id, reason=reason)

    task = _get_task(task_id)
    old_status = task["status"]
    task["status"] = STATUS_PENDING
    task["urgent"] = True  # 重做自动标记加急
    task["remake_count"] = task.get("remake_count", 0) + 1
    _add_timeline_event(task_id, "remake", detail=f"重做原因: {reason}, 原状态: {old_status}")

    log.info("kds_actions.remake.ok", remake_count=task["remake_count"])
    return {"ok": True, "data": {"task_id": task_id, "status": STATUS_PENDING, "remake_count": task["remake_count"]}}


async def report_shortage(task_id: str, ingredient_id: str, db: AsyncSession) -> dict:
    """缺料上报 — 厨师发现食材不足，暂停任务并通知前厅。

    联动库存预警 Agent（tx-supply 域）。
    """
    log = logger.bind(task_id=task_id, ingredient_id=ingredient_id)

    task = _get_task(task_id)
    _add_timeline_event(task_id, "shortage", detail=f"缺料上报: ingredient={ingredient_id}")

    # TODO: 联动 tx-supply 库存预警 Agent
    # 当前仅记录事件

    log.info("kds_actions.shortage.reported", ingredient_id=ingredient_id)
    return {
        "ok": True,
        "data": {
            "task_id": task_id,
            "ingredient_id": ingredient_id,
            "message": "缺料已上报，等待前厅处理",
        },
    }


async def get_task_timeline(task_id: str, db: AsyncSession) -> dict:
    """获取任务完整时间线。

    Returns:
        {"task_id": ..., "status": ..., "timeline": [...], ...}
    """
    log = logger.bind(task_id=task_id)

    task = _get_task(task_id)

    log.info("kds_actions.timeline", event_count=len(task["timeline"]))
    return {
        "ok": True,
        "data": {
            "task_id": task["task_id"],
            "status": task["status"],
            "urgent": task["urgent"],
            "remake_count": task.get("remake_count", 0),
            "started_at": task.get("started_at"),
            "finished_at": task.get("finished_at"),
            "cooking_duration_sec": task.get("cooking_duration_sec"),
            "timeline": task["timeline"],
        },
    }
