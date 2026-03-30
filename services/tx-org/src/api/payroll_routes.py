"""薪资计算 API 路由

# ROUTER REGISTRATION:
# from .api.payroll_routes import router as payroll_router
# app.include_router(payroll_router, prefix="/api/v1/payroll")

端点列表：
  POST /payroll/compute/{employee_id}     - 计算单人工资
  POST /payroll/batch/{store_id}          - 批量计算
  GET  /payroll/{employee_id}/{month}     - 查询工资单
  POST /payroll/{record_id}/confirm       - 确认工资单
  POST /payroll/{record_id}/pay           - 标记已发放
  GET  /payroll/store/{store_id}/{month}  - 门店月度汇总
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from services.payroll_engine_v2 import PayrollEngine
from models.payroll_record import PayrollRecord, PayrollRecordStatus, StoreSalarySummary


router = APIRouter(tags=["payroll"])

# 内存存储（生产环境替换为 DB）
# key: "{tenant_id}:{employee_id}:{month}" -> PayrollRecord
_records_store: Dict[str, PayrollRecord] = {}
# key: "{tenant_id}:{store_id}:{month}" -> StoreSalarySummary
_summaries_store: Dict[str, StoreSalarySummary] = {}


def _get_engine(city: str = "changsha") -> PayrollEngine:
    return PayrollEngine(city=city)


def _record_key(tenant_id: str, employee_id: str, month: str) -> str:
    return f"{tenant_id}:{employee_id}:{month}"


def _summary_key(tenant_id: str, store_id: str, month: str) -> str:
    return f"{tenant_id}:{store_id}:{month}"


# ── 请求模型 ─────────────────────────────────────────────────────────────────


class ComputePayrollReq(BaseModel):
    store_id: str = Field(..., description="门店 ID")
    payroll_month: str = Field(..., pattern=r"^\d{4}-\d{2}$", description="薪资月份 YYYY-MM")

    # 薪资方案
    base_salary_fen: int = Field(..., ge=0, description="月薪标准（分）")
    work_days_in_month: Optional[int] = Field(None, ge=1, le=31, description="当月工作日数，None 时自动计算")

    # 考勤
    attendance_days: int = Field(default=0, ge=0, description="实际出勤天数")
    absence_days: float = Field(default=0, ge=0, description="缺勤天数")
    late_count: int = Field(default=0, ge=0, description="迟到次数")
    early_leave_count: int = Field(default=0, ge=0, description="早退次数")
    late_deduction_per_time_fen: int = Field(default=5_000, ge=0, description="每次迟到扣款（分）")
    early_leave_deduction_per_time_fen: int = Field(default=5_000, ge=0, description="每次早退扣款（分）")

    # 加班
    overtime_weekday_hours: float = Field(default=0, ge=0, description="工作日加班小时数")
    overtime_weekend_hours: float = Field(default=0, ge=0, description="周末加班小时数")
    overtime_holiday_hours: float = Field(default=0, ge=0, description="法定节假日加班小时数")

    # 提成
    sales_amount_fen: int = Field(default=0, ge=0, description="当月销售额（分）")
    commission_rate: float = Field(default=0.0, ge=0, le=1, description="提成比例")

    # 绩效
    performance_coefficient: float = Field(default=1.0, ge=0, description="绩效系数（1.0=无奖金）")
    seniority_months: int = Field(default=0, ge=0, description="司龄月数")
    full_attendance_bonus_fen: int = Field(default=30_000, ge=0, description="全勤奖金额（分）")

    # 补贴
    position_allowance_fen: int = Field(default=0, ge=0, description="岗位补贴（分）")
    meal_allowance_fen: int = Field(default=0, ge=0, description="餐补（分）")
    transport_allowance_fen: int = Field(default=0, ge=0, description="交通补贴（分）")
    extra_bonus_fen: int = Field(default=0, ge=0, description="其他奖金（分）")

    # 社保配置
    housing_fund_rate: Optional[float] = Field(None, ge=0.05, le=0.12, description="公积金个人比例覆盖")
    city: str = Field(default="changsha", description="城市（社保费率）")
    city_config: Optional[Dict[str, Any]] = Field(None, description="城市费率额外覆盖")

    # 个税累计数据
    ytd_income_yuan: float = Field(default=0.0, ge=0, description="年初至今累计收入（元）")
    ytd_tax_paid_yuan: float = Field(default=0.0, ge=0, description="年初至今已预缴税款（元）")
    ytd_social_insurance_yuan: float = Field(default=0.0, ge=0, description="年初至今社保+公积金个人部分（元）")
    month_index: int = Field(default=1, ge=1, le=12, description="当年第几个月")
    special_deduction_monthly_yuan: float = Field(default=0.0, ge=0, description="月专项附加扣除（元）")


class BatchComputeReq(BaseModel):
    payroll_month: str = Field(..., pattern=r"^\d{4}-\d{2}$")
    city: str = Field(default="changsha")
    employees: List[Dict[str, Any]] = Field(..., description="员工参数列表，每项含 employee_id + ComputePayrollReq 字段")


# ── 端点 ─────────────────────────────────────────────────────────────────────


@router.post("/compute/{employee_id}")
async def compute_employee_payroll(
    employee_id: str,
    req: ComputePayrollReq,
    x_tenant_id: str = Header(..., description="租户 ID"),
) -> Dict[str, Any]:
    """计算单个员工当月工资

    计算结果以草稿状态保存，返回完整薪资明细（含五险一金分项和个税明细）。
    """
    engine = _get_engine(city=req.city)
    try:
        record = engine.compute_monthly(
            tenant_id=x_tenant_id,
            employee_id=employee_id,
            store_id=req.store_id,
            payroll_month=req.payroll_month,
            base_salary_fen=req.base_salary_fen,
            work_days_in_month=req.work_days_in_month,
            attendance_days=req.attendance_days,
            absence_days=req.absence_days,
            late_count=req.late_count,
            early_leave_count=req.early_leave_count,
            late_deduction_per_time_fen=req.late_deduction_per_time_fen,
            early_leave_deduction_per_time_fen=req.early_leave_deduction_per_time_fen,
            overtime_weekday_hours=req.overtime_weekday_hours,
            overtime_weekend_hours=req.overtime_weekend_hours,
            overtime_holiday_hours=req.overtime_holiday_hours,
            sales_amount_fen=req.sales_amount_fen,
            commission_rate=req.commission_rate,
            performance_coefficient=req.performance_coefficient,
            seniority_months=req.seniority_months,
            full_attendance_bonus_fen=req.full_attendance_bonus_fen,
            position_allowance_fen=req.position_allowance_fen,
            meal_allowance_fen=req.meal_allowance_fen,
            transport_allowance_fen=req.transport_allowance_fen,
            extra_bonus_fen=req.extra_bonus_fen,
            housing_fund_rate=req.housing_fund_rate,
            city_config=req.city_config,
            ytd_income_yuan=req.ytd_income_yuan,
            ytd_tax_paid_yuan=req.ytd_tax_paid_yuan,
            ytd_social_insurance_yuan=req.ytd_social_insurance_yuan,
            month_index=req.month_index,
            special_deduction_monthly_yuan=req.special_deduction_monthly_yuan,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    key = _record_key(x_tenant_id, employee_id, req.payroll_month)
    _records_store[key] = record

    return {"ok": True, "data": record.to_dict()}


@router.post("/batch/{store_id}")
async def batch_compute_payroll(
    store_id: str,
    req: BatchComputeReq,
    x_tenant_id: str = Header(..., description="租户 ID"),
) -> Dict[str, Any]:
    """批量计算门店所有员工工资

    employees 列表中每项需包含 employee_id 字段及其他薪资参数。
    """
    if not req.employees:
        raise HTTPException(status_code=400, detail="employees 列表不能为空")

    engine = _get_engine(city=req.city)
    summary = engine.batch_compute(
        tenant_id=x_tenant_id,
        store_id=store_id,
        payroll_month=req.payroll_month,
        employees=req.employees,
    )

    # 缓存汇总和各员工记录
    s_key = _summary_key(x_tenant_id, store_id, req.payroll_month)
    _summaries_store[s_key] = summary
    for record in summary.records:
        r_key = _record_key(x_tenant_id, str(record.employee_id), req.payroll_month)
        _records_store[r_key] = record

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "payroll_month": req.payroll_month,
            "employee_count": summary.employee_count,
            "total_gross_yuan": summary.total_gross_yuan,
            "total_net_yuan": summary.total_net_yuan,
            "total_labor_cost_yuan": summary.total_labor_cost_yuan,
            "records": [r.to_dict() for r in summary.records],
        },
    }


@router.get("/{employee_id}/{month}")
async def get_payroll_record(
    employee_id: str,
    month: str,
    x_tenant_id: str = Header(..., description="租户 ID"),
) -> Dict[str, Any]:
    """查询员工工资单"""
    key = _record_key(x_tenant_id, employee_id, month)
    record = _records_store.get(key)
    if not record:
        raise HTTPException(
            status_code=404,
            detail=f"工资单不存在: employee={employee_id}, month={month}",
        )
    return {"ok": True, "data": record.to_dict()}


@router.post("/{record_id}/confirm")
async def confirm_payroll(
    record_id: str,
    x_tenant_id: str = Header(..., description="租户 ID"),
) -> Dict[str, Any]:
    """确认工资单（草稿 → 已确认）

    record_id 格式："{employee_id}:{month}"
    """
    parts = record_id.split(":")
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail="record_id 格式错误，应为 {employee_id}:{month}")
    employee_id, month = parts[0], parts[1]
    key = _record_key(x_tenant_id, employee_id, month)
    record = _records_store.get(key)
    if not record:
        raise HTTPException(status_code=404, detail=f"工资单不存在: {record_id}")

    try:
        record.confirm()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "data": {"record_id": record_id, "status": record.status, "confirmed_at": record.confirmed_at}}


@router.post("/{record_id}/pay")
async def mark_payroll_paid(
    record_id: str,
    x_tenant_id: str = Header(..., description="租户 ID"),
) -> Dict[str, Any]:
    """标记工资单已发放（已确认 → 已发放）

    record_id 格式："{employee_id}:{month}"
    """
    parts = record_id.split(":")
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail="record_id 格式错误，应为 {employee_id}:{month}")
    employee_id, month = parts[0], parts[1]
    key = _record_key(x_tenant_id, employee_id, month)
    record = _records_store.get(key)
    if not record:
        raise HTTPException(status_code=404, detail=f"工资单不存在: {record_id}")

    try:
        record.mark_paid()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "data": {"record_id": record_id, "status": record.status, "paid_at": record.paid_at}}


@router.get("/store/{store_id}/{month}")
async def get_store_payroll_summary(
    store_id: str,
    month: str,
    x_tenant_id: str = Header(..., description="租户 ID"),
) -> Dict[str, Any]:
    """查询门店月度薪资汇总"""
    key = _summary_key(x_tenant_id, store_id, month)
    summary = _summaries_store.get(key)
    if not summary:
        raise HTTPException(
            status_code=404,
            detail=f"门店月度薪资汇总不存在: store={store_id}, month={month}",
        )
    return {
        "ok": True,
        "data": {
            "store_id": summary.store_id,
            "payroll_month": summary.payroll_month,
            "employee_count": summary.employee_count,
            "total_gross_yuan": summary.total_gross_yuan,
            "total_net_yuan": summary.total_net_yuan,
            "total_social_insurance_personal_yuan": summary.total_social_insurance_personal_yuan,
            "total_social_insurance_company_yuan": summary.total_social_insurance_company_yuan,
            "total_income_tax_yuan": summary.total_income_tax_yuan,
            "total_labor_cost_yuan": summary.total_labor_cost_yuan,
        },
    }
