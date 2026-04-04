"""D8 复盘与经营改进中心 — API 端点

10 个端点覆盖周/月复盘、问题追踪、知识库。
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from ..services import (
    issue_tracker,
    knowledge_base,
    monthly_review,
    weekly_review,
)

router = APIRouter(prefix="/api/v1/review", tags=["D8-复盘经营改进"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Request / Response Models
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class WeeklyReviewRequest(BaseModel):
    store_id: str
    week_start: str = Field(..., description="周一日期 YYYY-MM-DD")


class MonthlyReviewRequest(BaseModel):
    store_id: str
    month: str = Field(..., description="月份 YYYY-MM")


class RegionalReviewRequest(BaseModel):
    region_id: str
    month: str


class CreateIssueRequest(BaseModel):
    store_id: str
    type: str
    description: str
    reporter_id: str
    priority: str = "medium"
    deadline: Optional[str] = None


class AssignIssueRequest(BaseModel):
    issue_id: str
    assignee_id: str
    deadline: str


class UpdateIssueStatusRequest(BaseModel):
    issue_id: str
    status: str
    notes: str


class SaveCaseRequest(BaseModel):
    store_id: str
    case_data: Dict[str, Any]


class SearchCaseRequest(BaseModel):
    keyword: str
    category: Optional[str] = None


class ApiResponse(BaseModel):
    ok: bool = True
    data: Dict[str, Any] = {}
    error: Optional[Dict[str, Any]] = None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. 周度复盘
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/weekly", response_model=ApiResponse)
async def create_weekly_review(
    req: WeeklyReviewRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """生成周度复盘报告。"""
    try:
        week_start = date.fromisoformat(req.week_start)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid week_start: {exc}") from exc

    result = await weekly_review.generate_weekly_review(
        store_id=req.store_id,
        week_start=week_start,
        tenant_id=x_tenant_id,
        db=db,
    )
    return ApiResponse(data=result)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. 月度复盘
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/monthly", response_model=ApiResponse)
async def create_monthly_review(
    req: MonthlyReviewRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """生成月度复盘报告。"""
    result = await monthly_review.generate_monthly_review(
        store_id=req.store_id,
        month=req.month,
        tenant_id=x_tenant_id,
        db=db,
    )
    return ApiResponse(data=result)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. 区域月度汇总
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/regional", response_model=ApiResponse)
async def create_regional_review(
    req: RegionalReviewRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """生成区域月度汇总报告。"""
    result = await monthly_review.generate_regional_review(
        region_id=req.region_id,
        month=req.month,
        tenant_id=x_tenant_id,
        db=db,
    )
    return ApiResponse(data=result)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. 创建问题
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/issues", response_model=ApiResponse)
async def create_issue(
    req: CreateIssueRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """创建门店问题。"""
    result = await issue_tracker.create_issue(
        store_id=req.store_id,
        issue_type=req.type,
        description=req.description,
        reporter_id=req.reporter_id,
        tenant_id=x_tenant_id,
        db=db,
        priority=req.priority,
        deadline=req.deadline,
    )
    return ApiResponse(data=result)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. 派发问题
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/issues/assign", response_model=ApiResponse)
async def assign_issue(
    req: AssignIssueRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """派发问题给责任人。"""
    result = await issue_tracker.assign_issue(
        issue_id=req.issue_id,
        assignee_id=req.assignee_id,
        deadline=req.deadline,
        tenant_id=x_tenant_id,
        db=db,
    )
    return ApiResponse(data=result)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  6. 更新问题状态
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.put("/issues/status", response_model=ApiResponse)
async def update_issue_status(
    req: UpdateIssueStatusRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """更新问题状态。"""
    result = await issue_tracker.update_issue_status(
        issue_id=req.issue_id,
        status=req.status,
        notes=req.notes,
        tenant_id=x_tenant_id,
        db=db,
    )
    return ApiResponse(data=result)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  7. 门店问题看板
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/issues/board/{store_id}", response_model=ApiResponse)
async def get_issue_board(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """获取门店问题红黄绿看板。"""
    result = await issue_tracker.get_store_issue_board(
        store_id=store_id,
        tenant_id=x_tenant_id,
        db=db,
    )
    return ApiResponse(data=result)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  8. 保存案例
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/cases", response_model=ApiResponse)
async def save_case(
    req: SaveCaseRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """沉淀经营案例。"""
    result = await knowledge_base.save_case(
        store_id=req.store_id,
        case_data=req.case_data,
        tenant_id=x_tenant_id,
        db=db,
    )
    return ApiResponse(data=result)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  9. 搜索案例
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/cases/search", response_model=ApiResponse)
async def search_cases(
    req: SearchCaseRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """搜索案例库。"""
    result = await knowledge_base.search_cases(
        keyword=req.keyword,
        tenant_id=x_tenant_id,
        db=db,
        category=req.category,
    )
    return ApiResponse(data=result)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  10. SOP 建议
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/sop/{store_id}/{issue_type}", response_model=ApiResponse)
async def get_sop_suggestions(
    store_id: str,
    issue_type: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """获取 SOP 优化建议。"""
    result = await knowledge_base.get_sop_suggestions(
        store_id=store_id,
        issue_type=issue_type,
        tenant_id=x_tenant_id,
        db=db,
    )
    return ApiResponse(data=result)
