"""cert_routes — 供应商证件管理 API（PRD-01 食安合规 / Tier 1）

接口列表：
  GET    /api/v1/supply/suppliers/{supplier_id}/certificates/expiring
         即将过期证件列表（默认 within_days=30）
  POST   /api/v1/supply/certificates/{cert_id}/renew
         续证（更新 expire_date + attachment_url，无需手动解锁）

  PR-01C 追加（管理后台 CRUD）：
  GET    /api/v1/supply/suppliers/{supplier_id}/certificates
         列表（支持 status 过滤 + 分页）
  GET    /api/v1/supply/certificates/{cert_id}
         单条详情
  POST   /api/v1/supply/suppliers/{supplier_id}/certificates
         新建证件
  DELETE /api/v1/supply/certificates/{cert_id}
         软删证件（is_deleted=TRUE）
"""

from __future__ import annotations

from datetime import date
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db as _get_db

from ..services.cert_service import (
    count_certificates,
    create_certificate,
    get_certificate_by_id,
    list_certificates,
    list_expiring,
    renew_cert,
    soft_delete_certificate,
)

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/supply",
    tags=["supplier-certificates"],
)


# ─── 请求/响应模型 ─────────────────────────────────────────────────────────────


class RenewCertRequest(BaseModel):
    new_expire_date: date = Field(..., description="新到期日（续证后 expire_date）")
    new_attachment_url: Optional[str] = Field(None, description="新证件附件 URL（可选）")


class CreateCertRequest(BaseModel):
    cert_type: str = Field(..., min_length=1, max_length=48, description="证件类型（如 food_permit/business_license）")
    cert_number: str = Field(..., min_length=1, max_length=128, description="证件编号")
    expire_date: date = Field(..., description="到期日")
    issuer: Optional[str] = Field(default=None, max_length=128, description="发证机关")
    warning_days: Optional[List[int]] = Field(default=None, description="预警阈值列表（None 用 DB 默认 [30,15,7]）")
    auto_block_on_expire: bool = Field(default=True, description="到期是否自动阻断收货（默认 TRUE）")
    attachment_url: Optional[str] = Field(default=None, max_length=1024, description="附件 URL")


# ─── 路由 ─────────────────────────────────────────────────────────────────────


@router.get("/suppliers/{supplier_id}/certificates/expiring")
async def get_expiring_certificates(
    supplier_id: str,
    within_days: int = Query(30, ge=1, le=365, description="预警天数窗口（默认 30 天）"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """列出供应商即将过期证件。

    GIVEN 供应商 supplier_id
    WHEN  请求 within_days 天内到期证件列表
    THEN  返回按到期日升序排列的证件列表

    食药监告警场景：巡店督导每日查看 7 天内到期证件，提前联系供应商续证。
    """
    items = await list_expiring(
        db=db,
        tenant_id=x_tenant_id,
        within_days=within_days,
    )
    # 按 supplier_id 过滤（list_expiring 返回 tenant 维度所有证件）
    filtered = [item for item in items if item.get("supplier_id") == supplier_id]
    return {"ok": True, "data": {"items": filtered, "total": len(filtered)}}


@router.post("/certificates/{cert_id}/renew")
async def renew_certificate(
    cert_id: str,
    body: RenewCertRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """续证接口。

    GIVEN 证件 cert_id 已过期
    WHEN  提交新 expire_date + 新附件 URL
    THEN  expire_date 更新 → is_supplier_blocked 下次查询自动返回 False
    AND   无需手动解锁（续证 = 自动恢复收货能力）

    食药监场景：供应商提供新许可证，督导上传附件并更新到期日。
    """
    try:
        result = await renew_cert(
            db=db,
            tenant_id=x_tenant_id,
            cert_id=cert_id,
            new_expire_date=body.new_expire_date,
            new_attachment_url=body.new_attachment_url,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail={"code": "CERT_NOT_FOUND", "message": str(e)}) from e


# ─── PR-01C 管理后台 CRUD ──────────────────────────────────────────────────────


@router.get("/suppliers/{supplier_id}/certificates")
async def list_supplier_certificates(
    supplier_id: str,
    status: str = Query("all", pattern="^(all|active|expiring_30d|expired)$", description="状态过滤"),
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(20, ge=1, le=100, description="每页数量"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """列出供应商所有证件（支持 status 过滤 + 分页）.

    管理后台场景：督导查看某供应商所有证件 / 监管查阅过期证件全量列表.
    """
    items = await list_certificates(
        db=db,
        tenant_id=x_tenant_id,
        supplier_id=supplier_id,
        status=status,
        limit=size,
        offset=(page - 1) * size,
    )
    total = await count_certificates(
        db=db,
        tenant_id=x_tenant_id,
        supplier_id=supplier_id,
        status=status,
    )
    return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}


@router.get("/certificates/{cert_id}")
async def get_certificate(
    cert_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """查单条证件详情（含 supplier_name）."""
    item = await get_certificate_by_id(db=db, tenant_id=x_tenant_id, cert_id=cert_id)
    if item is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "CERT_NOT_FOUND", "message": f"cert_id={cert_id} 不存在或已删除"},
        )
    return {"ok": True, "data": item}


@router.post("/suppliers/{supplier_id}/certificates")
async def create_supplier_certificate(
    supplier_id: str,
    body: CreateCertRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """新建证件.

    管理后台场景：录入新供应商的营业执照 / 食品许可证.
    expire_date 允许过去日期（补录已过期证件场景：立即阻断收货，正常业务）.
    """
    try:
        item = await create_certificate(
            db=db,
            tenant_id=x_tenant_id,
            supplier_id=supplier_id,
            cert_type=body.cert_type,
            cert_number=body.cert_number,
            expire_date=body.expire_date,
            issuer=body.issuer,
            warning_days=body.warning_days,
            auto_block_on_expire=body.auto_block_on_expire,
            attachment_url=body.attachment_url,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail={"code": "CERT_VALIDATION", "message": str(e)},
        ) from e
    return {"ok": True, "data": item}


@router.delete("/certificates/{cert_id}")
async def delete_certificate(
    cert_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """软删证件（is_deleted=TRUE）.

    管理后台场景：误录入的证件删除 / 已废止证件从列表下架.
    软删后 is_supplier_blocked 不再考虑该证件（自动放行收货）.
    """
    deleted = await soft_delete_certificate(db=db, tenant_id=x_tenant_id, cert_id=cert_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={"code": "CERT_NOT_FOUND", "message": f"cert_id={cert_id} 不存在或已删除"},
        )
    return {"ok": True, "data": {"cert_id": cert_id, "is_deleted": True}}
