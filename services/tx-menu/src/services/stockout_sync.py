"""沽清联动服务 — 标记沽清 / 自动检测 / 恢复供应

菜品沽清状态与库存系统联动：
- 手动沽清：前台/厨房直接标记
- 自动沽清：基于库存数据自动检测（BOM 配方原料不足则沽清）
- 恢复供应：补货后手动恢复

菜品状态: sold_out ↔ active
"""
import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog

from shared.events import UniversalPublisher, MenuEventType

log = structlog.get_logger()

# ─── 沽清原因 ───
REASON_MANUAL = "manual"              # 手动沽清（厨房/前台操作）
REASON_STOCK_DEPLETED = "stock_depleted"  # 库存耗尽
REASON_INGREDIENT_SHORT = "ingredient_short"  # BOM 原料不足
REASON_QUALITY_ISSUE = "quality_issue"  # 品质问题
VALID_REASONS = {REASON_MANUAL, REASON_STOCK_DEPLETED, REASON_INGREDIENT_SHORT, REASON_QUALITY_ISSUE}

# ─── In-Memory Storage ───
_sold_out_records: dict[str, dict] = {}  # "{dish_id}:{store_id}:{tenant_id}" → record


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def mark_sold_out(
    dish_id: str,
    store_id: str,
    reason: str,
    tenant_id: str,
    *,
    operator: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    """标记菜品沽清。

    Args:
        dish_id: 菜品 ID
        store_id: 门店 ID
        reason: 沽清原因 manual/stock_depleted/ingredient_short/quality_issue
        tenant_id: 租户 ID
        operator: 操作人（可选）
        notes: 备注（可选）

    Returns:
        dict — 沽清记录
    """
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")
    if not dish_id:
        raise ValueError("dish_id 不能为空")
    if not store_id:
        raise ValueError("store_id 不能为空")
    if reason not in VALID_REASONS:
        raise ValueError(f"reason 必须为 {VALID_REASONS} 之一，收到: {reason!r}")

    now = _now_iso()
    key = f"{dish_id}:{store_id}:{tenant_id}"

    record = {
        "id": str(uuid.uuid4()),
        "dish_id": dish_id,
        "store_id": store_id,
        "tenant_id": tenant_id,
        "reason": reason,
        "operator": operator,
        "notes": notes,
        "status": "sold_out",
        "sold_out_at": now,
        "restored_at": None,
    }

    _sold_out_records[key] = record
    log.info(
        "dish.sold_out",
        tenant_id=tenant_id,
        dish_id=dish_id,
        store_id=store_id,
        reason=reason,
    )

    asyncio.create_task(UniversalPublisher.publish(
        event_type=MenuEventType.DISH_SOLDOUT,
        tenant_id=uuid.UUID(tenant_id),
        store_id=uuid.UUID(store_id),
        entity_id=uuid.UUID(dish_id),
        event_data={"dish_id": dish_id, "store_id": store_id},
        source_service="tx-menu",
    ))

    return record


def auto_check_stockout(
    store_id: str,
    tenant_id: str,
    db: Optional[dict] = None,
) -> list[dict]:
    """基于库存自动检测沽清菜品。

    遍历门店菜品的 BOM 配方，若任一必需原料库存低于安全阈值则标记沽清。

    Args:
        store_id: 门店 ID
        tenant_id: 租户 ID
        db: 模拟数据源，含 "dishes" 和 "ingredients" 字段
            dishes: [{"dish_id", "dish_name", "requires_inventory", "ingredients": [{"ingredient_id", "quantity_needed"}]}]
            ingredients: {"ingredient_id": {"current_quantity": float, "min_quantity": float}}

    Returns:
        list[dict] — 新增沽清记录列表
    """
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")
    if not store_id:
        raise ValueError("store_id 不能为空")

    if not db:
        log.info("stockout.auto_check.skip", tenant_id=tenant_id, store_id=store_id, reason="no_db")
        return []

    dishes = db.get("dishes", [])
    ingredients = db.get("ingredients", {})
    newly_sold_out: list[dict] = []

    for dish in dishes:
        if not dish.get("requires_inventory", True):
            continue

        dish_id = dish.get("dish_id", "")
        key = f"{dish_id}:{store_id}:{tenant_id}"

        # 已沽清则跳过
        if key in _sold_out_records and _sold_out_records[key]["status"] == "sold_out":
            continue

        # 检查 BOM 原料
        dish_ingredients = dish.get("ingredients", [])
        for ing in dish_ingredients:
            ing_id = ing.get("ingredient_id", "")
            stock = ingredients.get(ing_id, {})
            current_qty = stock.get("current_quantity", 0)
            min_qty = stock.get("min_quantity", 0)
            quantity_needed = ing.get("quantity_needed", 0)

            # 库存不足以制作一份
            if current_qty < quantity_needed or current_qty <= 0:
                record = mark_sold_out(
                    dish_id=dish_id,
                    store_id=store_id,
                    reason=REASON_INGREDIENT_SHORT,
                    tenant_id=tenant_id,
                    notes=f"原料 {ing_id} 库存不足: 当前 {current_qty}, 需要 {quantity_needed}",
                )
                newly_sold_out.append(record)
                break  # 一个原料不足即沽清整道菜

    log.info(
        "stockout.auto_check.done",
        tenant_id=tenant_id,
        store_id=store_id,
        checked=len(dishes),
        newly_sold_out=len(newly_sold_out),
    )
    return newly_sold_out


def get_sold_out_list(store_id: str, tenant_id: str) -> list[dict]:
    """获取门店当前沽清清单。

    Args:
        store_id: 门店 ID
        tenant_id: 租户 ID

    Returns:
        list[dict] — 所有状态为 sold_out 的记录
    """
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")
    if not store_id:
        raise ValueError("store_id 不能为空")

    return [
        r for r in _sold_out_records.values()
        if r["store_id"] == store_id
        and r["tenant_id"] == tenant_id
        and r["status"] == "sold_out"
    ]


def restore_dish(
    dish_id: str,
    store_id: str,
    tenant_id: str,
    *,
    operator: Optional[str] = None,
) -> dict:
    """恢复沽清菜品供应。

    Args:
        dish_id: 菜品 ID
        store_id: 门店 ID
        tenant_id: 租户 ID
        operator: 操作人（可选）

    Returns:
        dict — 更新后的沽清记录

    Raises:
        ValueError: 菜品不在沽清状态
    """
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")
    if not dish_id:
        raise ValueError("dish_id 不能为空")
    if not store_id:
        raise ValueError("store_id 不能为空")

    key = f"{dish_id}:{store_id}:{tenant_id}"
    record = _sold_out_records.get(key)

    if not record or record["status"] != "sold_out":
        raise ValueError(f"菜品 {dish_id} 在门店 {store_id} 不在沽清状态")

    now = _now_iso()
    record["status"] = "restored"
    record["restored_at"] = now
    record["restore_operator"] = operator

    log.info(
        "dish.restored",
        tenant_id=tenant_id,
        dish_id=dish_id,
        store_id=store_id,
    )
    return record


# ─── 测试工具 ───


def _clear_all() -> None:
    """清空内部存储，仅供测试用"""
    _sold_out_records.clear()
