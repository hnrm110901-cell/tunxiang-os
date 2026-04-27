"""品智POS数据 → 标准Order字段映射

品智金额单位：分(int)
DB金额单位：分(int)  — 无需转换

品智 billStatus 映射：
  0 → pending（未结账）
  1 → completed（已结账）
  2 → cancelled（已退单）
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import structlog

logger = structlog.get_logger(__name__)

# 品智 billStatus → 标准 OrderStatus
_STATUS_MAP: dict[int, str] = {
    0: "pending",
    1: "completed",
    2: "cancelled",
}

# 品智 orderSource → 标准 order_type
_ORDER_TYPE_MAP: dict[int, str] = {
    1: "dine_in",
    2: "delivery",
    3: "takeaway",
}


def _safe_int(val: Any, default: int = 0) -> int:
    """安全转整数，品智金额字段可能是 int/str/None"""
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _parse_datetime(raw: Any) -> datetime | None:
    """解析品智时间字段（ISO 格式或空间分隔）"""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("T", " "))
    except (ValueError, TypeError):
        return None


def pinzhi_order_to_db(
    raw_order: dict[str, Any],
    tenant_id: UUID,
    store_id: UUID,
) -> dict[str, Any]:
    """将品智原始订单转换为 orders 表字段字典

    Args:
        raw_order: 品智 orderNew.do 返回的单条订单原始数据
        tenant_id: 租户ID（RLS隔离必须）
        store_id: 门店ID

    Returns:
        可直接用于 INSERT 的字段字典
    """
    bill_id = str(raw_order.get("billId", ""))
    if not bill_id:
        logger.warning("pinzhi_mapper.missing_bill_id", raw_keys=list(raw_order.keys()))
        bill_id = str(uuid4())

    # 金额：品智返回分(int)，DB存分(int)
    dish_total_fen = _safe_int(raw_order.get("dishPriceTotal"))
    special_offer_fen = _safe_int(raw_order.get("specialOfferPrice"))
    real_price_fen = _safe_int(raw_order.get("realPrice"))
    tea_price_fen = _safe_int(raw_order.get("teaPrice"))

    # 如果 realPrice 为0但 dishPriceTotal 有值，用 dishTotal - specialOffer 计算
    if real_price_fen == 0 and dish_total_fen > 0:
        real_price_fen = dish_total_fen - special_offer_fen

    # 状态
    bill_status = _safe_int(raw_order.get("billStatus"))
    status = _STATUS_MAP.get(bill_status, "pending")

    # 时间
    order_time = _parse_datetime(raw_order.get("openTime"))
    completed_at = _parse_datetime(raw_order.get("payTime"))
    if order_time is None:
        order_time = datetime.utcnow()

    # 类型
    order_source = _safe_int(raw_order.get("orderSource"), 1)
    order_type = _ORDER_TYPE_MAP.get(order_source, "dine_in")

    # 散客信息
    customer_phone = raw_order.get("vipMobile") or raw_order.get("mobile") or ""
    customer_name = raw_order.get("vipName") or ""

    return {
        "id": bill_id,
        "tenant_id": str(tenant_id),
        "store_id": str(store_id),
        "order_no": str(raw_order.get("billNo", bill_id)),
        "order_type": order_type,
        "sales_channel_id": "pinzhi",
        "table_number": raw_order.get("tableNo"),
        "waiter_id": raw_order.get("openOrderUser"),
        "customer_phone": customer_phone,
        "customer_name": customer_name,
        "total_amount_fen": dish_total_fen + tea_price_fen,
        "discount_amount_fen": special_offer_fen,
        "final_amount_fen": real_price_fen,
        "status": status,
        "order_time": order_time,
        "completed_at": completed_at,
        "notes": raw_order.get("remark"),
        "order_metadata": {
            "pinzhi_bill_id": bill_id,
            "pinzhi_bill_status": bill_status,
            "cashier": raw_order.get("cashiers"),
            "vip_card": raw_order.get("vipCard"),
            "tea_price_fen": tea_price_fen,
        },
    }


def pinzhi_order_items_to_db(
    raw_order: dict[str, Any],
    order_id: str,
    tenant_id: UUID,
) -> list[dict[str, Any]]:
    """将品智订单中的 dishList 转换为 order_items 表字段列表

    Args:
        raw_order: 品智原始订单（含 dishList）
        order_id: 对应的订单ID
        tenant_id: 租户ID

    Returns:
        order_items 字段字典列表
    """
    items = []
    for idx, dish in enumerate(raw_order.get("dishList", []), start=1):
        unit_price_fen = _safe_int(dish.get("dishPrice", dish.get("price", 0)))
        qty = _safe_int(dish.get("dishNum", dish.get("quantity", 1)), 1)
        dish_id_raw = dish.get("dishId", f"{raw_order.get('billId', '')}_{idx}")

        items.append(
            {
                "id": str(uuid4()),
                "tenant_id": str(tenant_id),
                "order_id": order_id,
                "item_name": str(dish.get("dishName", "")),
                "quantity": qty,
                "unit_price_fen": unit_price_fen,
                "subtotal_fen": unit_price_fen * qty,
                "notes": dish.get("remark"),
                "customizations": {
                    "pinzhi_dish_id": str(dish_id_raw),
                    "category": dish.get("categoryName", ""),
                },
            }
        )
    return items
