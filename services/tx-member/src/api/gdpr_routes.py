"""GDPR 合规 API — 7 个端点（v103）

端点：
1. POST /api/v1/member/gdpr/requests          提交权利申请
2. GET  /api/v1/member/gdpr/requests          查询请求列表
3. GET  /api/v1/member/gdpr/requests/{id}     请求详情
4. POST /api/v1/member/gdpr/requests/{id}/review   审核（批准/拒绝）
5. POST /api/v1/member/gdpr/requests/{id}/execute  执行匿名化（erasure）
6. GET  /api/v1/member/gdpr/export/{customer_id}   数据导出（portability）
7. GET  /api/v1/member/gdpr/pending-count     待处理请求数量（运营看板）
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.gdpr_service import REQUEST_TYPES, GDPRService

router = APIRouter(prefix="/api/v1/member/gdpr", tags=["gdpr_compliance"])


# ─── DB 依赖 ──────────────────────────────────────────────────────────────────

async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ─── 请求模型 ─────────────────────────────────────────────────────────────────

class CreateRequestModel(BaseModel):
    customer_id: str = Field(..., description="客户 ID")
    request_type: str = Field(..., description="请求类型: erasure/portability/restriction")
    requested_by: Optional[str] = Field(None, description="申请人（客户姓名/联系方式）")
    note: Optional[str] = Field(None, description="附加说明")

    @field_validator("request_type")
    @classmethod
    def check_type(cls, v: str) -> str:
        if v not in REQUEST_TYPES:
            raise ValueError(f"request_type 必须是: {', '.join(REQUEST_TYPES)}")
        return v


class ReviewRequestModel(BaseModel):
    approved: bool = Field(..., description="True=批准进入执行流程，False=拒绝")
    reviewed_by: str = Field(..., description="审核人员工 ID")
    rejection_reason: Optional[str] = Field(None, description="拒绝原因（approved=False 时填写）")


class ExecuteErasureModel(BaseModel):
    executed_by: str = Field(..., description="执行人员工 ID")


# ─── 1. 提交权利申请 ──────────────────────────────────────────────────────────

@router.post("/requests", summary="提交 GDPR 权利申请", status_code=201)
async def create_gdpr_request(
    body: CreateRequestModel,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """提交数据主体权利申请。

    - erasure: 被遗忘权（匿名化个人信息）
    - portability: 数据可携权（导出个人数据）
    - restriction: 限制处理权（标记暂停数据使用）
    """
    svc = GDPRService(db, x_tenant_id)
    try:
        req = await svc.create_request(
            customer_id=body.customer_id,
            request_type=body.request_type,
            requested_by=body.requested_by,
            note=body.note,
        )
        await db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "data": req}


# ─── 2. 查询请求列表 ──────────────────────────────────────────────────────────

@router.get("/requests", summary="GDPR 请求列表")
async def list_gdpr_requests(
    customer_id: Optional[str] = Query(None, description="按客户过滤"),
    status: Optional[str] = Query(None, description="状态: pending/reviewing/executed/rejected"),
    request_type: Optional[str] = Query(None, description="类型: erasure/portability/restriction"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """查询 GDPR 权利请求列表。"""
    svc = GDPRService(db, x_tenant_id)
    items = await svc.list_requests(
        customer_id=customer_id,
        status=status,
        request_type=request_type,
    )
    return {"ok": True, "data": {"items": items, "total": len(items)}}


# ─── 3. 请求详情 ──────────────────────────────────────────────────────────────

@router.get("/requests/{request_id}", summary="GDPR 请求详情")
async def get_gdpr_request(
    request_id: str = Path(..., description="请求 ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """获取单条 GDPR 请求详情，包含处理日志。"""
    svc = GDPRService(db, x_tenant_id)
    req = await svc.get_request(request_id)
    if not req:
        raise HTTPException(status_code=404, detail=f"GDPR 请求不存在: {request_id}")
    return {"ok": True, "data": req}


# ─── 4. 审核请求 ──────────────────────────────────────────────────────────────

@router.post("/requests/{request_id}/review", summary="审核 GDPR 请求")
async def review_gdpr_request(
    request_id: str = Path(..., description="请求 ID"),
    body: ReviewRequestModel = ...,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """人工审核 GDPR 请求。

    - approved=True：进入 reviewing 状态，等待执行
    - approved=False：拒绝，需填写 rejection_reason
    """
    svc = GDPRService(db, x_tenant_id)
    try:
        req = await svc.review_request(
            request_id=request_id,
            approved=body.approved,
            reviewed_by=body.reviewed_by,
            rejection_reason=body.rejection_reason,
        )
        await db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "data": req}


# ─── 5. 执行匿名化 ────────────────────────────────────────────────────────────

@router.post("/requests/{request_id}/execute", summary="执行被遗忘权匿名化")
async def execute_erasure(
    request_id: str = Path(..., description="请求 ID"),
    body: ExecuteErasureModel = ...,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """执行数据匿名化。

    脱敏字段：name/phone/email/wechat_openid/birth_date/gender/avatar_url
    保留字段：order history（仅保留金额/时间，去除个人标识）
    合规说明：符合 GDPR Art.17 & GB/T 35273-2020
    """
    svc = GDPRService(db, x_tenant_id)
    try:
        req = await svc.execute_erasure(
            request_id=request_id,
            executed_by=body.executed_by,
        )
        await db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "data": req}


# ─── 6. 数据导出 ──────────────────────────────────────────────────────────────

@router.get("/export/{customer_id}", summary="导出客户个人数据（数据可携权）")
async def export_customer_data(
    customer_id: str = Path(..., description="客户 ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """导出客户全部个人数据（GDPR Art.20 数据可携权）。

    返回：基本信息 + 消费历史（最近 1000 笔）
    注意：调用前应已有审批通过的 portability 请求。
    """
    svc = GDPRService(db, x_tenant_id)
    try:
        data = await svc.export_customer_data(customer_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True, "data": data}


# ─── 7. 待处理数量 ────────────────────────────────────────────────────────────

@router.get("/pending-count", summary="待处理 GDPR 请求数（运营看板）")
async def get_pending_count(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """返回各状态的 GDPR 请求数量，供运营看板使用。"""
    from sqlalchemy import text as sa_text


    result = await db.execute(
        sa_text("""
            SELECT status, COUNT(*) AS cnt
            FROM gdpr_requests
            WHERE tenant_id = :tid
            GROUP BY status
        """),
        {"tid": x_tenant_id},
    )
    counts = {r.status: int(r.cnt) for r in result.fetchall()}
    return {
        "ok": True,
        "data": {
            "pending": counts.get("pending", 0),
            "reviewing": counts.get("reviewing", 0),
            "executed": counts.get("executed", 0),
            "rejected": counts.get("rejected", 0),
            "total_active": counts.get("pending", 0) + counts.get("reviewing", 0),
        },
    }
