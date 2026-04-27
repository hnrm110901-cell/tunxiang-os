"""宴会合同路由（Track R2-C / Sprint R2）

端点：
    POST   /api/v1/banquet-contracts
        新建合同（status=draft，CONTRACT_GENERATED 事件）
    GET    /api/v1/banquet-contracts/{id}
        获取单合同
    POST   /api/v1/banquet-contracts/{id}/sign
        签约 → status=signed + CONTRACT_SIGNED 事件（幂等）
    POST   /api/v1/banquet-contracts/{id}/cancel
        作废 → status=cancelled（幂等）
    GET    /api/v1/banquet-contracts
        分页查询：?lead_id=&status=&scheduled_date=&store_id=&page=&size=
    POST   /api/v1/banquet-contracts/{id}/eo-tickets
        手动拆分 EO 工单到 5 部门（默认）
    GET    /api/v1/banquet-contracts/{id}/eo-tickets
        查询合同下所有 EO 工单
    POST   /api/v1/banquet-contracts/{id}/approvals
        审批记录（approve/reject）

统一响应：{"ok": bool, "data": {...}, "error": {...}}
统一鉴权：X-Tenant-ID
"""

from __future__ import annotations

import uuid
from datetime import date as _date
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from shared.ontology.src.extensions.banquet_contracts import (
    ApprovalAction,
    ApprovalRole,
    BanquetApprovalLog,
    ContractStatus,
    EODepartment,
)
from shared.ontology.src.extensions.banquet_leads import BanquetType

from ..repositories.banquet_contract_repo import (
    BanquetContractRepositoryBase,
    InMemoryBanquetContractRepository,
)
from ..services.banquet_contract_service import (
    BanquetContractError,
    BanquetContractNotFoundError,
    BanquetContractService,
    CancellationReasonMissingError,
    InvalidContractTransitionError,
    SignatureRequiredError,
)
from ..services.banquet_eo_ticket_service import BanquetEOTicketService

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/banquet-contracts", tags=["banquet-contract"])


# ──────────────────────────────────────────────────────────────────────────
# 工具
# ──────────────────────────────────────────────────────────────────────────


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: str = "BAD_REQUEST") -> dict[str, Any]:
    return {"ok": False, "data": None, "error": {"code": code, "message": msg}}


def _require_tenant(request: Request) -> uuid.UUID:
    raw = getattr(request.state, "tenant_id", None) or request.headers.get(
        "X-Tenant-ID", ""
    )
    if not raw:
        raise HTTPException(status_code=400, detail="Missing X-Tenant-ID")
    try:
        return uuid.UUID(str(raw))
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid X-Tenant-ID: {exc}"
        ) from exc


def _optional_store_id(request: Request) -> Optional[uuid.UUID]:
    raw = request.headers.get("X-Store-ID", "")
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


# ──────────────────────────────────────────────────────────────────────────
# 依赖注入
# ──────────────────────────────────────────────────────────────────────────

_default_repo: BanquetContractRepositoryBase = InMemoryBanquetContractRepository()


def get_repo() -> BanquetContractRepositoryBase:
    return _default_repo


def get_contract_service(
    repo: BanquetContractRepositoryBase = Depends(get_repo),
) -> BanquetContractService:
    return BanquetContractService(repo=repo)


def get_eo_service(
    repo: BanquetContractRepositoryBase = Depends(get_repo),
) -> BanquetEOTicketService:
    return BanquetEOTicketService(repo=repo)


# ──────────────────────────────────────────────────────────────────────────
# 请求/响应模型
# ──────────────────────────────────────────────────────────────────────────


class CreateContractReq(BaseModel):
    lead_id: uuid.UUID = Field(..., description="关联商机ID")
    customer_id: uuid.UUID = Field(..., description="客户ID")
    banquet_type: BanquetType = Field(..., description="宴会类型")
    tables: int = Field(default=0, ge=0, description="桌数")
    total_amount_fen: int = Field(..., ge=0, description="合同总额（分）")
    deposit_fen: int = Field(default=0, ge=0, description="订金（分）")
    pdf_url: Optional[str] = Field(default=None, max_length=500)
    sales_employee_id: Optional[uuid.UUID] = Field(default=None)
    scheduled_date: Optional[_date] = Field(default=None)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SignContractReq(BaseModel):
    signer_id: Optional[uuid.UUID] = Field(default=None)
    signature_provider: str = Field(default="placeholder", max_length=64)
    pdf_url: Optional[str] = Field(default=None, max_length=500)


class CancelContractReq(BaseModel):
    reason: str = Field(..., min_length=1, max_length=200)
    operator_id: Optional[uuid.UUID] = Field(default=None)


class SplitEOReq(BaseModel):
    departments: list[EODepartment] = Field(
        default_factory=lambda: [
            EODepartment.KITCHEN,
            EODepartment.HALL,
            EODepartment.PURCHASE,
            EODepartment.FINANCE,
            EODepartment.MARKETING,
        ],
        min_length=1,
        max_length=5,
    )
    content_by_department: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ApprovalReq(BaseModel):
    approver_id: uuid.UUID = Field(..., description="审批人ID")
    role: ApprovalRole = Field(..., description="审批角色")
    action: ApprovalAction = Field(..., description="approve/reject")
    notes: Optional[str] = Field(default=None, max_length=500)


# ──────────────────────────────────────────────────────────────────────────
# 端点 — 合同 CRUD
# ──────────────────────────────────────────────────────────────────────────


@router.post("")
async def create_contract(
    payload: CreateContractReq,
    request: Request,
    service: BanquetContractService = Depends(get_contract_service),
) -> dict[str, Any]:
    tenant_id = _require_tenant(request)
    store_id = _optional_store_id(request)
    try:
        contract = await service.create_contract(
            tenant_id=tenant_id,
            lead_id=payload.lead_id,
            customer_id=payload.customer_id,
            banquet_type=payload.banquet_type,
            tables=payload.tables,
            total_amount_fen=payload.total_amount_fen,
            deposit_fen=payload.deposit_fen,
            pdf_url=payload.pdf_url,
            store_id=store_id,
            sales_employee_id=payload.sales_employee_id,
            scheduled_date=payload.scheduled_date,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        return _err(str(exc), code="VALIDATION_ERROR")
    return _ok(contract.model_dump(mode="json"))


@router.get("/{contract_id}")
async def get_contract(
    contract_id: uuid.UUID,
    request: Request,
    service: BanquetContractService = Depends(get_contract_service),
) -> dict[str, Any]:
    tenant_id = _require_tenant(request)
    try:
        contract = await service.get_contract(contract_id, tenant_id)
    except BanquetContractNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _ok(contract.model_dump(mode="json"))


@router.post("/{contract_id}/sign")
async def sign_contract(
    contract_id: uuid.UUID,
    payload: SignContractReq,
    request: Request,
    service: BanquetContractService = Depends(get_contract_service),
) -> dict[str, Any]:
    tenant_id = _require_tenant(request)
    try:
        contract = await service.mark_signed(
            contract_id=contract_id,
            tenant_id=tenant_id,
            signer_id=payload.signer_id,
            signature_provider=payload.signature_provider,
            pdf_url=payload.pdf_url,
        )
    except BanquetContractNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (InvalidContractTransitionError, SignatureRequiredError) as exc:
        return _err(str(exc), code=exc.code)
    except BanquetContractError as exc:
        return _err(str(exc), code=exc.code)
    return _ok(contract.model_dump(mode="json"))


@router.post("/{contract_id}/cancel")
async def cancel_contract(
    contract_id: uuid.UUID,
    payload: CancelContractReq,
    request: Request,
    service: BanquetContractService = Depends(get_contract_service),
) -> dict[str, Any]:
    tenant_id = _require_tenant(request)
    try:
        contract = await service.mark_cancelled(
            contract_id=contract_id,
            tenant_id=tenant_id,
            reason=payload.reason,
            operator_id=payload.operator_id,
        )
    except BanquetContractNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (CancellationReasonMissingError, InvalidContractTransitionError) as exc:
        return _err(str(exc), code=exc.code)
    except BanquetContractError as exc:
        return _err(str(exc), code=exc.code)
    return _ok(contract.model_dump(mode="json"))


@router.get("")
async def list_contracts(
    request: Request,
    lead_id: Optional[uuid.UUID] = Query(default=None),
    status: Optional[ContractStatus] = Query(default=None),
    scheduled_date: Optional[_date] = Query(default=None),
    store_id: Optional[uuid.UUID] = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
    service: BanquetContractService = Depends(get_contract_service),
) -> dict[str, Any]:
    tenant_id = _require_tenant(request)
    offset = (page - 1) * size
    items, total = await service.list_contracts(
        tenant_id=tenant_id,
        lead_id=lead_id,
        status=status,
        scheduled_date=scheduled_date,
        store_id=store_id,
        offset=offset,
        limit=size,
    )
    return _ok(
        {
            "items": [i.model_dump(mode="json") for i in items],
            "total": total,
            "page": page,
            "size": size,
        }
    )


# ──────────────────────────────────────────────────────────────────────────
# 端点 — EO 工单
# ──────────────────────────────────────────────────────────────────────────


@router.post("/{contract_id}/eo-tickets")
async def split_eo_tickets(
    contract_id: uuid.UUID,
    payload: SplitEOReq,
    request: Request,
    contract_service: BanquetContractService = Depends(get_contract_service),
    eo_service: BanquetEOTicketService = Depends(get_eo_service),
) -> dict[str, Any]:
    tenant_id = _require_tenant(request)
    try:
        contract = await contract_service.get_contract(contract_id, tenant_id)
    except BanquetContractNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    ctx = {
        "tables": contract.tables,
        "total_amount_fen": contract.total_amount_fen,
        "deposit_fen": contract.deposit_fen,
    }
    # 透传 dish_bom（食安合规）
    if isinstance(contract.metadata, dict):
        if "dish_bom" in contract.metadata:
            ctx["dish_bom"] = contract.metadata["dish_bom"]
        if "dishes" in contract.metadata:
            ctx["dishes"] = contract.metadata["dishes"]

    tickets = await eo_service.create_tickets_for_contract(
        tenant_id=tenant_id,
        contract_id=contract_id,
        departments=payload.departments,
        content_by_department=payload.content_by_department,
        contract_context=ctx,
    )
    return _ok(
        {
            "items": [t.model_dump(mode="json") for t in tickets],
            "count": len(tickets),
        }
    )


@router.get("/{contract_id}/eo-tickets")
async def list_eo_tickets(
    contract_id: uuid.UUID,
    request: Request,
    eo_service: BanquetEOTicketService = Depends(get_eo_service),
) -> dict[str, Any]:
    tenant_id = _require_tenant(request)
    tickets = await eo_service.list_by_contract(
        tenant_id=tenant_id, contract_id=contract_id
    )
    return _ok({"items": [t.model_dump(mode="json") for t in tickets]})


# ──────────────────────────────────────────────────────────────────────────
# 端点 — 审批日志
# ──────────────────────────────────────────────────────────────────────────


@router.post("/{contract_id}/approvals")
async def record_approval(
    contract_id: uuid.UUID,
    payload: ApprovalReq,
    request: Request,
    repo: BanquetContractRepositoryBase = Depends(get_repo),
    service: BanquetContractService = Depends(get_contract_service),
) -> dict[str, Any]:
    tenant_id = _require_tenant(request)
    # 校验 contract 存在
    try:
        await service.get_contract(contract_id, tenant_id)
    except BanquetContractNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if payload.action == ApprovalAction.REJECT and not payload.notes:
        return _err("notes required when action=reject", code="VALIDATION_ERROR")

    now = datetime.now(timezone.utc)
    log = BanquetApprovalLog(
        log_id=uuid.uuid4(),
        tenant_id=tenant_id,
        contract_id=contract_id,
        approver_id=payload.approver_id,
        role=payload.role,
        action=payload.action,
        notes=payload.notes,
        source_event_id=None,
        created_at=now,
    )
    await repo.insert_approval_log(log)
    return _ok(log.model_dump(mode="json"))


__all__ = ["router"]
