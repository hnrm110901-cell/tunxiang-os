"""借调管理 API 路由（DB 持久化版）

端点列表：
  POST   /api/v1/transfers                   创建借调单
  GET    /api/v1/transfers                   列表查询
  GET    /api/v1/transfers/{transfer_id}     借调单详情
  PUT    /api/v1/transfers/{transfer_id}/approve   审批
  PUT    /api/v1/transfers/{transfer_id}/complete   完成借调
  PUT    /api/v1/transfers/{transfer_id}/cancel     取消
  POST   /api/v1/transfers/compute-allocation       计算月度成本分摊
  GET    /api/v1/transfers/cost-report              成本分摊报表

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.transfer_cost_engine import TransferCostEngine

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/transfers", tags=["transfers"])


# ── 辅助函数 ──────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail={"error": "missing tenant_id"})
    return str(tid).strip()


def _ok(data: object) -> dict:
    return {"ok": True, "data": data}


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


# ── 请求模型 ──────────────────────────────────────────────


class CreateTransferReq(BaseModel):
    employee_id: str
    employee_name: str
    from_store_id: str
    from_store_name: str
    to_store_id: str
    to_store_name: str
    start_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    transfer_type: str = "temporary"
    reason: str = ""


class ApproveReq(BaseModel):
    approver_id: str


class ComputeAllocationReq(BaseModel):
    employee_id: str
    month: str = Field(..., pattern=r"^\d{4}-\d{2}$")
    salary_data: dict = Field(
        ...,
        description="{"
        '"base_fen": int, "overtime_fen": int, "social_fen": int, "bonus_fen": int'
        "}",
    )


# ── 借调单 CRUD ──────────────────────────────────────────


@router.post("")
async def create_transfer(
    req: CreateTransferReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建借调单。"""
    tid = _get_tenant_id(request)
    await _set_tenant(db, tid)
    engine = TransferCostEngine(db, tid)
    try:
        order = await engine.create_transfer(
            employee_id=req.employee_id,
            employee_name=req.employee_name,
            from_store_id=req.from_store_id,
            from_store_name=req.from_store_name,
            to_store_id=req.to_store_id,
            to_store_name=req.to_store_name,
            start_date=req.start_date,
            end_date=req.end_date,
            transfer_type=req.transfer_type,
            reason=req.reason,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"error": str(e)})
    return _ok(order)


@router.get("")
async def list_transfers(
    request: Request,
    store_id: Optional[str] = Query(None),
    employee_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """列表查询借调单。"""
    tid = _get_tenant_id(request)
    await _set_tenant(db, tid)
    engine = TransferCostEngine(db, tid)
    result = await engine.list_transfers(
        store_id=store_id,
        employee_id=employee_id,
        status=status,
        page=page,
        size=size,
    )
    return _ok(result)


@router.get("/cost-report")
async def cost_report(
    request: Request,
    store_id: str = Query(...),
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """成本分摊报表（三表合一）。"""
    tid = _get_tenant_id(request)
    await _set_tenant(db, tid)
    engine = TransferCostEngine(db, tid)
    report = await engine.get_store_transfer_report(store_id=store_id, month=month)
    return _ok(report)


@router.get("/{transfer_id}")
async def get_transfer(
    transfer_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """借调单详情。"""
    tid = _get_tenant_id(request)
    await _set_tenant(db, tid)
    engine = TransferCostEngine(db, tid)
    order = await engine.get_transfer(transfer_id)
    if not order:
        raise HTTPException(status_code=404, detail={"error": "借调单不存在"})
    return _ok(order)


@router.put("/{transfer_id}/approve")
async def approve_transfer(
    transfer_id: str,
    req: ApproveReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """审批借调单。"""
    tid = _get_tenant_id(request)
    await _set_tenant(db, tid)
    engine = TransferCostEngine(db, tid)
    try:
        order = await engine.approve_transfer(transfer_id, req.approver_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"error": str(e)})
    return _ok(order)


@router.put("/{transfer_id}/complete")
async def complete_transfer(
    transfer_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """完成借调。"""
    tid = _get_tenant_id(request)
    await _set_tenant(db, tid)
    engine = TransferCostEngine(db, tid)
    try:
        order = await engine.complete_transfer(transfer_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"error": str(e)})
    return _ok(order)


@router.put("/{transfer_id}/cancel")
async def cancel_transfer(
    transfer_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """取消借调。"""
    tid = _get_tenant_id(request)
    await _set_tenant(db, tid)
    engine = TransferCostEngine(db, tid)
    try:
        order = await engine.cancel_transfer(transfer_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"error": str(e)})
    return _ok(order)


@router.post("/compute-allocation")
async def compute_allocation(
    req: ComputeAllocationReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """计算月度成本分摊。"""
    tid = _get_tenant_id(request)
    await _set_tenant(db, tid)
    engine = TransferCostEngine(db, tid)
    result = await engine.compute_monthly_allocation(
        employee_id=req.employee_id,
        month=req.month,
        salary_data=req.salary_data,
    )
    return _ok(result)
