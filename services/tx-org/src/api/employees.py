"""员工主档 API 路由

端点列表：
  GET    /api/v1/employees                          员工列表（分页、多维筛选）
  POST   /api/v1/employees                          创建员工
  GET    /api/v1/employees/statistics                人力统计
  POST   /api/v1/employees/batch-import              批量导入
  GET    /api/v1/employees/{employee_id}             员工详情（含部门/岗位JOIN）
  PUT    /api/v1/employees/{employee_id}             更新员工
  DELETE /api/v1/employees/{employee_id}             软删除（status=inactive）
  GET    /api/v1/employees/{employee_id}/profile-tabs  7Tab聚合数据

  --- 保留原有端点（/api/v1/org 前缀） ---
  GET    /api/v1/org/employees/{emp_id}/performance  绩效
  POST   /api/v1/org/performance/compute             批量计算绩效
  GET    /api/v1/org/labor-cost                      人力成本
  GET    /api/v1/org/labor-cost/ranking              人力成本排名
  GET    /api/v1/org/attendance                      考勤查询
  POST   /api/v1/org/attendance/clock-in             打卡
  GET    /api/v1/org/training/plans                  培训计划
  GET    /api/v1/org/employees/{emp_id}/skill-gaps   技能差距
  GET    /api/v1/org/turnover-risk                   离职预测
  GET    /api/v1/org/hierarchy                       组织架构

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, List, Optional
from uuid import UUID, uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(tags=["employees"])


# ── 辅助函数 ──────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get(
        "X-Tenant-ID", ""
    )
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, status: int = 400) -> dict:
    raise HTTPException(status_code=status, detail=msg)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ── 请求模型 ──────────────────────────────────────────────────────────────────


class CreateEmployeeReq(BaseModel):
    emp_name: str = Field(..., description="员工姓名")
    phone: Optional[str] = Field(None, description="手机号")
    id_card_number: Optional[str] = Field(None, description="身份证号")
    gender: Optional[str] = Field(None, description="性别: male/female")
    birth_date: Optional[date] = Field(None, description="出生日期")
    store_id: Optional[str] = Field(None, description="所属门店ID")
    department_id: Optional[str] = Field(None, description="部门ID")
    job_grade_id: Optional[str] = Field(None, description="职级ID")
    position: Optional[str] = Field(None, description="岗位名称")
    employment_type: str = Field(default="full_time", description="用工类型: full_time/part_time/intern/outsourced")
    hire_date: Optional[date] = Field(None, description="入职日期")
    base_salary: Optional[int] = Field(None, description="基本工资（分）")
    health_cert_number: Optional[str] = Field(None, description="健康证编号")
    health_cert_expiry: Optional[date] = Field(None, description="健康证到期日")
    food_safety_cert: Optional[str] = Field(None, description="食品安全证编号")
    food_safety_cert_expiry: Optional[date] = Field(None, description="食品安全证到期日")
    contract_start_date: Optional[date] = Field(None, description="合同开始日期")
    contract_end_date: Optional[date] = Field(None, description="合同结束日期")
    emergency_contact: Optional[str] = Field(None, description="紧急联系人")
    emergency_phone: Optional[str] = Field(None, description="紧急联系电话")
    avatar_url: Optional[str] = Field(None, description="头像URL")
    status: str = Field(default="active", description="状态: active/inactive/probation")


class UpdateEmployeeReq(BaseModel):
    emp_name: Optional[str] = None
    phone: Optional[str] = None
    id_card_number: Optional[str] = None
    gender: Optional[str] = None
    birth_date: Optional[date] = None
    store_id: Optional[str] = None
    department_id: Optional[str] = None
    job_grade_id: Optional[str] = None
    position: Optional[str] = None
    employment_type: Optional[str] = None
    hire_date: Optional[date] = None
    base_salary: Optional[int] = None
    health_cert_number: Optional[str] = None
    health_cert_expiry: Optional[date] = None
    food_safety_cert: Optional[str] = None
    food_safety_cert_expiry: Optional[date] = None
    contract_start_date: Optional[date] = None
    contract_end_date: Optional[date] = None
    emergency_contact: Optional[str] = None
    emergency_phone: Optional[str] = None
    avatar_url: Optional[str] = None
    status: Optional[str] = None


class BatchImportReq(BaseModel):
    employees: List[CreateEmployeeReq] = Field(..., description="批量导入员工列表")


# ── 新版员工主档端点（/api/v1/employees） ────────────────────────────────────────


@router.get("/api/v1/employees")
async def list_employees(
    request: Request,
    store_id: Optional[str] = Query(None, description="门店ID筛选"),
    department_id: Optional[str] = Query(None, description="部门ID筛选"),
    status: Optional[str] = Query(None, description="状态筛选: active/inactive/probation"),
    employment_type: Optional[str] = Query(None, description="用工类型筛选"),
    keyword: Optional[str] = Query(None, description="关键字搜索（姓名/手机）"),
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(20, ge=1, le=100, description="每页条数"),
    db: AsyncSession = Depends(get_db),
):
    """员工列表（分页、多维筛选）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 构建动态WHERE子句
    conditions = ["e.is_deleted = FALSE"]
    params: dict[str, Any] = {"limit": size, "offset": (page - 1) * size}

    if store_id:
        conditions.append("e.store_id = :store_id")
        params["store_id"] = store_id
    if department_id:
        conditions.append("e.department_id = :department_id")
        params["department_id"] = department_id
    if status:
        conditions.append("e.status = :status")
        params["status"] = status
    if employment_type:
        conditions.append("e.employment_type = :employment_type")
        params["employment_type"] = employment_type
    if keyword:
        conditions.append("(e.emp_name ILIKE :kw OR e.phone ILIKE :kw)")
        params["kw"] = f"%{keyword}%"

    where_clause = " AND ".join(conditions)

    # 查询总数
    count_sql = f"SELECT COUNT(*) FROM employees e WHERE {where_clause}"
    count_result = await db.execute(text(count_sql), params)
    total = count_result.scalar() or 0

    # 查询列表（JOIN 部门和职级）
    list_sql = f"""
        SELECT
            e.id::text AS employee_id,
            e.emp_name,
            e.phone,
            e.gender,
            e.status,
            e.employment_type,
            e.position,
            e.store_id::text,
            e.department_id::text,
            e.job_grade_id::text,
            e.hire_date,
            e.avatar_url,
            d.name AS department_name,
            jg.name AS job_grade_name
        FROM employees e
        LEFT JOIN departments d ON d.id = e.department_id AND d.is_active = TRUE
        LEFT JOIN job_grades jg ON jg.id = e.job_grade_id AND jg.is_deleted = FALSE
        WHERE {where_clause}
        ORDER BY e.created_at DESC
        LIMIT :limit OFFSET :offset
    """
    result = await db.execute(text(list_sql), params)
    items = [dict(r._mapping) for r in result.fetchall()]

    # 序列化日期
    for item in items:
        if item.get("hire_date"):
            item["hire_date"] = str(item["hire_date"])

    log.info("list_employees", tenant_id=tenant_id, total=total, page=page, size=size)
    return _ok({"items": items, "total": total, "page": page, "size": size})


@router.post("/api/v1/employees")
async def create_employee(
    request: Request,
    req: CreateEmployeeReq,
    db: AsyncSession = Depends(get_db),
):
    """创建员工"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    employee_id = str(uuid4())
    now = datetime.now(timezone.utc)

    sql = text("""
        INSERT INTO employees (
            id, tenant_id, emp_name, phone, id_card_number, gender, birth_date,
            store_id, department_id, job_grade_id, position, employment_type,
            hire_date, base_salary, health_cert_number, health_cert_expiry,
            food_safety_cert, food_safety_cert_expiry,
            contract_start_date, contract_end_date,
            emergency_contact, emergency_phone, avatar_url, status,
            created_at, updated_at, is_deleted
        ) VALUES (
            :id, :tenant_id, :emp_name, :phone, :id_card_number, :gender, :birth_date,
            :store_id, :department_id, :job_grade_id, :position, :employment_type,
            :hire_date, :base_salary, :health_cert_number, :health_cert_expiry,
            :food_safety_cert, :food_safety_cert_expiry,
            :contract_start_date, :contract_end_date,
            :emergency_contact, :emergency_phone, :avatar_url, :status,
            :now, :now, FALSE
        )
        RETURNING id::text AS employee_id
    """)

    result = await db.execute(sql, {
        "id": employee_id,
        "tenant_id": tenant_id,
        "emp_name": req.emp_name,
        "phone": req.phone,
        "id_card_number": req.id_card_number,
        "gender": req.gender,
        "birth_date": req.birth_date,
        "store_id": req.store_id,
        "department_id": req.department_id,
        "job_grade_id": req.job_grade_id,
        "position": req.position,
        "employment_type": req.employment_type,
        "hire_date": req.hire_date or now.date(),
        "base_salary": req.base_salary,
        "health_cert_number": req.health_cert_number,
        "health_cert_expiry": req.health_cert_expiry,
        "food_safety_cert": req.food_safety_cert,
        "food_safety_cert_expiry": req.food_safety_cert_expiry,
        "contract_start_date": req.contract_start_date,
        "contract_end_date": req.contract_end_date,
        "emergency_contact": req.emergency_contact,
        "emergency_phone": req.emergency_phone,
        "avatar_url": req.avatar_url,
        "status": req.status,
        "now": now,
    })
    await db.commit()
    row = result.fetchone()

    log.info("create_employee", tenant_id=tenant_id, employee_id=employee_id, name=req.emp_name)
    return _ok({"employee_id": row._mapping["employee_id"] if row else employee_id})


@router.get("/api/v1/employees/statistics")
async def get_employee_statistics(
    request: Request,
    store_id: Optional[str] = Query(None, description="门店ID筛选"),
    db: AsyncSession = Depends(get_db),
):
    """人力统计（在职/离职/试用期/各部门人数）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    store_filter = "AND e.store_id = :store_id" if store_id else ""
    params: dict[str, Any] = {}
    if store_id:
        params["store_id"] = store_id

    # 状态统计
    status_sql = f"""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE e.status = 'active') AS active_count,
            COUNT(*) FILTER (WHERE e.status = 'inactive') AS inactive_count,
            COUNT(*) FILTER (WHERE e.status = 'probation') AS probation_count,
            COUNT(*) FILTER (WHERE e.employment_type = 'full_time') AS full_time_count,
            COUNT(*) FILTER (WHERE e.employment_type = 'part_time') AS part_time_count
        FROM employees e
        WHERE e.is_deleted = FALSE {store_filter}
    """
    status_result = await db.execute(text(status_sql), params)
    status_row = dict(status_result.fetchone()._mapping)

    # 各部门人数
    dept_sql = f"""
        SELECT
            d.id::text AS department_id,
            d.name AS department_name,
            COUNT(e.id) AS employee_count
        FROM departments d
        LEFT JOIN employees e ON e.department_id = d.id
            AND e.is_deleted = FALSE AND e.status = 'active' {store_filter}
        WHERE d.is_active = TRUE
        GROUP BY d.id, d.name
        ORDER BY employee_count DESC
    """
    dept_result = await db.execute(text(dept_sql), params)
    dept_items = [dict(r._mapping) for r in dept_result.fetchall()]

    log.info("employee_statistics", tenant_id=tenant_id, total=status_row.get("total", 0))
    return _ok({
        "status_summary": {
            "total": int(status_row.get("total") or 0),
            "active": int(status_row.get("active_count") or 0),
            "inactive": int(status_row.get("inactive_count") or 0),
            "probation": int(status_row.get("probation_count") or 0),
        },
        "employment_type_summary": {
            "full_time": int(status_row.get("full_time_count") or 0),
            "part_time": int(status_row.get("part_time_count") or 0),
        },
        "department_distribution": dept_items,
    })


@router.post("/api/v1/employees/batch-import")
async def batch_import_employees(
    request: Request,
    req: BatchImportReq,
    db: AsyncSession = Depends(get_db),
):
    """批量导入员工（JSON数组）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    now = datetime.now(timezone.utc)
    created_ids: list[str] = []
    errors: list[dict[str, Any]] = []

    for idx, emp in enumerate(req.employees):
        try:
            employee_id = str(uuid4())
            sql = text("""
                INSERT INTO employees (
                    id, tenant_id, emp_name, phone, id_card_number, gender, birth_date,
                    store_id, department_id, job_grade_id, position, employment_type,
                    hire_date, base_salary, health_cert_number, health_cert_expiry,
                    food_safety_cert, food_safety_cert_expiry,
                    contract_start_date, contract_end_date,
                    emergency_contact, emergency_phone, avatar_url, status,
                    created_at, updated_at, is_deleted
                ) VALUES (
                    :id, :tenant_id, :emp_name, :phone, :id_card_number, :gender, :birth_date,
                    :store_id, :department_id, :job_grade_id, :position, :employment_type,
                    :hire_date, :base_salary, :health_cert_number, :health_cert_expiry,
                    :food_safety_cert, :food_safety_cert_expiry,
                    :contract_start_date, :contract_end_date,
                    :emergency_contact, :emergency_phone, :avatar_url, :status,
                    :now, :now, FALSE
                )
            """)
            await db.execute(sql, {
                "id": employee_id,
                "tenant_id": tenant_id,
                "emp_name": emp.emp_name,
                "phone": emp.phone,
                "id_card_number": emp.id_card_number,
                "gender": emp.gender,
                "birth_date": emp.birth_date,
                "store_id": emp.store_id,
                "department_id": emp.department_id,
                "job_grade_id": emp.job_grade_id,
                "position": emp.position,
                "employment_type": emp.employment_type,
                "hire_date": emp.hire_date or now.date(),
                "base_salary": emp.base_salary,
                "health_cert_number": emp.health_cert_number,
                "health_cert_expiry": emp.health_cert_expiry,
                "food_safety_cert": emp.food_safety_cert,
                "food_safety_cert_expiry": emp.food_safety_cert_expiry,
                "contract_start_date": emp.contract_start_date,
                "contract_end_date": emp.contract_end_date,
                "emergency_contact": emp.emergency_contact,
                "emergency_phone": emp.emergency_phone,
                "avatar_url": emp.avatar_url,
                "status": emp.status,
                "now": now,
            })
            created_ids.append(employee_id)
        except Exception as exc:
            log.warning("batch_import_row_error", index=idx, name=emp.emp_name, error=str(exc))
            errors.append({"index": idx, "name": emp.emp_name, "error": str(exc)})

    await db.commit()
    log.info("batch_import_employees", tenant_id=tenant_id, success=len(created_ids), errors=len(errors))
    return _ok({
        "imported_count": len(created_ids),
        "imported_ids": created_ids,
        "error_count": len(errors),
        "errors": errors,
    })


@router.get("/api/v1/employees/{employee_id}")
async def get_employee_detail(
    request: Request,
    employee_id: str,
    db: AsyncSession = Depends(get_db),
):
    """员工详情（含部门/岗位JOIN）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    sql = text("""
        SELECT
            e.id::text AS employee_id,
            e.emp_name,
            e.phone,
            e.id_card_number,
            e.gender,
            e.birth_date,
            e.store_id::text,
            e.department_id::text,
            e.job_grade_id::text,
            e.position,
            e.employment_type,
            e.hire_date,
            e.base_salary,
            e.health_cert_number,
            e.health_cert_expiry,
            e.food_safety_cert,
            e.food_safety_cert_expiry,
            e.contract_start_date,
            e.contract_end_date,
            e.emergency_contact,
            e.emergency_phone,
            e.avatar_url,
            e.status,
            e.created_at,
            e.updated_at,
            d.name AS department_name,
            d.dept_type AS department_type,
            jg.name AS job_grade_name,
            jg.level AS job_grade_level,
            jg.category AS job_grade_category
        FROM employees e
        LEFT JOIN departments d ON d.id = e.department_id AND d.is_active = TRUE
        LEFT JOIN job_grades jg ON jg.id = e.job_grade_id AND jg.is_deleted = FALSE
        WHERE e.id = :eid AND e.is_deleted = FALSE
    """)
    result = await db.execute(sql, {"eid": employee_id})
    row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="员工不存在")

    data = dict(row._mapping)
    # 序列化日期字段
    for key in ("birth_date", "hire_date", "health_cert_expiry", "food_safety_cert_expiry",
                "contract_start_date", "contract_end_date", "created_at", "updated_at"):
        if data.get(key):
            data[key] = str(data[key])

    log.info("get_employee_detail", tenant_id=tenant_id, employee_id=employee_id)
    return _ok(data)


@router.put("/api/v1/employees/{employee_id}")
async def update_employee(
    request: Request,
    employee_id: str,
    req: UpdateEmployeeReq,
    db: AsyncSession = Depends(get_db),
):
    """更新员工"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 检查员工是否存在
    check = await db.execute(
        text("SELECT id FROM employees WHERE id = :eid AND is_deleted = FALSE"),
        {"eid": employee_id},
    )
    if not check.fetchone():
        raise HTTPException(status_code=404, detail="员工不存在")

    # 构建动态UPDATE
    update_fields: list[str] = []
    params: dict[str, Any] = {"eid": employee_id, "now": datetime.now(timezone.utc)}

    field_map = {
        "emp_name": req.emp_name,
        "phone": req.phone,
        "id_card_number": req.id_card_number,
        "gender": req.gender,
        "birth_date": req.birth_date,
        "store_id": req.store_id,
        "department_id": req.department_id,
        "job_grade_id": req.job_grade_id,
        "position": req.position,
        "employment_type": req.employment_type,
        "hire_date": req.hire_date,
        "base_salary": req.base_salary,
        "health_cert_number": req.health_cert_number,
        "health_cert_expiry": req.health_cert_expiry,
        "food_safety_cert": req.food_safety_cert,
        "food_safety_cert_expiry": req.food_safety_cert_expiry,
        "contract_start_date": req.contract_start_date,
        "contract_end_date": req.contract_end_date,
        "emergency_contact": req.emergency_contact,
        "emergency_phone": req.emergency_phone,
        "avatar_url": req.avatar_url,
        "status": req.status,
    }

    for field_name, value in field_map.items():
        if value is not None:
            update_fields.append(f"{field_name} = :{field_name}")
            params[field_name] = value

    if not update_fields:
        raise HTTPException(status_code=400, detail="没有需要更新的字段")

    update_fields.append("updated_at = :now")
    set_clause = ", ".join(update_fields)

    sql = text(f"UPDATE employees SET {set_clause} WHERE id = :eid AND is_deleted = FALSE")
    await db.execute(sql, params)
    await db.commit()

    log.info("update_employee", tenant_id=tenant_id, employee_id=employee_id, fields=list(field_map.keys()))
    return _ok({"employee_id": employee_id, "updated": True})


@router.delete("/api/v1/employees/{employee_id}")
async def delete_employee(
    request: Request,
    employee_id: str,
    db: AsyncSession = Depends(get_db),
):
    """软删除员工（设status=inactive, is_deleted=TRUE）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    result = await db.execute(
        text("""
            UPDATE employees
            SET status = 'inactive', is_deleted = TRUE, updated_at = :now
            WHERE id = :eid AND is_deleted = FALSE
            RETURNING id::text AS employee_id
        """),
        {"eid": employee_id, "now": datetime.now(timezone.utc)},
    )
    row = result.fetchone()
    await db.commit()

    if not row:
        raise HTTPException(status_code=404, detail="员工不存在")

    log.info("delete_employee", tenant_id=tenant_id, employee_id=employee_id)
    return _ok({"employee_id": employee_id, "deleted": True})


@router.get("/api/v1/employees/{employee_id}/profile-tabs")
async def get_employee_profile_tabs(
    request: Request,
    employee_id: str,
    db: AsyncSession = Depends(get_db),
):
    """7Tab聚合数据（基本信息/部门/岗位/考勤/请假/薪资/绩效）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # Tab 1: 基本信息（含部门/岗位）
    basic_sql = text("""
        SELECT
            e.id::text AS employee_id, e.emp_name, e.phone, e.id_card_number,
            e.gender, e.birth_date, e.store_id::text, e.department_id::text,
            e.job_grade_id::text, e.position, e.employment_type, e.hire_date,
            e.base_salary, e.emergency_contact, e.emergency_phone, e.avatar_url, e.status,
            d.name AS department_name, d.dept_type AS department_type,
            jg.name AS job_grade_name, jg.level AS job_grade_level
        FROM employees e
        LEFT JOIN departments d ON d.id = e.department_id AND d.is_active = TRUE
        LEFT JOIN job_grades jg ON jg.id = e.job_grade_id AND jg.is_deleted = FALSE
        WHERE e.id = :eid AND e.is_deleted = FALSE
    """)
    basic_result = await db.execute(basic_sql, {"eid": employee_id})
    basic_row = basic_result.fetchone()
    if not basic_row:
        raise HTTPException(status_code=404, detail="员工不存在")

    basic_info = dict(basic_row._mapping)
    for key in ("birth_date", "hire_date"):
        if basic_info.get(key):
            basic_info[key] = str(basic_info[key])

    # Tab 2: 部门信息
    dept_info = {
        "department_id": basic_info.get("department_id"),
        "department_name": basic_info.get("department_name"),
        "department_type": basic_info.get("department_type"),
    }

    # Tab 3: 岗位职级
    grade_info = {
        "job_grade_id": basic_info.get("job_grade_id"),
        "job_grade_name": basic_info.get("job_grade_name"),
        "job_grade_level": basic_info.get("job_grade_level"),
        "position": basic_info.get("position"),
    }

    # Tab 4: 考勤记录（近30天）
    attendance_sql = text("""
        SELECT
            date, status, clock_in_time, clock_out_time,
            is_late, is_early_leave, is_absent, overtime_hours,
            work_hours
        FROM daily_attendance
        WHERE employee_id = :eid
          AND date >= CURRENT_DATE - INTERVAL '30 days'
        ORDER BY date DESC
        LIMIT 30
    """)
    attendance_result = await db.execute(attendance_sql, {"eid": employee_id})
    attendance_items = []
    for r in attendance_result.fetchall():
        d = dict(r._mapping)
        d["date"] = str(d["date"]) if d.get("date") else None
        d["clock_in_time"] = str(d["clock_in_time"]) if d.get("clock_in_time") else None
        d["clock_out_time"] = str(d["clock_out_time"]) if d.get("clock_out_time") else None
        attendance_items.append(d)

    # Tab 5: 请假记录（近6个月）
    leave_sql = text("""
        SELECT
            id::text AS leave_id, leave_type, start_date, end_date,
            days, status, reason, created_at
        FROM leave_requests
        WHERE employee_id = :eid
          AND created_at >= CURRENT_DATE - INTERVAL '6 months'
        ORDER BY created_at DESC
        LIMIT 20
    """)
    leave_result = await db.execute(leave_sql, {"eid": employee_id})
    leave_items = []
    for r in leave_result.fetchall():
        d = dict(r._mapping)
        for key in ("start_date", "end_date", "created_at"):
            if d.get(key):
                d[key] = str(d[key])
        leave_items.append(d)

    # Tab 6: 薪资记录（近6个月）
    payroll_sql = text("""
        SELECT
            id::text AS payroll_id, period_year, period_month,
            base_salary, overtime_pay, bonus, deductions,
            net_salary, status, paid_at
        FROM payroll_records
        WHERE employee_id = :eid
          AND status != 'cancelled'
        ORDER BY period_year DESC, period_month DESC
        LIMIT 6
    """)
    payroll_result = await db.execute(payroll_sql, {"eid": employee_id})
    payroll_items = []
    for r in payroll_result.fetchall():
        d = dict(r._mapping)
        if d.get("paid_at"):
            d["paid_at"] = str(d["paid_at"])
        payroll_items.append(d)

    # Tab 7: 绩效记录
    perf_sql = text("""
        SELECT
            id::text AS performance_id, period_year, period_month,
            score, level, review_note, reviewer_id::text, created_at
        FROM staff_performance
        WHERE employee_id = :eid
        ORDER BY period_year DESC, period_month DESC
        LIMIT 12
    """)
    perf_result = await db.execute(perf_sql, {"eid": employee_id})
    perf_items = []
    for r in perf_result.fetchall():
        d = dict(r._mapping)
        if d.get("created_at"):
            d["created_at"] = str(d["created_at"])
        perf_items.append(d)

    log.info("get_employee_profile_tabs", tenant_id=tenant_id, employee_id=employee_id)
    return _ok({
        "basic_info": basic_info,
        "department": dept_info,
        "job_grade": grade_info,
        "attendance": {"items": attendance_items, "period": "近30天"},
        "leave": {"items": leave_items, "period": "近6个月"},
        "payroll": {"items": payroll_items, "period": "近6个月"},
        "performance": {"items": perf_items, "period": "近12个月"},
    })


# ── 保留原有端点（/api/v1/org 前缀） ────────────────────────────────────────────

_legacy_router = APIRouter(prefix="/api/v1/org", tags=["org-legacy"])


@_legacy_router.get("/employees/{emp_id}/performance")
async def get_performance(emp_id: str, period: str = "month"):
    """绩效查询"""
    return {"ok": True, "data": {"score": 0, "commission_fen": 0}}


@_legacy_router.post("/performance/compute")
async def compute_performance(store_id: str, period: str):
    """批量计算门店绩效"""
    return {"ok": True, "data": {"computed": True}}


@_legacy_router.get("/labor-cost")
async def get_labor_cost(store_id: str, month: Optional[str] = None):
    """人力成本"""
    return {"ok": True, "data": {"cost_rate": 0, "total_fen": 0}}


@_legacy_router.get("/labor-cost/ranking")
async def get_labor_cost_ranking(brand_id: Optional[str] = None):
    """人力成本排名"""
    return {"ok": True, "data": {"rankings": []}}


@_legacy_router.get("/attendance")
async def get_attendance(store_id: str, date: Optional[str] = None):
    """考勤查询"""
    return {"ok": True, "data": {"records": []}}


@_legacy_router.post("/attendance/clock-in")
async def clock_in(emp_id: str, store_id: str):
    """打卡"""
    return {"ok": True, "data": {"clocked_in": True}}


@_legacy_router.get("/training/plans")
async def list_training_plans(store_id: str):
    """培训计划"""
    return {"ok": True, "data": {"plans": []}}


@_legacy_router.get("/employees/{emp_id}/skill-gaps")
async def get_skill_gaps(emp_id: str):
    """技能差距"""
    return {"ok": True, "data": {"gaps": []}}


@_legacy_router.get("/turnover-risk")
async def get_turnover_risk(store_id: str):
    """离职预测"""
    return {"ok": True, "data": {"at_risk": []}}


@_legacy_router.get("/hierarchy")
async def get_org_hierarchy(brand_id: Optional[str] = None):
    """组织架构"""
    return {"ok": True, "data": {"hierarchy": {}}}


# 将 legacy router 的路由合并到主 router
for route in _legacy_router.routes:
    router.routes.append(route)
