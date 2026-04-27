"""岗位职级管理 API 路由

端点列表：
  GET    /api/v1/job-grades                          职级列表（可按category筛选）
  POST   /api/v1/job-grades                          创建职级
  GET    /api/v1/job-grades/statistics                各职级人数和平均薪资
  GET    /api/v1/job-grades/{grade_id}               职级详情
  PUT    /api/v1/job-grades/{grade_id}               更新职级
  DELETE /api/v1/job-grades/{grade_id}               软删除
  GET    /api/v1/job-grades/{grade_id}/employees     该职级下所有员工

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/job-grades", tags=["job-grades"])


# ── 辅助函数 ──────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None}


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ── 请求模型 ──────────────────────────────────────────────────────────────────


class CreateJobGradeReq(BaseModel):
    name: str = Field(..., description="职级名称")
    category: str = Field(default="management", description="职级类别: management/technical/operations/support")
    level: int = Field(..., description="职级等级（数字越大越高）")
    min_salary: Optional[int] = Field(None, description="薪资下限（分）")
    max_salary: Optional[int] = Field(None, description="薪资上限（分）")
    description: Optional[str] = Field(None, description="职级描述")
    requirements: Optional[str] = Field(None, description="任职要求")
    sort_order: int = Field(default=0, description="排序序号")


class UpdateJobGradeReq(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    level: Optional[int] = None
    min_salary: Optional[int] = None
    max_salary: Optional[int] = None
    description: Optional[str] = None
    requirements: Optional[str] = None
    sort_order: Optional[int] = None


# ── 端点 ──────────────────────────────────────────────────────────────────────


@router.get("")
async def list_job_grades(
    request: Request,
    category: Optional[str] = Query(None, description="职级类别筛选"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """职级列表（可按category筛选）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    conditions = ["jg.is_deleted = FALSE"]
    params: dict[str, Any] = {"limit": size, "offset": (page - 1) * size}

    if category:
        conditions.append("jg.category = :category")
        params["category"] = category

    where_clause = " AND ".join(conditions)

    count_sql = f"SELECT COUNT(*) FROM job_grades jg WHERE {where_clause}"
    count_result = await db.execute(text(count_sql), params)
    total = count_result.scalar() or 0

    list_sql = f"""
        SELECT
            jg.id::text AS grade_id,
            jg.name,
            jg.category,
            jg.level,
            jg.min_salary,
            jg.max_salary,
            jg.description,
            jg.requirements,
            jg.sort_order,
            jg.created_at,
            (SELECT COUNT(*) FROM employees e
             WHERE e.job_grade_id = jg.id AND e.is_deleted = FALSE AND e.status = 'active'
            ) AS employee_count
        FROM job_grades jg
        WHERE {where_clause}
        ORDER BY jg.level DESC, jg.sort_order
        LIMIT :limit OFFSET :offset
    """
    result = await db.execute(text(list_sql), params)
    items = []
    for r in result.fetchall():
        d = dict(r._mapping)
        d["employee_count"] = int(d.get("employee_count") or 0)
        if d.get("created_at"):
            d["created_at"] = str(d["created_at"])
        items.append(d)

    log.info("list_job_grades", tenant_id=tenant_id, total=total)
    return _ok({"items": items, "total": total, "page": page, "size": size})


@router.post("")
async def create_job_grade(
    request: Request,
    req: CreateJobGradeReq,
    db: AsyncSession = Depends(get_db),
):
    """创建职级"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    grade_id = str(uuid4())
    now = datetime.now(timezone.utc)

    sql = text("""
        INSERT INTO job_grades (
            id, tenant_id, name, category, level,
            min_salary, max_salary, description, requirements,
            sort_order, is_deleted, created_at, updated_at
        ) VALUES (
            :id, :tenant_id, :name, :category, :level,
            :min_salary, :max_salary, :description, :requirements,
            :sort_order, FALSE, :now, :now
        )
        RETURNING id::text AS grade_id
    """)

    result = await db.execute(
        sql,
        {
            "id": grade_id,
            "tenant_id": tenant_id,
            "name": req.name,
            "category": req.category,
            "level": req.level,
            "min_salary": req.min_salary,
            "max_salary": req.max_salary,
            "description": req.description,
            "requirements": req.requirements,
            "sort_order": req.sort_order,
            "now": now,
        },
    )
    await db.commit()
    row = result.fetchone()

    log.info("create_job_grade", tenant_id=tenant_id, grade_id=grade_id, name=req.name)
    return _ok({"grade_id": row._mapping["grade_id"] if row else grade_id})


@router.get("/statistics")
async def get_job_grade_statistics(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """各职级人数和平均薪资"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    sql = text("""
        SELECT
            jg.id::text AS grade_id,
            jg.name,
            jg.category,
            jg.level,
            jg.min_salary,
            jg.max_salary,
            COUNT(e.id) AS employee_count,
            COALESCE(ROUND(AVG(e.base_salary)::numeric, 0), 0) AS avg_salary,
            COALESCE(MIN(e.base_salary), 0) AS actual_min_salary,
            COALESCE(MAX(e.base_salary), 0) AS actual_max_salary
        FROM job_grades jg
        LEFT JOIN employees e ON e.job_grade_id = jg.id
            AND e.is_deleted = FALSE AND e.status = 'active'
        WHERE jg.is_deleted = FALSE
        GROUP BY jg.id, jg.name, jg.category, jg.level, jg.min_salary, jg.max_salary
        ORDER BY jg.level DESC
    """)

    result = await db.execute(sql)
    items = []
    total_employees = 0
    for r in result.fetchall():
        d = dict(r._mapping)
        emp_count = int(d.get("employee_count") or 0)
        d["employee_count"] = emp_count
        d["avg_salary"] = int(d.get("avg_salary") or 0)
        d["actual_min_salary"] = int(d.get("actual_min_salary") or 0)
        d["actual_max_salary"] = int(d.get("actual_max_salary") or 0)
        total_employees += emp_count
        items.append(d)

    log.info("job_grade_statistics", tenant_id=tenant_id, grades=len(items))
    return _ok(
        {
            "grades": items,
            "summary": {
                "total_grades": len(items),
                "total_employees": total_employees,
            },
        }
    )


@router.get("/{grade_id}")
async def get_job_grade_detail(
    request: Request,
    grade_id: str,
    db: AsyncSession = Depends(get_db),
):
    """职级详情"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    sql = text("""
        SELECT
            jg.id::text AS grade_id,
            jg.name,
            jg.category,
            jg.level,
            jg.min_salary,
            jg.max_salary,
            jg.description,
            jg.requirements,
            jg.sort_order,
            jg.created_at,
            jg.updated_at,
            (SELECT COUNT(*) FROM employees e
             WHERE e.job_grade_id = jg.id AND e.is_deleted = FALSE AND e.status = 'active'
            ) AS employee_count
        FROM job_grades jg
        WHERE jg.id = :grade_id AND jg.is_deleted = FALSE
    """)

    result = await db.execute(sql, {"grade_id": grade_id})
    row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="职级不存在")

    data = dict(row._mapping)
    data["employee_count"] = int(data.get("employee_count") or 0)
    for key in ("created_at", "updated_at"):
        if data.get(key):
            data[key] = str(data[key])

    log.info("get_job_grade_detail", tenant_id=tenant_id, grade_id=grade_id)
    return _ok(data)


@router.put("/{grade_id}")
async def update_job_grade(
    request: Request,
    grade_id: str,
    req: UpdateJobGradeReq,
    db: AsyncSession = Depends(get_db),
):
    """更新职级"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    check = await db.execute(
        text("SELECT id FROM job_grades WHERE id = :grade_id AND is_deleted = FALSE"),
        {"grade_id": grade_id},
    )
    if not check.fetchone():
        raise HTTPException(status_code=404, detail="职级不存在")

    update_fields: list[str] = []
    params: dict[str, Any] = {"grade_id": grade_id, "now": datetime.now(timezone.utc)}

    field_map = {
        "name": req.name,
        "category": req.category,
        "level": req.level,
        "min_salary": req.min_salary,
        "max_salary": req.max_salary,
        "description": req.description,
        "requirements": req.requirements,
        "sort_order": req.sort_order,
    }

    for field_name, value in field_map.items():
        if value is not None:
            update_fields.append(f"{field_name} = :{field_name}")
            params[field_name] = value

    if not update_fields:
        raise HTTPException(status_code=400, detail="没有需要更新的字段")

    update_fields.append("updated_at = :now")
    set_clause = ", ".join(update_fields)

    sql = text(f"UPDATE job_grades SET {set_clause} WHERE id = :grade_id AND is_deleted = FALSE")
    await db.execute(sql, params)
    await db.commit()

    log.info("update_job_grade", tenant_id=tenant_id, grade_id=grade_id)
    return _ok({"grade_id": grade_id, "updated": True})


@router.delete("/{grade_id}")
async def delete_job_grade(
    request: Request,
    grade_id: str,
    db: AsyncSession = Depends(get_db),
):
    """软删除职级"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 检查是否有在职员工使用该职级
    emp_check = await db.execute(
        text(
            "SELECT COUNT(*) FROM employees WHERE job_grade_id = :grade_id AND is_deleted = FALSE AND status = 'active'"
        ),
        {"grade_id": grade_id},
    )
    emp_count = emp_check.scalar() or 0
    if emp_count > 0:
        raise HTTPException(status_code=400, detail=f"该职级下还有 {emp_count} 名在职员工，请先调整员工职级")

    result = await db.execute(
        text("""
            UPDATE job_grades
            SET is_deleted = TRUE, updated_at = :now
            WHERE id = :grade_id AND is_deleted = FALSE
            RETURNING id::text AS grade_id
        """),
        {"grade_id": grade_id, "now": datetime.now(timezone.utc)},
    )
    row = result.fetchone()
    await db.commit()

    if not row:
        raise HTTPException(status_code=404, detail="职级不存在")

    log.info("delete_job_grade", tenant_id=tenant_id, grade_id=grade_id)
    return _ok({"grade_id": grade_id, "deleted": True})


@router.get("/{grade_id}/employees")
async def get_grade_employees(
    request: Request,
    grade_id: str,
    status: Optional[str] = Query(None, description="状态筛选"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """该职级下所有员工"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    conditions = ["e.job_grade_id = :grade_id", "e.is_deleted = FALSE"]
    params: dict[str, Any] = {"grade_id": grade_id, "limit": size, "offset": (page - 1) * size}

    if status:
        conditions.append("e.status = :status")
        params["status"] = status

    where_clause = " AND ".join(conditions)

    count_sql = f"SELECT COUNT(*) FROM employees e WHERE {where_clause}"
    count_result = await db.execute(text(count_sql), params)
    total = count_result.scalar() or 0

    list_sql = f"""
        SELECT
            e.id::text AS employee_id,
            e.emp_name,
            e.phone,
            e.position,
            e.store_id::text,
            e.department_id::text,
            e.employment_type,
            e.status,
            e.hire_date,
            e.base_salary,
            d.name AS department_name
        FROM employees e
        LEFT JOIN departments d ON d.id = e.department_id AND d.is_active = TRUE
        WHERE {where_clause}
        ORDER BY e.created_at DESC
        LIMIT :limit OFFSET :offset
    """
    result = await db.execute(text(list_sql), params)
    items = []
    for r in result.fetchall():
        d = dict(r._mapping)
        if d.get("hire_date"):
            d["hire_date"] = str(d["hire_date"])
        items.append(d)

    log.info("get_grade_employees", tenant_id=tenant_id, grade_id=grade_id, total=total)
    return _ok({"items": items, "total": total, "page": page, "size": size})
