"""高风险操作 Plan Mode API

端点：
  POST /api/v1/operation-plans                    提交操作（返回 plan 或 needs_plan=false）
  GET  /api/v1/operation-plans/pending            查看待确认列表
  GET  /api/v1/operation-plans/{plan_id}          查看单个计划详情
  POST /api/v1/operation-plans/{plan_id}/confirm  确认执行
  POST /api/v1/operation-plans/{plan_id}/cancel   取消
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/operation-plans", tags=["operation-plans"])


# ── Request Models ──────────────────────────────────────────────────────────────

class SubmitOperationRequest(BaseModel):
    operation_type: str = Field(..., description="操作类型，如 menu.price.bulk_update")
    params: dict[str, Any] = Field(default_factory=dict, description="操作参数")
    operator_id: str = Field(..., description="操作发起人 ID（UUID）")


class ConfirmRequest(BaseModel):
    operator_id: str = Field(..., description="确认人 ID（UUID）")


class CancelRequest(BaseModel):
    operator_id: str = Field(..., description="取消人 ID（UUID）")


# ── Response Models ─────────────────────────────────────────────────────────────

class ImpactAnalysisOut(BaseModel):
    affected_stores: int
    affected_employees: int
    affected_members: int
    financial_impact_fen: int
    risk_level: str
    impact_summary: str
    warnings: list[str]
    reversible: bool


class OperationPlanOut(BaseModel):
    plan_id: str
    tenant_id: str
    operation_type: str
    operation_params: dict[str, Any]
    impact: ImpactAnalysisOut
    status: str
    operator_id: str
    confirmed_by: Optional[str]
    confirmed_at: Optional[datetime]
    executed_at: Optional[datetime]
    created_at: datetime
    expires_at: Optional[datetime]


class SubmitResponse(BaseModel):
    needs_plan: bool
    plan: Optional[OperationPlanOut] = None


# ── Helper ──────────────────────────────────────────────────────────────────────

def _plan_to_out(plan: Any) -> OperationPlanOut:
    """将 OperationPlan dataclass 转换为 Pydantic 输出模型"""
    impact = plan.impact
    return OperationPlanOut(
        plan_id=plan.plan_id,
        tenant_id=plan.tenant_id,
        operation_type=plan.operation_type,
        operation_params=plan.operation_params,
        impact=ImpactAnalysisOut(
            affected_stores=impact.affected_stores,
            affected_employees=impact.affected_employees,
            affected_members=impact.affected_members,
            financial_impact_fen=impact.financial_impact_fen,
            risk_level=impact.risk_level.value,
            impact_summary=impact.impact_summary,
            warnings=impact.warnings,
            reversible=impact.reversible,
        ),
        status=plan.status.value,
        operator_id=plan.operator_id,
        confirmed_by=plan.confirmed_by,
        confirmed_at=plan.confirmed_at,
        executed_at=plan.executed_at,
        created_at=plan.created_at,
        expires_at=plan.expires_at,
    )


async def _get_db_for_tenant(
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
) -> AsyncSession:
    """FastAPI 依赖：从 X-Tenant-ID header 提取租户 ID，返回带 RLS 隔离的 DB session。"""
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _get_planner(db: AsyncSession) -> Any:
    """获取 OperationPlanner 实例，注入 DB session。"""
    from ..services.model_router import ModelRouter
    from ..services.operation_planner import OperationPlanner

    try:
        router_instance = ModelRouter()
    except ValueError:
        router_instance = None
    return OperationPlanner(model_router=router_instance, db=db)


# ── Endpoints ───────────────────────────────────────────────────────────────────

@router.post("", response_model=dict)
async def submit_operation(
    req: SubmitOperationRequest,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_for_tenant),
) -> dict[str, Any]:
    """提交高风险操作请求。

    - 若操作未达到 Plan Mode 触发阈值，返回 `{"ok": true, "data": {"needs_plan": false}}`
    - 若触发 Plan Mode，返回含影响分析的操作计划，等待人工确认
    """
    planner = _get_planner(db)

    plan = await planner.submit(
        operation_type=req.operation_type,
        params=req.params,
        operator_id=req.operator_id,
        tenant_id=x_tenant_id,
    )

    if plan is None:
        return {"ok": True, "data": {"needs_plan": False}, "error": None}

    return {
        "ok": True,
        "data": {
            "needs_plan": True,
            "plan": _plan_to_out(plan).model_dump(),
        },
        "error": None,
    }


@router.get("/pending", response_model=dict)
async def list_pending_plans(
    operator_id: Optional[str] = None,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_for_tenant),
) -> dict[str, Any]:
    """查看当前租户的待确认操作计划列表。

    可选 query param `operator_id` 过滤指定发起人的计划。
    """
    planner = _get_planner(db)
    plans = await planner.get_pending_plans(tenant_id=x_tenant_id, operator_id=operator_id)
    items = [_plan_to_out(p).model_dump() for p in plans]
    return {"ok": True, "data": {"items": items, "total": len(items)}, "error": None}


@router.get("/{plan_id}", response_model=dict)
async def get_plan(
    plan_id: str,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_for_tenant),
) -> dict[str, Any]:
    """查看单个操作计划详情"""
    planner = _get_planner(db)
    plan = await planner.get_plan(plan_id)

    if plan is None:
        raise HTTPException(status_code=404, detail="操作计划不存在")

    if plan.tenant_id != x_tenant_id:
        raise HTTPException(status_code=403, detail="无权访问此操作计划")

    return {"ok": True, "data": _plan_to_out(plan).model_dump(), "error": None}


@router.post("/{plan_id}/confirm", response_model=dict)
async def confirm_plan(
    plan_id: str,
    req: ConfirmRequest,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_for_tenant),
) -> dict[str, Any]:
    """确认执行操作计划。

    计划状态须为 pending_confirm 且未超时，否则返回 400。
    """
    planner = _get_planner(db)

    plan = await planner.get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="操作计划不存在")
    if plan.tenant_id != x_tenant_id:
        raise HTTPException(status_code=403, detail="无权访问此操作计划")

    confirmed = await planner.confirm(plan_id=plan_id, operator_id=req.operator_id)
    if not confirmed:
        return {
            "ok": False,
            "data": None,
            "error": {"message": "确认失败：计划已过期、已取消或状态不允许确认"},
        }

    updated_plan = await planner.get_plan(plan_id)
    return {
        "ok": True,
        "data": _plan_to_out(updated_plan).model_dump(),
        "error": None,
    }


@router.post("/{plan_id}/cancel", response_model=dict)
async def cancel_plan(
    plan_id: str,
    req: CancelRequest,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_for_tenant),
) -> dict[str, Any]:
    """取消操作计划。

    计划状态须为 pending_confirm，否则返回 400。
    """
    planner = _get_planner(db)

    plan = await planner.get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="操作计划不存在")
    if plan.tenant_id != x_tenant_id:
        raise HTTPException(status_code=403, detail="无权访问此操作计划")

    cancelled = await planner.cancel(plan_id=plan_id, operator_id=req.operator_id)
    if not cancelled:
        return {
            "ok": False,
            "data": None,
            "error": {"message": "取消失败：计划状态不允许取消"},
        }

    updated_plan = await planner.get_plan(plan_id)
    return {
        "ok": True,
        "data": _plan_to_out(updated_plan).model_dump(),
        "error": None,
    }
