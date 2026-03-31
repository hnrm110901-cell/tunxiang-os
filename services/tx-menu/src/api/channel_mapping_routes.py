"""渠道菜单独立管控 API

涵盖：
  - 平台菜品映射管理（查询/创建更新/自动匹配/批量确认）
  - 渠道菜单发布（发布版本/查历史/回滚）
  - 各渠道差异对比

ROUTER REGISTRATION (在tx-menu/src/main.py中添加):
    from .api.channel_mapping_routes import router as channel_mapping_router
    app.include_router(channel_mapping_router)
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.channel_mapping_service import (
    ChannelMappingService,
    DishOverride,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/menu", tags=["channel-mapping"])


# ─── DB 依赖占位（与其他路由保持一致） ─────────────────────────────────────────


async def get_db() -> AsyncSession:  # type: ignore[override]
    """数据库会话依赖 — 由 main.py 中 app.dependency_overrides 注入"""
    raise NotImplementedError("DB session dependency not configured")


# ─── 工具函数 ───────────────────────────────────────────────────────────────────


def _tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


# ─── 请求模型 ───────────────────────────────────────────────────────────────────


class UpsertMappingReq(BaseModel):
    store_id: str
    platform: str = Field(..., pattern="^(meituan|eleme|douyin)$")
    platform_item_id: str
    platform_item_name: Optional[str] = None
    dish_id: Optional[str] = None
    platform_price_fen: Optional[int] = Field(None, ge=0, description="平台独立定价（分），None 表示用内部价")
    platform_sku_name: Optional[str] = None
    is_active: bool = True


class BatchMappingItem(BaseModel):
    platform_item_id: str
    dish_id: str
    platform_price_fen: Optional[int] = Field(None, ge=0)


class BatchMappingReq(BaseModel):
    store_id: str
    platform: str = Field(..., pattern="^(meituan|eleme|douyin)$")
    items: list[BatchMappingItem] = Field(..., min_length=1, max_length=200)


class PublishChannelMenuReq(BaseModel):
    store_id: str
    channel_id: str
    dish_overrides: list[dict] = Field(default_factory=list)
    published_by: Optional[str] = None


# ─── 路由：映射管理 ─────────────────────────────────────────────────────────────


@router.get("/channel-mappings", summary="获取平台菜品映射列表")
async def list_channel_mappings(
    store_id: str = Query(..., description="门店ID"),
    platform: str = Query(..., description="平台: meituan/eleme/douyin"),
    unmapped_only: bool = Query(False, description="只返回未映射条目"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询平台菜品映射列表，支持按 platform 和 unmapped_only 过滤。"""
    if platform not in ("meituan", "eleme", "douyin"):
        raise HTTPException(status_code=400, detail=f"不支持的平台: {platform}")
    tenant_id = _tenant_id(request)
    svc = ChannelMappingService(db=db, tenant_id=tenant_id)
    mappings = await svc.get_mappings(
        store_id=store_id,
        platform=platform,
        unmapped_only=unmapped_only,
    )
    return {
        "ok": True,
        "data": {
            "items": [m.model_dump(mode="json") for m in mappings],
            "total": len(mappings),
        },
        "error": None,
    }


@router.post("/channel-mappings", summary="创建或更新平台菜品映射")
async def upsert_channel_mapping(
    req: UpsertMappingReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建或更新单条平台 ⇄ 内部菜品映射。"""
    tenant_id = _tenant_id(request)
    svc = ChannelMappingService(db=db, tenant_id=tenant_id)
    mapping = await svc.upsert_mapping(
        store_id=req.store_id,
        platform=req.platform,
        platform_item_id=req.platform_item_id,
        dish_id=req.dish_id,
        platform_price_fen=req.platform_price_fen,
        platform_item_name=req.platform_item_name,
        platform_sku_name=req.platform_sku_name,
        is_active=req.is_active,
    )
    await db.commit()
    return {"ok": True, "data": mapping.model_dump(mode="json"), "error": None}


@router.post("/channel-mappings/auto-match", summary="按名称自动匹配建议")
async def auto_match_mappings(
    store_id: str = Query(..., description="门店ID"),
    platform: str = Query(..., description="平台: meituan/eleme/douyin"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """对未映射的平台SKU按名称相似度（编辑距离）返回匹配建议，不自动写库。"""
    if platform not in ("meituan", "eleme", "douyin"):
        raise HTTPException(status_code=400, detail=f"不支持的平台: {platform}")
    tenant_id = _tenant_id(request)
    svc = ChannelMappingService(db=db, tenant_id=tenant_id)
    result = await svc.auto_match_by_name(store_id=store_id, platform=platform)
    return {"ok": True, "data": result.model_dump(mode="json"), "error": None}


@router.post("/channel-mappings/batch", summary="批量确认映射")
async def batch_confirm_mappings(
    req: BatchMappingReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """批量写入/更新多条平台 ⇄ 内部菜品映射（一次最多 200 条）。"""
    tenant_id = _tenant_id(request)
    svc = ChannelMappingService(db=db, tenant_id=tenant_id)
    results = []
    for item in req.items:
        mapping = await svc.upsert_mapping(
            store_id=req.store_id,
            platform=req.platform,
            platform_item_id=item.platform_item_id,
            dish_id=item.dish_id,
            platform_price_fen=item.platform_price_fen,
        )
        results.append(mapping.model_dump(mode="json"))
    await db.commit()
    return {
        "ok": True,
        "data": {"saved": len(results), "items": results},
        "error": None,
    }


# ─── 路由：渠道菜单发布 ─────────────────────────────────────────────────────────


@router.post("/channel-publish", summary="发布渠道菜单版本")
async def publish_channel_menu(
    req: PublishChannelMenuReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """发布渠道菜单（自动递增版本号，旧 published 版本→archived）。

    dish_overrides 每项格式：
      {dish_id, channel_price_fen?, is_available?, channel_name?}
    """
    tenant_id = _tenant_id(request)
    svc = ChannelMappingService(db=db, tenant_id=tenant_id)
    version = await svc.publish_channel_menu(
        store_id=req.store_id,
        channel_id=req.channel_id,
        dish_overrides=req.dish_overrides,
        published_by=req.published_by,
    )
    await db.commit()
    return {"ok": True, "data": version.model_dump(mode="json"), "error": None}


@router.get("/channel-versions/{store_id}", summary="查询渠道发布历史")
async def get_channel_versions(
    store_id: str,
    channel_id: Optional[str] = Query(None, description="渠道ID，不传则查所有渠道"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询门店渠道发布历史，支持按渠道过滤，分页返回。"""
    tenant_id = _tenant_id(request)
    svc = ChannelMappingService(db=db, tenant_id=tenant_id)
    versions, total = await svc.get_channel_versions(
        store_id=store_id,
        channel_id=channel_id,
        page=page,
        size=size,
    )
    return {
        "ok": True,
        "data": {
            "items": [v.model_dump(mode="json") for v in versions],
            "total": total,
            "page": page,
            "size": size,
        },
        "error": None,
    }


@router.post("/channel-versions/{version_id}/rollback", summary="回滚渠道菜单版本")
async def rollback_channel_version(
    version_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """将指定版本重新设为 published（当前 published 版本→archived）。"""
    tenant_id = _tenant_id(request)
    svc = ChannelMappingService(db=db, tenant_id=tenant_id)
    try:
        version = await svc.rollback_channel_version(version_id=version_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await db.commit()
    return {"ok": True, "data": version.model_dump(mode="json"), "error": None}


# ─── 路由：差异对比 ─────────────────────────────────────────────────────────────


@router.get("/channel-diff", summary="各渠道菜单差异对比")
async def get_channel_diff(
    store_id: str = Query(..., description="门店ID"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """返回以菜品为行、渠道为列的价格与可用性差异矩阵。"""
    tenant_id = _tenant_id(request)
    svc = ChannelMappingService(db=db, tenant_id=tenant_id)
    diff = await svc.get_channel_diff(store_id=store_id)
    return {"ok": True, "data": diff.model_dump(mode="json"), "error": None}
