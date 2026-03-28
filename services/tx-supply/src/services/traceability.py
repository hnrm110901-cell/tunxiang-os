"""原料追溯完整实现 -- 正向追溯 / 反向追溯 / 时间线 / 报告 / 关系图

追溯链必须完整：供应商 -> 入库 -> 领用 -> BOM -> 菜品 -> 订单 -> 客户
所有操作强制 tenant_id 租户隔离。
"""
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import structlog

log = structlog.get_logger()


# ─── 追溯节点类型 ───


class TraceNodeType(str, Enum):
    supplier = "supplier"           # 供应商
    receiving = "receiving"         # 入库验收
    storage = "storage"             # 仓储
    requisition = "requisition"     # 领用
    bom = "bom"                     # BOM 配方
    dish = "dish"                   # 菜品出品
    order = "order"                 # 订单
    customer = "customer"           # 客户


class TraceDirection(str, Enum):
    forward = "forward"    # 正向：供应商 -> 客户
    backward = "backward"  # 反向：客户 -> 供应商


# ─── 内部存储（可替换为 DB） ───


_batches: dict[str, dict] = {}            # batch_no -> 批次主档
_batch_transactions: dict[str, list] = {}  # batch_no -> [事务记录]
_bom_links: dict[str, list] = {}          # ingredient_id -> [dish_id]
_order_dishes: dict[str, list] = {}       # order_id -> [{dish_id, batch_nos}]
_order_customers: dict[str, dict] = {}    # order_id -> {customer_id, customer_name}
_ingredient_suppliers: dict[str, list] = {}  # ingredient_id -> [supplier_info]
_ingredient_alternatives: dict[str, list] = {}  # ingredient_id -> [alt_ingredient_id]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── 数据注入（供测试和外部服务调用） ───


def inject_batch(batch_no: str, tenant_id: str, data: dict) -> None:
    """注入批次主档

    data:
        supplier_id: str
        supplier_name: str
        ingredient_id: str
        ingredient_name: str
        quantity: float
        unit: str
        received_at: str(ISO)
        received_by: str
        store_id: str
        expiry_date: str|None
    """
    key = f"{tenant_id}:{batch_no}"
    _batches[key] = {**data, "batch_no": batch_no, "tenant_id": tenant_id}


def inject_batch_transaction(batch_no: str, tenant_id: str, txn: dict) -> None:
    """注入批次事务记录

    txn:
        node_type: str (TraceNodeType value)
        action: str (描述)
        operator: str
        location: str
        quantity: float
        timestamp: str(ISO)
        reference_id: str|None
        metadata: dict|None
    """
    key = f"{tenant_id}:{batch_no}"
    _batch_transactions.setdefault(key, []).append(txn)


def inject_bom_link(ingredient_id: str, tenant_id: str, dish_id: str) -> None:
    """注入原料 -> 菜品 BOM 关联"""
    key = f"{tenant_id}:{ingredient_id}"
    _bom_links.setdefault(key, []).append(dish_id)


def inject_order_dish(order_id: str, tenant_id: str, dish_info: dict) -> None:
    """注入订单 -> 菜品关联（含批次号）

    dish_info: {dish_id, dish_name, batch_nos: [str]}
    """
    key = f"{tenant_id}:{order_id}"
    _order_dishes.setdefault(key, []).append(dish_info)


def inject_order_customer(order_id: str, tenant_id: str, customer: dict) -> None:
    """注入订单 -> 客户关联

    customer: {customer_id, customer_name, phone}
    """
    key = f"{tenant_id}:{order_id}"
    _order_customers[key] = customer


def inject_ingredient_supplier(ingredient_id: str, tenant_id: str, supplier: dict) -> None:
    """注入原料 -> 供应商关联

    supplier: {supplier_id, supplier_name, contact, lead_time_days}
    """
    key = f"{tenant_id}:{ingredient_id}"
    _ingredient_suppliers.setdefault(key, []).append(supplier)


def inject_ingredient_alternative(ingredient_id: str, tenant_id: str, alt_id: str) -> None:
    """注入替代料关联"""
    key = f"{tenant_id}:{ingredient_id}"
    _ingredient_alternatives.setdefault(key, []).append(alt_id)


# ─── 核心服务函数 ───


def full_trace_forward(
    batch_no: str,
    tenant_id: str,
    db: object = None,
) -> dict:
    """正向追溯：供应商 -> 入库 -> 领用 -> BOM -> 菜品 -> 订单 -> 客户

    从一个批次号出发，追溯该批次原料流向了哪些菜品、哪些订单、哪些客户。

    Returns:
        {
            "batch_no": str,
            "direction": "forward",
            "chain": [TraceNode],
            "affected_dishes": [str],
            "affected_orders": [str],
            "affected_customers": [str],
            "complete": bool,
        }
    """
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")

    key = f"{tenant_id}:{batch_no}"
    batch = _batches.get(key)
    chain: list[dict] = []

    if not batch:
        log.warning("trace_forward_batch_not_found", batch_no=batch_no, tenant_id=tenant_id)
        return {
            "batch_no": batch_no,
            "direction": TraceDirection.forward.value,
            "chain": [],
            "affected_dishes": [],
            "affected_orders": [],
            "affected_customers": [],
            "complete": False,
        }

    # 1. 供应商节点
    chain.append({
        "node_type": TraceNodeType.supplier.value,
        "label": f"供应商: {batch.get('supplier_name', '未知')}",
        "supplier_id": batch.get("supplier_id"),
        "supplier_name": batch.get("supplier_name"),
        "timestamp": batch.get("received_at"),
    })

    # 2. 入库验收节点
    chain.append({
        "node_type": TraceNodeType.receiving.value,
        "label": f"入库验收: {batch.get('ingredient_name', '')} x{batch.get('quantity', 0)}{batch.get('unit', '')}",
        "store_id": batch.get("store_id"),
        "received_by": batch.get("received_by"),
        "quantity": batch.get("quantity"),
        "timestamp": batch.get("received_at"),
    })

    # 3. 事务记录中的领用节点
    transactions = _batch_transactions.get(key, [])
    for txn in transactions:
        chain.append({
            "node_type": txn.get("node_type", TraceNodeType.requisition.value),
            "label": txn.get("action", "操作"),
            "operator": txn.get("operator"),
            "location": txn.get("location"),
            "quantity": txn.get("quantity"),
            "timestamp": txn.get("timestamp"),
            "reference_id": txn.get("reference_id"),
        })

    # 4. BOM + 菜品关联
    ingredient_id = batch.get("ingredient_id")
    affected_dishes: list[str] = []
    if ingredient_id:
        ing_key = f"{tenant_id}:{ingredient_id}"
        dish_ids = _bom_links.get(ing_key, [])
        for did in dish_ids:
            affected_dishes.append(did)
            chain.append({
                "node_type": TraceNodeType.dish.value,
                "label": f"菜品出品: {did}",
                "dish_id": did,
                "ingredient_id": ingredient_id,
            })

    # 5. 订单 + 客户
    affected_orders: list[str] = []
    affected_customers: list[str] = []
    for okey, dishes in _order_dishes.items():
        if not okey.startswith(f"{tenant_id}:"):
            continue
        order_id = okey.split(":", 1)[1]
        for d in dishes:
            if d.get("dish_id") in affected_dishes or batch_no in d.get("batch_nos", []):
                affected_orders.append(order_id)
                chain.append({
                    "node_type": TraceNodeType.order.value,
                    "label": f"订单: {order_id}",
                    "order_id": order_id,
                    "dish_id": d.get("dish_id"),
                })
                # 客户
                cust = _order_customers.get(okey)
                if cust and cust.get("customer_id") not in affected_customers:
                    affected_customers.append(cust["customer_id"])
                    chain.append({
                        "node_type": TraceNodeType.customer.value,
                        "label": f"客户: {cust.get('customer_name', '未知')}",
                        "customer_id": cust["customer_id"],
                        "order_id": order_id,
                    })
                break

    complete = len(chain) >= 3  # 至少有供应商 + 入库 + 一个下游节点

    log.info(
        "trace_forward_complete",
        batch_no=batch_no,
        chain_length=len(chain),
        affected_dishes=len(affected_dishes),
        affected_orders=len(affected_orders),
        affected_customers=len(affected_customers),
        tenant_id=tenant_id,
    )

    return {
        "batch_no": batch_no,
        "direction": TraceDirection.forward.value,
        "chain": chain,
        "affected_dishes": affected_dishes,
        "affected_orders": affected_orders,
        "affected_customers": affected_customers,
        "complete": complete,
    }


def full_trace_backward(
    order_id: str,
    dish_id: str,
    tenant_id: str,
    db: object = None,
) -> dict:
    """反向追溯：客户 -> 订单 -> 菜品 -> BOM -> 原料 -> 批次 -> 供应商

    从一个订单和菜品出发，回溯用了哪些原料批次、来自哪些供应商。

    Returns:
        {
            "order_id": str,
            "dish_id": str,
            "direction": "backward",
            "chain": [TraceNode],
            "source_batches": [str],
            "source_suppliers": [str],
            "complete": bool,
        }
    """
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")

    chain: list[dict] = []

    # 1. 客户节点
    okey = f"{tenant_id}:{order_id}"
    cust = _order_customers.get(okey)
    if cust:
        chain.append({
            "node_type": TraceNodeType.customer.value,
            "label": f"客户: {cust.get('customer_name', '未知')}",
            "customer_id": cust.get("customer_id"),
        })

    # 2. 订单节点
    chain.append({
        "node_type": TraceNodeType.order.value,
        "label": f"订单: {order_id}",
        "order_id": order_id,
    })

    # 3. 菜品节点
    chain.append({
        "node_type": TraceNodeType.dish.value,
        "label": f"菜品: {dish_id}",
        "dish_id": dish_id,
    })

    # 4. 查找该菜品使用的批次号
    source_batches: list[str] = []
    order_dishes = _order_dishes.get(okey, [])
    for d in order_dishes:
        if d.get("dish_id") == dish_id:
            source_batches.extend(d.get("batch_nos", []))

    # 5. BOM -> 原料 -> 批次 -> 供应商
    source_suppliers: list[str] = []
    for bno in source_batches:
        bkey = f"{tenant_id}:{bno}"
        batch = _batches.get(bkey)
        if batch:
            # 原料节点
            chain.append({
                "node_type": TraceNodeType.bom.value,
                "label": f"原料: {batch.get('ingredient_name', '未知')} (批次 {bno})",
                "ingredient_id": batch.get("ingredient_id"),
                "batch_no": bno,
                "quantity": batch.get("quantity"),
            })
            # 入库节点
            chain.append({
                "node_type": TraceNodeType.receiving.value,
                "label": f"入库: {batch.get('received_at', '')}",
                "store_id": batch.get("store_id"),
                "received_by": batch.get("received_by"),
                "timestamp": batch.get("received_at"),
            })
            # 供应商节点
            supplier_name = batch.get("supplier_name", "未知")
            supplier_id = batch.get("supplier_id")
            if supplier_id and supplier_id not in source_suppliers:
                source_suppliers.append(supplier_id)
            chain.append({
                "node_type": TraceNodeType.supplier.value,
                "label": f"供应商: {supplier_name}",
                "supplier_id": supplier_id,
                "supplier_name": supplier_name,
            })

    complete = len(source_batches) > 0 and len(source_suppliers) > 0

    log.info(
        "trace_backward_complete",
        order_id=order_id,
        dish_id=dish_id,
        chain_length=len(chain),
        source_batches=source_batches,
        source_suppliers=source_suppliers,
        tenant_id=tenant_id,
    )

    return {
        "order_id": order_id,
        "dish_id": dish_id,
        "direction": TraceDirection.backward.value,
        "chain": chain,
        "source_batches": source_batches,
        "source_suppliers": source_suppliers,
        "complete": complete,
    }


def get_trace_timeline(
    batch_no: str,
    tenant_id: str,
    db: object = None,
) -> dict:
    """追溯时间线：每个节点的时间 / 操作人 / 位置

    Returns:
        {
            "batch_no": str,
            "timeline": [{timestamp, node_type, action, operator, location}],
            "total_nodes": int,
            "duration_hours": float|None,
        }
    """
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")

    key = f"{tenant_id}:{batch_no}"
    batch = _batches.get(key)
    timeline: list[dict] = []

    if not batch:
        log.warning("trace_timeline_not_found", batch_no=batch_no, tenant_id=tenant_id)
        return {
            "batch_no": batch_no,
            "timeline": [],
            "total_nodes": 0,
            "duration_hours": None,
        }

    # 入库节点
    timeline.append({
        "timestamp": batch.get("received_at"),
        "node_type": TraceNodeType.receiving.value,
        "action": f"入库验收 {batch.get('ingredient_name', '')}",
        "operator": batch.get("received_by"),
        "location": batch.get("store_id"),
    })

    # 事务节点
    transactions = _batch_transactions.get(key, [])
    for txn in transactions:
        timeline.append({
            "timestamp": txn.get("timestamp"),
            "node_type": txn.get("node_type", "unknown"),
            "action": txn.get("action", ""),
            "operator": txn.get("operator"),
            "location": txn.get("location"),
        })

    # 按时间排序
    timeline.sort(key=lambda x: x.get("timestamp") or "")

    # 计算时间跨度
    duration_hours = None
    if len(timeline) >= 2:
        first_ts = timeline[0].get("timestamp")
        last_ts = timeline[-1].get("timestamp")
        if first_ts and last_ts:
            t1 = datetime.fromisoformat(first_ts)
            t2 = datetime.fromisoformat(last_ts)
            duration_hours = round((t2 - t1).total_seconds() / 3600, 2)

    log.info(
        "trace_timeline_built",
        batch_no=batch_no,
        total_nodes=len(timeline),
        duration_hours=duration_hours,
        tenant_id=tenant_id,
    )

    return {
        "batch_no": batch_no,
        "timeline": timeline,
        "total_nodes": len(timeline),
        "duration_hours": duration_hours,
    }


def generate_trace_report(
    batch_no: str,
    tenant_id: str,
    db: object = None,
) -> dict:
    """追溯报告（用于食安事件）

    汇总正向追溯 + 时间线，生成完整的食安追溯报告。

    Returns:
        {
            "report_id": str,
            "batch_no": str,
            "generated_at": str(ISO),
            "batch_info": dict,
            "forward_trace": dict,
            "timeline": dict,
            "risk_assessment": dict,
            "recommendations": [str],
        }
    """
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")

    report_id = str(uuid.uuid4())
    key = f"{tenant_id}:{batch_no}"
    batch = _batches.get(key)

    forward_trace = full_trace_forward(batch_no, tenant_id)
    timeline = get_trace_timeline(batch_no, tenant_id)

    # 风险评估
    affected_count = len(forward_trace.get("affected_customers", []))
    if affected_count == 0:
        risk_level = "low"
        risk_description = "未发现受影响客户"
    elif affected_count <= 5:
        risk_level = "medium"
        risk_description = f"影响 {affected_count} 位客户"
    else:
        risk_level = "high"
        risk_description = f"影响 {affected_count} 位客户，需立即处理"

    risk_assessment = {
        "risk_level": risk_level,
        "affected_customers_count": affected_count,
        "affected_orders_count": len(forward_trace.get("affected_orders", [])),
        "affected_dishes_count": len(forward_trace.get("affected_dishes", [])),
        "description": risk_description,
        "trace_complete": forward_trace.get("complete", False),
    }

    # 建议
    recommendations: list[str] = []
    if risk_level == "high":
        recommendations.append("立即停用该批次剩余原料")
        recommendations.append("联系受影响客户进行健康跟踪")
        recommendations.append("通知区域经理及食安部门")
    elif risk_level == "medium":
        recommendations.append("暂停使用该批次原料，等待检测结果")
        recommendations.append("记录受影响订单，准备客户沟通方案")
    recommendations.append("联系供应商核实批次质量")
    recommendations.append("加强同类原料的入库检验标准")

    report = {
        "report_id": report_id,
        "batch_no": batch_no,
        "generated_at": _now_iso(),
        "batch_info": batch or {"batch_no": batch_no, "found": False},
        "forward_trace": forward_trace,
        "timeline": timeline,
        "risk_assessment": risk_assessment,
        "recommendations": recommendations,
    }

    log.info(
        "trace_report_generated",
        report_id=report_id,
        batch_no=batch_no,
        risk_level=risk_level,
        affected_customers=affected_count,
        tenant_id=tenant_id,
    )

    return report


def build_ingredient_graph(
    ingredient_id: str,
    tenant_id: str,
    db: object = None,
) -> dict:
    """原料关系图：替代料 / BOM 关联 / 供应商网络

    Returns:
        {
            "ingredient_id": str,
            "bom_dishes": [str],          # 使用该原料的菜品
            "suppliers": [dict],          # 供应商列表
            "alternatives": [str],        # 替代料 ID
            "graph_nodes": [dict],        # 图节点
            "graph_edges": [dict],        # 图边
        }
    """
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")

    key = f"{tenant_id}:{ingredient_id}"

    bom_dishes = _bom_links.get(key, [])
    suppliers = _ingredient_suppliers.get(key, [])
    alternatives = _ingredient_alternatives.get(key, [])

    # 构建图结构
    graph_nodes: list[dict] = []
    graph_edges: list[dict] = []

    # 原料中心节点
    graph_nodes.append({
        "id": ingredient_id,
        "type": "ingredient",
        "label": f"原料 {ingredient_id}",
    })

    # 菜品节点
    for did in bom_dishes:
        graph_nodes.append({"id": did, "type": "dish", "label": f"菜品 {did}"})
        graph_edges.append({
            "source": ingredient_id,
            "target": did,
            "relation": "used_in_bom",
        })

    # 供应商节点
    for sup in suppliers:
        sid = sup.get("supplier_id", "unknown")
        graph_nodes.append({
            "id": sid,
            "type": "supplier",
            "label": sup.get("supplier_name", "未知供应商"),
        })
        graph_edges.append({
            "source": sid,
            "target": ingredient_id,
            "relation": "supplies",
        })

    # 替代料节点
    for alt_id in alternatives:
        graph_nodes.append({
            "id": alt_id,
            "type": "alternative",
            "label": f"替代料 {alt_id}",
        })
        graph_edges.append({
            "source": ingredient_id,
            "target": alt_id,
            "relation": "alternative_for",
        })

    log.info(
        "ingredient_graph_built",
        ingredient_id=ingredient_id,
        dishes_count=len(bom_dishes),
        suppliers_count=len(suppliers),
        alternatives_count=len(alternatives),
        tenant_id=tenant_id,
    )

    return {
        "ingredient_id": ingredient_id,
        "bom_dishes": bom_dishes,
        "suppliers": suppliers,
        "alternatives": alternatives,
        "graph_nodes": graph_nodes,
        "graph_edges": graph_edges,
    }


# ─── 测试工具 ───


def _clear_store() -> None:
    """清空内部存储，仅供测试用"""
    _batches.clear()
    _batch_transactions.clear()
    _bom_links.clear()
    _order_dishes.clear()
    _order_customers.clear()
    _ingredient_suppliers.clear()
    _ingredient_alternatives.clear()
