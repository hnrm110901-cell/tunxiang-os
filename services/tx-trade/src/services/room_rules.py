"""包厢规则引擎 — 低消校验/配置管理/使用情况

金额单位统一为分(fen)。
"""

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.tables import Table

logger = structlog.get_logger()

# 包厢区域标识（area 字段中含 "包" 字即视为包厢）
_ROOM_AREA_KEYWORDS = ("包间", "包厢", "VIP")


def _is_room(table: Table) -> bool:
    """判断桌台是否为包厢"""
    area = table.area or ""
    return any(kw in area for kw in _ROOM_AREA_KEYWORDS)


# ─── 低消校验 ───


async def check_minimum_charge(
    room_id: uuid.UUID,
    order_amount_fen: int,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> dict:
    """检查包厢低消是否达标

    Returns:
        {"met": bool, "minimum_fen": int, "gap_fen": int}
        gap_fen > 0 表示还差多少分达到低消
    """
    stmt = select(Table).where(
        Table.id == room_id,
        Table.tenant_id == tenant_id,
        Table.is_deleted.is_(False),
    )
    result = await db.execute(stmt)
    room = result.scalar_one_or_none()
    if room is None:
        raise ValueError(f"包厢不存在: {room_id}")

    minimum_fen = room.min_consume_fen or 0
    gap_fen = max(0, minimum_fen - order_amount_fen)
    met = order_amount_fen >= minimum_fen

    logger.info(
        "minimum_charge_check",
        room_id=str(room_id),
        tenant_id=str(tenant_id),
        minimum_fen=minimum_fen,
        order_amount_fen=order_amount_fen,
        met=met,
        gap_fen=gap_fen,
    )

    return {
        "met": met,
        "minimum_fen": minimum_fen,
        "gap_fen": gap_fen,
    }


# ─── 包厢配置查询 ───


async def get_room_config(
    room_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> dict:
    """获取包厢配置

    Returns:
        {"minimum_charge_fen": int, "capacity": int, "time_limit_minutes": int | None, ...}
    """
    stmt = select(Table).where(
        Table.id == room_id,
        Table.tenant_id == tenant_id,
        Table.is_deleted.is_(False),
    )
    result = await db.execute(stmt)
    room = result.scalar_one_or_none()
    if room is None:
        raise ValueError(f"包厢不存在: {room_id}")

    config = room.config or {}

    return {
        "room_id": str(room.id),
        "table_no": room.table_no,
        "area": room.area,
        "minimum_charge_fen": room.min_consume_fen or 0,
        "capacity": room.seats,
        "time_limit_minutes": config.get("time_limit_minutes"),
        "floor": room.floor,
        "config": config,
    }


# ─── 设置包厢规则 ───


async def set_room_rules(
    room_id: uuid.UUID,
    rules: dict,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> dict:
    """设置包厢规则

    rules 可包含:
        - minimum_charge_fen: int — 低消金额(分)
        - time_limit_minutes: int — 用餐时限(分钟)
        - capacity: int — 容纳人数
        - 其他自定义规则写入 config
    """
    stmt = select(Table).where(
        Table.id == room_id,
        Table.tenant_id == tenant_id,
        Table.is_deleted.is_(False),
    )
    result = await db.execute(stmt)
    room = result.scalar_one_or_none()
    if room is None:
        raise ValueError(f"包厢不存在: {room_id}")

    # 更新模型字段
    if "minimum_charge_fen" in rules:
        min_fen = rules["minimum_charge_fen"]
        if not isinstance(min_fen, int) or min_fen < 0:
            raise ValueError("minimum_charge_fen 必须为非负整数(分)")
        room.min_consume_fen = min_fen

    if "capacity" in rules:
        cap = rules["capacity"]
        if not isinstance(cap, int) or cap < 1:
            raise ValueError("capacity 必须为正整数")
        room.seats = cap

    # 其他规则写入 config
    config = dict(room.config or {})
    if "time_limit_minutes" in rules:
        tl = rules["time_limit_minutes"]
        if tl is not None and (not isinstance(tl, int) or tl < 0):
            raise ValueError("time_limit_minutes 必须为非负整数或 null")
        config["time_limit_minutes"] = tl

    # 写入额外自定义规则
    extra_keys = set(rules.keys()) - {"minimum_charge_fen", "capacity", "time_limit_minutes"}
    for k in extra_keys:
        config[k] = rules[k]

    room.config = config
    db.add(room)

    logger.info(
        "room_rules_set",
        room_id=str(room_id),
        tenant_id=str(tenant_id),
        rules=rules,
    )

    return {
        "room_id": str(room.id),
        "table_no": room.table_no,
        "minimum_charge_fen": room.min_consume_fen,
        "capacity": room.seats,
        "time_limit_minutes": config.get("time_limit_minutes"),
        "config": config,
    }


# ─── 今日包厢使用情况 ───


async def get_room_usage_today(
    store_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> list[dict]:
    """获取门店今日所有包厢使用情况

    Returns:
        [{"room": {...}, "status": str, "current_order_id": str|None, "time_elapsed_minutes": int|None}]
    """
    stmt = (
        select(Table)
        .where(
            Table.store_id == store_id,
            Table.tenant_id == tenant_id,
            Table.is_deleted.is_(False),
            Table.is_active.is_(True),
        )
        .order_by(Table.area, Table.sort_order)
    )

    result = await db.execute(stmt)
    tables = result.scalars().all()

    now = datetime.now(timezone.utc)
    rooms = []

    for t in tables:
        if not _is_room(t):
            continue

        config = t.config or {}
        time_elapsed_minutes = None

        # 如果有开台时间记录在 config 中，计算已用时间
        open_time_str = config.get("open_time")
        if open_time_str and t.status == "occupied":
            try:
                open_time = datetime.fromisoformat(open_time_str)
                delta = now - open_time
                time_elapsed_minutes = int(delta.total_seconds() / 60)
            except (ValueError, TypeError):
                pass

        rooms.append(
            {
                "room": {
                    "id": str(t.id),
                    "table_no": t.table_no,
                    "area": t.area,
                    "seats": t.seats,
                    "floor": t.floor,
                    "minimum_charge_fen": t.min_consume_fen or 0,
                },
                "status": t.status,
                "current_order_id": str(t.current_order_id) if t.current_order_id else None,
                "time_elapsed_minutes": time_elapsed_minutes,
                "time_limit_minutes": config.get("time_limit_minutes"),
            }
        )

    logger.info(
        "room_usage_queried",
        store_id=str(store_id),
        tenant_id=str(tenant_id),
        room_count=len(rooms),
    )

    return rooms
