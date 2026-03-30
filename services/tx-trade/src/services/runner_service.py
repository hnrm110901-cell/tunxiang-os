"""传菜员(Runner)工作流服务

状态流转：pending → cooking → ready → delivering → served
新增状态：ready（出品完成等待传菜）/ delivering（传菜中）/ served（已送达）

职责：
- mark_ready:     KDS完成出品后将任务标记为ready，推送到RunnerStation
- pickup_dish:    传菜员领取任务，状态→delivering
- confirm_served: 送达确认，状态→served；检查全桌是否上齐后推通知到web-crew
- get_runner_queue: 按桌号聚合所有ready状态菜品，传菜员工作列表
- get_runner_history: 查询今日传菜记录
"""
import asyncio
import os
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog

logger = structlog.get_logger()

# Mac mini 地址（Runner Station WebSocket 推送 + web-crew 通知）
MAC_STATION_URL = os.getenv("MAC_STATION_URL", "http://localhost:8000")

# ─── 状态常量 ───

STATUS_PENDING = "pending"
STATUS_COOKING = "cooking"
STATUS_DONE = "done"        # KDS完成出品
STATUS_READY = "ready"      # 等待传菜员领取
STATUS_DELIVERING = "delivering"  # 传菜中
STATUS_SERVED = "served"    # 已送达

# ─── 内存任务存储 ───
# key: task_id, value: RunnerTask dict
# 与 kds_actions.py 共享逻辑：复用内存存储模式，后续可统一迁移到 kds_tasks 表

_MAX_STORE_SIZE = 5000
_runner_store: OrderedDict[str, dict] = OrderedDict()
_runner_store_lock = asyncio.Lock()


# ─── RunnerTask TypedDict（用于文档说明，不强制） ───

class RunnerTask:
    """传菜任务结构（参考字段）"""
    task_id: str
    status: str
    store_id: str
    table_number: str
    order_id: str
    tenant_id: str
    dish_name: str
    ready_at: Optional[str]
    pickup_at: Optional[str]
    served_at: Optional[str]
    runner_id: Optional[str]
    timeline: list


def _get_task(task_id: str) -> dict:
    """获取或初始化Runner任务记录。超过容量时淘汰已完成任务。"""
    if task_id not in _runner_store:
        if len(_runner_store) >= _MAX_STORE_SIZE:
            to_remove: list[str] = []
            for tid, t in _runner_store.items():
                if t["status"] == STATUS_SERVED:
                    to_remove.append(tid)
                if len(_runner_store) - len(to_remove) < _MAX_STORE_SIZE:
                    break
            for tid in to_remove:
                del _runner_store[tid]
            while len(_runner_store) >= _MAX_STORE_SIZE:
                _runner_store.popitem(last=False)

        _runner_store[task_id] = {
            "task_id": task_id,
            "status": STATUS_PENDING,
            "store_id": "",
            "table_number": "",
            "order_id": "",
            "tenant_id": "",
            "dish_name": "",
            "ready_at": None,
            "pickup_at": None,
            "served_at": None,
            "runner_id": None,
            "timeline": [],
        }
    else:
        _runner_store.move_to_end(task_id)

    return _runner_store[task_id]


def _add_timeline_event(
    task_id: str,
    event_type: str,
    operator_id: Optional[str] = None,
    detail: Optional[str] = None,
) -> None:
    """向任务时间线追加事件"""
    task = _get_task(task_id)
    task["timeline"].append({
        "event": event_type,
        "operator_id": operator_id,
        "detail": detail,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


async def _push_to_runner_station(store_id: str, message: dict) -> bool:
    """推送消息到 RunnerStation（传菜员看板）WebSocket。

    通过 Mac mini HTTP API 触发 WebSocket 广播到 /ws/runner/{store_id}。
    """
    log = logger.bind(store_id=store_id, message_type=message.get("type"))
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.post(
                f"{MAC_STATION_URL}/api/v1/runner/push",
                json={"store_id": store_id, "message": message},
            )
            if resp.status_code == 200:
                log.info("runner_service.push_runner_station.ok")
                return True
            log.warning("runner_service.push_runner_station.failed", status=resp.status_code)
            return False
    except httpx.ConnectError:
        log.warning("runner_service.push_runner_station.mac_station_unavailable")
        return False
    except httpx.TimeoutException:
        log.warning("runner_service.push_runner_station.timeout")
        return False


async def _push_to_crew(store_id: str, message: dict) -> bool:
    """推送通知到 web-crew（服务员手机端）WebSocket。

    通过 Mac mini HTTP API 触发 WebSocket 广播到 /ws/crew/{store_id}。
    """
    log = logger.bind(store_id=store_id, message_type=message.get("type"))
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.post(
                f"{MAC_STATION_URL}/api/v1/crew/push",
                json={"store_id": store_id, "message": message},
            )
            if resp.status_code == 200:
                log.info("runner_service.push_crew.ok")
                return True
            log.warning("runner_service.push_crew.failed", status=resp.status_code)
            return False
    except httpx.ConnectError:
        log.warning("runner_service.push_crew.mac_station_unavailable")
        return False
    except httpx.TimeoutException:
        log.warning("runner_service.push_crew.timeout")
        return False


async def _check_table_all_served(order_id: str, tenant_id: str) -> bool:
    """检查同一订单的所有传菜任务是否全部served。

    遍历内存中属于同一 order_id + tenant_id 的任务，
    若不存在未served的任务则返回True。
    """
    for task in _runner_store.values():
        if task["order_id"] == order_id and task["tenant_id"] == tenant_id:
            if task["status"] not in (STATUS_SERVED,):
                return False
    return True


# ─── 核心业务函数 ───

async def mark_ready(task_id: str, operator_id: str) -> dict:
    """KDS完成出品时调用，将任务标记为ready并推送到RunnerStation。

    Args:
        task_id:     KDS任务ID
        operator_id: 操作人（厨师）ID

    Returns:
        {"ok": bool, "task": {...}}
    """
    log = logger.bind(task_id=task_id, operator_id=operator_id)
    async with _runner_store_lock:
        task = _get_task(task_id)
        task["status"] = STATUS_READY
        task["ready_at"] = datetime.now(timezone.utc).isoformat()
        _add_timeline_event(task_id, "mark_ready", operator_id)
        task_snapshot = dict(task)

    log.info("runner_service.mark_ready.ok", table=task_snapshot.get("table_number"))

    # 推送到 RunnerStation（非阻塞，失败不影响主流程）
    store_id = task_snapshot.get("store_id", "")
    if store_id:
        asyncio.create_task(
            _push_to_runner_station(
                store_id,
                {
                    "type": "dish_ready",
                    "task_id": task_id,
                    "table_number": task_snapshot.get("table_number", ""),
                    "dish_name": task_snapshot.get("dish_name", ""),
                    "ready_at": task_snapshot.get("ready_at"),
                },
            )
        )

    return {"ok": True, "task": task_snapshot}


async def pickup_dish(task_id: str, runner_id: str) -> dict:
    """传菜员领取菜品，状态→delivering。

    Args:
        task_id:   传菜任务ID
        runner_id: 传菜员ID

    Returns:
        {"ok": bool, "task": {...}} 或 {"ok": False, "error": "..."}
    """
    log = logger.bind(task_id=task_id, runner_id=runner_id)
    async with _runner_store_lock:
        task = _get_task(task_id)
        if task["status"] != STATUS_READY:
            log.warning(
                "runner_service.pickup.invalid_status",
                current_status=task["status"],
            )
            return {
                "ok": False,
                "error": f"任务状态错误：当前状态为 {task['status']}，只有 ready 状态才可领取",
            }

        task["status"] = STATUS_DELIVERING
        task["runner_id"] = runner_id
        task["pickup_at"] = datetime.now(timezone.utc).isoformat()
        _add_timeline_event(task_id, "pickup", runner_id)
        task_snapshot = dict(task)

    log.info("runner_service.pickup.ok", table=task_snapshot.get("table_number"))
    return {"ok": True, "task": task_snapshot}


async def confirm_served(task_id: str, runner_id: str) -> dict:
    """传菜员确认送达，状态→served。

    检查同一订单其他任务，若全部served则推送"全桌上齐"通知到web-crew。

    Args:
        task_id:   传菜任务ID
        runner_id: 传菜员ID

    Returns:
        {"ok": bool, "task": {...}, "table_all_served": bool}
        或 {"ok": False, "error": "..."}
    """
    log = logger.bind(task_id=task_id, runner_id=runner_id)
    async with _runner_store_lock:
        task = _get_task(task_id)
        if task["status"] != STATUS_DELIVERING:
            log.warning(
                "runner_service.confirm_served.invalid_status",
                current_status=task["status"],
            )
            return {
                "ok": False,
                "error": f"任务状态错误：当前状态为 {task['status']}，只有 delivering 状态才可确认送达",
            }

        task["status"] = STATUS_SERVED
        task["served_at"] = datetime.now(timezone.utc).isoformat()
        _add_timeline_event(task_id, "served", runner_id)
        task_snapshot = dict(task)

    order_id = task_snapshot.get("order_id", "")
    tenant_id = task_snapshot.get("tenant_id", "")
    store_id = task_snapshot.get("store_id", "")
    table_number = task_snapshot.get("table_number", "")

    log.info("runner_service.confirm_served.ok", table=table_number, order_id=order_id)

    # 检查全桌上齐
    table_all_served = False
    if order_id and tenant_id:
        table_all_served = await _check_table_all_served(order_id, tenant_id)
        if table_all_served:
            log.info("runner_service.table_all_served", table=table_number, order_id=order_id)
            if store_id:
                asyncio.create_task(
                    _push_to_crew(
                        store_id,
                        {
                            "type": "table_all_served",
                            "order_id": order_id,
                            "table_number": table_number,
                            "tenant_id": tenant_id,
                            "served_at": task_snapshot.get("served_at"),
                            "message": f"{table_number} 桌所有菜品已上齐",
                        },
                    )
                )

    return {
        "ok": True,
        "task": task_snapshot,
        "table_all_served": table_all_served,
    }


async def get_runner_queue(store_id: str, tenant_id: str) -> list[dict]:
    """获取传菜员待取菜列表，按桌号聚合所有ready状态菜品。

    Args:
        store_id:  门店ID
        tenant_id: 租户ID（强制隔离）

    Returns:
        按 ready_at 升序排列的 ready 状态任务列表
    """
    result = [
        dict(task)
        for task in _runner_store.values()
        if (
            task["status"] == STATUS_READY
            and task["store_id"] == store_id
            and task["tenant_id"] == tenant_id
        )
    ]
    # 按等待时间升序（出品最早的优先）
    result.sort(key=lambda t: t.get("ready_at") or "")
    return result


async def get_runner_history(store_id: str, tenant_id: str) -> list[dict]:
    """查询今日传菜记录（served状态）。

    Args:
        store_id:  门店ID
        tenant_id: 租户ID（强制隔离）

    Returns:
        今日已送达的任务列表，按 served_at 降序
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    result = [
        dict(task)
        for task in _runner_store.values()
        if (
            task["status"] == STATUS_SERVED
            and task["store_id"] == store_id
            and task["tenant_id"] == tenant_id
            and (task.get("served_at") or "").startswith(today)
        )
    ]
    result.sort(key=lambda t: t.get("served_at") or "", reverse=True)
    return result


async def register_runner_task(
    task_id: str,
    store_id: str,
    table_number: str,
    order_id: str,
    tenant_id: str,
    dish_name: str,
) -> dict:
    """注册传菜任务（KDS分单时调用，初始状态为pending）。

    Args:
        task_id:      任务ID（与KDS任务同ID）
        store_id:     门店ID
        table_number: 桌号
        order_id:     订单ID
        tenant_id:    租户ID
        dish_name:    菜品名称

    Returns:
        {"ok": bool, "task": {...}}
    """
    async with _runner_store_lock:
        task = _get_task(task_id)
        task["store_id"] = store_id
        task["table_number"] = table_number
        task["order_id"] = order_id
        task["tenant_id"] = tenant_id
        task["dish_name"] = dish_name
        task["status"] = STATUS_PENDING
        _add_timeline_event(task_id, "registered")
        task_snapshot = dict(task)

    logger.info(
        "runner_service.register_task.ok",
        task_id=task_id,
        table=table_number,
        tenant_id=tenant_id,
    )
    return {"ok": True, "task": task_snapshot}
