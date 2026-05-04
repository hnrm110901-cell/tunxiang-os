"""营销任务日历 API — 任务CRUD/日历/生命周期/分配/执行/效果/排行榜

18个端点：
  CRUD (5):
    POST   /                        创建任务
    GET    /                        任务列表（分页）
    GET    /{id}                    任务详情
    PUT    /{id}                    更新任务
    DELETE /{id}                    删除任务

  Calendar (1):
    GET    /calendar                月视图日历

  Lifecycle (4):
    PUT    /{id}/schedule           排期
    PUT    /{id}/start              开始执行
    PUT    /{id}/pause              暂停
    PUT    /{id}/cancel             取消

  Assignments (1):
    POST   /{id}/assignments        创建分配
    GET    /{id}/assignments        查询分配列表

  Execution (2):
    POST   /{id}/execute            记录单条执行
    POST   /{id}/batch-execute      批量执行

  Effects (4):
    GET    /{id}/effect             任务效果
    GET    /{id}/effect/by-store    门店维度效果
    GET    /{id}/effect/by-employee 员工维度效果
    GET    /{id}/effect/coupons     优惠券效果

  Leaderboard (1):
    GET    /{id}/leaderboard        执行排行榜
"""

import uuid
from datetime import datetime
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Header
from pydantic import BaseModel
from services.marketing_task_service import MarketingTaskError, MarketingTaskService

from shared.ontology.src.database import async_session_factory

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/growth/marketing-tasks", tags=["marketing-tasks"])

_svc = MarketingTaskService()


# ---------------------------------------------------------------------------
# 统一响应
# ---------------------------------------------------------------------------


def ok_response(data: Any) -> dict:
    return {"ok": True, "data": data}


def error_response(msg: str, code: str = "ERROR") -> dict:
    return {"ok": False, "error": {"code": code, "message": msg}}


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class CreateTaskRequest(BaseModel):
    task_name: str
    channel: str = "private_chat"
    content: dict
    created_by: str
    description: Optional[str] = None
    task_type: str = "one_time"
    audience_pack_id: Optional[str] = None
    audience_filter: Optional[dict] = None
    schedule_at: Optional[datetime] = None
    schedule_end_at: Optional[datetime] = None
    recurrence_rule: Optional[dict] = None
    target_store_ids: Optional[list] = None
    target_employee_ids: Optional[list] = None
    priority: str = "normal"


class UpdateTaskRequest(BaseModel):
    task_name: Optional[str] = None
    description: Optional[str] = None
    channel: Optional[str] = None
    content: Optional[dict] = None
    audience_pack_id: Optional[str] = None
    audience_filter: Optional[dict] = None
    schedule_at: Optional[datetime] = None
    schedule_end_at: Optional[datetime] = None
    recurrence_rule: Optional[dict] = None
    target_store_ids: Optional[list] = None
    target_employee_ids: Optional[list] = None
    priority: Optional[str] = None


class ScheduleRequest(BaseModel):
    approved_by: Optional[str] = None


class CreateAssignmentsRequest(BaseModel):
    store_employee_map: list[dict]


class ExecuteRequest(BaseModel):
    store_id: Optional[str] = None
    employee_id: Optional[str] = None
    customer_id: Optional[str] = None
    wecom_external_userid: Optional[str] = None
    group_chat_id: Optional[str] = None
    channel: Optional[str] = None
    send_status: str = "sent"
    coupon_instance_id: Optional[str] = None
    failure_reason: Optional[str] = None


class BatchExecuteRequest(BaseModel):
    executions: list[dict]


# ---------------------------------------------------------------------------
# CRUD 端点
# ---------------------------------------------------------------------------


@router.post("")
async def create_task(
    req: CreateTaskRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """创建营销任务"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            result = await _svc.create_task(
                tenant_id=uuid.UUID(x_tenant_id),
                task_name=req.task_name,
                channel=req.channel,
                content=req.content,
                created_by=uuid.UUID(req.created_by),
                db=db,
                description=req.description,
                task_type=req.task_type,
                audience_pack_id=uuid.UUID(req.audience_pack_id) if req.audience_pack_id else None,
                audience_filter=req.audience_filter,
                schedule_at=req.schedule_at,
                schedule_end_at=req.schedule_end_at,
                recurrence_rule=req.recurrence_rule,
                target_store_ids=req.target_store_ids,
                target_employee_ids=req.target_employee_ids,
                priority=req.priority,
            )
            await db.commit()
            return ok_response(result)
        except MarketingTaskError as exc:
            return error_response(exc.message, exc.code)


@router.get("/calendar")
async def get_calendar(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    year: int = 2026,
    month: int = 1,
    store_id: Optional[str] = None,
) -> dict:
    """月视图日历"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        result = await _svc.get_calendar(
            tenant_id=uuid.UUID(x_tenant_id),
            year=year,
            month=month,
            db=db,
            store_id=uuid.UUID(store_id) if store_id else None,
        )
        return ok_response(result)


@router.get("")
async def list_tasks(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    status: Optional[str] = None,
    channel: Optional[str] = None,
    task_type: Optional[str] = None,
    priority: Optional[str] = None,
    page: int = 1,
    size: int = 20,
) -> dict:
    """任务列表"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        result = await _svc.list_tasks(
            tenant_id=uuid.UUID(x_tenant_id),
            db=db,
            status=status,
            channel=channel,
            task_type=task_type,
            priority=priority,
            page=page,
            size=size,
        )
        return ok_response(result)


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """任务详情"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            result = await _svc.get_task(uuid.UUID(x_tenant_id), uuid.UUID(task_id), db)
            return ok_response(result)
        except MarketingTaskError as exc:
            return error_response(exc.message, exc.code)


@router.put("/{task_id}")
async def update_task(
    task_id: str,
    req: UpdateTaskRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """更新任务"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            updates = req.model_dump(exclude_none=True)
            result = await _svc.update_task(uuid.UUID(x_tenant_id), uuid.UUID(task_id), updates, db)
            await db.commit()
            return ok_response(result)
        except MarketingTaskError as exc:
            return error_response(exc.message, exc.code)


@router.delete("/{task_id}")
async def delete_task(
    task_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """删除任务"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            result = await _svc.delete_task(uuid.UUID(x_tenant_id), uuid.UUID(task_id), db)
            await db.commit()
            return ok_response(result)
        except MarketingTaskError as exc:
            return error_response(exc.message, exc.code)


# ---------------------------------------------------------------------------
# Lifecycle 端点
# ---------------------------------------------------------------------------


@router.put("/{task_id}/schedule")
async def schedule_task(
    task_id: str,
    req: ScheduleRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """排期任务"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            result = await _svc.schedule_task(
                uuid.UUID(x_tenant_id),
                uuid.UUID(task_id),
                db,
                approved_by=uuid.UUID(req.approved_by) if req.approved_by else None,
            )
            await db.commit()
            return ok_response(result)
        except MarketingTaskError as exc:
            return error_response(exc.message, exc.code)


@router.put("/{task_id}/start")
async def start_task(
    task_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """开始执行"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            result = await _svc.start_task(uuid.UUID(x_tenant_id), uuid.UUID(task_id), db)
            await db.commit()
            return ok_response(result)
        except MarketingTaskError as exc:
            return error_response(exc.message, exc.code)


@router.put("/{task_id}/pause")
async def pause_task(
    task_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """暂停任务"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            result = await _svc.pause_task(uuid.UUID(x_tenant_id), uuid.UUID(task_id), db)
            await db.commit()
            return ok_response(result)
        except MarketingTaskError as exc:
            return error_response(exc.message, exc.code)


@router.put("/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """取消任务"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            result = await _svc.cancel_task(uuid.UUID(x_tenant_id), uuid.UUID(task_id), db)
            await db.commit()
            return ok_response(result)
        except MarketingTaskError as exc:
            return error_response(exc.message, exc.code)


# ---------------------------------------------------------------------------
# Assignments 端点
# ---------------------------------------------------------------------------


@router.post("/{task_id}/assignments")
async def create_assignments(
    task_id: str,
    req: CreateAssignmentsRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """创建任务分配"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            result = await _svc.create_assignments(
                uuid.UUID(x_tenant_id),
                uuid.UUID(task_id),
                req.store_employee_map,
                db,
            )
            await db.commit()
            return ok_response(result)
        except MarketingTaskError as exc:
            return error_response(exc.message, exc.code)


@router.get("/{task_id}/assignments")
async def list_assignments(
    task_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    status: Optional[str] = None,
) -> dict:
    """查询分配列表"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        result = await _svc.list_assignments(
            uuid.UUID(x_tenant_id),
            uuid.UUID(task_id),
            db,
            status=status,
        )
        return ok_response(result)


# ---------------------------------------------------------------------------
# Execution 端点
# ---------------------------------------------------------------------------


@router.post("/{task_id}/execute")
async def execute_task(
    task_id: str,
    req: ExecuteRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """记录单条执行"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            result = await _svc.record_execution(
                tenant_id=uuid.UUID(x_tenant_id),
                task_id=uuid.UUID(task_id),
                db=db,
                store_id=uuid.UUID(req.store_id) if req.store_id else None,
                employee_id=uuid.UUID(req.employee_id) if req.employee_id else None,
                customer_id=uuid.UUID(req.customer_id) if req.customer_id else None,
                wecom_external_userid=req.wecom_external_userid,
                group_chat_id=req.group_chat_id,
                channel=req.channel,
                send_status=req.send_status,
                coupon_instance_id=uuid.UUID(req.coupon_instance_id) if req.coupon_instance_id else None,
                failure_reason=req.failure_reason,
            )
            await db.commit()
            return ok_response(result)
        except MarketingTaskError as exc:
            return error_response(exc.message, exc.code)


@router.post("/{task_id}/batch-execute")
async def batch_execute(
    task_id: str,
    req: BatchExecuteRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """批量执行"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        result = await _svc.batch_execute(
            uuid.UUID(x_tenant_id),
            uuid.UUID(task_id),
            req.executions,
            db,
        )
        await db.commit()
        return ok_response(result)


# ---------------------------------------------------------------------------
# Effects 端点
# ---------------------------------------------------------------------------


@router.get("/{task_id}/effect")
async def get_task_effect(
    task_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """任务效果"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        result = await _svc.get_task_effect(uuid.UUID(x_tenant_id), uuid.UUID(task_id), db)
        return ok_response(result)


@router.get("/{task_id}/effect/by-store")
async def get_store_effect(
    task_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """门店维度效果"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        result = await _svc.get_store_effect(uuid.UUID(x_tenant_id), uuid.UUID(task_id), db)
        return ok_response(result)


@router.get("/{task_id}/effect/by-employee")
async def get_employee_effect(
    task_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """员工维度效果"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        result = await _svc.get_employee_effect(uuid.UUID(x_tenant_id), uuid.UUID(task_id), db)
        return ok_response(result)


@router.get("/{task_id}/effect/coupons")
async def get_coupon_effect(
    task_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """优惠券效果"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        result = await _svc.get_coupon_effect(uuid.UUID(x_tenant_id), uuid.UUID(task_id), db)
        return ok_response(result)


# ---------------------------------------------------------------------------
# Leaderboard 端点
# ---------------------------------------------------------------------------


@router.get("/{task_id}/leaderboard")
async def get_leaderboard(
    task_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    dimension: str = "store",
    limit: int = 20,
) -> dict:
    """执行排行榜"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            result = await _svc.get_execution_leaderboard(
                uuid.UUID(x_tenant_id),
                uuid.UUID(task_id),
                dimension,
                db,
                limit=limit,
            )
            return ok_response(result)
        except MarketingTaskError as exc:
            return error_response(exc.message, exc.code)
