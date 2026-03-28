"""KDS 档口分单引擎 — 将订单菜品分配到对应出品部门

根据 dish_dept_mappings 配置，自动将每道菜路由到正确的档口（热菜间/凉菜间/面点等），
生成档口级任务列表供 KDS 终端消费。
"""
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select, func, and_
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
) -> dict:
    """将订单中的每道菜分配到对应档口，生成分单结果。

    Args:
        order_id: 订单ID
        order_items: [{"dish_id": ..., "item_name": ..., "quantity": ..., "order_item_id": ...}, ...]
        tenant_id: 租户ID
        db: 数据库会话

    Returns:
        {"dept_tasks": [{"dept_id": ..., "dept_name": ..., "items": [...], "priority": ...}]}
    """
    tid = uuid.UUID(tenant_id)
    log = logger.bind(order_id=order_id, tenant_id=tenant_id)
    log.info("kds_dispatch.start", item_count=len(order_items))

    # 批量查询所有菜品的档口映射
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

    # 查询所有相关档口信息
    dept_ids = set(mappings.values())
    depts: dict[uuid.UUID, dict] = {}
    if dept_ids:
        stmt = select(ProductionDept).where(
            and_(
                ProductionDept.tenant_id == tid,
                ProductionDept.id.in_(dept_ids),
                ProductionDept.is_deleted == False,  # noqa: E712
            )
        )
        result = await db.execute(stmt)
        for dept in result.scalars().all():
            depts[dept.id] = {"dept_id": str(dept.id), "dept_name": dept.dept_name, "sort_order": dept.sort_order}

    # 按档口分组
    dept_items: dict[str, list[dict]] = {}
    unmapped_items: list[dict] = []

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
            "status": TASK_STATUS_PENDING,
            "urgent": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        if dept_id and dept_id in depts:
            key = str(dept_id)
            dept_items.setdefault(key, []).append(task)
        else:
            unmapped_items.append(task)

    # 组装分单结果
    dept_tasks = []
    for dept_id_str, items in dept_items.items():
        dept_info = depts.get(uuid.UUID(dept_id_str), {})
        dept_tasks.append({
            "dept_id": dept_id_str,
            "dept_name": dept_info.get("dept_name", "未知档口"),
            "items": items,
            "priority": dept_info.get("sort_order", 99),
        })

    # 未映射菜品归入"默认档口"
    if unmapped_items:
        dept_tasks.append({
            "dept_id": "default",
            "dept_name": "默认档口",
            "items": unmapped_items,
            "priority": 999,
        })

    # 按优先级排序
    dept_tasks.sort(key=lambda x: x["priority"])

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
            "pending": pending_count,
            "sort_order": dept.sort_order,
        })

    log.info("kds_dispatch.store_overview", store_id=store_id, dept_count=len(overview))
    return overview
