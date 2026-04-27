"""GDPR 个人信息保护合规 API

POST /api/v1/gdpr/data-request                    创建数据主体请求（查看/导出/删除/更正）
GET  /api/v1/gdpr/data-request/{request_id}        查询请求状态
POST /api/v1/gdpr/anonymize/{customer_id}          匿名化客户数据
GET  /api/v1/gdpr/audit-log                        GDPR操作审计日志
POST /api/v1/gdpr/consent                          记录用户同意
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Header, HTTPException, Query

from .models.gdpr import (
    AnonymizeCustomerIn,
    CreateDataRequestIn,
    RecordConsentIn,
)
from .response import ok, paginated
from .services.gdpr_service import GDPRService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/gdpr", tags=["gdpr"])

_service = GDPRService()


# ── 数据主体请求 ─────────────────────────────────────────────────


@router.post("/data-request")
async def create_data_request(
    body: CreateDataRequestIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """创建数据主体请求（GDPR Article 15-17）

    支持的 request_type:
    - access: 查看个人数据（Article 15）
    - export: 导出个人数据（Article 20 数据可携带权）
    - delete: 删除/匿名化（Article 17 被遗忘权）
    - rectify: 更正个人数据（Article 16）
    """
    logger.info(
        "gdpr_data_request_create",
        tenant_id=x_tenant_id,
        customer_id=str(body.customer_id),
        request_type=body.request_type.value,
    )
    result = await _service.create_data_request(
        tenant_id=x_tenant_id,
        customer_id=str(body.customer_id),
        request_type=body.request_type,
        reason=body.reason,
    )
    return ok(result.model_dump(mode="json"), status_code=201)


@router.get("/data-request/{request_id}")
async def get_data_request(
    request_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """查询数据主体请求状态"""
    result = _service.get_data_request(request_id=request_id, tenant_id=x_tenant_id)
    if result is None:
        raise HTTPException(status_code=404, detail="data request not found")
    return ok(result.model_dump(mode="json"))


# ── 匿名化 ──────────────────────────────────────────────────────


@router.post("/anonymize/{customer_id}")
async def anonymize_customer(
    customer_id: str,
    body: AnonymizeCustomerIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """匿名化客户数据（手机号→hash，姓名→"已删除用户"，地址→清空）"""
    logger.info(
        "gdpr_anonymize_request",
        tenant_id=x_tenant_id,
        customer_id=customer_id,
        reason=body.reason,
    )
    result = await _service.anonymize_customer(
        tenant_id=x_tenant_id,
        customer_id=customer_id,
        reason=body.reason,
    )
    return ok(result)


# ── 审计日志 ─────────────────────────────────────────────────────


@router.get("/audit-log")
async def get_audit_log(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    customer_id: str | None = Query(default=None),
    action: str | None = Query(default=None),
):
    """查询 GDPR 操作审计日志（分页）"""
    items, total = _service.get_audit_log(
        tenant_id=x_tenant_id,
        page=page,
        size=size,
        customer_id=customer_id,
        action=action,
    )
    return paginated(
        items=[item.model_dump(mode="json") for item in items],
        total=total,
        page=page,
        size=size,
    )


# ── 同意管理 ─────────────────────────────────────────────────────


@router.post("/consent")
async def record_consent(
    body: RecordConsentIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """记录用户同意/撤销同意"""
    logger.info(
        "gdpr_consent_record",
        tenant_id=x_tenant_id,
        customer_id=str(body.customer_id),
        consent_type=body.consent_type,
        granted=body.granted,
    )
    result = _service.record_consent(
        tenant_id=x_tenant_id,
        customer_id=str(body.customer_id),
        consent_type=body.consent_type,
        granted=body.granted,
        source=body.source,
    )
    return ok(result.model_dump(mode="json"), status_code=201)
