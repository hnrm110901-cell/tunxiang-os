"""马来西亚 PDPA 数据保护 API 端点（Phase 2 Sprint 2.4）

PDPA = Personal Data Protection Act 2010

端点：
  - POST /api/v1/pdpa/request              提交数据主体权利请求
  - GET  /api/v1/pdpa/request/{request_id}  查询请求状态
  - POST /api/v1/pdpa/request/{request_id}/approve   审批请求
  - POST /api/v1/pdpa/request/{request_id}/reject    拒绝请求
  - POST /api/v1/pdpa/consent               记录客户同意/撤回同意
  - GET  /api/v1/pdpa/consent/{customer_id} 查询客户同意历史
  - GET  /api/v1/pdpa/retention/report      数据留存合规报告

所有端点要求 X-Tenant-ID header。
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.pdpa_service import PDPAService

router = APIRouter(prefix="/api/v1/pdpa", tags=["pdpa"])


# ── DI ──────────────────────────────────────────────────────────


async def get_pdpa_service(
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> PDPAService:
    return PDPAService(db=db, tenant_id=x_tenant_id)


# ── 请求/响应模型 ─────────────────────────────────────────────


class PDPARequestCreate(BaseModel):
    """提交数据主体权利请求"""

    customer_id: str = Field(..., description="客户 ID")
    request_type: str = Field(
        ...,
        description="请求类型: access(查阅)/correction(更正)/deletion(删除)/portability(可携带)",
        pattern=r"^(access|correction|deletion|portability)$",
    )
    request_data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="请求附加数据（correction 需提供 corrections 字典: {\"corrections\": {\"field\": \"value\"}}）",
    )
    notes: Optional[str] = Field(default=None, max_length=500, description="备注")


class PDPARequestResponse(BaseModel):
    """数据主体权利请求响应"""

    request_id: str
    tenant_id: str
    customer_id: str
    request_type: str
    status: str
    request_data: Optional[Dict[str, Any]] = None
    response_data: Optional[Dict[str, Any]] = None
    requested_by: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class PDPAConsentCreate(BaseModel):
    """记录同意/撤回同意"""

    customer_id: str = Field(..., description="客户 ID")
    consent_type: str = Field(
        ...,
        description="同意类型: marketing_sms/marketing_email/data_processing/cross_border/third_party",
        pattern=r"^(marketing_sms|marketing_email|data_processing|cross_border|third_party)$",
    )
    granted: bool = Field(..., description="True=同意, False=撤回同意")
    ip_address: Optional[str] = Field(default=None, max_length=45, description="客户端 IP 地址")
    user_agent: Optional[str] = Field(default=None, max_length=500, description="User-Agent")


class PDPAConsentResponse(BaseModel):
    """同意记录响应"""

    consent_log_id: str
    customer_id: str
    consent_type: str
    granted: bool
    created_at: str


class RetentionReportResponse(BaseModel):
    """数据留存报告"""

    candidate_count: int
    candidates: list[Dict[str, Any]]
    retention_policy_days: int
    regulation: str
    note: str


# ── 端点 ──────────────────────────────────────────────────────────


@router.post("/request", response_model=PDPARequestResponse)
async def submit_pdpa_request(
    req: PDPARequestCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_requested_by: str = Header("system", alias="X-Requested-By"),
    service: PDPAService = Depends(get_pdpa_service),
):
    """提交 PDPA 数据主体权利请求

    四种请求类型：
      - access:     查阅权，自动返回解密后的客户全量数据画像
      - correction: 更正权，需提供 request_data.corrections 指明更新字段
      - deletion:   删除权（匿名化），需人工审批后执行
      - portability: 可携带权，自动返回 JSON 格式客户数据导出
    """
    try:
        result = await service.handle_data_subject_request(
            customer_id=req.customer_id,
            request_type=req.request_type,
            requested_by=x_requested_by,
            notes=req.notes,
            request_data=req.request_data,
        )
        return PDPARequestResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/request/{request_id}", response_model=PDPARequestResponse)
async def get_pdpa_request_status(
    request_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    service: PDPAService = Depends(get_pdpa_service),
):
    """查询 PDPA 请求当前状态"""
    result = await service.get_request(request_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"PDPA 请求 {request_id} 不存在")
    return PDPARequestResponse(**result)


@router.post("/request/{request_id}/approve", response_model=PDPARequestResponse)
async def approve_pdpa_request(
    request_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    service: PDPAService = Depends(get_pdpa_service),
):
    """审批通过 PDPA 请求并执行

    对 deletion 请求：执行匿名化（擦除 PII，保留统计）。
    对 correction 请求：应用字段更正。
    """
    try:
        result = await service.process_request(
            request_id=request_id,
            action="approve",
        )
        return PDPARequestResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class RejectRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500, description="拒绝原因")


@router.post("/request/{request_id}/reject", response_model=PDPARequestResponse)
async def reject_pdpa_request(
    request_id: str,
    req: RejectRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    service: PDPAService = Depends(get_pdpa_service),
):
    """拒绝 PDPA 请求"""
    try:
        result = await service.process_request(
            request_id=request_id,
            action="reject",
            rejection_reason=req.reason,
        )
        return PDPARequestResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/requests")
async def list_pdpa_requests(
    customer_id: Optional[str] = Query(None, description="按客户 ID 过滤"),
    status: Optional[str] = Query(None, description="按状态过滤: pending/processing/completed/rejected"),
    request_type: Optional[str] = Query(None, description="按类型过滤: access/correction/deletion/portability"),
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(20, ge=1, le=100, description="每页条数"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    service: PDPAService = Depends(get_pdpa_service),
):
    """分页查询 PDPA 请求列表"""
    try:
        result = await service.list_requests(
            customer_id=customer_id,
            status=status,
            request_type=request_type,
            page=page,
            size=size,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/consent", response_model=PDPAConsentResponse)
async def record_consent(
    req: PDPAConsentCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    service: PDPAService = Depends(get_pdpa_service),
):
    """记录 PDPA 客户同意/撤回同意

    PDPA 要求处理个人数据前必须获得明确同意（opt-in）。
    记录的同意类型：
      - marketing_sms:    SMS 营销
      - marketing_email:  邮件营销
      - data_processing:  个人数据处理
      - cross_border:     跨境数据传输
      - third_party:      第三方共享
    """
    try:
        result = await service.log_consent(
            customer_id=req.customer_id,
            consent_type=req.consent_type,
            granted=req.granted,
            ip_address=req.ip_address,
            user_agent=req.user_agent,
        )
        return PDPAConsentResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/consent/{customer_id}")
async def get_consent_history(
    customer_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    service: PDPAService = Depends(get_pdpa_service),
):
    """查询客户 PDPA 同意历史（按时间倒序）"""
    try:
        result = await service.get_consent_history(customer_id=customer_id)
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/retention/report")
async def retention_report(
    retention_days: int = Query(365, ge=30, le=3650, description="无活动天数阈值"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    service: PDPAService = Depends(get_pdpa_service),
):
    """数据留存合规报告

    PDPA 存储限制原则：个人数据在完成业务目的后应在合理期限内销毁或匿名化。
    默认检查超过 365 天无消费记录的客户。
    返回的候选数据已脱敏，需人工审核确认后通过 deletion 请求处理。
    """
    try:
        result = await service.check_data_retention(retention_days=retention_days)
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
