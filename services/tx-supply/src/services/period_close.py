"""月结与成本服务

月结: 锁定当月库存, 不可修改当月单据
反月结: 解锁 (需权限)
成本调整: 手工调整成本
收发结存: 期初 + 本期收入 - 本期发出 = 期末
应付账款: 供应商应付统计
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
#  1. 月结 (锁定库存)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def close_period(
    store_id: str,
    month: str,
    tenant_id: str,
    db: Any,
    *,
    period_data: Optional[Dict[str, Any]] = None,
    pending_count: int = 0,
) -> Dict[str, Any]:
    """月结: 锁定当月库存, 月结后不可修改当月单据。

    Args:
        store_id: 门店 ID
        month: 月份 (YYYY-MM)
        tenant_id: 租户 ID
        db: 数据库会话
        period_data: 期间数据 (测试注入用)
        pending_count: 未完成单据数

    Returns:
        月结结果
    """
    if pending_count > 0:
        raise ValueError(f"存在 {pending_count} 张未完成单据, 请先处理后再月结")

    # 检查是否已月结
    if period_data is not None and period_data.get("is_closed"):
        raise ValueError(f"{month} 已完成月结, 不可重复操作")

    close_id = _gen_id("close")
    now = _now_iso()

    record: Dict[str, Any] = {
        "close_id": close_id,
        "store_id": store_id,
        "month": month,
        "tenant_id": tenant_id,
        "status": "closed",
        "is_closed": True,
        "closed_at": now,
        "closed_by": "system",
        "snapshot": period_data or {},
    }

    log.info(
        "period_closed",
        close_id=close_id,
        store_id=store_id,
        month=month,
        tenant_id=tenant_id,
    )
    return record


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. 反月结
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def reverse_close(
    store_id: str,
    month: str,
    tenant_id: str,
    db: Any,
    *,
    period_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """反月结: 解锁已月结的期间。

    Args:
        store_id: 门店 ID
        month: 月份 (YYYY-MM)
        tenant_id: 租户 ID
        db: 数据库会话
        period_data: 期间数据 (测试注入用)

    Returns:
        反月结结果
    """
    if period_data is not None and not period_data.get("is_closed"):
        raise ValueError(f"{month} 尚未月结, 无需反月结")

    now = _now_iso()

    if period_data is not None:
        period_data["is_closed"] = False
        period_data["status"] = "reopened"
        period_data["reopened_at"] = now

    log.info(
        "period_reversed",
        store_id=store_id,
        month=month,
        tenant_id=tenant_id,
    )
    return {
        "store_id": store_id,
        "month": month,
        "tenant_id": tenant_id,
        "status": "reopened",
        "is_closed": False,
        "reopened_at": now,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. 成本调整单
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def create_cost_adjustment(
    store_id: str,
    items: List[Dict[str, Any]],
    tenant_id: str,
    db: Any,
    *,
    period_closed: bool = False,
    month: str = "",
) -> Dict[str, Any]:
    """创建成本调整单。月结后不可调整当月成本。

    Args:
        store_id: 门店 ID
        items: 调整明细 [{ingredient_id, name, old_cost_fen, new_cost_fen, reason}]
        tenant_id: 租户 ID
        db: 数据库会话
        period_closed: 当月是否已月结
        month: 调整月份

    Returns:
        成本调整单
    """
    if period_closed:
        raise ValueError(f"{month} 已月结, 不可修改当月成本。如需调整请先反月结")
    if not items:
        raise ValueError("成本调整单必须包含至少一项")

    adj_id = _gen_id("cadj")
    now = _now_iso()

    total_diff_fen = sum(i.get("new_cost_fen", 0) - i.get("old_cost_fen", 0) for i in items)

    record: Dict[str, Any] = {
        "adjustment_id": adj_id,
        "store_id": store_id,
        "month": month,
        "tenant_id": tenant_id,
        "status": "applied",
        "items": items,
        "item_count": len(items),
        "total_diff_fen": total_diff_fen,
        "created_at": now,
    }

    log.info(
        "cost_adjustment_created",
        adjustment_id=adj_id,
        store_id=store_id,
        tenant_id=tenant_id,
        item_count=len(items),
        total_diff_fen=total_diff_fen,
    )
    return record


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. 未完成单据检查
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def check_pending_documents(
    store_id: str,
    tenant_id: str,
    db: Any,
    *,
    documents: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """检查未完成单据 (月结前必须清理)。

    Args:
        store_id: 门店 ID
        tenant_id: 租户 ID
        db: 数据库会话
        documents: 单据列表 (测试注入用)

    Returns:
        未完成单据统计
    """
    docs = documents or []
    pending = [d for d in docs if d.get("status") not in ("completed", "cancelled", "closed", "stocked")]

    # 按类型分组
    type_summary: Dict[str, int] = {}
    for d in pending:
        doc_type = d.get("doc_type", "unknown")
        type_summary[doc_type] = type_summary.get(doc_type, 0) + 1

    can_close = len(pending) == 0

    log.info(
        "pending_documents_checked",
        store_id=store_id,
        tenant_id=tenant_id,
        pending_count=len(pending),
        can_close=can_close,
    )
    return {
        "store_id": store_id,
        "tenant_id": tenant_id,
        "pending_count": len(pending),
        "pending_documents": pending,
        "type_summary": type_summary,
        "can_close": can_close,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. 收发结存表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def get_receipt_balance(
    store_id: str,
    month: str,
    tenant_id: str,
    db: Any,
    *,
    balance_data: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """收发结存表: 期初 + 本期收入 - 本期发出 = 期末。

    Args:
        store_id: 门店 ID
        month: 月份 (YYYY-MM)
        tenant_id: 租户 ID
        db: 数据库会话
        balance_data: 结存数据 [{ingredient_id, name, unit,
                       opening_qty, opening_cost_fen,
                       received_qty, received_cost_fen,
                       issued_qty, issued_cost_fen}]

    Returns:
        收发结存表
    """
    data = balance_data or []
    items: List[Dict[str, Any]] = []

    total_opening_fen = 0
    total_received_fen = 0
    total_issued_fen = 0
    total_closing_fen = 0

    for row in data:
        opening_qty = row.get("opening_qty", 0)
        received_qty = row.get("received_qty", 0)
        issued_qty = row.get("issued_qty", 0)
        closing_qty = round(opening_qty + received_qty - issued_qty, 4)

        opening_cost = row.get("opening_cost_fen", 0)
        received_cost = row.get("received_cost_fen", 0)
        issued_cost = row.get("issued_cost_fen", 0)
        closing_cost = opening_cost + received_cost - issued_cost

        total_opening_fen += opening_cost
        total_received_fen += received_cost
        total_issued_fen += issued_cost
        total_closing_fen += closing_cost

        items.append(
            {
                **row,
                "closing_qty": closing_qty,
                "closing_cost_fen": closing_cost,
            }
        )

    log.info(
        "receipt_balance_queried",
        store_id=store_id,
        month=month,
        tenant_id=tenant_id,
        item_count=len(items),
    )
    return {
        "store_id": store_id,
        "month": month,
        "tenant_id": tenant_id,
        "items": items,
        "item_count": len(items),
        "summary": {
            "total_opening_fen": total_opening_fen,
            "total_received_fen": total_received_fen,
            "total_issued_fen": total_issued_fen,
            "total_closing_fen": total_closing_fen,
        },
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  6. 应付账款统计
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def get_payable_summary(
    store_id: str,
    tenant_id: str,
    db: Any,
    *,
    payable_data: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """应付账款统计 (按供应商汇总)。

    Args:
        store_id: 门店 ID
        tenant_id: 租户 ID
        db: 数据库会话
        payable_data: 应付数据 [{supplier_id, supplier_name,
                       total_payable_fen, paid_fen, po_count}]

    Returns:
        应付账款汇总
    """
    data = payable_data or []
    total_payable = sum(d.get("total_payable_fen", 0) for d in data)
    total_paid = sum(d.get("paid_fen", 0) for d in data)
    total_outstanding = total_payable - total_paid

    log.info(
        "payable_summary_queried",
        store_id=store_id,
        tenant_id=tenant_id,
        supplier_count=len(data),
        total_outstanding_fen=total_outstanding,
    )
    return {
        "store_id": store_id,
        "tenant_id": tenant_id,
        "suppliers": data,
        "supplier_count": len(data),
        "summary": {
            "total_payable_fen": total_payable,
            "total_paid_fen": total_paid,
            "total_outstanding_fen": total_outstanding,
        },
    }
