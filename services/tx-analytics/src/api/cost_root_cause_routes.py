"""成本根因分析 API 路由

# ROUTER REGISTRATION (在 tx-analytics/src/main.py 中添加):
# from .api.cost_root_cause_routes import router as cost_root_cause_router
# app.include_router(cost_root_cause_router)

端点清单：
  GET  /api/v1/cost-analysis/{store_id}/root-cause                全面根因分析
  GET  /api/v1/cost-analysis/{store_id}/root-cause/category       品类归因明细
  GET  /api/v1/cost-analysis/{store_id}/root-cause/supplier       供应商归因明细
  GET  /api/v1/cost-analysis/{store_id}/root-cause/recommendations 可执行建议
"""

import uuid
from datetime import date, timedelta
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.cost_root_cause_service import CostRootCauseService

logger = structlog.get_logger()
router = APIRouter(
    prefix="/api/v1/cost-analysis",
    tags=["cost-root-cause"],
)

_root_cause_service = CostRootCauseService()


# ── 依赖 ──────────────────────────────────────────────────────────────────────


async def _get_tenant_db(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> AsyncSession:
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _parse_tenant_id(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> uuid.UUID:
    try:
        return uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Tenant-ID 格式无效",
        )


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


def _parse_period(
    period_start: Optional[date],
    period_end: Optional[date],
) -> tuple[date, date]:
    """解析周期参数,默认最近30天"""
    if period_end is None:
        period_end = date.today()
    if period_start is None:
        period_start = period_end - timedelta(days=30)
    if period_start > period_end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="period_start 不能晚于 period_end",
        )
    return period_start, period_end


# ── 路由 ──────────────────────────────────────────────────────────────────────


@router.get("/{store_id}/root-cause")
async def analyze_root_cause(
    store_id: uuid.UUID,
    period_start: Optional[date] = Query(default=None, description="分析周期开始日期"),
    period_end: Optional[date] = Query(default=None, description="分析周期结束日期"),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict[str, Any]:
    """全面根因分析

    分析门店在指定周期内的成本超标原因。
    默认分析最近30天。

    返回:
    - summary: 摘要描述
    - root_causes: 根因列表(按影响金额降序)
    - recommendations: 可执行建议(按预估节省降序)
    """
    start, end = _parse_period(period_start, period_end)

    result = await _root_cause_service.analyze_root_cause(
        db=db,
        store_id=store_id,
        tenant_id=tenant_id,
        period_start=start,
        period_end=end,
    )
    return _ok(result)


@router.get("/{store_id}/root-cause/category")
async def get_category_detail(
    store_id: uuid.UUID,
    period_start: Optional[date] = Query(default=None, description="分析周期开始日期"),
    period_end: Optional[date] = Query(default=None, description="分析周期结束日期"),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict[str, Any]:
    """品类归因明细

    按食材品类(肉类/海鲜/蔬菜/调料)拆解成本变动,对比上一周期。
    """
    start, end = _parse_period(period_start, period_end)

    causes = await _root_cause_service.get_category_detail(
        db=db,
        store_id=store_id,
        tenant_id=tenant_id,
        period_start=start,
        period_end=end,
    )
    return _ok({"causes": causes, "count": len(causes)})


@router.get("/{store_id}/root-cause/supplier")
async def get_supplier_detail(
    store_id: uuid.UUID,
    period_start: Optional[date] = Query(default=None, description="分析周期开始日期"),
    period_end: Optional[date] = Query(default=None, description="分析周期结束日期"),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict[str, Any]:
    """供应商归因明细

    找出哪些供应商的采购价上涨导致成本超标。
    涨幅>10%的供应商+食材会被标红。
    """
    start, end = _parse_period(period_start, period_end)

    causes = await _root_cause_service.get_supplier_detail(
        db=db,
        store_id=store_id,
        tenant_id=tenant_id,
        period_start=start,
        period_end=end,
    )
    return _ok({"causes": causes, "count": len(causes)})


@router.get("/{store_id}/root-cause/recommendations")
async def get_recommendations(
    store_id: uuid.UUID,
    period_start: Optional[date] = Query(default=None, description="分析周期开始日期"),
    period_end: Optional[date] = Query(default=None, description="分析周期结束日期"),
    tenant_id: uuid.UUID = Depends(_parse_tenant_id),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict[str, Any]:
    """可执行建议

    基于根因分析结果生成具体的成本优化建议。
    每条建议含预估节省金额和优先级。
    """
    start, end = _parse_period(period_start, period_end)

    recommendations = await _root_cause_service.get_recommendations(
        db=db,
        store_id=store_id,
        tenant_id=tenant_id,
        period_start=start,
        period_end=end,
    )

    total_saving_fen = sum(
        r.get("expected_saving_fen", 0) for r in recommendations
    )

    return _ok({
        "recommendations": recommendations,
        "count": len(recommendations),
        "total_expected_saving_fen": total_saving_fen,
    })
