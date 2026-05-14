"""delivery_window_routes — 供应商配送时间窗 API（PRD-05 / Tier 1 食安）

接口列表：
  GET    /api/v1/supply/suppliers/{supplier_id}/delivery-windows
         列出某 supplier 的配送时间窗（默认 only_active=False 看全部含草稿/已删）
  POST   /api/v1/supply/suppliers/{supplier_id}/delivery-windows
         新建配送时间窗（草稿态 approved_by=NULL）
  POST   /api/v1/supply/delivery-windows/{window_id}/approve
         二级审批（不允许 self-approve）
  DELETE /api/v1/supply/delivery-windows/{window_id}
         软删配送时间窗
  POST   /api/v1/supply/receiving/check-delivery-window
         签收前合规性检查（收货员前置查询）
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db as _get_db

from ..models.supplier_delivery_window import (
    ApproveRequest,
    CheckWindowRequest,
    DeliveryWindowCreate,
)
from ..services.delivery_window_service import (
    approve_delivery_window,
    check_delivery_window,
    create_delivery_window,
    list_delivery_windows,
    soft_delete_delivery_window,
)

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/supply",
    tags=["supplier-delivery-windows"],
)


@router.get("/suppliers/{supplier_id}/delivery-windows")
async def list_supplier_delivery_windows(
    supplier_id: str,
    store_id: str | None = Query(None, description="可选 store_id 过滤"),
    only_active: bool = Query(False, description="只看已审批生效（默认 False — 含草稿/已删）"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """列出某 supplier 的配送时间窗。

    only_active=False（管理后台默认）：全部含草稿 + 已审批，不含 is_deleted=TRUE
    only_active=True：仅返回当前生效（已审批 + 未删除）— check 路径用。
    """
    items = await list_delivery_windows(
        db=db,
        tenant_id=x_tenant_id,
        supplier_id=supplier_id,
        store_id=store_id,
        only_active=only_active,
    )
    return {"ok": True, "data": {"items": items, "total": len(items)}}


@router.post("/suppliers/{supplier_id}/delivery-windows")
async def create_supplier_delivery_window(
    supplier_id: str,
    body: DeliveryWindowCreate,
    x_user_id: str = Header(..., alias="X-User-ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """新建配送时间窗（草稿态）。

    管理后台场景：门店店长为生鲜供应商 X 配置 04:00-07:00 配送窗 + grace 15min。
    创建后 approved_by=NULL（草稿态），必须独立审批人调 /approve 才生效参与 check。
    """
    # supplier_id 必须与 path 一致（body 内的 supplier_id 走 path 校验）
    if str(body.supplier_id) != str(supplier_id):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "DELIVERY_WINDOW_SUPPLIER_MISMATCH",
                "message": "body.supplier_id 与 path supplier_id 不一致",
            },
        )
    try:
        item = await create_delivery_window(
            db=db,
            tenant_id=x_tenant_id,
            supplier_id=supplier_id,
            store_id=body.store_id,
            earliest_time=body.earliest_time,
            latest_time=body.latest_time,
            created_by=x_user_id,
            weekday_mask=body.weekday_mask,
            grace_minutes=body.grace_minutes,
            auto_reject_on_late=body.auto_reject_on_late,
            notes=body.notes,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail={"code": "DELIVERY_WINDOW_VALIDATION", "message": str(e)},
        ) from e
    return {"ok": True, "data": item}


@router.post("/delivery-windows/{window_id}/approve")
async def approve_supplier_delivery_window(
    window_id: str,
    body: ApproveRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """二级审批接口。

    管理后台场景：店长录入配送窗 → 区域督导独立签字审批。
    必须 approver_id != created_by（防 self-approve），重复审批返回 422。
    """
    try:
        item = await approve_delivery_window(
            db=db,
            tenant_id=x_tenant_id,
            window_id=window_id,
            approver_id=body.approver_id,
        )
    except ValueError as e:
        msg = str(e)
        if "不存在" in msg:
            raise HTTPException(
                status_code=404,
                detail={"code": "DELIVERY_WINDOW_NOT_FOUND", "message": msg},
            ) from e
        raise HTTPException(
            status_code=422,
            detail={"code": "DELIVERY_WINDOW_APPROVE_INVALID", "message": msg},
        ) from e
    return {"ok": True, "data": item}


@router.delete("/delivery-windows/{window_id}")
async def delete_supplier_delivery_window(
    window_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """软删配送时间窗。

    软删后 check_delivery_window 不再使用此条配置（fallback within=True 不阻塞收货）。
    """
    deleted = await soft_delete_delivery_window(
        db=db, tenant_id=x_tenant_id, window_id=window_id
    )
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "DELIVERY_WINDOW_NOT_FOUND",
                "message": f"window_id={window_id} 不存在或已删除",
            },
        )
    return {"ok": True, "data": {"window_id": window_id, "is_deleted": True}}


@router.post("/receiving/check-delivery-window")
async def check_supplier_delivery_window(
    body: CheckWindowRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """收货员签收前合规性检查（前置 UI 查询用）。

    场景：商米 POS 收货页扫码到货后，前端调本接口预查询配送是否合规
    → UI 高亮 violation_kind/violation_minutes，让收货员决定接受 / 拒收。
    主流程的违约日志由 complete_receiving 在签收完成时自动写。
    """
    result = await check_delivery_window(
        db=db,
        tenant_id=x_tenant_id,
        supplier_id=body.supplier_id,
        store_id=body.store_id,
        signed_at=body.signed_at,
    )
    return {
        "ok": True,
        "data": {
            "within_window": result["within_window"],
            "window_id": result["window_id"],
            "weekday_matched": result["weekday_matched"],
            "scheduled_earliest": (
                result["scheduled_earliest"].isoformat()
                if result["scheduled_earliest"]
                else None
            ),
            "scheduled_latest": (
                result["scheduled_latest"].isoformat()
                if result["scheduled_latest"]
                else None
            ),
            "grace_minutes": result["grace_minutes"],
            "violation_minutes": result["violation_minutes"],
            "violation_kind": result["violation_kind"],
        },
    }


__all__ = ["router"]
