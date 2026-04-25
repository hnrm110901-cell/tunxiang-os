"""客户触达SOP旅程 — 18个API端点

端点分组:
- 模板管理(6端点): CRUD + 启停 + 预设初始化
- 步骤管理(4端点): 添加/更新/删除/重排序
- 触发与调度(1端点): 手动触发
- 实例管理(5端点): 列表/详情/暂停/恢复/取消
- 统计(1端点): 模板统计
- 预设(1端点): 初始化预设旅程
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.customer_journey_service import CustomerJourneyService

logger = structlog.get_logger(__name__)
router = APIRouter(
    prefix="/api/v1/agent/customer-journey",
    tags=["customer-journey"],
)


# ── 依赖 ──


async def _get_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> AsyncSession:
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ══════════════════════════════════════════════
# Pydantic 请求模型
# ══════════════════════════════════════════════


class CreateTemplateRequest(BaseModel):
    template_name: str = Field(..., min_length=1, max_length=200)
    trigger_type: str = Field(
        ...,
        pattern="^(post_payment|first_payment|birthday|anniversary|dormancy|"
        "stored_value_low|member_joined|group_joined|wecom_added|manual)$",
    )
    description: str | None = None
    trigger_config: dict = Field(default_factory=dict)
    audience_filter: dict = Field(default_factory=dict)
    is_active: bool = True
    priority: int = Field(default=0, ge=0)
    max_concurrent: int = Field(default=1, ge=1)
    created_by: str | None = None


class UpdateTemplateRequest(BaseModel):
    template_name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    trigger_config: dict | None = None
    audience_filter: dict | None = None
    priority: int | None = Field(None, ge=0)
    max_concurrent: int | None = Field(None, ge=1)


class AddStepRequest(BaseModel):
    step_name: str = Field(..., min_length=1, max_length=200)
    channel: str = Field(
        ...,
        pattern="^(wecom_private|wecom_group|sms|push|wechat_template)$",
    )
    step_order: int | None = None
    delay_minutes: int = Field(default=0, ge=0)
    content_template: dict = Field(default_factory=dict)
    condition: dict | None = None
    skip_if_responded: bool = False


class UpdateStepRequest(BaseModel):
    step_name: str | None = Field(None, min_length=1, max_length=200)
    delay_minutes: int | None = Field(None, ge=0)
    channel: str | None = Field(
        None,
        pattern="^(wecom_private|wecom_group|sms|push|wechat_template)$",
    )
    content_template: dict | None = None
    condition: dict | None = None
    skip_if_responded: bool | None = None


class ReorderStepsRequest(BaseModel):
    step_ids: list[str] = Field(..., min_length=1)


class TriggerJourneyRequest(BaseModel):
    trigger_type: str = Field(
        ...,
        pattern="^(post_payment|first_payment|birthday|anniversary|dormancy|"
        "stored_value_low|member_joined|group_joined|wecom_added|manual)$",
    )
    customer_id: str
    store_id: str
    event_data: dict = Field(default_factory=dict)


class InitPresetsRequest(BaseModel):
    created_by: str | None = None


# ══════════════════════════════════════════════
# 模板管理(6端点)
# ══════════════════════════════════════════════


@router.post("/templates")
async def create_template(
    req: CreateTemplateRequest,
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """创建旅程模板"""
    svc = CustomerJourneyService(db)
    result = await svc.create_template(
        tenant_id=x_tenant_id,
        template_name=req.template_name,
        trigger_type=req.trigger_type,
        description=req.description,
        trigger_config=req.trigger_config,
        audience_filter=req.audience_filter,
        is_active=req.is_active,
        priority=req.priority,
        max_concurrent=req.max_concurrent,
        created_by=req.created_by,
    )
    await db.commit()
    return {"ok": True, "data": result}


@router.get("/templates")
async def list_templates(
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    trigger_type: str | None = Query(None),
    is_active: bool | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    """模板列表(支持trigger_type/is_active过滤)"""
    svc = CustomerJourneyService(db)
    result = await svc.list_templates(
        tenant_id=x_tenant_id,
        trigger_type=trigger_type,
        is_active=is_active,
        page=page,
        size=size,
    )
    return {"ok": True, "data": result}


@router.get("/templates/{template_id}")
async def get_template(
    template_id: str = Path(...),
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """模板详情(含步骤列表)"""
    svc = CustomerJourneyService(db)
    result = await svc.get_template(
        tenant_id=x_tenant_id,
        template_id=template_id,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="旅程模板不存在")
    return {"ok": True, "data": result}


@router.put("/templates/{template_id}")
async def update_template(
    req: UpdateTemplateRequest,
    template_id: str = Path(...),
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """更新旅程模板"""
    svc = CustomerJourneyService(db)
    try:
        result = await svc.update_template(
            tenant_id=x_tenant_id,
            template_id=template_id,
            template_name=req.template_name,
            description=req.description,
            trigger_config=req.trigger_config,
            audience_filter=req.audience_filter,
            priority=req.priority,
            max_concurrent=req.max_concurrent,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    await db.commit()
    return {"ok": True, "data": result}


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: str = Path(...),
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """删除旅程模板"""
    svc = CustomerJourneyService(db)
    try:
        result = await svc.delete_template(
            tenant_id=x_tenant_id,
            template_id=template_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    await db.commit()
    return {"ok": True, "data": result}


@router.post("/templates/{template_id}/toggle")
async def toggle_template(
    template_id: str = Path(...),
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """启用/停用旅程模板"""
    svc = CustomerJourneyService(db)
    try:
        result = await svc.toggle_active(
            tenant_id=x_tenant_id,
            template_id=template_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    await db.commit()
    return {"ok": True, "data": result}


# ══════════════════════════════════════════════
# 步骤管理(4端点)
# ══════════════════════════════════════════════


@router.post("/templates/{template_id}/steps")
async def add_step(
    req: AddStepRequest,
    template_id: str = Path(...),
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """添加旅程步骤"""
    svc = CustomerJourneyService(db)
    result = await svc.add_step(
        tenant_id=x_tenant_id,
        template_id=template_id,
        step_name=req.step_name,
        channel=req.channel,
        step_order=req.step_order,
        delay_minutes=req.delay_minutes,
        content_template=req.content_template,
        condition=req.condition,
        skip_if_responded=req.skip_if_responded,
    )
    await db.commit()
    return {"ok": True, "data": result}


@router.put("/steps/{step_id}")
async def update_step(
    req: UpdateStepRequest,
    step_id: str = Path(...),
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """更新旅程步骤"""
    svc = CustomerJourneyService(db)
    try:
        result = await svc.update_step(
            tenant_id=x_tenant_id,
            step_id=step_id,
            step_name=req.step_name,
            delay_minutes=req.delay_minutes,
            channel=req.channel,
            content_template=req.content_template,
            condition=req.condition,
            skip_if_responded=req.skip_if_responded,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    await db.commit()
    return {"ok": True, "data": result}


@router.delete("/steps/{step_id}")
async def delete_step(
    step_id: str = Path(...),
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """删除旅程步骤"""
    svc = CustomerJourneyService(db)
    try:
        result = await svc.delete_step(
            tenant_id=x_tenant_id,
            step_id=step_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    await db.commit()
    return {"ok": True, "data": result}


@router.post("/templates/{template_id}/reorder-steps")
async def reorder_steps(
    req: ReorderStepsRequest,
    template_id: str = Path(...),
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """调整步骤顺序"""
    svc = CustomerJourneyService(db)
    result = await svc.reorder_steps(
        tenant_id=x_tenant_id,
        template_id=template_id,
        step_ids=req.step_ids,
    )
    await db.commit()
    return {"ok": True, "data": result}


# ══════════════════════════════════════════════
# 触发(1端点)
# ══════════════════════════════════════════════


@router.post("/trigger")
async def trigger_journey(
    req: TriggerJourneyRequest,
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """手动触发旅程"""
    svc = CustomerJourneyService(db)
    result = await svc.trigger_journey(
        tenant_id=x_tenant_id,
        trigger_type=req.trigger_type,
        customer_id=req.customer_id,
        store_id=req.store_id,
        event_data=req.event_data,
    )
    await db.commit()
    return {"ok": True, "data": {"enrollments": result}}


# ══════════════════════════════════════════════
# 实例管理(5端点)
# ══════════════════════════════════════════════


@router.get("/enrollments")
async def list_enrollments(
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    template_id: str | None = Query(None),
    customer_id: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    """旅程实例列表"""
    svc = CustomerJourneyService(db)
    result = await svc.list_enrollments(
        tenant_id=x_tenant_id,
        template_id=template_id,
        customer_id=customer_id,
        status=status,
        page=page,
        size=size,
    )
    return {"ok": True, "data": result}


@router.get("/enrollments/{enrollment_id}")
async def get_enrollment(
    enrollment_id: str = Path(...),
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """旅程实例详情(含步骤日志)"""
    svc = CustomerJourneyService(db)
    result = await svc.get_enrollment(
        tenant_id=x_tenant_id,
        enrollment_id=enrollment_id,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="旅程实例不存在")
    return {"ok": True, "data": result}


@router.post("/enrollments/{enrollment_id}/pause")
async def pause_enrollment(
    enrollment_id: str = Path(...),
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """暂停旅程实例"""
    svc = CustomerJourneyService(db)
    try:
        result = await svc.pause_enrollment(
            tenant_id=x_tenant_id,
            enrollment_id=enrollment_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    await db.commit()
    return {"ok": True, "data": result}


@router.post("/enrollments/{enrollment_id}/resume")
async def resume_enrollment(
    enrollment_id: str = Path(...),
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """恢复旅程实例"""
    svc = CustomerJourneyService(db)
    try:
        result = await svc.resume_enrollment(
            tenant_id=x_tenant_id,
            enrollment_id=enrollment_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    await db.commit()
    return {"ok": True, "data": result}


@router.post("/enrollments/{enrollment_id}/cancel")
async def cancel_enrollment(
    enrollment_id: str = Path(...),
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """取消旅程实例"""
    svc = CustomerJourneyService(db)
    try:
        result = await svc.cancel_enrollment(
            tenant_id=x_tenant_id,
            enrollment_id=enrollment_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    await db.commit()
    return {"ok": True, "data": result}


# ══════════════════════════════════════════════
# 统计(1端点)
# ══════════════════════════════════════════════


@router.get("/templates/{template_id}/stats")
async def get_template_stats(
    template_id: str = Path(...),
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """模板统计(总触发/进行中/完成/各步骤转化率)"""
    svc = CustomerJourneyService(db)
    result = await svc.get_template_stats(
        tenant_id=x_tenant_id,
        template_id=template_id,
    )
    return {"ok": True, "data": result}


# ══════════════════════════════════════════════
# 预设初始化(1端点)
# ══════════════════════════════════════════════


@router.post("/presets/init")
async def init_presets(
    req: InitPresetsRequest,
    db: AsyncSession = Depends(_get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """初始化预设旅程(消费后关怀链/沉睡客户召回/生日关怀)"""
    svc = CustomerJourneyService(db)
    result = await svc.create_preset_journeys(
        tenant_id=x_tenant_id,
        created_by=req.created_by,
    )
    await db.commit()
    return {"ok": True, "data": result}
