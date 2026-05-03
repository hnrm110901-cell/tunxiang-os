"""马来西亚 AI 业务洞察 API 端点 — Phase 3 Sprint 3.3

4 个端点：
  - GET  /api/v1/my/insights/waste-reduction     食材浪费减少建议
  - GET  /api/v1/my/insights/labour-optimization  人力排班优化
  - GET  /api/v1/my/insights/halal-compliance     Halal 合规检查
  - GET  /api/v1/my/insights/pricing              定价优化建议
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.ai_insights_service import AIInsightsService

router = APIRouter(prefix="/api/v1/my/insights", tags=["my-insights"])


# ── DI ──────────────────────────────────────────────────────────


async def get_insights_service() -> AIInsightsService:
    return AIInsightsService()


# ── 端点 ──────────────────────────────────────────────────────────


@router.get("/waste-reduction")
async def get_waste_reduction(
    store_id: str = Query(..., description="门店 UUID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
    service: AIInsightsService = Depends(get_insights_service),
):
    """AI 食材浪费减少建议

    基于库存消耗记录分析浪费模式，提供：
      - 食材过量库存警告
      - 份量调整建议
      - 菜单工程优化建议
    """
    try:
        result = await service.get_waste_reduction_recommendations(
            tenant_id=x_tenant_id,
            store_id=store_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/labour-optimization")
async def get_labour_optimization(
    store_id: str = Query(..., description="门店 UUID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
    service: AIInsightsService = Depends(get_insights_service),
):
    """人力排班优化建议

    基于 Malaysia Employment Act 1955 合规分析：
      - 每周工时上限 45h 检查
      - 月加班上限 104h 检查
      - 节假日人力需求预估
    """
    try:
        result = await service.get_labour_optimization(
            tenant_id=x_tenant_id,
            store_id=store_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/halal-compliance")
async def get_halal_compliance(
    store_id: str = Query(..., description="门店 UUID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
    service: AIInsightsService = Depends(get_insights_service),
):
    """Halal 供应链合规检查

    基于 JAKIM 认证标准检查食材库存的 Halal 合规状态。
    """
    try:
        result = await service.get_halal_compliance_check(
            tenant_id=x_tenant_id,
            store_id=store_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/pricing")
async def get_pricing_recommendations(
    store_id: str = Query(..., description="门店 UUID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
    service: AIInsightsService = Depends(get_insights_service),
):
    """定价优化建议

    结合食材季节性成本、菜系客单价基准、SST 税率影响，
    提供菜品定价调整建议。
    """
    try:
        result = await service.get_pricing_recommendations(
            tenant_id=x_tenant_id,
            store_id=store_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
