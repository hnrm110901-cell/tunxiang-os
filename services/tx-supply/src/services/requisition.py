"""申购全流程服务

流程: 申购单 → 店长审批 → 区域审批 → 总部审批(按金额分级) → 转采购订单
状态机: draft → pending_approval → store_approved → region_approved → approved → converted → rejected
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog

log = structlog.get_logger(__name__)

# 审批金额分级阈值 (单位: 分)
APPROVAL_THRESHOLDS = {
    "store": 500_000,       # <= 5000 元: 店长即可审批
    "region": 2_000_000,    # <= 20000 元: 区域审批
    "hq": float("inf"),     # > 20000 元: 总部审批
}

REQUISITION_STATES = {
    "draft": "草稿",
    "pending_approval": "待审批",
    "store_approved": "店长已审批",
    "region_approved": "区域已审批",
    "approved": "已审批",
    "rejected": "已驳回",
    "converted": "已转采购",
    "cancelled": "已取消",
}

REQUISITION_TRANSITIONS = {
    "draft": ["pending_approval", "cancelled"],
    "pending_approval": ["store_approved", "rejected"],
    "store_approved": ["region_approved", "approved", "rejected"],
    "region_approved": ["approved", "rejected"],
    "approved": ["converted", "cancelled"],
    "rejected": ["draft"],
    "converted": [],
    "cancelled": [],
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _determine_approval_level(total_fen: int) -> str:
    """根据金额确定审批级别"""
    if total_fen <= APPROVAL_THRESHOLDS["store"]:
        return "store"
    elif total_fen <= APPROVAL_THRESHOLDS["region"]:
        return "region"
    return "hq"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. 创建申购单
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def create_requisition(
    store_id: str,
    items: List[Dict[str, Any]],
    requester_id: str,
    tenant_id: str,
    db: Any,
) -> Dict[str, Any]:
    """创建申购单。

    Args:
        store_id: 门店 ID
        items: 申购明细 [{ingredient_id, name, quantity, unit, estimated_price_fen}]
        requester_id: 申请人 ID
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        申购单字典
    """
    if not items:
        raise ValueError("申购单必须包含至少一项商品")

    req_id = _gen_id("req")
    now = _now_iso()
    total_fen = sum(
        i.get("estimated_price_fen", 0) * i.get("quantity", 1) for i in items
    )
    approval_level = _determine_approval_level(total_fen)

    record: Dict[str, Any] = {
        "requisition_id": req_id,
        "store_id": store_id,
        "requester_id": requester_id,
        "tenant_id": tenant_id,
        "status": "draft",
        "items": items,
        "item_count": len(items),
        "total_estimated_fen": int(total_fen),
        "approval_level": approval_level,
        "approval_log": [],
        "created_at": now,
        "updated_at": now,
    }

    log.info(
        "requisition_created",
        requisition_id=req_id,
        store_id=store_id,
        tenant_id=tenant_id,
        item_count=len(items),
        total_estimated_fen=int(total_fen),
        approval_level=approval_level,
    )
    return record


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. 自动补货单 (基于安全库存)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def create_replenishment(
    store_id: str,
    tenant_id: str,
    db: Any,
    *,
    inventory_data: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """基于安全库存自动生成补货申购单。

    Args:
        store_id: 门店 ID
        tenant_id: 租户 ID
        db: 数据库会话
        inventory_data: 库存数据 [{ingredient_id, name, current_qty, safety_qty,
                         daily_usage, unit, estimated_price_fen}]

    Returns:
        自动补货申购单
    """
    data = inventory_data or []
    replenish_items: List[Dict[str, Any]] = []

    for item in data:
        current = item.get("current_qty", 0)
        safety = item.get("safety_qty", 0)
        daily_usage = item.get("daily_usage", 0)

        if current < safety:
            # 补货量 = 7天用量 - 当前库存, 至少补到安全库存的2倍
            target = max(daily_usage * 7, safety * 2)
            qty = max(0, target - current)
            if qty > 0:
                replenish_items.append({
                    "ingredient_id": item.get("ingredient_id"),
                    "name": item.get("name", ""),
                    "quantity": round(qty, 2),
                    "unit": item.get("unit", ""),
                    "estimated_price_fen": item.get("estimated_price_fen", 0),
                })

    if not replenish_items:
        log.info(
            "replenishment_not_needed",
            store_id=store_id,
            tenant_id=tenant_id,
        )
        return {
            "requisition_id": None,
            "store_id": store_id,
            "tenant_id": tenant_id,
            "status": "not_needed",
            "items": [],
            "message": "所有商品库存充足, 无需补货",
        }

    record = await create_requisition(
        store_id, replenish_items, "system_auto", tenant_id, db
    )
    record["source"] = "auto_replenishment"

    log.info(
        "replenishment_created",
        requisition_id=record["requisition_id"],
        store_id=store_id,
        tenant_id=tenant_id,
        replenish_count=len(replenish_items),
    )
    return record


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. 提交审批
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def submit_for_approval(
    req_id: str,
    tenant_id: str,
    db: Any,
    *,
    requisition: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """提交申购单进入审批流程。

    Args:
        req_id: 申购单 ID
        tenant_id: 租户 ID
        db: 数据库会话
        requisition: 已加载的申购单 (测试注入用)

    Returns:
        更新后的申购单
    """
    if requisition is not None:
        if requisition.get("status") != "draft":
            raise ValueError(
                f"只有草稿状态可提交审批, 当前状态: {requisition.get('status')}"
            )
        requisition["status"] = "pending_approval"
        requisition["submitted_at"] = _now_iso()
        requisition["updated_at"] = _now_iso()

    log.info(
        "requisition_submitted",
        requisition_id=req_id,
        tenant_id=tenant_id,
    )
    return {
        "requisition_id": req_id,
        "status": (requisition or {}).get("status", "pending_approval"),
        "submitted_at": _now_iso(),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. 审批 (通过/驳回) — 按金额分级
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def approve_requisition(
    req_id: str,
    approver_id: str,
    decision: str,
    tenant_id: str,
    db: Any,
    *,
    requisition: Optional[Dict[str, Any]] = None,
    approver_role: str = "store_manager",
    comment: str = "",
) -> Dict[str, Any]:
    """审批申购单 (通过/驳回)。

    审批流: 申购→店长→区域→总部 (按金额分级)
    - <= 5000元: 店长即可最终审批
    - <= 20000元: 需区域审批
    - > 20000元: 需总部审批

    Args:
        req_id: 申购单 ID
        approver_id: 审批人 ID
        decision: approve / reject
        tenant_id: 租户 ID
        db: 数据库会话
        requisition: 已加载的申购单 (测试注入用)
        approver_role: store_manager / region_manager / hq_manager
        comment: 审批意见

    Returns:
        审批结果
    """
    if decision not in ("approve", "reject"):
        raise ValueError(f"decision 必须为 approve 或 reject, 收到: {decision}")

    valid_roles = ("store_manager", "region_manager", "hq_manager")
    if approver_role not in valid_roles:
        raise ValueError(f"approver_role 必须为 {valid_roles} 之一")

    now = _now_iso()
    log_entry = {
        "approver_id": approver_id,
        "approver_role": approver_role,
        "decision": decision,
        "comment": comment,
        "timestamp": now,
    }

    new_status = "rejected"
    if decision == "approve" and requisition is not None:
        approval_level = requisition.get("approval_level", "store")
        current_status = requisition.get("status", "")

        # 根据审批角色和金额级别决定下一状态
        if approver_role == "store_manager":
            new_status = (
                "approved" if approval_level == "store" else "store_approved"
            )
        elif approver_role == "region_manager":
            if current_status not in ("pending_approval", "store_approved"):
                raise ValueError(
                    f"区域审批要求状态为 pending_approval 或 store_approved, "
                    f"当前: {current_status}"
                )
            new_status = (
                "approved" if approval_level in ("store", "region")
                else "region_approved"
            )
        elif approver_role == "hq_manager":
            new_status = "approved"

        requisition["status"] = new_status
        requisition["updated_at"] = now
        requisition.setdefault("approval_log", []).append(log_entry)
    elif decision == "reject" and requisition is not None:
        requisition["status"] = "rejected"
        requisition["rejection_reason"] = comment
        requisition["updated_at"] = now
        requisition.setdefault("approval_log", []).append(log_entry)

    log.info(
        "requisition_approval",
        requisition_id=req_id,
        approver_id=approver_id,
        approver_role=approver_role,
        decision=decision,
        new_status=new_status,
        tenant_id=tenant_id,
    )

    return {
        "requisition_id": req_id,
        "decision": decision,
        "new_status": new_status,
        "approver_id": approver_id,
        "approver_role": approver_role,
        "comment": comment,
        "timestamp": now,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. 申购→采购订单转换
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def convert_to_purchase(
    req_id: str,
    tenant_id: str,
    db: Any,
    *,
    requisition: Optional[Dict[str, Any]] = None,
    supplier_id: str = "",
    supplier_name: str = "",
    delivery_date: str = "",
) -> Dict[str, Any]:
    """将已审批的申购单转换为采购订单。

    Args:
        req_id: 申购单 ID
        tenant_id: 租户 ID
        db: 数据库会话
        requisition: 已加载的申购单 (测试注入用)
        supplier_id: 供应商 ID
        supplier_name: 供应商名称
        delivery_date: 预计送达日期

    Returns:
        采购订单
    """
    if requisition is not None:
        if requisition.get("status") != "approved":
            raise ValueError(
                f"只有已审批状态可转采购, 当前状态: {requisition.get('status')}"
            )
        requisition["status"] = "converted"
        requisition["updated_at"] = _now_iso()

    now = _now_iso()
    po_id = _gen_id("po")
    items = (requisition or {}).get("items", [])

    po: Dict[str, Any] = {
        "po_id": po_id,
        "requisition_id": req_id,
        "store_id": (requisition or {}).get("store_id", ""),
        "supplier_id": supplier_id,
        "supplier_name": supplier_name,
        "tenant_id": tenant_id,
        "status": "ordered",
        "items": items,
        "total_fen": (requisition or {}).get("total_estimated_fen", 0),
        "expected_delivery": delivery_date,
        "created_at": now,
    }

    log.info(
        "requisition_converted_to_po",
        requisition_id=req_id,
        po_id=po_id,
        tenant_id=tenant_id,
        supplier_id=supplier_id,
    )
    return po


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  6. 申退单
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def create_return_request(
    store_id: str,
    items: List[Dict[str, Any]],
    reason: str,
    tenant_id: str,
    db: Any,
) -> Dict[str, Any]:
    """创建申退单。

    Args:
        store_id: 门店 ID
        items: 退货明细 [{ingredient_id, name, quantity, unit, batch_no}]
        reason: 退货原因
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        申退单
    """
    if not items:
        raise ValueError("申退单必须包含至少一项商品")
    if not reason.strip():
        raise ValueError("退货原因不能为空")

    return_id = _gen_id("ret")
    now = _now_iso()

    record: Dict[str, Any] = {
        "return_id": return_id,
        "store_id": store_id,
        "tenant_id": tenant_id,
        "status": "pending",
        "reason": reason,
        "items": items,
        "item_count": len(items),
        "total_return_qty": sum(i.get("quantity", 0) for i in items),
        "created_at": now,
    }

    log.info(
        "return_request_created",
        return_id=return_id,
        store_id=store_id,
        tenant_id=tenant_id,
        item_count=len(items),
        reason=reason,
    )
    return record


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  7. 审批日志
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def get_approval_log(
    req_id: str,
    tenant_id: str,
    db: Any,
    *,
    requisition: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """获取申购单审批日志。

    Args:
        req_id: 申购单 ID
        tenant_id: 租户 ID
        db: 数据库会话
        requisition: 已加载的申购单 (测试注入用)

    Returns:
        审批日志
    """
    approval_log = (requisition or {}).get("approval_log", [])

    log.info(
        "approval_log_queried",
        requisition_id=req_id,
        tenant_id=tenant_id,
        log_count=len(approval_log),
    )
    return {
        "requisition_id": req_id,
        "tenant_id": tenant_id,
        "approval_log": approval_log,
        "log_count": len(approval_log),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  8. 申购商品流水
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def get_requisition_flow(
    store_id: str,
    tenant_id: str,
    db: Any,
    *,
    requisitions: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """查询门店申购商品流水。

    Args:
        store_id: 门店 ID
        tenant_id: 租户 ID
        db: 数据库会话
        requisitions: 申购单列表 (测试注入用)

    Returns:
        申购流水汇总
    """
    data = requisitions or []
    total_count = len(data)
    total_fen = sum(r.get("total_estimated_fen", 0) for r in data)

    status_summary: Dict[str, int] = {}
    for r in data:
        s = r.get("status", "unknown")
        status_summary[s] = status_summary.get(s, 0) + 1

    log.info(
        "requisition_flow_queried",
        store_id=store_id,
        tenant_id=tenant_id,
        total_count=total_count,
    )
    return {
        "store_id": store_id,
        "tenant_id": tenant_id,
        "requisitions": data,
        "total_count": total_count,
        "total_estimated_fen": total_fen,
        "status_summary": status_summary,
    }
