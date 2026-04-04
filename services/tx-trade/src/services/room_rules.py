"""包厢规则引擎 — 低消校验/服务费/超时/可用时段/配置管理/使用情况

金额单位统一为分(fen)。

config JSON 字段约定:
    service_charge_rate: float  — 服务费比例(如0.10=10%)
    room_fee_fen: int           — 固定包间费(分)
    time_limit_minutes: int     — 用餐时限(分钟)
    open_time: str              — 开台时间 ISO 格式
"""
import math
import uuid
from datetime import date as date_type
from datetime import datetime, time, timedelta, timezone

import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Order

from ..models.reservation import Reservation
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
    stmt = select(Table).where(
        Table.store_id == store_id,
        Table.tenant_id == tenant_id,
        Table.is_deleted.is_(False),
        Table.is_active.is_(True),
    ).order_by(Table.area, Table.sort_order)

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

        rooms.append({
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
        })

    logger.info(
        "room_usage_queried",
        store_id=str(store_id),
        tenant_id=str(tenant_id),
        room_count=len(rooms),
    )

    return rooms


# ─── 服务费/包间费计算 ───


async def calculate_service_charge(
    order_id: uuid.UUID,
    table_no: str,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> dict:
    """计算包间服务费

    规则优先级：
    1. 按比例收取 service_charge_rate（如 0.10 = 10%）
    2. 固定包间费 room_fee_fen（如 20000分 = 200元）
    3. 若两者都配了，取 rate（比例优先）

    Returns:
        {"charge_type": "rate"|"fixed"|"none", "charge_fen": int, "description": str}
    """
    # 查桌台
    stmt = select(Table).where(
        Table.table_no == table_no,
        Table.tenant_id == tenant_id,
        Table.is_deleted.is_(False),
    )
    result = await db.execute(stmt)
    table = result.scalar_one_or_none()
    if table is None:
        raise ValueError(f"桌台不存在: {table_no}")

    if not _is_room(table):
        return {"charge_type": "none", "charge_fen": 0, "description": "非包间桌台，无服务费"}

    config = table.config or {}
    service_charge_rate = config.get("service_charge_rate")
    room_fee_fen = config.get("room_fee_fen")

    # 查订单金额
    order_stmt = select(Order).where(
        Order.id == order_id,
        Order.tenant_id == tenant_id,
        Order.is_deleted.is_(False),
    )
    order_result = await db.execute(order_stmt)
    order = order_result.scalar_one_or_none()
    if order is None:
        raise ValueError(f"订单不存在: {order_id}")

    order_total_fen = order.total_amount_fen or 0

    # 比例优先
    if service_charge_rate is not None and service_charge_rate > 0:
        charge_fen = math.ceil(order_total_fen * service_charge_rate)
        rate_pct = round(service_charge_rate * 100)
        description = f"包间服务费 {rate_pct}%（基于消费 {order_total_fen / 100:.2f}元）"
        charge_type = "rate"
    elif room_fee_fen is not None and room_fee_fen > 0:
        charge_fen = room_fee_fen
        description = f"固定包间费 {room_fee_fen / 100:.2f}元"
        charge_type = "fixed"
    else:
        charge_fen = 0
        description = "包间未配置服务费"
        charge_type = "none"

    logger.info(
        "service_charge_calculated",
        order_id=str(order_id),
        table_no=table_no,
        tenant_id=str(tenant_id),
        charge_type=charge_type,
        charge_fen=charge_fen,
    )

    return {
        "charge_type": charge_type,
        "charge_fen": charge_fen,
        "description": description,
    }


# ─── 超时提醒 ───


async def check_room_timeout(
    table_no: str,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> dict:
    """检查包间是否超时

    依据 config.time_limit_minutes 和 config.open_time 判断。

    Returns:
        {"is_overtime": bool, "minutes_over": int, "dining_minutes": int, "limit_minutes": int|None}
    """
    stmt = select(Table).where(
        Table.table_no == table_no,
        Table.tenant_id == tenant_id,
        Table.is_deleted.is_(False),
    )
    result = await db.execute(stmt)
    table = result.scalar_one_or_none()
    if table is None:
        raise ValueError(f"桌台不存在: {table_no}")

    if not _is_room(table):
        return {
            "is_overtime": False,
            "minutes_over": 0,
            "dining_minutes": 0,
            "limit_minutes": None,
        }

    config = table.config or {}
    limit_minutes = config.get("time_limit_minutes")
    open_time_str = config.get("open_time")

    # 未设置时限或未开台 → 不超时
    if limit_minutes is None or open_time_str is None:
        return {
            "is_overtime": False,
            "minutes_over": 0,
            "dining_minutes": 0,
            "limit_minutes": limit_minutes,
        }

    now = datetime.now(timezone.utc)
    try:
        open_time = datetime.fromisoformat(open_time_str)
    except (ValueError, TypeError) as exc:
        logger.warning("invalid_open_time", table_no=table_no, open_time=open_time_str, error=str(exc))
        return {
            "is_overtime": False,
            "minutes_over": 0,
            "dining_minutes": 0,
            "limit_minutes": limit_minutes,
        }

    dining_minutes = int((now - open_time).total_seconds() / 60)
    minutes_over = max(0, dining_minutes - limit_minutes)
    is_overtime = dining_minutes > limit_minutes

    logger.info(
        "room_timeout_check",
        table_no=table_no,
        tenant_id=str(tenant_id),
        dining_minutes=dining_minutes,
        limit_minutes=limit_minutes,
        is_overtime=is_overtime,
    )

    return {
        "is_overtime": is_overtime,
        "minutes_over": minutes_over,
        "dining_minutes": dining_minutes,
        "limit_minutes": limit_minutes,
    }


# ─── 包间可用时段 ───

# 默认营业时段（午市+晚市）
_DEFAULT_SLOTS = [
    (time(11, 0), time(14, 0)),
    (time(17, 0), time(21, 0)),
]


async def get_room_availability(
    store_id: uuid.UUID,
    target_date: date_type,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> list[dict]:
    """查询门店所有包间在指定日期的可用时段

    交叉比对预订记录，返回每个包间的时段占用情况。

    Returns:
        [{
            "room_id": str,
            "room_name": str,    # table_no
            "capacity": int,     # seats
            "min_spend_fen": int,
            "time_slots": [{"start": "HH:MM", "end": "HH:MM", "status": "available"|"reserved"|"occupied"}]
        }]
    """
    # 1. 查所有包间
    room_stmt = select(Table).where(
        Table.store_id == store_id,
        Table.tenant_id == tenant_id,
        Table.is_deleted.is_(False),
        Table.is_active.is_(True),
    ).order_by(Table.area, Table.sort_order)
    room_result = await db.execute(room_stmt)
    tables = room_result.scalars().all()
    rooms = [t for t in tables if _is_room(t)]

    if not rooms:
        return []

    # 2. 查当日包间预订
    date_str = target_date.isoformat()
    rsv_stmt = select(Reservation).where(
        Reservation.store_id == store_id,
        Reservation.tenant_id == tenant_id,
        Reservation.date == date_str,
        Reservation.is_deleted.is_(False),
        Reservation.status.in_(["pending", "confirmed", "arrived", "seated"]),
    )
    rsv_result = await db.execute(rsv_stmt)
    reservations = rsv_result.scalars().all()

    # 按 room_name/table_no 分组预订
    rsv_by_room: dict[str, list] = {}
    for rsv in reservations:
        key = rsv.room_name or rsv.table_no
        if key:
            rsv_by_room.setdefault(key, []).append(rsv)

    # 3. 为每个包间生成时段
    availability = []
    for room in rooms:
        config = room.config or {}
        # 允许每个包间自定义时段，否则用默认
        custom_slots = config.get("time_slots")  # [["11:00","14:00"], ...]
        if custom_slots:
            slots = []
            for s in custom_slots:
                try:
                    start = time.fromisoformat(s[0])
                    end = time.fromisoformat(s[1])
                    slots.append((start, end))
                except (ValueError, IndexError, TypeError):
                    continue
        else:
            slots = _DEFAULT_SLOTS

        room_rsvs = rsv_by_room.get(room.table_no, [])

        time_slots = []
        for slot_start, slot_end in slots:
            # 检查该时段是否与任何预订重叠
            status = "available"

            # 如果包间当前 occupied 且是今天，标记对应时段
            if target_date == datetime.now(timezone.utc).date() and room.status == "occupied":
                open_time_str = config.get("open_time")
                if open_time_str:
                    try:
                        open_time = datetime.fromisoformat(open_time_str).time()
                        if slot_start <= open_time < slot_end:
                            status = "occupied"
                    except (ValueError, TypeError):
                        pass

            # 检查预订冲突
            if status == "available":
                for rsv in room_rsvs:
                    try:
                        rsv_start = time.fromisoformat(rsv.time)
                        rsv_end = time.fromisoformat(rsv.estimated_end_time) if rsv.estimated_end_time else slot_end
                    except (ValueError, TypeError):
                        continue

                    # 时段重叠检查
                    if rsv_start < slot_end and rsv_end > slot_start:
                        status = "reserved"
                        break

            time_slots.append({
                "start": slot_start.strftime("%H:%M"),
                "end": slot_end.strftime("%H:%M"),
                "status": status,
            })

        availability.append({
            "room_id": str(room.id),
            "room_name": room.table_no,
            "area": room.area,
            "capacity": room.seats,
            "min_spend_fen": room.min_consume_fen or 0,
            "time_slots": time_slots,
        })

    logger.info(
        "room_availability_queried",
        store_id=str(store_id),
        date=date_str,
        tenant_id=str(tenant_id),
        room_count=len(availability),
    )

    return availability


# ─── 结账低消校验（增强版） ───


async def enforce_min_spend_at_checkout(
    order_id: uuid.UUID,
    table_no: str,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> dict:
    """结账时校验低消是否达标，若未达标给出补齐建议

    Returns:
        {
            "met": bool,
            "minimum_fen": int,
            "order_fen": int,
            "gap_fen": int,
            "auto_add_service_charge": bool,
            "suggested_charge_fen": int,
            "description": str,
        }
    """
    # 查桌台
    table_stmt = select(Table).where(
        Table.table_no == table_no,
        Table.tenant_id == tenant_id,
        Table.is_deleted.is_(False),
    )
    table_result = await db.execute(table_stmt)
    table = table_result.scalar_one_or_none()
    if table is None:
        raise ValueError(f"桌台不存在: {table_no}")

    minimum_fen = table.min_consume_fen or 0

    # 非包间或无低消要求 → 直接通过
    if not _is_room(table) or minimum_fen == 0:
        return {
            "met": True,
            "minimum_fen": 0,
            "order_fen": 0,
            "gap_fen": 0,
            "auto_add_service_charge": False,
            "suggested_charge_fen": 0,
            "description": "无低消要求",
        }

    # 查订单
    order_stmt = select(Order).where(
        Order.id == order_id,
        Order.tenant_id == tenant_id,
        Order.is_deleted.is_(False),
    )
    order_result = await db.execute(order_stmt)
    order = order_result.scalar_one_or_none()
    if order is None:
        raise ValueError(f"订单不存在: {order_id}")

    order_fen = order.total_amount_fen or 0
    gap_fen = max(0, minimum_fen - order_fen)
    met = order_fen >= minimum_fen

    # 若未达标：建议将差额作为包间服务费补齐
    auto_add = False
    suggested_charge_fen = 0
    if not met:
        config = table.config or {}
        # 只有配置了 service_charge_rate 或 room_fee_fen 才建议自动补齐
        has_charge_config = (
            config.get("service_charge_rate") is not None
            or config.get("room_fee_fen") is not None
        )
        if has_charge_config:
            auto_add = True
            suggested_charge_fen = gap_fen
        description = (
            f"未达低消（差 {gap_fen / 100:.2f}元），"
            + ("建议加收包间服务费补齐" if auto_add else "请提示顾客加点或确认收取差额")
        )
    else:
        description = "已达低消要求"

    logger.info(
        "min_spend_enforcement",
        order_id=str(order_id),
        table_no=table_no,
        tenant_id=str(tenant_id),
        minimum_fen=minimum_fen,
        order_fen=order_fen,
        met=met,
        gap_fen=gap_fen,
    )

    return {
        "met": met,
        "minimum_fen": minimum_fen,
        "order_fen": order_fen,
        "gap_fen": gap_fen,
        "auto_add_service_charge": auto_add,
        "suggested_charge_fen": suggested_charge_fen,
        "description": description,
    }
