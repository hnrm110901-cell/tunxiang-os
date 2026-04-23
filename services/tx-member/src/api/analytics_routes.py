"""会员分析 API 端点 (D4)

5 个端点：增长分析、活跃度分析、复购分析、流失预警、偏好洞察
"""

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.member_analytics import (
    activity_analysis,
    churn_prediction,
    member_growth,
    preference_insight,
    repurchase_analysis,
)

router = APIRouter(prefix="/api/v1/member/analytics", tags=["member-analytics"])


# ── 请求/响应模型 ─────────────────────────────────────────────


class DateRangeParams(BaseModel):
    start_date: str  # YYYY-MM-DD
    end_date: str  # YYYY-MM-DD


# ── 1. 会员增长分析 ──────────────────────────────────────────


@router.get("/growth")
async def get_member_growth(
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """会员增长分析 — 新增、总量、增长率、渠道分布"""
    try:
        data = await member_growth(x_tenant_id, (start_date, end_date), db)
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ── 2. 活跃度分析 ─────────────────────────────────────────────


@router.get("/activity")
async def get_activity_analysis(
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """会员活跃度分析 — 活跃率、DAU、MAU、门店分布"""
    try:
        data = await activity_analysis(x_tenant_id, (start_date, end_date), db)
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ── 3. 复购分析 ───────────────────────────────────────────────


@router.get("/repurchase")
async def get_repurchase_analysis(
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """复购率分析 — 复购率、平均间隔天数、频次带分布"""
    try:
        data = await repurchase_analysis(x_tenant_id, (start_date, end_date), db)
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ── 4. 流失预警 ───────────────────────────────────────────────


@router.get("/churn-prediction")
async def get_churn_prediction(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """流失风险预测 — 按风险分排序的会员列表

    规则: >60天未消费=高风险, 30-60天=中风险
    """
    try:
        data = await churn_prediction(x_tenant_id, db)
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ── 5. 偏好洞察 ───────────────────────────────────────────────


@router.get("/preference/{customer_id}")
async def get_preference_insight(
    customer_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """单个会员偏好洞察 — 最爱菜品、到店时段、消费水平"""
    try:
        data = await preference_insight(customer_id, x_tenant_id, db)
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
