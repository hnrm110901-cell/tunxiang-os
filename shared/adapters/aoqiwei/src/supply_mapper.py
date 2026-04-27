"""
奥琦玮供应链数据映射层

将奥琦玮API原始响应字段映射为屯象OS统一类型：
  - UnifiedSupplier（供应商）
  - UnifiedPurchaseOrder（采购入库单）
  - 收货记录（配送出库单）

奥琦玮金额单位为分（fen），映射时转换为元（float）。
奥琦玮采购单状态：0=待确认, 1=已确认, 2=已入库
"""

from __future__ import annotations

import os as _os

# 引用 base 类型（根据项目实际路径）
import sys
import uuid
from typing import Any, Dict, List

import structlog

_src_dir = _os.path.dirname(__file__)
_adapters_root = _os.path.abspath(_os.path.join(_src_dir, "../../.."))
_base_types_path = _os.path.join(_adapters_root, "base", "src", "types")
if _base_types_path not in sys.path:
    sys.path.insert(0, _base_types_path)

from supplier import UnifiedPurchaseOrder, UnifiedSupplier  # noqa: E402

logger = structlog.get_logger(__name__)

# 奥琦玮采购入库单状态 → 屯象标准状态
_PURCHASE_STATUS_MAP: Dict[int, str] = {
    0: "ordered",  # 待确认
    1: "received",  # 已确认（到货）
    2: "stocked",  # 已入库
}


def aoqiwei_supplier_to_unified(raw: dict, tenant_id: str) -> UnifiedSupplier:
    """奥琦玮供应商原始数据 → UnifiedSupplier

    奥琦玮字段：
      supplierCode, supplierName, contactName, contactPhone,
      supplierAddress, supplierStatus (1=启用/0=停用), categoryList

    Args:
        raw: 奥琦玮API返回的单条供应商数据
        tenant_id: 租户ID（强制存在）

    Returns:
        UnifiedSupplier TypedDict

    Raises:
        ValueError: supplier_code 或 supplier_name 缺失时
    """
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")

    supplier_code: str = raw.get("supplierCode") or ""
    supplier_name: str = raw.get("supplierName") or ""

    if not supplier_code:
        raise ValueError(f"奥琦玮供应商缺少 supplierCode，原始数据: {raw!r}")
    if not supplier_name:
        raise ValueError(f"奥琦玮供应商缺少 supplierName，原始数据: {raw!r}")

    # supplierStatus: 1=启用, 0=停用；缺省视为启用
    raw_status = raw.get("supplierStatus")
    if raw_status is None:
        is_active = True
    else:
        try:
            is_active = int(raw_status) == 1
        except (ValueError, TypeError):
            is_active = True
            logger.warning(
                "aoqiwei_supplier_status_parse_error",
                supplier_code=supplier_code,
                raw_status=raw_status,
            )

    # categoryList: 奥琦玮可能是列表或逗号分隔字符串
    raw_categories = raw.get("categoryList") or []
    if isinstance(raw_categories, str):
        categories: List[str] = [c.strip() for c in raw_categories.split(",") if c.strip()]
    elif isinstance(raw_categories, list):
        categories = [str(c) for c in raw_categories if c]
    else:
        categories = []

    result: UnifiedSupplier = {
        "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"aoqiwei:{tenant_id}:{supplier_code}")),
        "external_id": supplier_code,
        "source": "aoqiwei",
        "name": supplier_name,
        "contact_name": raw.get("contactName") or "",
        "contact_phone": raw.get("contactPhone") or "",
        "categories": categories,
        "address": raw.get("supplierAddress") or "",
        "is_active": is_active,
        # 扩展字段（屯象非标准但有用）
        "tenant_id": tenant_id,  # type: ignore[typeddict-unknown-key]
    }

    logger.debug(
        "aoqiwei_supplier_mapped",
        supplier_code=supplier_code,
        tenant_id=tenant_id,
    )
    return result


def aoqiwei_purchase_order_to_unified(
    raw: dict,
    tenant_id: str,
    store_id: str,
) -> UnifiedPurchaseOrder:
    """奥琦玮采购入库单 → UnifiedPurchaseOrder

    奥琦玮字段：
      orderNo, depotCode, supplierCode, orderDate,
      totalAmount (单位：分), status (0/1/2),
      goodList[{goodCode, goodName, qty, unit, price(分)}]

    状态映射：
      0 → "ordered"（待确认）
      1 → "received"（已确认到货）
      2 → "stocked"（已入库）

    Args:
        raw: 奥琦玮API返回的单条采购入库单
        tenant_id: 租户ID（强制存在）
        store_id: 门店ID（屯象内部ID）

    Returns:
        UnifiedPurchaseOrder TypedDict

    Raises:
        ValueError: orderNo 缺失时
    """
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")
    if not store_id:
        raise ValueError("store_id 不能为空")

    order_no: str = raw.get("orderNo") or ""
    if not order_no:
        raise ValueError(f"奥琦玮采购单缺少 orderNo，原始数据: {raw!r}")

    # 状态映射，未知状态默认 ordered
    raw_status = raw.get("status")
    try:
        status_int = int(raw_status) if raw_status is not None else 0
    except (ValueError, TypeError):
        status_int = 0
        logger.warning(
            "aoqiwei_purchase_order_status_parse_error",
            order_no=order_no,
            raw_status=raw_status,
        )
    status: str = _PURCHASE_STATUS_MAP.get(status_int, "ordered")

    # 金额：奥琦玮单位为分，转换为元
    raw_total = raw.get("totalAmount") or 0
    try:
        total_amount_yuan: float = float(raw_total) / 100.0
    except (ValueError, TypeError):
        total_amount_yuan = 0.0
        logger.warning(
            "aoqiwei_purchase_order_amount_parse_error",
            order_no=order_no,
            raw_total=raw_total,
        )

    # 明细行映射
    items: List[Dict[str, Any]] = []
    for idx, good in enumerate(raw.get("goodList") or [], start=1):
        good_code: str = str(good.get("goodCode") or "")
        good_name: str = str(good.get("goodName") or "")
        try:
            qty = float(good.get("qty") or 0)
        except (ValueError, TypeError):
            qty = 0.0
        unit: str = str(good.get("unit") or "")
        try:
            unit_price_yuan = float(good.get("price") or 0) / 100.0
        except (ValueError, TypeError):
            unit_price_yuan = 0.0

        items.append(
            {
                "item_no": idx,
                "good_code": good_code,
                "good_name": good_name,
                "quantity": qty,
                "unit": unit,
                "unit_price": unit_price_yuan,
                "subtotal": round(qty * unit_price_yuan, 4),
            }
        )

    result: UnifiedPurchaseOrder = {
        "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"aoqiwei:{tenant_id}:{order_no}")),
        "external_id": order_no,
        "source": "aoqiwei",
        "store_id": store_id,
        "supplier_id": raw.get("supplierCode") or "",
        "order_date": raw.get("orderDate") or "",
        "total_amount": total_amount_yuan,
        "status": status,
        "items": items,
        "remark": raw.get("remark") or "",
        # 扩展字段
        "tenant_id": tenant_id,  # type: ignore[typeddict-unknown-key]
        "depot_code": raw.get("depotCode") or "",  # type: ignore[typeddict-unknown-key]
    }

    logger.debug(
        "aoqiwei_purchase_order_mapped",
        order_no=order_no,
        status=status,
        item_count=len(items),
        tenant_id=tenant_id,
    )
    return result


def aoqiwei_dispatch_to_receiving(
    raw: dict,
    tenant_id: str,
    store_id: str,
) -> dict:
    """奥琦玮配送出库单 → 屯象收货记录格式

    奥琦玮字段：
      dispatchOrderNo, shopCode, dispatchDate,
      goodList[{goodCode, goodName, qty, unit}]

    生成的收货记录兼容 receiving_service.create_receiving() 的 items 格式：
      [{ingredient_id, name, ordered_qty, received_qty, quality, unit}]

    Args:
        raw: 奥琦玮API返回的单条配送出库单
        tenant_id: 租户ID（强制存在）
        store_id: 门店ID（屯象内部ID）

    Returns:
        收货记录字典，可直接传入 receiving_service.create_receiving()

    Raises:
        ValueError: dispatchOrderNo 缺失时
    """
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")
    if not store_id:
        raise ValueError("store_id 不能为空")

    dispatch_no: str = raw.get("dispatchOrderNo") or ""
    if not dispatch_no:
        raise ValueError(f"奥琦玮配送出库单缺少 dispatchOrderNo，原始数据: {raw!r}")

    items: List[Dict[str, Any]] = []
    for good in raw.get("goodList") or []:
        good_code: str = str(good.get("goodCode") or "")
        good_name: str = str(good.get("goodName") or "")
        try:
            qty = float(good.get("qty") or 0)
        except (ValueError, TypeError):
            qty = 0.0
        unit: str = str(good.get("unit") or "")

        items.append(
            {
                # receiving_service 约定字段
                "ingredient_id": good_code,
                "name": good_name,
                "ordered_qty": qty,
                "received_qty": qty,  # 配送出库即视为实收（门店可在UI修改）
                "quality": "pass",
                "unit": unit,
                "notes": "",
            }
        )

    result = {
        "external_dispatch_no": dispatch_no,
        "source": "aoqiwei",
        "tenant_id": tenant_id,
        "store_id": store_id,
        "shop_code": raw.get("shopCode") or "",
        "dispatch_date": raw.get("dispatchDate") or "",
        "items": items,
        "item_count": len(items),
    }

    logger.debug(
        "aoqiwei_dispatch_mapped",
        dispatch_no=dispatch_no,
        item_count=len(items),
        tenant_id=tenant_id,
    )
    return result
