"""渠道菜单独立管控 API

涵盖：
  - 平台菜品映射管理（查询/创建更新/自动匹配/批量确认）
  - 渠道菜单发布（发布版本/查历史/回滚）
  - 各渠道差异对比
  - 多渠道发布管理（渠道列表/渠道菜品/添加移除/一键发布）

ROUTER REGISTRATION (在tx-menu/src/main.py中添加):
    from .api.channel_mapping_routes import router as channel_mapping_router
    app.include_router(channel_mapping_router)
"""
from __future__ import annotations

import uuid as _uuid
from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from shared.ontology.src.database import get_db

from ..services.channel_mapping_service import (
    ChannelMappingService,
    DishOverride,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/menu", tags=["channel-mapping"])

# 支持的渠道及显示名
_CHANNELS: dict[str, str] = {
    "dine_in": "堂食",
    "meituan": "外卖-美团",
    "eleme": "外卖-饿了么",
    "miniapp": "小程序",
    "douyin": "抖音",
}


# ─── DB 依赖占位（与其他路由保持一致） ─────────────────────────────────────────


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


# ─── 多渠道发布管理 ────────────────────────────────────────────────────────────


class AddChannelDishReq(BaseModel):
    dish_id: str = Field(..., description="菜品ID")
    channel_price_fen: Optional[int] = Field(None, ge=0, description="渠道特有价格（分），None 用基础价")
    is_available: bool = True
    sort_order: int = 0


class UpdateChannelPriceReq(BaseModel):
    channel_price_fen: int = Field(..., ge=0, description="新价格（分）")


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


@router.get("/channels", summary="获取门店支持的渠道列表")
async def list_channels(
    store_id: str = Query(..., description="门店ID"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """返回系统支持的所有渠道及各渠道已上架菜品数量。

    渠道：堂食 / 外卖-美团 / 外卖-饿了么 / 小程序 / 抖音
    """
    tenant_id = _tenant_id(request)
    await _set_rls(db, tenant_id)
    tid = _uuid.UUID(tenant_id)
    sid = _uuid.UUID(store_id)

    # 统计各渠道已上架菜品数
    count_result = await db.execute(
        text("""
            SELECT channel, COUNT(*) AS cnt
            FROM channel_menu_items
            WHERE tenant_id = :tid
              AND store_id  = :sid
              AND is_available = true
            GROUP BY channel
        """),
        {"tid": tid, "sid": sid},
    )
    counts: dict[str, int] = {row[0]: int(row[1]) for row in count_result.fetchall()}

    data = [
        {
            "channel": ch,
            "display_name": display,
            "dish_count": counts.get(ch, 0),
        }
        for ch, display in _CHANNELS.items()
    ]
    log.info("channels.list", store_id=store_id, tenant_id=tenant_id)
    return {"ok": True, "data": {"channels": data, "total": len(data)}, "error": None}


@router.get("/channels/{channel}/dishes", summary="获取指定渠道菜品列表（含渠道价）")
async def list_channel_dishes(
    channel: str,
    store_id: str = Query(..., description="门店ID"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取指定渠道的菜品列表，包含渠道特有价格（无 override 时显示基础价）。"""
    if channel not in _CHANNELS:
        raise HTTPException(status_code=400, detail=f"不支持的渠道: {channel}，有效值: {list(_CHANNELS)}")
    tenant_id = _tenant_id(request)
    await _set_rls(db, tenant_id)
    tid = _uuid.UUID(tenant_id)
    sid = _uuid.UUID(store_id)

    result = await db.execute(
        text("""
            SELECT
                cmi.id,
                cmi.dish_id,
                d.dish_name,
                d.price_fen           AS base_price_fen,
                cmi.channel_price_fen AS channel_price_fen,
                COALESCE(cmi.channel_price_fen, d.price_fen) AS effective_price_fen,
                cmi.is_available,
                cmi.sort_order,
                d.image_url,
                d.category_id
            FROM channel_menu_items cmi
            JOIN dishes d ON d.id = cmi.dish_id AND d.tenant_id = cmi.tenant_id
            WHERE cmi.tenant_id = :tid
              AND cmi.store_id  = :sid
              AND cmi.channel   = :channel
              AND d.is_deleted  = false
            ORDER BY cmi.sort_order, d.dish_name
        """),
        {"tid": tid, "sid": sid, "channel": channel},
    )
    rows = result.fetchall()
    dishes = [
        {
            "id": str(r[0]),
            "dish_id": str(r[1]),
            "dish_name": r[2],
            "base_price_fen": r[3],
            "channel_price_fen": r[4],
            "effective_price_fen": r[5],
            "is_available": r[6],
            "sort_order": r[7],
            "image_url": r[8],
            "category_id": str(r[9]) if r[9] else None,
        }
        for r in rows
    ]
    log.info("channel_dishes.list", channel=channel, store_id=store_id, count=len(dishes))
    return {
        "ok": True,
        "data": {
            "channel": channel,
            "display_name": _CHANNELS[channel],
            "items": dishes,
            "total": len(dishes),
        },
        "error": None,
    }


@router.post("/channels/{channel}/dishes", summary="添加菜品到渠道", status_code=201)
async def add_dish_to_channel(
    channel: str,
    req: AddChannelDishReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """将菜品添加到指定渠道（存在则更新）。

    外卖渠道可配置独立加价（channel_price_fen），None 则使用基础价。
    """
    if channel not in _CHANNELS:
        raise HTTPException(status_code=400, detail=f"不支持的渠道: {channel}")
    tenant_id = _tenant_id(request)
    store_id = request.headers.get("X-Store-ID", "")
    if not store_id:
        raise HTTPException(status_code=400, detail="X-Store-ID header required")
    await _set_rls(db, tenant_id)
    tid = _uuid.UUID(tenant_id)
    sid = _uuid.UUID(store_id)
    did = _uuid.UUID(req.dish_id)

    # 验证菜品存在
    dish_check = await db.execute(
        text("SELECT id, dish_name FROM dishes WHERE id = :did AND tenant_id = :tid AND is_deleted = false"),
        {"did": did, "tid": tid},
    )
    dish_row = dish_check.fetchone()
    if not dish_row:
        raise HTTPException(status_code=404, detail=f"菜品不存在: {req.dish_id}")

    result = await db.execute(
        text("""
            INSERT INTO channel_menu_items
                (tenant_id, store_id, dish_id, channel, channel_price_fen, is_available, sort_order)
            VALUES
                (:tid, :sid, :did, :channel, :channel_price_fen, :is_available, :sort_order)
            ON CONFLICT (tenant_id, store_id, dish_id, channel) DO UPDATE SET
                channel_price_fen = EXCLUDED.channel_price_fen,
                is_available      = EXCLUDED.is_available,
                sort_order        = EXCLUDED.sort_order,
                updated_at        = NOW()
            RETURNING id, channel_price_fen, is_available, sort_order
        """),
        {
            "tid": tid,
            "sid": sid,
            "did": did,
            "channel": channel,
            "channel_price_fen": req.channel_price_fen,
            "is_available": req.is_available,
            "sort_order": req.sort_order,
        },
    )
    row = result.fetchone()
    await db.commit()
    log.info("channel_dish.added", channel=channel, dish_id=req.dish_id, store_id=store_id)
    return {
        "ok": True,
        "data": {
            "id": str(row[0]),
            "dish_id": req.dish_id,
            "dish_name": dish_row[1],
            "channel": channel,
            "channel_price_fen": row[1],
            "is_available": row[2],
            "sort_order": row[3],
        },
        "error": None,
    }


@router.delete(
    "/channels/{channel}/dishes/{dish_id}",
    summary="从渠道移除菜品",
    status_code=200,
)
async def remove_dish_from_channel(
    channel: str,
    dish_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """将菜品从指定渠道下线（设为 is_available=false），不物理删除。"""
    if channel not in _CHANNELS:
        raise HTTPException(status_code=400, detail=f"不支持的渠道: {channel}")
    tenant_id = _tenant_id(request)
    store_id = request.headers.get("X-Store-ID", "")
    if not store_id:
        raise HTTPException(status_code=400, detail="X-Store-ID header required")
    await _set_rls(db, tenant_id)
    tid = _uuid.UUID(tenant_id)
    sid = _uuid.UUID(store_id)
    did = _uuid.UUID(dish_id)

    result = await db.execute(
        text("""
            UPDATE channel_menu_items
            SET is_available = false, updated_at = NOW()
            WHERE tenant_id = :tid
              AND store_id  = :sid
              AND dish_id   = :did
              AND channel   = :channel
            RETURNING id
        """),
        {"tid": tid, "sid": sid, "did": did, "channel": channel},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"菜品 {dish_id} 不在渠道 {channel} 中")
    await db.commit()
    log.info("channel_dish.removed", channel=channel, dish_id=dish_id, store_id=store_id)
    return {"ok": True, "data": {"dish_id": dish_id, "channel": channel, "is_available": False}, "error": None}


@router.put(
    "/channels/{channel}/dishes/{dish_id}/price",
    summary="更新渠道菜品价格",
)
async def update_channel_dish_price(
    channel: str,
    dish_id: str,
    req: UpdateChannelPriceReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """单独更新某菜品在指定渠道的渠道价。菜品须已存在于该渠道。"""
    if channel not in _CHANNELS:
        raise HTTPException(status_code=400, detail=f"不支持的渠道: {channel}")
    tenant_id = _tenant_id(request)
    store_id = request.headers.get("X-Store-ID", "")
    if not store_id:
        raise HTTPException(status_code=400, detail="X-Store-ID header required")
    await _set_rls(db, tenant_id)
    tid = _uuid.UUID(tenant_id)
    sid = _uuid.UUID(store_id)
    did = _uuid.UUID(dish_id)

    result = await db.execute(
        text("""
            UPDATE channel_menu_items
            SET channel_price_fen = :price, updated_at = NOW()
            WHERE tenant_id = :tid
              AND store_id  = :sid
              AND dish_id   = :did
              AND channel   = :channel
            RETURNING id, channel_price_fen
        """),
        {"tid": tid, "sid": sid, "did": did, "channel": channel, "price": req.channel_price_fen},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"菜品 {dish_id} 不在渠道 {channel} 中，请先调用 POST /channels/{channel}/dishes 添加",
        )
    await db.commit()
    log.info("channel_dish.price_updated", channel=channel, dish_id=dish_id, price=req.channel_price_fen)
    return {
        "ok": True,
        "data": {
            "dish_id": dish_id,
            "channel": channel,
            "channel_price_fen": row[1],
        },
        "error": None,
    }


@router.post("/channels/{channel}/publish", summary="一键发布到渠道")
async def publish_to_channel(
    channel: str,
    store_id: str = Query(..., description="门店ID"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """将当前渠道所有 is_available=true 的菜品发布（同步写入 channel_menu_versions 快照）。

    等效于调用 channel_mapping_service.publish_channel_menu 并以 channel_menu_items
    中的实时数据作为 dish_overrides。
    """
    if channel not in _CHANNELS:
        raise HTTPException(status_code=400, detail=f"不支持的渠道: {channel}")
    tenant_id = _tenant_id(request)
    await _set_rls(db, tenant_id)
    tid = _uuid.UUID(tenant_id)
    sid = _uuid.UUID(store_id)

    # 读取当前渠道所有可用菜品
    items_result = await db.execute(
        text("""
            SELECT dish_id, channel_price_fen, is_available
            FROM channel_menu_items
            WHERE tenant_id = :tid
              AND store_id  = :sid
              AND channel   = :channel
              AND is_available = true
            ORDER BY sort_order
        """),
        {"tid": tid, "sid": sid, "channel": channel},
    )
    items = items_result.fetchall()

    if not items:
        raise HTTPException(
            status_code=422,
            detail=f"渠道 {channel} 没有可发布的菜品，请先使用 POST /channels/{channel}/dishes 添加菜品",
        )

    overrides = [
        {
            "dish_id": str(r[0]),
            "channel_price_fen": r[1],
            "is_available": r[2],
        }
        for r in items
    ]

    svc = ChannelMappingService(db=db, tenant_id=tenant_id)
    published_by = request.headers.get("X-User-ID") if request else None
    version = await svc.publish_channel_menu(
        store_id=store_id,
        channel_id=channel,
        dish_overrides=overrides,
        published_by=published_by,
    )
    # commit 在 service 内部未 commit，需在此处 commit
    await db.commit()

    log.info(
        "channel.published",
        channel=channel,
        store_id=store_id,
        version_no=version.version_no,
        dish_count=len(overrides),
    )
    return {
        "ok": True,
        "data": {
            "channel": channel,
            "display_name": _CHANNELS[channel],
            "version": version.model_dump(mode="json"),
            "published_dishes": len(overrides),
        },
        "error": None,
    }
