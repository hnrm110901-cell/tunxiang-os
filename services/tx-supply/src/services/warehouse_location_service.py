"""库位/库区/温区服务 — TASK-2 仓储库存细化

核心逻辑：
  - create_zone / list_zones / update_zone
  - create_location / list_locations / get_location_by_code
  - bind_ingredient_to_location
  - auto_allocate_location  入库时按温区类型 + ABC 优先级匹配可用库位
  - move_between_locations  库位间转移（更新 inventory_by_location）
  - query_inventory_by_location
  - compute_zone_utilization
  - suggest_abc_optimization

事件：
  关键操作发 LocationEventType.INVENTORY_MOVED / LOCATION_BOUND
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import LocationEventType

from ..models.warehouse_location import (
    CATEGORY_TO_TEMPERATURE_TYPES,
    AbcClass,
    AutoAllocateRequest,
    BindIngredientRequest,
    LocationCreate,
    MoveBetweenLocationsRequest,
    TemperatureType,
    ZoneCreate,
    ZoneUpdate,
)

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 自定义异常
# ─────────────────────────────────────────────────────────────────────────────


class WarehouseLocationError(Exception):
    """库位服务通用异常基类"""


class TemperatureMismatchError(WarehouseLocationError):
    """食材类目与库区温区不匹配"""


class LocationCapacityExceededError(WarehouseLocationError):
    """库位容量超限"""


class LocationNotFoundError(WarehouseLocationError):
    """库位不存在"""


class ZoneNotFoundError(WarehouseLocationError):
    """库区不存在"""


class InsufficientInventoryError(WarehouseLocationError):
    """库存不足"""


class DuplicateCodeError(WarehouseLocationError):
    """重复编码（zone_code 或 location_code）"""


# ─────────────────────────────────────────────────────────────────────────────
# 内部工具
# ─────────────────────────────────────────────────────────────────────────────


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    """设置 RLS 租户上下文。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _row_to_dict(row: Any) -> dict:
    """把 SQLAlchemy mapping row 转成基础类型 dict（UUID/Decimal 转 str/float）。"""
    if row is None:
        return {}
    out: dict = {}
    for k, v in dict(row).items():
        if isinstance(v, uuid.UUID):
            out[k] = str(v)
        elif isinstance(v, Decimal):
            out[k] = float(v)
        elif isinstance(v, (datetime, date)):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 1. 库区（Zone）CRUD
# ─────────────────────────────────────────────────────────────────────────────


async def create_zone(
    body: ZoneCreate,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """创建库区。"""
    await _set_tenant(db, tenant_id)
    new_id = uuid.uuid4()
    try:
        await db.execute(
            text(
                """
                INSERT INTO warehouse_zones (
                    id, tenant_id, store_id, zone_code, zone_name,
                    temperature_type, min_temp_celsius, max_temp_celsius,
                    description, enabled
                ) VALUES (
                    :id, :tenant_id::uuid, :store_id::uuid, :zone_code, :zone_name,
                    :temperature_type, :min_temp, :max_temp,
                    :description, :enabled
                )
                """
            ),
            {
                "id": str(new_id),
                "tenant_id": tenant_id,
                "store_id": body.store_id,
                "zone_code": body.zone_code,
                "zone_name": body.zone_name,
                "temperature_type": body.temperature_type.value,
                "min_temp": body.min_temp_celsius,
                "max_temp": body.max_temp_celsius,
                "description": body.description,
                "enabled": body.enabled,
            },
        )
        await db.flush()
    except IntegrityError as exc:
        raise DuplicateCodeError(
            f"zone_code={body.zone_code} 在 store {body.store_id} 已存在"
        ) from exc

    logger.info(
        "warehouse_zone_created",
        zone_id=str(new_id),
        zone_code=body.zone_code,
        store_id=body.store_id,
        tenant_id=tenant_id,
    )
    return await _fetch_zone(new_id, tenant_id, db)


async def _fetch_zone(zone_id: uuid.UUID | str, tenant_id: str, db: AsyncSession) -> dict:
    await _set_tenant(db, tenant_id)
    result = await db.execute(
        text(
            """
            SELECT id, tenant_id, store_id, zone_code, zone_name, temperature_type,
                   min_temp_celsius, max_temp_celsius, description, enabled,
                   created_at, updated_at
              FROM warehouse_zones
             WHERE id = :id::uuid AND is_deleted = FALSE
            """
        ),
        {"id": str(zone_id)},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise ZoneNotFoundError(f"zone {zone_id} 不存在")
    return _row_to_dict(row)


async def list_zones(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
    temperature_type: Optional[str] = None,
) -> list[dict]:
    await _set_tenant(db, tenant_id)
    where = "store_id = :store_id::uuid AND is_deleted = FALSE"
    params: dict = {"store_id": store_id}
    if temperature_type:
        where += " AND temperature_type = :tt"
        params["tt"] = temperature_type
    result = await db.execute(
        text(
            f"""
            SELECT id, tenant_id, store_id, zone_code, zone_name, temperature_type,
                   min_temp_celsius, max_temp_celsius, description, enabled,
                   created_at, updated_at
              FROM warehouse_zones
             WHERE {where}
             ORDER BY zone_code ASC
            """
        ),
        params,
    )
    return [_row_to_dict(r) for r in result.mappings().all()]


async def update_zone(
    zone_id: str,
    body: ZoneUpdate,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    await _set_tenant(db, tenant_id)
    sets: list[str] = []
    params: dict = {"id": zone_id}
    if body.zone_name is not None:
        sets.append("zone_name = :zone_name")
        params["zone_name"] = body.zone_name
    if body.temperature_type is not None:
        sets.append("temperature_type = :tt")
        params["tt"] = body.temperature_type.value
    if body.min_temp_celsius is not None:
        sets.append("min_temp_celsius = :min_t")
        params["min_t"] = body.min_temp_celsius
    if body.max_temp_celsius is not None:
        sets.append("max_temp_celsius = :max_t")
        params["max_t"] = body.max_temp_celsius
    if body.description is not None:
        sets.append("description = :desc")
        params["desc"] = body.description
    if body.enabled is not None:
        sets.append("enabled = :enabled")
        params["enabled"] = body.enabled
    if not sets:
        return await _fetch_zone(zone_id, tenant_id, db)

    result = await db.execute(
        text(
            f"""
            UPDATE warehouse_zones
               SET {', '.join(sets)}
             WHERE id = :id::uuid AND is_deleted = FALSE
            RETURNING id
            """
        ),
        params,
    )
    if result.first() is None:
        raise ZoneNotFoundError(f"zone {zone_id} 不存在")
    await db.flush()
    return await _fetch_zone(zone_id, tenant_id, db)


# ─────────────────────────────────────────────────────────────────────────────
# 2. 库位（Location）CRUD
# ─────────────────────────────────────────────────────────────────────────────


async def create_location(
    body: LocationCreate,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """创建库位。前置校验 zone 存在。"""
    await _set_tenant(db, tenant_id)

    # 校验 zone 存在 + 同租户/门店
    zone_check = await db.execute(
        text(
            "SELECT store_id FROM warehouse_zones "
            "WHERE id = :zone_id::uuid AND is_deleted = FALSE"
        ),
        {"zone_id": body.zone_id},
    )
    zone_row = zone_check.mappings().one_or_none()
    if zone_row is None:
        raise ZoneNotFoundError(f"zone {body.zone_id} 不存在")
    if str(zone_row["store_id"]) != str(body.store_id):
        raise WarehouseLocationError(
            f"zone {body.zone_id} 隶属门店 {zone_row['store_id']}, "
            f"不可在门店 {body.store_id} 下创建库位"
        )

    new_id = uuid.uuid4()
    try:
        await db.execute(
            text(
                """
                INSERT INTO warehouse_locations (
                    id, tenant_id, zone_id, store_id, location_code,
                    aisle, rack, shelf, abc_class, max_capacity_units, enabled
                ) VALUES (
                    :id, :tenant_id::uuid, :zone_id::uuid, :store_id::uuid, :location_code,
                    :aisle, :rack, :shelf, :abc_class, :max_capacity, :enabled
                )
                """
            ),
            {
                "id": str(new_id),
                "tenant_id": tenant_id,
                "zone_id": body.zone_id,
                "store_id": body.store_id,
                "location_code": body.location_code,
                "aisle": body.aisle,
                "rack": body.rack,
                "shelf": body.shelf,
                "abc_class": body.abc_class.value if body.abc_class else None,
                "max_capacity": body.max_capacity_units,
                "enabled": body.enabled,
            },
        )
        await db.flush()
    except IntegrityError as exc:
        raise DuplicateCodeError(
            f"location_code={body.location_code} 在 store {body.store_id} 已存在"
        ) from exc

    logger.info(
        "warehouse_location_created",
        location_id=str(new_id),
        location_code=body.location_code,
        zone_id=body.zone_id,
        tenant_id=tenant_id,
    )
    return await _fetch_location(new_id, tenant_id, db)


async def _fetch_location(
    location_id: uuid.UUID | str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    await _set_tenant(db, tenant_id)
    result = await db.execute(
        text(
            """
            SELECT id, tenant_id, zone_id, store_id, location_code,
                   aisle, rack, shelf, abc_class, max_capacity_units, enabled,
                   created_at, updated_at
              FROM warehouse_locations
             WHERE id = :id::uuid AND is_deleted = FALSE
            """
        ),
        {"id": str(location_id)},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise LocationNotFoundError(f"location {location_id} 不存在")
    return _row_to_dict(row)


async def list_locations(
    tenant_id: str,
    db: AsyncSession,
    store_id: Optional[str] = None,
    zone_id: Optional[str] = None,
    abc_class: Optional[str] = None,
    enabled_only: bool = True,
) -> list[dict]:
    await _set_tenant(db, tenant_id)
    where_parts = ["is_deleted = FALSE"]
    params: dict = {}
    if store_id:
        where_parts.append("store_id = :store_id::uuid")
        params["store_id"] = store_id
    if zone_id:
        where_parts.append("zone_id = :zone_id::uuid")
        params["zone_id"] = zone_id
    if abc_class:
        where_parts.append("abc_class = :abc")
        params["abc"] = abc_class
    if enabled_only:
        where_parts.append("enabled = TRUE")

    result = await db.execute(
        text(
            f"""
            SELECT id, tenant_id, zone_id, store_id, location_code,
                   aisle, rack, shelf, abc_class, max_capacity_units, enabled,
                   created_at, updated_at
              FROM warehouse_locations
             WHERE {' AND '.join(where_parts)}
             ORDER BY location_code ASC
            """
        ),
        params,
    )
    return [_row_to_dict(r) for r in result.mappings().all()]


async def get_location_by_code(
    location_code: str,
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    await _set_tenant(db, tenant_id)
    result = await db.execute(
        text(
            """
            SELECT id, tenant_id, zone_id, store_id, location_code,
                   aisle, rack, shelf, abc_class, max_capacity_units, enabled,
                   created_at, updated_at
              FROM warehouse_locations
             WHERE location_code = :code AND store_id = :store_id::uuid
               AND is_deleted = FALSE
            """
        ),
        {"code": location_code, "store_id": store_id},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise LocationNotFoundError(f"location_code={location_code} 不存在")
    return _row_to_dict(row)


# ─────────────────────────────────────────────────────────────────────────────
# 3. 食材→库位 绑定
# ─────────────────────────────────────────────────────────────────────────────


async def bind_ingredient_to_location(
    location_id: str,
    body: BindIngredientRequest,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """绑定食材到库位。

    若 is_primary=True，先把同租户内该食材的其他绑定置为 is_primary=False。
    """
    await _set_tenant(db, tenant_id)

    # 校验 location 存在
    await _fetch_location(location_id, tenant_id, db)

    if body.is_primary:
        await db.execute(
            text(
                """
                UPDATE ingredient_location_bindings
                   SET is_primary = FALSE
                 WHERE ingredient_id = :ing_id::uuid
                   AND is_deleted = FALSE
                """
            ),
            {"ing_id": body.ingredient_id},
        )

    binding_id = uuid.uuid4()
    try:
        await db.execute(
            text(
                """
                INSERT INTO ingredient_location_bindings (
                    id, tenant_id, ingredient_id, location_id, is_primary, bound_by
                ) VALUES (
                    :id, :tenant_id::uuid, :ing_id::uuid, :loc_id::uuid,
                    :is_primary, :bound_by
                )
                ON CONFLICT (tenant_id, ingredient_id, location_id) DO UPDATE
                   SET is_primary = EXCLUDED.is_primary,
                       bound_by   = EXCLUDED.bound_by,
                       bound_at   = NOW(),
                       is_deleted = FALSE
                """
            ),
            {
                "id": str(binding_id),
                "tenant_id": tenant_id,
                "ing_id": body.ingredient_id,
                "loc_id": location_id,
                "is_primary": body.is_primary,
                "bound_by": body.bound_by,
            },
        )
        await db.flush()
    except IntegrityError as exc:
        raise WarehouseLocationError(f"绑定失败: {exc}") from exc

    asyncio.create_task(
        emit_event(
            event_type=LocationEventType.LOCATION_BOUND,
            tenant_id=tenant_id,
            stream_id=body.ingredient_id,
            payload={
                "ingredient_id": body.ingredient_id,
                "location_id": location_id,
                "is_primary": body.is_primary,
            },
            source_service="tx-supply",
            metadata={"bound_by": body.bound_by},
        )
    )

    logger.info(
        "ingredient_location_bound",
        ingredient_id=body.ingredient_id,
        location_id=location_id,
        is_primary=body.is_primary,
        tenant_id=tenant_id,
    )
    return {
        "ok": True,
        "ingredient_id": body.ingredient_id,
        "location_id": location_id,
        "is_primary": body.is_primary,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4. auto_allocate_location — 入库时自动定位
# ─────────────────────────────────────────────────────────────────────────────


async def auto_allocate_location(
    body: AutoAllocateRequest,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """根据食材类目匹配可用库位，并写入 inventory_by_location。

    匹配规则：
      1. 优先取该食材已绑定的主库位（若存在且类目兼容）
      2. 否则按 ingredient_category → CATEGORY_TO_TEMPERATURE_TYPES 找候选库区
      3. 在候选库区下，按 abc_class（A 优先）+ 容量未满 排序，挑首个
      4. 若 ingredient_category 与库区温区不匹配，抛 TemperatureMismatchError
    """
    await _set_tenant(db, tenant_id)

    # ── 1. 首选：已绑定的主库位 ──
    primary_result = await db.execute(
        text(
            """
            SELECT l.id, l.zone_id, l.location_code, l.abc_class,
                   l.max_capacity_units, z.temperature_type
              FROM ingredient_location_bindings b
              JOIN warehouse_locations l ON b.location_id = l.id
              JOIN warehouse_zones z ON l.zone_id = z.id
             WHERE b.ingredient_id = :ing_id::uuid
               AND b.is_primary = TRUE
               AND b.is_deleted = FALSE
               AND l.is_deleted = FALSE
               AND l.enabled = TRUE
               AND l.store_id = :store_id::uuid
             LIMIT 1
            """
        ),
        {"ing_id": body.ingredient_id, "store_id": body.store_id},
    )
    primary_row = primary_result.mappings().one_or_none()

    candidate: Optional[dict] = None

    if primary_row is not None:
        # 校验温区兼容（若提供了 ingredient_category）
        if body.ingredient_category:
            allowed = CATEGORY_TO_TEMPERATURE_TYPES.get(body.ingredient_category)
            if allowed is not None:
                if TemperatureType(primary_row["temperature_type"]) not in allowed:
                    raise TemperatureMismatchError(
                        f"主库位温区 {primary_row['temperature_type']} 与食材类目 "
                        f"{body.ingredient_category} 不兼容"
                    )
        candidate = _row_to_dict(primary_row)

    # ── 2. 否则按温区类目挑可用库位 ──
    if candidate is None:
        if not body.ingredient_category:
            raise WarehouseLocationError(
                f"食材 {body.ingredient_id} 无主库位绑定，"
                f"且未提供 ingredient_category 无法自动匹配"
            )
        allowed = CATEGORY_TO_TEMPERATURE_TYPES.get(body.ingredient_category)
        if not allowed:
            raise TemperatureMismatchError(
                f"未知食材类目 {body.ingredient_category}，无温区映射"
            )
        allowed_values = [t.value for t in allowed]

        # ABC 排序：A=1, B=2, C=3, NULL=4
        result = await db.execute(
            text(
                """
                SELECT l.id, l.zone_id, l.location_code, l.abc_class,
                       l.max_capacity_units, z.temperature_type,
                       COALESCE(
                         (SELECT SUM(quantity) FROM inventory_by_location
                           WHERE location_id = l.id), 0
                       ) AS current_units
                  FROM warehouse_locations l
                  JOIN warehouse_zones z ON l.zone_id = z.id
                 WHERE l.store_id = :store_id::uuid
                   AND l.enabled = TRUE
                   AND l.is_deleted = FALSE
                   AND z.is_deleted = FALSE
                   AND z.enabled = TRUE
                   AND z.temperature_type = ANY(:allowed)
                 ORDER BY
                   CASE l.abc_class
                     WHEN 'A' THEN 1 WHEN 'B' THEN 2 WHEN 'C' THEN 3 ELSE 4 END,
                   l.location_code
                """
            ),
            {"store_id": body.store_id, "allowed": allowed_values},
        )
        rows = result.mappings().all()
        if not rows:
            raise LocationNotFoundError(
                f"店 {body.store_id} 内无可用 {allowed_values} 温区库位"
            )

        # 容量过滤：max_capacity_units 为 NULL 视为无限
        for r in rows:
            cap = r["max_capacity_units"]
            cur = float(r["current_units"] or 0)
            if cap is None or cur + float(body.quantity) <= float(cap):
                candidate = _row_to_dict(r)
                break

        if candidate is None:
            raise LocationCapacityExceededError(
                f"店 {body.store_id} 内 {allowed_values} 温区所有库位容量已满"
            )

    # ── 3. 写入 inventory_by_location ──
    location_id = candidate["id"]
    batch_no = body.batch_no or ""
    expiry_date = body.expiry_date

    await db.execute(
        text(
            """
            INSERT INTO inventory_by_location (
                tenant_id, store_id, location_id, ingredient_id,
                batch_no, quantity, last_in_at, expiry_date
            ) VALUES (
                :tenant_id::uuid, :store_id::uuid, :loc_id::uuid, :ing_id::uuid,
                :batch_no, :qty, NOW(), :expiry
            )
            ON CONFLICT (tenant_id, location_id, ingredient_id, batch_no) DO UPDATE
               SET quantity     = inventory_by_location.quantity + EXCLUDED.quantity,
                   last_in_at   = NOW(),
                   expiry_date  = COALESCE(EXCLUDED.expiry_date,
                                            inventory_by_location.expiry_date)
            """
        ),
        {
            "tenant_id": tenant_id,
            "store_id": body.store_id,
            "loc_id": location_id,
            "ing_id": body.ingredient_id,
            "batch_no": batch_no,
            "qty": body.quantity,
            "expiry": expiry_date,
        },
    )
    await db.flush()

    logger.info(
        "auto_allocate_location",
        ingredient_id=body.ingredient_id,
        location_id=location_id,
        location_code=candidate.get("location_code"),
        quantity=float(body.quantity),
        tenant_id=tenant_id,
    )

    return {
        "ok": True,
        "location_id": location_id,
        "location_code": candidate.get("location_code"),
        "zone_id": candidate.get("zone_id"),
        "temperature_type": candidate.get("temperature_type"),
        "abc_class": candidate.get("abc_class"),
        "quantity_allocated": float(body.quantity),
        "batch_no": batch_no,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 5. move_between_locations — 库位间转移
# ─────────────────────────────────────────────────────────────────────────────


async def move_between_locations(
    body: MoveBetweenLocationsRequest,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """从 A 库位转移指定数量到 B 库位（同租户）。

    更新两条 inventory_by_location 记录，并发 INVENTORY_MOVED 事件。
    """
    await _set_tenant(db, tenant_id)

    if body.from_location_id == body.to_location_id:
        raise WarehouseLocationError("源库位与目标库位相同")

    batch_no = body.batch_no or ""

    # ── 1. 校验源库存够 ──
    src_result = await db.execute(
        text(
            """
            SELECT id, quantity, expiry_date, store_id
              FROM inventory_by_location
             WHERE location_id = :loc_id::uuid
               AND ingredient_id = :ing_id::uuid
               AND batch_no = :batch_no
            """
        ),
        {
            "loc_id": body.from_location_id,
            "ing_id": body.ingredient_id,
            "batch_no": batch_no,
        },
    )
    src_row = src_result.mappings().one_or_none()
    if src_row is None:
        raise InsufficientInventoryError(
            f"源库位 {body.from_location_id} 无 ingredient={body.ingredient_id} "
            f"batch={batch_no} 库存"
        )
    src_qty = Decimal(src_row["quantity"])
    if src_qty < body.quantity:
        raise InsufficientInventoryError(
            f"源库位库存 {src_qty} 不足以转移 {body.quantity}"
        )

    # ── 2. 目标库位 store_id 与源一致 ──
    tgt_loc_result = await db.execute(
        text(
            "SELECT store_id FROM warehouse_locations "
            "WHERE id = :id::uuid AND is_deleted = FALSE"
        ),
        {"id": body.to_location_id},
    )
    tgt_loc_row = tgt_loc_result.mappings().one_or_none()
    if tgt_loc_row is None:
        raise LocationNotFoundError(f"目标库位 {body.to_location_id} 不存在")
    if str(tgt_loc_row["store_id"]) != str(src_row["store_id"]):
        raise WarehouseLocationError(
            "源/目标库位不在同一门店，请使用门店间调拨"
        )

    # ── 3. 扣减源 ──
    await db.execute(
        text(
            """
            UPDATE inventory_by_location
               SET quantity    = quantity - :qty,
                   last_out_at = NOW()
             WHERE id = :id::uuid
            """
        ),
        {"qty": body.quantity, "id": str(src_row["id"])},
    )

    # ── 4. 增加目标 ──
    await db.execute(
        text(
            """
            INSERT INTO inventory_by_location (
                tenant_id, store_id, location_id, ingredient_id,
                batch_no, quantity, last_in_at, expiry_date
            ) VALUES (
                :tenant_id::uuid, :store_id::uuid, :loc_id::uuid, :ing_id::uuid,
                :batch_no, :qty, NOW(), :expiry
            )
            ON CONFLICT (tenant_id, location_id, ingredient_id, batch_no) DO UPDATE
               SET quantity   = inventory_by_location.quantity + EXCLUDED.quantity,
                   last_in_at = NOW()
            """
        ),
        {
            "tenant_id": tenant_id,
            "store_id": str(src_row["store_id"]),
            "loc_id": body.to_location_id,
            "ing_id": body.ingredient_id,
            "batch_no": batch_no,
            "qty": body.quantity,
            "expiry": src_row.get("expiry_date"),
        },
    )
    await db.flush()

    asyncio.create_task(
        emit_event(
            event_type=LocationEventType.INVENTORY_MOVED,
            tenant_id=tenant_id,
            stream_id=body.ingredient_id,
            payload={
                "ingredient_id": body.ingredient_id,
                "from_location_id": body.from_location_id,
                "to_location_id": body.to_location_id,
                "quantity": float(body.quantity),
                "batch_no": batch_no,
            },
            store_id=str(src_row["store_id"]),
            source_service="tx-supply",
            metadata={"operator_id": body.operator_id},
        )
    )

    logger.info(
        "inventory_moved_between_locations",
        from_location=body.from_location_id,
        to_location=body.to_location_id,
        ingredient_id=body.ingredient_id,
        quantity=float(body.quantity),
        tenant_id=tenant_id,
    )

    return {
        "ok": True,
        "from_location_id": body.from_location_id,
        "to_location_id": body.to_location_id,
        "ingredient_id": body.ingredient_id,
        "quantity": float(body.quantity),
        "batch_no": batch_no,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 6. query_inventory_by_location
# ─────────────────────────────────────────────────────────────────────────────


async def query_inventory_by_location(
    tenant_id: str,
    db: AsyncSession,
    store_id: Optional[str] = None,
    zone_id: Optional[str] = None,
    location_id: Optional[str] = None,
    ingredient_id: Optional[str] = None,
) -> list[dict]:
    """按库位查库存（可按 store / zone / location / ingredient 过滤）。"""
    await _set_tenant(db, tenant_id)

    where = ["1=1"]
    params: dict = {}
    if store_id:
        where.append("ibl.store_id = :store_id::uuid")
        params["store_id"] = store_id
    if location_id:
        where.append("ibl.location_id = :loc_id::uuid")
        params["loc_id"] = location_id
    if ingredient_id:
        where.append("ibl.ingredient_id = :ing_id::uuid")
        params["ing_id"] = ingredient_id
    if zone_id:
        where.append("l.zone_id = :zone_id::uuid")
        params["zone_id"] = zone_id

    result = await db.execute(
        text(
            f"""
            SELECT ibl.id, ibl.tenant_id, ibl.store_id, ibl.location_id,
                   l.location_code, l.zone_id, z.zone_code, z.temperature_type,
                   ibl.ingredient_id, ibl.batch_no,
                   ibl.quantity, ibl.reserved_quantity,
                   ibl.last_in_at, ibl.last_out_at, ibl.expiry_date
              FROM inventory_by_location ibl
              JOIN warehouse_locations l ON ibl.location_id = l.id
              JOIN warehouse_zones z ON l.zone_id = z.id
             WHERE {' AND '.join(where)}
             ORDER BY z.zone_code, l.location_code, ibl.batch_no
            """
        ),
        params,
    )
    return [_row_to_dict(r) for r in result.mappings().all()]


# ─────────────────────────────────────────────────────────────────────────────
# 7. compute_zone_utilization
# ─────────────────────────────────────────────────────────────────────────────


async def compute_zone_utilization(
    zone_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """库区使用率 = SUM(已用容量) / SUM(总容量)。

    总容量 = 该库区下所有 enabled 库位的 max_capacity_units 之和（NULL 视为 0 不计）；
    已用容量 = 这些库位 inventory_by_location.quantity 之和。
    """
    await _set_tenant(db, tenant_id)

    # 总容量
    total_result = await db.execute(
        text(
            """
            SELECT COUNT(*) AS loc_count,
                   COALESCE(SUM(max_capacity_units), 0) AS total_capacity
              FROM warehouse_locations
             WHERE zone_id = :zone_id::uuid
               AND is_deleted = FALSE
               AND enabled = TRUE
            """
        ),
        {"zone_id": zone_id},
    )
    total_row = total_result.mappings().one_or_none()
    if total_row is None or (total_row["loc_count"] or 0) == 0:
        return {
            "zone_id": zone_id,
            "location_count": 0,
            "total_capacity_units": 0.0,
            "used_units": 0.0,
            "utilization_pct": 0.0,
        }

    used_result = await db.execute(
        text(
            """
            SELECT COALESCE(SUM(ibl.quantity), 0) AS used_units
              FROM inventory_by_location ibl
              JOIN warehouse_locations l ON ibl.location_id = l.id
             WHERE l.zone_id = :zone_id::uuid
               AND l.is_deleted = FALSE
               AND l.enabled = TRUE
            """
        ),
        {"zone_id": zone_id},
    )
    used_row = used_result.mappings().one_or_none()

    total_cap = float(total_row["total_capacity"] or 0)
    used = float((used_row or {}).get("used_units") or 0)
    util = round(used / total_cap, 4) if total_cap > 0 else 0.0

    return {
        "zone_id": zone_id,
        "location_count": int(total_row["loc_count"]),
        "total_capacity_units": total_cap,
        "used_units": used,
        "utilization_pct": util,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 8. suggest_abc_optimization
# ─────────────────────────────────────────────────────────────────────────────


async def suggest_abc_optimization(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
    days: int = 30,
) -> dict:
    """基于近 N 天动销分析建议 ABC 重分类。

    近 days 天 ingredient 出库次数：
      - 前 20% → A
      - 中 30% → B
      - 后 50% → C

    返回每个食材当前主库位的 ABC 与建议 ABC，找出需要调整的项。

    源数据：ingredient_transactions（出库 type='issue' / 'consumption' / 'usage'）；
    若该表不存在或为空，返回空建议。
    """
    await _set_tenant(db, tenant_id)

    # 近 N 天每食材的出库次数（rolling）
    try:
        result = await db.execute(
            text(
                f"""
                SELECT ingredient_id, COUNT(*) AS turn_count
                  FROM ingredient_transactions
                 WHERE store_id = :store_id::uuid
                   AND created_at >= NOW() - INTERVAL '{int(days)} days'
                   AND transaction_type IN ('issue', 'consumption', 'usage')
                 GROUP BY ingredient_id
                """
            ),
            {"store_id": store_id},
        )
        turnover_rows = result.mappings().all()
    except ProgrammingError:
        # 表不存在，返回空建议
        return {
            "store_id": store_id,
            "days": days,
            "suggestions": [],
            "note": "ingredient_transactions 表不存在或不可用",
        }

    if not turnover_rows:
        return {
            "store_id": store_id,
            "days": days,
            "suggestions": [],
            "note": f"近 {days} 天无出库数据",
        }

    # 排序
    sorted_turnover = sorted(
        turnover_rows, key=lambda r: r["turn_count"] or 0, reverse=True
    )
    n = len(sorted_turnover)
    a_cutoff = max(1, int(n * 0.2))
    b_cutoff = max(a_cutoff + 1, int(n * 0.5))

    suggestions = []
    for idx, row in enumerate(sorted_turnover):
        if idx < a_cutoff:
            suggested = AbcClass.A.value
        elif idx < b_cutoff:
            suggested = AbcClass.B.value
        else:
            suggested = AbcClass.C.value

        ing_id = str(row["ingredient_id"])

        # 当前主库位 ABC
        cur_result = await db.execute(
            text(
                """
                SELECT l.id AS loc_id, l.location_code, l.abc_class
                  FROM ingredient_location_bindings b
                  JOIN warehouse_locations l ON b.location_id = l.id
                 WHERE b.ingredient_id = :ing_id::uuid
                   AND b.is_primary = TRUE
                   AND b.is_deleted = FALSE
                 LIMIT 1
                """
            ),
            {"ing_id": ing_id},
        )
        cur_row = cur_result.mappings().one_or_none()
        current_abc = cur_row["abc_class"] if cur_row else None

        if current_abc != suggested:
            suggestions.append(
                {
                    "ingredient_id": ing_id,
                    "turn_count": int(row["turn_count"] or 0),
                    "current_abc": current_abc,
                    "suggested_abc": suggested,
                    "current_location_id": str(cur_row["loc_id"]) if cur_row else None,
                    "current_location_code": cur_row["location_code"]
                    if cur_row
                    else None,
                }
            )

    return {
        "store_id": store_id,
        "days": days,
        "total_ingredients": n,
        "suggestions": suggestions,
        "summary": {
            "to_reclassify": len(suggestions),
            "a_cutoff": a_cutoff,
            "b_cutoff": b_cutoff,
        },
    }
