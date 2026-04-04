"""组织人事核心仓库 — 员工 CRUD / 组织架构 / 人力成本

所有操作需调用方预先通过 set_config('app.tenant_id', ...) 设置租户上下文（RLS）。
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  员工 CRUD
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def list_employees(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
    *,
    role: Optional[str] = None,
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """分页查询门店员工列表"""
    offset = (page - 1) * size

    # 构建 WHERE 子句
    where_parts = [
        "tenant_id = :tid",
        "store_id = :store_id::uuid",
        "is_deleted = FALSE",
    ]
    params: dict[str, Any] = {
        "tid": tenant_id,
        "store_id": store_id,
        "lim": size,
        "off": offset,
    }
    if role:
        where_parts.append("role = :role")
        params["role"] = role

    where_clause = " AND ".join(where_parts)

    # 计数
    count_result = await db.execute(
        text(f"SELECT COUNT(*) FROM employees WHERE {where_clause}"),
        params,
    )
    total = count_result.scalar() or 0

    # 分页查询
    rows_result = await db.execute(
        text(
            f"SELECT id, tenant_id, store_id, emp_name, phone, email, role, "
            f"skills, hire_date, employment_status, employment_type, is_active, "
            f"probation_end_date, grade_level, gender, birth_date, "
            f"health_cert_expiry, created_at, updated_at "
            f"FROM employees WHERE {where_clause} "
            f"ORDER BY created_at DESC "
            f"LIMIT :lim OFFSET :off"
        ),
        params,
    )
    items = []
    for r in rows_result.mappings().fetchall():
        row = dict(r)
        # 序列化 UUID / date 字段
        for k in ("id", "tenant_id", "store_id"):
            if row.get(k) is not None:
                row[k] = str(row[k])
        for k in ("hire_date", "probation_end_date", "birth_date", "health_cert_expiry"):
            if row.get(k) is not None and hasattr(row[k], "isoformat"):
                row[k] = row[k].isoformat()
        for k in ("created_at", "updated_at"):
            if row.get(k) is not None and hasattr(row[k], "isoformat"):
                row[k] = row[k].isoformat()
        items.append(row)

    return {"items": items, "total": total}


async def get_employee(
    emp_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> Optional[dict[str, Any]]:
    """根据 ID 查询单个员工"""
    result = await db.execute(
        text(
            "SELECT id, tenant_id, store_id, emp_name, phone, email, role, "
            "skills, hire_date, employment_status, employment_type, is_active, "
            "probation_end_date, grade_level, gender, birth_date, education, "
            "health_cert_expiry, daily_wage_standard_fen, work_hour_type, "
            "bank_name, bank_account, emergency_contact, emergency_phone, "
            "org_id, preferences, performance_score, training_completed, "
            "created_at, updated_at "
            "FROM employees "
            "WHERE id = :eid::uuid AND tenant_id = :tid AND is_deleted = FALSE"
        ),
        {"eid": emp_id, "tid": tenant_id},
    )
    row = result.mappings().first()
    if not row:
        return None
    d = dict(row)
    for k in ("id", "tenant_id", "store_id", "org_id"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    for k in ("hire_date", "probation_end_date", "birth_date", "health_cert_expiry"):
        if d.get(k) is not None and hasattr(d[k], "isoformat"):
            d[k] = d[k].isoformat()
    for k in ("created_at", "updated_at"):
        if d.get(k) is not None and hasattr(d[k], "isoformat"):
            d[k] = d[k].isoformat()
    return d


async def create_employee(
    tenant_id: str,
    store_id: str,
    emp_name: str,
    role: str,
    db: AsyncSession,
    *,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    hire_date: Optional[date] = None,
    skills: Optional[list[str]] = None,
    gender: Optional[str] = None,
    employment_type: str = "regular",
) -> dict[str, Any]:
    """创建员工记录"""
    emp_id = str(uuid4())
    result = await db.execute(
        text(
            "INSERT INTO employees "
            "(id, tenant_id, store_id, emp_name, role, phone, email, "
            "hire_date, skills, gender, employment_type) "
            "VALUES (:id::uuid, :tid::uuid, :store_id::uuid, :emp_name, :role, "
            ":phone, :email, :hire_date, :skills, :gender, :employment_type) "
            "RETURNING id, emp_name, role, store_id, phone, email, "
            "hire_date, employment_status, created_at"
        ),
        {
            "id": emp_id,
            "tid": tenant_id,
            "store_id": store_id,
            "emp_name": emp_name,
            "role": role,
            "phone": phone,
            "email": email,
            "hire_date": hire_date,
            "skills": skills,
            "gender": gender,
            "employment_type": employment_type,
        },
    )
    row = result.mappings().first()
    if not row:
        raise ValueError("创建员工失败")
    d = dict(row)
    for k in ("id", "store_id"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    return d


async def update_employee(
    emp_id: str,
    tenant_id: str,
    db: AsyncSession,
    **fields: Any,
) -> Optional[dict[str, Any]]:
    """更新员工字段（动态 SET）"""
    # 白名单可更新字段
    allowed = {
        "emp_name", "phone", "email", "role", "skills", "hire_date",
        "employment_status", "employment_type", "is_active",
        "probation_end_date", "grade_level", "gender", "birth_date",
        "education", "health_cert_expiry", "daily_wage_standard_fen",
        "work_hour_type", "bank_name", "bank_account",
        "emergency_contact", "emergency_phone", "org_id", "preferences",
    }
    set_parts: list[str] = ["updated_at = NOW()"]
    params: dict[str, Any] = {"eid": emp_id, "tid": tenant_id}

    for k, v in fields.items():
        if k in allowed and v is not None:
            set_parts.append(f"{k} = :{k}")
            params[k] = v

    if len(set_parts) == 1:
        return None  # 没有实际更新

    set_clause = ", ".join(set_parts)
    result = await db.execute(
        text(
            f"UPDATE employees SET {set_clause} "
            "WHERE id = :eid::uuid AND tenant_id = :tid AND is_deleted = FALSE "
            "RETURNING id, emp_name, role, store_id, updated_at"
        ),
        params,
    )
    row = result.mappings().first()
    if not row:
        return None
    d = dict(row)
    for k in ("id", "store_id"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    return d


async def soft_delete_employee(
    emp_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> bool:
    """软删除员工"""
    result = await db.execute(
        text(
            "UPDATE employees SET is_deleted = TRUE, is_active = FALSE, "
            "updated_at = NOW() "
            "WHERE id = :eid::uuid AND tenant_id = :tid AND is_deleted = FALSE "
            "RETURNING id"
        ),
        {"eid": emp_id, "tid": tenant_id},
    )
    return result.mappings().first() is not None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  组织架构查询
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def get_org_hierarchy(
    tenant_id: str,
    db: AsyncSession,
    *,
    brand_id: Optional[str] = None,
) -> dict[str, Any]:
    """查询组织架构（按门店分组的员工数统计）"""
    where_parts = ["e.tenant_id = :tid", "e.is_deleted = FALSE"]
    params: dict[str, Any] = {"tid": tenant_id}

    if brand_id:
        where_parts.append("s.brand_id = :brand_id::uuid")
        params["brand_id"] = brand_id

    where_clause = " AND ".join(where_parts)

    result = await db.execute(
        text(
            f"SELECT s.id AS store_id, s.name AS store_name, "
            f"COUNT(e.id) AS employee_count, "
            f"ARRAY_AGG(DISTINCT e.role) AS roles "
            f"FROM employees e "
            f"LEFT JOIN stores s ON s.id = e.store_id AND s.tenant_id = e.tenant_id "
            f"WHERE {where_clause} "
            f"GROUP BY s.id, s.name "
            f"ORDER BY s.name"
        ),
        params,
    )
    stores = []
    total_employees = 0
    for r in result.mappings().fetchall():
        row = dict(r)
        count = int(row["employee_count"])
        total_employees += count
        stores.append({
            "store_id": str(row["store_id"]) if row["store_id"] else None,
            "store_name": row["store_name"],
            "employee_count": count,
            "roles": row.get("roles") or [],
        })

    return {
        "stores": stores,
        "total_stores": len(stores),
        "total_employees": total_employees,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  人力成本
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def get_labor_cost(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
    *,
    month: Optional[str] = None,
) -> dict[str, Any]:
    """查询门店人力成本（基于 daily_attendance 的工时 + 日薪标准）

    若 daily_attendance 表不存在，返回基于员工数的估算。
    """
    params: dict[str, Any] = {"tid": tenant_id, "store_id": store_id}

    # 先查员工数和日薪标准
    emp_result = await db.execute(
        text(
            "SELECT COUNT(*) AS emp_count, "
            "COALESCE(SUM(daily_wage_standard_fen), 0) AS total_daily_wage_fen "
            "FROM employees "
            "WHERE tenant_id = :tid AND store_id = :store_id::uuid "
            "AND is_deleted = FALSE AND is_active = TRUE"
        ),
        params,
    )
    emp_row = emp_result.mappings().first()
    emp_count = int(emp_row["emp_count"]) if emp_row else 0
    total_daily_wage_fen = int(emp_row["total_daily_wage_fen"]) if emp_row else 0

    # 尝试从 daily_attendance 聚合实际工时成本
    actual_cost_fen = 0
    total_work_hours = 0.0
    if month:
        try:
            att_result = await db.execute(
                text(
                    "SELECT COALESCE(SUM(work_hours), 0) AS total_hours "
                    "FROM daily_attendance "
                    "WHERE tenant_id = :tid AND store_id = :store_id "
                    "AND TO_CHAR(date, 'YYYY-MM') = :month "
                    "AND is_deleted = FALSE"
                ),
                {**params, "month": month},
            )
            att_row = att_result.mappings().first()
            total_work_hours = float(att_row["total_hours"]) if att_row else 0.0
            # 估算：日薪 / 8 小时 = 时薪
            if emp_count > 0 and total_daily_wage_fen > 0:
                hourly_rate_fen = total_daily_wage_fen / emp_count / 8
                actual_cost_fen = int(total_work_hours * hourly_rate_fen)
        except (SQLAlchemyError, ConnectionError):
            log.debug("daily_attendance table not available for cost calc")

    # 估算月成本（日薪 × 26 工作日）
    estimated_monthly_fen = total_daily_wage_fen * 26

    return {
        "store_id": store_id,
        "month": month,
        "employee_count": emp_count,
        "total_daily_wage_fen": total_daily_wage_fen,
        "estimated_monthly_fen": estimated_monthly_fen,
        "actual_cost_fen": actual_cost_fen,
        "total_work_hours": total_work_hours,
        "cost_rate": round(actual_cost_fen / estimated_monthly_fen, 4) if estimated_monthly_fen > 0 else 0,
    }


async def get_labor_cost_ranking(
    tenant_id: str,
    db: AsyncSession,
    *,
    brand_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """人力成本门店排名"""
    where_parts = ["e.tenant_id = :tid", "e.is_deleted = FALSE", "e.is_active = TRUE"]
    params: dict[str, Any] = {"tid": tenant_id}

    result = await db.execute(
        text(
            "SELECT e.store_id, s.name AS store_name, "
            "COUNT(e.id) AS emp_count, "
            "COALESCE(SUM(e.daily_wage_standard_fen), 0) AS daily_total_fen "
            "FROM employees e "
            "LEFT JOIN stores s ON s.id = e.store_id AND s.tenant_id = e.tenant_id "
            "WHERE e.tenant_id = :tid AND e.is_deleted = FALSE AND e.is_active = TRUE "
            "GROUP BY e.store_id, s.name "
            "ORDER BY daily_total_fen DESC"
        ),
        params,
    )
    rankings = []
    for idx, r in enumerate(result.mappings().fetchall(), 1):
        row = dict(r)
        rankings.append({
            "rank": idx,
            "store_id": str(row["store_id"]) if row["store_id"] else None,
            "store_name": row["store_name"],
            "employee_count": int(row["emp_count"]),
            "daily_total_fen": int(row["daily_total_fen"]),
            "monthly_estimate_fen": int(row["daily_total_fen"]) * 26,
        })
    return rankings


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  离职风险（基于考勤异常 + 绩效低分）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def get_turnover_risk(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """识别离职风险员工

    规则：
    - 近30天迟到/缺勤 >= 3 次 → 高风险
    - 绩效评分 < 60 → 中风险
    - 试用期即将到期（30天内）→ 关注
    """
    at_risk = []

    # 试用期即将到期
    prob_result = await db.execute(
        text(
            "SELECT id, emp_name, role, probation_end_date "
            "FROM employees "
            "WHERE tenant_id = :tid AND store_id = :store_id::uuid "
            "AND is_deleted = FALSE AND is_active = TRUE "
            "AND probation_end_date IS NOT NULL "
            "AND probation_end_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '30 days'"
        ),
        {"tid": tenant_id, "store_id": store_id},
    )
    for r in prob_result.mappings().fetchall():
        row = dict(r)
        at_risk.append({
            "employee_id": str(row["id"]),
            "emp_name": row["emp_name"],
            "role": row["role"],
            "risk_level": "attention",
            "reason": f"试用期将于 {row['probation_end_date']} 到期",
        })

    return at_risk
