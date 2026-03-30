"""
门店批量操作服务

核心能力：
- 批量创建门店
- 批量激活/停用
- Excel 导入/导出门店

批量上限：100 家/次
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)

BATCH_LIMIT = 100

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  内存存储（纯函数实现，无 DB 依赖）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_stores: Dict[str, Dict[str, Any]] = {}


def _validate_batch_size(items: list, label: str = "操作") -> None:
    """校验批量操作数量。"""
    if not items:
        raise ValueError(f"{label}列表不能为空")
    if len(items) > BATCH_LIMIT:
        raise ValueError(f"批量{label}上限为 {BATCH_LIMIT}，当前请求 {len(items)}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  批量创建
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def batch_create_stores(
    stores: List[Dict[str, str]],
    tenant_id: str,
    db: Any = None,
) -> Dict[str, Any]:
    """批量创建门店。

    Args:
        stores: 门店列表，每个元素包含 {"name", "address", "brand_id"(可选), "business_type"(可选)}
        tenant_id: 租户ID
        db: 数据库会话（预留）

    Returns:
        批量创建结果
    """
    log = logger.bind(tenant_id=tenant_id, batch_size=len(stores))
    log.info("store_batch.create_started")

    _validate_batch_size(stores, "创建")

    created: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []

    for idx, store_info in enumerate(stores):
        name = store_info.get("name", "")
        address = store_info.get("address", "")

        if not name or not name.strip():
            failed.append({"index": idx, "name": name, "error": "门店名称不能为空"})
            continue
        if not address or not address.strip():
            failed.append({"index": idx, "name": name, "error": "门店地址不能为空"})
            continue

        store_id = str(uuid.uuid4())
        now = datetime.now().isoformat()

        store = {
            "id": store_id,
            "name": name.strip(),
            "address": address.strip(),
            "brand_id": store_info.get("brand_id", ""),
            "business_type": store_info.get("business_type", "standard"),
            "tenant_id": tenant_id,
            "status": "inactive",
            "created_at": now,
            "updated_at": now,
        }

        _stores[store_id] = store
        created.append({"index": idx, "store_id": store_id, "name": store["name"]})

    log.info(
        "store_batch.create_completed",
        success_count=len(created),
        failed_count=len(failed),
    )

    return {
        "total_requested": len(stores),
        "success_count": len(created),
        "failed_count": len(failed),
        "created": created,
        "failed": failed,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  批量激活 / 停用
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def batch_activate(
    store_ids: List[str],
    tenant_id: str,
    db: Any = None,
) -> Dict[str, Any]:
    """批量激活门店。

    Args:
        store_ids: 门店ID列表
        tenant_id: 租户ID
        db: 数据库会话（预留）

    Returns:
        激活结果
    """
    log = logger.bind(tenant_id=tenant_id, batch_size=len(store_ids))
    log.info("store_batch.activate_started")

    _validate_batch_size(store_ids, "激活")

    activated: List[str] = []
    failed: List[Dict[str, Any]] = []

    for store_id in store_ids:
        store = _stores.get(store_id)
        if not store:
            failed.append({"store_id": store_id, "error": "门店不存在"})
            continue
        if store["tenant_id"] != tenant_id:
            failed.append({"store_id": store_id, "error": "无权操作该门店"})
            continue
        if store["status"] == "active":
            failed.append({"store_id": store_id, "error": "门店已处于激活状态"})
            continue

        store["status"] = "active"
        store["updated_at"] = datetime.now().isoformat()
        activated.append(store_id)

    log.info(
        "store_batch.activate_completed",
        activated_count=len(activated),
        failed_count=len(failed),
    )

    return {
        "total_requested": len(store_ids),
        "activated_count": len(activated),
        "failed_count": len(failed),
        "activated": activated,
        "failed": failed,
    }


def batch_deactivate(
    store_ids: List[str],
    reason: str,
    tenant_id: str,
    db: Any = None,
) -> Dict[str, Any]:
    """批量停用门店。

    Args:
        store_ids: 门店ID列表
        reason: 停用原因
        tenant_id: 租户ID
        db: 数据库会话（预留）

    Returns:
        停用结果
    """
    log = logger.bind(tenant_id=tenant_id, batch_size=len(store_ids))
    log.info("store_batch.deactivate_started")

    _validate_batch_size(store_ids, "停用")

    if not reason or not reason.strip():
        raise ValueError("停用原因不能为空")

    deactivated: List[str] = []
    failed: List[Dict[str, Any]] = []

    for store_id in store_ids:
        store = _stores.get(store_id)
        if not store:
            failed.append({"store_id": store_id, "error": "门店不存在"})
            continue
        if store["tenant_id"] != tenant_id:
            failed.append({"store_id": store_id, "error": "无权操作该门店"})
            continue
        if store["status"] == "inactive":
            failed.append({"store_id": store_id, "error": "门店已处于停用状态"})
            continue

        store["status"] = "inactive"
        store["deactivation_reason"] = reason.strip()
        store["deactivated_at"] = datetime.now().isoformat()
        store["updated_at"] = datetime.now().isoformat()
        deactivated.append(store_id)

    log.info(
        "store_batch.deactivate_completed",
        deactivated_count=len(deactivated),
        failed_count=len(failed),
    )

    return {
        "total_requested": len(store_ids),
        "deactivated_count": len(deactivated),
        "failed_count": len(failed),
        "deactivated": deactivated,
        "failed": failed,
        "reason": reason.strip(),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Excel 导入 / 导出
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

REQUIRED_IMPORT_COLUMNS = {"name", "address"}
OPTIONAL_IMPORT_COLUMNS = {"brand_id", "business_type"}
EXPORT_COLUMNS = ["id", "name", "address", "brand_id", "business_type", "status", "created_at"]


def import_stores_from_excel(
    file_data: str,
    tenant_id: str,
    db: Any = None,
) -> Dict[str, Any]:
    """从 CSV/Excel 数据导入门店。

    Args:
        file_data: CSV 格式的文本数据（首行为列标题）
        tenant_id: 租户ID
        db: 数据库会话（预留）

    Returns:
        导入结果
    """
    log = logger.bind(tenant_id=tenant_id)
    log.info("store_batch.import_started")

    if not file_data or not file_data.strip():
        raise ValueError("导入数据不能为空")

    reader = csv.DictReader(io.StringIO(file_data.strip()))
    fieldnames = set(reader.fieldnames or [])

    missing_cols = REQUIRED_IMPORT_COLUMNS - fieldnames
    if missing_cols:
        raise ValueError(f"缺少必填列: {missing_cols}")

    rows = list(reader)
    if len(rows) > BATCH_LIMIT:
        raise ValueError(f"导入上限为 {BATCH_LIMIT} 条，当前数据 {len(rows)} 条")

    stores_to_create = []
    for row in rows:
        store_info: Dict[str, str] = {
            "name": row.get("name", ""),
            "address": row.get("address", ""),
        }
        for col in OPTIONAL_IMPORT_COLUMNS:
            if col in row and row[col]:
                store_info[col] = row[col]
        stores_to_create.append(store_info)

    result = batch_create_stores(stores_to_create, tenant_id, db)
    result["import_source"] = "excel"
    result["total_rows"] = len(rows)

    log.info("store_batch.import_completed", total_rows=len(rows))
    return result


def export_stores_to_excel(
    tenant_id: str,
    db: Any = None,
) -> Dict[str, Any]:
    """导出门店列表为 CSV 格式。

    Args:
        tenant_id: 租户ID
        db: 数据库会话（预留）

    Returns:
        包含 CSV 数据和门店数量的结果
    """
    log = logger.bind(tenant_id=tenant_id)
    log.info("store_batch.export_started")

    tenant_stores = [
        s for s in _stores.values() if s["tenant_id"] == tenant_id
    ]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=EXPORT_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for store in tenant_stores:
        writer.writerow(store)

    csv_data = output.getvalue()

    log.info("store_batch.export_completed", store_count=len(tenant_stores))

    return {
        "csv_data": csv_data,
        "store_count": len(tenant_stores),
        "columns": EXPORT_COLUMNS,
    }


def reset_storage() -> None:
    """重置内存存储（仅用于测试）。"""
    _stores.clear()
