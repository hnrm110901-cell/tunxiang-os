"""
行业方案 API — 列表 / 一键安装
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..services.ai_agent_market.industry_solution_service import IndustrySolutionService

router = APIRouter(prefix="/api/v1/industry-solutions", tags=["industry-solutions"])


class InstallRequest(BaseModel):
    tenant_id: str
    installed_by: Optional[str] = None


@router.get("/")
async def list_solutions(db: AsyncSession = Depends(get_db)):
    svc = IndustrySolutionService(db)
    return svc.list_solutions()


@router.post("/{solution_code}/install")
async def install(
    solution_code: str,
    body: InstallRequest,
    db: AsyncSession = Depends(get_db),
):
    svc = IndustrySolutionService(db)
    try:
        res = await svc.install_industry_solution(
            tenant_id=body.tenant_id,
            solution_code=solution_code,
            installed_by=body.installed_by,
        )
        await db.commit()
        return res
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
