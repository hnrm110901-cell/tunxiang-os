"""移库与拆组服务

移库: 仓库间商品转移
拆分/组装: 原料拆分或组装成半成品
BOM拆分: 成品按配方拆分为原料
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog

log = structlog.get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. 移库单
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def create_transfer_order(
    from_warehouse: str,
    to_warehouse: str,
    items: List[Dict[str, Any]],
    tenant_id: str,
    db: Any,
) -> Dict[str, Any]:
    """创建移库单。

    Args:
        from_warehouse: 调出仓库 ID
        to_warehouse: 调入仓库 ID
        items: 移库明细 [{ingredient_id, name, quantity, unit, batch_no}]
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        移库单
    """
    if from_warehouse == to_warehouse:
        raise ValueError("调出仓库和调入仓库不能相同")
    if not items:
        raise ValueError("移库单必须包含至少一项商品")

    transfer_id = _gen_id("wtf")
    now = _now_iso()
    total_qty = sum(i.get("quantity", 0) for i in items)

    record: Dict[str, Any] = {
        "transfer_id": transfer_id,
        "from_warehouse": from_warehouse,
        "to_warehouse": to_warehouse,
        "tenant_id": tenant_id,
        "status": "pending",
        "items": items,
        "item_count": len(items),
        "total_qty": round(total_qty, 2),
        "created_at": now,
        "updated_at": now,
    }

    log.info(
        "warehouse_transfer_created",
        transfer_id=transfer_id,
        from_warehouse=from_warehouse,
        to_warehouse=to_warehouse,
        tenant_id=tenant_id,
        item_count=len(items),
    )
    return record


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. 拆分/组装
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def create_split_assembly(
    item_id: str,
    op_type: str,
    components: List[Dict[str, Any]],
    tenant_id: str,
    db: Any,
) -> Dict[str, Any]:
    """创建拆分或组装单。

    拆分: 将一个原料拆分成多个子项 (如整鸡 → 鸡腿+鸡翅+鸡胸)
    组装: 将多个原料组装成一个半成品 (如鸡腿+调料 → 卤鸡腿)

    Args:
        item_id: 主商品 ID
        op_type: split (拆分) / assembly (组装)
        components: 组件明细 [{ingredient_id, name, quantity, unit}]
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        拆组单
    """
    if op_type not in ("split", "assembly"):
        raise ValueError(f"op_type 必须为 split 或 assembly, 收到: {op_type}")
    if not components:
        raise ValueError("拆组单必须包含至少一项组件")

    sa_id = _gen_id("sa")
    now = _now_iso()

    record: Dict[str, Any] = {
        "sa_id": sa_id,
        "item_id": item_id,
        "op_type": op_type,
        "tenant_id": tenant_id,
        "status": "completed",
        "components": components,
        "component_count": len(components),
        "total_component_qty": round(
            sum(c.get("quantity", 0) for c in components), 4
        ),
        "created_at": now,
    }

    log.info(
        "split_assembly_created",
        sa_id=sa_id,
        item_id=item_id,
        op_type=op_type,
        tenant_id=tenant_id,
        component_count=len(components),
    )
    return record


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. BOM 拆分 (成品 → 原料)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def create_bom_split(
    dish_id: str,
    quantity: float,
    tenant_id: str,
    db: Any,
    *,
    bom: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """BOM 拆分: 按配方将成品拆分为原料需求。

    Args:
        dish_id: 菜品 ID
        quantity: 成品数量
        tenant_id: 租户 ID
        db: 数据库会话
        bom: BOM 配方 [{ingredient_id, name, qty_per_dish, unit, cost_fen}]

    Returns:
        拆分后的原料清单
    """
    if quantity <= 0:
        raise ValueError("拆分数量必须大于0")

    bom_data = bom or []
    if not bom_data:
        raise ValueError(f"菜品 {dish_id} 无 BOM 配方数据")

    split_id = _gen_id("bsplit")
    now = _now_iso()

    ingredients: List[Dict[str, Any]] = []
    total_cost_fen = 0
    for item in bom_data:
        qty = round(item.get("qty_per_dish", 0) * quantity, 4)
        cost = int(item.get("cost_fen", 0) * quantity)
        ingredients.append({
            "ingredient_id": item.get("ingredient_id"),
            "name": item.get("name", ""),
            "required_qty": qty,
            "unit": item.get("unit", ""),
            "estimated_cost_fen": cost,
        })
        total_cost_fen += cost

    record: Dict[str, Any] = {
        "split_id": split_id,
        "dish_id": dish_id,
        "quantity": quantity,
        "tenant_id": tenant_id,
        "status": "completed",
        "ingredients": ingredients,
        "ingredient_count": len(ingredients),
        "total_cost_fen": total_cost_fen,
        "created_at": now,
    }

    log.info(
        "bom_split_created",
        split_id=split_id,
        dish_id=dish_id,
        quantity=quantity,
        tenant_id=tenant_id,
        ingredient_count=len(ingredients),
        total_cost_fen=total_cost_fen,
    )
    return record
