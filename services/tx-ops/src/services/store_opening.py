"""E1 开店准备 — 检查单生成、逐项打勾、开店放行

从 check_item_templates 加载模板，结合 workflow_engine 状态机。
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import structlog

from .check_item_templates import get_node_from_template

log = structlog.get_logger(__name__)

# ─── 开店检查项分类 ───

OPENING_CATEGORIES = [
    "hygiene",       # 卫生检查
    "equipment",     # 设备开机
    "ingredient",    # 食材验收
    "stockout",      # 沽清确认
    "staff",         # 人员到岗
    "table",         # 桌台就绪
]

# 模板项到分类的映射（关键词匹配）
_CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "hygiene":    ["卫生", "清洁", "仪容", "布置", "整洁", "灯光空调"],
    "equipment":  ["POS", "KDS", "打印机", "开机", "设备", "点餐机", "灯箱"],
    "ingredient": ["食材", "到货", "签收", "温度", "冰鲜", "冷藏", "海鲜池水温"],
    "stockout":   ["沽清", "补货", "备料", "库存"],
    "staff":      ["服务员", "人员", "仪容仪表", "晨会"],
    "table":      ["桌椅", "台面", "包间", "座位", "桌台", "预订"],
}


def _classify_item(item_text: str) -> str:
    """根据检查项文本关键词分类。"""
    for category, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in item_text:
                return category
    return "other"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  核心函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def create_opening_checklist(
    store_id: str,
    date_: date,
    tenant_id: str,
    db: Any,
    template_key: str = "xuji_seafood",
) -> Dict[str, Any]:
    """生成当日开店检查单。

    从 check_item_templates 加载 E1 节点模板，生成带唯一 ID 的检查项列表。

    Args:
        store_id: 门店 ID
        date_: 日期
        tenant_id: 租户 ID
        db: 数据库会话
        template_key: 模板标识

    Returns:
        {"checklist_id": str, "store_id": str, "date": str, "items": [...],
         "status": "pending", "created_at": str}
    """
    node_def = get_node_from_template(template_key, "E1")
    if node_def is None:
        raise ValueError(f"Template '{template_key}' does not have E1 node")

    checklist_id = f"chk_{store_id}_{date_.isoformat()}_{uuid.uuid4().hex[:8]}"
    items = []
    for idx, tpl_item in enumerate(node_def.get("check_items", [])):
        items.append({
            "item_id": f"{checklist_id}_item_{idx:03d}",
            "seq": idx,
            "text": tpl_item["item"],
            "required": tpl_item.get("required", False),
            "category": _classify_item(tpl_item["item"]),
            "status": "pending",      # pending / checked / skipped
            "result": None,           # pass / fail / na
            "checked_by": None,
            "checked_at": None,
            "note": None,
        })

    checklist = {
        "checklist_id": checklist_id,
        "store_id": store_id,
        "tenant_id": tenant_id,
        "date": date_.isoformat(),
        "node_code": "E1",
        "template_key": template_key,
        "items": items,
        "status": "pending",
        "created_at": datetime.utcnow().isoformat(),
    }

    log.info(
        "opening_checklist_created",
        store_id=store_id,
        tenant_id=tenant_id,
        checklist_id=checklist_id,
        item_count=len(items),
    )
    return checklist


async def check_item(
    checklist_id: str,
    item_id: str,
    status: str,
    operator_id: str,
    db: Any,
    *,
    result: str = "pass",
    note: Optional[str] = None,
    tenant_id: str = "",
    checklist: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """逐项打勾。

    Args:
        checklist_id: 检查单 ID
        item_id: 检查项 ID
        status: checked / skipped
        operator_id: 操作人 ID
        db: 数据库会话
        result: pass / fail / na
        note: 备注
        tenant_id: 租户 ID
        checklist: 已加载的检查单（避免重复查库）

    Returns:
        更新后的检查项 dict

    Raises:
        ValueError: 检查项不存在
    """
    if status not in ("checked", "skipped"):
        raise ValueError(f"Invalid check status: {status}. Must be 'checked' or 'skipped'")
    if result not in ("pass", "fail", "na"):
        raise ValueError(f"Invalid result: {result}. Must be 'pass', 'fail', or 'na'")

    if checklist is None:
        # 实际场景从 db 加载, 这里用占位
        raise ValueError(f"Checklist '{checklist_id}' not found — pass checklist explicitly or implement DB lookup")

    target_item = None
    for item in checklist.get("items", []):
        if item["item_id"] == item_id:
            target_item = item
            break

    if target_item is None:
        raise ValueError(f"Item '{item_id}' not found in checklist '{checklist_id}'")

    target_item["status"] = status
    target_item["result"] = result
    target_item["checked_by"] = operator_id
    target_item["checked_at"] = datetime.utcnow().isoformat()
    target_item["note"] = note

    log.info(
        "check_item_updated",
        checklist_id=checklist_id,
        item_id=item_id,
        status=status,
        result=result,
        operator_id=operator_id,
        tenant_id=tenant_id,
    )
    return target_item


def get_opening_status(
    store_id: str,
    date_: date,
    tenant_id: str,
    db: Any,
    *,
    checklist: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """获取开店检查进度。

    Args:
        store_id: 门店 ID
        date_: 日期
        tenant_id: 租户 ID
        db: 数据库会话
        checklist: 已加载的检查单

    Returns:
        {"total": int, "checked": int, "passed": int, "blocked": int,
         "can_open": bool, "categories": {...}}
    """
    if checklist is None:
        return {"total": 0, "checked": 0, "passed": 0, "blocked": 0, "can_open": False, "categories": {}}

    items = checklist.get("items", [])
    total = len(items)
    checked = sum(1 for i in items if i["status"] in ("checked", "skipped"))
    passed = sum(1 for i in items if i["result"] == "pass")
    blocked = sum(1 for i in items if i["result"] == "fail" and i.get("required"))

    # 必填项全部 pass 才可开店
    required_items = [i for i in items if i.get("required")]
    all_required_passed = all(i["result"] == "pass" for i in required_items) if required_items else True
    can_open = blocked == 0 and all_required_passed and len(required_items) > 0

    # 按分类汇总
    category_summary: Dict[str, Dict[str, int]] = {}
    for item in items:
        cat = item.get("category", "other")
        if cat not in category_summary:
            category_summary[cat] = {"total": 0, "checked": 0, "passed": 0}
        category_summary[cat]["total"] += 1
        if item["status"] in ("checked", "skipped"):
            category_summary[cat]["checked"] += 1
        if item["result"] == "pass":
            category_summary[cat]["passed"] += 1

    return {
        "total": total,
        "checked": checked,
        "passed": passed,
        "blocked": blocked,
        "can_open": can_open,
        "categories": category_summary,
    }


async def approve_opening(
    store_id: str,
    manager_id: str,
    tenant_id: str,
    db: Any,
    *,
    checklist: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """店长确认开店放行。

    必填项全部通过后，店长确认开店。

    Args:
        store_id: 门店 ID
        manager_id: 店长 ID
        tenant_id: 租户 ID
        db: 数据库会话
        checklist: 已加载的检查单

    Returns:
        {"approved": bool, "approved_by": str, "approved_at": str,
         "store_id": str, "message": str}

    Raises:
        ValueError: 必填项未全部通过
    """
    status = get_opening_status(store_id, date.today(), tenant_id, db, checklist=checklist)

    if not status["can_open"]:
        blocked = status["blocked"]
        raise ValueError(
            f"Cannot approve opening: {blocked} required item(s) blocked. "
            f"Checked {status['checked']}/{status['total']}"
        )

    approved_at = datetime.utcnow().isoformat()

    if checklist is not None:
        checklist["status"] = "approved"
        checklist["approved_by"] = manager_id
        checklist["approved_at"] = approved_at

    log.info(
        "opening_approved",
        store_id=store_id,
        manager_id=manager_id,
        tenant_id=tenant_id,
    )

    return {
        "approved": True,
        "approved_by": manager_id,
        "approved_at": approved_at,
        "store_id": store_id,
        "message": "开店放行成功",
    }
