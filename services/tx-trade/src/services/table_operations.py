"""桌台操作服务 — 转台/并台/拆台/清台/预留/桌态看板

所有操作记录操作日志，金额单位统一为分(fen)。
桌台状态流: idle(empty) -> reserved -> occupied(dining) -> cleaning(pending_cleanup) -> idle
"""
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.tables import Table
from .state_machine import can_table_transition, TABLE_STATES

logger = structlog.get_logger()


# ─── 操作日志记录 ───


async def _log_operation(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    op_type: str,
    detail: dict,
) -> dict:
    """记录桌台操作日志（写入 Table.config 的 op_log 数组）

    生产环境建议独立 table_operation_log 表，此处复用 config 字段简化。
    """
    log_entry = {
        "id": str(uuid.uuid4()),
        "op_type": op_type,
        "detail": detail,
        "tenant_id": str(tenant_id),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    logger.info(
        "table_operation",
        op_type=op_type,
        tenant_id=str(tenant_id),
        **detail,
    )
    return log_entry


# ─── 内部工具 ───


async def _get_table(
    table_id: uuid.UUID, tenant_id: uuid.UUID, db: AsyncSession
) -> Table:
    """按 ID + tenant_id 查找桌台，不存在则抛 ValueError"""
    stmt = select(Table).where(
        Table.id == table_id,
        Table.tenant_id == tenant_id,
        Table.is_deleted.is_(False),
    )
    result = await db.execute(stmt)
    table = result.scalar_one_or_none()
    if table is None:
        raise ValueError(f"桌台不存在: {table_id}")
    return table


def _map_status(db_status: str) -> str:
    """数据库 TableStatus 枚举 -> state_machine 状态"""
    mapping = {
        "free": "empty",
        "occupied": "dining",
        "reserved": "reserved",
        "cleaning": "pending_cleanup",
    }
    return mapping.get(db_status, db_status)


def _reverse_status(sm_status: str) -> str:
    """state_machine 状态 -> 数据库 TableStatus 枚举"""
    mapping = {
        "empty": "free",
        "dining": "occupied",
        "reserved": "reserved",
        "pending_cleanup": "cleaning",
        "pending_checkout": "occupied",
        "locked": "reserved",
        "maintenance": "free",
    }
    return mapping.get(sm_status, sm_status)


# ─── 转台 ───


async def transfer_table(
    from_table_id: uuid.UUID,
    to_table_id: uuid.UUID,
    order_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> dict:
    """转台 — 将顾客及订单从一张桌移动到另一张桌

    前提：源桌为 occupied，目标桌为 free。
    """
    from_table = await _get_table(from_table_id, tenant_id, db)
    to_table = await _get_table(to_table_id, tenant_id, db)

    if from_table.status != "occupied":
        raise ValueError(f"源桌 {from_table.table_no} 状态为 {from_table.status}，需为 occupied")
    if to_table.status != "free":
        raise ValueError(f"目标桌 {to_table.table_no} 状态为 {to_table.status}，需为 free")

    # 转移
    to_table.status = "occupied"
    to_table.current_order_id = order_id

    from_table.status = "free"
    from_table.current_order_id = None

    db.add(from_table)
    db.add(to_table)

    await _log_operation(
        db,
        tenant_id=tenant_id,
        op_type="transfer_table",
        detail={
            "from_table_id": str(from_table_id),
            "from_table_no": from_table.table_no,
            "to_table_id": str(to_table_id),
            "to_table_no": to_table.table_no,
            "order_id": str(order_id),
        },
    )

    return {
        "from_table": {"id": str(from_table.id), "table_no": from_table.table_no, "status": from_table.status},
        "to_table": {"id": str(to_table.id), "table_no": to_table.table_no, "status": to_table.status},
        "order_id": str(order_id),
    }


# ─── 并台 ───


async def merge_tables(
    table_ids: list[uuid.UUID],
    main_table_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> dict:
    """并台 — 将多张桌合并到主桌，统一管理订单

    所有桌台必须为 free 或 occupied。主桌必须在列表中。
    """
    if len(table_ids) < 2:
        raise ValueError("并台至少需要 2 张桌台")
    if main_table_id not in table_ids:
        raise ValueError("主桌必须在合并列表中")

    tables: list[Table] = []
    for tid in table_ids:
        t = await _get_table(tid, tenant_id, db)
        if t.status not in ("free", "occupied"):
            raise ValueError(f"桌台 {t.table_no} 状态为 {t.status}，无法并台（需 free 或 occupied）")
        tables.append(t)

    main_table = next(t for t in tables if t.id == main_table_id)
    sub_table_ids = [str(tid) for tid in table_ids if tid != main_table_id]

    # 合并容量与配置
    total_seats = sum(t.seats for t in tables)
    main_table.status = "occupied"
    main_table.config = {
        **(main_table.config or {}),
        "merged_with": sub_table_ids,
        "is_main_table": True,
        "original_seats": main_table.seats,
        "merged_total_seats": total_seats,
    }
    db.add(main_table)

    # 标记副桌
    for t in tables:
        if t.id != main_table_id:
            t.status = "occupied"
            t.current_order_id = main_table.current_order_id
            t.config = {
                **(t.config or {}),
                "merged_with": [str(main_table_id)],
                "is_main_table": False,
            }
            db.add(t)

    await _log_operation(
        db,
        tenant_id=tenant_id,
        op_type="merge_tables",
        detail={
            "main_table_id": str(main_table_id),
            "main_table_no": main_table.table_no,
            "table_ids": [str(tid) for tid in table_ids],
            "total_seats": total_seats,
        },
    )

    return {
        "main_table": {"id": str(main_table.id), "table_no": main_table.table_no, "status": main_table.status},
        "merged_count": len(table_ids),
        "total_seats": total_seats,
    }


# ─── 拆台 ───


async def split_table(
    table_id: uuid.UUID,
    new_orders: list[dict],
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> dict:
    """拆台 — 将并台状态解除，各桌独立经营

    new_orders: [{"table_id": uuid, "order_id": uuid}, ...]
    为拆出的每张桌指定新订单。
    """
    main_table = await _get_table(table_id, tenant_id, db)
    config = main_table.config or {}

    if not config.get("is_main_table"):
        raise ValueError(f"桌台 {main_table.table_no} 不是主桌，无法拆台")

    merged_ids = config.get("merged_with", [])
    if not merged_ids:
        raise ValueError(f"桌台 {main_table.table_no} 未处于并台状态")

    # 恢复主桌
    original_seats = config.get("original_seats", main_table.seats)
    main_table.seats = original_seats
    main_table.config = {
        k: v for k, v in config.items()
        if k not in ("merged_with", "is_main_table", "original_seats", "merged_total_seats")
    }
    db.add(main_table)

    # 恢复副桌
    split_results = []
    for sub_id_str in merged_ids:
        sub_id = uuid.UUID(sub_id_str)
        sub_table = await _get_table(sub_id, tenant_id, db)
        sub_config = sub_table.config or {}
        sub_table.config = {
            k: v for k, v in sub_config.items()
            if k not in ("merged_with", "is_main_table")
        }

        # 查找是否有新订单分配
        new_order = next(
            (o for o in new_orders if uuid.UUID(str(o["table_id"])) == sub_id),
            None,
        )
        if new_order:
            sub_table.status = "occupied"
            sub_table.current_order_id = uuid.UUID(str(new_order["order_id"]))
        else:
            sub_table.status = "free"
            sub_table.current_order_id = None

        db.add(sub_table)
        split_results.append({
            "table_id": str(sub_id),
            "table_no": sub_table.table_no,
            "status": sub_table.status,
        })

    await _log_operation(
        db,
        tenant_id=tenant_id,
        op_type="split_table",
        detail={
            "main_table_id": str(table_id),
            "main_table_no": main_table.table_no,
            "split_tables": split_results,
        },
    )

    return {
        "main_table": {"id": str(main_table.id), "table_no": main_table.table_no, "status": main_table.status},
        "split_tables": split_results,
    }


# ─── 清台 ───


async def clear_table(
    table_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> dict:
    """清台 — 将桌台从 cleaning 恢复为 free，或从 occupied 直接清空

    支持 occupied -> cleaning -> free 以及 cleaning -> free。
    """
    table = await _get_table(table_id, tenant_id, db)

    if table.status not in ("occupied", "cleaning"):
        raise ValueError(f"桌台 {table.table_no} 状态为 {table.status}，无法清台（需 occupied 或 cleaning）")

    table.status = "free"
    table.current_order_id = None
    # 清除并台配置
    if table.config:
        table.config = {
            k: v for k, v in table.config.items()
            if k not in ("merged_with", "is_main_table", "original_seats", "merged_total_seats")
        }
    db.add(table)

    await _log_operation(
        db,
        tenant_id=tenant_id,
        op_type="clear_table",
        detail={
            "table_id": str(table_id),
            "table_no": table.table_no,
        },
    )

    return {"id": str(table.id), "table_no": table.table_no, "status": "free"}


# ─── 预留 ───


async def lock_table(
    table_id: uuid.UUID,
    reservation_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> dict:
    """预留桌台 — 将 free 状态的桌台锁定为 reserved"""
    table = await _get_table(table_id, tenant_id, db)

    if table.status != "free":
        raise ValueError(f"桌台 {table.table_no} 状态为 {table.status}，无法预留（需 free）")

    table.status = "reserved"
    table.config = {
        **(table.config or {}),
        "reservation_id": str(reservation_id),
    }
    db.add(table)

    await _log_operation(
        db,
        tenant_id=tenant_id,
        op_type="lock_table",
        detail={
            "table_id": str(table_id),
            "table_no": table.table_no,
            "reservation_id": str(reservation_id),
        },
    )

    return {
        "id": str(table.id),
        "table_no": table.table_no,
        "status": "reserved",
        "reservation_id": str(reservation_id),
    }


# ─── 桌态看板 ───


async def get_table_status_board(
    store_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> dict:
    """全店桌态看板 — 返回按区域分组的桌台状态总览"""
    stmt = select(Table).where(
        Table.store_id == store_id,
        Table.tenant_id == tenant_id,
        Table.is_deleted.is_(False),
        Table.is_active.is_(True),
    ).order_by(Table.area, Table.sort_order, Table.table_no)

    result = await db.execute(stmt)
    tables = result.scalars().all()

    # 按区域分组
    areas: dict[str, list[dict]] = {}
    stats = {"total": 0, "free": 0, "occupied": 0, "reserved": 0, "cleaning": 0}

    for t in tables:
        area = t.area or "默认区域"
        if area not in areas:
            areas[area] = []

        table_info = {
            "id": str(t.id),
            "table_no": t.table_no,
            "seats": t.seats,
            "status": t.status,
            "current_order_id": str(t.current_order_id) if t.current_order_id else None,
            "min_consume_fen": t.min_consume_fen,
            "floor": t.floor,
            "config": t.config,
        }
        areas[area].append(table_info)

        stats["total"] += 1
        if t.status in stats:
            stats[t.status] += 1

    # 使用率
    usable = stats["total"]
    stats["occupancy_rate"] = round(stats["occupied"] / usable, 4) if usable > 0 else 0.0

    return {
        "store_id": str(store_id),
        "areas": areas,
        "stats": stats,
    }
