"""
审批流 API 路由

负责审批通过/驳回/转交/路由规则管理。
共6个端点，覆盖费用审批节点流转与路由配置。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from src.models.expense_enums import ApprovalAction

try:
    from src.services.approval_engine_service import ApprovalEngineService

    _approval_svc = ApprovalEngineService()
except ImportError:
    _approval_svc = None  # type: ignore[assignment]

router = APIRouter()
log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 依赖注入
# ---------------------------------------------------------------------------


async def get_tenant_id(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> UUID:
    try:
        return UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的租户ID格式")


async def get_current_user(x_user_id: str = Header(..., alias="X-User-ID")) -> UUID:
    try:
        return UUID(x_user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的用户ID格式")


def _get_approval_service() -> "ApprovalEngineService":
    if _approval_svc is None:
        raise HTTPException(status_code=503, detail="审批引擎服务暂不可用，请稍后重试")
    return _approval_svc


# ---------------------------------------------------------------------------
# Pydantic Schema
# ---------------------------------------------------------------------------


class ApprovalRequest(BaseModel):
    comment: Optional[str] = Field(None, description="审批意见（可选）")


class RejectRequest(BaseModel):
    comment: str = Field(..., min_length=5, description="驳回原因（必填，至少5个字）")


class TransferRequest(BaseModel):
    transfer_to_id: UUID = Field(..., description="转交目标审批人ID")
    comment: Optional[str] = Field(None, description="转交说明（可选）")


class PaginatedResponse(BaseModel):
    data: List[Any]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# 端点实现
# ---------------------------------------------------------------------------


@router.post("/applications/{application_id}/approve")
async def approve_application(
    application_id: UUID,
    body: ApprovalRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    审批通过

    - 只有当前审批节点的负责人才可操作
    - 通过后自动流转到下一审批节点（如有）或最终通过
    """
    svc = _get_approval_service()
    try:
        # 先获取审批实例 ID
        trace = await svc.get_approval_trace(
            db=db,
            tenant_id=tenant_id,
            application_id=application_id,
        )
        if trace is None:
            raise HTTPException(status_code=404, detail="审批实例不存在，请确认申请已提交")

        instance_id = trace.get("instance_id") if isinstance(trace, dict) else getattr(trace, "instance_id", None)
        if instance_id is None:
            raise HTTPException(status_code=404, detail="无法获取审批实例ID")

        result = await svc.process_approval_action(
            db=db,
            tenant_id=tenant_id,
            instance_id=instance_id,
            approver_id=current_user_id,
            action=ApprovalAction.APPROVE,
            comment=body.comment,
            transfer_to_id=None,
        )
        log.info(
            "approval_approved",
            application_id=str(application_id),
            approver_id=str(current_user_id),
        )
        return {"ok": True, "data": result, "message": "审批已通过"}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.error("approval_approve_failed", error=str(exc), application_id=str(application_id), exc_info=True)
        raise HTTPException(status_code=500, detail="审批操作失败，请稍后重试")


@router.post("/applications/{application_id}/reject")
async def reject_application(
    application_id: UUID,
    body: RejectRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    审批驳回

    - 驳回原因为必填项，最少5个字
    - 驳回后申请状态变为 rejected，申请人可查看驳回原因
    """
    svc = _get_approval_service()
    try:
        trace = await svc.get_approval_trace(
            db=db,
            tenant_id=tenant_id,
            application_id=application_id,
        )
        if trace is None:
            raise HTTPException(status_code=404, detail="审批实例不存在，请确认申请已提交")

        instance_id = trace.get("instance_id") if isinstance(trace, dict) else getattr(trace, "instance_id", None)
        if instance_id is None:
            raise HTTPException(status_code=404, detail="无法获取审批实例ID")

        result = await svc.process_approval_action(
            db=db,
            tenant_id=tenant_id,
            instance_id=instance_id,
            approver_id=current_user_id,
            action=ApprovalAction.REJECT,
            comment=body.comment,
            transfer_to_id=None,
        )
        log.info(
            "approval_rejected",
            application_id=str(application_id),
            approver_id=str(current_user_id),
        )
        return {"ok": True, "data": result, "message": "已驳回该申请"}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.error("approval_reject_failed", error=str(exc), application_id=str(application_id), exc_info=True)
        raise HTTPException(status_code=500, detail="驳回操作失败，请稍后重试")


@router.get("/pending")
async def get_pending_approvals(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse:
    """
    待我审批列表

    查询当前登录用户（审批人）的所有待处理审批任务，支持分页。
    """
    svc = _get_approval_service()
    try:
        items, total = await svc.get_pending_approvals(
            db=db,
            tenant_id=tenant_id,
            approver_id=current_user_id,
            page=page,
            page_size=page_size,
        )
        return PaginatedResponse(data=items, total=total, page=page, page_size=page_size)
    except Exception as exc:
        log.error("pending_approvals_list_failed", error=str(exc), approver_id=str(current_user_id), exc_info=True)
        raise HTTPException(status_code=500, detail="获取待审批列表失败，请稍后重试")


@router.get("/applications/{application_id}/nodes")
async def get_approval_nodes(
    application_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    查询审批节点详情（完整审批链）

    返回该申请的审批实例信息，包含所有节点的审批人、状态、时间、意见。
    """
    svc = _get_approval_service()
    try:
        result = await svc.get_approval_trace(
            db=db,
            tenant_id=tenant_id,
            application_id=application_id,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="审批记录不存在，请确认申请已提交")
        return {"ok": True, "data": result}
    except HTTPException:
        raise
    except Exception as exc:
        log.error("approval_nodes_get_failed", error=str(exc), application_id=str(application_id), exc_info=True)
        raise HTTPException(status_code=500, detail="获取审批节点失败，请稍后重试")


@router.post("/applications/{application_id}/transfer")
async def transfer_approval(
    application_id: UUID,
    body: TransferRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    转交审批

    - 将当前审批任务转交给指定人员处理
    - 转交后原审批人不再收到该申请的审批通知
    """
    svc = _get_approval_service()
    try:
        trace = await svc.get_approval_trace(
            db=db,
            tenant_id=tenant_id,
            application_id=application_id,
        )
        if trace is None:
            raise HTTPException(status_code=404, detail="审批实例不存在，请确认申请已提交")

        instance_id = trace.get("instance_id") if isinstance(trace, dict) else getattr(trace, "instance_id", None)
        if instance_id is None:
            raise HTTPException(status_code=404, detail="无法获取审批实例ID")

        result = await svc.process_approval_action(
            db=db,
            tenant_id=tenant_id,
            instance_id=instance_id,
            approver_id=current_user_id,
            action=ApprovalAction.TRANSFER,
            comment=body.comment,
            transfer_to_id=body.transfer_to_id,
        )
        log.info(
            "approval_transferred",
            application_id=str(application_id),
            from_approver=str(current_user_id),
            to_approver=str(body.transfer_to_id),
        )
        return {"ok": True, "data": result, "message": "审批已转交"}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.error("approval_transfer_failed", error=str(exc), application_id=str(application_id), exc_info=True)
        raise HTTPException(status_code=500, detail="转交审批失败，请稍后重试")


@router.get("/routing-rules")
async def get_routing_rules(
    brand_id: UUID = Query(..., description="品牌ID（必填）"),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    查看审批路由规则（管理员权限）

    返回指定品牌的审批路由配置，包含金额区间、审批人层级等规则。
    路由类型：按金额分段路由 / 场景固定双签 / 超差标升级审批。
    """
    svc = _get_approval_service()
    try:
        rules = await svc.get_routing_rules(
            db=db,
            tenant_id=tenant_id,
            brand_id=brand_id,
        )
        return {"ok": True, "data": rules}
    except Exception as exc:
        log.error("routing_rules_get_failed", error=str(exc), brand_id=str(brand_id), exc_info=True)
        raise HTTPException(status_code=500, detail="获取路由规则失败，请稍后重试")
