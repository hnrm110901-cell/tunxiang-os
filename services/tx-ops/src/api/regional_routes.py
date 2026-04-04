"""E8 区域追踪与整改 API 路由 — 7 个端点

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/regional", tags=["regional"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class DispatchRectificationRequest(BaseModel):
    store_id: str
    issue_id: str
    assignee_id: str
    deadline: str = Field(..., description="YYYY-MM-DD")


class TrackRectificationRequest(BaseModel):
    new_status: str = Field(..., description="in_progress / submitted")
    note: str = ""


class SubmitReviewRequest(BaseModel):
    reviewer_id: str
    result: str = Field(..., pattern="^(pass|fail)$")
    comment: str = ""


class BenchmarkRequest(BaseModel):
    metric: str


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. 派发整改
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/regions/{region_id}/rectifications")
async def dispatch_rectification(
    region_id: str,
    body: DispatchRectificationRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """E8: 派发区域整改任务"""
    from ..services.regional_management import dispatch_rectification as svc

    try:
        result = await svc(
            region_id, body.store_id, body.issue_id,
            body.assignee_id, body.deadline, x_tenant_id, db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. 进度跟踪
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.put("/rectifications/{rectification_id}/track")
async def track_rectification(
    rectification_id: str,
    body: TrackRectificationRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """E8: 更新整改进度"""
    from ..services.regional_management import track_rectification as svc

    try:
        result = await svc(
            rectification_id, x_tenant_id, db=db,
            new_status=body.new_status, note=body.note,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. 复查记录
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/rectifications/{rectification_id}/review")
async def submit_review(
    rectification_id: str,
    body: SubmitReviewRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """E8: 提交整改复查"""
    from ..services.regional_management import submit_review as svc

    try:
        result = await svc(
            rectification_id, body.reviewer_id, body.result,
            x_tenant_id, db=db, comment=body.comment,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. 评分卡
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/regions/{region_id}/scorecard")
async def get_regional_scorecard(
    region_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """E8: 区域红黄绿评分卡"""
    from ..services.regional_management import get_regional_scorecard as svc

    result = await svc(region_id, x_tenant_id, db=db)
    return {"ok": True, "data": result}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. 跨店对标
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/regions/{region_id}/benchmark")
async def cross_store_benchmark(
    region_id: str,
    metric: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """E8: 跨店对标"""
    from ..services.regional_management import cross_store_benchmark as svc

    result = await svc(metric, region_id, x_tenant_id, db=db)
    return {"ok": True, "data": result}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  6. 区域月报
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/regions/{region_id}/report/{month}")
async def generate_regional_report(
    region_id: str,
    month: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """E8: 区域月报"""
    from ..services.regional_management import generate_regional_report as svc

    result = await svc(region_id, month, x_tenant_id, db=db)
    return {"ok": True, "data": result}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  7. 整改归档
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/regions/{region_id}/archive")
async def get_rectification_archive(
    region_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """E8: 整改归档"""
    from ..services.regional_management import get_rectification_archive as svc

    result = await svc(region_id, x_tenant_id, db=db)
    return {"ok": True, "data": result}
