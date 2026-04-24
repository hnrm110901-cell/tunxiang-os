"""KDS显示配置 API — 层级配置 + 做法过滤 + 表格模式

所有接口需要 X-Tenant-ID header。
ROUTER REGISTRATION（在 main.py 中添加）：
  from .api.kds_display_config_routes import router as kds_display_config_router
  app.include_router(kds_display_config_router, prefix="/api/v1/kds-display")
"""

from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.kds_display_config_service import KdsDisplayConfigService

logger = structlog.get_logger()

router = APIRouter(tags=["kds-display"])


# ── 公共依赖 ─────────────────────────────────────────────────

def _tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


# ── 请求/响应模型 ────────────────────────────────────────────

class UpdateConfigRequest(BaseModel):
    store_id: str
    station_id: Optional[str] = None
    config_key: str
    config_value: dict


class ApplyFilterRequest(BaseModel):
    store_id: str
    practices: List[str] = Field(default_factory=list)


# ── 端点 ─────────────────────────────────────────────────────

@router.get("/config")
async def get_display_config(
    store_id: str = Query(...),
    config_key: str = Query(...),
    station_id: Optional[str] = Query(None),
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """获取KDS显示配置（station > store > default 层级）"""
    result = await KdsDisplayConfigService.get_display_config(
        db,
        tenant_id,
        store_id=store_id,
        station_id=station_id,
        config_key=config_key,
    )
    return {"ok": True, "data": result}


@router.post("/config")
async def update_display_config(
    body: UpdateConfigRequest,
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """更新/创建KDS显示配置（UPSERT）"""
    result = await KdsDisplayConfigService.update_config(
        db,
        tenant_id,
        store_id=body.store_id,
        station_id=body.station_id,
        config_key=body.config_key,
        config_value=body.config_value,
    )
    return {"ok": True, "data": result}


@router.get("/practice-filters")
async def get_practice_filters(
    store_id: str = Query(...),
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """获取做法过滤选项列表"""
    result = await KdsDisplayConfigService.get_practice_filter_options(
        db,
        tenant_id,
        store_id=store_id,
    )
    return {"ok": True, "data": result}


@router.post("/apply-filter")
async def apply_practice_filter(
    body: ApplyFilterRequest,
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """按做法组合过滤，返回匹配的菜品列表"""
    result = await KdsDisplayConfigService.get_practice_combo_filter(
        db,
        tenant_id,
        store_id=body.store_id,
        practices=body.practices,
    )
    return {"ok": True, "data": result}


@router.get("/table-mode")
async def get_table_mode(
    store_id: str = Query(...),
    station_id: Optional[str] = Query(None),
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """获取KDS表格模式的全量配置数据"""
    result = await KdsDisplayConfigService.get_table_mode_data(
        db,
        tenant_id,
        store_id=store_id,
        station_id=station_id,
    )
    return {"ok": True, "data": result}
