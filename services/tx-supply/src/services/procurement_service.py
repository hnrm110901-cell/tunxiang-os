"""采购全流程服务 (C4)

流程：请购 → 审批 → 下单 → 收货 → 验收 → 入库
状态机：draft → pending_approval → approved → ordered → received → inspected → stocked / rejected
"""

import uuid
from datetime import datetime, timezone

# 采购单状态
PROCUREMENT_STATES = {
    "draft": "草稿",
    "pending_approval": "待审批",
    "approved": "已审批",
    "rejected": "已驳回",
    "ordered": "已下单",
    "received": "已收货",
    "inspected": "已验收",
    "stocked": "已入库",
    "cancelled": "已取消",
}

PROCUREMENT_TRANSITIONS = {
    "draft": ["pending_approval", "cancelled"],
    "pending_approval": ["approved", "rejected"],
    "approved": ["ordered", "cancelled"],
    "rejected": ["draft"],  # 驳回可重新编辑
    "ordered": ["received"],
    "received": ["inspected"],
    "inspected": ["stocked", "rejected"],  # 验收不合格可退回
    "stocked": [],
    "cancelled": [],
}


def can_procurement_transition(current: str, target: str) -> bool:
    return target in PROCUREMENT_TRANSITIONS.get(current, [])


# ─── 请购单 ───


def create_requisition(
    store_id: str,
    requester_id: str,
    items: list[dict],
    urgency: str = "normal",
    reason: str = "",
) -> dict:
    """创建请购单
    items: [{"ingredient_id","name","quantity","unit","estimated_price_fen"}]
    """
    req_no = f"REQ{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:4].upper()}"
    total_fen = sum(i.get("estimated_price_fen", 0) * i.get("quantity", 1) for i in items)

    return {
        "requisition_no": req_no,
        "store_id": store_id,
        "requester_id": requester_id,
        "status": "draft",
        "urgency": urgency,
        "reason": reason,
        "items": items,
        "item_count": len(items),
        "total_estimated_fen": total_fen,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


# ─── 审批 ───


def approve_requisition(requisition: dict, approver_id: str, comment: str = "") -> dict:
    """审批请购单"""
    if requisition.get("status") != "pending_approval":
        raise ValueError(f"Cannot approve from status: {requisition.get('status')}")
    return {
        **requisition,
        "status": "approved",
        "approved_by": approver_id,
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "approval_comment": comment,
    }


def reject_requisition(requisition: dict, approver_id: str, reason: str) -> dict:
    """驳回请购单"""
    return {
        **requisition,
        "status": "rejected",
        "rejected_by": approver_id,
        "rejected_at": datetime.now(timezone.utc).isoformat(),
        "rejection_reason": reason,
    }


# ─── 采购下单 ───


def create_purchase_order(
    requisition: dict,
    supplier_id: str,
    supplier_name: str,
    delivery_date: str,
) -> dict:
    """从请购单生成采购订单"""
    po_no = f"PO{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:4].upper()}"

    return {
        "po_no": po_no,
        "requisition_no": requisition.get("requisition_no"),
        "store_id": requisition.get("store_id"),
        "supplier_id": supplier_id,
        "supplier_name": supplier_name,
        "status": "ordered",
        "items": requisition.get("items", []),
        "total_fen": requisition.get("total_estimated_fen", 0),
        "expected_delivery": delivery_date,
        "ordered_at": datetime.now(timezone.utc).isoformat(),
    }


# ─── 收货验收 ───


def receive_delivery(po: dict, received_items: list[dict]) -> dict:
    """收货登记
    received_items: [{"ingredient_id","received_qty","quality":"pass/fail","notes":""}]
    """
    total_received = sum(i.get("received_qty", 0) for i in received_items)
    total_ordered = sum(i.get("quantity", 0) for i in po.get("items", []))
    quality_issues = [i for i in received_items if i.get("quality") != "pass"]

    return {
        **po,
        "status": "received",
        "received_items": received_items,
        "total_ordered": total_ordered,
        "total_received": total_received,
        "shortage": max(0, total_ordered - total_received),
        "quality_issues": quality_issues,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }


def inspect_and_stock(delivery: dict, inspector_id: str) -> dict:
    """验收入库"""
    quality_issues = delivery.get("quality_issues", [])
    all_pass = len(quality_issues) == 0

    return {
        **delivery,
        "status": "stocked" if all_pass else "inspected",
        "inspection_result": "pass" if all_pass else "partial",
        "quality_issue_count": len(quality_issues),
        "inspector_id": inspector_id,
        "inspected_at": datetime.now(timezone.utc).isoformat(),
    }


# ─── 智能补货建议 ───


def suggest_procurement(inventory_alerts: list[dict], supplier_prices: dict) -> list[dict]:
    """基于库存预警自动生成采购建议
    Args:
        inventory_alerts: 库存预警列表 [{"item_name","current_qty","min_qty","daily_usage"}]
        supplier_prices: {ingredient_id: {"supplier","price_fen"}}
    """
    suggestions = []
    for alert in inventory_alerts:
        item_name = alert.get("item_name", "")
        current = alert.get("current_qty", 0)
        min_qty = alert.get("min_qty", 0)
        daily_usage = alert.get("daily_usage", 1)

        # 补货量 = 7天用量 - 当前库存（至少补到安全库存的3倍）
        restock_qty = max(daily_usage * 7 - current, min_qty * 3 - current)
        if restock_qty <= 0:
            continue

        price_info = supplier_prices.get(alert.get("ingredient_id"), {})
        est_cost = int(restock_qty * price_info.get("price_fen", 0))

        suggestions.append(
            {
                "item_name": item_name,
                "ingredient_id": alert.get("ingredient_id"),
                "current_qty": current,
                "restock_qty": round(restock_qty, 1),
                "supplier": price_info.get("supplier", "待选"),
                "estimated_cost_fen": est_cost,
                "urgency": "critical" if current <= 0 else "urgent" if current < min_qty else "normal",
            }
        )

    suggestions.sort(key=lambda s: {"critical": 0, "urgent": 1, "normal": 2}[s["urgency"]])
    return suggestions
