"""rfq_routes — RFQ 询价单 API（PRD-04 sub-B + sub-C / Phase 2 W9-W10 / T1+T2）

接口列表:
  admin-side (`/api/v1/supply/rfqs`):
    POST   /api/v1/supply/rfqs                       创建草稿 RFQ (sub-B)
    GET    /api/v1/supply/rfqs                       列表 (sub-C)
    GET    /api/v1/supply/rfqs/{rfq_id}              单条详情 (sub-B)
    POST   /api/v1/supply/rfqs/{rfq_id}/publish      draft → published (sub-C)
    POST   /api/v1/supply/rfqs/{rfq_id}/close        quoting → comparing (sub-C)
    POST   /api/v1/supply/rfqs/{rfq_id}/cancel       任何非终态 → cancelled (sub-C)
    GET    /api/v1/supply/rfqs/{rfq_id}/comparison   比价表 + AI 推荐 (sub-C)
    POST   /api/v1/supply/rfqs/{rfq_id}/award        Tier 1 中标 + 二级审批 (sub-B)

  supplier-portal (`/api/v1/supply/supplier-portal/rfqs`):
    POST   /api/v1/supply/supplier-portal/rfqs/{rfq_id}/quote   供应商报价 (sub-C)

Auth 模式 (sub-C):
  - admin-side: X-Tenant-ID + X-User-ID (existing pattern)
  - supplier-portal: X-Tenant-ID + X-Supplier-ID (供应商门户登录后由 supplier_portal_v2
    的 supplier_token 解出, sub-C 暂以 header 透传 — 生产 JWT 由 sub-D follow-up 接入)

sub-B / sub-C 边界:
  - sub-B (#647 已 ship): create_rfq + get_rfq + award_rfq (Tier 1 资金路径)
  - sub-C (本 PR): 4 state transitions + supplier 报价 + 比价表 + list + 前端 UI
  - sub-D follow-up: 供应商门户登录 JWT + sub-C scope 完整鉴权
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db as _get_db

from ..models.rfq_models import (
    RFQAwardCreate,
    RFQCancelRequest,
    RFQCreate,
    RFQSupplierQuoteSubmit,
)
from ..services.rfq_service import (
    award_rfq,
    cancel_rfq,
    close_rfq,
    create_rfq,
    get_rfq,
    get_rfq_comparison,
    list_rfqs,
    publish_rfq,
    submit_quote,
)

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/supply",
    tags=["rfqs"],
)


# ─── 错误映射 helper ─────────────────────────────────────────────────────────


def _state_machine_http(code: str, msg: str) -> HTTPException:
    """状态机冲突 (409) — 沿 PR-A/B/C row-lock 错误模型对齐。"""
    if "不存在" in msg:
        return HTTPException(
            status_code=404,
            detail={"code": f"{code}_NOT_FOUND", "message": msg},
        )
    if (
        "终态" in msg
        or "不可" in msg
        or "已 " in msg
        or "幂等" in msg
        or "仅" in msg
    ):
        return HTTPException(
            status_code=409,
            detail={"code": f"{code}_CONFLICT", "message": msg},
        )
    return HTTPException(
        status_code=422,
        detail={"code": f"{code}_INVALID", "message": msg},
    )


# ─── admin-side: create / get / list / state transitions / comparison / award ──


@router.post("/rfqs")
async def create_supply_rfq(
    body: RFQCreate,
    x_user_id: str = Header(..., alias="X-User-ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """创建草稿 RFQ — 同事务原子写 rfqs + rfq_items + rfq_invitees (sub-B)。"""
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


@router.get("/rfqs")
async def list_supply_rfqs(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """RFQ 列表 — deadline 倒序; status 精确过滤 (可选)。"""
    try:
        items = await list_rfqs(
            db=db,
            tenant_id=x_tenant_id,
            status_filter=status_filter,
            limit=limit,
            offset=offset,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail={"code": "RFQ_LIST_INVALID", "message": str(e)},
        ) from e
    return {"ok": True, "data": items}


@router.get("/rfqs/{rfq_id}")
async def get_supply_rfq(
    rfq_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """单条 RFQ 详情 (read-only / lock=False)。"""
    item = await get_rfq(db=db, tenant_id=x_tenant_id, rfq_id=rfq_id)
    if item is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "RFQ_NOT_FOUND", "message": f"rfq_id={rfq_id} 不存在或已删除"},
        )
    return {"ok": True, "data": item}


@router.post("/rfqs/{rfq_id}/publish")
async def publish_supply_rfq(
    rfq_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """draft → published — 发布草稿, 邀请供应商可见 (sub-C)。"""
    try:
        item = await publish_rfq(db=db, tenant_id=x_tenant_id, rfq_id=rfq_id)
    except ValueError as e:
        raise _state_machine_http("RFQ_PUBLISH", str(e)) from e
    return {"ok": True, "data": item}


@router.post("/rfqs/{rfq_id}/close")
async def close_supply_rfq(
    rfq_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """quoting → comparing — 截止收报价, 进入比价审核 (sub-C)。"""
    try:
        item = await close_rfq(db=db, tenant_id=x_tenant_id, rfq_id=rfq_id)
    except ValueError as e:
        raise _state_machine_http("RFQ_CLOSE", str(e)) from e
    return {"ok": True, "data": item}


@router.post("/rfqs/{rfq_id}/cancel")
async def cancel_supply_rfq(
    rfq_id: str,
    body: RFQCancelRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """任何非终态 → cancelled (reason 必填, 合规审计) (sub-C)。"""
    try:
        item = await cancel_rfq(
            db=db,
            tenant_id=x_tenant_id,
            rfq_id=rfq_id,
            reason=body.reason,
        )
    except ValueError as e:
        raise _state_machine_http("RFQ_CANCEL", str(e)) from e
    return {"ok": True, "data": item}


@router.get("/rfqs/{rfq_id}/comparison")
async def get_supply_rfq_comparison(
    rfq_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """比价表 + AI 推荐 — 按 SKU 汇总所有供应商报价 (sub-C)。"""
    try:
        item = await get_rfq_comparison(
            db=db, tenant_id=x_tenant_id, rfq_id=rfq_id
        )
    except ValueError as e:
        raise _state_machine_http("RFQ_COMPARISON", str(e)) from e
    return {"ok": True, "data": item}


@router.post("/rfqs/{rfq_id}/award")
async def award_supply_rfq(
    rfq_id: str,
    body: RFQAwardCreate,
    x_user_id: str = Header(..., alias="X-User-ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """Tier 1 中标 — FOR UPDATE 行锁串行化 + 二级审批 + RLHF (sub-B)。"""
    try:
        item = await award_rfq(
            db=db,
            tenant_id=x_tenant_id,
            rfq_id=rfq_id,
            selected_quote_id=str(body.selected_quote_id),
            reason=body.reason,
            approver_id=x_user_id,
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


# ─── supplier-portal scope (sub-C) ────────────────────────────────────────────


supplier_portal_router = APIRouter(
    prefix="/api/v1/supply/supplier-portal",
    tags=["rfqs-supplier-portal"],
)


@supplier_portal_router.post("/rfqs/{rfq_id}/quote")
async def submit_supplier_quote(
    rfq_id: str,
    body: RFQSupplierQuoteSubmit,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_supplier_id: str = Header(..., alias="X-Supplier-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """供应商门户报价 (sub-C)。

    Auth: X-Supplier-ID header (sub-C scope — 生产由 supplier_portal_v2 login 出的
    JWT 解析得到, sub-D follow-up 接 JWT 鉴权; sub-C 暂以 header 透传方便 e2e 验证)。

    校验链:
      1. RFQ 存在 + status in (published, quoting)
      2. supplier_id 必须被邀 (rfq_invitees)
      3. ingredient_id 必须在 rfq_items
      4. unit_price_fen > 0
      5. UNIQUE(tenant, rfq, supplier, ingredient) ON CONFLICT 覆盖 (允许修改报价)
    """
    try:
        item = await submit_quote(
            db=db,
            tenant_id=x_tenant_id,
            rfq_id=rfq_id,
            supplier_id=x_supplier_id,
            ingredient_id=str(body.ingredient_id),
            unit_price_fen=body.unit_price_fen,
            qty_offered=body.qty_offered,
            valid_until=body.valid_until,
            notes=body.notes,
        )
    except ValueError as e:
        msg = str(e)
        if "不存在" in msg:
            raise HTTPException(
                status_code=404,
                detail={"code": "RFQ_QUOTE_NOT_FOUND", "message": msg},
            ) from e
        if "未被邀请" in msg:
            raise HTTPException(
                status_code=403,
                detail={"code": "RFQ_QUOTE_FORBIDDEN", "message": msg},
            ) from e
        if "不在" in msg or "状态为" in msg or "仅" in msg:
            raise HTTPException(
                status_code=409,
                detail={"code": "RFQ_QUOTE_CONFLICT", "message": msg},
            ) from e
        raise HTTPException(
            status_code=422,
            detail={"code": "RFQ_QUOTE_INVALID", "message": msg},
        ) from e
    return {"ok": True, "data": item}


__all__ = ["router", "supplier_portal_router"]
