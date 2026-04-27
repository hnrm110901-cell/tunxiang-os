"""新员工训练路径 API 路由 — onboarding_paths 表

端点列表：
  GET    /api/v1/onboarding-paths                              训练路径列表（分页+筛选）
  POST   /api/v1/onboarding-paths                              创建训练路径（含默认任务模板生成）
  GET    /api/v1/onboarding-paths/dashboard                    训练总览看板
  GET    /api/v1/onboarding-paths/templates                    训练模板列表
  GET    /api/v1/onboarding-paths/{path_id}                    路径详情
  PUT    /api/v1/onboarding-paths/{path_id}                    更新路径
  PUT    /api/v1/onboarding-paths/{path_id}/task/{task_idx}    完成单个任务
  PUT    /api/v1/onboarding-paths/{path_id}/advance-day        推进训练日
  PUT    /api/v1/onboarding-paths/{path_id}/complete           完成训练
  PUT    /api/v1/onboarding-paths/{path_id}/terminate          终止训练
  DELETE /api/v1/onboarding-paths/{path_id}                    软删除

统一响应格式: {"ok": bool, "data": {}, "error": null}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any, List, Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/onboarding-paths", tags=["onboarding-paths"])


# ── 默认训练模板 ────────────────────────────────────────────────────────────────

TEMPLATE_7_DAYS: list[dict] = [
    {"day": 1, "task": "企业文化与制度学习", "type": "theory", "required": True, "completed": False},
    {"day": 1, "task": "门店环境熟悉与安全培训", "type": "practice", "required": True, "completed": False},
    {"day": 2, "task": "岗位职责与工作流程", "type": "theory", "required": True, "completed": False},
    {"day": 2, "task": "基础操作实操训练", "type": "practice", "required": True, "completed": False},
    {"day": 3, "task": "服务标准与话术训练", "type": "practice", "required": True, "completed": False},
    {"day": 4, "task": "独立操作考核（带教在旁）", "type": "exam", "required": True, "completed": False},
    {"day": 5, "task": "高峰期实战（午市）", "type": "practice", "required": True, "completed": False},
    {"day": 6, "task": "高峰期实战（晚市）", "type": "practice", "required": True, "completed": False},
    {"day": 7, "task": "综合考核与通关评估", "type": "exam", "required": True, "completed": False},
]

TEMPLATE_14_DAYS: list[dict] = [
    *TEMPLATE_7_DAYS[:4],
    {"day": 3, "task": "菜品知识学习（原料与口味）", "type": "theory", "required": True, "completed": False},
    {"day": 4, "task": "菜品知识考核", "type": "exam", "required": True, "completed": False},
    {"day": 5, "task": "设备操作培训", "type": "practice", "required": True, "completed": False},
    {"day": 6, "task": "设备操作考核", "type": "exam", "required": True, "completed": False},
    {"day": 7, "task": "服务标准与话术训练", "type": "practice", "required": True, "completed": False},
    {"day": 8, "task": "客诉处理流程学习", "type": "theory", "required": True, "completed": False},
    {"day": 9, "task": "客诉处理模拟演练", "type": "practice", "required": True, "completed": False},
    {"day": 10, "task": "交叉岗位体验（前厅）", "type": "practice", "required": True, "completed": False},
    {"day": 11, "task": "交叉岗位体验（后厨）", "type": "practice", "required": True, "completed": False},
    {"day": 12, "task": "独立值班（午市）", "type": "practice", "required": True, "completed": False},
    {"day": 13, "task": "独立值班（晚市）", "type": "practice", "required": True, "completed": False},
    {"day": 14, "task": "综合考核与通关评估", "type": "exam", "required": True, "completed": False},
]

TEMPLATE_30_DAYS: list[dict] = [
    *TEMPLATE_14_DAYS,
    {"day": 15, "task": "成本管理基础（食材成本）", "type": "theory", "required": True, "completed": False},
    {"day": 16, "task": "成本管理基础（人力成本）", "type": "theory", "required": True, "completed": False},
    {"day": 17, "task": "成本控制实操", "type": "practice", "required": True, "completed": False},
    {"day": 18, "task": "成本管理考核", "type": "exam", "required": True, "completed": False},
    {"day": 19, "task": "带新人实习（观摩）", "type": "practice", "required": True, "completed": False},
    {"day": 20, "task": "带新人实习（辅助带教）", "type": "practice", "required": True, "completed": False},
    {"day": 21, "task": "带新人实习（独立带教）", "type": "practice", "required": True, "completed": False},
    {"day": 22, "task": "带教能力考核", "type": "exam", "required": True, "completed": False},
    {"day": 23, "task": "数据分析基础（营业数据）", "type": "theory", "required": True, "completed": False},
    {"day": 24, "task": "数据分析基础（客流数据）", "type": "theory", "required": True, "completed": False},
    {"day": 25, "task": "数据分析实操", "type": "practice", "required": True, "completed": False},
    {"day": 26, "task": "数据分析考核", "type": "exam", "required": True, "completed": False},
    {"day": 27, "task": "管理技能（团队沟通）", "type": "theory", "required": True, "completed": False},
    {"day": 28, "task": "管理技能（排班与调度）", "type": "theory", "required": True, "completed": False},
    {"day": 29, "task": "管理技能综合演练", "type": "practice", "required": True, "completed": False},
    {"day": 30, "task": "毕业答辩与综合评定", "type": "exam", "required": True, "completed": False},
]

TEMPLATES: dict[int, list[dict]] = {
    7: TEMPLATE_7_DAYS,
    14: TEMPLATE_14_DAYS,
    30: TEMPLATE_30_DAYS,
}


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


def _parse_jsonb(val: Any) -> Any:
    """安全解析 JSONB 字段"""
    if val is None:
        return None
    if isinstance(val, (list, dict)):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, ValueError):
            return val
    return val


def _row_to_dict(r) -> dict:
    """Convert a row mapping to a serialisable dict."""
    d = dict(r)
    for key in ("created_at", "updated_at", "completed_at", "start_date"):
        if d.get(key) is not None:
            d[key] = d[key].isoformat() if hasattr(d[key], "isoformat") else str(d[key])
    if "tasks" in d:
        d["tasks"] = _parse_jsonb(d["tasks"])
    # UUID → str
    for key in ("id", "tenant_id", "employee_id", "store_id", "mentor_id"):
        if d.get(key) is not None:
            d[key] = str(d[key])
    # Decimal → float
    for key in ("progress_pct", "readiness_score"):
        if d.get(key) is not None:
            d[key] = float(d[key])
    return d


# ── 查询列 ──────────────────────────────────────────────────────────────────

_SELECT_COLS = """
    id, tenant_id, employee_id, store_id,
    template_name, start_date, target_days, current_day,
    tasks, progress_pct, mentor_id, readiness_score,
    status, completed_at, is_deleted,
    created_at, updated_at
"""


# ── 请求模型 ──────────────────────────────────────────────────────────────────


class CreateOnboardingPathReq(BaseModel):
    employee_id: str = Field(..., min_length=1)
    store_id: str = Field(..., min_length=1)
    template_name: Optional[str] = Field("标准入职路径", max_length=100)
    start_date: Optional[date] = None
    target_days: int = Field(7, description="7/14/30")
    mentor_id: Optional[str] = None
    custom_tasks: Optional[List[dict]] = None  # 自定义任务列表，覆盖模板


class UpdateOnboardingPathReq(BaseModel):
    template_name: Optional[str] = Field(None, max_length=100)
    mentor_id: Optional[str] = None
    target_days: Optional[int] = None
    readiness_score: Optional[float] = Field(None, ge=0, le=10)


class TerminateReq(BaseModel):
    notes: Optional[str] = None


# ── 1. GET /api/v1/onboarding-paths  训练路径列表 ──────────────────────────────


@router.get("")
async def list_onboarding_paths(
    request: Request,
    store_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    employee_id: Optional[str] = Query(None),
    mentor_id: Optional[str] = Query(None),
    target_days: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    where_clauses = ["is_deleted = FALSE", "tenant_id = :tenant_id"]
    params: dict[str, Any] = {"tenant_id": tenant_id}

    if store_id:
        where_clauses.append("store_id = :store_id")
        params["store_id"] = store_id
    if status:
        where_clauses.append("status = :status")
        params["status"] = status
    if employee_id:
        where_clauses.append("employee_id = :employee_id")
        params["employee_id"] = employee_id
    if mentor_id:
        where_clauses.append("mentor_id = :mentor_id")
        params["mentor_id"] = mentor_id
    if target_days:
        where_clauses.append("target_days = :target_days")
        params["target_days"] = target_days

    where_sql = " AND ".join(where_clauses)

    # count
    count_result = await db.execute(
        text(f"SELECT COUNT(*) FROM onboarding_paths WHERE {where_sql}"),
        params,
    )
    total = count_result.scalar() or 0

    # data
    offset = (page - 1) * size
    params["limit"] = size
    params["offset"] = offset
    result = await db.execute(
        text(f"""
            SELECT {_SELECT_COLS}
            FROM onboarding_paths
            WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    rows = [_row_to_dict(r._mapping) for r in result.fetchall()]

    return _ok({"items": rows, "total": total, "page": page, "size": size})


# ── 2. POST /api/v1/onboarding-paths  创建训练路径 ─────────────────────────────


@router.post("")
async def create_onboarding_path(
    request: Request,
    body: CreateOnboardingPathReq,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    path_id = str(uuid4())
    start = body.start_date or date.today()

    # 选择任务模板
    if body.custom_tasks:
        tasks = body.custom_tasks
    else:
        template = TEMPLATES.get(body.target_days)
        if not template:
            raise HTTPException(
                status_code=400,
                detail=f"target_days 必须为 7/14/30，收到: {body.target_days}",
            )
        tasks = [dict(t) for t in template]  # 深拷贝

    tasks_json = json.dumps(tasks, ensure_ascii=False)

    await db.execute(
        text("""
            INSERT INTO onboarding_paths (
                id, tenant_id, employee_id, store_id,
                template_name, start_date, target_days, current_day,
                tasks, progress_pct, mentor_id, readiness_score,
                status, is_deleted, created_at, updated_at
            ) VALUES (
                :id, :tenant_id, :employee_id, :store_id,
                :template_name, :start_date, :target_days, 1,
                :tasks::jsonb, 0, :mentor_id, 0,
                'in_progress', FALSE, NOW(), NOW()
            )
        """),
        {
            "id": path_id,
            "tenant_id": tenant_id,
            "employee_id": body.employee_id,
            "store_id": body.store_id,
            "template_name": body.template_name or "标准入职路径",
            "start_date": start,
            "target_days": body.target_days,
            "tasks": tasks_json,
            "mentor_id": body.mentor_id,
        },
    )
    await db.commit()

    log.info(
        "onboarding_path.created",
        path_id=path_id,
        employee_id=body.employee_id,
        target_days=body.target_days,
    )

    return _ok({"id": path_id, "target_days": body.target_days, "task_count": len(tasks)})


# ── 3. GET /api/v1/onboarding-paths/dashboard  训练总览看板 ────────────────────


@router.get("/dashboard")
async def onboarding_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 总览统计
    summary_result = await db.execute(
        text("""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE status = 'in_progress') AS in_progress,
                COUNT(*) FILTER (WHERE status = 'completed') AS completed,
                COUNT(*) FILTER (WHERE status = 'overdue') AS overdue,
                COUNT(*) FILTER (WHERE status = 'terminated') AS terminated,
                COALESCE(
                    AVG(
                        EXTRACT(DAY FROM (completed_at - created_at))
                    ) FILTER (WHERE status = 'completed'),
                    0
                ) AS avg_completion_days
            FROM onboarding_paths
            WHERE tenant_id = :tenant_id AND is_deleted = FALSE
        """),
        {"tenant_id": tenant_id},
    )
    summary_row = summary_result.fetchone()._mapping

    # 按门店分组
    by_store_result = await db.execute(
        text("""
            SELECT
                store_id::text,
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE status = 'in_progress') AS in_progress,
                COUNT(*) FILTER (WHERE status = 'completed') AS completed,
                COUNT(*) FILTER (WHERE status = 'overdue') AS overdue
            FROM onboarding_paths
            WHERE tenant_id = :tenant_id AND is_deleted = FALSE
            GROUP BY store_id
            ORDER BY total DESC
        """),
        {"tenant_id": tenant_id},
    )
    by_store = [dict(r._mapping) for r in by_store_result.fetchall()]

    # 按路径类型分组
    by_target_result = await db.execute(
        text("""
            SELECT
                target_days,
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE status = 'in_progress') AS in_progress,
                COUNT(*) FILTER (WHERE status = 'completed') AS completed,
                COUNT(*) FILTER (WHERE status = 'overdue') AS overdue
            FROM onboarding_paths
            WHERE tenant_id = :tenant_id AND is_deleted = FALSE
            GROUP BY target_days
            ORDER BY target_days
        """),
        {"tenant_id": tenant_id},
    )
    by_target_days = [dict(r._mapping) for r in by_target_result.fetchall()]

    return _ok(
        {
            "total": summary_row["total"],
            "in_progress": summary_row["in_progress"],
            "completed": summary_row["completed"],
            "overdue": summary_row["overdue"],
            "terminated": summary_row["terminated"],
            "avg_completion_days": round(float(summary_row["avg_completion_days"]), 1),
            "by_store": by_store,
            "by_target_days": by_target_days,
        }
    )


# ── 4. GET /api/v1/onboarding-paths/templates  训练模板列表 ────────────────────


@router.get("/templates")
async def list_templates():
    templates = []
    for days, tasks in TEMPLATES.items():
        templates.append(
            {
                "target_days": days,
                "name": {7: "7天速成模板", 14: "14天标准模板", 30: "30天深度模板"}[days],
                "task_count": len(tasks),
                "tasks": tasks,
            }
        )
    return _ok(templates)


# ── 5. GET /api/v1/onboarding-paths/{path_id}  路径详情 ────────────────────────


@router.get("/{path_id}")
async def get_onboarding_path(
    request: Request,
    path_id: str,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    result = await db.execute(
        text(f"""
            SELECT {_SELECT_COLS}
            FROM onboarding_paths
            WHERE id = :path_id AND tenant_id = :tenant_id AND is_deleted = FALSE
        """),
        {"path_id": path_id, "tenant_id": tenant_id},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="训练路径不存在")

    return _ok(_row_to_dict(row._mapping))


# ── 6. PUT /api/v1/onboarding-paths/{path_id}  更新路径 ────────────────────────


@router.put("/{path_id}")
async def update_onboarding_path(
    request: Request,
    path_id: str,
    body: UpdateOnboardingPathReq,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    set_parts: list[str] = ["updated_at = NOW()"]
    params: dict[str, Any] = {"path_id": path_id, "tenant_id": tenant_id}

    if body.template_name is not None:
        set_parts.append("template_name = :template_name")
        params["template_name"] = body.template_name
    if body.mentor_id is not None:
        set_parts.append("mentor_id = :mentor_id")
        params["mentor_id"] = body.mentor_id
    if body.target_days is not None:
        set_parts.append("target_days = :target_days")
        params["target_days"] = body.target_days
    if body.readiness_score is not None:
        set_parts.append("readiness_score = :readiness_score")
        params["readiness_score"] = body.readiness_score

    if len(set_parts) == 1:
        raise HTTPException(status_code=400, detail="至少提供一个更新字段")

    result = await db.execute(
        text(f"""
            UPDATE onboarding_paths
            SET {", ".join(set_parts)}
            WHERE id = :path_id AND tenant_id = :tenant_id AND is_deleted = FALSE
            RETURNING id
        """),
        params,
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="训练路径不存在")

    await db.commit()
    log.info("onboarding_path.updated", path_id=path_id)
    return _ok({"id": path_id, "updated": True})


# ── 7. PUT /api/v1/onboarding-paths/{path_id}/task/{task_idx}  完成单个任务 ───


@router.put("/{path_id}/task/{task_idx}")
async def complete_task(
    request: Request,
    path_id: str,
    task_idx: int,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 读取当前 tasks
    result = await db.execute(
        text("""
            SELECT tasks, status
            FROM onboarding_paths
            WHERE id = :path_id AND tenant_id = :tenant_id AND is_deleted = FALSE
        """),
        {"path_id": path_id, "tenant_id": tenant_id},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="训练路径不存在")

    mapping = row._mapping
    if mapping["status"] not in ("in_progress", "overdue"):
        raise HTTPException(status_code=400, detail=f"当前状态 {mapping['status']} 不允许完成任务")

    tasks = _parse_jsonb(mapping["tasks"]) or []
    if task_idx < 0 or task_idx >= len(tasks):
        raise HTTPException(status_code=400, detail=f"任务索引 {task_idx} 超出范围 (0-{len(tasks) - 1})")

    if tasks[task_idx].get("completed"):
        raise HTTPException(status_code=400, detail="该任务已完成")

    now_str = datetime.now(timezone.utc).isoformat()

    # 用 jsonb_set 更新单个任务的 completed 和 completed_at
    await db.execute(
        text("""
            UPDATE onboarding_paths
            SET tasks = jsonb_set(
                    jsonb_set(
                        tasks,
                        ARRAY[:idx_str, 'completed'],
                        'true'::jsonb
                    ),
                    ARRAY[:idx_str, 'completed_at'],
                    to_jsonb(:now_str::text)
                ),
                updated_at = NOW()
            WHERE id = :path_id AND tenant_id = :tenant_id AND is_deleted = FALSE
        """),
        {
            "idx_str": str(task_idx),
            "now_str": now_str,
            "path_id": path_id,
            "tenant_id": tenant_id,
        },
    )

    # 重算 progress_pct
    # 更新内存中的 tasks 用于计算
    tasks[task_idx]["completed"] = True
    total_required = sum(1 for t in tasks if t.get("required"))
    completed_required = sum(1 for t in tasks if t.get("required") and t.get("completed"))
    progress = round(completed_required / total_required * 100, 2) if total_required > 0 else 0

    await db.execute(
        text("""
            UPDATE onboarding_paths
            SET progress_pct = :progress, updated_at = NOW()
            WHERE id = :path_id AND tenant_id = :tenant_id AND is_deleted = FALSE
        """),
        {"progress": progress, "path_id": path_id, "tenant_id": tenant_id},
    )

    await db.commit()
    log.info("onboarding_path.task_completed", path_id=path_id, task_idx=task_idx, progress=progress)

    return _ok(
        {
            "id": path_id,
            "task_idx": task_idx,
            "progress_pct": progress,
            "completed_required": completed_required,
            "total_required": total_required,
        }
    )


# ── 8. PUT /api/v1/onboarding-paths/{path_id}/advance-day  推进训练日 ──────────


@router.put("/{path_id}/advance-day")
async def advance_day(
    request: Request,
    path_id: str,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    result = await db.execute(
        text("""
            SELECT current_day, target_days, status
            FROM onboarding_paths
            WHERE id = :path_id AND tenant_id = :tenant_id AND is_deleted = FALSE
        """),
        {"path_id": path_id, "tenant_id": tenant_id},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="训练路径不存在")

    mapping = row._mapping
    if mapping["status"] not in ("in_progress", "overdue"):
        raise HTTPException(status_code=400, detail=f"当前状态 {mapping['status']} 不允许推进")

    new_day = mapping["current_day"] + 1
    new_status = mapping["status"]

    # 超过 target_days 且仍为 in_progress → overdue
    if new_day > mapping["target_days"] and mapping["status"] == "in_progress":
        new_status = "overdue"

    await db.execute(
        text("""
            UPDATE onboarding_paths
            SET current_day = :new_day, status = :new_status, updated_at = NOW()
            WHERE id = :path_id AND tenant_id = :tenant_id AND is_deleted = FALSE
        """),
        {
            "new_day": new_day,
            "new_status": new_status,
            "path_id": path_id,
            "tenant_id": tenant_id,
        },
    )
    await db.commit()

    log.info("onboarding_path.day_advanced", path_id=path_id, new_day=new_day, status=new_status)
    return _ok({"id": path_id, "current_day": new_day, "status": new_status})


# ── 9. PUT /api/v1/onboarding-paths/{path_id}/complete  完成训练 ───────────────


@router.put("/{path_id}/complete")
async def complete_onboarding(
    request: Request,
    path_id: str,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    result = await db.execute(
        text("""
            SELECT tasks, status, progress_pct
            FROM onboarding_paths
            WHERE id = :path_id AND tenant_id = :tenant_id AND is_deleted = FALSE
        """),
        {"path_id": path_id, "tenant_id": tenant_id},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="训练路径不存在")

    mapping = row._mapping
    if mapping["status"] not in ("in_progress", "overdue"):
        raise HTTPException(status_code=400, detail=f"当前状态 {mapping['status']} 不允许完成")

    tasks = _parse_jsonb(mapping["tasks"]) or []
    # 校验所有 required 任务已完成
    uncompleted = [t["task"] for t in tasks if t.get("required") and not t.get("completed")]
    if uncompleted:
        raise HTTPException(
            status_code=400,
            detail=f"还有 {len(uncompleted)} 个必修任务未完成: {', '.join(uncompleted[:3])}",
        )

    # readiness_score = progress_pct / 10
    progress = float(mapping["progress_pct"]) if mapping["progress_pct"] else 0
    readiness = round(progress / 10, 1)

    await db.execute(
        text("""
            UPDATE onboarding_paths
            SET status = 'completed',
                completed_at = NOW(),
                readiness_score = :readiness,
                progress_pct = 100,
                updated_at = NOW()
            WHERE id = :path_id AND tenant_id = :tenant_id AND is_deleted = FALSE
        """),
        {"readiness": readiness, "path_id": path_id, "tenant_id": tenant_id},
    )
    await db.commit()

    log.info("onboarding_path.completed", path_id=path_id, readiness_score=readiness)
    return _ok({"id": path_id, "status": "completed", "readiness_score": readiness})


# ── 10. PUT /api/v1/onboarding-paths/{path_id}/terminate  终止训练 ─────────────


@router.put("/{path_id}/terminate")
async def terminate_onboarding(
    request: Request,
    path_id: str,
    body: TerminateReq,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    result = await db.execute(
        text("""
            SELECT status
            FROM onboarding_paths
            WHERE id = :path_id AND tenant_id = :tenant_id AND is_deleted = FALSE
        """),
        {"path_id": path_id, "tenant_id": tenant_id},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="训练路径不存在")

    if row._mapping["status"] in ("completed", "terminated"):
        raise HTTPException(
            status_code=400,
            detail=f"当前状态 {row._mapping['status']} 不允许终止",
        )

    await db.execute(
        text("""
            UPDATE onboarding_paths
            SET status = 'terminated', updated_at = NOW()
            WHERE id = :path_id AND tenant_id = :tenant_id AND is_deleted = FALSE
        """),
        {"path_id": path_id, "tenant_id": tenant_id},
    )
    await db.commit()

    log.info("onboarding_path.terminated", path_id=path_id, notes=body.notes)
    return _ok({"id": path_id, "status": "terminated"})


# ── 11. DELETE /api/v1/onboarding-paths/{path_id}  软删除 ─────────────────────


@router.delete("/{path_id}")
async def delete_onboarding_path(
    request: Request,
    path_id: str,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    result = await db.execute(
        text("""
            UPDATE onboarding_paths
            SET is_deleted = TRUE, updated_at = NOW()
            WHERE id = :path_id AND tenant_id = :tenant_id AND is_deleted = FALSE
            RETURNING id
        """),
        {"path_id": path_id, "tenant_id": tenant_id},
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="训练路径不存在")

    await db.commit()
    log.info("onboarding_path.deleted", path_id=path_id)
    return _ok({"id": path_id, "deleted": True})
