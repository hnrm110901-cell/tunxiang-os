"""GDPR 合规 API — 11 个端点（v202 扩展）

端点：
1.  POST /api/v1/member/gdpr/requests                           提交权利申请
2.  GET  /api/v1/member/gdpr/requests                           查询请求列表
3.  GET  /api/v1/member/gdpr/requests/{id}                      请求详情
4.  POST /api/v1/member/gdpr/requests/{id}/review               审核（批准/拒绝）
5.  POST /api/v1/member/gdpr/requests/{id}/execute              执行匿名化（erasure）
6.  GET  /api/v1/member/gdpr/export/{customer_id}               数据导出（portability）
7.  GET  /api/v1/member/gdpr/pending-count                      待处理请求数量（运营看板）
8.  POST /api/v1/member/gdpr/requests/{id}/process              统一处理端点（approve/reject）
9.  GET  /api/v1/member/gdpr/retention-policies                 列出数据保留期策略
10. PUT  /api/v1/member/gdpr/retention-policies/{category}      更新某类数据保留期
11. GET  /api/v1/member/gdpr/export/{customer_id}               生成顾客数据导出（兼容旧路径）
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


# ─── 8. 统一处理端点（approve/reject）— v202 新增 ─────────────────────────────

import uuid as _uuid_mod
import structlog as _structlog
from datetime import datetime, timezone
from sqlalchemy import text as _sa_text

_log = _structlog.get_logger(__name__)


class ProcessRequestModel(BaseModel):
    action: str = Field(..., description="操作: approve 或 reject")
    operator_id: str = Field(..., description="操作人员工 ID")
    reason: Optional[str] = Field(None, description="拒绝原因（action=reject 时必填）")

    @field_validator("action")
    @classmethod
    def check_action(cls, v: str) -> str:
        if v not in ("approve", "reject"):
            raise ValueError("action 必须是 approve 或 reject")
        return v


@router.post("/requests/{request_id}/process", summary="处理 GDPR 请求（approve/reject）")
async def process_gdpr_request(
    request_id: str = Path(..., description="请求 ID"),
    body: ProcessRequestModel = ...,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """统一处理端点：批准或拒绝一条 GDPR 请求。

    - action=approve：将请求置为 processing 状态，等待执行
    - action=reject：拒绝请求，需提供 reason
    """
    svc = GDPRService(db, x_tenant_id)
    try:
        req = await svc.review_request(
            request_id=request_id,
            approved=(body.action == "approve"),
            reviewed_by=body.operator_id,
            rejection_reason=body.reason,
        )
        await db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _log.info(
        "gdpr_request_processed",
        request_id=request_id,
        action=body.action,
        operator_id=body.operator_id,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": req}


# ─── 9. 列出数据保留期策略 — v202 新增 ────────────────────────────────────────

@router.get("/retention-policies", summary="列出数据保留期策略")
async def list_retention_policies(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """列出当前租户所有数据类别的保留期配置。

    数据类别：orders / members / logs / payments
    """
    result = await db.execute(
        _sa_text("""
            SELECT id, tenant_id, data_category, retention_days,
                   anonymize_after_days, legal_basis, is_active,
                   created_at, updated_at
            FROM data_retention_policies
            WHERE tenant_id = :tid AND is_active = TRUE
            ORDER BY data_category
        """),
        {"tid": x_tenant_id},
    )
    rows = result.fetchall()
    items = [
        {
            "id": str(r.id),
            "data_category": r.data_category,
            "retention_days": r.retention_days,
            "anonymize_after_days": r.anonymize_after_days,
            "legal_basis": r.legal_basis,
            "is_active": r.is_active,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]
    return {"ok": True, "data": {"items": items, "total": len(items)}}


# ─── 10. 更新数据保留期策略 — v202 新增 ───────────────────────────────────────

_VALID_CATEGORIES = frozenset(["orders", "members", "logs", "payments"])


class RetentionPolicyUpdateModel(BaseModel):
    retention_days: int = Field(..., ge=1, le=3650, description="保留天数（1-3650）")
    anonymize_after_days: Optional[int] = Field(None, ge=1, description="匿名化天数（可选）")
    legal_basis: Optional[str] = Field(None, max_length=100, description="GDPR 合法依据")
    is_active: bool = Field(True, description="是否启用")


@router.put(
    "/retention-policies/{category}",
    summary="更新某类数据保留期策略",
)
async def update_retention_policy(
    category: str = Path(..., description="数据类别: orders/members/logs/payments"),
    body: RetentionPolicyUpdateModel = ...,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """更新指定数据类别的保留期策略（不存在则自动创建）。

    合规说明：变更保留期策略须有合法依据（GDPR Art.5(1)(e)）。
    """
    if category not in _VALID_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"category 必须是: {', '.join(sorted(_VALID_CATEGORIES))}",
        )

    now = datetime.now(timezone.utc)
    # UPSERT：若存在则更新，否则插入
    await db.execute(
        _sa_text("""
            INSERT INTO data_retention_policies
                (id, tenant_id, data_category, retention_days,
                 anonymize_after_days, legal_basis, is_active,
                 created_at, updated_at)
            VALUES
                (gen_random_uuid(), :tid, :cat, :days,
                 :anon_days, :basis, :active,
                 :now, :now)
            ON CONFLICT (tenant_id, data_category)
            DO UPDATE SET
                retention_days        = EXCLUDED.retention_days,
                anonymize_after_days  = EXCLUDED.anonymize_after_days,
                legal_basis           = EXCLUDED.legal_basis,
                is_active             = EXCLUDED.is_active,
                updated_at            = EXCLUDED.updated_at
        """),
        {
            "tid": x_tenant_id,
            "cat": category,
            "days": body.retention_days,
            "anon_days": body.anonymize_after_days,
            "basis": body.legal_basis,
            "active": body.is_active,
            "now": now,
        },
    )
    await db.commit()
    _log.info(
        "retention_policy_updated",
        tenant_id=x_tenant_id,
        category=category,
        retention_days=body.retention_days,
    )
    return {
        "ok": True,
        "data": {
            "tenant_id": x_tenant_id,
            "data_category": category,
            "retention_days": body.retention_days,
            "anonymize_after_days": body.anonymize_after_days,
            "legal_basis": body.legal_basis,
            "is_active": body.is_active,
            "updated_at": now.isoformat(),
        },
    }
