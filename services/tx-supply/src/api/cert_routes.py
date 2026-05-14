"""cert_routes — 供应商证件管理 API（PRD-01 食安合规 / Tier 1）

接口列表：
  GET  /api/v1/supply/suppliers/{supplier_id}/certificates/expiring
       即将过期证件列表（默认 within_days=30）
  POST /api/v1/supply/certificates/{cert_id}/renew
       续证（更新 expire_date + attachment_url，无需手动解锁）
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db as _get_db

from ..services.cert_service import list_expiring, renew_cert

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/supply",
    tags=["supplier-certificates"],
)


# ─── 请求/响应模型 ─────────────────────────────────────────────────────────────


class RenewCertRequest(BaseModel):
    new_expire_date: date = Field(..., description="新到期日（续证后 expire_date）")
    new_attachment_url: Optional[str] = Field(None, description="新证件附件 URL（可选）")


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
