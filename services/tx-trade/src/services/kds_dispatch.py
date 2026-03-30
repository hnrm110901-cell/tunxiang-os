"""KDS 档口分单引擎 — 将订单菜品分配到对应出品部门

根据 dish_dept_mappings 配置，自动将每道菜路由到正确的档口（热菜间/凉菜间/面点等），
生成档口级任务列表供 KDS 终端消费。

分单完成后自动：
1. 回写 OrderItem.kds_station（自动映射，前端无需手动传）
2. 为每个档口生成 ESC/POS 厨打单并发送到对应网络打印机
3. 通过 WebSocket 推送新票据到 KDS 终端
"""
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select, func, update, and_
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Order, OrderItem
from ..models.production_dept import ProductionDept, DishDeptMapping

logger = structlog.get_logger()

# ─── KDS 任务状态 ───

TASK_STATUS_PENDING = "pending"
TASK_STATUS_COOKING = "cooking"
TASK_STATUS_DONE = "done"
TASK_STATUS_CANCELLED = "cancelled"


async def dispatch_order_to_kds(
    order_id: str,
    order_items: list[dict],
    tenant_id: str,
    db: AsyncSession,
    *,
    table_number: str = "",
    order_no: str = "",
    auto_print: bool = True,
) -> dict:
    """将订单中的每道菜分配到对应档口，生成分单结果。

    自动完成菜品->出品部门映射，无需前端传 kitchen_station。

    Args:
        order_id: 订单ID
        order_items: [{"dish_id": ..., "item_name": ..., "quantity": ...,
                       "order_item_id": ..., "notes": ...}, ...]
        tenant_id: 租户ID
        db: 数据库会话
        table_number: 桌号（用于厨打单）
        order_no: 订单号（用于厨打单）
        auto_print: 是否自动发送厨打单到档口打印机

    Returns:
        {"dept_tasks": [{"dept_id": ..., "dept_name": ..., "printer_address": ...,
                         "items": [...], "priority": ...}]}
    """
    tid = uuid.UUID(tenant_id)
    log = logger.bind(order_id=order_id, tenant_id=tenant_id)
    log.info("kds_dispatch.start", item_count=len(order_items))

    # ── 1. 批量查询所有菜品的档口映射 ──
    dish_ids = [uuid.UUID(item["dish_id"]) for item in order_items if item.get("dish_id")]
    mappings: dict[uuid.UUID, uuid.UUID] = {}

    if dish_ids:
        stmt = select(DishDeptMapping.dish_id, DishDeptMapping.production_dept_id).where(
            and_(
                DishDeptMapping.tenant_id == tid,
                DishDeptMapping.dish_id.in_(dish_ids),
                DishDeptMapping.is_deleted == False,  # noqa: E712
            )
        )
        result = await db.execute(stmt)
        for row in result.all():
            mappings[row[0]] = row[1]

    # ── 2. 查询所有相关档口信息（含打印机地址） ──
    dept_ids = set(mappings.values())
    depts: dict[uuid.UUID, dict] = {}

    # 也查询默认档口（用于未映射菜品）
    all_dept_stmt = select(ProductionDept).where(
        and_(
            ProductionDept.tenant_id == tid,
            ProductionDept.is_deleted == False,  # noqa: E712
        )
    ).order_by(ProductionDept.sort_order)
    all_dept_result = await db.execute(all_dept_stmt)
    all_depts = all_dept_result.scalars().all()

    default_dept: dict | None = None
    for dept in all_depts:
        info = {
            "dept_id": str(dept.id),
            "dept_name": dept.dept_name,
            "dept_code": dept.dept_code,
            "printer_address": dept.printer_address,
            "sort_order": dept.sort_order,
        }
        depts[dept.id] = info
        # 第一个档口作为默认档口
        if default_dept is None:
            default_dept = info

    # ── 3. 按档口分组 ──
    dept_items: dict[str, list[dict]] = {}
    unmapped_items: list[dict] = []
    # 收集需要回写 kds_station 的 order_item_id -> dept_id 映射
    item_dept_map: dict[str, str] = {}

    for item in order_items:
        dish_id = uuid.UUID(item["dish_id"]) if item.get("dish_id") else None
        dept_id = mappings.get(dish_id) if dish_id else None

        task = {
            "task_id": str(uuid.uuid4()),
            "order_id": order_id,
            "order_item_id": item.get("order_item_id", ""),
            "dish_id": str(dish_id) if dish_id else None,
            "dish_name": item.get("item_name", ""),
            "quantity": item.get("quantity", 1),
            "notes": item.get("notes", ""),
            "status": TASK_STATUS_PENDING,
            "urgent": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        if dept_id and dept_id in depts:
            key = str(dept_id)
            dept_items.setdefault(key, []).append(task)
            if item.get("order_item_id"):
                item_dept_map[item["order_item_id"]] = key
        else:
            unmapped_items.append(task)

    # ── 4. 组装分单结果 ──
    dept_tasks = []
    for dept_id_str, items in dept_items.items():
        dept_info = depts.get(uuid.UUID(dept_id_str), {})
        dept_tasks.append({
            "dept_id": dept_id_str,
            "dept_name": dept_info.get("dept_name", "未知档口"),
            "printer_address": dept_info.get("printer_address"),
            "items": items,
            "priority": dept_info.get("sort_order", 99),
        })

    # 未映射菜品归入默认档口
    if unmapped_items:
        if default_dept:
            dept_tasks.append({
                "dept_id": default_dept["dept_id"],
                "dept_name": default_dept["dept_name"],
                "printer_address": default_dept.get("printer_address"),
                "items": unmapped_items,
                "priority": 999,
            })
            # 未映射菜品也回写 kds_station 到默认档口
            for item in unmapped_items:
                oii = item.get("order_item_id")
                if oii:
                    item_dept_map[oii] = default_dept["dept_id"]
        else:
            dept_tasks.append({
                "dept_id": "default",
                "dept_name": "默认档口",
                "printer_address": None,
                "items": unmapped_items,
                "priority": 999,
            })

    # 按优先级排序
    dept_tasks.sort(key=lambda x: x["priority"])

    # ── 5. 回写 OrderItem.kds_station + sent_to_kds_flag ──
    for order_item_id, dept_id_str in item_dept_map.items():
        try:
            stmt = (
                update(OrderItem)
                .where(
                    and_(
                        OrderItem.id == uuid.UUID(order_item_id),
                        OrderItem.tenant_id == tid,
                    )
                )
                .values(kds_station=dept_id_str, sent_to_kds_flag=True)
            )
            await db.execute(stmt)
        except (ValueError, AttributeError) as exc:
            log.warning("kds_dispatch.update_item_failed", order_item_id=order_item_id, error=str(exc))
    await db.flush()

    # ── 6. 自动发送厨打单到各档口打印机 ──
    if auto_print:
        # 延迟导入避免循环依赖
        from .kitchen_print_service import print_kitchen_tickets_for_dispatch
        _tbl = table_number
        _ono = order_no

        # 如果调用方没传桌号/单号，尝试从订单表获取
        if not _tbl or not _ono:
            try:
                order_stmt = select(Order.table_number, Order.order_no).where(
                    and_(Order.id == uuid.UUID(order_id), Order.tenant_id == tid)
                )
                order_row = (await db.execute(order_stmt)).one_or_none()
                if order_row:
                    _tbl = _tbl or order_row[0] or ""
                    _ono = _ono or order_row[1] or ""
            except (ValueError, AttributeError):
                pass

        try:
            await print_kitchen_tickets_for_dispatch(dept_tasks, _ono, _tbl)
        except (OSError, ConnectionError, TimeoutError) as e:
            log.error("kds_dispatch.print_failed", error=str(e), exc_info=True)

    # ── 7. 同桌同出协同 — 计算延迟开始时间 ──
    from .cooking_scheduler import coordinate_same_table

    all_tasks = [task for dept in dept_tasks for task in dept["items"]]
    coordination = await coordinate_same_table(order_id, all_tasks, db)

    # 将 start_delay 和 target_completion 写入每个任务的 metadata
    coord_map = {c["task_id"]: c for c in coordination}
    for dept in dept_tasks:
        for task in dept["items"]:
            coord = coord_map.get(task["task_id"])
            if coord:
                task["metadata"] = {
                    **(task.get("metadata") or {}),
                    "start_delay_seconds": coord["start_delay_seconds"],
                    "target_completion": coord["target_completion"],
                    "estimated_seconds": coord["estimated_seconds"],
                }

    log.info("kds_dispatch.done", dept_count=len(dept_tasks), total_tasks=sum(len(d["items"]) for d in dept_tasks))
    return {"dept_tasks": dept_tasks}


async def get_dept_queue(
    dept_id: str,
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> list[dict]:
    """获取某档口当前待出品队列。

    查询该档口下所有 pending/cooking 状态的任务，按创建时间排序（urgent 优先）。
    """
    tid = uuid.UUID(tenant_id)
    log = logger.bind(dept_id=dept_id, store_id=store_id, tenant_id=tenant_id)

    # 查询该档口的 pending/cooking 订单项
    # 通过 OrderItem.kds_station 关联档口
    stmt = (
        select(OrderItem, Order.order_no, Order.table_number)
        .join(Order, OrderItem.order_id == Order.id)
        .where(
            and_(
                Order.tenant_id == tid,
                Order.store_id == uuid.UUID(store_id),
                OrderItem.kds_station == dept_id,
                OrderItem.sent_to_kds_flag == True,  # noqa: E712
                Order.is_deleted == False,  # noqa: E712
            )
        )
        .order_by(OrderItem.created_at.asc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    queue = []
    for item, order_no, table_no in rows:
        queue.append({
            "order_item_id": str(item.id),
            "order_id": str(item.order_id),
            "order_no": order_no,
            "table_number": table_no,
            "dish_id": str(item.dish_id) if item.dish_id else None,
            "dish_name": item.item_name,
            "quantity": item.quantity,
            "notes": item.notes,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        })

    log.info("kds_dispatch.get_dept_queue", queue_size=len(queue))
    return queue


async def get_store_kds_overview(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> list[dict]:
    """获取门店所有档口的实时负载概览。

    Returns:
        [{"dept_id": ..., "dept_name": ..., "pending": N, "cooking": N, "done_today": N}]
    """
    tid = uuid.UUID(tenant_id)
    log = logger.bind(store_id=store_id, tenant_id=tenant_id)

    # 查询该门店所有档口
    stmt = select(ProductionDept).where(
        and_(
            ProductionDept.tenant_id == tid,
            ProductionDept.is_deleted == False,  # noqa: E712
        )
    ).order_by(ProductionDept.sort_order)
    result = await db.execute(stmt)
    depts = result.scalars().all()

    overview = []
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    for dept in depts:
        dept_id_str = str(dept.id)

        # 统计待出品数量（kds_station 匹配且 sent_to_kds_flag = True）
        pending_stmt = select(func.count()).select_from(OrderItem).join(
            Order, OrderItem.order_id == Order.id
        ).where(
            and_(
                Order.tenant_id == tid,
                Order.store_id == uuid.UUID(store_id),
                OrderItem.kds_station == dept_id_str,
                OrderItem.sent_to_kds_flag == True,  # noqa: E712
                Order.is_deleted == False,  # noqa: E712
            )
        )
        pending_result = await db.execute(pending_stmt)
        pending_count = pending_result.scalar() or 0

        overview.append({
            "dept_id": dept_id_str,
            "dept_name": dept.dept_name,
            "dept_code": dept.dept_code,
            "printer_address": dept.printer_address,
            "pending": pending_count,
            "sort_order": dept.sort_order,
        })

    log.info("kds_dispatch.store_overview", store_id=store_id, dept_count=len(overview))
    return overview


async def resolve_dept_for_dish(
    dish_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict | None:
    """查询单个菜品对应的档口信息（供加菜等场景使用）。

    Returns:
        {"dept_id": ..., "dept_name": ..., "printer_address": ...} or None
    """
    tid = uuid.UUID(tenant_id)

    stmt = (
        select(DishDeptMapping.production_dept_id)
        .where(
            and_(
                DishDeptMapping.tenant_id == tid,
                DishDeptMapping.dish_id == uuid.UUID(dish_id),
                DishDeptMapping.is_deleted == False,  # noqa: E712
            )
        )
    )
    result = await db.execute(stmt)
    row = result.one_or_none()

    if not row:
        return None

    dept_stmt = select(ProductionDept).where(
        and_(
            ProductionDept.id == row[0],
            ProductionDept.tenant_id == tid,
            ProductionDept.is_deleted == False,  # noqa: E712
        )
    )
    dept_result = await db.execute(dept_stmt)
    dept = dept_result.scalar_one_or_none()

    if not dept:
        return None

    return {
        "dept_id": str(dept.id),
        "dept_name": dept.dept_name,
        "printer_address": dept.printer_address,
    }
