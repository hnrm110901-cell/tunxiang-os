"""配送签收凭证 API（TASK-4，v369）

8 个端点：
  POST /api/v1/supply/delivery/{id}/sign                       — 提交电子签名
  POST /api/v1/supply/delivery/{id}/damage                      — 登记损坏
  POST /api/v1/supply/delivery/damage/{id}/attachment           — 上传附件
  GET  /api/v1/supply/delivery/{id}/receipt                     — 查签收单
  GET  /api/v1/supply/delivery/{id}/proof                       — 完整凭证包
  GET  /api/v1/supply/delivery/damage/pending                   — 待处理损坏
  POST /api/v1/supply/delivery/damage/{id}/resolve              — 处理损坏
  GET  /api/v1/supply/delivery/damage/stats                     — 损坏统计

统一响应：{"ok": bool, "data": {}, "error": {}}
"""

from __future__ import annotations

from datetime import date as _date
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db as _get_db

from ..models.delivery_proof import (
    AttachmentIn,
    DamageRecordIn,
    EntityType,
    ResolveDamageIn,
    SignatureSubmitIn,
)
from ..services import delivery_proof_service as svc
from ..services.delivery_proof_service import DeliveryProofError

router = APIRouter(prefix="/api/v1/supply/delivery", tags=["delivery-proof"])


# ──────────────────────────────────────────────────────────────────────
# 1. 签收
# ──────────────────────────────────────────────────────────────────────


@router.post("/{delivery_id}/sign")
async def sign_delivery(
    delivery_id: str,
    body: SignatureSubmitIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    try:
        result = await svc.submit_signature(
            delivery_id=delivery_id,
            tenant_id=x_tenant_id,
            db=db,
            signer_name=body.signer_name,
            signature_base64=body.signature_base64,
            signer_role=body.signer_role,
            signer_phone=body.signer_phone,
            gps_lat=body.gps_lat,
            gps_lng=body.gps_lng,
            device_info=body.device_info.model_dump() if body.device_info else None,
            notes=body.notes,
        )
        await db.commit()
        return {"ok": True, "data": result, "error": {}}
    except DeliveryProofError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail={"message": str(exc)})


# ──────────────────────────────────────────────────────────────────────
# 2. 登记损坏
# ──────────────────────────────────────────────────────────────────────


@router.post("/{delivery_id}/damage")
async def report_damage(
    delivery_id: str,
    body: DamageRecordIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    try:
        result = await svc.record_damage(
            delivery_id=delivery_id,
            tenant_id=x_tenant_id,
            db=db,
            damage_type=body.damage_type,
            damaged_qty=body.damaged_qty,
            item_id=str(body.item_id) if body.item_id else None,
            ingredient_id=str(body.ingredient_id) if body.ingredient_id else None,
            batch_no=body.batch_no,
            unit_cost_fen=body.unit_cost_fen,
            description=body.description,
            severity=body.severity,
            reported_by=str(body.reported_by) if body.reported_by else None,
        )
        await db.commit()
        return {"ok": True, "data": result, "error": {}}
    except DeliveryProofError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail={"message": str(exc)})


# ──────────────────────────────────────────────────────────────────────
# 3. 附件上传（统一通过 base64；entity_type 可指向 RECEIPT 或 DAMAGE）
# ──────────────────────────────────────────────────────────────────────


@router.post("/damage/{damage_id}/attachment")
async def attach_to_damage(
    damage_id: str,
    body: AttachmentIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """对损坏记录上传附件（照片/视频）。

    路由参数 damage_id 限定 entity_id；entity_type 必须由 body 指定为 DAMAGE
    （或对签收单上传时改为 RECEIPT，但语义不推荐）。
    """
    try:
        result = await svc.attach_file(
            tenant_id=x_tenant_id,
            db=db,
            entity_type=body.entity_type,
            entity_id=damage_id,
            file_base64=body.file_base64,
            file_name=body.file_name,
            captured_at=body.captured_at,
            gps_lat=body.gps_lat,
            gps_lng=body.gps_lng,
            uploaded_by=str(body.uploaded_by) if body.uploaded_by else None,
        )
        await db.commit()
        return {"ok": True, "data": result, "error": {}}
    except DeliveryProofError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail={"message": str(exc)})


# ──────────────────────────────────────────────────────────────────────
# 4. 查签收单
# ──────────────────────────────────────────────────────────────────────


@router.get("/{delivery_id}/receipt")
async def get_receipt(
    delivery_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    try:
        result = await svc.get_receipt(
            delivery_id=delivery_id,
            tenant_id=x_tenant_id,
            db=db,
        )
    except DeliveryProofError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)})
    if result is None:
        raise HTTPException(
            status_code=404,
            detail={"message": f"receipt not found for delivery {delivery_id}"},
        )
    return {"ok": True, "data": result, "error": {}}


# ──────────────────────────────────────────────────────────────────────
# 5. 完整凭证包
# ──────────────────────────────────────────────────────────────────────


@router.get("/{delivery_id}/proof")
async def get_proof(
    delivery_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    try:
        result = await svc.get_complete_proof(
            delivery_id=delivery_id,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": result, "error": {}}
    except DeliveryProofError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)})


# ──────────────────────────────────────────────────────────────────────
# 6. 待处理损坏列表
# ──────────────────────────────────────────────────────────────────────


@router.get("/damage/pending")
async def list_pending(
    store_id: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    try:
        result = await svc.list_pending_damages(
            tenant_id=x_tenant_id,
            db=db,
            store_id=store_id,
            severity=severity,
            limit=size,
            offset=(page - 1) * size,
        )
        return {"ok": True, "data": result, "error": {}}
    except DeliveryProofError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)})


# ──────────────────────────────────────────────────────────────────────
# 7. 处理损坏
# ──────────────────────────────────────────────────────────────────────


@router.post("/damage/{damage_id}/resolve")
async def resolve(
    damage_id: str,
    body: ResolveDamageIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    try:
        result = await svc.resolve_damage(
            damage_id=damage_id,
            tenant_id=x_tenant_id,
            db=db,
            action=body.action,
            comment=body.comment,
            resolve_action_code=body.resolve_action_code,
            resolved_by=str(body.resolved_by) if body.resolved_by else None,
        )
        await db.commit()
        return {"ok": True, "data": result, "error": {}}
    except DeliveryProofError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail={"message": str(exc)})


# ──────────────────────────────────────────────────────────────────────
# 8. 损坏统计
# ──────────────────────────────────────────────────────────────────────


@router.get("/damage/stats")
async def damage_stats(
    from_: Optional[_date] = Query(None, alias="from"),
    to: Optional[_date] = Query(None),
    store_id: Optional[str] = Query(None),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    try:
        result = await svc.get_damage_stats(
            tenant_id=x_tenant_id,
            db=db,
            from_date=from_,
            to_date=to,
            store_id=store_id,
        )
        return {"ok": True, "data": result, "error": {}}
    except DeliveryProofError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)})


# 让 EntityType 可被路由消费方导入（避免循环 import）
__all__ = ["router", "EntityType"]
