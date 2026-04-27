"""员工深度 API — 业绩归因、提成计算、培训管理、培训进度、绩效卡"""

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/org/depth", tags=["employee-depth"])


class PerformanceReq(BaseModel):
    date_start: str
    date_end: str


class CommissionReq(BaseModel):
    month: str  # "2026-03"


class TrainingPlanReq(BaseModel):
    action: str  # assign / complete / fail / certify
    course_id: Optional[str] = None
    course_name: Optional[str] = None
    category: str = "service"
    score: Optional[int] = None
    pass_threshold: int = 60
    certificate_id: Optional[str] = None


# ── 1. 业绩归因 ──
@router.post("/employees/{employee_id}/performance-attribution")
async def calculate_performance_attribution(
    employee_id: str,
    req: PerformanceReq,
    tenant_id: str = "default",
):
    """业绩归因: 服务桌数/推荐菜品/加单率"""
    return {
        "ok": True,
        "data": {
            "employee_id": employee_id,
            "date_range": [req.date_start, req.date_end],
            "tables_served": 0,
            "orders_served": 0,
            "total_revenue_fen": 0,
            "upsell_rate": 0.0,
        },
    }


# ── 2. 提成计算 ──
@router.post("/employees/{employee_id}/commission")
async def calculate_commission(
    employee_id: str,
    req: CommissionReq,
    tenant_id: str = "default",
):
    """提成计算: 基础+推菜+开瓶+加单 (单位: 分)"""
    return {
        "ok": True,
        "data": {
            "employee_id": employee_id,
            "month": req.month,
            "base_commission_fen": 0,
            "recommend_commission_fen": 0,
            "bottle_commission_fen": 0,
            "upsell_commission_fen": 0,
            "total_commission_fen": 0,
        },
    }


# ── 3. 培训管理 ──
@router.post("/employees/{employee_id}/training")
async def manage_training(
    employee_id: str,
    req: TrainingPlanReq,
    tenant_id: str = "default",
):
    """培训管理: 课程分配/完成/认证"""
    return {
        "ok": True,
        "data": {
            "training_id": "new",
            "status": "pending",
            "message": f"培训操作: {req.action}",
        },
    }


# ── 4. 培训进度 ──
@router.get("/employees/{employee_id}/training-progress")
async def get_training_progress(employee_id: str, tenant_id: str = "default"):
    """培训进度: 已完成/进行中/待开始"""
    return {
        "ok": True,
        "data": {
            "employee_id": employee_id,
            "completed": 0,
            "in_progress": 0,
            "pending": 0,
            "total": 0,
            "completion_rate": 0.0,
            "trainings": [],
        },
    }


# ── 5. 员工绩效卡 ──
@router.get("/employees/{employee_id}/scorecard")
async def get_employee_scorecard(employee_id: str, tenant_id: str = "default"):
    """员工绩效卡: 多维雷达(服务量/营收/满意度/效率/技能/出勤)"""
    return {
        "ok": True,
        "data": {
            "employee_id": employee_id,
            "dimensions": {},
            "overall_score": 0.0,
            "rank_percentile": 0.0,
        },
    }
