"""rfq_routes — RFQ 询价单 API（PRD-04 sub-B / Phase 2 W9 / Tier 1）

接口列表（sub-B 范围 — 仅 admin-side core 3 endpoint）：
  POST   /api/v1/supply/rfqs                       创建草稿 RFQ（含 items + invitees）
  GET    /api/v1/supply/rfqs/{rfq_id}              单条 RFQ 详情
  POST   /api/v1/supply/rfqs/{rfq_id}/award        Tier 1 中标 + 二级审批 + RLHF

sub-C 接续:
  - POST /api/supplier-portal/rfqs/{id}/quote      供应商报价（supplier_portal scope）
  - POST /api/v1/supply/rfqs/{id}/publish          publish draft → published + 发送邀请
  - POST /api/v1/supply/rfqs/{id}/cancel           cancel
  - GET  /api/v1/supply/rfqs/{id}/comparison       比价表 (AI 推荐)
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db as _get_db

from ..models.rfq_models import (
    RFQAwardCreate,
    RFQCreate,
)
from ..services.rfq_service import (
    award_rfq,
    create_rfq,
    get_rfq,
)

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/supply",
    tags=["rfqs"],
)


@router.post("/rfqs")
async def create_supply_rfq(
    body: RFQCreate,
    x_user_id: str = Header(..., alias="X-User-ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """创建草稿 RFQ — 同事务原子写 rfqs + rfq_items + rfq_invitees。

    业务场景：采购员录入 SKU 清单 + 选择邀请的供应商 + 截止时间 → 系统生成 draft RFQ。
    sub-C 提供 publish 接口让 supplier 收到邀约（发邮件/消息中心）。
    """
    try:
        item = await create_rfq(
            db=db,
            tenant_id=x_tenant_id,
            initiator_id=x_user_id,
            deadline=body.deadline,
            items=[
                {
                    "ingredient_id": str(it.ingredient_id),
                    "qty_required": it.qty_required,
                    "qty_unit": it.qty_unit,
                    "spec_notes": it.spec_notes,
                }
                for it in body.items
            ],
            invited_supplier_ids=[str(sid) for sid in body.invited_supplier_ids],
            created_by=x_user_id,
            notes=body.notes,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail={"code": "RFQ_CREATE_VALIDATION", "message": str(e)},
        ) from e
    return {"ok": True, "data": item}


@router.get("/rfqs/{rfq_id}")
async def get_supply_rfq(
    rfq_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """单条 RFQ 详情（read-only / lock=False）。"""
    item = await get_rfq(db=db, tenant_id=x_tenant_id, rfq_id=rfq_id)
    if item is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "RFQ_NOT_FOUND", "message": f"rfq_id={rfq_id} 不存在或已删除"},
        )
    return {"ok": True, "data": item}


@router.post("/rfqs/{rfq_id}/award")
async def award_supply_rfq(
    rfq_id: str,
    body: RFQAwardCreate,
    x_user_id: str = Header(..., alias="X-User-ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """Tier 1 中标接口 — FOR UPDATE 行锁串行化 + 二级审批 + RLHF 信号。

    业务场景：采购总监审核比价表后选定 selected_quote_id → 系统校验:
      1. RFQ 状态非 awarded/cancelled
      2. approver_id != rfq.created_by (二级审批)
      3. selected_quote_id 属于本 RFQ (合规审计)
      4. UNIQUE(rfq_id) 防重复 award
    成功后 rfqs.status='awarded' + rfq_awards 入表（不可回退）。
    """
    try:
        item = await award_rfq(
            db=db,
            tenant_id=x_tenant_id,
            rfq_id=rfq_id,
            selected_quote_id=str(body.selected_quote_id),
            reason=body.reason,
            approver_id=x_user_id,
            created_by=x_user_id,
            ai_recommendation_followed=body.ai_recommendation_followed,
        )
    except ValueError as e:
        msg = str(e)
        if "不存在" in msg:
            raise HTTPException(
                status_code=404,
                detail={"code": "RFQ_NOT_FOUND", "message": msg},
            ) from e
        if "已 award" in msg or "已 cancel" in msg or "不允许" in msg:
            raise HTTPException(
                status_code=409,
                detail={"code": "RFQ_AWARD_CONFLICT", "message": msg},
            ) from e
        raise HTTPException(
            status_code=422,
            detail={"code": "RFQ_AWARD_INVALID", "message": msg},
        ) from e
    return {"ok": True, "data": item}


__all__ = ["router"]
