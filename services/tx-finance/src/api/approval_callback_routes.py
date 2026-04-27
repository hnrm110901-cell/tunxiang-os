"""审批流回调路由

审批引擎（tx-org approval-flow）审批完成后回调本服务，更新挂账协议状态。

端点：
  POST /api/v1/credit/agreements/{id}/approval-callback — 审批结果回调
"""

import asyncio
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Path
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/credit", tags=["企业挂账-审批回调"])


# ─── 依赖注入 ──────────────────────────────────────────────────────────────────


async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _parse_uuid(val: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(val)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"无效的 {field_name}: {val}") from exc


# ─── 请求模型 ──────────────────────────────────────────────────────────────────


class ApprovalCallbackRequest(BaseModel):
    decision: str  # "approved" | "rejected"
    approver_id: str
    comment: Optional[str] = None


# ─── POST /agreements/{id}/approval-callback ─────────────────────────────────


@router.post("/agreements/{id}/approval-callback", summary="挂账协议审批结果回调")
async def approval_callback(
    id: uuid.UUID = Path(..., description="挂账协议ID"),
    body: ApprovalCallbackRequest = ...,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """接收审批流回调，更新挂账协议状态。

    - approved  → status 更新为 active，记录 approved_by
    - rejected  → status 更新为 terminated
    - 仅处理 pending_approval 状态的协议，其他状态返回 409
    """
    valid_decisions = {"approved", "rejected"}
    if body.decision not in valid_decisions:
        raise HTTPException(
            status_code=400,
            detail=f"decision 必须是: {', '.join(valid_decisions)}",
        )

    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    approver_id = _parse_uuid(body.approver_id, "approver_id")

    # 查询协议，确认存在且处于待审批状态
    try:
        select_result = await db.execute(
            text("""
                SELECT id, status, company_name, credit_limit_fen
                FROM biz_credit_agreements
                WHERE id = :id::UUID AND tenant_id = :tenant_id::UUID
            """),
            {"id": str(id), "tenant_id": str(tid)},
        )
    except Exception as exc:
        logger.error("approval_callback.query_failed", agreement_id=str(id), error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询挂账协议失败") from exc

    row = select_result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="挂账协议不存在")

    if row["status"] != "pending_approval":
        raise HTTPException(
            status_code=409,
            detail=f"协议当前状态为 '{row['status']}'，不可执行审批回调（仅 pending_approval 状态可处理）",
        )

    # 根据审批结果更新状态
    if body.decision == "approved":
        new_status = "active"
        try:
            await db.execute(
                text("""
                    UPDATE biz_credit_agreements
                    SET status = 'active',
                        approved_by = :approver_id::UUID,
                        updated_at = NOW()
                    WHERE id = :id::UUID AND tenant_id = :tenant_id::UUID
                """),
                {
                    "id": str(id),
                    "tenant_id": str(tid),
                    "approver_id": str(approver_id),
                },
            )
            await db.commit()
        except Exception as exc:
            logger.error("approval_callback.approve_failed", agreement_id=str(id), error=str(exc), exc_info=True)
            raise HTTPException(status_code=500, detail="审批通过更新失败") from exc

        event_type = "credit.agreement_approved"
        event_payload = {
            "agreement_id": str(id),
            "company_name": row["company_name"],
            "credit_limit_fen": row["credit_limit_fen"],
            "approver_id": str(approver_id),
            "comment": body.comment,
        }
        logger.info("credit_agreement_approved", agreement_id=str(id), approver_id=str(approver_id))

    else:  # rejected
        new_status = "terminated"
        try:
            await db.execute(
                text("""
                    UPDATE biz_credit_agreements
                    SET status = 'terminated',
                        updated_at = NOW()
                    WHERE id = :id::UUID AND tenant_id = :tenant_id::UUID
                """),
                {"id": str(id), "tenant_id": str(tid)},
            )
            await db.commit()
        except Exception as exc:
            logger.error("approval_callback.reject_failed", agreement_id=str(id), error=str(exc), exc_info=True)
            raise HTTPException(status_code=500, detail="审批拒绝更新失败") from exc

        event_type = "credit.agreement_rejected"
        event_payload = {
            "agreement_id": str(id),
            "company_name": row["company_name"],
            "credit_limit_fen": row["credit_limit_fen"],
            "approver_id": str(approver_id),
            "comment": body.comment,
        }
        logger.info(
            "credit_agreement_rejected", agreement_id=str(id), approver_id=str(approver_id), comment=body.comment
        )

    # 旁路发射结果事件（不阻塞响应）
    asyncio.create_task(
        emit_event(
            event_type=event_type,
            tenant_id=str(tid),
            stream_id=str(id),
            payload=event_payload,
            source_service="tx-finance",
        )
    )

    return {
        "ok": True,
        "data": {
            "agreement_id": str(id),
            "decision": body.decision,
            "new_status": new_status,
        },
        "error": None,
    }
