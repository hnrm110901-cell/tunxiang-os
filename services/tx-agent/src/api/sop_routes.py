"""SOP时间轴引擎 — Phase S1 全部25个API端点

端点分组：
- 模板管理（6端点）
- 门店配置（3端点）
- 任务实例（6端点）
- 概况（2端点）
- 纠正动作（6端点）
- 调度（2端点）
"""
from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Path
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.sop_scheduler_service import SOPSchedulerService
from ..services.sop_task_service import SOPTaskService
from ..services.corrective_action_service import CorrectiveActionService

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/agent/sop", tags=["sop"])


# ── 依赖 ──

async def _get_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> AsyncSession:
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ══════════════════════════════════════════════
# Pydantic 请求模型
# ══════════════════════════════════════════════

class CreateTemplateRequest(BaseModel):
    template_name: str = Field(..., min_length=1, max_length=100)
    store_format: str = Field(..., pattern="^(full_service|qsr|hotpot|bakery)$")
    description: str | None = None
    is_default: bool = False


class InitDefaultRequest(BaseModel):
    store_format: str = Field(default="full_service", pattern="^(full_service|qsr|hotpot|bakery)$")


class AddTimeSlotRequest(BaseModel):
    slot_code: str
    slot_name: str
    start_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    sort_order: int = Field(..., ge=0)


class AddTaskRequest(BaseModel):
    slot_id: str
    task_code: str
    task_name: str
    task_type: str = Field(..., pattern="^(checklist|inspection|report|action)$")
    target_role: str = Field(..., pattern="^(store_manager|kitchen_lead|floor_lead|cashier|all)$")
    priority: str = Field(default="normal", pattern="^(critical|high|normal|low)$")
    duration_min: int | None = None
    instructions: str | None = None
    checklist_items: list[dict] | None = None
    condition_logic: dict | None = None
    auto_complete: dict | None = None
    sort_order: int = 0


class BindStoreRequest(BaseModel):
    template_id: str
    timezone: str = "Asia/Shanghai"
    custom_overrides: dict | None = None


class StartTaskRequest(BaseModel):
    assignee_id: str


class CompleteTaskRequest(BaseModel):
    result: dict = Field(default_factory=dict)
    compliance: str = Field(default="pass", pattern="^(pass|fail|warning)$")


class SkipTaskRequest(BaseModel):
    reason: str = Field(..., min_length=1)


class ResolveActionRequest(BaseModel):
    resolution: dict


class VerifyActionRequest(BaseModel):
    verified_by: str


class EscalateActionRequest(BaseModel):
    escalated_to: str


class TickRequest(BaseModel):
    store_id: str


class SOPEventRequest(BaseModel):
    store_id: str
    event_type: str
    payload: dict = Field(default_factory=dict)


class GenerateDailyRequest(BaseModel):
    target_date: str | None = None


# ══════════════════════════════════════════════
# 模板管理（6端点）
# ══════════════════════════════════════════════

@router.post("/templates")
async def create_template(
    req: CreateTemplateRequest,
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """创建SOP模板"""
    svc = SOPTaskService(db)
    result = await svc.create_template(
        tenant_id=x_tenant_id,
        template_name=req.template_name,
        store_format=req.store_format,
        description=req.description,
        is_default=req.is_default,
    )
    await db.commit()
    return {"ok": True, "data": result}


@router.get("/templates")
async def list_templates(
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    store_format: str | None = Query(None),
):
    """列出所有SOP模板"""
    svc = SOPTaskService(db)
    result = await svc.list_templates(
        tenant_id=x_tenant_id,
        store_format=store_format,
    )
    return {"ok": True, "data": result}


@router.get("/templates/{template_id}")
async def get_template(
    template_id: str = Path(...),
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """获取模板详情（含时段+任务）"""
    svc = SOPTaskService(db)
    result = await svc.get_template(
        tenant_id=x_tenant_id,
        template_id=template_id,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    return {"ok": True, "data": result}


@router.post("/templates/init-default")
async def init_default_template(
    req: InitDefaultRequest,
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """初始化默认SOP模板（含时段+任务）"""
    svc = SOPTaskService(db)
    result = await svc.init_default_template(
        tenant_id=x_tenant_id,
        store_format=req.store_format,
    )
    await db.commit()
    return {"ok": True, "data": result}


@router.post("/templates/{template_id}/time-slots")
async def add_time_slot(
    req: AddTimeSlotRequest,
    template_id: str = Path(...),
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """向模板添加时段"""
    svc = SOPTaskService(db)
    result = await svc.add_time_slot(
        tenant_id=x_tenant_id,
        template_id=template_id,
        slot_code=req.slot_code,
        slot_name=req.slot_name,
        start_time=req.start_time,
        end_time=req.end_time,
        sort_order=req.sort_order,
    )
    await db.commit()
    return {"ok": True, "data": result}


@router.post("/templates/{template_id}/tasks")
async def add_task(
    req: AddTaskRequest,
    template_id: str = Path(...),
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """向模板添加任务定义"""
    svc = SOPTaskService(db)
    result = await svc.add_task(
        tenant_id=x_tenant_id,
        template_id=template_id,
        slot_id=req.slot_id,
        task_code=req.task_code,
        task_name=req.task_name,
        task_type=req.task_type,
        target_role=req.target_role,
        priority=req.priority,
        duration_min=req.duration_min,
        instructions=req.instructions,
        checklist_items=req.checklist_items,
        condition_logic=req.condition_logic,
        auto_complete=req.auto_complete,
        sort_order=req.sort_order,
    )
    await db.commit()
    return {"ok": True, "data": result}


# ══════════════════════════════════════════════
# 门店配置（3端点）
# ══════════════════════════════════════════════

@router.post("/stores/{store_id}/bind")
async def bind_store(
    req: BindStoreRequest,
    store_id: str = Path(...),
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """绑定门店到SOP模板"""
    svc = SOPSchedulerService(db)
    try:
        result = await svc.bind_store_template(
            tenant_id=x_tenant_id,
            store_id=store_id,
            template_id=req.template_id,
            timezone=req.timezone,
            custom_overrides=req.custom_overrides,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    await db.commit()
    return {"ok": True, "data": result}


@router.get("/stores/{store_id}/config")
async def get_store_config(
    store_id: str = Path(...),
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """获取门店SOP配置"""
    svc = SOPSchedulerService(db)
    result = await svc.get_store_sop_config(
        tenant_id=x_tenant_id,
        store_id=store_id,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="门店未绑定SOP")
    return {"ok": True, "data": result}


@router.get("/stores/{store_id}/current-slot")
async def get_current_slot(
    store_id: str = Path(...),
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """获取门店当前时段"""
    svc = SOPSchedulerService(db)
    now = datetime.now(timezone.utc)
    # 门店时区偏移：默认 Asia/Shanghai = UTC+8
    store_tz_offset = timedelta(hours=8)
    local_now = now + store_tz_offset
    current_time = local_now.time()

    result = await svc.get_current_slot(
        tenant_id=x_tenant_id,
        store_id=store_id,
        current_time=current_time,
    )
    if result is None:
        return {"ok": True, "data": {"current_slot": None, "message": "当前无活跃时段"}}
    return {"ok": True, "data": result}


# ══════════════════════════════════════════════
# 任务实例（6端点）
# ══════════════════════════════════════════════

@router.post("/stores/{store_id}/generate-daily")
async def generate_daily(
    req: GenerateDailyRequest,
    store_id: str = Path(...),
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """生成每日任务实例"""
    svc = SOPSchedulerService(db)
    if req.target_date is not None:
        target = date_type.fromisoformat(req.target_date)
    else:
        target = datetime.now(timezone.utc).date()

    count = await svc.generate_daily_instances(
        tenant_id=x_tenant_id,
        store_id=store_id,
        target_date=target,
    )
    await db.commit()
    return {"ok": True, "data": {"generated": count, "date": target.isoformat()}}


@router.get("/stores/{store_id}/tasks")
async def list_tasks(
    store_id: str = Path(...),
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    date: str | None = Query(None, description="YYYY-MM-DD"),
    slot_code: str | None = Query(None),
    status: str | None = Query(None),
    role: str | None = Query(None),
):
    """分页列出门店任务实例"""
    svc = SOPTaskService(db)
    result = await svc.list_task_instances(
        tenant_id=x_tenant_id,
        store_id=store_id,
        page=page,
        size=size,
        target_date=date,
        slot_code=slot_code,
        status=status,
        role=role,
    )
    return {"ok": True, "data": result}


@router.get("/tasks/{instance_id}")
async def get_task_instance(
    instance_id: str = Path(...),
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """获取任务实例详情"""
    svc = SOPTaskService(db)
    result = await svc.get_task_instance(
        tenant_id=x_tenant_id,
        instance_id=instance_id,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="任务实例不存在")
    return {"ok": True, "data": result}


@router.post("/tasks/{instance_id}/start")
async def start_task(
    req: StartTaskRequest,
    instance_id: str = Path(...),
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """开始任务"""
    svc = SOPTaskService(db)
    try:
        result = await svc.start_task(
            tenant_id=x_tenant_id,
            instance_id=instance_id,
            assignee_id=req.assignee_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    await db.commit()
    return {"ok": True, "data": result}


@router.post("/tasks/{instance_id}/complete")
async def complete_task(
    req: CompleteTaskRequest,
    instance_id: str = Path(...),
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """完成任务"""
    svc = SOPTaskService(db)
    try:
        result = await svc.complete_task(
            tenant_id=x_tenant_id,
            instance_id=instance_id,
            result_data=req.result,
            compliance=req.compliance,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    await db.commit()
    return {"ok": True, "data": result}


@router.post("/tasks/{instance_id}/skip")
async def skip_task(
    req: SkipTaskRequest,
    instance_id: str = Path(...),
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """跳过任务"""
    svc = SOPTaskService(db)
    try:
        result = await svc.skip_task(
            tenant_id=x_tenant_id,
            instance_id=instance_id,
            reason=req.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    await db.commit()
    return {"ok": True, "data": result}


# ══════════════════════════════════════════════
# 概况（2端点）
# ══════════════════════════════════════════════

@router.get("/stores/{store_id}/daily-summary")
async def daily_summary(
    store_id: str = Path(...),
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    date: str | None = Query(None, description="YYYY-MM-DD"),
):
    """获取每日SOP执行概况"""
    svc = SOPSchedulerService(db)
    if date is not None:
        target = date_type.fromisoformat(date)
    else:
        target = datetime.now(timezone.utc).date()

    result = await svc.get_daily_summary(
        tenant_id=x_tenant_id,
        store_id=store_id,
        target_date=target,
    )
    return {"ok": True, "data": result}


@router.get("/stores/{store_id}/slot-tasks")
async def slot_tasks(
    store_id: str = Path(...),
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    date: str | None = Query(None, description="YYYY-MM-DD"),
    slot_code: str = Query(...),
    role: str | None = Query(None),
):
    """获取指定时段的任务列表"""
    svc = SOPSchedulerService(db)
    if date is not None:
        target = date_type.fromisoformat(date)
    else:
        target = datetime.now(timezone.utc).date()

    result = await svc.get_slot_tasks(
        tenant_id=x_tenant_id,
        store_id=store_id,
        target_date=target,
        slot_code=slot_code,
        role=role,
    )
    return {"ok": True, "data": result}


# ══════════════════════════════════════════════
# 纠正动作（6端点）
# ══════════════════════════════════════════════

@router.get("/stores/{store_id}/corrective-actions")
async def list_actions(
    store_id: str = Path(...),
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    severity: str | None = Query(None),
):
    """分页列出门店纠正动作"""
    svc = CorrectiveActionService(db)
    result = await svc.list_actions(
        tenant_id=x_tenant_id,
        store_id=store_id,
        page=page,
        size=size,
        status=status,
        severity=severity,
    )
    return {"ok": True, "data": result}


@router.get("/corrective-actions/{action_id}")
async def get_action(
    action_id: str = Path(...),
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """获取纠正动作详情"""
    svc = CorrectiveActionService(db)
    result = await svc.get_action(
        tenant_id=x_tenant_id,
        action_id=action_id,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="纠正动作不存在")
    return {"ok": True, "data": result}


@router.post("/corrective-actions/{action_id}/resolve")
async def resolve_action(
    req: ResolveActionRequest,
    action_id: str = Path(...),
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """解决纠正动作"""
    svc = CorrectiveActionService(db)
    try:
        result = await svc.resolve(
            tenant_id=x_tenant_id,
            action_id=action_id,
            resolution=req.resolution,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    await db.commit()
    return {"ok": True, "data": result}


@router.post("/corrective-actions/{action_id}/verify")
async def verify_action(
    req: VerifyActionRequest,
    action_id: str = Path(...),
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """验证纠正动作"""
    svc = CorrectiveActionService(db)
    try:
        result = await svc.verify(
            tenant_id=x_tenant_id,
            action_id=action_id,
            verified_by=req.verified_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    await db.commit()
    return {"ok": True, "data": result}


@router.post("/corrective-actions/{action_id}/escalate")
async def escalate_action(
    req: EscalateActionRequest,
    action_id: str = Path(...),
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """升级纠正动作"""
    svc = CorrectiveActionService(db)
    try:
        result = await svc.escalate(
            tenant_id=x_tenant_id,
            action_id=action_id,
            escalated_to=req.escalated_to,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    await db.commit()
    return {"ok": True, "data": result}


@router.get("/stores/{store_id}/corrective-summary")
async def action_summary(
    store_id: str = Path(...),
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """纠正动作统计概况"""
    svc = CorrectiveActionService(db)
    result = await svc.get_summary(
        tenant_id=x_tenant_id,
        store_id=store_id,
    )
    return {"ok": True, "data": result}


# ══════════════════════════════════════════════
# 调度（2端点 — 内部/手动）
# ══════════════════════════════════════════════

@router.post("/tick")
async def manual_tick(
    req: TickRequest,
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """手动触发一次SOP调度（tick）"""
    svc = SOPSchedulerService(db)
    result = await svc.tick(
        tenant_id=x_tenant_id,
        store_id=req.store_id,
    )
    await db.commit()
    return {"ok": True, "data": result}


@router.post("/event")
async def handle_event(
    req: SOPEventRequest,
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """处理业务事件（触发SOP任务）"""
    svc = SOPSchedulerService(db)
    # 将store_id注入payload
    payload = {**req.payload, "store_id": req.store_id}
    triggered = await svc.on_business_event(
        tenant_id=x_tenant_id,
        event_type=req.event_type,
        payload=payload,
    )
    await db.commit()
    return {"ok": True, "data": {"triggered_task_ids": triggered}}
