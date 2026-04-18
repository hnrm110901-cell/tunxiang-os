"""
成本中心 API
GET  /api/v1/hr/cost-centers?store_id=...         树形列表
POST /api/v1/hr/cost-centers                      新建
POST /api/v1/hr/cost-centers/{id}/employees       分配员工(支持多条分摊)
GET  /api/v1/hr/cost-centers/{id}/allocation/{ym} 当月分摊快照
GET  /api/v1/hr/cost-centers/aggregate/{store_id}/{ym} 分类汇总
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..models.cost_center import CostCenter
from ..services.cost_center_service import CostCenterService

logger = structlog.get_logger()
router = APIRouter()


class CreateCostCenterReq(BaseModel):
    code: str
    name: str
    category: str
    parent_id: Optional[uuid.UUID] = None
    store_id: Optional[str] = None
    description: Optional[str] = None


class AllocationItem(BaseModel):
    cost_center_id: uuid.UUID
    allocation_pct: int
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None


class AssignEmployeeReq(BaseModel):
    employee_id: str
    allocations: List[AllocationItem]


@router.get("/hr/cost-centers")
async def list_cost_centers(
    store_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(CostCenter).where(CostCenter.is_active.is_(True))
    if store_id:
        stmt = stmt.where((CostCenter.store_id == store_id) | (CostCenter.store_id.is_(None)))
    rows = list((await db.execute(stmt)).scalars().all())
    # 简易树形：按 parent_id 分组
    nodes = {
        str(r.id): {
            "id": str(r.id),
            "code": r.code,
            "name": r.name,
            "category": r.category,
            "parent_id": str(r.parent_id) if r.parent_id else None,
            "store_id": r.store_id,
            "children": [],
        }
        for r in rows
    }
    roots = []
    for n in nodes.values():
        if n["parent_id"] and n["parent_id"] in nodes:
            nodes[n["parent_id"]]["children"].append(n)
        else:
            roots.append(n)
    return {"items": roots, "total": len(rows)}


@router.post("/hr/cost-centers")
async def create_cost_center(req: CreateCostCenterReq, db: AsyncSession = Depends(get_db)):
    svc = CostCenterService(db)
    try:
        cc = await svc.create_cost_center(
            code=req.code,
            name=req.name,
            category=req.category,
            parent_id=req.parent_id,
            store_id=req.store_id,
            description=req.description,
        )
        await db.commit()
        return {"id": str(cc.id), "code": cc.code, "name": cc.name}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/hr/cost-centers/{cc_id}/employees")
async def assign_employee(cc_id: uuid.UUID, req: AssignEmployeeReq, db: AsyncSession = Depends(get_db)):
    svc = CostCenterService(db)
    try:
        allocs = [a.model_dump() for a in req.allocations]
        rows = await svc.assign_employee(req.employee_id, allocs)
        await db.commit()
        return {"assigned": len(rows)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/hr/cost-centers/{cc_id}/allocation/{ym}")
async def get_allocation_snapshot(cc_id: uuid.UUID, ym: str, store_id: str = Query(...),
                                   db: AsyncSession = Depends(get_db)):
    svc = CostCenterService(db)
    snapshot = await svc.compute_cost_allocation(pay_month=ym, store_id=store_id)
    return snapshot.get(str(cc_id), {"labor_fen": 0, "labor_yuan": 0.0, "headcount": 0})


@router.get("/hr/cost-centers/aggregate/{store_id}/{ym}")
async def aggregate_by_category(store_id: str, ym: str, db: AsyncSession = Depends(get_db)):
    svc = CostCenterService(db)
    return await svc.aggregate_by_category(store_id=store_id, year_month=ym)
