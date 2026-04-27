"""外卖异议工作流 API

端点概览:
  POST /api/v1/delivery/disputes              — 创建异议
  GET  /api/v1/delivery/disputes              — 异议列表
  GET  /api/v1/delivery/disputes/stats        — 异议统计
  GET  /api/v1/delivery/disputes/{dispute_id} — 异议详情
  POST /api/v1/delivery/disputes/{dispute_id}/review — 人工复核

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.delivery_dispute_service import DeliveryDisputeService

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/delivery/disputes", tags=["delivery-disputes"])


# ─── 辅助 ───


def _err(status: int, msg: str) -> None:
    raise HTTPException(
        status_code=status,
        detail={"ok": False, "error": {"message": msg}},
    )


def _svc(db: AsyncSession, tenant_id: str) -> DeliveryDisputeService:
    return DeliveryDisputeService(db=db, tenant_id=tenant_id)


# ─── 请求模型 ───


class CreateDisputeReq(BaseModel):
    store_id: str
    order_id: str
    channel: str = Field(..., pattern="^(meituan|eleme|douyin)$")
    dispute_type: str = Field(
        ...,
        pattern="^(refund|deduction|penalty|missing_item|quality|late_delivery|other)$",
    )
    disputed_amount_fen: int = Field(..., ge=0, description="争议金额(分)")
    platform_dispute_id: Optional[str] = Field(None, max_length=50)
    platform_evidence: Optional[dict] = Field(default_factory=dict)


class ReviewDisputeReq(BaseModel):
    action: str = Field(..., pattern="^(accept|reject|escalate)$")
    reviewer_id: str
    note: Optional[str] = None
    resolution_amount_fen: Optional[int] = Field(None, ge=0, description="最终结算金额(分)")
    store_evidence: Optional[dict] = None


# ─── 端点 ───


@router.post("", status_code=201)
async def create_dispute(
    req: CreateDisputeReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建异议 + 自动裁决。

    金额≤¥50自动接受，>¥50转人工复核。
    """
    try:
        svc = _svc(db, x_tenant_id)
        result = await svc.create_dispute(
            store_id=req.store_id,
            dispute_data=req.model_dump(),
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        _err(400, str(exc))
    except SQLAlchemyError:
        log.exception("delivery_dispute.create_api_error")
        _err(500, "创建异议失败，请稍后重试")
    return {"ok": False, "error": {"message": "未知错误"}}  # unreachable, satisfy type checker


@router.get("")
async def list_disputes(
    store_id: str = Query(..., description="门店ID"),
    status: Optional[str] = Query(None, description="状态筛选"),
    channel: Optional[str] = Query(None, description="渠道筛选"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询异议列表(分页)。"""
    try:
        svc = _svc(db, x_tenant_id)
        result = await svc.get_disputes(
            store_id=store_id,
            status=status,
            channel=channel,
            page=page,
            size=size,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        _err(400, str(exc))
    return {"ok": False, "error": {"message": "未知错误"}}


@router.get("/stats")
async def dispute_stats(
    store_id: str = Query(..., description="门店ID"),
    period_start: str = Query(..., description="开始日期(ISO格式)"),
    period_end: str = Query(..., description="结束日期(ISO格式)"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """异议统计: 按渠道/类型/状态汇总, 自动接受率, 平均处理时长。"""
    try:
        svc = _svc(db, x_tenant_id)
        result = await svc.get_dispute_stats(
            store_id=store_id,
            period_start=period_start,
            period_end=period_end,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        _err(400, str(exc))
    return {"ok": False, "error": {"message": "未知错误"}}


@router.get("/{dispute_id}")
async def get_dispute(
    dispute_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取异议详情。"""
    try:
        svc = _svc(db, x_tenant_id)
        result = await svc.get_dispute_detail(dispute_id)
        if not result:
            _err(404, f"异议不存在: {dispute_id}")
        return {"ok": True, "data": result}
    except ValueError as exc:
        _err(400, str(exc))
    return {"ok": False, "error": {"message": "未知错误"}}


@router.post("/{dispute_id}/review")
async def review_dispute(
    dispute_id: str,
    req: ReviewDisputeReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """人工复核: accept/reject/escalate。"""
    try:
        svc = _svc(db, x_tenant_id)
        result = await svc.review_dispute(
            dispute_id=dispute_id,
            action=req.action,
            reviewer_id=req.reviewer_id,
            note=req.note,
            resolution_amount_fen=req.resolution_amount_fen,
            store_evidence=req.store_evidence,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        _err(400, str(exc))
    except SQLAlchemyError:
        log.exception("delivery_dispute.review_api_error", dispute_id=dispute_id)
        _err(500, "复核异议失败，请稍后重试")
    return {"ok": False, "error": {"message": "未知错误"}}
