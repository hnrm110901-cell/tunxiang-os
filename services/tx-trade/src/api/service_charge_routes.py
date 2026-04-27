"""服务费管理 API — 配置/计算/模板/下发

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.service_charge import (
    calculate_service_charge,
    create_charge_template,
    get_charge_config,
    publish_template,
    set_charge_config,
)

router = APIRouter(prefix="/api/v1/service-charge", tags=["service-charge"])


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


async def _get_tenant_db(request: Request):
    tid = _get_tenant_id(request)
    async for session in get_db_with_tenant(tid):
        yield session


def _ok(data) -> dict:
    return {"ok": True, "data": data, "error": None}


# ─── 请求模型 ───


class SetChargeConfigReq(BaseModel):
    store_id: str
    config: dict = Field(..., description="收费配置，包含 mode/各参数/enabled")


class CalculateChargeReq(BaseModel):
    order_id: str
    store_id: str
    guest_count: int = Field(default=1, ge=1)
    room_type: Optional[str] = None
    duration_minutes: int = Field(default=0, ge=0)
    order_amount_fen: int = Field(default=0, ge=0)


class CreateTemplateReq(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    rules: dict


class PublishTemplateReq(BaseModel):
    template_id: str
    store_ids: list[str] = Field(..., min_length=1)


# ─── 路由 ───


@router.get("/config/{store_id}")
async def api_get_charge_config(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(_get_tenant_db),
):
    """获取门店服务费配置"""
    tenant_id = _get_tenant_id(request)
    config = await get_charge_config(store_id, tenant_id, db)
    return _ok(config)


@router.post("/config")
async def api_set_charge_config(
    body: SetChargeConfigReq,
    request: Request,
    db: AsyncSession = Depends(_get_tenant_db),
):
    """设置门店服务费配置"""
    tenant_id = _get_tenant_id(request)
    result = await set_charge_config(body.store_id, body.config, tenant_id, db)
    return _ok(result)


@router.post("/calculate")
async def api_calculate_charge(
    body: CalculateChargeReq,
    request: Request,
    db: AsyncSession = Depends(_get_tenant_db),
):
    """计算订单服务费"""
    tenant_id = _get_tenant_id(request)
    result = await calculate_service_charge(
        order_id=body.order_id,
        store_id=body.store_id,
        tenant_id=tenant_id,
        db=db,
        guest_count=body.guest_count,
        room_type=body.room_type,
        duration_minutes=body.duration_minutes,
        order_amount_fen=body.order_amount_fen,
    )
    return _ok(result)


@router.post("/template")
async def api_create_template(
    body: CreateTemplateReq,
    request: Request,
    db: AsyncSession = Depends(_get_tenant_db),
):
    """创建总部服务费模板"""
    tenant_id = _get_tenant_id(request)
    result = await create_charge_template(body.name, body.rules, tenant_id, db)
    return _ok(result)


@router.post("/template/publish")
async def api_publish_template(
    body: PublishTemplateReq,
    request: Request,
    db: AsyncSession = Depends(_get_tenant_db),
):
    """下发模板到门店"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await publish_template(body.template_id, body.store_ids, tenant_id, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return _ok(result)
