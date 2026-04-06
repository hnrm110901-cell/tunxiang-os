"""增长中枢 V2 API — 25 个端点

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

所有端点必须携带 X-Tenant-ID Header（UUID 格式）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
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
            result = await _profile_svc.update_profile(
                UUID(customer_id),
                str(tenant_id),
                body.model_dump(exclude_unset=True),
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
                str(tenant_id), db,
                journey_type=journey_type,
                is_active=is_active,
                page=page,
                size=size,
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
                str(tenant_id), body.model_dump(), db,
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
            result = await _journey_svc.get_template(template_id, str(tenant_id), db)
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
                template_id, str(tenant_id), body.model_dump(), db,
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
            result = await _journey_svc.activate_template(template_id, str(tenant_id), db)
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
            result = await _journey_svc.deactivate_template(template_id, str(tenant_id), db)
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
            result = await _journey_svc.create_enrollment(
                str(tenant_id), body.model_dump(), db,
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
            result = await _journey_svc.get_enrollment(enrollment_id, str(tenant_id), db)
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
            result = await _journey_svc.update_enrollment_state(
                enrollment_id, str(tenant_id), body.model_dump(), db,
            )
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
                str(tenant_id), db,
                customer_id=customer_id,
                channel=channel,
                execution_state=execution_state,
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
            result = await _touch_svc.create_execution(
                str(tenant_id), body.model_dump(), db,
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
                execution_id, str(tenant_id), body.model_dump(), db,
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
            result = await _touch_svc.update_attribution(
                execution_id, str(tenant_id), body.model_dump(), db,
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
                str(tenant_id), db,
                customer_id=customer_id,
                repair_state=repair_state,
                severity=severity,
                page=page,
                size=size,
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
                str(tenant_id), body.model_dump(), db,
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
            result = await _repair_svc.get_case(case_id, str(tenant_id), db)
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
            result = await _repair_svc.update_case_state(
                case_id, str(tenant_id), body.model_dump(), db,
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
            result = await _repair_svc.update_compensation(
                case_id, str(tenant_id), body.model_dump(), db,
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
                str(tenant_id), db,
                customer_id=customer_id,
                suggestion_type=suggestion_type,
                review_state=review_state,
                page=page,
                size=size,
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
                str(tenant_id), body.model_dump(), db,
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
            result = await _suggestion_svc.get_suggestion(suggestion_id, str(tenant_id), db)
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
            result = await _suggestion_svc.review_suggestion(
                suggestion_id, str(tenant_id), body.model_dump(), db,
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
                suggestion_id, str(tenant_id), db,
            )
            await db.commit()
            return ok(result)
        except ValueError as exc:
            return err(str(exc))
