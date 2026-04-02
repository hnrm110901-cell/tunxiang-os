"""门店借调与成本分摊 API"""
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from services.store_transfer_service import (
    approve_transfer_order,
    compute_cost_split,
    compute_time_split,
    create_transfer_order,
    generate_cost_analysis_report,
    generate_detail_report,
    generate_summary_report,
)

router = APIRouter(prefix="/api/v1/org", tags=["transfers"])

# ── 内存存储（演示用，生产环境替换为 DB） ──────────────────
_transfer_store: dict = {}  # id -> order dict


# ── 请求模型 ──────────────────────────────────────────────


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


# ── 借调单 CRUD ───────────────────────────────────────────


@router.post("/transfers")
async def api_create_transfer(req: CreateTransferReq):
    """创建借调单"""
    try:
        order = create_transfer_order(
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
        raise HTTPException(status_code=400, detail=str(e))

    _transfer_store[order["id"]] = order
    return {"ok": True, "data": order}


@router.get("/transfers")
async def api_list_transfers(
    store_id: Optional[str] = Query(None),
    employee_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    """列表查询借调单（支持 store_id/employee_id/status 筛选）"""
    items = list(_transfer_store.values())

    if store_id:
        items = [
            o for o in items
            if o["from_store_id"] == store_id or o["to_store_id"] == store_id
        ]
    if employee_id:
        items = [o for o in items if o["employee_id"] == employee_id]
    if status:
        items = [o for o in items if o["status"] == status]

    total = len(items)
    start = (page - 1) * size
    end = start + size
    paged = items[start:end]

    return {"ok": True, "data": {"items": paged, "total": total}}


@router.post("/transfers/{transfer_id}/approve")
async def api_approve_transfer(transfer_id: str, req: ApproveTransferReq):
    """审批借调单"""
    order = _transfer_store.get(transfer_id)
    if not order:
        raise HTTPException(status_code=404, detail="借调单不存在")

    try:
        updated = approve_transfer_order(order, req.approver_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _transfer_store[transfer_id] = updated
    return {"ok": True, "data": updated}


# ── 成本分摊 ──────────────────────────────────────────────


@router.post("/cost-split")
async def api_cost_split(req: CostSplitReq):
    """成本分摊查询"""
    attendance = [r.model_dump() for r in req.attendance_records]
    time_split = compute_time_split(req.transfers, attendance)
    salary = req.salary_data.model_dump()
    cost_split = compute_cost_split(time_split, salary)
    return {"ok": True, "data": {"time_split": time_split, "cost_split": cost_split}}


@router.post("/cost-split/report")
async def api_cost_report(req: CostReportReq):
    """三表报告（detail/summary/analysis）"""
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

    elif req.report_type == "summary":
        all_emp = []
        for emp_id, emp_cost in cost_split.items():
            all_emp.append({"employee_id": emp_id, "cost_split": emp_cost})
        report = generate_summary_report(all_emp)
        return {"ok": True, "data": report}

    elif req.report_type == "analysis":
        all_emp = []
        for emp_id, emp_cost in cost_split.items():
            all_emp.append({"employee_id": emp_id, "cost_split": emp_cost})
        summary = generate_summary_report(all_emp)
        budget = req.budget_data or {}
        report = generate_cost_analysis_report(summary, budget)
        return {"ok": True, "data": report}

    else:
        raise HTTPException(status_code=400, detail=f"未知报告类型: {req.report_type}")
