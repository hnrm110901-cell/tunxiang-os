"""KDS 操作处理 — 档口厨师的交互动作

处理 KDS 终端上的所有操作：开始制作、完成出品、催菜、重做、缺料上报。
每个操作都记录时间线，支持事后追溯。

催菜/重做时自动：
1. 通过 WebSocket 推送提醒到对应档口的 KDS 屏幕
2. 发送厨打单到该档口打印机
"""
import asyncio
import os
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog
from sqlalchemy import select, update, and_
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Order, OrderItem
from ..models.production_dept import ProductionDept

logger = structlog.get_logger()

# Mac mini WebSocket 推送地址
MAC_STATION_URL = os.getenv("MAC_STATION_URL", "http://localhost:8000")

# ─── 任务状态常量 ───

STATUS_PENDING = "pending"
STATUS_COOKING = "cooking"
STATUS_DONE = "done"
STATUS_CANCELLED = "cancelled"

# ─── 内存中的任务时间线和状态（后续迁移到独立 kds_tasks 表） ───
# key: task_id, value: {"status": ..., "timeline": [...], ...}
# 使用 OrderedDict 以便按插入顺序淘汰旧任务
_MAX_TASK_STORE_SIZE = 5000
_task_store: OrderedDict[str, dict] = OrderedDict()
_task_store_lock = asyncio.Lock()


def _get_task(task_id: str) -> dict:
    """获取或初始化任务记录。超过容量时淘汰最旧的已完成任务。"""
    if task_id not in _task_store:
        # 淘汰旧的已完成/取消任务，防止内存无限增长
        if len(_task_store) >= _MAX_TASK_STORE_SIZE:
            to_remove: list[str] = []
            for tid, t in _task_store.items():
                if t["status"] in (STATUS_DONE, STATUS_CANCELLED):
                    to_remove.append(tid)
                if len(_task_store) - len(to_remove) < _MAX_TASK_STORE_SIZE:
                    break
            for tid in to_remove:
                del _task_store[tid]
            # 如果淘汰完成任务后仍然超限，淘汰最旧的任务
            while len(_task_store) >= _MAX_TASK_STORE_SIZE:
                _task_store.popitem(last=False)
        _task_store[task_id] = {
            "task_id": task_id,
            "status": STATUS_PENDING,
            "urgent": False,
            "remake_count": 0,
            "timeline": [],
        }
    else:
        # 移到末尾（标记为最近访问）
        _task_store.move_to_end(task_id)
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


async def _push_to_kds_station(station_id: str, message: dict) -> bool:
    """通过 Mac mini 的 KDS WebSocket 推送消息到指定档口。

    Mac mini kds_pusher 管理所有 KDS 终端的 WebSocket 连接。
    此方法通过 HTTP API 触发推送（Mac mini 侧转为 WebSocket 发送）。

    Args:
        station_id: 目标档口ID
        message: 消息体

    Returns:
        是否推送成功
    """
    log = logger.bind(station_id=station_id, message_type=message.get("type"))
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.post(
                f"{MAC_STATION_URL}/api/v1/kds/push",
                json={"station_id": station_id, "message": message},
            )
            if resp.status_code == 200:
                log.info("kds_actions.ws_push.ok")
                return True
            log.warning("kds_actions.ws_push.failed", status=resp.status_code)
            return False
    except httpx.ConnectError:
        log.warning("kds_actions.ws_push.mac_station_unavailable")
        return False
    except httpx.TimeoutException:
        log.warning("kds_actions.ws_push.timeout")
        return False


async def _resolve_task_context(
    order_id: str,
    dish_id: str | None,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """查询催菜/重做所需的上下文信息（档口、桌号、打印机地址等）。

    Returns:
        {"dept_id": ..., "dept_name": ..., "printer_address": ...,
         "table_number": ..., "order_no": ..., "dish_name": ..., "quantity": ...}
    """
    tid = uuid.UUID(tenant_id) if tenant_id else None
    ctx: dict = {
        "dept_id": None,
        "dept_name": "未知档口",
        "printer_address": None,
        "table_number": "",
        "order_no": "",
        "dish_name": "",
        "quantity": 1,
    }

    if not tid:
        return ctx

    # 查询订单基本信息
    try:
        order_stmt = select(Order.table_number, Order.order_no).where(
            and_(Order.id == uuid.UUID(order_id), Order.tenant_id == tid)
        )
        order_row = (await db.execute(order_stmt)).one_or_none()
        if order_row:
            ctx["table_number"] = order_row[0] or ""
            ctx["order_no"] = order_row[1] or ""
    except (ValueError, AttributeError):
        pass

    # 查询菜品对应的档口
    if dish_id:
        try:
            item_stmt = (
                select(OrderItem.kds_station, OrderItem.item_name, OrderItem.quantity)
                .where(
                    and_(
                        OrderItem.order_id == uuid.UUID(order_id),
                        OrderItem.dish_id == uuid.UUID(dish_id),
                        OrderItem.tenant_id == tid,
                        OrderItem.is_deleted == False,  # noqa: E712
                    )
                )
                .limit(1)
            )
            item_row = (await db.execute(item_stmt)).one_or_none()
            if item_row:
                kds_station = item_row[0]
                ctx["dish_name"] = item_row[1] or ""
                ctx["quantity"] = item_row[2] or 1
                ctx["dept_id"] = kds_station

                # 查询档口详情
                if kds_station:
                    try:
                        dept_stmt = select(ProductionDept).where(
                            and_(
                                ProductionDept.id == uuid.UUID(kds_station),
                                ProductionDept.tenant_id == tid,
                            )
                        )
                        dept = (await db.execute(dept_stmt)).scalar_one_or_none()
                        if dept:
                            ctx["dept_name"] = dept.dept_name
                            ctx["printer_address"] = dept.printer_address
                    except (ValueError, AttributeError):
                        pass
        except (ValueError, AttributeError):
            pass

    return ctx


async def start_cooking(task_id: str, operator_id: str, db: AsyncSession) -> dict:
    """开始制作 — 厨师领取任务。

    状态: pending -> cooking
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

    # 推送状态变更到 KDS
    dept_id = task.get("dept_id")
    if dept_id:
        await _push_to_kds_station(dept_id, {
            "type": "status_change",
            "ticket_id": task_id,
            "new_status": STATUS_COOKING,
            "operator_id": operator_id,
        })

    log.info("kds_actions.start_cooking.ok")
    return {"ok": True, "data": {"task_id": task_id, "status": STATUS_COOKING}}


async def finish_cooking(task_id: str, operator_id: str, db: AsyncSession) -> dict:
    """完成出品 — 菜品已出锅。

    状态: cooking -> done
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

    # 推送状态变更到 KDS
    dept_id = task.get("dept_id")
    if dept_id:
        await _push_to_kds_station(dept_id, {
            "type": "status_change",
            "ticket_id": task_id,
            "new_status": STATUS_DONE,
            "operator_id": operator_id,
            "duration_sec": task.get("cooking_duration_sec"),
        })

    log.info("kds_actions.finish_cooking.ok", duration=task.get("cooking_duration_sec"))
    return {"ok": True, "data": {"task_id": task_id, "status": STATUS_DONE, "duration_sec": task.get("cooking_duration_sec")}}


async def request_rush(
    order_id: str,
    dish_id: str,
    db: AsyncSession,
    *,
    tenant_id: str = "",
) -> dict:
    """催菜 — 标记为 urgent，推送催单到 KDS + 发送催单厨打单。

    查找匹配的 pending/cooking 任务并标记 urgent。
    同时：
    1. WebSocket 推送催单提醒到对应档口 KDS 屏幕（高亮 + 声音）
    2. 发送催单厨打单到该档口打印机（大字 "催" + 菜品名）
    """
    log = logger.bind(order_id=order_id, dish_id=dish_id)

    rushed_count = 0
    for tid, task in _task_store.items():
        if (
            task.get("order_id") == order_id
            and task.get("dish_id") == dish_id
            and task.get("status") in (STATUS_PENDING, STATUS_COOKING)
        ):
            task["urgent"] = True
            _add_timeline_event(tid, "rush", detail=f"催菜: order={order_id}, dish={dish_id}")
            rushed_count += 1

    # 查询上下文信息（档口、桌号等）
    ctx = await _resolve_task_context(order_id, dish_id, tenant_id, db)
    dept_id = ctx["dept_id"]

    # ── WebSocket 推送催单到 KDS ──
    if dept_id:
        await _push_to_kds_station(dept_id, {
            "type": "rush_order",
            "order_id": order_id,
            "dish_id": dish_id,
            "dish_name": ctx["dish_name"],
            "table_number": ctx["table_number"],
            "alert": True,
            "sound": "rush",
        })

    # ── 发送催单厨打单到档口打印机 ──
    if ctx["dish_name"]:
        from .kitchen_print_service import print_rush_ticket
        await print_rush_ticket(
            dept_name=ctx["dept_name"],
            table_number=ctx["table_number"],
            dish_name=ctx["dish_name"],
            quantity=ctx["quantity"],
            order_no=ctx["order_no"],
            printer_address=ctx["printer_address"],
        )

    if rushed_count == 0 and not ctx["dish_name"]:
        log.info("kds_actions.rush.no_match")
        return {"ok": True, "data": {"rushed": 0, "message": "未找到匹配的待出品任务"}}

    log.info("kds_actions.rush.ok", rushed=rushed_count, dept=ctx["dept_name"])
    return {
        "ok": True,
        "data": {
            "rushed": rushed_count,
            "dept_name": ctx["dept_name"],
            "dish_name": ctx["dish_name"],
            "message": f"已催菜「{ctx['dish_name']}」，已通知{ctx['dept_name']}",
        },
    }


async def request_remake(
    task_id: str,
    reason: str,
    db: AsyncSession,
    *,
    tenant_id: str = "",
) -> dict:
    """重做 — 因质量问题需要重新制作。

    将任务状态重置为 pending，记录重做原因。
    同时：
    1. WebSocket 推送重做提醒到对应档口 KDS 屏幕
    2. 发送重做厨打单到该档口打印机（大字 "重做" + 菜品名 + 原因）
    """
    log = logger.bind(task_id=task_id, reason=reason)

    task = _get_task(task_id)
    old_status = task["status"]
    task["status"] = STATUS_PENDING
    task["urgent"] = True  # 重做自动标记加急
    task["remake_count"] = task.get("remake_count", 0) + 1
    _add_timeline_event(task_id, "remake", detail=f"重做原因: {reason}, 原状态: {old_status}")

    # 获取任务关联信息
    order_id = task.get("order_id", "")
    dish_id = task.get("dish_id")
    dish_name = task.get("dish_name", "")
    dept_id = task.get("dept_id")
    dept_name = task.get("dept_name", "未知档口")
    table_number = task.get("table_number", "")
    order_no = task.get("order_no", "")
    printer_address = task.get("printer_address")

    # 如果 task 中没有完整信息，尝试从数据库查询
    if tenant_id and order_id and (not dept_id or dept_name == "未知档口"):
        ctx = await _resolve_task_context(order_id, dish_id, tenant_id, db)
        dept_id = dept_id or ctx["dept_id"]
        dept_name = ctx["dept_name"]
        printer_address = printer_address or ctx["printer_address"]
        table_number = table_number or ctx["table_number"]
        order_no = order_no or ctx["order_no"]
        dish_name = dish_name or ctx["dish_name"]

    # ── WebSocket 推送重做提醒到 KDS ──
    if dept_id:
        await _push_to_kds_station(dept_id, {
            "type": "remake_order",
            "task_id": task_id,
            "dish_name": dish_name,
            "reason": reason,
            "table_number": table_number,
            "remake_count": task["remake_count"],
            "alert": True,
            "sound": "remake",
        })

    # ── 发送重做厨打单到档口打印机 ──
    if dish_name:
        from .kitchen_print_service import print_remake_ticket
        await print_remake_ticket(
            dept_name=dept_name,
            table_number=table_number,
            dish_name=dish_name,
            reason=reason,
            order_no=order_no,
            printer_address=printer_address,
        )

    log.info("kds_actions.remake.ok", remake_count=task["remake_count"], dept=dept_name)
    return {
        "ok": True,
        "data": {
            "task_id": task_id,
            "status": STATUS_PENDING,
            "remake_count": task["remake_count"],
            "dept_name": dept_name,
            "message": f"已通知{dept_name}重做「{dish_name}」，原因: {reason}",
        },
    }


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
