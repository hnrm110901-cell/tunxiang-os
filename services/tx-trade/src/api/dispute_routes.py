"""Sprint E4 — 异议工作流 API

端点：
  POST /api/v1/trade/delivery/disputes
    创建 dispute（webhook 或手动）

  GET  /api/v1/trade/delivery/disputes
    分页列表（platform / status / store / sla_breached 过滤）

  GET  /api/v1/trade/delivery/disputes/{id}
    详情（含消息流）

  GET  /api/v1/trade/delivery/disputes/{id}/messages
    消息历史

  POST /api/v1/trade/delivery/disputes/{id}/draft-response
    生成响应草稿（自动推荐或指定模板）

  POST /api/v1/trade/delivery/disputes/{id}/respond
    商家提交响应 → 状态机迁移

  POST /api/v1/trade/delivery/disputes/{id}/platform-ruling
    记录平台裁决（webhook 或手动）

  POST /api/v1/trade/delivery/disputes/{id}/escalate
    升级到人工/主管

  POST /api/v1/trade/delivery/disputes/{id}/withdraw
    顾客撤诉

  GET  /api/v1/trade/delivery/disputes/templates
    列出响应模板（可按 dispute_type 过滤）

  POST /api/v1/trade/delivery/disputes/sweep-sla
    cron 端点：扫描过期 dispute（status → expired）
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.dispute_response_templates import (
    list_templates,
)
from ..services.dispute_service import (
    DisputeError,
    DisputeIngestInput,
    DisputeService,
    MerchantResponseInput,
    PlatformRulingInput,
)

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/v1/trade/delivery/disputes",
    tags=["trade-delivery-disputes"],
)


# ── 请求模型 ─────────────────────────────────────────────────────


class DisputeIngestRequest(BaseModel):
    platform: str = Field(
        ..., description="meituan|eleme|douyin|xiaohongshu|wechat"
    )
    platform_dispute_id: str = Field(..., min_length=1, max_length=100)
    platform_order_id: str = Field(..., min_length=1, max_length=100)
    dispute_type: str = Field(..., description="quality_issue|missing_item|...")
    dispute_reason: Optional[str] = None
    customer_claim_amount_fen: Optional[int] = Field(default=None, ge=0)
    customer_evidence_urls: list[str] = Field(default_factory=list)
    raised_at: Optional[datetime] = None
    canonical_order_id: Optional[str] = None
    store_id: Optional[str] = None
    brand_id: Optional[str] = None
    source: str = Field(default="webhook")
    raw_payload: dict = Field(default_factory=dict)
    merchant_sla_hours: int = Field(default=24, ge=1, le=168)


class DraftResponseRequest(BaseModel):
    template_id: Optional[str] = None
    extra_variables: dict = Field(default_factory=dict)


class MerchantResponseRequest(BaseModel):
    action: str = Field(..., description="accept_full|offer_partial|dispute")
    response_text: str = Field(..., min_length=1)
    offered_refund_fen: Optional[int] = Field(default=None, ge=0)
    evidence_urls: list[str] = Field(default_factory=list)
    template_id: Optional[str] = None


class PlatformRulingRequest(BaseModel):
    platform_decision: str = Field(..., min_length=1)
    platform_refund_fen: int = Field(..., ge=0)
    merchant_win: bool = False
    escalate: bool = False
    ruled_at: Optional[datetime] = None


class EscalateRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


class WithdrawRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


# ── 端点 ────────────────────────────────────────────────────────


@router.post("", response_model=dict, status_code=201)
async def create_dispute(
    req: DisputeIngestRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建 dispute（webhook 或手动）"""
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    if req.canonical_order_id:
        _parse_uuid(req.canonical_order_id, "canonical_order_id")
    if req.store_id:
        _parse_uuid(req.store_id, "store_id")
    if req.brand_id:
        _parse_uuid(req.brand_id, "brand_id")

    from datetime import timedelta as _td

    inp = DisputeIngestInput(
        platform=req.platform,
        platform_dispute_id=req.platform_dispute_id,
        platform_order_id=req.platform_order_id,
        dispute_type=req.dispute_type,
        dispute_reason=req.dispute_reason,
        customer_claim_amount_fen=req.customer_claim_amount_fen,
        customer_evidence_urls=req.customer_evidence_urls,
        raised_at=req.raised_at,
        canonical_order_id=req.canonical_order_id,
        store_id=req.store_id,
        brand_id=req.brand_id,
        source=req.source,
        raw_payload=req.raw_payload,
        merchant_sla=_td(hours=req.merchant_sla_hours),
    )

    service = DisputeService(db, tenant_id=x_tenant_id)
    try:
        result = await service.ingest_dispute(inp)
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("dispute_ingest_db_error")
        raise HTTPException(status_code=500, detail=f"创建失败: {exc}") from exc

    return {"ok": True, "data": result}


@router.get("", response_model=dict)
async def list_disputes(
    platform: Optional[str] = None,
    status: Optional[str] = None,
    store_id: Optional[str] = None,
    sla_breached: Optional[bool] = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """分页列表"""
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    if store_id:
        _parse_uuid(store_id, "store_id")

    conditions = [
        "tenant_id = CAST(:tenant_id AS uuid)",
        "is_deleted = false",
    ]
    params: dict[str, Any] = {"tenant_id": x_tenant_id}
    if platform:
        conditions.append("platform = :platform")
        params["platform"] = platform
    if status:
        conditions.append("status = :status")
        params["status"] = status
    if store_id:
        conditions.append("store_id = CAST(:store_id AS uuid)")
        params["store_id"] = store_id
    if sla_breached is not None:
        conditions.append("sla_breached = :sla_breached")
        params["sla_breached"] = sla_breached

    where = " AND ".join(conditions)
    offset = (page - 1) * size

    try:
        count_row = await db.execute(
            text(f"SELECT COUNT(*) AS total FROM delivery_disputes WHERE {where}"),
            params,
        )
        total = count_row.scalar() or 0

        list_params = {**params, "limit": size, "offset": offset}
        rows = await db.execute(
            text(f"""
                SELECT id, platform, platform_dispute_id, platform_order_id,
                       store_id, dispute_type, status,
                       customer_claim_amount_fen,
                       merchant_offered_refund_fen, platform_refund_fen,
                       raised_at, merchant_deadline_at, sla_breached,
                       closed_at
                FROM delivery_disputes
                WHERE {where}
                ORDER BY raised_at DESC
                LIMIT :limit OFFSET :offset
            """),
            list_params,
        )
        items = [dict(r) for r in rows.mappings()]
    except SQLAlchemyError as exc:
        logger.exception("disputes_list_failed")
        raise HTTPException(status_code=500, detail=f"查询失败: {exc}") from exc

    return {
        "ok": True,
        "data": {"items": items, "total": total, "page": page, "size": size},
    }


@router.get("/templates", response_model=dict)
async def list_response_templates(
    dispute_type: Optional[str] = None,
) -> dict:
    """列响应模板（公共端点，无需 tenant）"""
    templates = list_templates(dispute_type=dispute_type)
    return {
        "ok": True,
        "data": {
            "templates": [t.to_dict() for t in templates],
            "count": len(templates),
        },
    }


@router.post("/sweep-sla", response_model=dict)
async def sweep_sla(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """cron 端点：扫描过期未响应的 dispute → expired

    正常生产环境由 cron / scheduled-tasks 定时（~5min）触发。
    """
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    service = DisputeService(db, tenant_id=x_tenant_id)
    try:
        count = await service.sweep_breached_slas()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("dispute_sweep_failed")
        raise HTTPException(status_code=500, detail=f"SLA 扫描失败: {exc}") from exc
    return {"ok": True, "data": {"expired_count": count}}


@router.get("/{dispute_id}", response_model=dict)
async def get_dispute(
    dispute_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(dispute_id, "dispute_id")

    try:
        row = await db.execute(
            text("""
                SELECT * FROM delivery_disputes
                WHERE id = CAST(:id AS uuid)
                  AND tenant_id = CAST(:tenant_id AS uuid)
                  AND is_deleted = false
            """),
            {"id": dispute_id, "tenant_id": x_tenant_id},
        )
        dispute = row.mappings().first()
        if not dispute:
            raise HTTPException(status_code=404, detail="dispute 不存在")

        msgs_row = await db.execute(
            text("""
                SELECT id, sender_role, sender_id, message_type, content,
                       attachment_urls, linked_refund_fen, sent_at
                FROM delivery_dispute_messages
                WHERE dispute_id = CAST(:id AS uuid)
                  AND is_deleted = false
                ORDER BY sent_at ASC
            """),
            {"id": dispute_id},
        )
        messages = [dict(r) for r in msgs_row.mappings()]
    except SQLAlchemyError as exc:
        logger.exception("dispute_get_failed")
        raise HTTPException(status_code=500, detail=f"查询失败: {exc}") from exc

    return {
        "ok": True,
        "data": {
            "dispute": dict(dispute),
            "messages": messages,
            "message_count": len(messages),
        },
    }


@router.get("/{dispute_id}/messages", response_model=dict)
async def list_messages(
    dispute_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(dispute_id, "dispute_id")

    try:
        rows = await db.execute(
            text("""
                SELECT id, sender_role, sender_id, message_type, content,
                       attachment_urls, linked_refund_fen, sent_at
                FROM delivery_dispute_messages m
                WHERE dispute_id = CAST(:id AS uuid)
                  AND EXISTS (
                    SELECT 1 FROM delivery_disputes d
                    WHERE d.id = m.dispute_id
                      AND d.tenant_id = CAST(:tenant_id AS uuid)
                  )
                  AND m.is_deleted = false
                ORDER BY sent_at ASC
            """),
            {"id": dispute_id, "tenant_id": x_tenant_id},
        )
        messages = [dict(r) for r in rows.mappings()]
    except SQLAlchemyError as exc:
        logger.exception("dispute_messages_list_failed")
        raise HTTPException(status_code=500, detail=f"查询失败: {exc}") from exc

    return {"ok": True, "data": {"messages": messages, "count": len(messages)}}


@router.post("/{dispute_id}/draft-response", response_model=dict)
async def draft_response(
    dispute_id: str,
    req: DraftResponseRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(dispute_id, "dispute_id")

    service = DisputeService(db, tenant_id=x_tenant_id)
    try:
        result = await service.draft_response(
            dispute_id=dispute_id,
            template_id=req.template_id,
            extra_variables=req.extra_variables,
        )
    except DisputeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "data": result.to_dict()}


@router.post("/{dispute_id}/respond", response_model=dict)
async def respond(
    dispute_id: str,
    req: MerchantResponseRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: Optional[str] = Header(default=None, alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(dispute_id, "dispute_id")
    if x_operator_id:
        _parse_uuid(x_operator_id, "X-Operator-ID")

    try:
        response_input = MerchantResponseInput(
            action=req.action,
            response_text=req.response_text,
            offered_refund_fen=req.offered_refund_fen,
            evidence_urls=req.evidence_urls,
            template_id=req.template_id,
            responded_by=x_operator_id,
        )
    except DisputeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    service = DisputeService(db, tenant_id=x_tenant_id)
    try:
        result = await service.submit_merchant_response(
            dispute_id=dispute_id, response=response_input
        )
    except DisputeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("dispute_respond_db_error")
        raise HTTPException(status_code=500, detail=f"提交失败: {exc}") from exc

    return {"ok": True, "data": result}


@router.post("/{dispute_id}/platform-ruling", response_model=dict)
async def platform_ruling(
    dispute_id: str,
    req: PlatformRulingRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(dispute_id, "dispute_id")

    ruling = PlatformRulingInput(
        platform_decision=req.platform_decision,
        platform_refund_fen=req.platform_refund_fen,
        merchant_win=req.merchant_win,
        escalate=req.escalate,
        ruled_at=req.ruled_at,
    )
    service = DisputeService(db, tenant_id=x_tenant_id)
    try:
        result = await service.record_platform_ruling(
            dispute_id=dispute_id, ruling=ruling
        )
    except DisputeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("dispute_ruling_db_error")
        raise HTTPException(status_code=500, detail=f"裁决失败: {exc}") from exc

    return {"ok": True, "data": result}


@router.post("/{dispute_id}/escalate", response_model=dict)
async def escalate(
    dispute_id: str,
    req: EscalateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: Optional[str] = Header(default=None, alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(dispute_id, "dispute_id")

    service = DisputeService(db, tenant_id=x_tenant_id)
    try:
        result = await service.escalate(
            dispute_id=dispute_id, reason=req.reason, escalated_by=x_operator_id
        )
    except DisputeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("dispute_escalate_db_error")
        raise HTTPException(status_code=500, detail=f"升级失败: {exc}") from exc

    return {"ok": True, "data": result}


@router.post("/{dispute_id}/withdraw", response_model=dict)
async def withdraw(
    dispute_id: str,
    req: WithdrawRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(dispute_id, "dispute_id")

    service = DisputeService(db, tenant_id=x_tenant_id)
    try:
        result = await service.withdraw(dispute_id=dispute_id, reason=req.reason)
    except DisputeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("dispute_withdraw_db_error")
        raise HTTPException(status_code=500, detail=f"撤诉失败: {exc}") from exc

    return {"ok": True, "data": result}


# ── 辅助 ─────────────────────────────────────────────────────────


def _parse_uuid(value: str, field_name: str) -> UUID:
    try:
        return UUID(value)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=400, detail=f"{field_name} 非法 UUID: {value!r}"
        ) from exc
