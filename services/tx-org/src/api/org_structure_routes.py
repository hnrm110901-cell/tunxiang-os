"""组织架构管理 API 路由

端点列表：
  GET    /api/v1/org-structure/tree                              组织架构树（递归CTE）
  POST   /api/v1/org-structure/departments                       创建部门
  GET    /api/v1/org-structure/departments/{dept_id}             部门详情
  PUT    /api/v1/org-structure/departments/{dept_id}             更新部门
  DELETE /api/v1/org-structure/departments/{dept_id}             软删除
  GET    /api/v1/org-structure/departments/{dept_id}/employees   部门下员工
  POST   /api/v1/org-structure/departments/{dept_id}/move        移动部门
  GET    /api/v1/org-structure/statistics                        各部门人数统计

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

router = APIRouter(prefix="/api/v1/org-structure", tags=["org-structure"])


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


class CreateDepartmentReq(BaseModel):
    name: str = Field(..., description="部门名称")
    parent_id: Optional[str] = Field(None, description="上级部门ID（空=顶级部门）")
    dept_type: str = Field(default="department", description="部门类型: company/brand/store/department")
    store_id: Optional[str] = Field(None, description="所属门店ID（门店级部门必填）")
    manager_id: Optional[str] = Field(None, description="部门负责人ID")
    sort_order: int = Field(default=0, description="排序序号")
    description: Optional[str] = Field(None, description="部门描述")


class UpdateDepartmentReq(BaseModel):
    name: Optional[str] = None
    dept_type: Optional[str] = None
    store_id: Optional[str] = None
    manager_id: Optional[str] = None
    sort_order: Optional[int] = None
    description: Optional[str] = None


class MoveDepartmentReq(BaseModel):
    new_parent_id: Optional[str] = Field(None, description="新的上级部门ID（null=移为顶级）")


# ── 树构建辅助 ────────────────────────────────────────────────────────────────


def _build_tree(flat_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """将扁平列表构建为嵌套树"""
    node_map: dict[str, dict[str, Any]] = {}
    roots: list[dict[str, Any]] = []

    for row in flat_rows:
        row["children"] = []
        node_map[row["department_id"]] = row

    for row in flat_rows:
        parent = row.get("parent_id")
        if parent and parent in node_map:
            node_map[parent]["children"].append(row)
        else:
            roots.append(row)

    return roots


# ── 端点 ──────────────────────────────────────────────────────────────────────


@router.get("/tree")
async def get_org_tree(
    request: Request,
    store_id: Optional[str] = Query(None, description="按门店筛选"),
    db: AsyncSession = Depends(get_db),
):
    """组织架构树（递归CTE查询，返回嵌套JSON）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    store_filter = ""
    params: dict[str, Any] = {}
    if store_id:
        store_filter = "AND d.store_id = :store_id"
        params["store_id"] = store_id

    sql = text(f"""
        WITH RECURSIVE dept_tree AS (
            SELECT
                id, parent_id, name, dept_type, store_id, manager_id,
                sort_order, level, path, 0 AS depth
            FROM departments
            WHERE parent_id IS NULL
              AND is_active = TRUE
              {store_filter}
            UNION ALL
            SELECT
                d.id, d.parent_id, d.name, d.dept_type, d.store_id, d.manager_id,
                d.sort_order, d.level, d.path, dt.depth + 1
            FROM departments d
            JOIN dept_tree dt ON d.parent_id = dt.id
            WHERE d.is_active = TRUE
        )
        SELECT
            dt.id::text AS department_id,
            dt.parent_id::text AS parent_id,
            dt.name,
            dt.dept_type,
            dt.store_id::text,
            dt.manager_id::text,
            dt.sort_order,
            dt.level,
            dt.path,
            dt.depth,
            e.emp_name AS manager_name,
            (SELECT COUNT(*) FROM employees emp
             WHERE emp.department_id = dt.id AND emp.is_deleted = FALSE AND emp.status = 'active'
            ) AS employee_count
        FROM dept_tree dt
        LEFT JOIN employees e ON e.id = dt.manager_id AND e.is_deleted = FALSE
        ORDER BY dt.depth, dt.sort_order
    """)

    result = await db.execute(sql, params)
    flat_rows = [dict(r._mapping) for r in result.fetchall()]

    # 将depth转为int
    for row in flat_rows:
        row["depth"] = int(row.get("depth") or 0)
        row["employee_count"] = int(row.get("employee_count") or 0)

    tree = _build_tree(flat_rows)
    log.info("get_org_tree", tenant_id=tenant_id, total_nodes=len(flat_rows))
    return _ok({"tree": tree, "total_departments": len(flat_rows)})


@router.post("/departments")
async def create_department(
    request: Request,
    req: CreateDepartmentReq,
    db: AsyncSession = Depends(get_db),
):
    """创建部门"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    dept_id = str(uuid4())
    now = datetime.now(timezone.utc)

    # 计算 level 和 path
    level = 1
    path = f"/{req.name}"
    if req.parent_id:
        parent_result = await db.execute(
            text("SELECT level, path, name FROM departments WHERE id = :pid AND is_active = TRUE"),
            {"pid": req.parent_id},
        )
        parent = parent_result.fetchone()
        if not parent:
            raise HTTPException(status_code=404, detail="上级部门不存在")
        parent_data = dict(parent._mapping)
        level = int(parent_data.get("level") or 0) + 1
        parent_path = parent_data.get("path") or ""
        path = f"{parent_path}/{req.name}"

    sql = text("""
        INSERT INTO departments (
            id, tenant_id, name, parent_id, dept_type, store_id,
            manager_id, sort_order, level, path, description,
            is_active, created_at, updated_at
        ) VALUES (
            :id, :tenant_id, :name, :parent_id, :dept_type, :store_id,
            :manager_id, :sort_order, :level, :path, :description,
            TRUE, :now, :now
        )
        RETURNING id::text AS department_id
    """)

    result = await db.execute(
        sql,
        {
            "id": dept_id,
            "tenant_id": tenant_id,
            "name": req.name,
            "parent_id": req.parent_id,
            "dept_type": req.dept_type,
            "store_id": req.store_id,
            "manager_id": req.manager_id,
            "sort_order": req.sort_order,
            "level": level,
            "path": path,
            "description": req.description,
            "now": now,
        },
    )
    await db.commit()
    row = result.fetchone()

    log.info("create_department", tenant_id=tenant_id, dept_id=dept_id, name=req.name)
    return _ok({"department_id": row._mapping["department_id"] if row else dept_id, "path": path, "level": level})


@router.get("/departments/{dept_id}")
async def get_department_detail(
    request: Request,
    dept_id: str,
    db: AsyncSession = Depends(get_db),
):
    """部门详情"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    sql = text("""
        SELECT
            d.id::text AS department_id,
            d.name,
            d.parent_id::text,
            d.dept_type,
            d.store_id::text,
            d.manager_id::text,
            d.sort_order,
            d.level,
            d.path,
            d.description,
            d.created_at,
            d.updated_at,
            e.emp_name AS manager_name,
            pd.name AS parent_name,
            (SELECT COUNT(*) FROM employees emp
             WHERE emp.department_id = d.id AND emp.is_deleted = FALSE AND emp.status = 'active'
            ) AS employee_count
        FROM departments d
        LEFT JOIN employees e ON e.id = d.manager_id AND e.is_deleted = FALSE
        LEFT JOIN departments pd ON pd.id = d.parent_id AND pd.is_active = TRUE
        WHERE d.id = :dept_id AND d.is_active = TRUE
    """)
    result = await db.execute(sql, {"dept_id": dept_id})
    row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="部门不存在")

    data = dict(row._mapping)
    for key in ("created_at", "updated_at"):
        if data.get(key):
            data[key] = str(data[key])
    data["employee_count"] = int(data.get("employee_count") or 0)

    log.info("get_department_detail", tenant_id=tenant_id, dept_id=dept_id)
    return _ok(data)


@router.put("/departments/{dept_id}")
async def update_department(
    request: Request,
    dept_id: str,
    req: UpdateDepartmentReq,
    db: AsyncSession = Depends(get_db),
):
    """更新部门"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    check = await db.execute(
        text("SELECT id FROM departments WHERE id = :dept_id AND is_active = TRUE"),
        {"dept_id": dept_id},
    )
    if not check.fetchone():
        raise HTTPException(status_code=404, detail="部门不存在")

    update_fields: list[str] = []
    params: dict[str, Any] = {"dept_id": dept_id, "now": datetime.now(timezone.utc)}

    field_map = {
        "name": req.name,
        "dept_type": req.dept_type,
        "store_id": req.store_id,
        "manager_id": req.manager_id,
        "sort_order": req.sort_order,
        "description": req.description,
    }

    for field_name, value in field_map.items():
        if value is not None:
            update_fields.append(f"{field_name} = :{field_name}")
            params[field_name] = value

    if not update_fields:
        raise HTTPException(status_code=400, detail="没有需要更新的字段")

    update_fields.append("updated_at = :now")
    set_clause = ", ".join(update_fields)

    sql = text(f"UPDATE departments SET {set_clause} WHERE id = :dept_id AND is_active = TRUE")
    await db.execute(sql, params)
    await db.commit()

    log.info("update_department", tenant_id=tenant_id, dept_id=dept_id)
    return _ok({"department_id": dept_id, "updated": True})


@router.delete("/departments/{dept_id}")
async def delete_department(
    request: Request,
    dept_id: str,
    db: AsyncSession = Depends(get_db),
):
    """软删除部门"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 检查是否有子部门
    child_check = await db.execute(
        text("SELECT COUNT(*) FROM departments WHERE parent_id = :dept_id AND is_active = TRUE"),
        {"dept_id": dept_id},
    )
    child_count = child_check.scalar() or 0
    if child_count > 0:
        raise HTTPException(status_code=400, detail=f"该部门下还有 {child_count} 个子部门，请先处理子部门")

    # 检查是否有在职员工
    emp_check = await db.execute(
        text(
            "SELECT COUNT(*) FROM employees WHERE department_id = :dept_id AND is_deleted = FALSE AND status = 'active'"
        ),
        {"dept_id": dept_id},
    )
    emp_count = emp_check.scalar() or 0
    if emp_count > 0:
        raise HTTPException(status_code=400, detail=f"该部门下还有 {emp_count} 名在职员工，请先转移员工")

    result = await db.execute(
        text("""
            UPDATE departments
            SET is_active = FALSE, updated_at = :now
            WHERE id = :dept_id AND is_active = TRUE
            RETURNING id::text AS department_id
        """),
        {"dept_id": dept_id, "now": datetime.now(timezone.utc)},
    )
    row = result.fetchone()
    await db.commit()

    if not row:
        raise HTTPException(status_code=404, detail="部门不存在")

    log.info("delete_department", tenant_id=tenant_id, dept_id=dept_id)
    return _ok({"department_id": dept_id, "deleted": True})


@router.get("/departments/{dept_id}/employees")
async def get_department_employees(
    request: Request,
    dept_id: str,
    status: Optional[str] = Query(None, description="状态筛选"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """部门下员工列表"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    conditions = ["e.department_id = :dept_id", "e.is_deleted = FALSE"]
    params: dict[str, Any] = {"dept_id": dept_id, "limit": size, "offset": (page - 1) * size}

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
            e.employment_type,
            e.status,
            e.hire_date,
            jg.name AS job_grade_name
        FROM employees e
        LEFT JOIN job_grades jg ON jg.id = e.job_grade_id AND jg.is_deleted = FALSE
        WHERE {where_clause}
        ORDER BY e.created_at DESC
        LIMIT :limit OFFSET :offset
    """
    result = await db.execute(text(list_sql), params)
    items = [dict(r._mapping) for r in result.fetchall()]

    for item in items:
        if item.get("hire_date"):
            item["hire_date"] = str(item["hire_date"])

    log.info("get_department_employees", tenant_id=tenant_id, dept_id=dept_id, total=total)
    return _ok({"items": items, "total": total, "page": page, "size": size})


@router.post("/departments/{dept_id}/move")
async def move_department(
    request: Request,
    dept_id: str,
    req: MoveDepartmentReq,
    db: AsyncSession = Depends(get_db),
):
    """移动部门（更新parent_id和path）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 获取当前部门信息
    current = await db.execute(
        text("SELECT id, name, parent_id::text, path FROM departments WHERE id = :dept_id AND is_active = TRUE"),
        {"dept_id": dept_id},
    )
    current_row = current.fetchone()
    if not current_row:
        raise HTTPException(status_code=404, detail="部门不存在")

    current_data = dict(current_row._mapping)
    dept_name = current_data["name"]

    # 防止移动到自身下级（环形检测）
    if req.new_parent_id:
        # 检查 new_parent_id 是否是当前部门的子部门
        cycle_check_sql = text("""
            WITH RECURSIVE ancestors AS (
                SELECT id, parent_id FROM departments WHERE id = :new_parent_id AND is_active = TRUE
                UNION ALL
                SELECT d.id, d.parent_id FROM departments d
                JOIN ancestors a ON d.id = a.parent_id
                WHERE d.is_active = TRUE
            )
            SELECT COUNT(*) FROM ancestors WHERE id = :dept_id
        """)
        cycle_result = await db.execute(cycle_check_sql, {"new_parent_id": req.new_parent_id, "dept_id": dept_id})
        if (cycle_result.scalar() or 0) > 0:
            raise HTTPException(status_code=400, detail="不能将部门移动到其子部门下（会造成循环）")

        # 获取新父部门信息
        parent_result = await db.execute(
            text("SELECT level, path FROM departments WHERE id = :pid AND is_active = TRUE"),
            {"pid": req.new_parent_id},
        )
        parent_row = parent_result.fetchone()
        if not parent_row:
            raise HTTPException(status_code=404, detail="目标上级部门不存在")
        parent_data = dict(parent_row._mapping)
        new_level = int(parent_data.get("level") or 0) + 1
        new_path = f"{parent_data.get('path') or ''}/{dept_name}"
    else:
        new_level = 1
        new_path = f"/{dept_name}"

    now = datetime.now(timezone.utc)

    # 更新当前部门
    await db.execute(
        text("""
            UPDATE departments
            SET parent_id = :new_parent_id, level = :new_level, path = :new_path, updated_at = :now
            WHERE id = :dept_id AND is_active = TRUE
        """),
        {
            "new_parent_id": req.new_parent_id,
            "new_level": new_level,
            "new_path": new_path,
            "now": now,
            "dept_id": dept_id,
        },
    )

    # 递归更新子部门的 level 和 path
    await db.execute(
        text("""
            WITH RECURSIVE subtree AS (
                SELECT id, name, parent_id, level, path
                FROM departments WHERE parent_id = :dept_id AND is_active = TRUE
                UNION ALL
                SELECT d.id, d.name, d.parent_id, d.level, d.path
                FROM departments d JOIN subtree s ON d.parent_id = s.id
                WHERE d.is_active = TRUE
            )
            UPDATE departments d2
            SET
                level = :base_level + (
                    WITH RECURSIVE depth_calc AS (
                        SELECT id, parent_id, 1 AS rel_depth FROM departments WHERE parent_id = :dept_id AND is_active = TRUE
                        UNION ALL
                        SELECT dc.id, dc.parent_id, dc2.rel_depth + 1
                        FROM departments dc JOIN depth_calc dc2 ON dc.parent_id = dc2.id
                        WHERE dc.is_active = TRUE
                    )
                    SELECT rel_depth FROM depth_calc WHERE depth_calc.id = d2.id
                ),
                updated_at = :now
            FROM subtree s
            WHERE d2.id = s.id
        """),
        {"dept_id": dept_id, "base_level": new_level, "now": now},
    )

    await db.commit()

    log.info("move_department", tenant_id=tenant_id, dept_id=dept_id, new_parent_id=req.new_parent_id)
    return _ok(
        {
            "department_id": dept_id,
            "new_parent_id": req.new_parent_id,
            "new_level": new_level,
            "new_path": new_path,
        }
    )


@router.get("/statistics")
async def get_org_statistics(
    request: Request,
    store_id: Optional[str] = Query(None, description="按门店筛选"),
    db: AsyncSession = Depends(get_db),
):
    """各部门人数统计"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    store_filter = "AND d.store_id = :store_id" if store_id else ""
    params: dict[str, Any] = {}
    if store_id:
        params["store_id"] = store_id

    sql = text(f"""
        SELECT
            d.id::text AS department_id,
            d.name AS department_name,
            d.dept_type,
            d.level,
            d.store_id::text,
            COUNT(e.id) FILTER (WHERE e.status = 'active') AS active_count,
            COUNT(e.id) FILTER (WHERE e.status = 'probation') AS probation_count,
            COUNT(e.id) FILTER (WHERE e.status = 'inactive') AS inactive_count,
            COUNT(e.id) AS total_count
        FROM departments d
        LEFT JOIN employees e ON e.department_id = d.id AND e.is_deleted = FALSE
        WHERE d.is_active = TRUE {store_filter}
        GROUP BY d.id, d.name, d.dept_type, d.level, d.store_id
        ORDER BY d.level, d.name
    """)

    result = await db.execute(sql, params)
    items = []
    total_active = 0
    total_all = 0
    for r in result.fetchall():
        d = dict(r._mapping)
        d["active_count"] = int(d.get("active_count") or 0)
        d["probation_count"] = int(d.get("probation_count") or 0)
        d["inactive_count"] = int(d.get("inactive_count") or 0)
        d["total_count"] = int(d.get("total_count") or 0)
        total_active += d["active_count"]
        total_all += d["total_count"]
        items.append(d)

    log.info("get_org_statistics", tenant_id=tenant_id, departments=len(items))
    return _ok(
        {
            "departments": items,
            "summary": {
                "total_departments": len(items),
                "total_employees": total_all,
                "total_active": total_active,
            },
        }
    )
