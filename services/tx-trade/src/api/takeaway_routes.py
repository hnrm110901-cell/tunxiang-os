"""外卖管理中心 API — 多平台统一管理

10 个端点：订单同步、接单/拒单、沽清、配送、仪表盘、对账、菜品管理、自动接单。
所有接口需要 X-Tenant-ID header。
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.takeaway_manager import (
    accept_order,
    get_platform_reconciliation,
    get_takeaway_dashboard,
    manage_online_menu,
    reject_order,
    set_auto_accept_rules,
    sync_eleme_orders,
    sync_meituan_orders,
    sync_stockout_to_platforms,
    update_delivery_status,
)

router = APIRouter(prefix="/api/v1/takeaway", tags=["takeaway"])


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


# ─── 请求模型 ───


class SyncOrdersReq(BaseModel):
    store_id: str


class AcceptOrderReq(BaseModel):
    platform: str = Field(..., description="meituan / eleme")
    order_id: str


class RejectOrderReq(BaseModel):
    platform: str = Field(..., description="meituan / eleme")
    order_id: str
    reason: str


class StockoutSyncReq(BaseModel):
    store_id: str
    sold_out_ids: list[str]


class DeliveryStatusReq(BaseModel):
    order_id: str
    status: str = Field(..., description="pending/confirmed/preparing/delivering/completed/cancelled")


class MenuActionItem(BaseModel):
    food_id: str
    action: str = Field(..., description="on_sale / sold_out")


class ManageMenuReq(BaseModel):
    store_id: str
    platform: str = Field(..., description="meituan / eleme")
    actions: list[MenuActionItem]


class AutoAcceptRulesReq(BaseModel):
    store_id: str
    rules: dict = Field(
        ...,
        description="mode: all/daytime/off, daytime_start, daytime_end, max_order_amount_fen, platforms",
    )


# ─── 端点 1: 同步美团订单 ───


@router.post("/sync/meituan")
async def api_sync_meituan_orders(
    req: SyncOrdersReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """拉取美团新订单"""
    tenant_id = _get_tenant_id(request)
    result = await sync_meituan_orders(
        store_id=req.store_id,
        tenant_id=tenant_id,
        db=db,
    )
    return {"ok": True, "data": result}


# ─── 端点 2: 同步饿了么订单 ───


@router.post("/sync/eleme")
async def api_sync_eleme_orders(
    req: SyncOrdersReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """拉取饿了么新订单"""
    tenant_id = _get_tenant_id(request)
    result = await sync_eleme_orders(
        store_id=req.store_id,
        tenant_id=tenant_id,
        db=db,
    )
    return {"ok": True, "data": result}


# ─── 端点 3: 接单 ───


@router.post("/accept")
async def api_accept_order(
    req: AcceptOrderReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """接单（自动/手动）"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await accept_order(
            platform=req.platform,
            order_id=req.order_id,
            tenant_id=tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ─── 端点 4: 拒单 ───


@router.post("/reject")
async def api_reject_order(
    req: RejectOrderReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """拒单"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await reject_order(
            platform=req.platform,
            order_id=req.order_id,
            reason=req.reason,
            tenant_id=tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ─── 端点 5: 沽清同步 ───


@router.post("/stockout/sync")
async def api_sync_stockout(
    req: StockoutSyncReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """沽清同步到外卖平台"""
    tenant_id = _get_tenant_id(request)
    result = await sync_stockout_to_platforms(
        store_id=req.store_id,
        sold_out_ids=req.sold_out_ids,
        tenant_id=tenant_id,
        db=db,
    )
    return {"ok": True, "data": result}


# ─── 端点 6: 配送状态更新 ───


@router.put("/delivery/status")
async def api_update_delivery_status(
    req: DeliveryStatusReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """配送状态更新"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await update_delivery_status(
            order_id=req.order_id,
            status=req.status,
            tenant_id=tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ─── 端点 7: 外卖仪表盘 ───


@router.get("/dashboard/{store_id}")
async def api_get_dashboard(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """获取外卖仪表盘（待接/制作中/配送中/已完成）"""
    tenant_id = _get_tenant_id(request)
    result = await get_takeaway_dashboard(
        store_id=store_id,
        tenant_id=tenant_id,
        db=db,
    )
    return {"ok": True, "data": result}


# ─── 端点 8: 平台对账 ───


@router.get("/reconciliation/{store_id}/{platform}/{date}")
async def api_get_reconciliation(
    store_id: str,
    platform: str,
    date: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """平台对账"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await get_platform_reconciliation(
            store_id=store_id,
            platform=platform,
            date=date,
            tenant_id=tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ─── 端点 9: 外卖菜品上下架 ───


@router.post("/menu/manage")
async def api_manage_menu(
    req: ManageMenuReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """外卖菜品上下架"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await manage_online_menu(
            store_id=req.store_id,
            platform=req.platform,
            actions=[a.model_dump() for a in req.actions],
            tenant_id=tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ─── 端点 10: 自动接单规则 ───


@router.post("/auto-accept/rules")
async def api_set_auto_accept_rules(
    req: AutoAcceptRulesReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """设置自动接单规则"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await set_auto_accept_rules(
            store_id=req.store_id,
            rules=req.rules,
            tenant_id=tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
