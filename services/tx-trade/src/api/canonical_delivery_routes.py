"""Sprint E1 — 外卖 canonical schema ingest API

端点：
  POST /api/v1/trade/delivery/canonical/ingest
    入参：{platform, raw_payload, ingested_by?}
    出参：{canonical_order_id, canonical_order_no, status, transformation_errors}
    幂等：同 payload_sha256 重复推送 → 返回原 order（不新建）

  GET  /api/v1/trade/delivery/canonical/{id}
    出参：CanonicalDeliveryOrder + items

  GET  /api/v1/trade/delivery/canonical
    查询参数：platform / store_id / status / date_from / date_to / page / size
    出参：分页列表
"""
from __future__ import annotations

import logging
import secrets
from datetime import date as date_cls
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.adapters.delivery_canonical import (
    CanonicalDeliveryOrder,
    TransformationError,
    list_supported_platforms,
    transform,
)
from shared.ontology.src.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/v1/trade/delivery/canonical",
    tags=["trade-delivery-canonical"],
)


# ── 请求模型 ─────────────────────────────────────────────────────


class IngestRequest(BaseModel):
    platform: str = Field(
        ..., description="meituan|eleme|douyin|xiaohongshu|wechat"
    )
    raw_payload: dict = Field(..., min_length=1)
    ingested_by: str = Field(
        default="webhook",
        description="webhook|manual|backfill|replay",
        max_length=100,
    )
    store_id: Optional[str] = Field(default=None, description="强制指定 store_id")


# ── 端点 ────────────────────────────────────────────────────────


@router.post("/ingest", response_model=dict)
async def ingest_canonical(
    req: IngestRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """把平台原始 payload 转换为 canonical 并持久化（幂等）"""
    tenant_uuid = _parse_uuid(x_tenant_id, "X-Tenant-ID")

    if req.platform not in list_supported_platforms():
        raise HTTPException(
            status_code=400,
            detail=f"platform 未注册 transformer: {req.platform!r}，"
            f"支持 {list_supported_platforms()}",
        )

    # 1. 转换
    try:
        order: CanonicalDeliveryOrder = transform(
            req.platform, req.raw_payload, tenant_id=str(tenant_uuid)
        )
    except TransformationError as exc:
        logger.warning(
            "canonical_transform_failed",
            extra={"platform": req.platform, "error": str(exc)},
        )
        raise HTTPException(
            status_code=422, detail=f"transformation 失败: {exc}"
        ) from exc

    # 2. 生成 canonical_order_no（若 transformer 未填）
    if not order.canonical_order_no:
        order.canonical_order_no = _generate_canonical_no(order.placed_at)
    if req.store_id:
        order.store_id = req.store_id
    order.ingested_by = req.ingested_by

    # 3. 持久化（幂等）
    try:
        analysis_id, was_new = await _upsert_canonical_order(
            db, tenant_id=x_tenant_id, order=order
        )
    except SQLAlchemyError as exc:
        logger.exception("canonical_upsert_failed")
        raise HTTPException(
            status_code=500, detail=f"持久化失败: {exc}"
        ) from exc

    return {
        "ok": True,
        "data": {
            "canonical_order_id": analysis_id,
            "canonical_order_no": order.canonical_order_no,
            "platform": order.platform,
            "status": order.status,
            "was_new": was_new,
            "transformation_errors": order.transformation_errors,
            "item_count": len(order.items),
        },
    }


@router.get("/{canonical_order_id}", response_model=dict)
async def get_canonical_order(
    canonical_order_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取单个 canonical 订单（含 items）"""
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(canonical_order_id, "canonical_order_id")

    try:
        row = await db.execute(
            text("""
                SELECT * FROM canonical_delivery_orders
                WHERE id = CAST(:id AS uuid)
                  AND tenant_id = CAST(:tenant_id AS uuid)
                  AND is_deleted = false
            """),
            {"id": canonical_order_id, "tenant_id": x_tenant_id},
        )
        order = row.mappings().first()
        if not order:
            raise HTTPException(status_code=404, detail="canonical 订单不存在")

        items_row = await db.execute(
            text("""
                SELECT * FROM canonical_delivery_items
                WHERE order_id = CAST(:id AS uuid)
                  AND is_deleted = false
                ORDER BY line_no
            """),
            {"id": canonical_order_id},
        )
        items = [dict(r) for r in items_row.mappings()]
    except SQLAlchemyError as exc:
        logger.exception("canonical_get_failed")
        raise HTTPException(
            status_code=500, detail=f"查询失败: {exc}"
        ) from exc

    return {
        "ok": True,
        "data": {
            "order": dict(order),
            "items": items,
            "item_count": len(items),
        },
    }


@router.get("", response_model=dict)
async def list_canonical_orders(
    platform: Optional[str] = None,
    store_id: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[date_cls] = None,
    date_to: Optional[date_cls] = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """分页查询 canonical 订单"""
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    if store_id:
        _parse_uuid(store_id, "store_id")

    conditions = [
        "tenant_id = CAST(:tenant_id AS uuid)",
        "is_deleted = false",
    ]
    params: dict[str, Any] = {"tenant_id": x_tenant_id}
    if platform:
        conditions.append("platform = :platform")
        params["platform"] = platform
    if store_id:
        conditions.append("store_id = CAST(:store_id AS uuid)")
        params["store_id"] = store_id
    if status:
        conditions.append("status = :status")
        params["status"] = status
    if date_from:
        conditions.append("placed_at >= :date_from")
        params["date_from"] = date_from
    if date_to:
        conditions.append("placed_at <= :date_to")
        params["date_to"] = date_to

    where = " AND ".join(conditions)
    offset = (page - 1) * size

    try:
        count_row = await db.execute(
            text(f"SELECT COUNT(*) AS total FROM canonical_delivery_orders WHERE {where}"),
            params,
        )
        total = count_row.scalar() or 0

        list_params = {**params, "limit": size, "offset": offset}
        rows = await db.execute(
            text(f"""
                SELECT id, canonical_order_no, platform, platform_order_id,
                       status, order_type, placed_at,
                       gross_amount_fen, paid_amount_fen, net_amount_fen,
                       customer_phone_masked, store_id
                FROM canonical_delivery_orders
                WHERE {where}
                ORDER BY placed_at DESC
                LIMIT :limit OFFSET :offset
            """),
            list_params,
        )
        items = [dict(r) for r in rows.mappings()]
    except SQLAlchemyError as exc:
        logger.exception("canonical_list_failed")
        raise HTTPException(
            status_code=500, detail=f"查询失败: {exc}"
        ) from exc

    return {
        "ok": True,
        "data": {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
        },
    }


@router.get("/meta/platforms", response_model=dict)
async def supported_platforms() -> dict:
    """返回当前已注册的 transformer 列表（用于前端 dropdown）"""
    return {
        "ok": True,
        "data": {"platforms": list_supported_platforms()},
    }


# ── 辅助 ─────────────────────────────────────────────────────────


async def _upsert_canonical_order(
    db: AsyncSession,
    *,
    tenant_id: str,
    order: CanonicalDeliveryOrder,
) -> tuple[str, bool]:
    """幂等 UPSERT：同 (tenant, platform, platform_order_id) 已存在则更新。

    返回 (canonical_order_id, was_new)
    """
    params = order.to_insert_params()
    params["tenant_id"] = tenant_id

    # 先尝试 INSERT；冲突则读现有 id
    row = await db.execute(
        text("""
            INSERT INTO canonical_delivery_orders (
                tenant_id, canonical_order_no, platform, platform_order_id,
                platform_sub_type, store_id, brand_id, order_type, status,
                platform_status_raw,
                customer_name, customer_phone_masked, customer_address,
                customer_address_hash,
                gross_amount_fen, discount_amount_fen, platform_commission_fen,
                platform_subsidy_fen, delivery_fee_fen, delivery_cost_fen,
                packaging_fee_fen, tax_fen, tip_fen, paid_amount_fen, net_amount_fen,
                placed_at, accepted_at, dispatched_at, delivered_at, completed_at,
                cancelled_at, expected_delivery_at,
                raw_payload, payload_sha256, platform_metadata,
                transformation_errors, canonical_version, ingested_by
            ) VALUES (
                CAST(:tenant_id AS uuid), :canonical_order_no, :platform, :platform_order_id,
                :platform_sub_type, CAST(:store_id AS uuid), CAST(:brand_id AS uuid),
                :order_type, :status, :platform_status_raw,
                :customer_name, :customer_phone_masked, :customer_address,
                :customer_address_hash,
                :gross_amount_fen, :discount_amount_fen, :platform_commission_fen,
                :platform_subsidy_fen, :delivery_fee_fen, :delivery_cost_fen,
                :packaging_fee_fen, :tax_fen, :tip_fen, :paid_amount_fen, :net_amount_fen,
                :placed_at, :accepted_at, :dispatched_at, :delivered_at, :completed_at,
                :cancelled_at, :expected_delivery_at,
                CAST(:raw_payload AS jsonb), :payload_sha256,
                CAST(:platform_metadata AS jsonb),
                CAST(:transformation_errors AS jsonb),
                :canonical_version, :ingested_by
            )
            ON CONFLICT (tenant_id, platform, platform_order_id)
              WHERE is_deleted = false
            DO UPDATE SET
                status = EXCLUDED.status,
                platform_status_raw = EXCLUDED.platform_status_raw,
                accepted_at = COALESCE(EXCLUDED.accepted_at, canonical_delivery_orders.accepted_at),
                dispatched_at = COALESCE(EXCLUDED.dispatched_at, canonical_delivery_orders.dispatched_at),
                delivered_at = COALESCE(EXCLUDED.delivered_at, canonical_delivery_orders.delivered_at),
                completed_at = COALESCE(EXCLUDED.completed_at, canonical_delivery_orders.completed_at),
                cancelled_at = COALESCE(EXCLUDED.cancelled_at, canonical_delivery_orders.cancelled_at),
                raw_payload = EXCLUDED.raw_payload,
                payload_sha256 = EXCLUDED.payload_sha256,
                platform_metadata = EXCLUDED.platform_metadata,
                transformation_errors = EXCLUDED.transformation_errors,
                updated_at = NOW()
            RETURNING id, (xmax = 0) AS was_new
        """),
        params,
    )
    result = row.mappings().first()
    canonical_id = str(result["id"])
    was_new = bool(result["was_new"])

    # 若 was_new 新建才插入 items；重复推送只更新 order 主体（items 由首次写入为准）
    if was_new and order.items:
        for item in order.items:
            item_params = item.to_dict()
            item_params["tenant_id"] = tenant_id
            item_params["order_id"] = canonical_id
            # dataclass 里的 modifiers 是 list，写入时转 JSON 字符串
            import json as _json
            item_params["modifiers"] = _json.dumps(
                item_params.get("modifiers") or [], ensure_ascii=False
            )
            await db.execute(
                text("""
                    INSERT INTO canonical_delivery_items (
                        tenant_id, order_id, platform_sku_id, internal_dish_id,
                        dish_name_platform, dish_name_canonical,
                        quantity, unit_price_fen, subtotal_fen,
                        discount_amount_fen, total_fen, modifiers, notes, line_no
                    ) VALUES (
                        CAST(:tenant_id AS uuid), CAST(:order_id AS uuid),
                        :platform_sku_id, CAST(:internal_dish_id AS uuid),
                        :dish_name_platform, :dish_name_canonical,
                        :quantity, :unit_price_fen, :subtotal_fen,
                        :discount_amount_fen, :total_fen, CAST(:modifiers AS jsonb),
                        :notes, :line_no
                    )
                """),
                item_params,
            )

    await db.commit()
    return canonical_id, was_new


def _generate_canonical_no(placed_at: datetime) -> str:
    """生成 canonical_order_no: CNL + YYYYMMDD + 8 位随机 hex"""
    if placed_at.tzinfo is None:
        placed_at = placed_at.replace(tzinfo=timezone.utc)
    date_part = placed_at.strftime("%Y%m%d")
    suffix = secrets.token_hex(4).upper()
    return f"CNL{date_part}{suffix}"


def _parse_uuid(value: str, field_name: str) -> UUID:
    try:
        return UUID(value)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=400, detail=f"{field_name} 非法 UUID: {value!r}"
        ) from exc
