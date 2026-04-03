"""部门领用服务

领用流程: 创建领用单 → 出库 → 退回(可选)
部门间调拨: 发起 → 确认
出料率抽检: 实际产出量 / 理论产出量
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import structlog

log = structlog.get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. 创建领用单
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def create_issue_order(
    store_id: str,
    dept_id: str,
    items: List[Dict[str, Any]],
    operator_id: str,
    tenant_id: str,
    db: Any,
) -> Dict[str, Any]:
    """创建部门领用单。

    Args:
        store_id: 门店 ID
        dept_id: 领用部门 ID
        items: 领用明细 [{ingredient_id, name, quantity, unit, unit_cost_fen}]
        operator_id: 操作人 ID
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        领用单
    """
    if not items:
        raise ValueError("领用单必须包含至少一项商品")

    issue_id = _gen_id("iss")
    now = _now_iso()
    total_qty = sum(i.get("quantity", 0) for i in items)
    total_cost_fen = sum(
        i.get("quantity", 0) * i.get("unit_cost_fen", 0) for i in items
    )

    record: Dict[str, Any] = {
        "issue_id": issue_id,
        "store_id": store_id,
        "dept_id": dept_id,
        "operator_id": operator_id,
        "tenant_id": tenant_id,
        "status": "issued",
        "items": items,
        "item_count": len(items),
        "total_qty": round(total_qty, 2),
        "total_cost_fen": int(total_cost_fen),
        "created_at": now,
    }

    log.info(
        "issue_order_created",
        issue_id=issue_id,
        store_id=store_id,
        dept_id=dept_id,
        tenant_id=tenant_id,
        item_count=len(items),
        total_cost_fen=int(total_cost_fen),
    )
    return record


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. 领用退回
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def create_return_order(
    issue_id: str,
    items: List[Dict[str, Any]],
    tenant_id: str,
    db: Any,
    *,
    issue_order: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """创建领用退回单。

    Args:
        issue_id: 原领用单 ID
        items: 退回明细 [{ingredient_id, name, quantity, unit, reason}]
        tenant_id: 租户 ID
        db: 数据库会话
        issue_order: 原领用单 (测试注入用)

    Returns:
        退回单
    """
    if not items:
        raise ValueError("退回单必须包含至少一项商品")

    # 校验退回数量不超过领用数量
    if issue_order is not None:
        issued_map: Dict[str, float] = {}
        for it in issue_order.get("items", []):
            iid = it.get("ingredient_id", "")
            issued_map[iid] = issued_map.get(iid, 0) + it.get("quantity", 0)

        for ret_item in items:
            iid = ret_item.get("ingredient_id", "")
            ret_qty = ret_item.get("quantity", 0)
            issued_qty = issued_map.get(iid, 0)
            if ret_qty > issued_qty:
                raise ValueError(
                    f"退回数量({ret_qty})不能超过领用数量({issued_qty}), "
                    f"商品: {iid}"
                )

    return_id = _gen_id("iret")
    now = _now_iso()
    total_return_qty = sum(i.get("quantity", 0) for i in items)

    record: Dict[str, Any] = {
        "return_id": return_id,
        "issue_id": issue_id,
        "tenant_id": tenant_id,
        "status": "returned",
        "items": items,
        "item_count": len(items),
        "total_return_qty": round(total_return_qty, 2),
        "created_at": now,
    }

    log.info(
        "issue_return_created",
        return_id=return_id,
        issue_id=issue_id,
        tenant_id=tenant_id,
        item_count=len(items),
    )
    return record


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. 部门间调拨
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def create_dept_transfer(
    from_dept: str,
    to_dept: str,
    items: List[Dict[str, Any]],
    tenant_id: str,
    db: Any,
) -> Dict[str, Any]:
    """创建部门间调拨单。

    Args:
        from_dept: 调出部门 ID
        to_dept: 调入部门 ID
        items: 调拨明细 [{ingredient_id, name, quantity, unit}]
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        调拨单
    """
    if from_dept == to_dept:
        raise ValueError("调出部门和调入部门不能相同")
    if not items:
        raise ValueError("调拨单必须包含至少一项商品")

    transfer_id = _gen_id("dtf")
    now = _now_iso()

    record: Dict[str, Any] = {
        "transfer_id": transfer_id,
        "from_dept": from_dept,
        "to_dept": to_dept,
        "tenant_id": tenant_id,
        "status": "pending",
        "items": items,
        "item_count": len(items),
        "total_qty": round(sum(i.get("quantity", 0) for i in items), 2),
        "created_at": now,
    }

    log.info(
        "dept_transfer_created",
        transfer_id=transfer_id,
        from_dept=from_dept,
        to_dept=to_dept,
        tenant_id=tenant_id,
        item_count=len(items),
    )
    return record


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. 出料率抽检
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def check_yield_rate(
    dish_id: str,
    store_id: str,
    tenant_id: str,
    db: Any,
    *,
    actual_output: float = 0,
    theoretical_output: float = 0,
) -> Dict[str, Any]:
    """出料率抽检: 出料率 = 实际产出量 / 理论产出量。

    Args:
        dish_id: 菜品 ID
        store_id: 门店 ID
        tenant_id: 租户 ID
        db: 数据库会话
        actual_output: 实际产出量
        theoretical_output: 理论产出量

    Returns:
        出料率检查结果
    """
    if theoretical_output <= 0:
        raise ValueError("理论产出量必须大于0")
    if actual_output < 0:
        raise ValueError("实际产出量不能为负")

    yield_rate = round(actual_output / theoretical_output, 4)
    # 出料率低于 90% 视为异常
    is_normal = yield_rate >= 0.90
    check_id = _gen_id("yld")

    record: Dict[str, Any] = {
        "check_id": check_id,
        "dish_id": dish_id,
        "store_id": store_id,
        "tenant_id": tenant_id,
        "actual_output": actual_output,
        "theoretical_output": theoretical_output,
        "yield_rate": yield_rate,
        "yield_percent": round(yield_rate * 100, 2),
        "is_normal": is_normal,
        "status": "normal" if is_normal else "abnormal",
        "checked_at": _now_iso(),
    }

    log.info(
        "yield_rate_checked",
        check_id=check_id,
        dish_id=dish_id,
        store_id=store_id,
        tenant_id=tenant_id,
        yield_rate=yield_rate,
        is_normal=is_normal,
    )
    return record


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. 销售转出库
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def sales_to_inventory(
    store_id: str,
    date: str,
    tenant_id: str,
    db: Any,
    *,
    sales_data: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """将销售数据转为出库记录 (基于 BOM 扣减原料)。

    Args:
        store_id: 门店 ID
        date: 日期 (YYYY-MM-DD)
        tenant_id: 租户 ID
        db: 数据库会话
        sales_data: 销售数据 [{dish_id, dish_name, quantity,
                     ingredients: [{ingredient_id, name, qty_per_dish, unit}]}]

    Returns:
        出库汇总
    """
    data = sales_data or []
    deduction_items: List[Dict[str, Any]] = []

    for sale in data:
        dish_qty = sale.get("quantity", 0)
        for ing in sale.get("ingredients", []):
            deduction_items.append({
                "ingredient_id": ing.get("ingredient_id"),
                "name": ing.get("name", ""),
                "quantity": round(ing.get("qty_per_dish", 0) * dish_qty, 4),
                "unit": ing.get("unit", ""),
                "source_dish_id": sale.get("dish_id"),
                "source_dish_name": sale.get("dish_name", ""),
            })

    # 合并相同原料
    merged: Dict[str, Dict[str, Any]] = {}
    for item in deduction_items:
        iid = item["ingredient_id"]
        if iid in merged:
            merged[iid]["quantity"] = round(
                merged[iid]["quantity"] + item["quantity"], 4
            )
        else:
            merged[iid] = {**item}

    merged_list = list(merged.values())
    out_id = _gen_id("sout")

    record: Dict[str, Any] = {
        "outbound_id": out_id,
        "store_id": store_id,
        "date": date,
        "tenant_id": tenant_id,
        "status": "completed",
        "sales_count": len(data),
        "deduction_items": merged_list,
        "deduction_item_count": len(merged_list),
        "total_deduction_qty": round(
            sum(i["quantity"] for i in merged_list), 4
        ),
        "created_at": _now_iso(),
    }

    log.info(
        "sales_to_inventory_completed",
        outbound_id=out_id,
        store_id=store_id,
        date=date,
        tenant_id=tenant_id,
        sales_count=len(data),
        deduction_count=len(merged_list),
    )
    return record


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  6. 领用商品流水
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def get_issue_flow(
    store_id: str,
    dept_id: str,
    date_range: Tuple[str, str],
    tenant_id: str,
    db: Any,
    *,
    issue_orders: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """查询领用商品流水。

    Args:
        store_id: 门店 ID
        dept_id: 部门 ID
        date_range: (start_date, end_date)
        tenant_id: 租户 ID
        db: 数据库会话
        issue_orders: 领用单列表 (测试注入用)

    Returns:
        领用流水汇总
    """
    data = issue_orders or []
    total_cost_fen = sum(o.get("total_cost_fen", 0) for o in data)
    total_qty = sum(o.get("total_qty", 0) for o in data)

    log.info(
        "issue_flow_queried",
        store_id=store_id,
        dept_id=dept_id,
        tenant_id=tenant_id,
        date_range=date_range,
        total_count=len(data),
    )
    return {
        "store_id": store_id,
        "dept_id": dept_id,
        "date_range": list(date_range),
        "tenant_id": tenant_id,
        "orders": data,
        "total_count": len(data),
        "total_cost_fen": total_cost_fen,
        "total_qty": round(total_qty, 2),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  7. 月度汇总
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def get_monthly_summary(
    store_id: str,
    month: str,
    tenant_id: str,
    db: Any,
    *,
    issue_orders: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """月度领用汇总。

    Args:
        store_id: 门店 ID
        month: 月份 (YYYY-MM)
        tenant_id: 租户 ID
        db: 数据库会话
        issue_orders: 当月领用单列表 (测试注入用)

    Returns:
        月度汇总
    """
    data = issue_orders or []
    total_cost_fen = sum(o.get("total_cost_fen", 0) for o in data)
    total_qty = sum(o.get("total_qty", 0) for o in data)

    # 按部门汇总
    dept_summary: Dict[str, Dict[str, Any]] = {}
    for order in data:
        dept = order.get("dept_id", "unknown")
        if dept not in dept_summary:
            dept_summary[dept] = {"dept_id": dept, "order_count": 0, "total_cost_fen": 0, "total_qty": 0}
        dept_summary[dept]["order_count"] += 1
        dept_summary[dept]["total_cost_fen"] += order.get("total_cost_fen", 0)
        dept_summary[dept]["total_qty"] = round(
            dept_summary[dept]["total_qty"] + order.get("total_qty", 0), 2
        )

    log.info(
        "monthly_summary_queried",
        store_id=store_id,
        month=month,
        tenant_id=tenant_id,
        total_orders=len(data),
    )
    return {
        "store_id": store_id,
        "month": month,
        "tenant_id": tenant_id,
        "total_orders": len(data),
        "total_cost_fen": total_cost_fen,
        "total_qty": round(total_qty, 2),
        "dept_summary": list(dept_summary.values()),
    }
