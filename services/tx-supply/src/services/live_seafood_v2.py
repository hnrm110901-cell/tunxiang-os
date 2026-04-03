"""活鲜库存深度管理 V2 -- 状态跟踪/损耗计算/鱼缸分区/按重定价/仪表盘

基于 live_seafood_service.py 的基础，扩展面向数据库的异步版本。
所有重量单位：克（g）。金额单位：分（fen）。
活鲜状态流转：alive → weak → dead（不可逆）。
"""
import uuid
from datetime import date, datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Ingredient, IngredientTransaction
from shared.ontology.src.enums import InventoryStatus, TransactionType

logger = structlog.get_logger()

# ─── 活鲜状态常量 ───

LIVE_STATUS_ALIVE = "alive"
LIVE_STATUS_WEAK = "weak"
LIVE_STATUS_DEAD = "dead"

_STATUS_ORDER = {LIVE_STATUS_ALIVE: 0, LIVE_STATUS_WEAK: 1, LIVE_STATUS_DEAD: 2}

# 品质降级折扣（dead 不可售，按废料处理）
_QUALITY_DISCOUNT = {
    LIVE_STATUS_ALIVE: 1.0,
    LIVE_STATUS_WEAK: 0.7,
    LIVE_STATUS_DEAD: 0.0,
}

# ─── 仓库类型 ───

WAREHOUSE_CENTRAL = "central"
WAREHOUSE_STORE = "store"
WAREHOUSE_DEPT = "dept"
_VALID_WAREHOUSE_TYPES = {WAREHOUSE_CENTRAL, WAREHOUSE_STORE, WAREHOUSE_DEPT}


# ─── 工具函数 ───


def _uuid(val: str | uuid.UUID) -> uuid.UUID:
    return val if isinstance(val, uuid.UUID) else uuid.UUID(str(val))


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─── 内存存储（活鲜状态/鱼缸分区，后续可迁移到独立表） ───

# key: "{tenant_id}:{store_id}:{ingredient_id}" → list of status records
_live_status_records: dict[str, list[dict]] = {}

# key: "{tenant_id}:{store_id}:{tank_id}" → tank inventory info
_tank_inventory: dict[str, dict] = {}

# key: "{tenant_id}:{store_id}:{ingredient_id}" → current market price fen/g
_live_prices: dict[str, int] = {}

# key: "{tenant_id}:{store_id}:{warehouse_type}" → list of items
_warehouse_stock: dict[str, list[dict]] = {}


def _status_key(ingredient_id: str, store_id: str, tenant_id: str) -> str:
    return f"{tenant_id}:{store_id}:{ingredient_id}"


def _tank_key(store_id: str, tank_id: str, tenant_id: str) -> str:
    return f"{tenant_id}:{store_id}:{tank_id}"


def _wh_key(store_id: str, warehouse_type: str, tenant_id: str) -> str:
    return f"{tenant_id}:{store_id}:{warehouse_type}"


# ─── C4-1: 活鲜状态跟踪 ───


async def track_live_status(
    ingredient_id: str,
    store_id: str,
    status: str,
    weight_g: float,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """跟踪活鲜状态（alive/weak/dead），状态不可逆转。

    Args:
        ingredient_id: 原料ID
        store_id: 门店ID
        status: 目标状态 alive/weak/dead
        weight_g: 当前称重(克)
        tenant_id: 租户ID
        db: 数据库会话

    Returns:
        {"record_id": str, "ingredient_id": str, "status": str,
         "weight_g": float, "previous_status": str|None}

    Raises:
        ValueError: 状态无效或状态逆转
    """
    log = logger.bind(ingredient_id=ingredient_id, store_id=store_id, tenant_id=tenant_id)

    if status not in _STATUS_ORDER:
        raise ValueError(f"无效的活鲜状态: {status}，必须是 {list(_STATUS_ORDER.keys())} 之一")
    if weight_g < 0:
        raise ValueError("重量不能为负数")

    await _set_tenant(db, tenant_id)
    key = _status_key(ingredient_id, store_id, tenant_id)
    records = _live_status_records.setdefault(key, [])

    # 检查不可逆约束
    previous_status = records[-1]["status"] if records else None
    if previous_status is not None:
        if _STATUS_ORDER[status] < _STATUS_ORDER[previous_status]:
            raise ValueError(
                f"活鲜状态不可逆转: 当前 {previous_status} → 目标 {status}"
            )

    record_id = uuid.uuid4().hex[:12].upper()
    record = {
        "record_id": record_id,
        "ingredient_id": ingredient_id,
        "store_id": store_id,
        "tenant_id": tenant_id,
        "status": status,
        "weight_g": weight_g,
        "previous_status": previous_status,
        "recorded_at": _now().isoformat(),
    }
    records.append(record)

    # 如果死亡，记录一笔 waste 事务
    if status == LIVE_STATUS_DEAD:
        try:
            ingredient = await _get_ingredient_safe(db, ingredient_id, store_id, tenant_id)
            if ingredient is not None:
                waste_kg = weight_g / 1000.0
                if ingredient.current_quantity >= waste_kg:
                    ingredient.current_quantity -= waste_kg
                    tx = IngredientTransaction(
                        id=uuid.uuid4(),
                        tenant_id=_uuid(tenant_id),
                        ingredient_id=_uuid(ingredient_id),
                        store_id=_uuid(store_id),
                        transaction_type=TransactionType.waste.value,
                        quantity=waste_kg,
                        unit_cost_fen=ingredient.unit_price_fen or 0,
                        total_cost_fen=round((ingredient.unit_price_fen or 0) * waste_kg),
                        quantity_before=ingredient.current_quantity + waste_kg,
                        quantity_after=ingredient.current_quantity,
                        performed_by=None,
                        reference_id=None,
                        notes=f"活鲜死亡: {weight_g}g",
                    )
                    db.add(tx)
                    await db.flush()
        except (ValueError, AttributeError):
            log.warning("live_status.dead_waste_record_failed", ingredient_id=ingredient_id)

    log.info(
        "live_status.tracked",
        status=status,
        weight_g=weight_g,
        previous_status=previous_status,
    )

    return {
        "record_id": record_id,
        "ingredient_id": ingredient_id,
        "status": status,
        "weight_g": weight_g,
        "previous_status": previous_status,
    }


async def _get_ingredient_safe(
    db: AsyncSession, ingredient_id: str, store_id: str, tenant_id: str,
) -> Optional[Ingredient]:
    """获取原料记录，不存在返回 None"""
    result = await db.execute(
        select(Ingredient).where(
            Ingredient.id == _uuid(ingredient_id),
            Ingredient.store_id == _uuid(store_id),
            Ingredient.tenant_id == _uuid(tenant_id),
            Ingredient.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


# ─── C4-2: 活鲜损耗计算 ───


async def calculate_live_loss(
    store_id: str,
    date_range: tuple[date, date],
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """计算活鲜损耗（死亡/品质降级/称重差）。

    Args:
        store_id: 门店ID
        date_range: (start_date, end_date) 日期范围
        tenant_id: 租户ID
        db: 数据库会话

    Returns:
        {"store_id": str, "date_range": [...], "dead_loss_g": float,
         "weak_loss_g": float, "weight_diff_g": float,
         "total_loss_value_fen": int, "details": [...]}
    """
    log = logger.bind(store_id=store_id, tenant_id=tenant_id)
    await _set_tenant(db, tenant_id)

    start_date, end_date = date_range
    start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc)

    dead_loss_g = 0.0
    weak_loss_g = 0.0
    weight_diff_g = 0.0
    total_loss_value_fen = 0
    details = []

    # 遍历所有该门店的状态记录
    for key, records in _live_status_records.items():
        parts = key.split(":")
        if len(parts) < 3:
            continue
        rec_tenant, rec_store, rec_ingredient = parts[0], parts[1], parts[2]
        if rec_store != store_id or rec_tenant != tenant_id:
            continue

        for rec in records:
            rec_time = datetime.fromisoformat(rec["recorded_at"])
            if rec_time < start_dt or rec_time > end_dt:
                continue

            weight = rec["weight_g"]

            if rec["status"] == LIVE_STATUS_DEAD:
                dead_loss_g += weight
                # 查找单价估算损失
                ingredient = await _get_ingredient_safe(db, rec_ingredient, store_id, tenant_id)
                unit_fen = (ingredient.unit_price_fen or 0) if ingredient else 0
                loss_fen = round(unit_fen * weight / 1000.0)
                total_loss_value_fen += loss_fen
                details.append({
                    "ingredient_id": rec_ingredient,
                    "type": "dead",
                    "weight_g": weight,
                    "loss_value_fen": loss_fen,
                    "recorded_at": rec["recorded_at"],
                })
            elif rec["status"] == LIVE_STATUS_WEAK:
                # 品质降级损耗 = 原价的30%
                weak_loss_g += weight
                ingredient = await _get_ingredient_safe(db, rec_ingredient, store_id, tenant_id)
                unit_fen = (ingredient.unit_price_fen or 0) if ingredient else 0
                discount_loss = round(unit_fen * weight / 1000.0 * 0.3)
                total_loss_value_fen += discount_loss
                details.append({
                    "ingredient_id": rec_ingredient,
                    "type": "weak_downgrade",
                    "weight_g": weight,
                    "loss_value_fen": discount_loss,
                    "recorded_at": rec["recorded_at"],
                })

    # 称重差：查 DB 中 waste 事务的称重差记录
    tid = _uuid(tenant_id)
    sid = _uuid(store_id)
    waste_q = (
        select(func.coalesce(func.sum(IngredientTransaction.quantity), 0))
        .where(
            IngredientTransaction.tenant_id == tid,
            IngredientTransaction.store_id == sid,
            IngredientTransaction.transaction_type == TransactionType.waste.value,
            IngredientTransaction.is_deleted == False,  # noqa: E712
            IngredientTransaction.created_at >= start_dt,
            IngredientTransaction.created_at <= end_dt,
        )
    )
    waste_result = await db.execute(waste_q)
    waste_kg = float(waste_result.scalar() or 0)
    weight_diff_g = waste_kg * 1000.0 - dead_loss_g  # 排除已经计算的死亡部分

    log.info(
        "live_loss.calculated",
        dead_loss_g=dead_loss_g,
        weak_loss_g=weak_loss_g,
        weight_diff_g=weight_diff_g,
        total_loss_value_fen=total_loss_value_fen,
    )

    return {
        "store_id": store_id,
        "date_range": [start_date.isoformat(), end_date.isoformat()],
        "dead_loss_g": dead_loss_g,
        "weak_loss_g": weak_loss_g,
        "weight_diff_g": max(weight_diff_g, 0),
        "total_loss_value_fen": total_loss_value_fen,
        "details": details,
    }


# ─── C4-3: 鱼缸/水箱分区库存 ───


async def get_tank_inventory(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """获取门店鱼缸/水箱分区库存。

    Returns:
        {"store_id": str, "tanks": [{"tank_id": str, "species": str,
         "alive_count": int, "alive_weight_g": float, "weak_count": int,
         "weak_weight_g": float, "total_value_fen": int}], "summary": {...}}
    """
    log = logger.bind(store_id=store_id, tenant_id=tenant_id)
    await _set_tenant(db, tenant_id)

    tanks = []
    total_alive_g = 0.0
    total_weak_g = 0.0
    total_value_fen = 0

    for key, tank_info in _tank_inventory.items():
        parts = key.split(":")
        if len(parts) < 3:
            continue
        rec_tenant, rec_store, tank_id = parts[0], parts[1], parts[2]
        if rec_store != store_id or rec_tenant != tenant_id:
            continue

        alive_g = tank_info.get("alive_weight_g", 0.0)
        weak_g = tank_info.get("weak_weight_g", 0.0)
        price_per_g = tank_info.get("price_per_g_fen", 0)

        alive_value = round(alive_g * price_per_g * _QUALITY_DISCOUNT[LIVE_STATUS_ALIVE])
        weak_value = round(weak_g * price_per_g * _QUALITY_DISCOUNT[LIVE_STATUS_WEAK])
        tank_value = alive_value + weak_value

        total_alive_g += alive_g
        total_weak_g += weak_g
        total_value_fen += tank_value

        tanks.append({
            "tank_id": tank_id,
            "species": tank_info.get("species", ""),
            "alive_count": tank_info.get("alive_count", 0),
            "alive_weight_g": alive_g,
            "weak_count": tank_info.get("weak_count", 0),
            "weak_weight_g": weak_g,
            "total_value_fen": tank_value,
            "temperature": tank_info.get("temperature"),
            "updated_at": tank_info.get("updated_at"),
        })

    log.info("tank_inventory.fetched", tank_count=len(tanks))

    return {
        "store_id": store_id,
        "tanks": tanks,
        "summary": {
            "tank_count": len(tanks),
            "total_alive_weight_g": total_alive_g,
            "total_weak_weight_g": total_weak_g,
            "total_inventory_value_fen": total_value_fen,
        },
    }


def register_tank(
    store_id: str,
    tank_id: str,
    species: str,
    tenant_id: str,
    alive_count: int = 0,
    alive_weight_g: float = 0.0,
    weak_count: int = 0,
    weak_weight_g: float = 0.0,
    price_per_g_fen: int = 0,
    temperature: Optional[float] = None,
) -> dict:
    """注册/更新鱼缸库存（内部辅助，供入库和巡检使用）。"""
    key = _tank_key(store_id, tank_id, tenant_id)
    _tank_inventory[key] = {
        "species": species,
        "alive_count": alive_count,
        "alive_weight_g": alive_weight_g,
        "weak_count": weak_count,
        "weak_weight_g": weak_weight_g,
        "price_per_g_fen": price_per_g_fen,
        "temperature": temperature,
        "updated_at": _now().isoformat(),
    }
    return _tank_inventory[key]


# ─── C4-4: 按重量实时定价 ───


async def price_by_weight(
    ingredient_id: str,
    weight_g: float,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """按重量实时定价（活鲜时价）。

    优先使用门店设置的时价，否则回退到成本价加默认毛利。

    Args:
        ingredient_id: 原料ID
        weight_g: 称重(克)
        tenant_id: 租户ID
        db: 数据库会话

    Returns:
        {"ingredient_id": str, "weight_g": float, "unit_price_fen_per_g": int,
         "total_price_fen": int, "pricing_method": str}
    """
    log = logger.bind(ingredient_id=ingredient_id, tenant_id=tenant_id)

    if weight_g <= 0:
        raise ValueError("称重必须大于0克")

    await _set_tenant(db, tenant_id)

    # 先查门店时价
    price_key = f"{tenant_id}:*:{ingredient_id}"
    unit_price_fen_per_g = None
    pricing_method = "market_price"

    for k, v in _live_prices.items():
        if k.endswith(f":{ingredient_id}") and k.startswith(f"{tenant_id}:"):
            unit_price_fen_per_g = v
            break

    # 回退到数据库成本价 + 默认毛利 55%
    if unit_price_fen_per_g is None:
        result = await db.execute(
            select(Ingredient.unit_price_fen).where(
                Ingredient.id == _uuid(ingredient_id),
                Ingredient.tenant_id == _uuid(tenant_id),
                Ingredient.is_deleted == False,  # noqa: E712
            )
        )
        cost_fen_per_kg = result.scalar_one_or_none()
        if cost_fen_per_kg is None:
            raise ValueError(f"原料 {ingredient_id} 不存在或无价格信息")

        # 成本 fen/kg → fen/g，加上 55% 毛利
        cost_per_g = cost_fen_per_kg / 1000.0
        unit_price_fen_per_g = round(cost_per_g / (1 - 0.55))
        pricing_method = "cost_plus_margin"

    total_price_fen = round(unit_price_fen_per_g * weight_g)

    log.info(
        "price_by_weight.calculated",
        weight_g=weight_g,
        unit_price=unit_price_fen_per_g,
        total=total_price_fen,
        method=pricing_method,
    )

    return {
        "ingredient_id": ingredient_id,
        "weight_g": weight_g,
        "unit_price_fen_per_g": unit_price_fen_per_g,
        "total_price_fen": total_price_fen,
        "pricing_method": pricing_method,
    }


def set_market_price(
    ingredient_id: str, store_id: str, tenant_id: str, price_fen_per_g: int
) -> None:
    """设置活鲜时价（分/克）。"""
    if price_fen_per_g <= 0:
        raise ValueError("时价必须大于0")
    key = f"{tenant_id}:{store_id}:{ingredient_id}"
    _live_prices[key] = price_fen_per_g


# ─── C4-5: 活鲜仪表盘 ───


async def get_seafood_dashboard(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """活鲜仪表盘（库存/损耗/价值）。

    Returns:
        {"store_id": str, "inventory": {...}, "loss_today": {...},
         "total_inventory_value_fen": int, "alerts": [...]}
    """
    log = logger.bind(store_id=store_id, tenant_id=tenant_id)
    await _set_tenant(db, tenant_id)

    # 鱼缸库存汇总
    tank_data = await get_tank_inventory(store_id, tenant_id, db)

    # 今日损耗
    today = date.today()
    loss_data = await calculate_live_loss(store_id, (today, today), tenant_id, db)

    # 活鲜原料库存（DB查询）
    tid = _uuid(tenant_id)
    sid = _uuid(store_id)
    inv_q = (
        select(Ingredient)
        .where(
            Ingredient.tenant_id == tid,
            Ingredient.store_id == sid,
            Ingredient.category == "seafood",
            Ingredient.is_deleted == False,  # noqa: E712
        )
    )
    result = await db.execute(inv_q)
    seafood_items = result.scalars().all()

    inventory_items = []
    total_value_fen = 0
    alerts = []

    for item in seafood_items:
        value = round((item.unit_price_fen or 0) * item.current_quantity)
        total_value_fen += value

        status_key = _status_key(str(item.id), store_id, tenant_id)
        records = _live_status_records.get(status_key, [])
        current_live_status = records[-1]["status"] if records else LIVE_STATUS_ALIVE

        inventory_items.append({
            "id": str(item.id),
            "name": item.ingredient_name,
            "quantity_kg": item.current_quantity,
            "unit_price_fen": item.unit_price_fen,
            "value_fen": value,
            "status": item.status,
            "live_status": current_live_status,
        })

        # 库存预警
        if item.status in (InventoryStatus.low.value, InventoryStatus.critical.value):
            alerts.append({
                "type": "low_stock",
                "ingredient": item.ingredient_name,
                "current_qty": item.current_quantity,
                "min_qty": item.min_quantity,
                "severity": "critical" if item.status == InventoryStatus.critical.value else "warning",
            })

        # 活鲜状态预警
        if current_live_status == LIVE_STATUS_WEAK:
            alerts.append({
                "type": "weak_seafood",
                "ingredient": item.ingredient_name,
                "severity": "warning",
                "suggestion": "建议尽快售出或降价促销",
            })

    log.info("seafood_dashboard.built", item_count=len(inventory_items), alert_count=len(alerts))

    return {
        "store_id": store_id,
        "inventory": {
            "items": inventory_items,
            "total_count": len(inventory_items),
        },
        "tank_summary": tank_data["summary"],
        "loss_today": {
            "dead_loss_g": loss_data["dead_loss_g"],
            "weak_loss_g": loss_data["weak_loss_g"],
            "total_loss_value_fen": loss_data["total_loss_value_fen"],
        },
        "total_inventory_value_fen": total_value_fen,
        "alerts": alerts,
    }


# ─── 仓库/档口库存区分 ───


async def get_warehouse_stock(
    store_id: str,
    warehouse_type: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """按仓库类型获取库存。

    Args:
        store_id: 门店ID
        warehouse_type: 仓库类型 central/store/dept
        tenant_id: 租户ID
        db: 数据库会话

    Returns:
        {"store_id": str, "warehouse_type": str, "items": [...], "total_value_fen": int}
    """
    if warehouse_type not in _VALID_WAREHOUSE_TYPES:
        raise ValueError(f"无效仓库类型: {warehouse_type}，必须是 {_VALID_WAREHOUSE_TYPES}")

    log = logger.bind(store_id=store_id, warehouse_type=warehouse_type, tenant_id=tenant_id)
    await _set_tenant(db, tenant_id)

    key = _wh_key(store_id, warehouse_type, tenant_id)
    items = _warehouse_stock.get(key, [])

    total_value = sum(item.get("value_fen", 0) for item in items)

    log.info("warehouse_stock.fetched", warehouse_type=warehouse_type, item_count=len(items))

    return {
        "store_id": store_id,
        "warehouse_type": warehouse_type,
        "items": items,
        "total_value_fen": total_value,
    }


def register_warehouse_item(
    store_id: str,
    warehouse_type: str,
    tenant_id: str,
    ingredient_id: str,
    ingredient_name: str,
    quantity_g: float,
    unit_price_fen: int = 0,
) -> dict:
    """注册仓库库存项（内部辅助）。"""
    if warehouse_type not in _VALID_WAREHOUSE_TYPES:
        raise ValueError(f"无效仓库类型: {warehouse_type}")

    key = _wh_key(store_id, warehouse_type, tenant_id)
    items = _warehouse_stock.setdefault(key, [])

    item = {
        "ingredient_id": ingredient_id,
        "ingredient_name": ingredient_name,
        "quantity_g": quantity_g,
        "unit_price_fen": unit_price_fen,
        "value_fen": round(unit_price_fen * quantity_g / 1000.0),
        "warehouse_type": warehouse_type,
        "updated_at": _now().isoformat(),
    }
    items.append(item)
    return item


async def transfer_between_locations(
    from_location: dict,
    to_location: dict,
    items: list[dict],
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """仓库到档口领料调拨。

    Args:
        from_location: {"store_id": str, "warehouse_type": str}
        to_location: {"store_id": str, "warehouse_type": str}
        items: [{"ingredient_id": str, "quantity_g": float}]
        tenant_id: 租户ID
        db: 数据库会话

    Returns:
        {"transfer_id": str, "from": str, "to": str,
         "items_transferred": int, "total_weight_g": float}
    """
    log = logger.bind(tenant_id=tenant_id)

    from_type = from_location.get("warehouse_type", "")
    to_type = to_location.get("warehouse_type", "")
    from_store = from_location.get("store_id", "")
    to_store = to_location.get("store_id", "")

    if from_type not in _VALID_WAREHOUSE_TYPES:
        raise ValueError(f"来源仓库类型无效: {from_type}")
    if to_type not in _VALID_WAREHOUSE_TYPES:
        raise ValueError(f"目标仓库类型无效: {to_type}")
    if not items:
        raise ValueError("调拨物品列表不能为空")

    await _set_tenant(db, tenant_id)

    transfer_id = uuid.uuid4().hex[:12].upper()
    total_weight_g = 0.0
    transferred_count = 0

    from_key = _wh_key(from_store, from_type, tenant_id)
    to_key = _wh_key(to_store, to_type, tenant_id)

    from_items = _warehouse_stock.get(from_key, [])
    to_items = _warehouse_stock.setdefault(to_key, [])

    for transfer_item in items:
        ing_id = transfer_item["ingredient_id"]
        qty_g = transfer_item["quantity_g"]

        if qty_g <= 0:
            raise ValueError(f"调拨数量必须大于0: {ing_id}")

        # 从来源扣减
        source_found = False
        for src_item in from_items:
            if src_item["ingredient_id"] == ing_id:
                if src_item["quantity_g"] < qty_g:
                    raise ValueError(
                        f"库存不足: {ing_id} 需要 {qty_g}g, 当前 {src_item['quantity_g']}g"
                    )
                src_item["quantity_g"] -= qty_g
                src_item["value_fen"] = round(
                    src_item["unit_price_fen"] * src_item["quantity_g"] / 1000.0
                )
                source_found = True

                # 添加到目标
                to_items.append({
                    "ingredient_id": ing_id,
                    "ingredient_name": src_item.get("ingredient_name", ""),
                    "quantity_g": qty_g,
                    "unit_price_fen": src_item.get("unit_price_fen", 0),
                    "value_fen": round(src_item.get("unit_price_fen", 0) * qty_g / 1000.0),
                    "warehouse_type": to_type,
                    "transfer_id": transfer_id,
                    "updated_at": _now().isoformat(),
                })
                break

        if not source_found:
            raise ValueError(f"来源仓库中未找到原料: {ing_id}")

        total_weight_g += qty_g
        transferred_count += 1

    log.info(
        "transfer.completed",
        transfer_id=transfer_id,
        from_location=f"{from_store}/{from_type}",
        to_location=f"{to_store}/{to_type}",
        items=transferred_count,
        total_weight_g=total_weight_g,
    )

    return {
        "transfer_id": transfer_id,
        "from": f"{from_store}/{from_type}",
        "to": f"{to_store}/{to_type}",
        "items_transferred": transferred_count,
        "total_weight_g": total_weight_g,
    }
