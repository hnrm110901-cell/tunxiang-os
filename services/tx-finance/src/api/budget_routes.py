"""预算管理 API — 8 个端点（v101）

端点：
1. POST   /api/v1/finance/budgets              创建/更新预算计划（UPSERT）
2. GET    /api/v1/finance/budgets              预算计划列表
3. GET    /api/v1/finance/budgets/{id}         预算计划详情
4. POST   /api/v1/finance/budgets/{id}/approve 审批预算计划
5. POST   /api/v1/finance/budgets/{id}/execute 录入实际执行金额
6. GET    /api/v1/finance/budgets/{id}/progress 执行进度（最新快照）
7. GET    /api/v1/finance/budgets/summary      门店期间预算汇总
8. GET    /api/v1/finance/budgets/categories   查看支持的科目列表
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.budget_service import (
    VALID_CATEGORIES,
    VALID_PERIOD_TYPES,
    VALID_STATUSES,
    BudgetService,
)

router = APIRouter(prefix="/api/v1/finance/budgets", tags=["budget_management"])


# ─── DB 依赖 ──────────────────────────────────────────────────────────────────


async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ─── 请求模型 ─────────────────────────────────────────────────────────────────


class UpsertBudgetRequest(BaseModel):
    store_id: str = Field(..., description="门店 ID")
    period_type: str = Field(..., description="期间类型: monthly/quarterly/yearly")
    period: str = Field(..., description="期间值，monthly=YYYY-MM，quarterly=YYYY-Qn，yearly=YYYY")
    category: str = Field(..., description="科目: revenue/ingredient_cost/labor_cost/fixed_cost/marketing_cost/total")
    budget_fen: int = Field(..., ge=0, description="预算金额（分）")
    note: Optional[str] = Field(None, max_length=500, description="备注")
    created_by: Optional[str] = Field(None, description="创建人员工 ID")

    @field_validator("period_type")
    @classmethod
    def check_period_type(cls, v: str) -> str:
        if v not in VALID_PERIOD_TYPES:
            raise ValueError(f"period_type 必须是: {', '.join(VALID_PERIOD_TYPES)}")
        return v

    @field_validator("category")
    @classmethod
    def check_category(cls, v: str) -> str:
        if v not in VALID_CATEGORIES:
            raise ValueError(f"category 必须是: {', '.join(VALID_CATEGORIES)}")
        return v


class ApproveRequest(BaseModel):
    approved_by: str = Field(..., description="审批人员工 ID")


class RecordExecutionRequest(BaseModel):
    actual_fen: int = Field(..., ge=0, description="实际执行金额（分）")
    tracked_at: Optional[str] = Field(None, description="执行日期 YYYY-MM-DD，默认今日")
    note: Optional[str] = Field(None, max_length=500, description="备注")


# ─── 1. 创建/更新预算计划 ─────────────────────────────────────────────────────


@router.post("", summary="创建或更新预算计划", status_code=201)
async def upsert_budget(
    body: UpsertBudgetRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """创建门店预算计划，同一(门店+期间+科目)唯一，重复提交则更新金额。

    - period 格式: monthly=2026-04, quarterly=2026-Q2, yearly=2026
    """
    svc = BudgetService(db, x_tenant_id)
    try:
        plan = await svc.upsert_plan(
            store_id=body.store_id,
            period_type=body.period_type,
            period=body.period,
            category=body.category,
            budget_fen=body.budget_fen,
            note=body.note,
            created_by=body.created_by,
        )
        await db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "data": plan}


# ─── 2. 查询预算计划列表 ──────────────────────────────────────────────────────


@router.get("", summary="预算计划列表")
async def list_budgets(
    store_id: Optional[str] = Query(None, description="按门店过滤"),
    period_type: Optional[str] = Query(None, description="按期间类型过滤"),
    period: Optional[str] = Query(None, description="按期间值过滤"),
    category: Optional[str] = Query(None, description="按科目过滤"),
    status: Optional[str] = Query(None, description="按状态过滤: draft/approved/locked"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """查询预算计划列表，支持多维过滤。"""
    svc = BudgetService(db, x_tenant_id)
    plans = await svc.list_plans(
        store_id=store_id,
        period_type=period_type,
        period=period,
        category=category,
        status=status,
    )
    return {"ok": True, "data": {"items": plans, "total": len(plans)}}


# ─── 3. 预算计划详情 ──────────────────────────────────────────────────────────


@router.get("/{plan_id}", summary="预算计划详情")
async def get_budget(
    plan_id: str = Path(..., description="预算计划 ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """获取单个预算计划详情。"""
    svc = BudgetService(db, x_tenant_id)
    plan = await svc.get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail=f"预算计划不存在: {plan_id}")
    return {"ok": True, "data": plan}


# ─── 4. 审批预算计划 ──────────────────────────────────────────────────────────


@router.post("/{plan_id}/approve", summary="审批预算计划")
async def approve_budget(
    plan_id: str = Path(..., description="预算计划 ID"),
    body: ApproveRequest = ...,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """将 draft 状态预算计划审批为 approved。审批后不可再修改金额。"""
    svc = BudgetService(db, x_tenant_id)
    try:
        plan = await svc.approve_plan(plan_id, body.approved_by)
        await db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "data": plan}


# ─── 5. 录入执行金额 ──────────────────────────────────────────────────────────


@router.post("/{plan_id}/execute", summary="录入实际执行金额")
async def record_execution(
    plan_id: str = Path(..., description="预算计划 ID"),
    body: RecordExecutionRequest = ...,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """录入实际执行金额，计算差异并追加写入 budget_executions。

    - 可多次调用（追加历史，不覆盖）
    - variance_fen > 0 = 超支；< 0 = 节约
    """
    svc = BudgetService(db, x_tenant_id)
    try:
        result = await svc.record_execution(
            plan_id=plan_id,
            actual_fen=body.actual_fen,
            tracked_at=body.tracked_at,
            note=body.note,
        )
        await db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "data": result}


# ─── 6. 执行进度 ──────────────────────────────────────────────────────────────


@router.get("/{plan_id}/progress", summary="预算执行进度")
async def get_execution_progress(
    plan_id: str = Path(..., description="预算计划 ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """返回最新一次执行快照：预算 vs 实际 vs 差异 vs 完成率。"""
    svc = BudgetService(db, x_tenant_id)
    try:
        progress = await svc.get_execution_progress(plan_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True, "data": progress}


# ─── 7. 门店期间汇总 ──────────────────────────────────────────────────────────


@router.get("/summary", summary="门店期间预算汇总")
async def get_budget_summary(
    store_id: str = Query(..., description="门店 ID"),
    period_type: str = Query(..., description="期间类型: monthly/quarterly/yearly"),
    period: str = Query(..., description="期间值"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """获取门店指定期间所有科目的预算执行汇总表。

    包含：各科目预算/实际/差异/完成率 + 总计。
    """
    svc = BudgetService(db, x_tenant_id)
    summary = await svc.get_store_budget_summary(
        store_id=store_id,
        period_type=period_type,
        period=period,
    )
    return {"ok": True, "data": summary}


# ─── 8. 科目列表 ──────────────────────────────────────────────────────────────


@router.get("/categories", summary="支持的预算科目列表")
async def list_categories(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """返回系统支持的预算科目和期间类型。"""
    return {
        "ok": True,
        "data": {
            "categories": list(VALID_CATEGORIES),
            "period_types": list(VALID_PERIOD_TYPES),
            "statuses": list(VALID_STATUSES),
        },
    }
