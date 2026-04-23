"""薪资计算引擎 V3 API 路由（配合 v119 表结构）

端点列表（prefix /api/v1/org/payroll）：
  GET  /configs                           — 查询薪资配置列表
  POST /configs                           — 创建/更新薪资配置
  POST /calculate                         — 计算单个员工月薪
  POST /batch-calculate                   — 批量计算门店当月所有员工
  GET  /records                           — 薪资单列表（可按 store/year/month/status 过滤）
  GET  /records/{record_id}               — 薪资单详情（含明细行）
  POST /records/{record_id}/approve       — 审批薪资单
  GET  /summary                           — 门店月薪汇总
"""

from __future__ import annotations

from datetime import date
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from services.payroll_engine_v3 import PayrollEngine
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/org/payroll", tags=["payroll-engine-v3"])

# ── DB session 依赖（与其他路由保持一致，注入方式项目自定义） ────────────────


async def get_db() -> AsyncSession:  # pragma: no cover
    """占位：在运行时由 FastAPI 依赖注入框架替换为实际 DB session 工厂。"""
    raise NotImplementedError("请在 main.py 或 dependencies.py 中覆盖 get_db 依赖")


# ── Pydantic 请求/响应模型 ────────────────────────────────────────────────


class PayrollConfigCreateReq(BaseModel):
    store_id: str | None = Field(None, description="门店 UUID，NULL 表示品牌级默认")
    employee_role: str = Field(..., description="cashier/chef/waiter/manager")
    salary_type: str = Field("monthly", description="monthly/hourly/piecework")
    base_salary_fen: int | None = Field(None, ge=0, description="月薪（分）")
    hourly_rate_fen: int | None = Field(None, ge=0, description="时薪（分）")
    piecework_unit: str | None = Field(None, description="per_order/per_dish/per_table")
    piecework_rate_fen: int | None = Field(None, ge=0, description="每计件单位工资（分）")
    commission_type: str = Field("none", description="none/fixed/percentage")
    commission_rate: float | None = Field(None, ge=0, le=1, description="提成比例")
    commission_base: str | None = Field(None, description="revenue/profit/tips")
    kpi_bonus_max_fen: int = Field(0, ge=0, description="月最高绩效奖金（分）")
    effective_from: date = Field(..., description="配置生效日期")
    effective_to: date | None = Field(None, description="配置失效日期，NULL=永久有效")
    is_active: bool = Field(True)


class CalculatePayrollReq(BaseModel):
    store_id: str = Field(..., description="门店 UUID")
    employee_id: str = Field(..., description="员工 UUID")
    year: int = Field(..., ge=2020, le=2100)
    month: int = Field(..., ge=1, le=12)
    employee_role: str = Field("waiter", description="cashier/chef/waiter/manager")
    overtime_hours: float = Field(0.0, ge=0)
    kpi_score: float = Field(0.0, ge=0, le=100)
    absence_days: float = Field(0.0, ge=0)
    late_count: int = Field(0, ge=0)
    early_leave_count: int = Field(0, ge=0)
    late_deduction_per_time_fen: int = Field(5_000, ge=0)
    early_leave_deduction_per_time_fen: int = Field(5_000, ge=0)
    seniority_months: int = Field(0, ge=0)
    ytd_income_yuan: float = Field(0.0, ge=0)
    ytd_tax_paid_yuan: float = Field(0.0, ge=0)
    ytd_social_insurance_yuan: float = Field(0.0, ge=0)
    special_deduction_monthly_yuan: float = Field(0.0, ge=0)


class BatchCalculateReq(BaseModel):
    store_id: str = Field(..., description="门店 UUID")
    year: int = Field(..., ge=2020, le=2100)
    month: int = Field(..., ge=1, le=12)


class ApprovePayrollReq(BaseModel):
    approved_by: str = Field(..., description="审批人姓名或 UUID")


# ── 辅助函数 ──────────────────────────────────────────────────────────────


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data, "error": {}}


def _err(msg: str, code: int = 400) -> HTTPException:
    return HTTPException(
        status_code=code,
        detail={"ok": False, "data": {}, "error": {"message": msg}},
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  薪资配置端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/configs")
async def list_payroll_configs(
    store_id: str | None = Query(None, description="门店 UUID 过滤"),
    role: str | None = Query(None, description="岗位过滤"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """查询薪资配置列表"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": x_tenant_id},
    )
    conditions = [
        "tenant_id = :tenant_id",
        "is_active = true",
        "is_deleted = false",
    ]
    params: dict[str, Any] = {"tenant_id": x_tenant_id}

    if store_id:
        conditions.append("(store_id = :store_id OR store_id IS NULL)")
        params["store_id"] = store_id
    if role:
        conditions.append("employee_role = :role")
        params["role"] = role

    sql = text(
        f"SELECT * FROM payroll_configs WHERE {' AND '.join(conditions)} ORDER BY employee_role, effective_from DESC"
    )
    rows = (await db.execute(sql, params)).mappings().all()
    return _ok([dict(r) for r in rows])


@router.post("/configs")
async def create_payroll_config(
    req: PayrollConfigCreateReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """创建薪资配置（如已存在同门店+岗位+effective_from 则更新）"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": x_tenant_id},
    )
    sql = text("""
        INSERT INTO payroll_configs (
            tenant_id, store_id, employee_role, salary_type,
            base_salary_fen, hourly_rate_fen,
            piecework_unit, piecework_rate_fen,
            commission_type, commission_rate, commission_base,
            kpi_bonus_max_fen, effective_from, effective_to, is_active
        ) VALUES (
            :tenant_id, :store_id, :role, :salary_type,
            :base_salary_fen, :hourly_rate_fen,
            :piecework_unit, :piecework_rate_fen,
            :commission_type, :commission_rate, :commission_base,
            :kpi_bonus_max_fen, :effective_from, :effective_to, :is_active
        )
        ON CONFLICT DO NOTHING
        RETURNING id
    """)
    result = await db.execute(
        sql,
        {
            "tenant_id": x_tenant_id,
            "store_id": req.store_id,
            "role": req.employee_role,
            "salary_type": req.salary_type,
            "base_salary_fen": req.base_salary_fen,
            "hourly_rate_fen": req.hourly_rate_fen,
            "piecework_unit": req.piecework_unit,
            "piecework_rate_fen": req.piecework_rate_fen,
            "commission_type": req.commission_type,
            "commission_rate": req.commission_rate,
            "commission_base": req.commission_base,
            "kpi_bonus_max_fen": req.kpi_bonus_max_fen,
            "effective_from": req.effective_from,
            "effective_to": req.effective_to,
            "is_active": req.is_active,
        },
    )
    row = result.fetchone()
    await db.commit()
    config_id = str(row[0]) if row else None
    return _ok({"config_id": config_id, "created": config_id is not None})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  薪资计算端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/calculate")
async def calculate_employee_payroll(
    req: CalculatePayrollReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """计算单个员工月薪（计算后以 draft 状态写入 payroll_records）"""
    engine = PayrollEngine()
    try:
        record = await engine.calculate_monthly_payroll(
            db,
            x_tenant_id,
            req.store_id,
            req.employee_id,
            req.year,
            req.month,
            employee_role=req.employee_role,
            overtime_hours=req.overtime_hours,
            kpi_score=req.kpi_score,
            absence_days=req.absence_days,
            late_count=req.late_count,
            early_leave_count=req.early_leave_count,
            late_deduction_per_time_fen=req.late_deduction_per_time_fen,
            early_leave_deduction_per_time_fen=req.early_leave_deduction_per_time_fen,
            seniority_months=req.seniority_months,
            ytd_income_yuan=req.ytd_income_yuan,
            ytd_tax_paid_yuan=req.ytd_tax_paid_yuan,
            ytd_social_insurance_yuan=req.ytd_social_insurance_yuan,
            month_index=req.month,
            special_deduction_monthly_yuan=req.special_deduction_monthly_yuan,
        )
    except ValueError as exc:
        raise _err(str(exc)) from exc
    return _ok(record)


@router.post("/batch-calculate")
async def batch_calculate_store_payroll(
    req: BatchCalculateReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """批量计算门店当月所有有绩效记录的员工薪资"""
    engine = PayrollEngine()
    results = await engine.batch_calculate_store(db, x_tenant_id, req.store_id, req.year, req.month)
    success = [r for r in results if r.get("status") != "error"]
    errors = [r for r in results if r.get("status") == "error"]
    return _ok(
        {
            "store_id": req.store_id,
            "year": req.year,
            "month": req.month,
            "total": len(results),
            "success_count": len(success),
            "error_count": len(errors),
            "records": success,
            "errors": errors,
        }
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  薪资单端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/records")
async def list_payroll_records(
    store_id: str | None = Query(None),
    year: int | None = Query(None),
    month: int | None = Query(None),
    status: str | None = Query(None, description="draft/approved/paid/voided"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """薪资单列表（支持按门店/年月/状态过滤，分页）"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": x_tenant_id},
    )
    conditions = ["r.tenant_id = :tenant_id", "r.is_deleted = false"]
    params: dict[str, Any] = {"tenant_id": x_tenant_id}

    if store_id:
        conditions.append("r.store_id = :store_id")
        params["store_id"] = store_id
    if year and month:
        from datetime import date as _date

        params["period_start"] = _date(year, month, 1)
        conditions.append("r.pay_period_start = :period_start")
    if status:
        conditions.append("r.status = :status")
        params["status"] = status

    where = " AND ".join(conditions)
    count_sql = text(f"SELECT COUNT(*) FROM payroll_records r WHERE {where}")
    total = (await db.execute(count_sql, params)).scalar() or 0

    params["limit"] = size
    params["offset"] = (page - 1) * size
    list_sql = text(
        f"""
        SELECT r.*
        FROM payroll_records r
        WHERE {where}
        ORDER BY r.pay_period_start DESC, r.created_at DESC
        LIMIT :limit OFFSET :offset
        """
    )
    rows = (await db.execute(list_sql, params)).mappings().all()
    return _ok({"items": [dict(r) for r in rows], "total": total})


@router.get("/records/{record_id}")
async def get_payroll_record(
    record_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """薪资单详情（含明细行 line_items）"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": x_tenant_id},
    )
    record_row = (
        (
            await db.execute(
                text("""
                SELECT * FROM payroll_records
                WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = false
            """),
                {"id": record_id, "tenant_id": x_tenant_id},
            )
        )
        .mappings()
        .first()
    )

    if not record_row:
        raise _err(f"薪资单不存在: {record_id}", 404)

    lines = (
        (
            await db.execute(
                text("""
                SELECT * FROM payroll_line_items
                WHERE record_id = :record_id AND tenant_id = :tenant_id
                ORDER BY created_at
            """),
                {"record_id": record_id, "tenant_id": x_tenant_id},
            )
        )
        .mappings()
        .all()
    )

    return _ok(
        {
            **dict(record_row),
            "line_items": [dict(li) for li in lines],
        }
    )


@router.post("/records/{record_id}/approve")
async def approve_payroll_record(
    record_id: str,
    req: ApprovePayrollReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """审批薪资单（draft → approved）"""
    engine = PayrollEngine()
    try:
        result = await engine.approve_payroll(db, x_tenant_id, record_id, req.approved_by)
    except ValueError as exc:
        raise _err(str(exc)) from exc
    return _ok(result)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  汇总分析端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/summary")
async def get_payroll_summary(
    store_id: str = Query(..., description="门店 UUID"),
    year: int = Query(..., ge=2020, le=2100),
    month: int = Query(..., ge=1, le=12),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """门店月度薪资汇总（含环比、岗位分布、中位数）"""
    engine = PayrollEngine()
    summary = await engine.get_payroll_summary(db, x_tenant_id, store_id, year, month)
    return _ok(summary)
