"""销售CRM API — 目标/线索/任务/拜访/画像/仪表盘

23个端点：
  Targets (5):
    POST   /targets                    创建销售目标
    GET    /targets                    目标列表
    PUT    /targets/{id}               更新目标设定值
    PUT    /targets/{id}/actuals       更新实际值
    GET    /targets/ranking            达成率排名

  Leads (8):
    POST   /leads                      创建线索
    GET    /leads                      线索列表（分页+筛选）
    GET    /leads/{id}                 线索详情
    PUT    /leads/{id}/stage           推进阶段
    PUT    /leads/{id}/assign          分配线索
    GET    /leads/funnel               漏斗统计
    GET    /leads/conversion           转化率统计
    GET    /leads/lost-reasons         流失原因

  Tasks (5):
    POST   /tasks                      创建任务
    GET    /tasks                      任务列表
    GET    /tasks/my                   我的任务
    PUT    /tasks/{id}/complete        完成任务
    GET    /tasks/stats                任务统计

  Visits (3):
    POST   /visits                     创建拜访记录
    GET    /visits                     拜访记录列表
    GET    /visits/customer/{cid}      客户拜访记录

  Profile (1):
    GET    /profiles/ranking           画像完整度排名

  Dashboard (1):
    GET    /dashboard                  销售仪表盘
"""

import uuid
from datetime import date, datetime
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from services.sales_crm_service import SalesCRMError, SalesCRMService

from shared.ontology.src.database import async_session_factory

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/growth/sales", tags=["sales-crm"])

_svc = SalesCRMService()


# ---------------------------------------------------------------------------
# 统一响应
# ---------------------------------------------------------------------------


def ok_response(data: Any) -> dict:
    return {"ok": True, "data": data}


def error_response(msg: str, code: str = "ERROR") -> dict:
    return {"ok": False, "error": {"code": code, "message": msg}}


async def _get_db(tenant_id: str):
    """创建带 RLS tenant_id 的 DB session"""
    from sqlalchemy import text
    db = async_session_factory()
    session = await db.__aenter__()
    await session.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})
    return session, db


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class CreateTargetRequest(BaseModel):
    store_id: Optional[str] = None
    brand_id: Optional[str] = None
    employee_id: Optional[str] = None
    target_type: str  # annual/monthly/weekly/daily
    year: int
    month: Optional[int] = None
    target_revenue_fen: int = 0
    target_orders: int = 0
    target_new_customers: int = 0
    target_reservations: int = 0


class UpdateTargetRequest(BaseModel):
    target_revenue_fen: Optional[int] = None
    target_orders: Optional[int] = None
    target_new_customers: Optional[int] = None
    target_reservations: Optional[int] = None


class UpdateActualsRequest(BaseModel):
    actual_revenue_fen: Optional[int] = None
    actual_orders: Optional[int] = None
    actual_new_customers: Optional[int] = None
    actual_reservations: Optional[int] = None


class CreateLeadRequest(BaseModel):
    store_id: str
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    customer_id: Optional[str] = None
    lead_source: str = "other"
    lead_type: str = "dining"
    expected_revenue_fen: Optional[int] = None
    expected_date: Optional[date] = None
    assigned_to: Optional[str] = None
    priority: str = "medium"
    notes: Optional[str] = None


class AdvanceStageRequest(BaseModel):
    new_stage: str
    lost_reason: Optional[str] = None
    won_order_id: Optional[str] = None


class AssignLeadRequest(BaseModel):
    assigned_to: str


class CreateTaskRequest(BaseModel):
    employee_id: str
    title: str
    task_type: str
    due_at: datetime
    store_id: Optional[str] = None
    related_lead_id: Optional[str] = None
    related_customer_id: Optional[str] = None
    description: Optional[str] = None
    priority: str = "medium"
    reminder_at: Optional[datetime] = None


class CompleteTaskRequest(BaseModel):
    result: Optional[str] = None


class CreateVisitRequest(BaseModel):
    employee_id: str
    customer_id: str
    visit_type: str  # phone/wechat/in_person/sms
    store_id: Optional[str] = None
    purpose: Optional[str] = None
    summary: Optional[str] = None
    customer_satisfaction: Optional[int] = None
    next_action: Optional[str] = None
    next_action_date: Optional[date] = None


# ---------------------------------------------------------------------------
# Targets 端点
# ---------------------------------------------------------------------------


@router.post("/targets")
async def create_target(
    req: CreateTargetRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """创建销售目标"""
    async with async_session_factory() as db:
        from sqlalchemy import text
        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            result = await _svc.create_target(
                tenant_id=uuid.UUID(x_tenant_id),
                target_type=req.target_type,
                year=req.year,
                store_id=uuid.UUID(req.store_id) if req.store_id else None,
                brand_id=uuid.UUID(req.brand_id) if req.brand_id else None,
                employee_id=uuid.UUID(req.employee_id) if req.employee_id else None,
                month=req.month,
                target_revenue_fen=req.target_revenue_fen,
                target_orders=req.target_orders,
                target_new_customers=req.target_new_customers,
                target_reservations=req.target_reservations,
                db=db,
            )
            await db.commit()
            return ok_response(result)
        except SalesCRMError as exc:
            return error_response(exc.message, exc.code)


@router.get("/targets")
async def list_targets(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    store_id: Optional[str] = None,
    year: Optional[int] = None,
    target_type: Optional[str] = None,
) -> dict:
    """查询销售目标列表"""
    async with async_session_factory() as db:
        from sqlalchemy import text
        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        result = await _svc.list_targets(
            tenant_id=uuid.UUID(x_tenant_id),
            db=db,
            store_id=uuid.UUID(store_id) if store_id else None,
            year=year,
            target_type=target_type,
        )
        return ok_response(result)


@router.put("/targets/{target_id}")
async def update_target(
    target_id: str,
    req: UpdateTargetRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """更新销售目标设定值"""
    async with async_session_factory() as db:
        from sqlalchemy import text
        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            updates = req.model_dump(exclude_none=True)
            result = await _svc.update_target(uuid.UUID(x_tenant_id), uuid.UUID(target_id), updates, db)
            await db.commit()
            return ok_response(result)
        except SalesCRMError as exc:
            return error_response(exc.message, exc.code)


@router.put("/targets/{target_id}/actuals")
async def update_actuals(
    target_id: str,
    req: UpdateActualsRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """更新实际值（自动计算达成率）"""
    async with async_session_factory() as db:
        from sqlalchemy import text
        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            result = await _svc.update_actuals(
                tenant_id=uuid.UUID(x_tenant_id),
                target_id=uuid.UUID(target_id),
                actual_revenue_fen=req.actual_revenue_fen,
                actual_orders=req.actual_orders,
                actual_new_customers=req.actual_new_customers,
                actual_reservations=req.actual_reservations,
                db=db,
            )
            await db.commit()
            return ok_response(result)
        except SalesCRMError as exc:
            return error_response(exc.message, exc.code)


@router.get("/targets/ranking")
async def get_achievement_ranking(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    year: int = 2026,
    month: Optional[int] = None,
    store_id: Optional[str] = None,
    limit: int = 20,
) -> dict:
    """获取达成率排名"""
    async with async_session_factory() as db:
        from sqlalchemy import text
        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        result = await _svc.get_achievement_ranking(
            tenant_id=uuid.UUID(x_tenant_id),
            db=db,
            year=year,
            month=month,
            store_id=uuid.UUID(store_id) if store_id else None,
            limit=limit,
        )
        return ok_response(result)


# ---------------------------------------------------------------------------
# Leads 端点
# ---------------------------------------------------------------------------


@router.post("/leads")
async def create_lead(
    req: CreateLeadRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """创建销售线索"""
    async with async_session_factory() as db:
        from sqlalchemy import text
        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            result = await _svc.create_lead(
                tenant_id=uuid.UUID(x_tenant_id),
                store_id=uuid.UUID(req.store_id),
                customer_name=req.customer_name,
                customer_phone=req.customer_phone,
                customer_id=uuid.UUID(req.customer_id) if req.customer_id else None,
                lead_source=req.lead_source,
                lead_type=req.lead_type,
                expected_revenue_fen=req.expected_revenue_fen,
                expected_date=req.expected_date,
                assigned_to=uuid.UUID(req.assigned_to) if req.assigned_to else None,
                priority=req.priority,
                notes=req.notes,
                db=db,
            )
            await db.commit()
            return ok_response(result)
        except SalesCRMError as exc:
            return error_response(exc.message, exc.code)


@router.get("/leads")
async def list_leads(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    store_id: Optional[str] = None,
    stage: Optional[str] = None,
    assigned_to: Optional[str] = None,
    lead_source: Optional[str] = None,
    priority: Optional[str] = None,
    page: int = 1,
    size: int = 20,
) -> dict:
    """线索列表（分页+筛选）"""
    async with async_session_factory() as db:
        from sqlalchemy import text
        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        result = await _svc.list_leads(
            tenant_id=uuid.UUID(x_tenant_id),
            db=db,
            store_id=uuid.UUID(store_id) if store_id else None,
            stage=stage,
            assigned_to=uuid.UUID(assigned_to) if assigned_to else None,
            lead_source=lead_source,
            priority=priority,
            page=page,
            size=size,
        )
        return ok_response(result)


@router.get("/leads/funnel")
async def get_funnel(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    store_id: Optional[str] = None,
) -> dict:
    """漏斗统计"""
    async with async_session_factory() as db:
        from sqlalchemy import text
        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        result = await _svc.get_funnel(
            tenant_id=uuid.UUID(x_tenant_id),
            db=db,
            store_id=uuid.UUID(store_id) if store_id else None,
        )
        return ok_response(result)


@router.get("/leads/conversion")
async def get_conversion_stats(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    store_id: Optional[str] = None,
    days: int = 30,
) -> dict:
    """转化率统计"""
    async with async_session_factory() as db:
        from sqlalchemy import text
        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        result = await _svc.get_conversion_stats(
            tenant_id=uuid.UUID(x_tenant_id),
            db=db,
            store_id=uuid.UUID(store_id) if store_id else None,
            days=days,
        )
        return ok_response(result)


@router.get("/leads/lost-reasons")
async def get_lost_reasons(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    store_id: Optional[str] = None,
    days: int = 90,
) -> dict:
    """流失原因统计"""
    async with async_session_factory() as db:
        from sqlalchemy import text
        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        result = await _svc.get_lost_reasons(
            tenant_id=uuid.UUID(x_tenant_id),
            db=db,
            store_id=uuid.UUID(store_id) if store_id else None,
            days=days,
        )
        return ok_response(result)


@router.get("/leads/{lead_id}")
async def get_lead(
    lead_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """线索详情"""
    async with async_session_factory() as db:
        from sqlalchemy import text
        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            result = await _svc.get_lead(uuid.UUID(x_tenant_id), uuid.UUID(lead_id), db)
            return ok_response(result)
        except SalesCRMError as exc:
            return error_response(exc.message, exc.code)


@router.put("/leads/{lead_id}/stage")
async def advance_stage(
    lead_id: str,
    req: AdvanceStageRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """推进线索阶段"""
    async with async_session_factory() as db:
        from sqlalchemy import text
        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            result = await _svc.advance_stage(
                tenant_id=uuid.UUID(x_tenant_id),
                lead_id=uuid.UUID(lead_id),
                new_stage=req.new_stage,
                db=db,
                lost_reason=req.lost_reason,
                won_order_id=uuid.UUID(req.won_order_id) if req.won_order_id else None,
            )
            await db.commit()
            return ok_response(result)
        except SalesCRMError as exc:
            return error_response(exc.message, exc.code)


@router.put("/leads/{lead_id}/assign")
async def assign_lead(
    lead_id: str,
    req: AssignLeadRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """分配线索"""
    async with async_session_factory() as db:
        from sqlalchemy import text
        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            result = await _svc.assign_lead(
                uuid.UUID(x_tenant_id), uuid.UUID(lead_id), uuid.UUID(req.assigned_to), db,
            )
            await db.commit()
            return ok_response(result)
        except SalesCRMError as exc:
            return error_response(exc.message, exc.code)


# ---------------------------------------------------------------------------
# Tasks 端点
# ---------------------------------------------------------------------------


@router.post("/tasks")
async def create_task(
    req: CreateTaskRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """创建销售任务"""
    async with async_session_factory() as db:
        from sqlalchemy import text
        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            result = await _svc.create_task(
                tenant_id=uuid.UUID(x_tenant_id),
                employee_id=uuid.UUID(req.employee_id),
                title=req.title,
                task_type=req.task_type,
                due_at=req.due_at,
                db=db,
                store_id=uuid.UUID(req.store_id) if req.store_id else None,
                related_lead_id=uuid.UUID(req.related_lead_id) if req.related_lead_id else None,
                related_customer_id=uuid.UUID(req.related_customer_id) if req.related_customer_id else None,
                description=req.description,
                priority=req.priority,
                reminder_at=req.reminder_at,
            )
            await db.commit()
            return ok_response(result)
        except SalesCRMError as exc:
            return error_response(exc.message, exc.code)


@router.get("/tasks")
async def list_tasks(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    store_id: Optional[str] = None,
    employee_id: Optional[str] = None,
    status: Optional[str] = None,
    task_type: Optional[str] = None,
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
            store_id=uuid.UUID(store_id) if store_id else None,
            employee_id=uuid.UUID(employee_id) if employee_id else None,
            status=status,
            task_type=task_type,
            page=page,
            size=size,
        )
        return ok_response(result)


@router.get("/tasks/my")
async def get_my_tasks(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    employee_id: str = "",
    status: Optional[str] = None,
) -> dict:
    """获取我的任务"""
    if not employee_id:
        raise HTTPException(status_code=400, detail="employee_id is required")
    async with async_session_factory() as db:
        from sqlalchemy import text
        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        result = await _svc.get_my_tasks(
            tenant_id=uuid.UUID(x_tenant_id),
            employee_id=uuid.UUID(employee_id),
            db=db,
            status=status,
        )
        return ok_response(result)


@router.put("/tasks/{task_id}/complete")
async def complete_task(
    task_id: str,
    req: CompleteTaskRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """完成任务"""
    async with async_session_factory() as db:
        from sqlalchemy import text
        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            result = await _svc.complete_task(
                uuid.UUID(x_tenant_id), uuid.UUID(task_id), db,
                result_text=req.result,
            )
            await db.commit()
            return ok_response(result)
        except SalesCRMError as exc:
            return error_response(exc.message, exc.code)


@router.get("/tasks/stats")
async def get_task_stats(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    store_id: Optional[str] = None,
    employee_id: Optional[str] = None,
) -> dict:
    """任务统计"""
    async with async_session_factory() as db:
        from sqlalchemy import text
        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        result = await _svc.get_task_stats(
            tenant_id=uuid.UUID(x_tenant_id),
            db=db,
            store_id=uuid.UUID(store_id) if store_id else None,
            employee_id=uuid.UUID(employee_id) if employee_id else None,
        )
        return ok_response(result)


# ---------------------------------------------------------------------------
# Visits 端点
# ---------------------------------------------------------------------------


@router.post("/visits")
async def create_visit(
    req: CreateVisitRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """创建拜访记录"""
    async with async_session_factory() as db:
        from sqlalchemy import text
        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            result = await _svc.create_visit(
                tenant_id=uuid.UUID(x_tenant_id),
                employee_id=uuid.UUID(req.employee_id),
                customer_id=uuid.UUID(req.customer_id),
                visit_type=req.visit_type,
                db=db,
                store_id=uuid.UUID(req.store_id) if req.store_id else None,
                purpose=req.purpose,
                summary=req.summary,
                customer_satisfaction=req.customer_satisfaction,
                next_action=req.next_action,
                next_action_date=req.next_action_date,
            )
            await db.commit()
            return ok_response(result)
        except SalesCRMError as exc:
            return error_response(exc.message, exc.code)


@router.get("/visits")
async def list_visits(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    store_id: Optional[str] = None,
    employee_id: Optional[str] = None,
    page: int = 1,
    size: int = 20,
) -> dict:
    """拜访记录列表"""
    async with async_session_factory() as db:
        from sqlalchemy import text
        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        result = await _svc.list_visits(
            tenant_id=uuid.UUID(x_tenant_id),
            db=db,
            store_id=uuid.UUID(store_id) if store_id else None,
            employee_id=uuid.UUID(employee_id) if employee_id else None,
            page=page,
            size=size,
        )
        return ok_response(result)


@router.get("/visits/customer/{customer_id}")
async def get_customer_visits(
    customer_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    limit: int = 50,
) -> dict:
    """获取指定客户的拜访记录"""
    async with async_session_factory() as db:
        from sqlalchemy import text
        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        result = await _svc.get_customer_visits(
            uuid.UUID(x_tenant_id), uuid.UUID(customer_id), db, limit=limit,
        )
        return ok_response(result)


# ---------------------------------------------------------------------------
# Profile 端点
# ---------------------------------------------------------------------------


@router.get("/profiles/ranking")
async def get_profile_ranking(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    limit: int = 50,
    min_score: Optional[float] = None,
    max_score: Optional[float] = None,
    order: str = "asc",
) -> dict:
    """画像完整度排名"""
    async with async_session_factory() as db:
        from sqlalchemy import text
        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        result = await _svc.get_profile_ranking(
            uuid.UUID(x_tenant_id), db,
            limit=limit, min_score=min_score, max_score=max_score, order=order,
        )
        return ok_response(result)


# ---------------------------------------------------------------------------
# Dashboard 端点
# ---------------------------------------------------------------------------


@router.get("/dashboard")
async def get_sales_dashboard(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    store_id: Optional[str] = None,
) -> dict:
    """销售仪表盘（聚合所有维度）"""
    async with async_session_factory() as db:
        from sqlalchemy import text
        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        result = await _svc.get_sales_dashboard(
            uuid.UUID(x_tenant_id), db,
            store_id=uuid.UUID(store_id) if store_id else None,
        )
        return ok_response(result)
