"""
门店克隆服务 -- 深拷贝门店全部配置数据

核心能力：
- 单店克隆：复制门店全部配置（菜品库/菜单模板/桌台/档口/打印/服务费）
- 克隆预览：查看将复制哪些数据
- 批量克隆：一次创建多家新门店（上限 100 家）

不复制的数据：订单/库存/会员/报表（这些属于新门店的运营数据）
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  可克隆的数据类型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CLONEABLE_MODULES = [
    "dish_library",       # 菜品库
    "menu_templates",     # 菜单模板
    "table_config",       # 桌台配置
    "stall_config",       # 档口设置
    "print_config",       # 打印配置
    "service_fee_plan",   # 服务费方案
]

NON_CLONEABLE_MODULES = [
    "orders",       # 订单
    "inventory",    # 库存
    "members",      # 会员
    "reports",      # 报表
]

BATCH_LIMIT = 100


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  模拟源门店数据（纯函数实现，无 DB 依赖）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _get_source_store_data(source_store_id: str, tenant_id: str) -> Dict[str, Any]:
    """获取源门店的可克隆数据（模拟）。"""
    return {
        "store_id": source_store_id,
        "tenant_id": tenant_id,
        "dish_library": [
            {"id": str(uuid.uuid4()), "name": "招牌菜A", "price_fen": 4800, "category": "热菜"},
            {"id": str(uuid.uuid4()), "name": "招牌菜B", "price_fen": 3200, "category": "凉菜"},
        ],
        "menu_templates": [
            {"id": str(uuid.uuid4()), "name": "午市套餐", "dish_count": 12},
            {"id": str(uuid.uuid4()), "name": "晚市套餐", "dish_count": 18},
        ],
        "table_config": [
            {"id": str(uuid.uuid4()), "zone": "大厅", "table_no": f"A{i}", "seats": 4}
            for i in range(1, 11)
        ],
        "stall_config": [
            {"id": str(uuid.uuid4()), "name": "热菜档", "type": "hot"},
            {"id": str(uuid.uuid4()), "name": "凉菜档", "type": "cold"},
        ],
        "print_config": [
            {"id": str(uuid.uuid4()), "printer_name": "前台小票机", "type": "receipt"},
            {"id": str(uuid.uuid4()), "printer_name": "厨房打印机", "type": "kitchen"},
        ],
        "service_fee_plan": [
            {"id": str(uuid.uuid4()), "name": "标准服务费", "rate": 0.10, "min_persons": 1},
        ],
    }


def _deep_copy_with_new_ids(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """深拷贝列表中的每个字典，并生成新 ID。"""
    result = []
    for item in items:
        new_item = dict(item)
        new_item["id"] = str(uuid.uuid4())
        new_item["cloned_from"] = item.get("id", "")
        result.append(new_item)
    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  克隆预览
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_clone_preview(
    source_store_id: str,
    tenant_id: str,
    db: Any = None,
) -> Dict[str, Any]:
    """克隆预览：查看源门店将被复制的数据概况。

    Args:
        source_store_id: 源门店ID
        tenant_id: 租户ID
        db: 数据库会话（预留）

    Returns:
        各模块数据量统计及不会复制的模块列表
    """
    log = logger.bind(tenant_id=tenant_id, source_store_id=source_store_id)
    log.info("store_clone.preview_requested")

    source_data = _get_source_store_data(source_store_id, tenant_id)

    preview = {
        "source_store_id": source_store_id,
        "cloneable": {},
        "non_cloneable": NON_CLONEABLE_MODULES,
    }

    for module in CLONEABLE_MODULES:
        items = source_data.get(module, [])
        preview["cloneable"][module] = {
            "count": len(items),
            "sample": items[:2] if items else [],
        }

    log.info("store_clone.preview_generated", modules=len(CLONEABLE_MODULES))
    return preview


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  单店克隆
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def clone_store(
    source_store_id: str,
    new_store_name: str,
    new_address: str,
    tenant_id: str,
    db: Any = None,
) -> Dict[str, Any]:
    """克隆门店：深拷贝源门店全部配置数据到新门店。

    新门店获得全新 ID，所有子数据（菜品/桌台等）也生成新 ID，
    不与源门店共享任何引用。

    Args:
        source_store_id: 源门店ID
        new_store_name: 新门店名称
        new_address: 新门店地址
        tenant_id: 租户ID
        db: 数据库会话（预留）

    Returns:
        新门店完整数据（含所有克隆后的配置）
    """
    log = logger.bind(
        tenant_id=tenant_id,
        source_store_id=source_store_id,
        new_store_name=new_store_name,
    )
    log.info("store_clone.started")

    if not new_store_name or not new_store_name.strip():
        raise ValueError("新门店名称不能为空")
    if not new_address or not new_address.strip():
        raise ValueError("新门店地址不能为空")

    source_data = _get_source_store_data(source_store_id, tenant_id)

    new_store_id = str(uuid.uuid4())
    now = datetime.now().isoformat()

    new_store: Dict[str, Any] = {
        "id": new_store_id,
        "name": new_store_name.strip(),
        "address": new_address.strip(),
        "tenant_id": tenant_id,
        "cloned_from": source_store_id,
        "status": "inactive",
        "created_at": now,
        "updated_at": now,
    }

    # 深拷贝每个可克隆模块
    clone_summary: Dict[str, int] = {}
    for module in CLONEABLE_MODULES:
        source_items = source_data.get(module, [])
        cloned_items = _deep_copy_with_new_ids(source_items)
        # 更新每个子项的 store_id
        for item in cloned_items:
            item["store_id"] = new_store_id
        new_store[module] = cloned_items
        clone_summary[module] = len(cloned_items)

    new_store["clone_summary"] = clone_summary

    log.info(
        "store_clone.completed",
        new_store_id=new_store_id,
        clone_summary=clone_summary,
    )
    return new_store


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  批量克隆
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def batch_clone(
    source_store_id: str,
    new_stores: List[Dict[str, str]],
    tenant_id: str,
    db: Any = None,
) -> Dict[str, Any]:
    """批量克隆：从同一源门店克隆出多家新门店。

    Args:
        source_store_id: 源门店ID
        new_stores: 新门店列表，每个元素包含 {"name": "xxx", "address": "xxx"}
        tenant_id: 租户ID
        db: 数据库会话（预留）

    Returns:
        批量克隆结果，包含成功/失败列表
    """
    log = logger.bind(
        tenant_id=tenant_id,
        source_store_id=source_store_id,
        batch_size=len(new_stores),
    )
    log.info("store_clone.batch_started")

    if not new_stores:
        raise ValueError("新门店列表不能为空")
    if len(new_stores) > BATCH_LIMIT:
        raise ValueError(f"批量克隆上限为 {BATCH_LIMIT} 家，当前请求 {len(new_stores)} 家")

    results: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []

    for idx, store_info in enumerate(new_stores):
        name = store_info.get("name", "")
        address = store_info.get("address", "")
        try:
            new_store = clone_store(
                source_store_id=source_store_id,
                new_store_name=name,
                new_address=address,
                tenant_id=tenant_id,
                db=db,
            )
            results.append({
                "index": idx,
                "store_id": new_store["id"],
                "name": new_store["name"],
                "status": "success",
            })
        except (ValueError, KeyError) as e:
            log.warning("store_clone.batch_item_failed", index=idx, name=name, error=str(e))
            failed.append({
                "index": idx,
                "name": name,
                "status": "failed",
                "error": str(e),
            })

    log.info(
        "store_clone.batch_completed",
        success_count=len(results),
        failed_count=len(failed),
    )

    return {
        "source_store_id": source_store_id,
        "total_requested": len(new_stores),
        "success_count": len(results),
        "failed_count": len(failed),
        "results": results,
        "failed": failed,
    }
