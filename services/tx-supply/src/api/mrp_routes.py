"""MRP智能预估 API 路由

端点：
  POST /plans                                  - 创建预估计划
  GET  /plans                                  - 计划列表
  GET  /plans/{plan_id}                        - 计划详情
  POST /plans/{plan_id}/calculate              - 执行需求计算
  POST /plans/{plan_id}/generate-production    - 生成生产建议
  POST /plans/{plan_id}/generate-procurement   - 生成采购建议
  POST /plans/{plan_id}/approve                - 审批计划
  GET  /plans/{plan_id}/demand-lines           - 需求行列表
  GET  /plans/{plan_id}/production-suggestions - 生产建议列表
  GET  /plans/{plan_id}/procurement-suggestions- 采购建议列表
  POST /procurement/convert-to-po              - 转采购订单
  POST /production/convert-to-task             - 转生产任务
  POST /material-issue/plan                    - 生成领料单
  POST /material-issue/execute                 - 执行领料
  GET  /plans/{plan_id}/variance               - 差异报告
  GET  /plans/{plan_id}/summary                - 计划总览

统一响应格式: {"ok": bool, "data": {}, "error": {}}

# ROUTER REGISTRATION:
# from .api.mrp_routes import router as mrp_router
# app.include_router(mrp_router, prefix="/api/v1/supply/mrp")
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from shared.ontology.src.database import get_db as _get_db

router = APIRouter(tags=["mrp"])


# ─── 请求模型 ───


class CreatePlanRequest(BaseModel):
    plan_name: str = Field(..., min_length=1, max_length=200, description="计划名称")
    plan_type: str = Field(
        default="demand_driven",
        pattern="^(demand_driven|manual|hybrid)$",
        description="计划类型: demand_driven | manual | hybrid",
    )
    store_id: Optional[str] = Field(default=None, description="门店ID(null=集团级别)")
    forecast_date_from: date = Field(..., description="预测起始日期")
    forecast_date_to: date = Field(..., description="预测结束日期")
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="计划参数: lookback_days, safety_stock_multiplier, lead_time_days, min_order_qty_enabled",
    )


class ApprovePlanRequest(BaseModel):
    approved_by: str = Field(..., description="审批人ID")


class ConvertToPORequest(BaseModel):
    plan_id: str = Field(..., description="计划ID")
    suggestion_ids: List[str] = Field(..., min_length=1, description="采购建议ID列表")


class ConvertToTaskRequest(BaseModel):
    plan_id: str = Field(..., description="计划ID")
    suggestion_ids: List[str] = Field(..., min_length=1, description="生产建议ID列表")


class PlanMaterialIssueRequest(BaseModel):
    production_suggestion_id: str = Field(..., description="生产建议ID")


class ExecuteMaterialIssueRequest(BaseModel):
    planned_issue_id: str = Field(..., description="领料单ID")
    actual_qty: float = Field(..., ge=0, description="实际领料量")
    issued_by: str = Field(..., description="领料人ID")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  POST /plans — 创建预估计划
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/plans")
async def create_plan(
    body: CreatePlanRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_user_id: str = Header(..., alias="X-User-ID"),
    db=Depends(_get_db),
):
    """创建MRP预估计划。

    支持三种计划类型：
    - demand_driven: 基于销售预测自动计算
    - manual: 手动填写需求
    - hybrid: 自动+手动混合

    Returns:
        {"ok": true, "data": MRPPlanInfo}
    """
    from ..services.mrp_engine_service import MRPEngineService, MRPPlanCreate

    svc = MRPEngineService()
    try:
        plan_data = MRPPlanCreate(
            plan_name=body.plan_name,
            plan_type=body.plan_type,
            store_id=body.store_id,
            forecast_date_from=body.forecast_date_from,
            forecast_date_to=body.forecast_date_to,
            parameters=body.parameters,
        )
        result = await svc.create_forecast_plan(
            tenant_id=x_tenant_id,
            created_by=x_user_id,
            plan_data=plan_data,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"ok": True, "data": result.model_dump()}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /plans — 计划列表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/plans")
async def list_plans(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    store_id: Optional[str] = Query(default=None, description="门店ID筛选"),
    status: Optional[str] = Query(default=None, description="状态筛选"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db=Depends(_get_db),
):
    """查询MRP计划列表（分页）。

    Returns:
        {"ok": true, "data": {"items": [...], "total": int}}
    """
    from ..services.mrp_engine_service import MRPEngineService

    svc = MRPEngineService()
    try:
        result = await svc.list_plans(
            tenant_id=x_tenant_id,
            db=db,
            store_id=store_id,
            status=status,
            page=page,
            size=size,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"ok": True, "data": result}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /plans/{plan_id} — 计划详情
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/plans/{plan_id}")
async def get_plan(
    plan_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db=Depends(_get_db),
):
    """查询MRP计划详情。

    Returns:
        {"ok": true, "data": MRPPlanInfo}
    """
    from ..services.mrp_engine_service import MRPEngineService

    svc = MRPEngineService()
    try:
        result = await svc.get_plan(
            tenant_id=x_tenant_id,
            plan_id=plan_id,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {"ok": True, "data": result.model_dump()}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  POST /plans/{plan_id}/calculate — 执行需求计算
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/plans/{plan_id}/calculate")
async def calculate_demand(
    plan_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db=Depends(_get_db),
):
    """执行需求计算。

    流程：销售预测 → BOM展开 → 净需求计算 → 生成需求行。
    计划状态 draft → calculating → calculated。

    Returns:
        {"ok": true, "data": {"demand_lines_count": int, "demand_lines": [...]}}
    """
    from ..services.mrp_engine_service import MRPEngineService

    svc = MRPEngineService()
    try:
        demand_lines = await svc.calculate_demand(
            tenant_id=x_tenant_id,
            plan_id=plan_id,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "ok": True,
        "data": {
            "demand_lines_count": len(demand_lines),
            "demand_lines": [dl.model_dump() for dl in demand_lines],
        },
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  POST /plans/{plan_id}/generate-production — 生成生产建议
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/plans/{plan_id}/generate-production")
async def generate_production(
    plan_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db=Depends(_get_db),
):
    """生成生产建议。

    筛选自制半成品（有BOM且为自产），按BOM计算生产数量，按交期排序优先级。

    Returns:
        {"ok": true, "data": {"suggestions_count": int, "suggestions": [...]}}
    """
    from ..services.mrp_engine_service import MRPEngineService

    svc = MRPEngineService()
    try:
        suggestions = await svc.generate_production_plan(
            tenant_id=x_tenant_id,
            plan_id=plan_id,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "ok": True,
        "data": {
            "suggestions_count": len(suggestions),
            "suggestions": [s.model_dump() for s in suggestions],
        },
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  POST /plans/{plan_id}/generate-procurement — 生成采购建议
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/plans/{plan_id}/generate-procurement")
async def generate_procurement(
    plan_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db=Depends(_get_db),
):
    """生成采购建议。

    筛选需要外购的原料，匹配供应商（按评分优先），考虑MOQ和前置时间，估算采购金额。

    Returns:
        {"ok": true, "data": {"suggestions_count": int, "total_estimated_cost_fen": int, "suggestions": [...]}}
    """
    from ..services.mrp_engine_service import MRPEngineService

    svc = MRPEngineService()
    try:
        suggestions = await svc.generate_procurement_plan(
            tenant_id=x_tenant_id,
            plan_id=plan_id,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    total_cost = sum(s.estimated_cost_fen for s in suggestions)
    return {
        "ok": True,
        "data": {
            "suggestions_count": len(suggestions),
            "total_estimated_cost_fen": total_cost,
            "suggestions": [s.model_dump() for s in suggestions],
        },
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  POST /plans/{plan_id}/approve — 审批计划
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/plans/{plan_id}/approve")
async def approve_plan(
    plan_id: str,
    body: ApprovePlanRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db=Depends(_get_db),
):
    """审批MRP计划。

    同步审批所有 suggested 状态的生产建议和采购建议。

    Returns:
        {"ok": true, "data": MRPPlanInfo}
    """
    from ..services.mrp_engine_service import MRPEngineService

    svc = MRPEngineService()
    try:
        result = await svc.approve_plan(
            tenant_id=x_tenant_id,
            plan_id=plan_id,
            approved_by=body.approved_by,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"ok": True, "data": result.model_dump()}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /plans/{plan_id}/demand-lines — 需求行列表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/plans/{plan_id}/demand-lines")
async def get_demand_lines(
    plan_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    db=Depends(_get_db),
):
    """查询需求行列表（分页，按净需求量降序）。

    Returns:
        {"ok": true, "data": {"items": [...], "total": int}}
    """
    from ..services.mrp_engine_service import MRPEngineService

    svc = MRPEngineService()
    try:
        result = await svc.get_demand_lines(
            tenant_id=x_tenant_id,
            plan_id=plan_id,
            db=db,
            page=page,
            size=size,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"ok": True, "data": result}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /plans/{plan_id}/production-suggestions — 生产建议列表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/plans/{plan_id}/production-suggestions")
async def get_production_suggestions(
    plan_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    db=Depends(_get_db),
):
    """查询生产建议列表（按优先级+交期排序）。

    Returns:
        {"ok": true, "data": {"items": [...], "total": int}}
    """
    from ..services.mrp_engine_service import MRPEngineService

    svc = MRPEngineService()
    try:
        result = await svc.get_production_suggestions(
            tenant_id=x_tenant_id,
            plan_id=plan_id,
            db=db,
            page=page,
            size=size,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"ok": True, "data": result}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /plans/{plan_id}/procurement-suggestions — 采购建议列表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/plans/{plan_id}/procurement-suggestions")
async def get_procurement_suggestions(
    plan_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    db=Depends(_get_db),
):
    """查询采购建议列表（按估算金额降序）。

    Returns:
        {"ok": true, "data": {"items": [...], "total": int}}
    """
    from ..services.mrp_engine_service import MRPEngineService

    svc = MRPEngineService()
    try:
        result = await svc.get_procurement_suggestions(
            tenant_id=x_tenant_id,
            plan_id=plan_id,
            db=db,
            page=page,
            size=size,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"ok": True, "data": result}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  POST /procurement/convert-to-po — 转采购订单
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/procurement/convert-to-po")
async def convert_to_purchase_orders(
    body: ConvertToPORequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db=Depends(_get_db),
):
    """将采购建议转为采购订单。

    按供应商分组自动创建 draft 采购订单。

    Returns:
        {"ok": true, "data": {"orders_count": int, "orders": [...]}}
    """
    from ..services.mrp_engine_service import MRPEngineService

    svc = MRPEngineService()
    try:
        orders = await svc.convert_to_purchase_orders(
            tenant_id=x_tenant_id,
            plan_id=body.plan_id,
            suggestion_ids=body.suggestion_ids,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "ok": True,
        "data": {
            "orders_count": len(orders),
            "orders": orders,
        },
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  POST /production/convert-to-task — 转生产任务
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/production/convert-to-task")
async def convert_to_production_tasks(
    body: ConvertToTaskRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db=Depends(_get_db),
):
    """将生产建议转为生产任务。

    Returns:
        {"ok": true, "data": {"tasks_count": int, "tasks": [...]}}
    """
    from ..services.mrp_engine_service import MRPEngineService

    svc = MRPEngineService()
    try:
        tasks = await svc.convert_to_production_tasks(
            tenant_id=x_tenant_id,
            plan_id=body.plan_id,
            suggestion_ids=body.suggestion_ids,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "ok": True,
        "data": {
            "tasks_count": len(tasks),
            "tasks": tasks,
        },
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  POST /material-issue/plan — 生成领料单
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/material-issue/plan")
async def plan_material_issue(
    body: PlanMaterialIssueRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db=Depends(_get_db),
):
    """根据生产建议生成按计划领料单。

    从BOM展开所需原料，生成领料明细。

    Returns:
        {"ok": true, "data": {"issues_count": int, "issues": [...]}}
    """
    from ..services.mrp_engine_service import MRPEngineService

    svc = MRPEngineService()
    try:
        issues = await svc.plan_material_issue(
            tenant_id=x_tenant_id,
            production_suggestion_id=body.production_suggestion_id,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "ok": True,
        "data": {
            "issues_count": len(issues),
            "issues": [i.model_dump() for i in issues],
        },
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  POST /material-issue/execute — 执行领料
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/material-issue/execute")
async def execute_material_issue(
    body: ExecuteMaterialIssueRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db=Depends(_get_db),
):
    """执行领料，记录实际领料量并计算差异。

    Returns:
        {"ok": true, "data": PlannedIssueInfo}
    """
    from ..services.mrp_engine_service import MRPEngineService

    svc = MRPEngineService()
    try:
        result = await svc.execute_material_issue(
            tenant_id=x_tenant_id,
            planned_issue_id=body.planned_issue_id,
            actual_qty=body.actual_qty,
            issued_by=body.issued_by,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"ok": True, "data": result.model_dump()}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /plans/{plan_id}/variance — 差异报告
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/plans/{plan_id}/variance")
async def get_variance_report(
    plan_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db=Depends(_get_db),
):
    """计划vs实际差异报告。

    统计所有已执行领料的计划量vs实际量差异，按差异绝对值降序排列。

    Returns:
        {"ok": true, "data": VarianceReport}
    """
    from ..services.mrp_engine_service import MRPEngineService

    svc = MRPEngineService()
    try:
        result = await svc.get_variance_report(
            tenant_id=x_tenant_id,
            plan_id=plan_id,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"ok": True, "data": result.model_dump()}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /plans/{plan_id}/summary — 计划总览
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/plans/{plan_id}/summary")
async def get_plan_summary(
    plan_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db=Depends(_get_db),
):
    """计划总览：需求/生产/采购/领料汇总。

    Returns:
        {"ok": true, "data": PlanSummary}
    """
    from ..services.mrp_engine_service import MRPEngineService

    svc = MRPEngineService()
    try:
        result = await svc.get_plan_summary(
            tenant_id=x_tenant_id,
            plan_id=plan_id,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"ok": True, "data": result.model_dump()}
