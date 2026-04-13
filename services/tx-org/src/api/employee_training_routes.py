"""
员工培训管理路由 — DB持久化版
OR-02: employee_trainings / training_plans 表（v104迁移）
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/org/training", tags=["employee-training"])

# ── 常量 ─────────────────────────────────────────────────────────────────────

TRAINING_TYPES = ("onboarding", "food_safety", "service", "skills", "compliance", "other")
STATUSES = ("scheduled", "in_progress", "completed", "failed")

# 证书到期风险映射：type → (days_warn, risk_level)
CERT_RISK = {
    "food_safety": (30, "high"),
    "compliance": (30, "medium"),
    "onboarding": (60, "low"),
}
DEFAULT_CERT_RISK = (30, "medium")

# ── 辅助函数 ─────────────────────────────────────────────────────────────────


def _parse_tenant(x_tenant_id: str) -> str:
    try:
        uuid.UUID(x_tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="X-Tenant-ID 须为合法 UUID") from e
    return x_tenant_id


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _days_until(expires_str: str) -> int:
    today = date.today()
    exp = date.fromisoformat(expires_str)
    return (exp - today).days


def _cert_status(days: int) -> str:
    if days < 0:
        return "expired"
    if days <= 7:
        return "critical"
    if days <= 30:
        return "warning"
    return "ok"


# ── Pydantic 模型 ─────────────────────────────────────────────────────────────


class TrainingRecordCreate(BaseModel):
    employee_id: str = Field(..., description="员工ID")
    training_type: str = Field(default="other", description="培训类型")
    training_name: str = Field(..., description="培训名称", min_length=1, max_length=100)
    trainer_id: Optional[str] = Field(None, description="培训师员工ID")
    training_date: str = Field(..., description="培训日期 YYYY-MM-DD")
    duration_hours: float = Field(default=0.0, ge=0, description="培训时长（小时）")
    location: Optional[str] = Field(None, description="培训地点")
    score: Optional[float] = Field(None, ge=0, le=100, description="考核分数")
    passed: Optional[bool] = Field(None, description="是否通过")
    certificate_no: Optional[str] = Field(None, description="证书编号")
    certificate_expires_at: Optional[str] = Field(None, description="证书有效期 YYYY-MM-DD")
    notes: Optional[str] = Field(None, description="备注")
    status: str = Field(default="completed", description="培训状态")


class TrainingRecordUpdate(BaseModel):
    score: Optional[float] = Field(None, ge=0, le=100)
    certificate_no: Optional[str] = None  # maps to certificate_id
    status: Optional[str] = None


class TrainingPlanCreate(BaseModel):
    name: str = Field(..., description="计划名称", min_length=1, max_length=100)
    training_type: Optional[str] = Field(None, description="培训类型")
    store_id: Optional[str] = Field(None, description="门店ID，NULL=集团")
    frequency: Optional[str] = Field(None, description="once/monthly/quarterly/annual")
    required_roles: list[str] = Field(default_factory=list, description="必须参加的岗位列表")
    is_mandatory: bool = Field(default=True)
    reminder_days_before: int = Field(default=7, ge=0)


# ── 端点实现 ──────────────────────────────────────────────────────────────────


@router.get("/records")
async def list_training_records(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    employee_id: Optional[str] = Query(None, description="按员工ID过滤"),
    training_type: Optional[str] = Query(None, description="按培训类型过滤"),
    date_from: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """培训记录列表（支持 employee_id / training_type / date 过滤）。"""
    tid = _parse_tenant(x_tenant_id)
    await _set_rls(db, tid)

    conditions = ["tenant_id = :tid", "is_deleted = false"]
    params: dict = {"tid": tid}

    if employee_id:
        conditions.append("employee_id = :employee_id")
        params["employee_id"] = employee_id
    if training_type:
        # training_type maps to category in employee_trainings
        conditions.append("category = :category")
        params["category"] = training_type
    if date_from:
        conditions.append("assigned_at::date >= :date_from")
        params["date_from"] = date_from
    if date_to:
        conditions.append("assigned_at::date <= :date_to")
        params["date_to"] = date_to

    where = " AND ".join(conditions)
    offset = (page - 1) * size

    try:
        count_res = await db.execute(
            text(f"SELECT COUNT(*) FROM employee_trainings WHERE {where}"),
            params,
        )
        total = count_res.scalar() or 0

        rows_res = await db.execute(
            text(f"""
                SELECT id, employee_id, category, course_name, course_id,
                       assigned_at, completed_at, score, status,
                       certificate_id, pass_threshold,
                       created_at, updated_at
                FROM employee_trainings
                WHERE {where}
                ORDER BY assigned_at DESC, created_at DESC
                LIMIT :size OFFSET :offset
            """),
            {**params, "size": size, "offset": offset},
        )
        rows = rows_res.fetchall()

        items = []
        for r in rows:
            item = {
                "id": str(r.id),
                "employee_id": str(r.employee_id),
                "training_type": r.category,
                "training_name": r.course_name,
                "course_id": r.course_id,
                "training_date": r.assigned_at.date().isoformat() if r.assigned_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "score": int(r.score) if r.score is not None else None,
                "passed": r.status == "completed",
                "certificate_no": r.certificate_id,
                "pass_threshold": r.pass_threshold,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            items.append(item)

    except SQLAlchemyError as exc:
        logger.warning("training_records_db_fallback", error=str(exc))
        total = 0
        items = []

    logger.info("training_records_listed", tenant_id=tid, total=total, page=page)
    return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}


@router.post("/records")
async def create_training_record(
    body: TrainingRecordCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """新增培训记录。"""
    tid = _parse_tenant(x_tenant_id)
    await _set_rls(db, tid)

    # 参数校验
    if body.training_type not in TRAINING_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"training_type 须为 {'/'.join(TRAINING_TYPES)}",
        )
    if body.status not in STATUSES:
        raise HTTPException(status_code=400, detail=f"status 须为 {'/'.join(STATUSES)}")

    try:
        assigned_at = datetime.fromisoformat(body.training_date).replace(tzinfo=timezone.utc)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="training_date 格式须为 YYYY-MM-DD") from e

    record_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    # Determine completed_at: set when status is completed/failed
    completed_at = now if body.status in ("completed", "failed") else None
    # Map passed/score: score stored as INT, cast if provided
    score_int = int(body.score) if body.score is not None else None

    try:
        await db.execute(
            text("""
                INSERT INTO employee_trainings
                    (id, tenant_id, employee_id, category, course_name,
                     course_id, assigned_at, started_at, completed_at,
                     score, certificate_id, status,
                     is_deleted, created_at, updated_at)
                VALUES
                    (:id, :tid, :employee_id, :category, :course_name,
                     :course_id, :assigned_at, :started_at, :completed_at,
                     :score, :certificate_id, :status,
                     false, :now, :now)
            """),
            {
                "id": record_id,
                "tid": tid,
                "employee_id": body.employee_id,
                "category": body.training_type,
                "course_name": body.training_name,
                "course_id": None,
                "assigned_at": assigned_at,
                "started_at": assigned_at if body.status in ("in_progress", "completed", "failed") else None,
                "completed_at": completed_at,
                "score": score_int,
                "certificate_id": body.certificate_no,
                "status": body.status,
                "now": now,
            },
        )
        await db.commit()
    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="培训记录创建失败") from e

    logger.info(
        "training_record_created",
        record_id=str(record_id),
        employee_id=body.employee_id,
        training_name=body.training_name,
        tenant_id=tid,
    )
    return {"ok": True, "data": {"id": str(record_id), "status": body.status}}


@router.put("/records/{record_id}")
async def update_training_record(
    record_id: str,
    body: TrainingRecordUpdate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新培训记录（含成绩/证书信息）。"""
    tid = _parse_tenant(x_tenant_id)
    await _set_rls(db, tid)

    now = datetime.now(timezone.utc)
    set_parts = ["updated_at = :now"]
    params: dict = {"id": record_id, "tid": tid, "now": now}

    if body.score is not None:
        set_parts.append("score = :score")
        params["score"] = int(body.score)
    if body.certificate_no is not None:
        set_parts.append("certificate_id = :certificate_id")
        params["certificate_id"] = body.certificate_no
    if body.status is not None:
        if body.status not in STATUSES:
            raise HTTPException(status_code=400, detail=f"status 须为 {'/'.join(STATUSES)}")
        set_parts.append("status = :status")
        params["status"] = body.status
        # Auto-set completed_at when transitioning to terminal status
        if body.status in ("completed", "failed"):
            set_parts.append("completed_at = :completed_at")
            params["completed_at"] = now

    try:
        result = await db.execute(
            text(f"""
                UPDATE employee_trainings
                SET {', '.join(set_parts)}
                WHERE id = :id AND tenant_id = :tid AND is_deleted = false
                RETURNING id
            """),
            params,
        )
        updated = result.fetchone()
        if not updated:
            raise HTTPException(status_code=404, detail="培训记录不存在")
        await db.commit()
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="培训记录更新失败") from e

    logger.info("training_record_updated", record_id=record_id, tenant_id=tid)
    return {"ok": True, "data": {"id": record_id, "updated": True}}


@router.get("/records/expiring-certs")
async def get_expiring_certificates(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    days: int = Query(30, ge=1, le=365, description="多少天内到期"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """即将到期的证书列表。
    - food_safety 证书到期：高风险，需立即安排复训
    - compliance（消防等）证书到期：中风险
    """
    tid = _parse_tenant(x_tenant_id)
    await _set_rls(db, tid)

    today = date.today()
    cutoff = date.fromordinal(today.toordinal() + days)

    try:
        rows_res = await db.execute(
            text("""
                SELECT id, employee_id, category, course_name,
                       certificate_id, completed_at, status
                FROM employee_trainings
                WHERE tenant_id = :tid
                  AND is_deleted = false
                  AND certificate_id IS NOT NULL
                  AND status = 'completed'
                  AND completed_at IS NOT NULL
                  AND completed_at::date + INTERVAL '1 year' <= :cutoff
                  AND completed_at::date + INTERVAL '1 year' >= :today
                ORDER BY completed_at ASC
            """),
            {"tid": tid, "cutoff": cutoff, "today": today},
        )
        rows = rows_res.fetchall()

        items = []
        for r in rows:
            # Approximate certificate expiry as 1 year from completed_at
            if not r.completed_at:
                continue
            exp_date = date(
                r.completed_at.year + 1,
                r.completed_at.month,
                r.completed_at.day,
            )
            exp_str = exp_date.isoformat()
            days_remaining = _days_until(exp_str)
            _, risk_level = CERT_RISK.get(r.category or "", DEFAULT_CERT_RISK)
            if r.category == "food_safety":
                risk_level = "high"
            items.append({
                "record_id": str(r.id),
                "employee_id": str(r.employee_id),
                "training_type": r.category,
                "training_name": r.course_name,
                "certificate_no": r.certificate_id,
                "certificate_expires_at": exp_str,
                "days_remaining": days_remaining,
                "cert_status": _cert_status(days_remaining),
                "risk_level": risk_level,
                "action": "安排复训",
            })

    except SQLAlchemyError as exc:
        logger.warning("expiring_certs_db_fallback", error=str(exc))
        items = []

    logger.info("expiring_certs_queried", tenant_id=tid, days=days, count=len(items))
    return {"ok": True, "data": {"items": items, "total": len(items), "query_days": days}}


@router.get("/plans")
async def list_training_plans(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    store_id: Optional[str] = Query(None, description="门店ID，不传=集团"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """培训计划列表。"""
    tid = _parse_tenant(x_tenant_id)
    await _set_rls(db, tid)

    conditions = ["tenant_id = :tid", "is_active = true"]
    params: dict = {"tid": tid}
    if store_id:
        conditions.append("(store_id = :store_id OR store_id IS NULL)")
        params["store_id"] = store_id
    where = " AND ".join(conditions)

    try:
        rows_res = await db.execute(
            text(f"""
                SELECT id, store_id, name, training_type, frequency,
                       required_roles, is_mandatory, reminder_days_before, is_active,
                       created_at, updated_at
                FROM training_plans
                WHERE {where}
                ORDER BY created_at DESC
            """),
            params,
        )
        rows = rows_res.fetchall()
        items = [
            {
                "id": str(r.id),
                "store_id": str(r.store_id) if r.store_id else None,
                "name": r.name,
                "training_type": r.training_type,
                "frequency": r.frequency,
                "required_roles": r.required_roles or [],
                "is_mandatory": r.is_mandatory,
                "reminder_days_before": r.reminder_days_before,
                "is_active": r.is_active,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

    except SQLAlchemyError as exc:
        logger.warning("training_plans_db_fallback", error=str(exc))
        items = []

    return {"ok": True, "data": {"items": items, "total": len(items)}}


@router.post("/plans")
async def create_training_plan(
    body: TrainingPlanCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建培训计划。"""
    tid = _parse_tenant(x_tenant_id)
    await _set_rls(db, tid)

    import json
    plan_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    try:
        await db.execute(
            text("""
                INSERT INTO training_plans
                    (id, tenant_id, store_id, name, training_type, frequency,
                     required_roles, is_mandatory, reminder_days_before,
                     is_active, created_at, updated_at)
                VALUES
                    (:id, :tid, :store_id, :name, :training_type, :frequency,
                     :required_roles, :is_mandatory, :reminder_days_before,
                     true, :now, :now)
            """),
            {
                "id": plan_id,
                "tid": tid,
                "store_id": body.store_id,
                "name": body.name,
                "training_type": body.training_type,
                "frequency": body.frequency,
                "required_roles": json.dumps(body.required_roles, ensure_ascii=False),
                "is_mandatory": body.is_mandatory,
                "reminder_days_before": body.reminder_days_before,
                "now": now,
            },
        )
        await db.commit()
    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="培训计划创建失败") from e

    logger.info("training_plan_created", plan_id=str(plan_id), name=body.name, tenant_id=tid)
    return {"ok": True, "data": {"id": str(plan_id), "name": body.name}}


@router.get("/stats")
async def get_training_stats(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    month: Optional[str] = Query(None, description="月份 YYYY-MM，不传=当月"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """培训统计（部门培训完成率/证书持有率/本月培训人次）。"""
    tid = _parse_tenant(x_tenant_id)
    await _set_rls(db, tid)

    today = date.today()
    if month:
        try:
            year_s, mon_s = month.split("-")
            month_start = date(int(year_s), int(mon_s), 1)
        except ValueError as e:
            raise HTTPException(status_code=400, detail="month 格式须为 YYYY-MM") from e
    else:
        month_start = today.replace(day=1)

    if month_start.month == 12:
        month_end = date(month_start.year + 1, 1, 1)
    else:
        month_end = date(month_start.year, month_start.month + 1, 1)

    expiring_30_cutoff = date.fromordinal(today.toordinal() + 30)

    try:
        # 本月培训人次（以 assigned_at 为准）
        monthly_res = await db.execute(
            text("""
                SELECT COUNT(*) as count,
                       COUNT(CASE WHEN status = 'completed' THEN 1 END) as passed_count
                FROM employee_trainings
                WHERE tenant_id = :tid
                  AND is_deleted = false
                  AND assigned_at >= :month_start
                  AND assigned_at < :month_end
            """),
            {"tid": tid, "month_start": month_start, "month_end": month_end},
        )
        monthly_row = monthly_res.fetchone()
        monthly_count = monthly_row.count or 0
        monthly_passed = monthly_row.passed_count or 0
        pass_rate = round(monthly_passed / max(monthly_count, 1) * 100, 1)

        # 证书持有人数（持有 certificate_id 且已完成）
        cert_res = await db.execute(
            text("""
                SELECT COUNT(DISTINCT employee_id) as cert_holders
                FROM employee_trainings
                WHERE tenant_id = :tid
                  AND is_deleted = false
                  AND certificate_id IS NOT NULL
                  AND status = 'completed'
            """),
            {"tid": tid},
        )
        cert_holders = cert_res.scalar() or 0

        # 即将到期数（完成时间距今超过 335 天，约 30 天内到期，假设证书有效期 1 年）
        expiring_res = await db.execute(
            text("""
                SELECT COUNT(*) as expiring
                FROM employee_trainings
                WHERE tenant_id = :tid
                  AND is_deleted = false
                  AND certificate_id IS NOT NULL
                  AND status = 'completed'
                  AND completed_at IS NOT NULL
                  AND completed_at::date + INTERVAL '1 year' <= :cutoff
                  AND completed_at::date + INTERVAL '1 year' >= :today
            """),
            {"tid": tid, "cutoff": expiring_30_cutoff, "today": today},
        )
        expiring_count = expiring_res.scalar() or 0

        # 按培训类型分组统计
        by_type_res = await db.execute(
            text("""
                SELECT category,
                       COUNT(*) as total,
                       COUNT(CASE WHEN status = 'completed' THEN 1 END) as passed
                FROM employee_trainings
                WHERE tenant_id = :tid
                  AND is_deleted = false
                GROUP BY category
                ORDER BY total DESC
            """),
            {"tid": tid},
        )
        by_type = [
            {
                "training_type": r.category or "other",
                "total": r.total,
                "passed": r.passed,
                "pass_rate": round((r.passed or 0) / max(r.total, 1) * 100, 1),
            }
            for r in by_type_res.fetchall()
        ]

    except SQLAlchemyError as exc:
        logger.warning("training_stats_db_fallback", error=str(exc))
        monthly_count = 0
        monthly_passed = 0
        pass_rate = 0.0
        cert_holders = 0
        expiring_count = 0
        by_type = []

    return {
        "ok": True,
        "data": {
            "month": month_start.strftime("%Y-%m"),
            "monthly_count": monthly_count,
            "monthly_passed": monthly_passed,
            "pass_rate": pass_rate,
            "cert_holders": cert_holders,
            "expiring_30_days": expiring_count,
            "by_type": by_type,
        },
    }


@router.get("/employee/{employee_id}")
async def get_employee_training_profile(
    employee_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """员工个人培训档案（所有培训记录 + 证书状态）。"""
    tid = _parse_tenant(x_tenant_id)
    await _set_rls(db, tid)

    try:
        rows_res = await db.execute(
            text("""
                SELECT id, category, course_name, course_id,
                       assigned_at, started_at, completed_at,
                       score, certificate_id, status, created_at
                FROM employee_trainings
                WHERE tenant_id = :tid
                  AND employee_id = :eid
                  AND is_deleted = false
                ORDER BY assigned_at DESC
            """),
            {"tid": tid, "eid": employee_id},
        )
        rows = rows_res.fetchall()

        records = []
        active_certs = []

        for r in rows:
            item = {
                "id": str(r.id),
                "training_type": r.category,
                "training_name": r.course_name,
                "course_id": r.course_id,
                "training_date": r.assigned_at.date().isoformat() if r.assigned_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "score": int(r.score) if r.score is not None else None,
                "passed": r.status == "completed",
                "certificate_no": r.certificate_id,
                "status": r.status,
            }
            # Approximate cert expiry as 1 year from completed_at if certificate issued
            if r.certificate_id and r.completed_at:
                exp_date = date(
                    r.completed_at.year + 1,
                    r.completed_at.month,
                    r.completed_at.day,
                )
                exp_str = exp_date.isoformat()
                days = _days_until(exp_str)
                item["certificate_expires_at"] = exp_str
                item["cert_days_remaining"] = days
                item["cert_status"] = _cert_status(days)
                if days >= 0:
                    active_certs.append({
                        "training_type": r.category,
                        "training_name": r.course_name,
                        "certificate_no": r.certificate_id,
                        "certificate_expires_at": exp_str,
                        "days_remaining": days,
                        "cert_status": _cert_status(days),
                    })
            records.append(item)

        completed = sum(1 for r in records if r["status"] == "completed")
        failed = sum(1 for r in records if r["status"] == "failed")
        total = len(records)
        completion_rate = round(completed / max(total, 1) * 100, 1)

    except SQLAlchemyError as exc:
        logger.warning("employee_training_profile_db_fallback", error=str(exc), employee_id=employee_id)
        records = []
        active_certs = []
        completed = 0
        failed = 0
        total = 0
        completion_rate = 0.0

    return {
        "ok": True,
        "data": {
            "employee_id": employee_id,
            "summary": {
                "total_trainings": total,
                "completed": completed,
                "failed": failed,
                "completion_rate": completion_rate,
                "active_certificates": len(active_certs),
            },
            "certificates": active_certs,
            "records": records,
        },
    }
