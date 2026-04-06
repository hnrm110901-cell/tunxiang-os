"""增长中枢 V2 API — 31 个端点

端点：
  # Customer Growth Profile
  GET    /api/v1/growth/customers/{customer_id}/profile        → 客户增长画像
  PATCH  /api/v1/growth/customers/{customer_id}/profile        → 更新增长画像

  # Journey Templates
  GET    /api/v1/growth/journey-templates                      → 旅程模板列表
  POST   /api/v1/growth/journey-templates                      → 创建旅程模板
  GET    /api/v1/growth/journey-templates/{template_id}        → 旅程模板详情
  PUT    /api/v1/growth/journey-templates/{template_id}        → 更新旅程模板
  POST   /api/v1/growth/journey-templates/{template_id}/activate    → 激活
  POST   /api/v1/growth/journey-templates/{template_id}/deactivate  → 停用

  # Journey Enrollments
  GET    /api/v1/growth/journey-enrollments                    → 旅程参与列表
  POST   /api/v1/growth/journey-enrollments                    → 创建旅程参与
  GET    /api/v1/growth/journey-enrollments/{enrollment_id}    → 参与详情
  PATCH  /api/v1/growth/journey-enrollments/{enrollment_id}/state → 更新参与状态

  # Touch Executions
  GET    /api/v1/growth/touch-executions                       → 触达执行列表
  POST   /api/v1/growth/touch-executions                       → 创建触达执行
  PATCH  /api/v1/growth/touch-executions/{execution_id}        → 更新触达状态
  PATCH  /api/v1/growth/touch-executions/{execution_id}/attribution → 更新归因

  # Service Repair Cases
  GET    /api/v1/growth/service-repair-cases                   → 服务修复列表
  POST   /api/v1/growth/service-repair-cases                   → 创建服务修复
  GET    /api/v1/growth/service-repair-cases/{case_id}         → 修复详情
  PATCH  /api/v1/growth/service-repair-cases/{case_id}/state   → 更新修复状态
  PATCH  /api/v1/growth/service-repair-cases/{case_id}/compensation → 更新补偿方案

  # Agent Strategy Suggestions
  GET    /api/v1/growth/agent-suggestions                      → 策略建议列表
  POST   /api/v1/growth/agent-suggestions                      → 创建策略建议
  GET    /api/v1/growth/agent-suggestions/{suggestion_id}      → 建议详情
  POST   /api/v1/growth/agent-suggestions/{suggestion_id}/review  → 审核建议
  POST   /api/v1/growth/agent-suggestions/{suggestion_id}/publish → 发布建议

  # Dashboard & Attribution
  GET    /api/v1/growth/dashboard-stats                        → 增长驾驶舱KPI聚合(含mechanism_summary)
  GET    /api/v1/growth/attribution/by-mechanism               → 按心理机制归因统计
  GET    /api/v1/growth/attribution/by-journey-template        → 按旅程模板归因统计
  GET    /api/v1/growth/attribution/repair-effectiveness       → 服务修复效果归因
  GET    /api/v1/growth/customers/funnel-stats                 → 客户增长漏斗

所有端点必须携带 X-Tenant-ID Header（UUID 格式）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from services.growth_profile_service import GrowthProfileService
from services.growth_journey_service import GrowthJourneyService
from services.growth_touch_service import GrowthTouchService
from services.growth_repair_service import GrowthRepairService
from services.growth_suggestion_service import GrowthSuggestionService
from shared.ontology.src.database import async_session_factory

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/growth", tags=["growth-hub"])

_profile_svc = GrowthProfileService()
_journey_svc = GrowthJourneyService()
_touch_svc = GrowthTouchService()
_repair_svc = GrowthRepairService()
_suggestion_svc = GrowthSuggestionService()


# ---------------------------------------------------------------------------
# 统一响应
# ---------------------------------------------------------------------------

def ok(data: Any) -> dict:
    return {"ok": True, "data": data}


def err(msg: str) -> dict:
    return {"ok": False, "error": {"message": msg}}


def _parse_tenant(x_tenant_id: str) -> UUID:
    try:
        return UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"X-Tenant-ID 格式无效: {x_tenant_id}")


# ---------------------------------------------------------------------------
# 请求/响应模型
# ---------------------------------------------------------------------------

# --- Customer Growth Profile ---

class GrowthProfileUpdate(BaseModel):
    repurchase_stage: Optional[str] = None
    reactivation_priority: Optional[str] = None
    reactivation_reason: Optional[str] = None
    has_active_owned_benefit: Optional[bool] = None
    owned_benefit_type: Optional[str] = None
    owned_benefit_expire_at: Optional[datetime] = None
    service_repair_status: Optional[str] = None
    growth_opt_out: Optional[bool] = None
    marketing_pause_until: Optional[datetime] = None


# --- Journey Template ---

class JourneyStepCreate(BaseModel):
    step_no: int
    step_type: str
    mechanism_type: Optional[str] = None
    wait_minutes: Optional[int] = None
    decision_rule_json: Optional[dict] = None
    offer_rule_json: Optional[dict] = None
    touch_template_id: Optional[str] = None
    observe_window_hours: Optional[int] = None
    success_next_step_no: Optional[int] = None
    fail_next_step_no: Optional[int] = None
    skip_next_step_no: Optional[int] = None


class JourneyTemplateCreate(BaseModel):
    code: str
    name: str
    journey_type: str  # first_to_second / reactivation / service_repair
    mechanism_family: str  # hook / loss_aversion / repair / mixed
    target_segment_rule_id: Optional[str] = None
    entry_rule_json: dict = Field(default_factory=dict)
    exit_rule_json: dict = Field(default_factory=dict)
    pause_rule_json: dict = Field(default_factory=dict)
    priority: int = 100
    steps: list[JourneyStepCreate] = Field(default_factory=list)


# --- Journey Enrollment ---

class EnrollmentCreate(BaseModel):
    customer_id: str
    journey_template_id: str
    enrollment_source: str  # rule_engine / agent_suggestion / manual / event_trigger
    source_event_type: Optional[str] = None
    source_event_id: Optional[str] = None
    assigned_agent_suggestion_id: Optional[str] = None


class EnrollmentStateUpdate(BaseModel):
    journey_state: str  # paused / active / cancelled
    pause_reason: Optional[str] = None


# --- Touch Execution ---

class TouchExecutionCreate(BaseModel):
    customer_id: str
    journey_enrollment_id: Optional[str] = None
    touch_template_code: str
    channel: str
    mechanism_type: Optional[str] = None
    variables: dict = Field(default_factory=dict)


class TouchStateUpdate(BaseModel):
    execution_state: str


class TouchAttributionUpdate(BaseModel):
    attributed_order_id: str
    attributed_revenue_fen: int
    attributed_gross_profit_fen: int


# --- Service Repair ---

class RepairCaseCreate(BaseModel):
    customer_id: str
    source_type: str  # complaint / bad_review / refund / service_timeout
    source_ref_id: Optional[str] = None
    severity: str = "medium"
    summary: Optional[str] = None
    owner_type: str = "auto"


class RepairStateUpdate(BaseModel):
    repair_state: str


class RepairCompensationUpdate(BaseModel):
    compensation_plan_json: dict
    compensation_selected: str


# --- Agent Suggestion ---

class SuggestionCreate(BaseModel):
    customer_id: Optional[str] = None
    segment_package_id: Optional[str] = None
    journey_template_id: Optional[str] = None
    suggestion_type: str
    priority: str = "medium"
    mechanism_type: Optional[str] = None
    recommended_offer_type: Optional[str] = None
    recommended_channel: Optional[str] = None
    recommended_touch_template_id: Optional[str] = None
    explanation_summary: str
    risk_summary: Optional[str] = None
    expected_outcome_json: Optional[dict] = None
    requires_human_review: bool = False
    created_by_agent: Optional[str] = None


class SuggestionReview(BaseModel):
    review_result: str  # approved / rejected / revised
    reviewer_id: str
    reviewer_note: Optional[str] = None
    revised_offer_type: Optional[str] = None
    revised_channel: Optional[str] = None
    revised_template_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Customer Growth Profile 端点 (2)
# ---------------------------------------------------------------------------

@router.get("/customers/{customer_id}/profile")
async def get_growth_profile(
    customer_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """获取客户增长画像。"""
    tenant_id = _parse_tenant(x_tenant_id)
    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        try:
            result = await _profile_svc.get_profile(UUID(customer_id), str(tenant_id), db)
            if result is None:
                return err("Profile not found")
            return ok(result)
        except ValueError as exc:
            return err(str(exc))


@router.patch("/customers/{customer_id}/profile")
async def update_growth_profile(
    customer_id: str,
    body: GrowthProfileUpdate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """更新客户增长画像。"""
    tenant_id = _parse_tenant(x_tenant_id)
    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        try:
            result = await _profile_svc.upsert_profile(
                UUID(customer_id),
                body.model_dump(exclude_unset=True),
                str(tenant_id),
                db,
            )
            await db.commit()
            return ok(result)
        except ValueError as exc:
            return err(str(exc))


# ---------------------------------------------------------------------------
# Journey Templates 端点 (6)
# ---------------------------------------------------------------------------

@router.get("/journey-templates")
async def list_journey_templates(
    journey_type: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """列出旅程模板（支持筛选）。"""
    tenant_id = _parse_tenant(x_tenant_id)
    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        try:
            result = await _journey_svc.list_templates(
                journey_type=journey_type,
                is_active=is_active,
                tenant_id=str(tenant_id),
                db=db,
            )
            return ok(result)
        except ValueError as exc:
            return err(str(exc))


@router.post("/journey-templates")
async def create_journey_template(
    body: JourneyTemplateCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """创建旅程模板。"""
    tenant_id = _parse_tenant(x_tenant_id)
    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        try:
            result = await _journey_svc.create_template(
                body.model_dump(), str(tenant_id), db,
            )
            await db.commit()
            return ok(result)
        except ValueError as exc:
            return err(str(exc))


@router.get("/journey-templates/{template_id}")
async def get_journey_template(
    template_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """获取旅程模板详情。"""
    tenant_id = _parse_tenant(x_tenant_id)
    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        try:
            result = await _journey_svc.get_template(UUID(template_id), str(tenant_id), db)
            if result is None:
                return err("Journey template not found")
            return ok(result)
        except ValueError as exc:
            return err(str(exc))


@router.put("/journey-templates/{template_id}")
async def update_journey_template(
    template_id: str,
    body: JourneyTemplateCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """更新旅程模板。"""
    tenant_id = _parse_tenant(x_tenant_id)
    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        try:
            result = await _journey_svc.update_template(
                UUID(template_id), body.model_dump(), str(tenant_id), db,
            )
            await db.commit()
            return ok(result)
        except ValueError as exc:
            return err(str(exc))


@router.post("/journey-templates/{template_id}/activate")
async def activate_journey_template(
    template_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """激活旅程模板。"""
    tenant_id = _parse_tenant(x_tenant_id)
    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        try:
            result = await _journey_svc.activate_template(UUID(template_id), str(tenant_id), db)
            await db.commit()
            return ok(result)
        except ValueError as exc:
            return err(str(exc))


@router.post("/journey-templates/{template_id}/deactivate")
async def deactivate_journey_template(
    template_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """停用旅程模板。"""
    tenant_id = _parse_tenant(x_tenant_id)
    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        try:
            result = await _journey_svc.deactivate_template(UUID(template_id), str(tenant_id), db)
            await db.commit()
            return ok(result)
        except ValueError as exc:
            return err(str(exc))


# ---------------------------------------------------------------------------
# Journey Enrollments 端点 (4)
# ---------------------------------------------------------------------------

@router.get("/journey-enrollments")
async def list_journey_enrollments(
    customer_id: Optional[str] = Query(None),
    journey_state: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """列出旅程参与记录（支持筛选）。"""
    tenant_id = _parse_tenant(x_tenant_id)
    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        try:
            result = await _journey_svc.list_enrollments(
                str(tenant_id), db,
                customer_id=customer_id,
                journey_state=journey_state,
                page=page,
                size=size,
            )
            return ok(result)
        except ValueError as exc:
            return err(str(exc))


@router.post("/journey-enrollments")
async def create_journey_enrollment(
    body: EnrollmentCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """创建旅程参与。"""
    tenant_id = _parse_tenant(x_tenant_id)
    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        try:
            result = await _journey_svc.enroll_customer(
                customer_id=UUID(body.customer_id),
                template_id=UUID(body.journey_template_id),
                source=body.enrollment_source,
                event_type=body.source_event_type,
                event_id=body.source_event_id,
                suggestion_id=UUID(body.assigned_agent_suggestion_id) if body.assigned_agent_suggestion_id else None,
                tenant_id=str(tenant_id),
                db=db,
            )
            await db.commit()
            return ok(result)
        except ValueError as exc:
            return err(str(exc))


@router.get("/journey-enrollments/{enrollment_id}")
async def get_journey_enrollment(
    enrollment_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """获取旅程参与详情。"""
    tenant_id = _parse_tenant(x_tenant_id)
    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        try:
            result = await _journey_svc.get_enrollment(UUID(enrollment_id), str(tenant_id), db)
            if result is None:
                return err("Enrollment not found")
            return ok(result)
        except ValueError as exc:
            return err(str(exc))


@router.patch("/journey-enrollments/{enrollment_id}/state")
async def update_enrollment_state(
    enrollment_id: str,
    body: EnrollmentStateUpdate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """更新旅程参与状态（暂停/恢复/取消）。"""
    tenant_id = _parse_tenant(x_tenant_id)
    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        try:
            target = body.journey_state
            eid = UUID(enrollment_id)
            if target == "paused":
                result = await _journey_svc.pause_enrollment(
                    eid, body.pause_reason or "", str(tenant_id), db,
                )
            elif target == "active":
                result = await _journey_svc.resume_enrollment(
                    eid, str(tenant_id), db,
                )
            elif target == "cancelled":
                result = await _journey_svc.cancel_enrollment(
                    eid, str(tenant_id), db,
                )
            else:
                return err(f"Unsupported target journey_state: {target}")
            await db.commit()
            return ok(result)
        except ValueError as exc:
            return err(str(exc))


# ---------------------------------------------------------------------------
# Touch Executions 端点 (4)
# ---------------------------------------------------------------------------

@router.get("/touch-executions")
async def list_touch_executions(
    customer_id: Optional[str] = Query(None),
    channel: Optional[str] = Query(None),
    execution_state: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """列出触达执行记录（支持筛选）。"""
    tenant_id = _parse_tenant(x_tenant_id)
    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        try:
            result = await _touch_svc.list_executions(
                tenant_id=str(tenant_id),
                db=db,
                customer_id=customer_id,
                enrollment_id=None,
                page=page,
                size=size,
            )
            return ok(result)
        except ValueError as exc:
            return err(str(exc))


@router.post("/touch-executions")
async def create_touch_execution(
    body: TouchExecutionCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """创建触达执行。"""
    tenant_id = _parse_tenant(x_tenant_id)
    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        try:
            result = await _touch_svc.execute_touch(
                customer_id=UUID(body.customer_id),
                enrollment_id=UUID(body.journey_enrollment_id) if body.journey_enrollment_id else None,
                template_id=UUID(body.touch_template_code),
                step_no=None,
                channel=body.channel,
                mechanism_type=body.mechanism_type,
                variables=body.variables,
                tenant_id=str(tenant_id),
                db=db,
            )
            await db.commit()
            return ok(result)
        except ValueError as exc:
            return err(str(exc))


@router.patch("/touch-executions/{execution_id}")
async def update_touch_execution_state(
    execution_id: str,
    body: TouchStateUpdate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """更新触达执行状态。"""
    tenant_id = _parse_tenant(x_tenant_id)
    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        try:
            result = await _touch_svc.update_execution_state(
                UUID(execution_id), body.execution_state, str(tenant_id), db,
            )
            await db.commit()
            return ok(result)
        except ValueError as exc:
            return err(str(exc))


@router.patch("/touch-executions/{execution_id}/attribution")
async def update_touch_attribution(
    execution_id: str,
    body: TouchAttributionUpdate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """更新触达归因（关联订单和收入）。"""
    tenant_id = _parse_tenant(x_tenant_id)
    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        try:
            result = await _touch_svc.update_attribution_by_execution(
                execution_id=UUID(execution_id),
                order_id=UUID(body.attributed_order_id),
                revenue_fen=body.attributed_revenue_fen,
                profit_fen=body.attributed_gross_profit_fen,
                tenant_id=str(tenant_id),
                db=db,
            )
            await db.commit()
            return ok(result)
        except ValueError as exc:
            return err(str(exc))


# ---------------------------------------------------------------------------
# Service Repair Cases 端点 (5)
# ---------------------------------------------------------------------------

@router.get("/service-repair-cases")
async def list_repair_cases(
    customer_id: Optional[str] = Query(None),
    repair_state: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """列出服务修复案例（支持筛选）。"""
    tenant_id = _parse_tenant(x_tenant_id)
    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        try:
            result = await _repair_svc.list_cases(
                customer_id=UUID(customer_id) if customer_id else None,
                repair_state=repair_state,
                tenant_id=str(tenant_id),
                page=page,
                size=size,
                db=db,
            )
            return ok(result)
        except ValueError as exc:
            return err(str(exc))


@router.post("/service-repair-cases")
async def create_repair_case(
    body: RepairCaseCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """创建服务修复案例。"""
    tenant_id = _parse_tenant(x_tenant_id)
    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        try:
            result = await _repair_svc.create_case(
                customer_id=UUID(body.customer_id),
                source_type=body.source_type,
                source_ref_id=body.source_ref_id,
                severity=body.severity,
                summary=body.summary,
                owner_type=body.owner_type,
                tenant_id=str(tenant_id),
                db=db,
            )
            await db.commit()
            return ok(result)
        except ValueError as exc:
            return err(str(exc))


@router.get("/service-repair-cases/{case_id}")
async def get_repair_case(
    case_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """获取服务修复案例详情。"""
    tenant_id = _parse_tenant(x_tenant_id)
    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        try:
            result = await _repair_svc.get_case(UUID(case_id), str(tenant_id), db)
            if result is None:
                return err("Repair case not found")
            return ok(result)
        except ValueError as exc:
            return err(str(exc))


@router.patch("/service-repair-cases/{case_id}/state")
async def update_repair_case_state(
    case_id: str,
    body: RepairStateUpdate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """更新服务修复状态。"""
    tenant_id = _parse_tenant(x_tenant_id)
    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        try:
            result = await _repair_svc.transition_state(
                case_id=UUID(case_id),
                target_state=body.repair_state,
                tenant_id=str(tenant_id),
                db=db,
            )
            await db.commit()
            return ok(result)
        except ValueError as exc:
            return err(str(exc))


@router.patch("/service-repair-cases/{case_id}/compensation")
async def update_repair_compensation(
    case_id: str,
    body: RepairCompensationUpdate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """更新服务修复补偿方案。"""
    tenant_id = _parse_tenant(x_tenant_id)
    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        try:
            result = await _repair_svc.submit_compensation(
                case_id=UUID(case_id),
                plan_json=body.compensation_plan_json,
                selected=body.compensation_selected,
                tenant_id=str(tenant_id),
                db=db,
            )
            await db.commit()
            return ok(result)
        except ValueError as exc:
            return err(str(exc))


# ---------------------------------------------------------------------------
# Agent Strategy Suggestions 端点 (5)
# ---------------------------------------------------------------------------

@router.get("/agent-suggestions")
async def list_agent_suggestions(
    customer_id: Optional[str] = Query(None),
    suggestion_type: Optional[str] = Query(None),
    review_state: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """列出 Agent 策略建议（支持筛选）。"""
    tenant_id = _parse_tenant(x_tenant_id)
    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        try:
            result = await _suggestion_svc.list_suggestions(
                review_state=review_state,
                suggestion_type=suggestion_type,
                customer_id=UUID(customer_id) if customer_id else None,
                tenant_id=str(tenant_id),
                page=page,
                size=size,
                db=db,
            )
            return ok(result)
        except ValueError as exc:
            return err(str(exc))


@router.post("/agent-suggestions")
async def create_agent_suggestion(
    body: SuggestionCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """创建 Agent 策略建议。"""
    tenant_id = _parse_tenant(x_tenant_id)
    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        try:
            result = await _suggestion_svc.create_suggestion(
                body.model_dump(), str(tenant_id), db,
            )
            await db.commit()
            return ok(result)
        except ValueError as exc:
            return err(str(exc))


@router.get("/agent-suggestions/{suggestion_id}")
async def get_agent_suggestion(
    suggestion_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """获取 Agent 策略建议详情。"""
    tenant_id = _parse_tenant(x_tenant_id)
    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        try:
            result = await _suggestion_svc.get_suggestion(UUID(suggestion_id), str(tenant_id), db)
            if result is None:
                return err("Suggestion not found")
            return ok(result)
        except ValueError as exc:
            return err(str(exc))


@router.post("/agent-suggestions/{suggestion_id}/review")
async def review_agent_suggestion(
    suggestion_id: str,
    body: SuggestionReview,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """审核 Agent 策略建议。"""
    tenant_id = _parse_tenant(x_tenant_id)
    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        try:
            revised_data = None
            if body.review_result == "revised":
                revised_data = {}
                if body.revised_offer_type is not None:
                    revised_data["offer"] = body.revised_offer_type
                if body.revised_channel is not None:
                    revised_data["channel"] = body.revised_channel
                if body.revised_template_id is not None:
                    revised_data["template_id"] = body.revised_template_id
            result = await _suggestion_svc.review_suggestion(
                suggestion_id=UUID(suggestion_id),
                result_action=body.review_result,
                reviewer_id=UUID(body.reviewer_id),
                note=body.reviewer_note,
                revised_data=revised_data,
                tenant_id=str(tenant_id),
                db=db,
            )
            await db.commit()
            return ok(result)
        except ValueError as exc:
            return err(str(exc))


@router.post("/agent-suggestions/{suggestion_id}/publish")
async def publish_agent_suggestion(
    suggestion_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """发布 Agent 策略建议（触发执行）。"""
    tenant_id = _parse_tenant(x_tenant_id)
    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        try:
            result = await _suggestion_svc.publish_suggestion(
                UUID(suggestion_id), str(tenant_id), db,
            )
            await db.commit()
            return ok(result)
        except ValueError as exc:
            return err(str(exc))


# ---------------------------------------------------------------------------
# Dashboard Stats 聚合端点
# ---------------------------------------------------------------------------

@router.get("/dashboard-stats")
async def get_dashboard_stats(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """增长驾驶舱KPI聚合 — 一次请求返回所有关键指标"""
    tenant_uuid = _parse_tenant(x_tenant_id)
    tenant_id = str(tenant_uuid)

    async with async_session_factory() as db:
        try:
            await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})

            # 1. 客户增长画像统计
            profile_stats = await db.execute(text("""
                SELECT
                    COUNT(*) AS total_profiles,
                    COUNT(*) FILTER (WHERE repurchase_stage = 'first_order_done') AS first_order_only,
                    COUNT(*) FILTER (WHERE repurchase_stage = 'second_order_done') AS second_order_done,
                    COUNT(*) FILTER (WHERE repurchase_stage = 'stable_repeat') AS stable_repeat,
                    COUNT(*) FILTER (WHERE reactivation_priority IN ('high', 'critical')) AS high_priority_reactivation,
                    COUNT(*) FILTER (WHERE service_repair_status NOT IN ('none', 'repair_completed')) AS active_repairs
                FROM customer_growth_profiles
                WHERE is_deleted = FALSE
            """))
            ps = profile_stats.fetchone()

            # 2. 旅程enrollment统计
            enrollment_stats = await db.execute(text("""
                SELECT
                    COUNT(*) AS total_enrollments,
                    COUNT(*) FILTER (WHERE journey_state = 'active') AS active_enrollments,
                    COUNT(*) FILTER (WHERE journey_state = 'paused') AS paused_enrollments,
                    COUNT(*) FILTER (WHERE journey_state = 'completed') AS completed_enrollments,
                    COUNT(*) FILTER (WHERE journey_state = 'waiting_observe') AS observing_enrollments
                FROM growth_journey_enrollments
                WHERE is_deleted = FALSE
            """))
            es = enrollment_stats.fetchone()

            # 3. 触达执行统计（近7天）
            touch_stats = await db.execute(text("""
                SELECT
                    COUNT(*) AS total_touches_7d,
                    COUNT(*) FILTER (WHERE execution_state = 'delivered') AS delivered_7d,
                    COUNT(*) FILTER (WHERE execution_state = 'opened') AS opened_7d,
                    COUNT(*) FILTER (WHERE execution_state = 'clicked') AS clicked_7d,
                    COUNT(*) FILTER (WHERE attributed_order_id IS NOT NULL) AS attributed_7d,
                    COALESCE(SUM(attributed_revenue_fen) FILTER (WHERE attributed_order_id IS NOT NULL), 0) AS attributed_revenue_fen_7d
                FROM growth_touch_executions
                WHERE is_deleted = FALSE AND created_at >= NOW() - INTERVAL '7 days'
            """))
            ts = touch_stats.fetchone()

            # 4. Agent建议统计
            suggestion_stats = await db.execute(text("""
                SELECT
                    COUNT(*) AS total_suggestions,
                    COUNT(*) FILTER (WHERE review_state = 'pending_review') AS pending_review,
                    COUNT(*) FILTER (WHERE review_state = 'approved') AS approved,
                    COUNT(*) FILTER (WHERE review_state = 'published') AS published,
                    COUNT(*) FILTER (WHERE review_state = 'rejected') AS rejected
                FROM growth_agent_strategy_suggestions
                WHERE is_deleted = FALSE AND created_at >= NOW() - INTERVAL '7 days'
            """))
            ss = suggestion_stats.fetchone()

            # 5. 增长漏斗（首单→入会→触达→到店→复购）
            total_profiles = ps[0] if ps else 0
            first_order = ps[1] if ps else 0
            second_order = ps[2] if ps else 0
            stable = ps[3] if ps else 0

            delivered = ts[1] if ts else 0
            attributed = ts[4] if ts else 0

            funnel = {
                "first_order": first_order + second_order + stable,
                "touched": delivered,
                "revisited": attributed,
                "repeat_customer": second_order + stable,
                "stable_repeat": stable,
            }

            # 6. 二访率和召回率
            conversion_rates: dict = {}
            if first_order + second_order + stable > 0:
                conversion_rates["second_visit_rate"] = round((second_order + stable) / (first_order + second_order + stable) * 100, 1)
            else:
                conversion_rates["second_visit_rate"] = 0.0

            if delivered > 0:
                conversion_rates["touch_open_rate"] = round((ts[2] if ts else 0) / delivered * 100, 1)
                conversion_rates["touch_attribution_rate"] = round(attributed / delivered * 100, 1)
            else:
                conversion_rates["touch_open_rate"] = 0.0
                conversion_rates["touch_attribution_rate"] = 0.0

            # 7. mechanism_type 分组摘要（近7天）
            mech_stats = await db.execute(text("""
                SELECT mechanism_type, COUNT(*),
                       COUNT(*) FILTER (WHERE execution_state IN ('opened','clicked','replied')),
                       COUNT(*) FILTER (WHERE attributed_order_id IS NOT NULL)
                FROM growth_touch_executions
                WHERE is_deleted = FALSE AND created_at >= NOW() - INTERVAL '7 days'
                  AND mechanism_type IS NOT NULL
                GROUP BY mechanism_type
            """))
            mech_rows = mech_stats.fetchall()
            mechanism_summary = []
            for mr in mech_rows:
                total_m = mr[1] or 0
                mechanism_summary.append({
                    "mechanism_type": mr[0],
                    "total": total_m,
                    "opened": mr[2] or 0,
                    "attributed": mr[3] or 0,
                    "open_rate": round((mr[2] or 0) / total_m * 100, 1) if total_m > 0 else 0,
                    "attribution_rate": round((mr[3] or 0) / total_m * 100, 1) if total_m > 0 else 0,
                })

            return {"ok": True, "data": {
                "profiles": {
                    "total": total_profiles,
                    "first_order_only": first_order,
                    "second_order_done": second_order,
                    "stable_repeat": stable,
                    "high_priority_reactivation": ps[4] if ps else 0,
                    "active_repairs": ps[5] if ps else 0,
                },
                "enrollments": {
                    "total": es[0] if es else 0,
                    "active": es[1] if es else 0,
                    "paused": es[2] if es else 0,
                    "completed": es[3] if es else 0,
                    "observing": es[4] if es else 0,
                },
                "touches_7d": {
                    "total": ts[0] if ts else 0,
                    "delivered": delivered,
                    "opened": ts[2] if ts else 0,
                    "clicked": ts[3] if ts else 0,
                    "attributed": attributed,
                    "attributed_revenue_fen": ts[5] if ts else 0,
                },
                "suggestions_7d": {
                    "total": ss[0] if ss else 0,
                    "pending_review": ss[1] if ss else 0,
                    "approved": ss[2] if ss else 0,
                    "published": ss[3] if ss else 0,
                    "rejected": ss[4] if ss else 0,
                },
                "funnel": funnel,
                "conversion_rates": conversion_rates,
                "mechanism_summary": mechanism_summary,
            }}
        except (ValueError, RuntimeError, OSError) as exc:
            return {"ok": False, "error": {"message": str(exc)}}


# ---------------------------------------------------------------------------
# Customer Funnel Stats 端点（客户总池页面用）
# ---------------------------------------------------------------------------

@router.get("/customers/funnel-stats")
async def get_funnel_stats(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """客户增长漏斗统计 — 与 dashboard-stats 中 funnel 数据一致，供客户总池页面独立调用。"""
    tenant_uuid = _parse_tenant(x_tenant_id)
    tenant_id = str(tenant_uuid)

    async with async_session_factory() as db:
        try:
            await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})

            profile_stats = await db.execute(text("""
                SELECT
                    COUNT(*) AS total_profiles,
                    COUNT(*) FILTER (WHERE repurchase_stage = 'first_order_done') AS first_order_only,
                    COUNT(*) FILTER (WHERE repurchase_stage = 'second_order_done') AS second_order_done,
                    COUNT(*) FILTER (WHERE repurchase_stage = 'stable_repeat') AS stable_repeat,
                    COUNT(*) FILTER (WHERE reactivation_priority IN ('high', 'critical')) AS high_priority_reactivation
                FROM customer_growth_profiles
                WHERE is_deleted = FALSE
            """))
            ps = profile_stats.fetchone()

            touch_stats = await db.execute(text("""
                SELECT
                    COUNT(*) FILTER (WHERE execution_state = 'delivered') AS delivered_7d,
                    COUNT(*) FILTER (WHERE attributed_order_id IS NOT NULL) AS attributed_7d
                FROM growth_touch_executions
                WHERE is_deleted = FALSE AND created_at >= NOW() - INTERVAL '7 days'
            """))
            ts = touch_stats.fetchone()

            total = ps[0] if ps else 0
            first_order = ps[1] if ps else 0
            second_order = ps[2] if ps else 0
            stable = ps[3] if ps else 0
            delivered = ts[0] if ts else 0
            attributed = ts[1] if ts else 0

            funnel = {
                "total_profiles": total,
                "first_order": first_order + second_order + stable,
                "touched": delivered,
                "revisited": attributed,
                "repeat_customer": second_order + stable,
                "stable_repeat": stable,
                "high_priority_reactivation": ps[4] if ps else 0,
            }

            conversion_rates: dict = {}
            if first_order + second_order + stable > 0:
                conversion_rates["second_visit_rate"] = round((second_order + stable) / (first_order + second_order + stable) * 100, 1)
            else:
                conversion_rates["second_visit_rate"] = 0.0

            return ok({"funnel": funnel, "conversion_rates": conversion_rates})
        except (ValueError, RuntimeError, OSError) as exc:
            return err(str(exc))


# ---------------------------------------------------------------------------
# Attribution 归因端点 (3)
# ---------------------------------------------------------------------------

@router.get("/attribution/by-mechanism")
async def get_attribution_by_mechanism(
    days: int = Query(7, ge=1, le=90),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """按心理机制分组的触达归因统计。"""
    tenant_id = str(_parse_tenant(x_tenant_id))
    async with async_session_factory() as db:
        try:
            await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})

            result = await db.execute(text("""
                SELECT
                    mechanism_type,
                    COUNT(*) AS total_touches,
                    COUNT(*) FILTER (WHERE execution_state IN ('delivered','opened','clicked','replied')) AS delivered,
                    COUNT(*) FILTER (WHERE execution_state IN ('opened','clicked','replied')) AS opened,
                    COUNT(*) FILTER (WHERE execution_state IN ('clicked','replied')) AS clicked,
                    COUNT(*) FILTER (WHERE attributed_order_id IS NOT NULL) AS attributed,
                    COALESCE(SUM(attributed_revenue_fen) FILTER (WHERE attributed_order_id IS NOT NULL), 0) AS revenue_fen,
                    COALESCE(SUM(attributed_gross_profit_fen) FILTER (WHERE attributed_order_id IS NOT NULL), 0) AS profit_fen
                FROM growth_touch_executions
                WHERE is_deleted = FALSE
                  AND created_at >= NOW() - make_interval(days => :days)
                  AND mechanism_type IS NOT NULL
                GROUP BY mechanism_type
                ORDER BY attributed DESC
            """), {"days": days})

            rows = result.fetchall()
            items = []
            for r in rows:
                delivered = r[2] or 0
                items.append({
                    "mechanism_type": r[0],
                    "total_touches": r[1],
                    "delivered": delivered,
                    "opened": r[3] or 0,
                    "clicked": r[4] or 0,
                    "attributed": r[5] or 0,
                    "revenue_fen": r[6] or 0,
                    "profit_fen": r[7] or 0,
                    "open_rate": round((r[3] or 0) / delivered * 100, 1) if delivered > 0 else 0,
                    "attribution_rate": round((r[5] or 0) / delivered * 100, 1) if delivered > 0 else 0,
                })
            return ok({"items": items, "days": days})
        except (ValueError, RuntimeError, OSError) as exc:
            return err(str(exc))


@router.get("/attribution/by-journey-template")
async def get_attribution_by_journey_template(
    days: int = Query(7, ge=1, le=90),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """按旅程模板分组的归因统计。"""
    tenant_id = str(_parse_tenant(x_tenant_id))
    async with async_session_factory() as db:
        try:
            await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})

            result = await db.execute(text("""
                SELECT
                    gjt.name AS template_name,
                    gjt.journey_type,
                    gjt.mechanism_family,
                    COUNT(DISTINCT gje.id) AS total_enrollments,
                    COUNT(DISTINCT gje.id) FILTER (WHERE gje.journey_state = 'completed') AS completed,
                    COUNT(DISTINCT gje.id) FILTER (WHERE gje.journey_state = 'exited') AS exited,
                    COUNT(gte.id) AS total_touches,
                    COUNT(gte.id) FILTER (WHERE gte.execution_state IN ('opened','clicked','replied')) AS opened,
                    COUNT(gte.id) FILTER (WHERE gte.attributed_order_id IS NOT NULL) AS attributed,
                    COALESCE(SUM(gte.attributed_revenue_fen) FILTER (WHERE gte.attributed_order_id IS NOT NULL), 0) AS revenue_fen
                FROM growth_journey_templates gjt
                LEFT JOIN growth_journey_enrollments gje
                    ON gje.journey_template_id = gjt.id AND gje.is_deleted = FALSE
                    AND gje.created_at >= NOW() - make_interval(days => :days)
                LEFT JOIN growth_touch_executions gte
                    ON gte.journey_enrollment_id = gje.id AND gte.is_deleted = FALSE
                WHERE gjt.is_deleted = FALSE AND gjt.is_active = TRUE
                GROUP BY gjt.id, gjt.name, gjt.journey_type, gjt.mechanism_family
                ORDER BY attributed DESC
            """), {"days": days})

            rows = result.fetchall()
            items = []
            for r in rows:
                total_enroll = r[3] or 0
                items.append({
                    "template_name": r[0],
                    "journey_type": r[1],
                    "mechanism_family": r[2],
                    "total_enrollments": total_enroll,
                    "completed": r[4] or 0,
                    "exited": r[5] or 0,
                    "completion_rate": round((r[4] or 0) / total_enroll * 100, 1) if total_enroll > 0 else 0,
                    "total_touches": r[6] or 0,
                    "opened": r[7] or 0,
                    "attributed": r[8] or 0,
                    "revenue_fen": r[9] or 0,
                })
            return ok({"items": items, "days": days})
        except (ValueError, RuntimeError, OSError) as exc:
            return err(str(exc))


@router.get("/attribution/repair-effectiveness")
async def get_repair_effectiveness(
    days: int = Query(30, ge=1, le=365),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """服务修复效果归因。"""
    tenant_id = str(_parse_tenant(x_tenant_id))
    async with async_session_factory() as db:
        try:
            await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})

            result = await db.execute(text("""
                SELECT
                    COUNT(*) AS total_cases,
                    COUNT(*) FILTER (WHERE repair_state = 'recovered') AS recovered,
                    COUNT(*) FILTER (WHERE repair_state = 'failed') AS failed,
                    COUNT(*) FILTER (WHERE repair_state = 'closed') AS closed,
                    COUNT(*) FILTER (WHERE repair_state IN ('opened','acknowledged','compensating','observing')) AS in_progress,
                    AVG(EXTRACT(EPOCH FROM (recovered_at - created_at))/3600)
                        FILTER (WHERE recovered_at IS NOT NULL) AS avg_recovery_hours,
                    AVG(EXTRACT(EPOCH FROM (emotion_ack_at - created_at))/60)
                        FILTER (WHERE emotion_ack_at IS NOT NULL) AS avg_ack_minutes
                FROM growth_service_repair_cases
                WHERE is_deleted = FALSE
                  AND created_at >= NOW() - make_interval(days => :days)
            """), {"days": days})

            r = result.fetchone()
            total = r[0] if r else 0
            return ok({
                "total_cases": total,
                "recovered": r[1] or 0 if r else 0,
                "failed": r[2] or 0 if r else 0,
                "closed": r[3] or 0 if r else 0,
                "in_progress": r[4] or 0 if r else 0,
                "recovery_rate": round((r[1] or 0) / total * 100, 1) if r and total > 0 else 0,
                "avg_recovery_hours": round(r[5], 1) if r and r[5] else None,
                "avg_ack_minutes": round(r[6], 1) if r and r[6] else None,
                "days": days,
            })
        except (ValueError, RuntimeError, OSError) as exc:
            return err(str(exc))
