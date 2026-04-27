"""门店借调与成本分摊 API

持久化：employee_transfers 表（v140 创建，v208 补全字段）
"""

import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from services.store_transfer_service import (
    compute_cost_split,
    compute_time_split,
    generate_cost_analysis_report,
    generate_detail_report,
    generate_summary_report,
)
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import TenantIDInvalid, TenantIDMissing, get_db_with_tenant

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/org", tags=["transfers"])


# ── DB 依赖（含 RLS 校验，防止 NULL 绕过）──────────────────────────────────────


async def _get_db(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> AsyncGenerator[AsyncSession, None]:
    try:
        async for session in get_db_with_tenant(x_tenant_id):
            yield session
    except (TenantIDMissing, TenantIDInvalid) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── 辅助函数 ──────────────────────────────────────────────────────────────────


def _row_to_dict(row: object) -> dict:
    """将 SQLAlchemy Row 转为可序列化字典。"""
    if hasattr(row, "_mapping"):
        d = dict(row._mapping)
    else:
        d = dict(row)
    for key in ("start_date", "end_date", "created_at", "updated_at", "approved_at", "effective_date"):
        if d.get(key) is not None and hasattr(d[key], "isoformat"):
            d[key] = d[key].isoformat()
    for key in ("id", "tenant_id", "employee_id", "from_store_id", "to_store_id", "requested_by", "approved_by"):
        if d.get(key) is not None:
            d[key] = str(d[key])
    return d


# ── 请求模型 ──────────────────────────────────────────────────────────────────


class CreateTransferReq(BaseModel):
    employee_id: str
    employee_name: str
    from_store_id: str
    from_store_name: str
    to_store_id: str
    to_store_name: str
    start_date: str
    end_date: str
    reason: str = ""


class ApproveTransferReq(BaseModel):
    approver_id: str


class AttendanceRecord(BaseModel):
    employee_id: str
    date: str
    hours: float
    store_id: str


class SalaryData(BaseModel):
    base_fen: int = 0
    overtime_fen: int = 0
    social_fen: int = 0
    bonus_fen: int = 0


class CostSplitReq(BaseModel):
    transfers: List[dict]
    attendance_records: List[AttendanceRecord]
    salary_data: SalaryData


class CostReportReq(BaseModel):
    report_type: str  # detail / summary / analysis
    transfers: List[dict]
    attendance_records: List[AttendanceRecord]
    salary_data: SalaryData
    employee_id: Optional[str] = None
    budget_data: Optional[dict] = None
    all_employees: Optional[List[dict]] = None


# ── 借调单 CRUD ───────────────────────────────────────────────────────────────


@router.post("/transfers")
async def api_create_transfer(
    req: CreateTransferReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """创建借调单（持久化到 employee_transfers 表）。"""
    # 业务校验（利用原有纯函数服务）
    try:
        from services.store_transfer_service import create_transfer_order as _validate

        _validate(
            employee_id=req.employee_id,
            employee_name=req.employee_name,
            from_store_id=req.from_store_id,
            from_store_name=req.from_store_name,
            to_store_id=req.to_store_id,
            to_store_name=req.to_store_name,
            start_date=req.start_date,
            end_date=req.end_date,
            reason=req.reason,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    transfer_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    try:
        await db.execute(
            text("""
                INSERT INTO employee_transfers (
                    id, tenant_id, employee_id, employee_name,
                    from_store_id, from_store_name,
                    to_store_id, to_store_name,
                    start_date, end_date,
                    reason, status, is_deleted,
                    created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :employee_id, :employee_name,
                    :from_store_id, :from_store_name,
                    :to_store_id, :to_store_name,
                    :start_date, :end_date,
                    :reason, 'pending', false,
                    :now, :now
                )
            """),
            {
                "id": transfer_id,
                "tenant_id": uuid.UUID(x_tenant_id),
                "employee_id": req.employee_id,
                "employee_name": req.employee_name,
                "from_store_id": req.from_store_id,
                "from_store_name": req.from_store_name,
                "to_store_id": req.to_store_id,
                "to_store_name": req.to_store_name,
                "start_date": req.start_date,
                "end_date": req.end_date,
                "reason": req.reason,
                "now": now,
            },
        )
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("transfer.create_failed", error=str(exc), tenant_id=x_tenant_id, exc_info=True)
        raise HTTPException(status_code=500, detail="借调单创建失败，请稍后重试")

    order = {
        "id": str(transfer_id),
        "employee_id": req.employee_id,
        "employee_name": req.employee_name,
        "from_store_id": req.from_store_id,
        "from_store_name": req.from_store_name,
        "to_store_id": req.to_store_id,
        "to_store_name": req.to_store_name,
        "start_date": req.start_date,
        "end_date": req.end_date,
        "reason": req.reason,
        "status": "pending",
        "approved_by": None,
        "approved_at": None,
        "created_at": now.isoformat(),
    }
    logger.info("transfer.created", transfer_id=str(transfer_id), tenant_id=x_tenant_id)
    return {"ok": True, "data": order}


@router.get("/transfers")
async def api_list_transfers(
    store_id: Optional[str] = Query(None),
    employee_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """列表查询借调单（支持 store_id/employee_id/status 筛选）。"""
    conditions = ["tenant_id = :tenant_id", "is_deleted = false"]
    params: dict = {"tenant_id": uuid.UUID(x_tenant_id)}

    if store_id:
        conditions.append("(from_store_id = :store_id OR to_store_id = :store_id)")
        params["store_id"] = store_id
    if employee_id:
        conditions.append("employee_id = :employee_id")
        params["employee_id"] = employee_id
    if status:
        conditions.append("status = :status")
        params["status"] = status

    where = " AND ".join(conditions)

    try:
        count_res = await db.execute(
            text(f"SELECT COUNT(*) FROM employee_transfers WHERE {where}"),
            params,
        )
        total = count_res.scalar() or 0

        rows_res = await db.execute(
            text(f"""
                SELECT id, tenant_id, employee_id, employee_name,
                       from_store_id, from_store_name,
                       to_store_id, to_store_name,
                       start_date, end_date,
                       reason, status, approved_by, approved_at,
                       created_at, updated_at
                FROM employee_transfers
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT :size OFFSET :offset
            """),
            {**params, "size": size, "offset": (page - 1) * size},
        )
        items = [_row_to_dict(r) for r in rows_res.fetchall()]

    except SQLAlchemyError as exc:
        logger.error("transfer.list_failed", error=str(exc), tenant_id=x_tenant_id, exc_info=True)
        raise HTTPException(status_code=500, detail="查询借调单失败，请稍后重试")

    return {"ok": True, "data": {"items": items, "total": total}}


@router.post("/transfers/{transfer_id}/approve")
async def api_approve_transfer(
    transfer_id: str,
    req: ApproveTransferReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """审批借调单（pending → approved）。"""
    try:
        cur = await db.execute(
            text("""
                SELECT id, status FROM employee_transfers
                WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = false
            """),
            {"id": transfer_id, "tenant_id": uuid.UUID(x_tenant_id)},
        )
        row = cur.fetchone()
    except SQLAlchemyError as exc:
        logger.error("transfer.approve_fetch_failed", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询借调单失败，请稍后重试")

    if not row:
        raise HTTPException(status_code=404, detail="借调单不存在")

    current_status = row[1]
    if current_status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"借调单状态为 {current_status}，无法审批",
        )

    now = datetime.now(timezone.utc)

    try:
        await db.execute(
            text("""
                UPDATE employee_transfers
                SET status = 'approved',
                    approved_by = :approver_id,
                    approved_at = :now,
                    updated_at = :now
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {
                "approver_id": req.approver_id,
                "now": now,
                "id": transfer_id,
                "tenant_id": uuid.UUID(x_tenant_id),
            },
        )
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("transfer.approve_failed", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="审批借调单失败，请稍后重试")

    # 返回更新后的记录
    try:
        res = await db.execute(
            text("""
                SELECT id, tenant_id, employee_id, employee_name,
                       from_store_id, from_store_name,
                       to_store_id, to_store_name,
                       start_date, end_date,
                       reason, status, approved_by, approved_at,
                       created_at, updated_at
                FROM employee_transfers
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {"id": transfer_id, "tenant_id": uuid.UUID(x_tenant_id)},
        )
        updated = _row_to_dict(res.fetchone())
    except SQLAlchemyError as exc:
        logger.warning("transfer.approve_refetch_failed", error=str(exc))
        updated = {"id": transfer_id, "status": "approved", "approved_by": req.approver_id}

    logger.info("transfer.approved", transfer_id=transfer_id, tenant_id=x_tenant_id)
    return {"ok": True, "data": updated}


# ── 成本分摊 ──────────────────────────────────────────────────────────────────


@router.post("/cost-split")
async def api_cost_split(req: CostSplitReq) -> dict:
    """成本分摊查询（纯计算，无 DB 依赖）。"""
    attendance = [r.model_dump() for r in req.attendance_records]
    time_split = compute_time_split(req.transfers, attendance)
    salary = req.salary_data.model_dump()
    cost_split = compute_cost_split(time_split, salary)
    return {"ok": True, "data": {"time_split": time_split, "cost_split": cost_split}}


@router.post("/cost-split/report")
async def api_cost_report(req: CostReportReq) -> dict:
    """三表报告（detail/summary/analysis，纯计算，无 DB 依赖）。"""
    attendance = [r.model_dump() for r in req.attendance_records]
    time_split = compute_time_split(req.transfers, attendance)
    salary = req.salary_data.model_dump()
    cost_split = compute_cost_split(time_split, salary)

    if req.report_type == "detail":
        if not req.employee_id:
            raise HTTPException(status_code=400, detail="明细报告需要 employee_id")
        emp_time = time_split.get(req.employee_id, {})
        emp_cost = cost_split.get(req.employee_id, {})
        report = generate_detail_report(req.employee_id, emp_time, emp_cost)
        return {"ok": True, "data": report}

    if req.report_type == "summary":
        all_emp = [{"employee_id": eid, "cost_split": ecost} for eid, ecost in cost_split.items()]
        report = generate_summary_report(all_emp)
        return {"ok": True, "data": report}

    if req.report_type == "analysis":
        all_emp = [{"employee_id": eid, "cost_split": ecost} for eid, ecost in cost_split.items()]
        summary = generate_summary_report(all_emp)
        budget = req.budget_data or {}
        report = generate_cost_analysis_report(summary, budget)
        return {"ok": True, "data": report}

    raise HTTPException(status_code=400, detail=f"未知报告类型: {req.report_type}")
