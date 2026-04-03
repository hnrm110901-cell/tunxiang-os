"""员工管理 API"""
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/org", tags=["org"])


class CreateEmployeeReq(BaseModel):
    emp_name: str
    role: str
    store_id: str
    phone: Optional[str] = None


# 员工 CRUD
@router.get("/employees")
async def list_employees(store_id: str, role: Optional[str] = None, page: int = 1, size: int = 20):
    return {"ok": True, "data": {"items": [], "total": 0}}

@router.post("/employees")
async def create_employee(req: CreateEmployeeReq):
    return {"ok": True, "data": {"employee_id": "new"}}

@router.get("/employees/{emp_id}")
async def get_employee(emp_id: str):
    return {"ok": True, "data": None}

@router.patch("/employees/{emp_id}")
async def update_employee(emp_id: str, data: dict):
    return {"ok": True, "data": {"updated": True}}

# 绩效
@router.get("/employees/{emp_id}/performance")
async def get_performance(emp_id: str, period: str = "month"):
    return {"ok": True, "data": {"score": 0, "commission_fen": 0}}

@router.post("/performance/compute")
async def compute_performance(store_id: str, period: str):
    """批量计算门店绩效"""
    return {"ok": True, "data": {"computed": True}}

# 人力成本
@router.get("/labor-cost")
async def get_labor_cost(store_id: str, month: Optional[str] = None):
    return {"ok": True, "data": {"cost_rate": 0, "total_fen": 0}}

@router.get("/labor-cost/ranking")
async def get_labor_cost_ranking(brand_id: Optional[str] = None):
    return {"ok": True, "data": {"rankings": []}}

# 考勤
@router.get("/attendance")
async def get_attendance(store_id: str, date: Optional[str] = None):
    return {"ok": True, "data": {"records": []}}

@router.post("/attendance/clock-in")
async def clock_in(emp_id: str, store_id: str):
    return {"ok": True, "data": {"clocked_in": True}}

# 培训
@router.get("/training/plans")
async def list_training_plans(store_id: str):
    return {"ok": True, "data": {"plans": []}}

@router.get("/employees/{emp_id}/skill-gaps")
async def get_skill_gaps(emp_id: str):
    return {"ok": True, "data": {"gaps": []}}

# 离职预测
@router.get("/turnover-risk")
async def get_turnover_risk(store_id: str):
    return {"ok": True, "data": {"at_risk": []}}

# 组织架构
@router.get("/hierarchy")
async def get_org_hierarchy(brand_id: Optional[str] = None):
    return {"ok": True, "data": {"hierarchy": {}}}
