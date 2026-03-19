"""
统一门店健康指数 API

GET /api/v1/stores/{store_id}/health-index
    — 单店综合健康指数（运营+私域+AI诊断三支柱）

GET /api/v1/stores/health-index/multi
    — 多店健康指数对比（query param: store_ids=S001,S002,...）

这是系统的唯一权威健康分出口。
"""

from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.dependencies import get_current_active_user, get_db
from ..models.user import User
from ..services.store_health_index_service import (
    get_multi_store_health_index,
    get_store_health_index,
)

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/stores", tags=["store_health_index"])


@router.get("/{store_id}/health-index")
async def single_store_health_index(
    store_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    获取门店统一健康指数。

    三支柱聚合：运营健康(40%) + 私域健康(35%) + AI诊断(25%)。
    自动写入历史快照，响应含近 7 天趋势。
    """
    result = await get_store_health_index(store_id=store_id, db=db)
    return result


@router.get("/health-index/multi")
async def multi_store_health_index(
    store_ids: str = Query(..., description="逗号分隔的门店ID，如 S001,S002,S003"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    批量获取多门店健康指数，按综合分降序排列。
    适用于总部大屏和 HQ Dashboard。
    """
    ids = [s.strip() for s in store_ids.split(",") if s.strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="store_ids 不能为空")
    if len(ids) > 50:
        raise HTTPException(status_code=400, detail="单次最多查询 50 个门店")
    results = await get_multi_store_health_index(store_ids=ids, db=db)
    return {"stores": results, "total": len(results)}
