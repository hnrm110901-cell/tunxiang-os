"""菜单中心完整路由 — 模板 / 发布 / 渠道差异价 / 季节菜单 / 包厢菜单 / 沽清联动

补全 dishes.py 和 publish.py 未覆盖的 C1 功能。
统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from shared.ontology.src.database import get_db

from ..services.dish_service import (
    create_dish,
    get_dish,
    update_dish,
    delete_dish,
    list_dishes,
    list_dishes_by_status,
    list_dishes_by_season,
)
from ..services.menu_template_repository import (
    MenuTemplateRepository,
    VALID_CHANNELS,
    VALID_SEASONS,
    VALID_ROOM_TYPES,
)
from ..services.stockout_sync import (
    mark_sold_out,
    auto_check_stockout,
    get_sold_out_list,
    restore_dish,
)

log = structlog.get_logger()

router = APIRouter(prefix="/api/v1/menu", tags=["menu-center"])


# ─── Request Models ───


class DishCreateReq(BaseModel):
    dish_name: str
    dish_code: str
    price_fen: int = Field(ge=0, description="售价(分)")
    store_id: Optional[str] = None
    category_id: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    kitchen_station: Optional[str] = None
    preparation_time: Optional[int] = None
    unit: str = "份"
    spicy_level: int = 0
    cost_fen: Optional[int] = None
    tags: Optional[list[str]] = None
    season: Optional[str] = None
    is_seasonal: bool = False


class DishUpdateReq(BaseModel):
    dish_name: Optional[str] = None
    price_fen: Optional[int] = None
    cost_fen: Optional[int] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    kitchen_station: Optional[str] = None
    preparation_time: Optional[int] = None
    unit: Optional[str] = None
    spicy_level: Optional[int] = None
    tags: Optional[list[str]] = None
    season: Optional[str] = None
    is_seasonal: Optional[bool] = None
    is_available: Optional[bool] = None
    sort_order: Optional[int] = None
    category_id: Optional[str] = None


class TemplateDishItem(BaseModel):
    dish_id: str
    sort_order: int = 0
    price_fen: Optional[int] = None


class TemplateCreateReq(BaseModel):
    name: str
    dishes: list[TemplateDishItem]
    rules: Optional[dict] = None


class PublishToStoreReq(BaseModel):
    template_id: str
    store_id: str


class ChannelPriceReq(BaseModel):
    dish_id: str
    channel: str = Field(description="dine_in/takeout/delivery/miniapp")
    price_fen: int = Field(ge=0, description="渠道售价(分)")


class SeasonalMenuReq(BaseModel):
    store_id: str
    season: str = Field(description="spring/summer/autumn/winter")
    dishes: list[TemplateDishItem]


class RoomMenuReq(BaseModel):
    store_id: str
    room_type: str = Field(description="standard/vip/luxury/banquet")
    dishes: list[TemplateDishItem]


class BanquetPackageReq(BaseModel):
    name: str
    dishes: list[TemplateDishItem]
    package_price_fen: int = Field(ge=0)
    guest_count: int = Field(gt=0)
    description: Optional[str] = None


class SoldOutReq(BaseModel):
    dish_id: str
    store_id: str
    reason: str = Field(description="manual/stock_depleted/ingredient_short/quality_issue")
    notes: Optional[str] = None


class RestoreDishReq(BaseModel):
    dish_id: str
    store_id: str


# ─── 辅助 ───


def _err(status: int, msg: str):
    raise HTTPException(status_code=status, detail={"ok": False, "error": {"message": msg}})


def _repo(db: AsyncSession, tenant_id: str) -> MenuTemplateRepository:
    return MenuTemplateRepository(db=db, tenant_id=tenant_id)


# ═══════════════════════════════════════════
# 菜品档案 CRUD（补全 dish_service 调用）
# ═══════════════════════════════════════════


@router.post("/v2/dishes")
async def api_create_dish(
    req: DishCreateReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """创建菜品档案"""
    try:
        dish = create_dish(tenant_id=x_tenant_id, **req.model_dump())
        return {"ok": True, "data": dish}
    except ValueError as exc:
        _err(400, str(exc))


@router.get("/v2/dishes/{dish_id}")
async def api_get_dish(
    dish_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """获取菜品详情"""
    dish = get_dish(dish_id, x_tenant_id)
    if not dish:
        _err(404, f"菜品不存在: {dish_id}")
    return {"ok": True, "data": dish}


@router.patch("/v2/dishes/{dish_id}")
async def api_update_dish(
    dish_id: str,
    req: DishUpdateReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """更新菜品档案"""
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    try:
        dish = update_dish(dish_id, x_tenant_id, **updates)
        return {"ok": True, "data": dish}
    except ValueError as exc:
        _err(400, str(exc))


@router.delete("/v2/dishes/{dish_id}")
async def api_delete_dish(
    dish_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """软删除菜品"""
    ok = delete_dish(dish_id, x_tenant_id)
    if not ok:
        _err(404, f"菜品不存在: {dish_id}")
    return {"ok": True, "data": {"deleted": True}}


@router.get("/v2/dishes")
async def api_list_dishes(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    store_id: Optional[str] = None,
    category_id: Optional[str] = None,
    status: Optional[str] = None,
    season: Optional[str] = None,
    keyword: Optional[str] = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    """菜品列表 — 支持多维筛选"""
    try:
        result = list_dishes(
            x_tenant_id,
            store_id=store_id,
            category_id=category_id,
            status=status,
            season=season,
            keyword=keyword,
            page=page,
            size=size,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        _err(400, str(exc))


@router.get("/v2/dishes/by-status/{status}")
async def api_list_by_status(
    status: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """按状态查询菜品"""
    try:
        items = list_dishes_by_status(x_tenant_id, status)
        return {"ok": True, "data": {"items": items, "total": len(items)}}
    except ValueError as exc:
        _err(400, str(exc))


@router.get("/v2/dishes/by-season/{season}")
async def api_list_by_season(
    season: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """按季节查询菜品"""
    try:
        items = list_dishes_by_season(x_tenant_id, season)
        return {"ok": True, "data": {"items": items, "total": len(items)}}
    except ValueError as exc:
        _err(400, str(exc))


# ═══════════════════════════════════════════
# 菜单模板
# ═══════════════════════════════════════════


@router.post("/templates")
async def api_create_template(
    req: TemplateCreateReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """创建菜单模板"""
    try:
        repo = _repo(db, x_tenant_id)
        tpl = await repo.create_template(
            name=req.name,
            dishes=[d.model_dump() for d in req.dishes],
            rules=req.rules,
        )
        await db.commit()
        return {"ok": True, "data": tpl}
    except ValueError as exc:
        _err(400, str(exc))


@router.get("/templates")
async def api_list_templates(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """列出菜单模板"""
    repo = _repo(db, x_tenant_id)
    templates = await repo.list_templates()
    return {"ok": True, "data": {"items": templates, "total": len(templates)}}


@router.get("/templates/{template_id}")
async def api_get_template(
    template_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取模板详情"""
    repo = _repo(db, x_tenant_id)
    tpl = await repo.get_template(template_id)
    if not tpl:
        _err(404, f"模板不存在: {template_id}")
    return {"ok": True, "data": tpl}


# ═══════════════════════════════════════════
# 门店发布
# ═══════════════════════════════════════════


@router.post("/templates/publish")
async def api_publish_to_store(
    req: PublishToStoreReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """将模板发布到门店"""
    try:
        repo = _repo(db, x_tenant_id)
        result = await repo.publish_to_store(req.template_id, req.store_id)
        await db.commit()
        return {"ok": True, "data": result}
    except ValueError as exc:
        _err(400, str(exc))


@router.get("/stores/{store_id}/menu")
async def api_get_store_menu(
    store_id: str,
    channel: str = Query("dine_in", description="渠道: dine_in/takeout/delivery/miniapp"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取门店当前菜单（按渠道）"""
    try:
        if channel not in VALID_CHANNELS:
            _err(400, f"channel 必须为 {VALID_CHANNELS} 之一，收到: {channel!r}")
        repo = _repo(db, x_tenant_id)
        menu = await repo.get_store_menu(store_id, channel)
        return {"ok": True, "data": menu}
    except ValueError as exc:
        _err(400, str(exc))


# ═══════════════════════════════════════════
# 渠道差异价
# ═══════════════════════════════════════════


@router.post("/channel-price")
async def api_set_channel_price(
    req: ChannelPriceReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """设置菜品渠道差异价"""
    try:
        if req.channel not in VALID_CHANNELS:
            _err(400, f"channel 必须为 {VALID_CHANNELS} 之一，收到: {req.channel!r}")
        repo = _repo(db, x_tenant_id)
        record = await repo.set_channel_price(
            dish_id=req.dish_id,
            channel=req.channel,
            price_fen=req.price_fen,
        )
        await db.commit()
        return {"ok": True, "data": record}
    except ValueError as exc:
        _err(400, str(exc))


# ═══════════════════════════════════════════
# 季节菜单
# ═══════════════════════════════════════════


@router.post("/seasonal-menu")
async def api_set_seasonal_menu(
    req: SeasonalMenuReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """设置门店季节菜单"""
    try:
        if req.season not in VALID_SEASONS:
            _err(400, f"season 必须为 {VALID_SEASONS} 之一，收到: {req.season!r}")
        repo = _repo(db, x_tenant_id)
        record = await repo.set_seasonal_menu(
            store_id=req.store_id,
            season=req.season,
            dishes=[d.model_dump() for d in req.dishes],
        )
        await db.commit()
        return {"ok": True, "data": record}
    except ValueError as exc:
        _err(400, str(exc))


@router.get("/stores/{store_id}/seasonal-menu/{season}")
async def api_get_seasonal_menu(
    store_id: str,
    season: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取门店季节菜单"""
    try:
        if season not in VALID_SEASONS:
            _err(400, f"season 必须为 {VALID_SEASONS} 之一，收到: {season!r}")
        repo = _repo(db, x_tenant_id)
        menu = await repo.get_seasonal_menu(store_id, season)
        if not menu:
            _err(404, f"门店 {store_id} 没有 {season} 季节菜单")
        return {"ok": True, "data": menu}
    except ValueError as exc:
        _err(400, str(exc))


# ═══════════════════════════════════════════
# 包厢菜单
# ═══════════════════════════════════════════


@router.post("/room-menu")
async def api_set_room_menu(
    req: RoomMenuReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """设置门店包厢专属菜单"""
    try:
        if req.room_type not in VALID_ROOM_TYPES:
            _err(400, f"room_type 必须为 {VALID_ROOM_TYPES} 之一，收到: {req.room_type!r}")
        repo = _repo(db, x_tenant_id)
        record = await repo.set_room_menu(
            store_id=req.store_id,
            room_type=req.room_type,
            dishes=[d.model_dump() for d in req.dishes],
        )
        await db.commit()
        return {"ok": True, "data": record}
    except ValueError as exc:
        _err(400, str(exc))


@router.get("/stores/{store_id}/room-menu/{room_type}")
async def api_get_room_menu(
    store_id: str,
    room_type: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取门店包厢菜单"""
    try:
        if room_type not in VALID_ROOM_TYPES:
            _err(400, f"room_type 必须为 {VALID_ROOM_TYPES} 之一，收到: {room_type!r}")
        repo = _repo(db, x_tenant_id)
        menu = await repo.get_room_menu(store_id, room_type)
        if not menu:
            _err(404, f"门店 {store_id} 没有 {room_type} 包厢菜单")
        return {"ok": True, "data": menu}
    except ValueError as exc:
        _err(400, str(exc))


# ═══════════════════════════════════════════
# 宴席套餐
# ═══════════════════════════════════════════


@router.post("/banquet-packages")
async def api_create_banquet_package(
    req: BanquetPackageReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """创建宴席套餐"""
    try:
        repo = _repo(db, x_tenant_id)
        pkg = await repo.create_banquet_package(
            name=req.name,
            dishes=[d.model_dump() for d in req.dishes],
            package_price_fen=req.package_price_fen,
            guest_count=req.guest_count,
            description=req.description,
        )
        await db.commit()
        return {"ok": True, "data": pkg}
    except ValueError as exc:
        _err(400, str(exc))


# ═══════════════════════════════════════════
# 沽清联动
# ═══════════════════════════════════════════


@router.post("/stockout/mark")
async def api_mark_sold_out(
    req: SoldOutReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """标记菜品沽清"""
    try:
        record = mark_sold_out(
            dish_id=req.dish_id,
            store_id=req.store_id,
            reason=req.reason,
            tenant_id=x_tenant_id,
            notes=req.notes,
        )
        return {"ok": True, "data": record}
    except ValueError as exc:
        _err(400, str(exc))


@router.post("/stockout/auto-check")
async def api_auto_check_stockout(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """自动检测沽清（基于库存）"""
    # 在真实场景中，db 从 DI 注入；这里接受空调用
    records = auto_check_stockout(store_id, x_tenant_id)
    return {"ok": True, "data": {"newly_sold_out": records, "count": len(records)}}


@router.get("/stores/{store_id}/stockout")
async def api_get_sold_out_list(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """获取门店沽清清单"""
    try:
        items = get_sold_out_list(store_id, x_tenant_id)
        return {"ok": True, "data": {"items": items, "total": len(items)}}
    except ValueError as exc:
        _err(400, str(exc))


@router.post("/stockout/restore")
async def api_restore_dish(
    req: RestoreDishReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """恢复沽清菜品供应"""
    try:
        record = restore_dish(req.dish_id, req.store_id, x_tenant_id)
        return {"ok": True, "data": record}
    except ValueError as exc:
        _err(400, str(exc))
