"""沽清全链路同步 API 路由"""
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..services.kds_soldout_sync import mark_soldout, restore_soldout, get_active_soldout

router = APIRouter(prefix="/api/v1/kds/soldout", tags=["kds-soldout"])


class MarkSoldoutRequest(BaseModel):
    store_id: str
    dish_id: str
    dish_name: str
    reason: Optional[str] = None
    reported_by: Optional[str] = None


class RestoreSoldoutRequest(BaseModel):
    store_id: str
    dish_id: str


@router.post("")
async def api_mark_soldout(
    body: MarkSoldoutRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """标记菜品沽清，同步到 POS 菜单、小程序、所有KDS屏幕。"""
    try:
        result = await mark_soldout(
            tenant_id=x_tenant_id,
            store_id=body.store_id,
            dish_id=body.dish_id,
            dish_name=body.dish_name,
            reason=body.reason,
            reported_by=body.reported_by,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("")
async def api_restore_soldout(
    body: RestoreSoldoutRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """恢复沽清（菜品重新可售），全链路同步恢复。"""
    try:
        result = await restore_soldout(
            tenant_id=x_tenant_id,
            store_id=body.store_id,
            dish_id=body.dish_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("")
async def api_get_active_soldout(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """查询当前门店所有沽清菜品列表。"""
    items = await get_active_soldout(
        tenant_id=x_tenant_id,
        store_id=store_id,
        db=db,
    )
    return {"ok": True, "data": {"items": items, "total": len(items)}}
