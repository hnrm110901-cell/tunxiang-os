"""C5 收货验收 + 退货 + 门店调拨

收货验收流程: 采购单到货 → 逐项验收 → 入库/退货
调拨流程: 发起调拨 → 双方确认 (发方确认发出 + 收方确认收到)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog

log = structlog.get_logger(__name__)

# 调拨状态
TRANSFER_STATUSES = (
    "pending", "sender_confirmed", "receiver_confirmed", "completed", "cancelled",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. 收货验收
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def create_receiving(
    purchase_order_id: str,
    items: List[Dict[str, Any]],
    receiver_id: str,
    tenant_id: str,
    db: Any,
) -> Dict[str, Any]:
    """创建收货验收单。

    Args:
        purchase_order_id: 采购订单 ID
        items: 收货明细 [{ingredient_id, name, ordered_qty, received_qty, quality, notes}]
               quality: pass / fail / partial
        receiver_id: 收货人 ID
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        收货单字典，含验收统计
    """
    receiving_id = f"rcv_{uuid.uuid4().hex[:8]}"
    now = _now_iso()

    total_ordered = sum(i.get("ordered_qty", 0) for i in items)
    total_received = sum(i.get("received_qty", 0) for i in items)
    quality_issues = [i for i in items if i.get("quality") != "pass"]
    all_pass = len(quality_issues) == 0

    record: Dict[str, Any] = {
        "receiving_id": receiving_id,
        "purchase_order_id": purchase_order_id,
        "receiver_id": receiver_id,
        "tenant_id": tenant_id,
        "items": items,
        "total_ordered": total_ordered,
        "total_received": total_received,
        "shortage": max(0, total_ordered - total_received),
        "quality_issues": quality_issues,
        "quality_issue_count": len(quality_issues),
        "all_pass": all_pass,
        "status": "accepted" if all_pass else "partial",
        "created_at": now,
    }

    log.info(
        "receiving_created",
        receiving_id=receiving_id,
        purchase_order_id=purchase_order_id,
        tenant_id=tenant_id,
        total_received=total_received,
        quality_issue_count=len(quality_issues),
    )
    return record


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. 退货
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def reject_item(
    receiving_id: str,
    item_id: str,
    reason: str,
    quantity: float,
    tenant_id: str,
    db: Any,
) -> Dict[str, Any]:
    """对收货单中的某项发起退货。

    Args:
        receiving_id: 收货单 ID
        item_id: 退货原料 ID (ingredient_id)
        reason: 退货原因
        quantity: 退货数量
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        退货记录
    """
    if quantity <= 0:
        raise ValueError("Reject quantity must be positive")

    rejection_id = f"rej_{uuid.uuid4().hex[:8]}"
    now = _now_iso()

    record: Dict[str, Any] = {
        "rejection_id": rejection_id,
        "receiving_id": receiving_id,
        "item_id": item_id,
        "reason": reason,
        "quantity": quantity,
        "tenant_id": tenant_id,
        "status": "pending_return",
        "created_at": now,
    }

    log.info(
        "item_rejected",
        rejection_id=rejection_id,
        receiving_id=receiving_id,
        item_id=item_id,
        tenant_id=tenant_id,
        quantity=quantity,
        reason=reason,
    )
    return record


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. 门店调拨
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def create_transfer(
    from_store_id: str,
    to_store_id: str,
    items: List[Dict[str, Any]],
    tenant_id: str,
    db: Any,
) -> Dict[str, Any]:
    """发起门店间调拨（双方确认制）。

    Args:
        from_store_id: 调出门店 ID
        to_store_id: 调入门店 ID
        items: 调拨明细 [{ingredient_id, name, quantity, unit}]
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        调拨单，初始状态 pending
    """
    if from_store_id == to_store_id:
        raise ValueError("Cannot transfer to the same store")

    if not items:
        raise ValueError("Transfer must include at least one item")

    transfer_id = f"tf_{uuid.uuid4().hex[:8]}"
    now = _now_iso()

    record: Dict[str, Any] = {
        "transfer_id": transfer_id,
        "from_store_id": from_store_id,
        "to_store_id": to_store_id,
        "items": items,
        "item_count": len(items),
        "tenant_id": tenant_id,
        "status": "pending",
        "sender_confirmed": False,
        "receiver_confirmed": False,
        "created_at": now,
        "updated_at": now,
    }

    log.info(
        "transfer_created",
        transfer_id=transfer_id,
        from_store_id=from_store_id,
        to_store_id=to_store_id,
        tenant_id=tenant_id,
        item_count=len(items),
    )
    return record


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. 调拨确认（双方确认制）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def confirm_transfer(
    transfer_id: str,
    receiver_id: str,
    tenant_id: str,
    db: Any,
    *,
    transfer: Optional[Dict[str, Any]] = None,
    role: str = "sender",
) -> Dict[str, Any]:
    """确认调拨（发方或收方）。

    双方确认制：sender_confirmed + receiver_confirmed 都为 True 时，
    状态变为 completed。

    Args:
        transfer_id: 调拨单 ID
        receiver_id: 确认人 ID
        tenant_id: 租户 ID
        db: 数据库会话
        transfer: 已加载调拨记录（测试注入用）
        role: 确认角色 sender / receiver

    Returns:
        更新后的调拨状态
    """
    if role not in ("sender", "receiver"):
        raise ValueError(f"Role must be 'sender' or 'receiver', got '{role}'")

    now = _now_iso()

    if transfer is not None:
        current_status = transfer.get("status", "pending")
        if current_status in ("completed", "cancelled"):
            raise ValueError(f"Transfer is already '{current_status}'")

        if role == "sender":
            transfer["sender_confirmed"] = True
            transfer["sender_confirmed_by"] = receiver_id
            transfer["sender_confirmed_at"] = now
            if not transfer.get("receiver_confirmed"):
                transfer["status"] = "sender_confirmed"
        else:
            transfer["receiver_confirmed"] = True
            transfer["receiver_confirmed_by"] = receiver_id
            transfer["receiver_confirmed_at"] = now
            if not transfer.get("sender_confirmed"):
                transfer["status"] = "receiver_confirmed"

        # 双方都确认 → completed
        if transfer.get("sender_confirmed") and transfer.get("receiver_confirmed"):
            transfer["status"] = "completed"
            transfer["completed_at"] = now

        transfer["updated_at"] = now

    status = (transfer or {}).get("status", "unknown")

    log.info(
        "transfer_confirmed",
        transfer_id=transfer_id,
        tenant_id=tenant_id,
        role=role,
        confirmed_by=receiver_id,
        status=status,
    )

    return {
        "transfer_id": transfer_id,
        "role": role,
        "confirmed_by": receiver_id,
        "status": status,
        "updated_at": now,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. 中央仓库存
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def get_central_warehouse_stock(
    tenant_id: str,
    db: Any,
    *,
    stock_data: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """查询中央仓库存。

    Args:
        tenant_id: 租户 ID
        db: 数据库会话
        stock_data: 库存数据（测试注入用）

    Returns:
        中央仓库存汇总
    """
    items = stock_data or []

    total_items = len(items)
    low_stock = [i for i in items if i.get("quantity", 0) <= i.get("min_quantity", 0)]
    total_value_fen = sum(
        i.get("quantity", 0) * i.get("unit_price_fen", 0) for i in items
    )

    log.info(
        "central_warehouse_queried",
        tenant_id=tenant_id,
        total_items=total_items,
        low_stock_count=len(low_stock),
    )

    return {
        "tenant_id": tenant_id,
        "items": items,
        "summary": {
            "total_items": total_items,
            "low_stock_count": len(low_stock),
            "low_stock_items": low_stock,
            "total_value_fen": total_value_fen,
        },
    }
