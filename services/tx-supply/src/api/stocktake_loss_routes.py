"""盘亏处理审批闭环 API 路由

10 个端点：
- POST /api/v1/supply/stocktake/{stocktake_id}/auto-create-loss-case
- POST /api/v1/supply/stocktake-loss/cases               — 手动建案
- GET  /api/v1/supply/stocktake-loss/cases?status=&store_id=
- GET  /api/v1/supply/stocktake-loss/{id}
- POST /api/v1/supply/stocktake-loss/{id}/items
- POST /api/v1/supply/stocktake-loss/{id}/responsibility
- POST /api/v1/supply/stocktake-loss/{id}/submit
- POST /api/v1/supply/stocktake-loss/{id}/approve
- POST /api/v1/supply/stocktake-loss/{id}/reject
- POST /api/v1/supply/stocktake-loss/{id}/writeoff
- GET  /api/v1/supply/stocktake-loss/stats?from=&to=&store_id=

每个端点：读取 X-Tenant-ID + SET LOCAL app.tenant_id；
统一响应 {ok, data, error}。
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

# Imports work both in production (relative within tx-supply package) and in
# tests where src/ is added to sys.path directly. `models` becomes top-level.
try:
    from models.stocktake_loss import (  # type: ignore[no-redef]
        ApproveDecisionPayload,
        AssignResponsibilityPayload,
        CaseStatus,
        CreateLossCasePayload,
        InvalidStateTransition,
        LossItemInput,
        SubmitForApprovalPayload,
        WriteoffPayload,
    )
    from services.stocktake_loss_service import (  # type: ignore[no-redef]
        ApprovalPermissionError,
        CaseNotFoundError,
        CaseValidationError,
        WriteoffStateError,
        add_items,
        approve,
        assign_responsibility,
        auto_create_loss_case_from_stocktake,
        create_loss_case,
        get_case_detail,
        get_loss_stats,
        list_cases,
        reject,
        submit_for_approval,
        writeoff,
    )
except ImportError:  # pragma: no cover
    from ..models.stocktake_loss import (  # type: ignore[no-redef]
        ApproveDecisionPayload,
        AssignResponsibilityPayload,
        CaseStatus,
        CreateLossCasePayload,
        InvalidStateTransition,
        LossItemInput,
        SubmitForApprovalPayload,
        WriteoffPayload,
    )
    from ..services.stocktake_loss_service import (  # type: ignore[no-redef]
        ApprovalPermissionError,
        CaseNotFoundError,
        CaseValidationError,
        WriteoffStateError,
        add_items,
        approve,
        assign_responsibility,
        auto_create_loss_case_from_stocktake,
        create_loss_case,
        get_case_detail,
        get_loss_stats,
        list_cases,
        reject,
        submit_for_approval,
        writeoff,
    )

router = APIRouter(prefix="/api/v1/supply", tags=["stocktake-loss"])


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    """SET LOCAL app.tenant_id（路由层防御纵深）。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data, "error": None}


def _fail(http_code: int, message: str, detail: Optional[Any] = None) -> HTTPException:
    return HTTPException(
        status_code=http_code,
        detail={"ok": False, "data": None, "error": {"message": message, "detail": detail}},
    )


# ─────────────────────────────────────────────────────────────────────
# 入参 wrapper
# ─────────────────────────────────────────────────────────────────────


class AutoCreateBody(BaseModel):
    created_by: str


class AddItemsBody(BaseModel):
    items: list[LossItemInput]


# ─────────────────────────────────────────────────────────────────────
# 1. 自动建案（盘点完成后调用）
# ─────────────────────────────────────────────────────────────────────


@router.post("/stocktake/{stocktake_id}/auto-create-loss-case")
async def auto_create_loss_case_route(
    stocktake_id: str,
    body: AutoCreateBody,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """盘点完成后自动建案；金额未超阈值返回 None（仍是 ok=True）。"""
    await _set_rls(db, x_tenant_id)
    try:
        data = await auto_create_loss_case_from_stocktake(
            stocktake_id=stocktake_id,
            tenant_id=x_tenant_id,
            db=db,
            created_by=body.created_by,
        )
        return _ok({"created": data is not None, "case": data})
    except CaseValidationError as exc:
        raise _fail(400, str(exc))


# ─────────────────────────────────────────────────────────────────────
# 2. 手动建案
# ─────────────────────────────────────────────────────────────────────


@router.post("/stocktake-loss/cases")
async def create_loss_case_route(
    body: CreateLossCasePayload,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """手动建案（适用于补录历史盘亏或盘点之外的损失登记）。"""
    await _set_rls(db, x_tenant_id)
    try:
        data = await create_loss_case(
            tenant_id=x_tenant_id,
            stocktake_id=body.stocktake_id,
            store_id=body.store_id,
            items=body.items,
            created_by=body.created_by,
            db=db,
            responsible_party_type=body.responsible_party_type,
            responsible_party_id=body.responsible_party_id,
            responsible_reason=body.responsible_reason,
        )
        return _ok(data)
    except CaseValidationError as exc:
        raise _fail(400, str(exc))


# ─────────────────────────────────────────────────────────────────────
# 3. 列表
# ─────────────────────────────────────────────────────────────────────


@router.get("/stocktake-loss/cases")
async def list_cases_route(
    status: Optional[str] = Query(None),
    store_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _set_rls(db, x_tenant_id)
    parsed_status: Optional[CaseStatus] = None
    if status:
        try:
            parsed_status = CaseStatus(status)
        except ValueError:
            raise _fail(400, f"Invalid status: {status}")
    data = await list_cases(
        tenant_id=x_tenant_id,
        db=db,
        status=parsed_status,
        store_id=store_id,
        limit=limit,
        offset=offset,
    )
    return _ok(data)


# ─────────────────────────────────────────────────────────────────────
# 4. 损失统计（必须在 /{case_id} 之前注册，避免路由冲突）
# ─────────────────────────────────────────────────────────────────────


@router.get("/stocktake-loss/stats")
async def stats_route(
    from_date: str = Query(..., alias="from", description="YYYY-MM-DD"),
    to_date: str = Query(..., alias="to", description="YYYY-MM-DD"),
    store_id: Optional[str] = Query(None),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _set_rls(db, x_tenant_id)
    try:
        data = await get_loss_stats(
            tenant_id=x_tenant_id,
            db=db,
            from_date=from_date,
            to_date=to_date,
            store_id=store_id,
        )
        return _ok(data)
    except CaseValidationError as exc:
        raise _fail(400, str(exc))


# ─────────────────────────────────────────────────────────────────────
# 5. 详情
# ─────────────────────────────────────────────────────────────────────


@router.get("/stocktake-loss/{case_id}")
async def get_case_detail_route(
    case_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _set_rls(db, x_tenant_id)
    try:
        data = await get_case_detail(case_id, x_tenant_id, db)
        return _ok(data)
    except CaseNotFoundError as exc:
        raise _fail(404, str(exc))


# ─────────────────────────────────────────────────────────────────────
# 5. 追加明细
# ─────────────────────────────────────────────────────────────────────


@router.post("/stocktake-loss/{case_id}/items")
async def add_items_route(
    case_id: str,
    body: AddItemsBody,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _set_rls(db, x_tenant_id)
    try:
        data = await add_items(case_id, body.items, x_tenant_id, db)
        return _ok(data)
    except CaseNotFoundError as exc:
        raise _fail(404, str(exc))
    except CaseValidationError as exc:
        raise _fail(400, str(exc))


# ─────────────────────────────────────────────────────────────────────
# 6. 指派责任
# ─────────────────────────────────────────────────────────────────────


@router.post("/stocktake-loss/{case_id}/responsibility")
async def assign_responsibility_route(
    case_id: str,
    body: AssignResponsibilityPayload,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _set_rls(db, x_tenant_id)
    try:
        data = await assign_responsibility(
            case_id=case_id,
            party_type=body.responsible_party_type,
            party_id=body.responsible_party_id,
            reason=body.responsible_reason,
            tenant_id=x_tenant_id,
            db=db,
        )
        return _ok(data)
    except CaseNotFoundError as exc:
        raise _fail(404, str(exc))
    except CaseValidationError as exc:
        raise _fail(400, str(exc))


# ─────────────────────────────────────────────────────────────────────
# 7. 提交审批
# ─────────────────────────────────────────────────────────────────────


@router.post("/stocktake-loss/{case_id}/submit")
async def submit_route(
    case_id: str,
    body: SubmitForApprovalPayload,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _set_rls(db, x_tenant_id)
    try:
        data = await submit_for_approval(
            case_id=case_id,
            tenant_id=x_tenant_id,
            db=db,
            submitted_by=body.submitted_by,
            approval_chain=body.approval_chain,
        )
        return _ok(data)
    except CaseNotFoundError as exc:
        raise _fail(404, str(exc))
    except InvalidStateTransition as exc:
        raise _fail(409, str(exc))
    except CaseValidationError as exc:
        raise _fail(400, str(exc))


# ─────────────────────────────────────────────────────────────────────
# 8. 审批通过
# ─────────────────────────────────────────────────────────────────────


@router.post("/stocktake-loss/{case_id}/approve")
async def approve_route(
    case_id: str,
    body: ApproveDecisionPayload,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _set_rls(db, x_tenant_id)
    try:
        data = await approve(
            case_id=case_id,
            approver_id=body.approver_id,
            approver_role=body.approver_role,
            tenant_id=x_tenant_id,
            db=db,
            comment=body.comment,
        )
        return _ok(data)
    except CaseNotFoundError as exc:
        raise _fail(404, str(exc))
    except ApprovalPermissionError as exc:
        raise _fail(403, str(exc))
    except InvalidStateTransition as exc:
        raise _fail(409, str(exc))
    except CaseValidationError as exc:
        raise _fail(400, str(exc))


# ─────────────────────────────────────────────────────────────────────
# 9. 审批驳回
# ─────────────────────────────────────────────────────────────────────


@router.post("/stocktake-loss/{case_id}/reject")
async def reject_route(
    case_id: str,
    body: ApproveDecisionPayload,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _set_rls(db, x_tenant_id)
    try:
        data = await reject(
            case_id=case_id,
            approver_id=body.approver_id,
            approver_role=body.approver_role,
            tenant_id=x_tenant_id,
            db=db,
            comment=body.comment,
        )
        return _ok(data)
    except CaseNotFoundError as exc:
        raise _fail(404, str(exc))
    except ApprovalPermissionError as exc:
        raise _fail(403, str(exc))
    except InvalidStateTransition as exc:
        raise _fail(409, str(exc))
    except CaseValidationError as exc:
        raise _fail(400, str(exc))


# ─────────────────────────────────────────────────────────────────────
# 10. 财务核销
# ─────────────────────────────────────────────────────────────────────


@router.post("/stocktake-loss/{case_id}/writeoff")
async def writeoff_route(
    case_id: str,
    body: WriteoffPayload,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _set_rls(db, x_tenant_id)
    try:
        data = await writeoff(
            case_id=case_id,
            writeoff_voucher_no=body.writeoff_voucher_no,
            writeoff_amount_fen=body.writeoff_amount_fen,
            accounting_subject=body.accounting_subject,
            finance_user_id=body.finance_user_id,
            tenant_id=x_tenant_id,
            db=db,
            attachment_url=body.attachment_url,
            comment=body.comment,
        )
        return _ok(data)
    except CaseNotFoundError as exc:
        raise _fail(404, str(exc))
    except WriteoffStateError as exc:
        raise _fail(409, str(exc))
    except InvalidStateTransition as exc:
        raise _fail(409, str(exc))
    except CaseValidationError as exc:
        raise _fail(400, str(exc))


