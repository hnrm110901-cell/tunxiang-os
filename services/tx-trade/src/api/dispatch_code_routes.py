"""外卖出餐码 API — 生成、扫码确认、查询、待确认列表

# ROUTER REGISTRATION:
# from .api.dispatch_code_routes import router as dispatch_code_router
# app.include_router(dispatch_code_router, prefix="/api/v1/dispatch-codes")
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.dispatch_code_service import DispatchCodeService

router = APIRouter(tags=["dispatch-codes"])


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


# ---------------------------------------------------------------------------
# 请求 / 响应模型
# ---------------------------------------------------------------------------


class GenerateReq(BaseModel):
    order_id: str = Field(..., description="订单 UUID")
    platform: str = Field(default="unknown", description="meituan / eleme / douyin / dianping")


class GenerateResp(BaseModel):
    code: str
    qr_data: str  # 供前端渲染二维码的数据字符串


class ScanReq(BaseModel):
    code: str = Field(..., description="6 位出餐码")
    operator_id: str = Field(..., description="操作员 UUID")


# ---------------------------------------------------------------------------
# 端点 1: 生成出餐码
# ---------------------------------------------------------------------------


@router.post("/generate")
async def api_generate(
    req: GenerateReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """为外卖订单生成出餐码（幂等）。

    Returns:
        {ok, data: {code, qr_data}}
    """
    tenant_id = _get_tenant_id(request)
    try:
        dc = await DispatchCodeService.generate(
            order_id=req.order_id,
            tenant_id=tenant_id,
            db=db,
            platform=req.platform,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    # qr_data: 打包员扫码时传回的唯一标识（格式：txdc://<code>）
    qr_data = f"txdc://{dc.code}"

    return {
        "ok": True,
        "data": {
            "code": dc.code,
            "qr_data": qr_data,
            "order_id": dc.order_id,
            "platform": dc.platform,
            "confirmed": dc.confirmed,
            "created_at": dc.created_at.isoformat(),
        },
    }


# ---------------------------------------------------------------------------
# 端点 2: 扫码确认出餐
# ---------------------------------------------------------------------------


@router.post("/scan")
async def api_scan(
    req: ScanReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """打包员扫码确认出餐，触发平台回调。

    Returns:
        {ok, data: ScanResult}
    """
    tenant_id = _get_tenant_id(request)

    # 支持 txdc:// 前缀（直接扫 QR）
    code = req.code
    if code.startswith("txdc://"):
        code = code[len("txdc://") :]

    result = await DispatchCodeService.confirm_by_scan(
        code=code,
        operator_id=req.operator_id,
        tenant_id=tenant_id,
        db=db,
    )

    if not result.success:
        return {
            "ok": False,
            "data": None,
            "error": {"message": result.error},
        }

    return {
        "ok": True,
        "data": {
            "success": result.success,
            "order_id": result.order_id,
            "platform": result.platform,
            "already_confirmed": result.already_confirmed,
        },
    }


# ---------------------------------------------------------------------------
# 端点 3: 查询订单出餐码状态
# ---------------------------------------------------------------------------


@router.get("/order/{order_id}")
async def api_get_by_order(
    order_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """查询订单出餐码状态。

    Returns:
        {ok, data: DispatchCode | null}
    """
    tenant_id = _get_tenant_id(request)
    dc = await DispatchCodeService.get_by_order(
        order_id=order_id,
        tenant_id=tenant_id,
        db=db,
    )

    if dc is None:
        return {"ok": True, "data": None}

    return {
        "ok": True,
        "data": {
            "id": dc.id,
            "order_id": dc.order_id,
            "code": dc.code,
            "platform": dc.platform,
            "confirmed": dc.confirmed,
            "confirmed_at": dc.confirmed_at.isoformat() if dc.confirmed_at else None,
            "operator_id": dc.operator_id,
            "created_at": dc.created_at.isoformat(),
        },
    }


# ---------------------------------------------------------------------------
# 端点 4: 待确认出餐码列表
# ---------------------------------------------------------------------------


@router.get("/pending/{store_id}")
async def api_list_pending(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """返回当前门店未确认的外卖出餐码列表（待打包出餐订单）。

    Args:
        store_id: 门店 UUID（当前内存实现以租户范围过滤，生产 ORM 可加 store_id 索引）

    Returns:
        {ok, data: {items: [...], total: int}}
    """
    tenant_id = _get_tenant_id(request)
    pending = await DispatchCodeService.list_pending(
        tenant_id=tenant_id,
        store_id=store_id,
        db=db,
    )

    items = [
        {
            "id": dc.id,
            "order_id": dc.order_id,
            "code": dc.code,
            "platform": dc.platform,
            "confirmed": dc.confirmed,
            "created_at": dc.created_at.isoformat(),
        }
        for dc in pending
    ]

    return {
        "ok": True,
        "data": {
            "items": items,
            "total": len(items),
            "store_id": store_id,
        },
    }
