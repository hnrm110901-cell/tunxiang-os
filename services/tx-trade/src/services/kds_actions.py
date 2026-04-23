"""KDS 操作处理 — 档口厨师的交互动作

处理 KDS 终端上的所有操作：开始制作、完成出品、催菜、重做、缺料上报。
每个操作都记录时间线，支持事后追溯。

架构：
  L1 热缓存  — 内存 OrderedDict（5000条活跃任务，快速查询）
  L2 持久层  — PostgreSQL kds_tasks 表（所有任务，重启恢复）

催菜SLA闭环：
  request_rush()    — 限流检查（同一任务30分钟内≤2次）
  confirm_rush()    — 厨师确认+设置承诺时间 → 推送到web-crew
  check_rush_overdue() — 后台检查承诺超时，触发升级告警

催菜/重做时自动：
1. 通过 WebSocket 推送提醒到对应档口的 KDS 屏幕
2. 发送厨打单到该档口打印机
"""

import asyncio
import os
import uuid
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Order, OrderItem

from ..models.kds_task import KDSTask
from ..models.production_dept import ProductionDept

logger = structlog.get_logger()

# Mac mini WebSocket 推送地址
MAC_STATION_URL = os.getenv("MAC_STATION_URL", "http://localhost:8000")

# 催菜限流配置
RUSH_RATE_LIMIT_MAX = 2  # 每个滑动窗口内最大催菜次数
RUSH_RATE_LIMIT_WINDOW_MIN = 30  # 滑动窗口时长（分钟）

# ─── 任务状态常量 ───

STATUS_PENDING = "pending"
STATUS_COOKING = "cooking"
STATUS_DONE = "done"
STATUS_CANCELLED = "cancelled"

# ─── L1 热缓存（内存 OrderedDict） ───
# 仅存活跃任务（pending/cooking），重启后从DB恢复
# key: task_id(str), value: {"status": ..., "timeline": [...], ...}
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


def _add_timeline_event(
    task_id: str,
    event_type: str,
    operator_id: Optional[str] = None,
    detail: Optional[str] = None,
) -> None:
    """向任务时间线追加事件"""
    task = _get_task(task_id)
    task["timeline"].append(
        {
            "event": event_type,
            "operator_id": operator_id,
            "detail": detail,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )


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


async def _fetch_task_from_db(
    task_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> Optional[KDSTask]:
    """从DB查询任务，强制带tenant_id过滤。

    Args:
        task_id: 任务UUID字符串
        tenant_id: 租户UUID字符串
        db: 数据库会话

    Returns:
        KDSTask 或 None（不存在/不属于该租户）
    """
    try:
        tid = uuid.UUID(tenant_id)
        task_uuid = uuid.UUID(task_id)
    except ValueError as exc:
        logger.warning("kds_actions.fetch_task.invalid_uuid", error=str(exc), task_id=task_id, tenant_id=tenant_id)
        return None

    stmt = select(KDSTask).where(
        and_(
            KDSTask.id == task_uuid,
            KDSTask.tenant_id == tid,
            KDSTask.is_deleted == False,  # noqa: E712
        )
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _find_active_tasks_for_dish(
    order_id: str,
    dish_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> list[KDSTask]:
    """查找某订单+菜品的活跃任务（pending/cooking）。

    同时兼容内存缓存和DB查询：先查内存快速路径，DB作为回退。

    Args:
        order_id: 订单ID（字符串UUID）
        dish_id: 菜品ID（字符串UUID）
        tenant_id: 租户ID
        db: 数据库会话

    Returns:
        活跃KDS任务列表
    """
    # 先从L1内存缓存快速查找
    memory_tasks = []
    for tid_key, task in _task_store.items():
        if (
            task.get("order_id") == order_id
            and task.get("dish_id") == dish_id
            and task.get("status") in (STATUS_PENDING, STATUS_COOKING)
        ):
            memory_tasks.append(task)

    if memory_tasks:
        # 将内存缓存格式的dict包装为伪KDSTask对象，保持接口一致
        return [_MemoryTaskProxy(t) for t in memory_tasks]

    # L1未命中，回退到DB查询（重启后场景）
    try:
        tid = uuid.UUID(tenant_id)
    except ValueError as exc:
        logger.warning("kds_actions.find_tasks.invalid_tenant", error=str(exc))
        return []

    # 通过order_item表关联查找（order_item_id → order_id+dish_id）
    # 此处简化：查tenant+status，实际应通过order_item_id关联
    stmt = select(KDSTask).where(
        and_(
            KDSTask.tenant_id == tid,
            KDSTask.status.in_([STATUS_PENDING, STATUS_COOKING]),
            KDSTask.is_deleted == False,  # noqa: E712
        )
    )
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows)


class _MemoryTaskProxy:
    """将内存缓存dict包装为KDSTask-like对象，统一催菜限流接口。"""

    def __init__(self, task_dict: dict) -> None:
        self._d = task_dict

    @property
    def id(self) -> Optional[uuid.UUID]:
        raw = self._d.get("task_id")
        try:
            return uuid.UUID(raw) if raw else None
        except ValueError:
            return None

    @property
    def status(self) -> str:
        return self._d.get("status", STATUS_PENDING)

    @property
    def rush_count(self) -> int:
        return self._d.get("rush_count", 0)

    @rush_count.setter
    def rush_count(self, val: int) -> None:
        self._d["rush_count"] = val

    @property
    def last_rush_at(self) -> Optional[datetime]:
        raw = self._d.get("last_rush_at")
        if isinstance(raw, datetime):
            return raw
        if isinstance(raw, str):
            return datetime.fromisoformat(raw)
        return None

    @last_rush_at.setter
    def last_rush_at(self, val: Optional[datetime]) -> None:
        self._d["last_rush_at"] = val

    @property
    def promised_at(self) -> Optional[datetime]:
        raw = self._d.get("promised_at")
        if isinstance(raw, datetime):
            return raw
        if isinstance(raw, str):
            return datetime.fromisoformat(raw)
        return None

    @promised_at.setter
    def promised_at(self, val: Optional[datetime]) -> None:
        self._d["promised_at"] = val

    @property
    def dept_id(self) -> Optional[uuid.UUID]:
        raw = self._d.get("dept_id")
        try:
            return uuid.UUID(raw) if raw else None
        except ValueError:
            return None

    @property
    def tenant_id(self) -> Optional[uuid.UUID]:
        raw = self._d.get("tenant_id")
        try:
            return uuid.UUID(raw) if raw else None
        except ValueError:
            return None


def _check_rush_rate_limit(task: KDSTask) -> bool:
    """检查催菜是否超出限流阈值。

    规则：同一任务在 RUSH_RATE_LIMIT_WINDOW_MIN 分钟内最多催菜 RUSH_RATE_LIMIT_MAX 次。
    如果 last_rush_at 超过窗口期，计数自动重置（滑动窗口）。

    Returns:
        True — 允许催菜
        False — 已超限，拒绝
    """
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=RUSH_RATE_LIMIT_WINDOW_MIN)

    last_rush = task.last_rush_at
    if last_rush is None or last_rush < window_start:
        # 窗口已过期，计数归零，允许催菜
        return True

    # 在窗口内，检查次数
    return task.rush_count < RUSH_RATE_LIMIT_MAX


# ─── 公开操作接口 ───


async def start_cooking(
    task_id: str,
    operator_id: str,
    db: AsyncSession,
    *,
    tenant_id: str = "",
) -> dict:
    """开始制作 — 厨师领取任务。

    状态: pending -> cooking
    同步写入 kds_tasks 表。
    """
    log = logger.bind(task_id=task_id, operator_id=operator_id)

    # ── L2 DB 查询（权威状态） ──
    db_task = await _fetch_task_from_db(task_id, tenant_id, db)
    if db_task is None:
        log.warning("kds_actions.start_cooking.not_found")
        return {"ok": False, "error": f"任务 {task_id} 不存在或无权访问"}

    if db_task.status != STATUS_PENDING:
        log.warning("kds_actions.start_cooking.invalid_status", current=db_task.status)
        return {"ok": False, "error": f"任务状态为 {db_task.status}，无法开始制作"}

    # ── 更新DB ──
    now = datetime.now(timezone.utc)
    db_task.status = STATUS_COOKING
    db_task.started_at = now
    db_task.operator_id = uuid.UUID(operator_id) if operator_id and operator_id != "unknown" else None
    await db.commit()

    # ── 同步L1缓存 ──
    task = _get_task(task_id)
    task["status"] = STATUS_COOKING
    task["started_at"] = now.isoformat()
    task["operator_id"] = operator_id
    _add_timeline_event(task_id, "start_cooking", operator_id)

    # ── 推送状态变更到 KDS ──
    dept_id = str(db_task.dept_id) if db_task.dept_id else task.get("dept_id")
    if dept_id:
        await _push_to_kds_station(
            dept_id,
            {
                "type": "status_change",
                "ticket_id": task_id,
                "new_status": STATUS_COOKING,
                "operator_id": operator_id,
            },
        )

    log.info("kds_actions.start_cooking.ok")
    return {"ok": True, "data": {"task_id": task_id, "status": STATUS_COOKING}}


async def finish_cooking(
    task_id: str,
    operator_id: str,
    db: AsyncSession,
    *,
    tenant_id: str = "",
) -> dict:
    """完成出品 — 菜品已出锅。

    状态: cooking -> done
    更新 DB 记录。
    """
    log = logger.bind(task_id=task_id, operator_id=operator_id)

    # ── L2 DB 查询（权威状态） ──
    db_task = await _fetch_task_from_db(task_id, tenant_id, db)
    if db_task is None:
        log.warning("kds_actions.finish_cooking.not_found")
        return {"ok": False, "error": f"任务 {task_id} 不存在或无权访问"}

    if db_task.status != STATUS_COOKING:
        log.warning("kds_actions.finish_cooking.invalid_status", current=db_task.status)
        return {"ok": False, "error": f"任务状态为 {db_task.status}，无法完成出品"}

    # ── 计算制作耗时 ──
    now = datetime.now(timezone.utc)
    duration_sec: Optional[int] = None
    if db_task.started_at:
        duration_sec = int((now - db_task.started_at).total_seconds())

    # ── 更新DB ──
    db_task.status = STATUS_DONE
    db_task.completed_at = now
    await db.commit()

    # ── 同步L1缓存 ──
    task = _get_task(task_id)
    task["status"] = STATUS_DONE
    task["finished_at"] = now.isoformat()
    if duration_sec is not None:
        task["cooking_duration_sec"] = duration_sec
    _add_timeline_event(task_id, "finish_cooking", operator_id)

    # ── 推送状态变更到 KDS ──
    dept_id = str(db_task.dept_id) if db_task.dept_id else task.get("dept_id")
    if dept_id:
        await _push_to_kds_station(
            dept_id,
            {
                "type": "status_change",
                "ticket_id": task_id,
                "new_status": STATUS_DONE,
                "operator_id": operator_id,
                "duration_sec": duration_sec,
            },
        )

    # ── 回调堂食会话：更新出菜时间戳，推进状态到 dining ──
    dining_session_id = db_task.dining_session_id
    if dining_session_id:
        tenant_id_str = str(db_task.tenant_id) if db_task.tenant_id else tenant_id
        dish_qty = int(db_task.quantity or 1)

        async def _notify_session() -> None:
            from shared.ontology.src.database import async_session_factory

            from .dining_session_service import DiningSessionService

            async with async_session_factory() as notify_db:
                try:
                    svc = DiningSessionService(notify_db, tenant_id_str)
                    await svc.record_dish_served(dining_session_id, dish_count=dish_qty)
                    await notify_db.commit()
                except Exception as exc:  # noqa: BLE001 — 回调失败不阻断出餐确认
                    log.warning(
                        "kds_actions.finish_cooking.session_callback_failed",
                        session_id=str(dining_session_id),
                        error=str(exc),
                        exc_info=True,
                    )

        asyncio.create_task(_notify_session())

    log.info("kds_actions.finish_cooking.ok", duration=duration_sec)
    return {
        "ok": True,
        "data": {"task_id": task_id, "status": STATUS_DONE, "duration_sec": duration_sec},
    }


async def request_rush(
    order_id: str,
    dish_id: str,
    db: AsyncSession,
    *,
    tenant_id: str = "",
) -> dict:
    """催菜 — 标记为 urgent，推送催单到 KDS + 发送催单厨打单。

    限流规则：同一任务 30 分钟内最多催 2 次。
    超出限制时返回 ok=False，告知调用方限流原因。

    查找匹配的 pending/cooking 任务并标记 urgent。
    同时：
    1. WebSocket 推送催单提醒到对应档口 KDS 屏幕（高亮 + 声音）
    2. 发送催单厨打单到该档口打印机（大字 "催" + 菜品名）
    """
    log = logger.bind(order_id=order_id, dish_id=dish_id)

    # ── 查找活跃任务 ──
    active_tasks = await _find_active_tasks_for_dish(order_id, dish_id, tenant_id, db)

    # ── 限流检查（对每个匹配任务） ──
    if active_tasks:
        for task_obj in active_tasks:
            if not _check_rush_rate_limit(task_obj):
                window = RUSH_RATE_LIMIT_WINDOW_MIN
                max_count = RUSH_RATE_LIMIT_MAX
                log.warning(
                    "kds_actions.rush.rate_limited",
                    task_id=str(task_obj.id),
                    rush_count=task_obj.rush_count,
                )
                return {
                    "ok": False,
                    "error": (f"催菜限流：{window}分钟内最多催{max_count}次，请稍后再试"),
                }

    # ── 标记urgent + 更新限流计数 ──
    rushed_count = 0
    now = datetime.now(timezone.utc)
    for task_obj in active_tasks:
        task_id_str = str(task_obj.id) if task_obj.id else None

        # 更新内存缓存
        if task_id_str and task_id_str in _task_store:
            mem_task = _task_store[task_id_str]
            mem_task["urgent"] = True
            now_iso = now.isoformat()
            # 检查窗口是否过期，过期则重置计数
            last_rush = task_obj.last_rush_at
            window_start = now - timedelta(minutes=RUSH_RATE_LIMIT_WINDOW_MIN)
            if last_rush is None or last_rush < window_start:
                mem_task["rush_count"] = 1
            else:
                mem_task["rush_count"] = task_obj.rush_count + 1
            mem_task["last_rush_at"] = now_iso
            if task_id_str:
                _add_timeline_event(
                    task_id_str,
                    "rush",
                    detail=f"催菜: order={order_id}, dish={dish_id}",
                )

        # 更新DB（仅KDSTask实例，_MemoryTaskProxy不直接写DB）
        if isinstance(task_obj, KDSTask):
            window_start = now - timedelta(minutes=RUSH_RATE_LIMIT_WINDOW_MIN)
            last_rush = task_obj.last_rush_at
            if last_rush is None or last_rush < window_start:
                task_obj.rush_count = 1
            else:
                task_obj.rush_count = task_obj.rush_count + 1
            task_obj.last_rush_at = now
            task_obj.priority = "rush"

        rushed_count += 1

    if isinstance(active_tasks[0] if active_tasks else None, KDSTask):
        await db.commit()

    # ── 查询上下文信息（档口、桌号等） ──
    ctx = await _resolve_task_context(order_id, dish_id, tenant_id, db)
    dept_id = ctx["dept_id"]

    # ── WebSocket 推送催单到 KDS ──
    if dept_id:
        await _push_to_kds_station(
            dept_id,
            {
                "type": "rush_order",
                "order_id": order_id,
                "dish_id": dish_id,
                "dish_name": ctx["dish_name"],
                "table_number": ctx["table_number"],
                "alert": True,
                "sound": "rush",
            },
        )

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


async def confirm_rush(
    task_id: str,
    promised_minutes: int,
    operator_id: str,
    db: AsyncSession,
    *,
    tenant_id: str = "",
) -> dict:
    """厨师确认催菜 + 设置承诺完成时间。

    只有 pending/cooking 状态的任务可以确认催菜。
    承诺时间写入DB并推送到web-crew（通过KDS WebSocket）。

    Args:
        task_id: 任务ID
        promised_minutes: 承诺在多少分钟内完成
        operator_id: 操作厨师ID
        db: 数据库会话
        tenant_id: 租户ID

    Returns:
        {"ok": True, "data": {"task_id": ..., "promised_at": ..., "promised_minutes": ...}}
    """
    log = logger.bind(task_id=task_id, promised_minutes=promised_minutes)

    # ── 从DB获取任务（权威状态） ──
    db_task = await _fetch_task_from_db(task_id, tenant_id, db)
    if db_task is None:
        log.warning("kds_actions.confirm_rush.not_found")
        return {"ok": False, "error": f"任务 {task_id} 不存在或无权访问"}

    if db_task.status not in (STATUS_PENDING, STATUS_COOKING):
        log.warning("kds_actions.confirm_rush.invalid_status", current=db_task.status)
        return {
            "ok": False,
            "error": f"任务状态为 {db_task.status}，只有待制作/制作中的任务可确认催菜",
        }

    # ── 计算承诺时间并写入DB ──
    now = datetime.now(timezone.utc)
    promised_at = now + timedelta(minutes=promised_minutes)
    db_task.promised_at = promised_at
    db_task.priority = "rush"
    await db.commit()

    # ── 同步L1缓存 ──
    if task_id in _task_store:
        _task_store[task_id]["promised_at"] = promised_at.isoformat()
        _task_store[task_id]["priority"] = "rush"
    _add_timeline_event(
        task_id,
        "rush_confirmed",
        operator_id=operator_id,
        detail=f"承诺{promised_minutes}分钟内完成，promised_at={promised_at.isoformat()}",
    )

    # ── 推送承诺时间到 KDS / web-crew ──
    dept_id = str(db_task.dept_id) if db_task.dept_id else None
    if dept_id:
        await _push_to_kds_station(
            dept_id,
            {
                "type": "rush_confirmed",
                "task_id": task_id,
                "operator_id": operator_id,
                "promised_at": promised_at.isoformat(),
                "promised_minutes": promised_minutes,
            },
        )

    log.info("kds_actions.confirm_rush.ok", promised_at=promised_at.isoformat())
    return {
        "ok": True,
        "data": {
            "task_id": task_id,
            "promised_at": promised_at.isoformat(),
            "promised_minutes": promised_minutes,
        },
    }


async def check_rush_overdue(tenant_id: str, db: AsyncSession) -> dict:
    """后台检查承诺时间已到期但任务仍未完成的任务，触发升级告警。

    设计用于定时任务（每分钟）或接口轮询调用。
    查询条件：promised_at < NOW() AND status IN (pending, cooking)。

    Returns:
        {"ok": True, "data": {"overdue_count": int, "task_ids": [...]}}
    """
    log = logger.bind(tenant_id=tenant_id)

    try:
        tid = uuid.UUID(tenant_id)
    except ValueError as exc:
        log.error("kds_actions.check_rush_overdue.invalid_tenant", error=str(exc))
        return {"ok": False, "error": f"无效的 tenant_id: {tenant_id}"}

    now = datetime.now(timezone.utc)

    stmt = select(KDSTask).where(
        and_(
            KDSTask.tenant_id == tid,
            KDSTask.promised_at.isnot(None),
            KDSTask.promised_at < now,
            KDSTask.status.in_([STATUS_PENDING, STATUS_COOKING]),
            KDSTask.is_deleted == False,  # noqa: E712
        )
    )
    overdue_tasks = (await db.execute(stmt)).scalars().all()

    overdue_ids: list[str] = []
    for task in overdue_tasks:
        task_id_str = str(task.id)
        overdue_ids.append(task_id_str)
        dept_id = str(task.dept_id) if task.dept_id else None

        overdue_sec = int((now - task.promised_at).total_seconds())
        log.warning(
            "kds_actions.rush_overdue",
            task_id=task_id_str,
            overdue_sec=overdue_sec,
            rush_count=task.rush_count,
        )

        # ── 推送升级告警到档口KDS ──
        if dept_id:
            await _push_to_kds_station(
                dept_id,
                {
                    "type": "rush_overdue_alert",
                    "task_id": task_id_str,
                    "promised_at": task.promised_at.isoformat(),
                    "overdue_sec": overdue_sec,
                    "rush_count": task.rush_count,
                    "alert": True,
                    "sound": "overdue",
                },
            )

        # ── 同步L1缓存标记 ──
        if task_id_str in _task_store:
            _task_store[task_id_str]["rush_overdue"] = True
            _add_timeline_event(
                task_id_str,
                "rush_overdue_alert",
                detail=f"承诺时间到期超{overdue_sec}秒未完成",
            )

    log.info("kds_actions.check_rush_overdue.done", overdue_count=len(overdue_ids))
    return {
        "ok": True,
        "data": {"overdue_count": len(overdue_ids), "task_ids": overdue_ids},
    }


async def recover_active_tasks(tenant_id: str, db: AsyncSession) -> dict:
    """Mac mini重启后从DB恢复活跃任务到L1内存缓存。

    只恢复 pending/cooking 状态的任务，跳过 done/cancelled。
    设计在服务启动时调用一次。

    Returns:
        {"ok": True, "data": {"recovered": int}}
    """
    log = logger.bind(tenant_id=tenant_id)

    try:
        tid = uuid.UUID(tenant_id)
    except ValueError as exc:
        log.error("kds_actions.recover_active_tasks.invalid_tenant", error=str(exc))
        return {"ok": False, "error": f"无效的 tenant_id: {tenant_id}"}

    stmt = select(KDSTask).where(
        and_(
            KDSTask.tenant_id == tid,
            KDSTask.status.in_([STATUS_PENDING, STATUS_COOKING]),
            KDSTask.is_deleted == False,  # noqa: E712
        )
    )
    active_tasks = (await db.execute(stmt)).scalars().all()

    recovered = 0
    for task in active_tasks:
        task_id_str = str(task.id)
        # 写入L1缓存
        _task_store[task_id_str] = {
            "task_id": task_id_str,
            "status": task.status,
            "urgent": task.priority == "rush",
            "remake_count": task.remake_count,
            "rush_count": task.rush_count,
            "last_rush_at": task.last_rush_at.isoformat() if task.last_rush_at else None,
            "promised_at": task.promised_at.isoformat() if task.promised_at else None,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "dept_id": str(task.dept_id) if task.dept_id else None,
            "tenant_id": str(task.tenant_id),
            "timeline": [],
        }
        recovered += 1

    log.info("kds_actions.recover_active_tasks.done", recovered=recovered)
    return {"ok": True, "data": {"recovered": recovered}}


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

    # ── 同步更新DB ──
    if tenant_id:
        db_task = await _fetch_task_from_db(task_id, tenant_id, db)
        if db_task is not None:
            db_task.status = STATUS_PENDING
            db_task.priority = "rush"
            db_task.remake_count = task["remake_count"]
            db_task.remake_reason = reason
            await db.commit()

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
        await _push_to_kds_station(
            dept_id,
            {
                "type": "remake_order",
                "task_id": task_id,
                "dish_name": dish_name,
                "reason": reason,
                "table_number": table_number,
                "remake_count": task["remake_count"],
                "alert": True,
                "sound": "remake",
            },
        )

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
            "promised_at": task.get("promised_at"),
            "rush_count": task.get("rush_count", 0),
            "timeline": task["timeline"],
        },
    }
