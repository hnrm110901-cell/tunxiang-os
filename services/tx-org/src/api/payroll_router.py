"""薪资计算系统 API 路由

# ROUTER REGISTRATION:
# from api.payroll_router import router as new_payroll_router
# app.include_router(new_payroll_router, prefix="/api/v1/payroll")

端点清单：
  POST /api/v1/payroll/calculate              触发月度薪资计算
  GET  /api/v1/payroll/records                薪资记录列表（按月/门店/员工筛选）
  GET  /api/v1/payroll/records/{id}           薪资记录详情
  POST /api/v1/payroll/confirm                确认当月薪资
  POST /api/v1/payroll/mark-paid              批量标记发放
  GET  /api/v1/payroll/summary                汇总统计
  GET  /api/v1/payroll/payslip/{employee_id}  个人工资条
  GET  /api/v1/payroll/attendance             考勤汇总

  GET  /api/v1/payroll/schemes                薪资方案列表
  POST /api/v1/payroll/schemes                创建方案
  PUT  /api/v1/payroll/schemes/{id}           更新方案

  GET  /api/v1/payroll/si-configs             社保配置列表（按地区）
  POST /api/v1/payroll/si-configs             新建社保配置

统一响应格式: {"ok": bool, "data": {}, "error": None}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from services.payroll_engine_db import PayrollEngine, SocialInsuranceConfig

log = structlog.get_logger(__name__)

router = APIRouter(tags=["payroll-v2"])

_engine = PayrollEngine()


# ── 辅助 ──────────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: Any) -> Dict[str, Any]:
    return {"ok": True, "data": data, "error": None}


def _uuid(value: str, field_name: str = "id") -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field_name} 格式无效: {value}")


# ── 请求模型 ──────────────────────────────────────────────────────────────────


class CalculatePayrollReq(BaseModel):
    store_id: str = Field(..., description="门店 UUID")
    year: int = Field(..., ge=2020, le=2099, description="年份")
    month: int = Field(..., ge=1, le=12, description="月份")


class ConfirmPayrollReq(BaseModel):
    year: int = Field(..., ge=2020, le=2099)
    month: int = Field(..., ge=1, le=12)
    store_id: Optional[str] = Field(None, description="指定门店（不填则确认全租户）")


class MarkPaidReq(BaseModel):
    payroll_ids: List[str] = Field(..., min_length=1, description="薪资记录 UUID 列表")


class CreateSchemeReq(BaseModel):
    name: str = Field(..., max_length=100)
    scheme_type: str = Field(..., description="monthly / hourly / commission")
    base_salary_fen: int = Field(..., ge=0, description="月薪/底薪（分）")
    hourly_rate_fen: int = Field(default=0, ge=0, description="时薪（分），时薪制必填")
    overtime_multiplier: float = Field(default=1.5, ge=1.0, description="加班倍率")


class UpdateSchemeReq(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    base_salary_fen: Optional[int] = Field(None, ge=0)
    hourly_rate_fen: Optional[int] = Field(None, ge=0)
    overtime_multiplier: Optional[float] = Field(None, ge=1.0)
    is_active: Optional[bool] = None


class CreateSIConfigReq(BaseModel):
    region: str = Field(..., max_length=50, description="地区标识，如 changsha")
    pension_rate_employee: float = Field(default=0.08, ge=0, le=1)
    pension_rate_employer: float = Field(default=0.16, ge=0, le=1)
    medical_rate_employee: float = Field(default=0.02, ge=0, le=1)
    medical_rate_employer: float = Field(default=0.08, ge=0, le=1)
    unemployment_rate_employee: float = Field(default=0.005, ge=0, le=1)
    unemployment_rate_employer: float = Field(default=0.005, ge=0, le=1)
    housing_fund_rate: float = Field(default=0.07, ge=0.05, le=0.12)
    effective_from: str = Field(..., description="生效日期 YYYY-MM-DD")


# ── 薪资计算 ──────────────────────────────────────────────────────────────────


@router.post("/calculate")
async def calculate_payroll(
    req: CalculatePayrollReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """触发月度薪资计算

    读取门店当月考勤和员工薪资配置，批量计算并以草稿状态写入 payroll_records_v2。
    已处于 confirmed/paid 状态的记录不会被覆盖。
    """
    tenant_id = _uuid(_get_tenant_id(request), "X-Tenant-ID")
    store_id = _uuid(req.store_id, "store_id")

    try:
        records = await _engine.calculate_monthly_payroll(
            db, tenant_id, store_id, req.year, req.month
        )
    except Exception as exc:
        log.error("payroll.calculate.error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail=f"薪资计算失败: {exc}") from exc

    await db.commit()
    return _ok({
        "year": req.year,
        "month": req.month,
        "store_id": req.store_id,
        "calculated_count": len(records),
        "records": [
            {
                "employee_id": str(r.employee_id),
                "gross_salary_fen": r.gross_salary_fen,
                "net_salary_fen": r.net_salary_fen,
                "status": r.status,
            }
            for r in records
        ],
    })


# ── 薪资记录 ──────────────────────────────────────────────────────────────────


@router.get("/records")
async def list_payroll_records(
    request: Request,
    year: int = Query(..., ge=2020, le=2099),
    month: int = Query(..., ge=1, le=12),
    store_id: Optional[str] = Query(None),
    employee_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="draft / confirmed / paid"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """薪资记录列表（支持按年月/门店/员工/状态筛选，分页）"""
    tenant_id = _get_tenant_id(request)

    filters: List[str] = [
        "tenant_id = :tenant_id",
        "period_year = :year",
        "period_month = :month",
        "is_deleted = FALSE",
    ]
    params: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "year": year,
        "month": month,
        "offset": (page - 1) * size,
        "limit": size,
    }
    if store_id:
        filters.append("store_id = :store_id")
        params["store_id"] = store_id
    if employee_id:
        filters.append("employee_id = :employee_id")
        params["employee_id"] = employee_id
    if status:
        filters.append("status = :status")
        params["status"] = status

    where = " AND ".join(filters)

    count_row = await db.execute(
        text(f"SELECT COUNT(*) FROM payroll_records_v2 WHERE {where}"),
        params,
    )
    total: int = count_row.scalar_one()

    rows = await db.execute(
        text(f"""
            SELECT * FROM payroll_records_v2
            WHERE {where}
            ORDER BY employee_id
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    items = [dict(r) for r in rows.mappings().all()]

    return _ok({"items": items, "total": total, "page": page, "size": size})


@router.get("/records/{record_id}")
async def get_payroll_record(
    record_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """薪资记录详情"""
    tenant_id = _get_tenant_id(request)
    _uuid(record_id, "record_id")

    row = await db.execute(
        text("""
            SELECT * FROM payroll_records_v2
            WHERE tenant_id = :tenant_id
              AND id = :id
              AND is_deleted = FALSE
        """),
        {"tenant_id": tenant_id, "id": record_id},
    )
    mapping = row.mappings().first()
    if not mapping:
        raise HTTPException(status_code=404, detail=f"薪资记录不存在: {record_id}")
    return _ok(dict(mapping))


# ── 状态流转 ──────────────────────────────────────────────────────────────────


@router.post("/confirm")
async def confirm_payroll(
    req: ConfirmPayrollReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """确认当月薪资（draft → confirmed）"""
    tenant_id = _uuid(_get_tenant_id(request), "X-Tenant-ID")
    store_uuid = _uuid(req.store_id, "store_id") if req.store_id else None

    count = await _engine.confirm_payroll(db, tenant_id, req.year, req.month, store_uuid)
    await db.commit()
    return _ok({"confirmed_count": count, "year": req.year, "month": req.month})


@router.post("/mark-paid")
async def mark_paid(
    req: MarkPaidReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """批量标记薪资已发放（confirmed → paid）"""
    tenant_id = _uuid(_get_tenant_id(request), "X-Tenant-ID")
    payroll_uuids = [_uuid(pid, "payroll_id") for pid in req.payroll_ids]

    count = await _engine.mark_paid(db, tenant_id, payroll_uuids)
    await db.commit()
    return _ok({"paid_count": count, "requested": len(payroll_uuids)})


# ── 汇总 & 工资条 ─────────────────────────────────────────────────────────────


@router.get("/summary")
async def get_payroll_summary(
    request: Request,
    store_id: str = Query(...),
    year: int = Query(..., ge=2020, le=2099),
    month: int = Query(..., ge=1, le=12),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """薪资汇总统计（总人数、总薪资、社保合计、实发合计，按岗位分组）"""
    tenant_id = _uuid(_get_tenant_id(request), "X-Tenant-ID")
    store_uuid = _uuid(store_id, "store_id")

    summary = await _engine.get_payroll_summary(db, tenant_id, store_uuid, year, month)
    return _ok({
        "tenant_id": str(summary.tenant_id),
        "store_id": str(summary.store_id),
        "year": summary.period_year,
        "month": summary.period_month,
        "employee_count": summary.employee_count,
        "total_gross_fen": summary.total_gross_fen,
        "total_gross_yuan": round(summary.total_gross_fen / 100, 2),
        "total_net_fen": summary.total_net_fen,
        "total_net_yuan": round(summary.total_net_fen / 100, 2),
        "total_si_fen": summary.total_si_fen,
        "total_si_yuan": round(summary.total_si_fen / 100, 2),
        "by_position": summary.by_position,
    })


@router.get("/payslip/{employee_id}")
async def get_payslip(
    employee_id: str,
    request: Request,
    year: int = Query(..., ge=2020, le=2099),
    month: int = Query(..., ge=1, le=12),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """个人工资条详情"""
    tenant_id = _uuid(_get_tenant_id(request), "X-Tenant-ID")
    emp_uuid = _uuid(employee_id, "employee_id")

    payslip = await _engine.get_employee_payslip(db, tenant_id, emp_uuid, year, month)
    if not payslip:
        raise HTTPException(
            status_code=404,
            detail=f"工资条不存在: employee_id={employee_id}, {year}-{month:02d}",
        )
    return _ok({
        "employee_id": str(payslip.employee_id),
        "period": f"{payslip.period_year}-{payslip.period_month:02d}",
        "status": payslip.record.status,
        "gross_salary_fen": payslip.record.gross_salary_fen,
        "gross_salary_yuan": round(payslip.record.gross_salary_fen / 100, 2),
        "net_salary_fen": payslip.record.net_salary_fen,
        "net_salary_yuan": round(payslip.record.net_salary_fen / 100, 2),
        "items": payslip.items,
    })


@router.get("/attendance")
async def get_attendance_summary(
    request: Request,
    store_id: str = Query(...),
    year: int = Query(..., ge=2020, le=2099),
    month: int = Query(..., ge=1, le=12),
    employee_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """考勤汇总（门店月度考勤统计，可按员工筛选）"""
    tenant_id = _get_tenant_id(request)

    filters = [
        "ar.tenant_id = :tenant_id",
        "e.store_id = :store_id",
        "EXTRACT(YEAR FROM ar.work_date) = :year",
        "EXTRACT(MONTH FROM ar.work_date) = :month",
        "ar.is_deleted = FALSE",
        "e.is_deleted = FALSE",
    ]
    params: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "store_id": store_id,
        "year": year,
        "month": month,
    }
    if employee_id:
        filters.append("ar.employee_id = :employee_id")
        params["employee_id"] = employee_id

    where = " AND ".join(filters)
    rows = await db.execute(
        text(f"""
            SELECT
                ar.employee_id,
                COUNT(*) FILTER (WHERE ar.absence_type IS NULL)  AS work_days,
                COALESCE(SUM(ar.work_hours), 0)                  AS work_hours,
                COALESCE(SUM(ar.overtime_hours), 0)              AS overtime_hours,
                COUNT(*) FILTER (WHERE ar.absence_type IS NOT NULL) AS absent_days,
                COUNT(*) FILTER (WHERE ar.absence_type = 'sick')    AS sick_leave_days,
                COUNT(*) FILTER (WHERE ar.absence_type = 'annual')  AS annual_leave_days
            FROM attendance_records ar
            JOIN employees e
                   ON e.id = ar.employee_id
                  AND e.tenant_id = ar.tenant_id
            WHERE {where}
            GROUP BY ar.employee_id
            ORDER BY ar.employee_id
        """),
        params,
    )
    items = [dict(r) for r in rows.mappings().all()]
    return _ok({"items": items, "total": len(items), "year": year, "month": month})


# ── 薪资方案 ──────────────────────────────────────────────────────────────────


@router.get("/schemes")
async def list_salary_schemes(
    request: Request,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """薪资方案列表"""
    tenant_id = _get_tenant_id(request)

    count_row = await db.execute(
        text("SELECT COUNT(*) FROM salary_schemes WHERE tenant_id = :tid AND is_deleted = FALSE"),
        {"tid": tenant_id},
    )
    total: int = count_row.scalar_one()

    rows = await db.execute(
        text("""
            SELECT * FROM salary_schemes
            WHERE tenant_id = :tid AND is_deleted = FALSE
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        {"tid": tenant_id, "limit": size, "offset": (page - 1) * size},
    )
    items = [dict(r) for r in rows.mappings().all()]
    return _ok({"items": items, "total": total, "page": page, "size": size})


@router.post("/schemes")
async def create_salary_scheme(
    req: CreateSchemeReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """创建薪资方案"""
    tenant_id = _get_tenant_id(request)

    if req.scheme_type not in ("monthly", "hourly", "commission"):
        raise HTTPException(status_code=400, detail="scheme_type 必须为 monthly/hourly/commission")

    if req.scheme_type == "hourly" and req.hourly_rate_fen == 0:
        raise HTTPException(status_code=400, detail="时薪制方案 hourly_rate_fen 不能为 0")

    row = await db.execute(
        text("""
            INSERT INTO salary_schemes (
                tenant_id, name, scheme_type,
                base_salary_fen, hourly_rate_fen, overtime_multiplier
            ) VALUES (
                :tenant_id, :name, :scheme_type,
                :base_salary_fen, :hourly_rate_fen, :overtime_multiplier
            )
            RETURNING *
        """),
        {
            "tenant_id": tenant_id,
            "name": req.name,
            "scheme_type": req.scheme_type,
            "base_salary_fen": req.base_salary_fen,
            "hourly_rate_fen": req.hourly_rate_fen,
            "overtime_multiplier": req.overtime_multiplier,
        },
    )
    await db.commit()
    created = dict(row.mappings().one())
    return _ok(created)


@router.put("/schemes/{scheme_id}")
async def update_salary_scheme(
    scheme_id: str,
    req: UpdateSchemeReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """更新薪资方案（仅更新提供的字段）"""
    tenant_id = _get_tenant_id(request)
    _uuid(scheme_id, "scheme_id")

    # 确认存在
    exists = await db.execute(
        text("""
            SELECT id FROM salary_schemes
            WHERE tenant_id = :tenant_id AND id = :id AND is_deleted = FALSE
        """),
        {"tenant_id": tenant_id, "id": scheme_id},
    )
    if not exists.first():
        raise HTTPException(status_code=404, detail=f"薪资方案不存在: {scheme_id}")

    set_parts: List[str] = ["updated_at = NOW()"]
    params: Dict[str, Any] = {"tenant_id": tenant_id, "id": scheme_id}

    if req.name is not None:
        set_parts.append("name = :name")
        params["name"] = req.name
    if req.base_salary_fen is not None:
        set_parts.append("base_salary_fen = :base_salary_fen")
        params["base_salary_fen"] = req.base_salary_fen
    if req.hourly_rate_fen is not None:
        set_parts.append("hourly_rate_fen = :hourly_rate_fen")
        params["hourly_rate_fen"] = req.hourly_rate_fen
    if req.overtime_multiplier is not None:
        set_parts.append("overtime_multiplier = :overtime_multiplier")
        params["overtime_multiplier"] = req.overtime_multiplier
    if req.is_active is not None:
        set_parts.append("is_active = :is_active")
        params["is_active"] = req.is_active

    row = await db.execute(
        text(f"""
            UPDATE salary_schemes
            SET {', '.join(set_parts)}
            WHERE tenant_id = :tenant_id AND id = :id AND is_deleted = FALSE
            RETURNING *
        """),
        params,
    )
    await db.commit()
    updated = dict(row.mappings().one())
    return _ok(updated)


# ── 社保配置 ──────────────────────────────────────────────────────────────────


@router.get("/si-configs")
async def list_si_configs(
    request: Request,
    region: Optional[str] = Query(None, description="按地区筛选"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """社保配置列表（按地区筛选）"""
    tenant_id = _get_tenant_id(request)

    filters = ["tenant_id = :tenant_id", "is_deleted = FALSE"]
    params: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "limit": size,
        "offset": (page - 1) * size,
    }
    if region:
        filters.append("region = :region")
        params["region"] = region

    where = " AND ".join(filters)
    count_row = await db.execute(
        text(f"SELECT COUNT(*) FROM social_insurance_configs WHERE {where}"),
        params,
    )
    total: int = count_row.scalar_one()

    rows = await db.execute(
        text(f"""
            SELECT * FROM social_insurance_configs
            WHERE {where}
            ORDER BY region, effective_from DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    items = [dict(r) for r in rows.mappings().all()]
    return _ok({"items": items, "total": total, "page": page, "size": size})


@router.post("/si-configs")
async def create_si_config(
    req: CreateSIConfigReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """新建社保配置"""
    tenant_id = _get_tenant_id(request)

    row = await db.execute(
        text("""
            INSERT INTO social_insurance_configs (
                tenant_id, region,
                pension_rate_employee, pension_rate_employer,
                medical_rate_employee, medical_rate_employer,
                unemployment_rate_employee, unemployment_rate_employer,
                housing_fund_rate, effective_from
            ) VALUES (
                :tenant_id, :region,
                :pension_emp, :pension_er,
                :medical_emp, :medical_er,
                :unemp_emp, :unemp_er,
                :hf_rate, :effective_from
            )
            RETURNING *
        """),
        {
            "tenant_id": tenant_id,
            "region": req.region,
            "pension_emp": req.pension_rate_employee,
            "pension_er": req.pension_rate_employer,
            "medical_emp": req.medical_rate_employee,
            "medical_er": req.medical_rate_employer,
            "unemp_emp": req.unemployment_rate_employee,
            "unemp_er": req.unemployment_rate_employer,
            "hf_rate": req.housing_fund_rate,
            "effective_from": req.effective_from,
        },
    )
    await db.commit()
    created = dict(row.mappings().one())
    return _ok(created)
