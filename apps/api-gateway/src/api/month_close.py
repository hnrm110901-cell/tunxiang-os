"""月结/年结 API（D7 Nice-to-Have）

端点:
  GET  /api/v1/finance/month-close/{store_id}/{ym}/pre-check
  POST /api/v1/finance/month-close/{store_id}/{ym}
  POST /api/v1/finance/month-close/{store_id}/{ym}/reopen
  POST /api/v1/finance/year-close/{store_id}/{year}
  GET  /api/v1/finance/year-close/{store_id}/{year}/status
"""

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..core.deps_store_access import require_store_access
from ..core.dependencies import get_current_active_user
from ..models.user import User
from ..services.month_close_service import MonthCloseError, month_close_service

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/finance", tags=["月结年结"])


class ReopenRequest(BaseModel):
    reason: str = Field(..., min_length=5, max_length=500, description="反结账原因（≥5字）")


@router.get("/month-close/{store_id}/{ym}/pre-check", summary="月结前阻塞检查")
async def pre_close_check(
    store_id: str,
    ym: str,
    user: User = Depends(require_store_access("finance")),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await month_close_service.pre_close_check(session, store_id, ym)
    except MonthCloseError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/month-close/{store_id}/{ym}", summary="执行月结")
async def execute_month_close(
    store_id: str,
    ym: str,
    user: User = Depends(require_store_access("finance_write")),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await month_close_service.execute_month_close(session, store_id, ym, user)
    except MonthCloseError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/month-close/{store_id}/{ym}/reopen", summary="反结账（仅老板）")
async def reopen_month(
    store_id: str,
    ym: str,
    body: ReopenRequest,
    # 反结账权限极高，固定走 finance_write + service 内 role 双重校验
    user: User = Depends(require_store_access("finance_write")),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await month_close_service.reopen_month(session, store_id, ym, user, body.reason)
    except MonthCloseError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/year-close/{store_id}/{year}", summary="执行年结")
async def execute_year_close(
    store_id: str,
    year: int,
    user: User = Depends(require_store_access("finance_write")),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if not (2000 <= year <= 2100):
        raise HTTPException(status_code=400, detail=f"year 越界: {year}")
    try:
        return await month_close_service.execute_year_close(session, store_id, year, user)
    except MonthCloseError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/year-close/{store_id}/{year}/status", summary="查询年结状态")
async def get_year_close_status(
    store_id: str,
    year: int,
    user: User = Depends(require_store_access("finance")),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await month_close_service.get_year_close_status(session, store_id, year)
