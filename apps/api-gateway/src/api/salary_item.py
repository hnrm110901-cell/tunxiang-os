"""
薪资项目库 API — D12 z66

端点：
  GET  /api/v1/payroll/salary-items                 列出项目
  POST /api/v1/payroll/salary-items                 创建项目
  POST /api/v1/payroll/employee-salary-items        分配给员工
  POST /api/v1/payroll/compute/{employee_id}/{pay_month}  单员工试算
  GET  /api/v1/payroll/payslip/{employee_id}/{pay_month}  查看工资条明细
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..services.salary_item_service import SalaryItemService

router = APIRouter(prefix="/api/v1/payroll", tags=["payroll-salary-items"])
logger = structlog.get_logger()


# ── Request / Response 模型 ──


class SalaryItemCreateReq(BaseModel):
    brand_id: str
    code: str = Field(..., description="全局薪资项目编码，如 ATT_001")
    name: str
    category: str = Field(..., description="attendance/leave/performance/commission/subsidy/deduction/social/welfare")
    tax_attribute: str = Field(..., description="pre_tax_add/pre_tax_deduct/after_tax_add/after_tax_deduct/non_tax")
    formula: Optional[str] = None
    formula_type: str = "fixed"  # fixed/formula/manual
    calc_order: int = 50
    store_id: Optional[str] = None
    remark: Optional[str] = None


class EmployeeSalaryItemCreateReq(BaseModel):
    employee_id: str
    brand_id: str
    item_code: str
    amount_fen: Optional[int] = None
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    remark: Optional[str] = None


class ComputeReq(BaseModel):
    context: Dict[str, Any] = Field(default_factory=dict)
    persist: bool = False


# ── 路由 ──


@router.get("/salary-items", summary="列出薪资项目")
async def list_salary_items(
    brand_id: str,
    category: Optional[str] = None,
    only_active: bool = True,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    svc = SalaryItemService(store_id=brand_id)
    items = await svc.list_salary_items(
        db, brand_id=brand_id, category=category, only_active=only_active
    )
    return {
        "brand_id": brand_id,
        "total": len(items),
        "items": [
            {
                "id": str(i.id),
                "code": i.item_code,
                "name": i.item_name,
                "category": i.item_category,
                "tax_attribute": i.tax_attribute,
                "formula": i.formula,
                "formula_type": i.formula_type,
                "calc_order": i.calc_order,
                "is_active": i.is_active,
            }
            for i in items
        ],
    }


@router.post("/salary-items", summary="创建薪资项目")
async def create_salary_item(
    req: SalaryItemCreateReq,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    svc = SalaryItemService(store_id=req.brand_id)
    try:
        item = await svc.create_salary_item(
            db,
            code=req.code,
            name=req.name,
            category=req.category,
            tax_attribute=req.tax_attribute,
            brand_id=req.brand_id,
            store_id=req.store_id,
            formula=req.formula,
            formula_type=req.formula_type,
            calc_order=req.calc_order,
            remark=req.remark,
        )
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "id": str(item.id), "code": item.item_code}


@router.post("/employee-salary-items", summary="分配薪资项目给员工")
async def assign_employee_salary_item(
    req: EmployeeSalaryItemCreateReq,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    svc = SalaryItemService(store_id=req.brand_id)
    try:
        link = await svc.assign_to_employee(
            db,
            employee_id=req.employee_id,
            brand_id=req.brand_id,
            item_code=req.item_code,
            amount_fen=req.amount_fen,
            effective_from=req.effective_from,
            effective_to=req.effective_to,
            remark=req.remark,
        )
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True, "assignment_id": str(link.id)}


@router.post("/compute/{employee_id}/{pay_month}", summary="单员工 V3 试算")
async def compute_employee(
    employee_id: str,
    pay_month: str,
    req: ComputeReq,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    if len(pay_month) != 7 or pay_month[4] != "-":
        raise HTTPException(status_code=400, detail="pay_month must be YYYY-MM")
    svc = SalaryItemService(store_id=req.context.get("store_id"))
    result = await svc.compute_employee_payroll_v3(
        db,
        employee_id=employee_id,
        pay_month=pay_month,
        context=req.context,
        persist=req.persist,
    )
    if req.persist:
        await db.commit()
    return result


@router.get("/payslip/{employee_id}/{pay_month}", summary="查看工资条明细")
async def get_payslip(
    employee_id: str,
    pay_month: str,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    sql = text(
        """
        SELECT item_code, item_name, item_category, tax_attribute, amount_fen, calc_basis
        FROM payslip_lines
        WHERE employee_id = :emp AND pay_month = :pm
        ORDER BY item_category, item_code
        """
    )
    rows = (await db.execute(sql, {"emp": employee_id, "pm": pay_month})).fetchall()
    lines: List[Dict[str, Any]] = []
    totals_fen: Dict[str, int] = {}
    for r in rows:
        code, name, cat, tax_attr, amount, basis = r
        lines.append(
            {
                "item_code": code,
                "item_name": name,
                "item_category": cat,
                "tax_attribute": tax_attr,
                "amount_fen": int(amount),
                "amount_yuan": round(int(amount) / 100.0, 2),
                "calc_basis": basis,
            }
        )
        totals_fen[tax_attr] = totals_fen.get(tax_attr, 0) + int(amount)
    return {
        "employee_id": employee_id,
        "pay_month": pay_month,
        "total_lines": len(lines),
        "lines": lines,
        "totals_fen": totals_fen,
        "totals_yuan": {k: round(v / 100.0, 2) for k, v in totals_fen.items()},
    }
