"""E5 闭店盘点 — 闭店检查单、原料盘点、损耗上报、闭店放行

从 check_item_templates 加载 E5 模板，结合 workflow_engine 状态机。
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import structlog

from .check_item_templates import get_node_from_template
from .daily_ops_service import compute_node_check_result

log = structlog.get_logger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  闭店检查单
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def create_closing_checklist(
    store_id: str,
    date_: date,
    tenant_id: str,
    db: Any,
    template_key: str = "xuji_seafood",
) -> Dict[str, Any]:
    """生成闭店检查单。

    Args:
        store_id: 门店 ID
        date_: 日期
        tenant_id: 租户 ID
        db: 数据库会话
        template_key: 模板标识

    Returns:
        {"checklist_id": str, "items": [...], "status": "pending", ...}
    """
    node_def = get_node_from_template(template_key, "E5")
    if node_def is None:
        raise ValueError(f"Template '{template_key}' does not have E5 node")

    checklist_id = f"close_{store_id}_{date_.isoformat()}_{uuid.uuid4().hex[:8]}"
    items = []
    for idx, tpl_item in enumerate(node_def.get("check_items", [])):
        items.append({
            "item_id": f"{checklist_id}_item_{idx:03d}",
            "seq": idx,
            "text": tpl_item["item"],
            "required": tpl_item.get("required", False),
            "status": "pending",
            "result": None,
            "checked_by": None,
            "checked_at": None,
            "note": None,
        })

    checklist = {
        "checklist_id": checklist_id,
        "store_id": store_id,
        "tenant_id": tenant_id,
        "date": date_.isoformat(),
        "node_code": "E5",
        "template_key": template_key,
        "items": items,
        "stocktake": None,
        "waste_report": None,
        "status": "pending",
        "created_at": datetime.utcnow().isoformat(),
    }

    log.info(
        "closing_checklist_created",
        store_id=store_id,
        tenant_id=tenant_id,
        checklist_id=checklist_id,
        item_count=len(items),
    )
    return checklist


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  原料盘点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def record_closing_stocktake(
    store_id: str,
    items: List[Dict[str, Any]],
    tenant_id: str,
    db: Any,
) -> Dict[str, Any]:
    """记录闭店原料盘点。

    Args:
        store_id: 门店 ID
        items: 盘点项列表, 每项包含:
            {"ingredient_id": str, "name": str, "expected_qty": float,
             "actual_qty": float, "unit": str}
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        {"stocktake_id": str, "items": [...], "variance_count": int,
         "total_variance_pct": float, ...}
    """
    stocktake_id = f"st_{store_id}_{uuid.uuid4().hex[:8]}"
    enriched = []
    variance_count = 0
    total_expected = 0.0
    total_actual = 0.0

    for idx, item in enumerate(items):
        expected = item.get("expected_qty", 0.0)
        actual = item.get("actual_qty", 0.0)
        diff = actual - expected
        diff_pct = (diff / expected * 100) if expected != 0 else 0.0
        has_variance = abs(diff) > 0.001

        if has_variance:
            variance_count += 1
        total_expected += expected
        total_actual += actual

        enriched.append({
            "line_id": f"{stocktake_id}_l{idx:03d}",
            "ingredient_id": item.get("ingredient_id", ""),
            "name": item.get("name", ""),
            "expected_qty": expected,
            "actual_qty": actual,
            "unit": item.get("unit", ""),
            "variance": round(diff, 3),
            "variance_pct": round(diff_pct, 2),
            "has_variance": has_variance,
        })

    total_variance_pct = (
        round((total_actual - total_expected) / total_expected * 100, 2)
        if total_expected != 0 else 0.0
    )

    result = {
        "stocktake_id": stocktake_id,
        "store_id": store_id,
        "tenant_id": tenant_id,
        "items": enriched,
        "item_count": len(enriched),
        "variance_count": variance_count,
        "total_variance_pct": total_variance_pct,
        "recorded_at": datetime.utcnow().isoformat(),
    }

    log.info(
        "closing_stocktake_recorded",
        store_id=store_id,
        tenant_id=tenant_id,
        stocktake_id=stocktake_id,
        item_count=len(enriched),
        variance_count=variance_count,
    )
    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  损耗上报
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def record_waste_report(
    store_id: str,
    waste_items: List[Dict[str, Any]],
    tenant_id: str,
    db: Any,
) -> Dict[str, Any]:
    """记录损耗上报。

    Args:
        store_id: 门店 ID
        waste_items: 损耗项列表, 每项包含:
            {"ingredient_id": str, "name": str, "qty": float, "unit": str,
             "reason": str, "cost_fen": int}
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        {"waste_report_id": str, "items": [...], "total_cost_fen": int, ...}
    """
    report_id = f"waste_{store_id}_{uuid.uuid4().hex[:8]}"
    total_cost_fen = 0
    enriched = []

    for idx, item in enumerate(waste_items):
        cost = item.get("cost_fen", 0)
        total_cost_fen += cost
        enriched.append({
            "line_id": f"{report_id}_l{idx:03d}",
            "ingredient_id": item.get("ingredient_id", ""),
            "name": item.get("name", ""),
            "qty": item.get("qty", 0),
            "unit": item.get("unit", ""),
            "reason": item.get("reason", ""),
            "cost_fen": cost,
        })

    result = {
        "waste_report_id": report_id,
        "store_id": store_id,
        "tenant_id": tenant_id,
        "items": enriched,
        "item_count": len(enriched),
        "total_cost_fen": total_cost_fen,
        "recorded_at": datetime.utcnow().isoformat(),
    }

    log.info(
        "waste_report_recorded",
        store_id=store_id,
        tenant_id=tenant_id,
        report_id=report_id,
        item_count=len(enriched),
        total_cost_fen=total_cost_fen,
    )
    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  闭店放行
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def finalize_closing(
    store_id: str,
    manager_id: str,
    tenant_id: str,
    db: Any,
    *,
    checklist: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """闭店放行。

    检查单必填项全部通过后，店长确认闭店。

    Args:
        store_id: 门店 ID
        manager_id: 店长 ID
        tenant_id: 租户 ID
        db: 数据库会话
        checklist: 闭店检查单

    Returns:
        {"finalized": bool, "finalized_by": str, "finalized_at": str, ...}

    Raises:
        ValueError: 必填项未全部通过
    """
    status = get_closing_status(store_id, date.today(), tenant_id, db, checklist=checklist)

    if not status["can_close"]:
        raise ValueError(
            f"Cannot finalize closing: {status['blocked']} required item(s) blocked. "
            f"Checked {status['checked']}/{status['total']}"
        )

    finalized_at = datetime.utcnow().isoformat()

    if checklist is not None:
        checklist["status"] = "finalized"
        checklist["finalized_by"] = manager_id
        checklist["finalized_at"] = finalized_at

    log.info(
        "closing_finalized",
        store_id=store_id,
        manager_id=manager_id,
        tenant_id=tenant_id,
    )

    return {
        "finalized": True,
        "finalized_by": manager_id,
        "finalized_at": finalized_at,
        "store_id": store_id,
        "message": "闭店确认完成",
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  闭店进度
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def get_closing_status(
    store_id: str,
    date_: date,
    tenant_id: str,
    db: Any,
    *,
    checklist: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """获取闭店检查进度。

    Args:
        store_id: 门店 ID
        date_: 日期
        tenant_id: 租户 ID
        db: 数据库会话
        checklist: 已加载的闭店检查单

    Returns:
        {"total": int, "checked": int, "passed": int, "blocked": int,
         "can_close": bool, "has_stocktake": bool, "has_waste_report": bool}
    """
    if checklist is None:
        return {
            "total": 0, "checked": 0, "passed": 0, "blocked": 0,
            "can_close": False, "has_stocktake": False, "has_waste_report": False,
        }

    items = checklist.get("items", [])
    total = len(items)
    checked = sum(1 for i in items if i["status"] in ("checked", "skipped"))
    passed = sum(1 for i in items if i.get("result") == "pass")
    blocked = sum(1 for i in items if i.get("result") == "fail" and i.get("required"))

    required_items = [i for i in items if i.get("required")]
    all_required_passed = all(i.get("result") == "pass" for i in required_items) if required_items else True
    has_stocktake = checklist.get("stocktake") is not None
    has_waste_report = checklist.get("waste_report") is not None

    can_close = blocked == 0 and all_required_passed and len(required_items) > 0

    return {
        "total": total,
        "checked": checked,
        "passed": passed,
        "blocked": blocked,
        "can_close": can_close,
        "has_stocktake": has_stocktake,
        "has_waste_report": has_waste_report,
    }
