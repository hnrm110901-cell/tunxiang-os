"""
品智食材数据映射（轻量版）

将品智食材/库存原始数据映射为屯象标准格式，供供应链模块使用。

品智食材接口字段：
  materialId, materialName, unit, categoryName, specification,
  stockQty (可能为 None), unitPrice (分，可能缺失)
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)


def pinzhi_ingredient_to_unified(
    raw: dict,
    store_id: str,
    tenant_id: str,
) -> dict:
    """品智食材 → 屯象标准 Ingredient 格式

    品智字段：
      materialId, materialName, unit, categoryName,
      specification, stockQty, unitPrice (分)

    Args:
        raw: 品智API返回的单条食材数据
        store_id: 门店ID（屯象内部）
        tenant_id: 租户ID（强制存在）

    Returns:
        屯象标准食材字典

    Raises:
        ValueError: materialId 或 materialName 缺失时
    """
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")
    if not store_id:
        raise ValueError("store_id 不能为空")

    material_id: str = str(raw.get("materialId") or "").strip()
    material_name: str = str(raw.get("materialName") or "").strip()

    if not material_id:
        raise ValueError(f"品智食材缺少 materialId，原始数据: {raw!r}")
    if not material_name:
        raise ValueError(f"品智食材缺少 materialName，原始数据: {raw!r}")

    # 库存数量（品智可能不返回此字段）
    raw_stock = raw.get("stockQty")
    try:
        stock_qty: Optional[float] = float(raw_stock) if raw_stock is not None else None
    except (ValueError, TypeError):
        stock_qty = None
        logger.warning(
            "pinzhi_ingredient_stock_parse_error",
            material_id=material_id,
            raw_stock=raw_stock,
        )

    # 单价（品智单位为分，转换为元）
    raw_price = raw.get("unitPrice")
    try:
        unit_price_yuan: Optional[float] = float(raw_price) / 100.0 if raw_price is not None else None
    except (ValueError, TypeError):
        unit_price_yuan = None
        logger.warning(
            "pinzhi_ingredient_price_parse_error",
            material_id=material_id,
            raw_price=raw_price,
        )

    result: dict = {
        "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"pinzhi:{tenant_id}:{store_id}:{material_id}")),
        "external_id": material_id,
        "source": "pinzhi",
        "tenant_id": tenant_id,
        "store_id": store_id,
        "name": material_name,
        "unit": str(raw.get("unit") or ""),
        "category_name": str(raw.get("categoryName") or ""),
        "specification": str(raw.get("specification") or ""),
        "stock_qty": stock_qty,
        "unit_price": unit_price_yuan,
    }

    logger.debug(
        "pinzhi_ingredient_mapped",
        material_id=material_id,
        tenant_id=tenant_id,
        store_id=store_id,
    )
    return result


def pinzhi_ingredients_batch_to_unified(
    raw_list: List[dict],
    store_id: str,
    tenant_id: str,
) -> Dict[str, Any]:
    """批量映射品智食材列表，含错误统计。

    Args:
        raw_list: 品智API返回的食材列表
        store_id: 门店ID
        tenant_id: 租户ID

    Returns:
        {"items": [...], "total": int, "failed": int, "failed_ids": [...]}
    """
    mapped: List[dict] = []
    failed = 0
    failed_ids: List[str] = []

    for raw in raw_list:
        try:
            mapped.append(pinzhi_ingredient_to_unified(raw, store_id, tenant_id))
        except (KeyError, ValueError) as exc:
            failed += 1
            mid = str(raw.get("materialId") or "unknown")
            failed_ids.append(mid)
            logger.warning(
                "pinzhi_ingredient_batch_map_error",
                material_id=mid,
                tenant_id=tenant_id,
                error=str(exc),
            )

    logger.info(
        "pinzhi_ingredients_batch_mapped",
        tenant_id=tenant_id,
        store_id=store_id,
        total=len(raw_list),
        success=len(mapped),
        failed=failed,
    )
    return {
        "items": mapped,
        "total": len(raw_list),
        "success": len(mapped),
        "failed": failed,
        "failed_ids": failed_ids,
    }
