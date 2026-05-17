"""certificate_type_routes — 资质证件类型字典 API（PRD-12 / Phase 3 W13 / Tier 1 邻接）

接口列表（5 endpoints）:
  POST   /api/v1/supply/cert-types                       创建证件类型
  PUT    /api/v1/supply/cert-types/{id}                  更新证件类型
  DELETE /api/v1/supply/cert-types/{id}                  软删除证件类型
  GET    /api/v1/supply/cert-types                        分页列表（?page=1&size=20&include_deleted=false）
  POST   /api/v1/supply/cert-types/initialize-defaults   写入 5 类默认证件（幂等）

错误码映射：
  - ValueError("CERT_TYPE_NOT_FOUND")    → HTTP 404
  - ValueError("CERT_TYPE_NAME_EXISTS")  → HTTP 409
  - 其他 ValueError                      → HTTP 422
"""

from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db as _get_db

from ..services.certificate_type_service import (
    create_certificate_type,
    initialize_defaults,
    list_certificate_types,
    soft_delete_certificate_type,
    update_certificate_type,
)

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/supply/cert-types",
    tags=["certificate-types"],
)


# ─── Pydantic Schemas ─────────────────────────────────────────────────────────


class CertificateTypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100, description="证件类型名称")
    applicable_supplier_kinds: list[str] = Field(
        default=["all"],
        description='适用供应商类型，如 ["all"] / ["seafood","meat"]',
    )
    validity_period_days: Optional[int] = Field(
        default=None, ge=1, description="有效期天数（None = 长期有效）"
    )
    is_required: bool = Field(default=True, description="是否为必须证件")


class CertificateTypeUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    applicable_supplier_kinds: Optional[list[str]] = None
    validity_period_days: Optional[int] = Field(default=None, ge=1)
    is_required: Optional[bool] = None


class CertificateTypeOut(BaseModel):
    id: str
    name: str
    applicable_supplier_kinds: list[str]
    validity_period_days: Optional[int]
    is_required: bool
    is_deleted: bool
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)


# ─── 错误码映射 ────────────────────────────────────────────────────────────────


def _map_value_error(exc: ValueError) -> HTTPException:
    """统一 ValueError → HTTPException 映射。"""
    msg = str(exc)
    if msg == "CERT_TYPE_NOT_FOUND":
        return HTTPException(
            status_code=404,
            detail={"code": "CERT_TYPE_NOT_FOUND", "message": "证件类型不存在"},
        )
    if msg == "CERT_TYPE_NAME_EXISTS":
        return HTTPException(
            status_code=409,
            detail={"code": "CERT_TYPE_NAME_EXISTS", "message": "同租户内已存在同名证件类型"},
        )
    return HTTPException(
        status_code=422,
        detail={"code": "INVALID_REQUEST", "message": msg},
    )


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/initialize-defaults", summary="写入默认证件类型（幂等）")
async def post_initialize_defaults(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """写入 5 类系统标准证件类型（ON CONFLICT DO NOTHING）。

    支持重复调用（幂等），返回 created/skipped 统计。
    """
    result = await initialize_defaults(tenant_id=x_tenant_id, db=db)
    logger.info(
        "cert_types_initialize_defaults",
        tenant_id=x_tenant_id,
        created=result["created"],
        skipped=result["skipped"],
    )
    return {"ok": True, "data": result}


@router.get("", summary="分页列表")
async def get_cert_types(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    include_deleted: bool = Query(False),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """列出当前租户的证件类型（默认过滤软删除）。"""
    result = await list_certificate_types(
        tenant_id=x_tenant_id,
        page=page,
        size=size,
        include_deleted=include_deleted,
        db=db,
    )
    return {"ok": True, "data": result}


@router.post("", summary="创建证件类型")
async def post_cert_type(
    body: CertificateTypeCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """创建新证件类型。同租户同名（未软删除）返回 409。"""
    try:
        cert_type = await create_certificate_type(
            tenant_id=x_tenant_id,
            name=body.name,
            applicable_supplier_kinds=body.applicable_supplier_kinds,
            validity_period_days=body.validity_period_days,
            is_required=body.is_required,
            db=db,
        )
    except ValueError as exc:
        raise _map_value_error(exc) from exc

    return {"ok": True, "data": cert_type}


@router.put("/{cert_type_id}", summary="更新证件类型")
async def put_cert_type(
    cert_type_id: str,
    body: CertificateTypeUpdate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """更新证件类型字段（仅传入的字段被更新）。not found 返回 404。"""
    try:
        cert_type = await update_certificate_type(
            cert_type_id,
            tenant_id=x_tenant_id,
            name=body.name,
            applicable_supplier_kinds=body.applicable_supplier_kinds,
            validity_period_days=body.validity_period_days,
            is_required=body.is_required,
            fields_set=body.model_fields_set,
            db=db,
        )
    except ValueError as exc:
        raise _map_value_error(exc) from exc

    return {"ok": True, "data": cert_type}


@router.delete("/{cert_type_id}", summary="软删除证件类型")
async def delete_cert_type(
    cert_type_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """软删除证件类型（is_deleted=True）。

    注意：历史 supplier_certificates 证件记录不受影响（松耦合字符串匹配设计）。
    """
    try:
        await soft_delete_certificate_type(
            cert_type_id,
            tenant_id=x_tenant_id,
            db=db,
        )
    except ValueError as exc:
        raise _map_value_error(exc) from exc

    return {"ok": True, "data": {"deleted": True, "id": cert_type_id}}
