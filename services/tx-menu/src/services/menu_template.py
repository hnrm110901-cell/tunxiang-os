"""菜单模板管理 — 已迁移到 DB（v095）

渠道: dine_in / takeout / delivery / miniapp
价格单位: 分(fen)
所有操作强制 tenant_id 租户隔离。

持久化：PostgreSQL + SQLAlchemy async，Repository 模式。
本文件的内存实现已由 menu_template_repository.MenuTemplateRepository 替代。
路由层（menu_routes.py）已切换到 Repository，本文件不再被导入。

保留原因：
  1. _clear_all() 供旧版单元测试调用（待测试迁移后删除）
  2. 作为迁移前的历史参考
"""

import uuid
from typing import Optional

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.menu_template import (
    ChannelPrice,
    MenuTemplate,
    RoomMenu,
    SeasonalMenu,
    StoreMenuPublish,
)

log = structlog.get_logger()

# ─── 渠道常量 ───
VALID_CHANNELS = {"dine_in", "takeout", "delivery", "miniapp"}

# ─── 季节常量 ───
VALID_SEASONS = {"spring", "summer", "autumn", "winter"}

# ─── 包厢类型常量 ───
VALID_ROOM_TYPES = {"standard", "vip", "luxury", "banquet"}


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    """设置 RLS tenant context"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _model_to_template_dict(tpl: MenuTemplate) -> dict:
    """将 ORM 模型转为 API 兼容 dict"""
    result = {
        "template_id": str(tpl.id),
        "name": tpl.name,
        "dishes": tpl.dishes or [],
        "rules": tpl.rules or {},
        "tenant_id": str(tpl.tenant_id),
        "status": tpl.status,
        "published_stores": tpl.published_stores or [],
        "created_at": tpl.created_at.isoformat() if tpl.created_at else None,
        "updated_at": tpl.updated_at.isoformat() if tpl.updated_at else None,
    }
    if tpl.package_price_fen is not None:
        result["package_price_fen"] = tpl.package_price_fen
    if tpl.guest_count is not None:
        result["guest_count"] = tpl.guest_count
    if tpl.description is not None:
        result["description"] = tpl.description
    return result


# ─── 菜单模板 ───


async def create_template(
    db: AsyncSession,
    name: str,
    dishes: list[dict],
    rules: Optional[dict] = None,
    tenant_id: str = "",
) -> dict:
    """创建菜单模板。

    Args:
        db: 异步数据库会话
        name: 模板名称
        dishes: 菜品列表，每项含 {"dish_id": str, "sort_order": int, ...}
        rules: 可选模板规则，如 {"min_dishes": 10, "max_dishes": 50, "require_categories": [...]}
        tenant_id: 租户 ID

    Returns:
        dict — 完整模板对象
    """
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")
    if not name or not name.strip():
        raise ValueError("name 不能为空")
    if not dishes:
        raise ValueError("dishes 不能为空列表")

    await _set_tenant(db, tenant_id)

    tpl = MenuTemplate(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(tenant_id),
        name=name.strip(),
        dishes=list(dishes),
        rules=rules or {},
        status="draft",
        published_stores=[],
    )
    db.add(tpl)
    await db.flush()

    log.info(
        "menu_template.created",
        tenant_id=tenant_id,
        template_id=str(tpl.id),
        dish_count=len(dishes),
    )
    return _model_to_template_dict(tpl)


async def get_template(
    db: AsyncSession,
    template_id: str,
    tenant_id: str,
) -> Optional[dict]:
    """获取模板详情"""
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")

    await _set_tenant(db, tenant_id)

    result = await db.execute(
        select(MenuTemplate)
        .where(MenuTemplate.id == uuid.UUID(template_id))
        .where(MenuTemplate.tenant_id == uuid.UUID(tenant_id))
        .where(MenuTemplate.is_deleted == False)  # noqa: E712
    )
    tpl = result.scalar_one_or_none()
    if not tpl:
        return None
    return _model_to_template_dict(tpl)


async def list_templates(
    db: AsyncSession,
    tenant_id: str,
) -> list[dict]:
    """列出租户的所有菜单模板"""
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")

    await _set_tenant(db, tenant_id)

    result = await db.execute(
        select(MenuTemplate)
        .where(MenuTemplate.tenant_id == uuid.UUID(tenant_id))
        .where(MenuTemplate.is_deleted == False)  # noqa: E712
        .order_by(MenuTemplate.created_at.desc())
    )
    rows = result.scalars().all()
    return [_model_to_template_dict(t) for t in rows]


# ─── 门店发布 ───


async def publish_to_store(
    db: AsyncSession,
    template_id: str,
    store_id: str,
    tenant_id: str,
) -> dict:
    """将菜单模板发布到门店。

    Args:
        db: 异步数据库会话
        template_id: 模板 ID
        store_id: 目标门店 ID
        tenant_id: 租户 ID

    Returns:
        dict — 发布结果，含 store_id、发布时间、菜品数
    """
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")
    if not store_id:
        raise ValueError("store_id 不能为空")

    await _set_tenant(db, tenant_id)
    tenant_uuid = uuid.UUID(tenant_id)
    store_uuid = uuid.UUID(store_id)

    # 获取模板
    result = await db.execute(
        select(MenuTemplate)
        .where(MenuTemplate.id == uuid.UUID(template_id))
        .where(MenuTemplate.tenant_id == tenant_uuid)
        .where(MenuTemplate.is_deleted == False)  # noqa: E712
    )
    template = result.scalar_one_or_none()
    if not template:
        raise ValueError(f"模板不存在: {template_id}")

    # 查找是否已有该门店的发布记录（upsert 逻辑）
    existing_result = await db.execute(
        select(StoreMenuPublish)
        .where(StoreMenuPublish.store_id == store_uuid)
        .where(StoreMenuPublish.tenant_id == tenant_uuid)
        .where(StoreMenuPublish.is_deleted == False)  # noqa: E712
    )
    existing = existing_result.scalar_one_or_none()

    if existing:
        existing.template_id = template.id
        existing.template_name = template.name
        existing.dishes = list(template.dishes)
        existing.status = "active"
    else:
        publish_record = StoreMenuPublish(
            id=uuid.uuid4(),
            tenant_id=tenant_uuid,
            store_id=store_uuid,
            template_id=template.id,
            template_name=template.name,
            dishes=list(template.dishes),
            status="active",
        )
        db.add(publish_record)

    # 更新模板的已发布门店列表
    published_stores = list(template.published_stores or [])
    if store_id not in published_stores:
        published_stores.append(store_id)
    template.published_stores = published_stores
    template.status = "published"

    await db.flush()

    log.info(
        "menu_template.published",
        tenant_id=tenant_id,
        template_id=template_id,
        store_id=store_id,
        dish_count=len(template.dishes),
    )

    return {
        "store_id": store_id,
        "template_id": template_id,
        "dish_count": len(template.dishes),
        "published_at": template.updated_at.isoformat() if template.updated_at else None,
        "status": "success",
    }


# ─── 门店菜单查询（按渠道） ───


async def get_store_menu(
    db: AsyncSession,
    store_id: str,
    channel: str,
    tenant_id: str,
) -> dict:
    """获取门店当前菜单（按渠道）。

    根据渠道差异价调整菜品价格，未设置差异价则使用原价。

    Args:
        db: 异步数据库会话
        store_id: 门店 ID
        channel: 渠道 dine_in/takeout/delivery/miniapp
        tenant_id: 租户 ID

    Returns:
        dict — {"store_id", "channel", "dishes": [...], "dish_count"}
    """
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")
    if channel not in VALID_CHANNELS:
        raise ValueError(f"channel 必须为 {VALID_CHANNELS} 之一，收到: {channel!r}")

    await _set_tenant(db, tenant_id)
    tenant_uuid = uuid.UUID(tenant_id)
    store_uuid = uuid.UUID(store_id)

    # 查询门店已发布菜单
    result = await db.execute(
        select(StoreMenuPublish)
        .where(StoreMenuPublish.store_id == store_uuid)
        .where(StoreMenuPublish.tenant_id == tenant_uuid)
        .where(StoreMenuPublish.is_deleted == False)  # noqa: E712
        .where(StoreMenuPublish.status == "active")
    )
    menu = result.scalar_one_or_none()

    if not menu:
        return {
            "store_id": store_id,
            "channel": channel,
            "dishes": [],
            "dish_count": 0,
        }

    # 批量查询该租户下该渠道的所有差异价
    price_result = await db.execute(
        select(ChannelPrice)
        .where(ChannelPrice.tenant_id == tenant_uuid)
        .where(ChannelPrice.channel == channel)
        .where(ChannelPrice.is_deleted == False)  # noqa: E712
    )
    price_map: dict[str, int] = {str(cp.dish_id): cp.price_fen for cp in price_result.scalars().all()}

    # 应用渠道差异价
    dishes_with_price = []
    for dish in menu.dishes or []:
        dish_copy = dict(dish)
        dish_id = dish.get("dish_id", "")
        if dish_id in price_map:
            dish_copy["channel_price_fen"] = price_map[dish_id]
        else:
            dish_copy["channel_price_fen"] = dish.get("price_fen", 0)
        dish_copy["channel"] = channel
        dishes_with_price.append(dish_copy)

    return {
        "store_id": store_id,
        "channel": channel,
        "dishes": dishes_with_price,
        "dish_count": len(dishes_with_price),
    }


# ─── 渠道差异价 ───


async def set_channel_price(
    db: AsyncSession,
    dish_id: str,
    channel: str,
    price_fen: int,
    tenant_id: str,
) -> dict:
    """设置菜品在某渠道的差异价。

    Args:
        db: 异步数据库会话
        dish_id: 菜品 ID
        channel: 渠道 dine_in/takeout/delivery/miniapp
        price_fen: 渠道售价（分）
        tenant_id: 租户 ID

    Returns:
        dict — 差异价记录
    """
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")
    if not dish_id:
        raise ValueError("dish_id 不能为空")
    if channel not in VALID_CHANNELS:
        raise ValueError(f"channel 必须为 {VALID_CHANNELS} 之一，收到: {channel!r}")
    if price_fen < 0:
        raise ValueError("price_fen 不能为负数")

    await _set_tenant(db, tenant_id)
    tenant_uuid = uuid.UUID(tenant_id)
    dish_uuid = uuid.UUID(dish_id)

    # upsert: 查找已有记录
    result = await db.execute(
        select(ChannelPrice)
        .where(ChannelPrice.tenant_id == tenant_uuid)
        .where(ChannelPrice.dish_id == dish_uuid)
        .where(ChannelPrice.channel == channel)
        .where(ChannelPrice.is_deleted == False)  # noqa: E712
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.price_fen = price_fen
        record = existing
    else:
        record = ChannelPrice(
            id=uuid.uuid4(),
            tenant_id=tenant_uuid,
            dish_id=dish_uuid,
            channel=channel,
            price_fen=price_fen,
        )
        db.add(record)

    await db.flush()

    log.info(
        "channel_price.set",
        tenant_id=tenant_id,
        dish_id=dish_id,
        channel=channel,
        price_fen=price_fen,
    )
    return {
        "dish_id": dish_id,
        "channel": channel,
        "price_fen": price_fen,
        "tenant_id": tenant_id,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


# ─── 季节菜单 ───


async def set_seasonal_menu(
    db: AsyncSession,
    store_id: str,
    season: str,
    dishes: list[dict],
    tenant_id: str,
) -> dict:
    """设置门店季节菜单。

    Args:
        db: 异步数据库会话
        store_id: 门店 ID
        season: 季节 spring/summer/autumn/winter
        dishes: 季节菜品列表，每项含 {"dish_id": str, ...}
        tenant_id: 租户 ID

    Returns:
        dict — 季节菜单记录
    """
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")
    if not store_id:
        raise ValueError("store_id 不能为空")
    if season not in VALID_SEASONS:
        raise ValueError(f"season 必须为 {VALID_SEASONS} 之一，收到: {season!r}")
    if not dishes:
        raise ValueError("dishes 不能为空列表")

    await _set_tenant(db, tenant_id)
    tenant_uuid = uuid.UUID(tenant_id)
    store_uuid = uuid.UUID(store_id)

    # upsert
    result = await db.execute(
        select(SeasonalMenu)
        .where(SeasonalMenu.tenant_id == tenant_uuid)
        .where(SeasonalMenu.store_id == store_uuid)
        .where(SeasonalMenu.season == season)
        .where(SeasonalMenu.is_deleted == False)  # noqa: E712
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.dishes = list(dishes)
        existing.dish_count = len(dishes)
        existing.status = "active"
        record = existing
    else:
        record = SeasonalMenu(
            id=uuid.uuid4(),
            tenant_id=tenant_uuid,
            store_id=store_uuid,
            season=season,
            dishes=list(dishes),
            dish_count=len(dishes),
            status="active",
        )
        db.add(record)

    await db.flush()

    log.info(
        "seasonal_menu.set",
        tenant_id=tenant_id,
        store_id=store_id,
        season=season,
        dish_count=len(dishes),
    )
    return {
        "store_id": store_id,
        "season": season,
        "dishes": list(dishes),
        "dish_count": len(dishes),
        "tenant_id": tenant_id,
        "status": "active",
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


async def get_seasonal_menu(
    db: AsyncSession,
    store_id: str,
    season: str,
    tenant_id: str,
) -> Optional[dict]:
    """获取门店季节菜单"""
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")

    await _set_tenant(db, tenant_id)
    tenant_uuid = uuid.UUID(tenant_id)
    store_uuid = uuid.UUID(store_id)

    result = await db.execute(
        select(SeasonalMenu)
        .where(SeasonalMenu.tenant_id == tenant_uuid)
        .where(SeasonalMenu.store_id == store_uuid)
        .where(SeasonalMenu.season == season)
        .where(SeasonalMenu.is_deleted == False)  # noqa: E712
    )
    record = result.scalar_one_or_none()
    if not record:
        return None

    return {
        "store_id": store_id,
        "season": season,
        "dishes": record.dishes or [],
        "dish_count": record.dish_count,
        "tenant_id": tenant_id,
        "status": record.status,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


# ─── 包厢菜单 ───


async def set_room_menu(
    db: AsyncSession,
    store_id: str,
    room_type: str,
    dishes: list[dict],
    tenant_id: str,
) -> dict:
    """设置门店包厢专属菜单。

    Args:
        db: 异步数据库会话
        store_id: 门店 ID
        room_type: 包厢类型 standard/vip/luxury/banquet
        dishes: 菜品列表
        tenant_id: 租户 ID

    Returns:
        dict — 包厢菜单记录
    """
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")
    if not store_id:
        raise ValueError("store_id 不能为空")
    if room_type not in VALID_ROOM_TYPES:
        raise ValueError(f"room_type 必须为 {VALID_ROOM_TYPES} 之一，收到: {room_type!r}")
    if not dishes:
        raise ValueError("dishes 不能为空列表")

    await _set_tenant(db, tenant_id)
    tenant_uuid = uuid.UUID(tenant_id)
    store_uuid = uuid.UUID(store_id)

    # upsert
    result = await db.execute(
        select(RoomMenu)
        .where(RoomMenu.tenant_id == tenant_uuid)
        .where(RoomMenu.store_id == store_uuid)
        .where(RoomMenu.room_type == room_type)
        .where(RoomMenu.is_deleted == False)  # noqa: E712
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.dishes = list(dishes)
        existing.dish_count = len(dishes)
        existing.status = "active"
        record = existing
    else:
        record = RoomMenu(
            id=uuid.uuid4(),
            tenant_id=tenant_uuid,
            store_id=store_uuid,
            room_type=room_type,
            dishes=list(dishes),
            dish_count=len(dishes),
            status="active",
        )
        db.add(record)

    await db.flush()

    log.info(
        "room_menu.set",
        tenant_id=tenant_id,
        store_id=store_id,
        room_type=room_type,
        dish_count=len(dishes),
    )
    return {
        "store_id": store_id,
        "room_type": room_type,
        "dishes": list(dishes),
        "dish_count": len(dishes),
        "tenant_id": tenant_id,
        "status": "active",
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


async def get_room_menu(
    db: AsyncSession,
    store_id: str,
    room_type: str,
    tenant_id: str,
) -> Optional[dict]:
    """获取门店包厢菜单"""
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")

    await _set_tenant(db, tenant_id)
    tenant_uuid = uuid.UUID(tenant_id)
    store_uuid = uuid.UUID(store_id)

    result = await db.execute(
        select(RoomMenu)
        .where(RoomMenu.tenant_id == tenant_uuid)
        .where(RoomMenu.store_id == store_uuid)
        .where(RoomMenu.room_type == room_type)
        .where(RoomMenu.is_deleted == False)  # noqa: E712
    )
    record = result.scalar_one_or_none()
    if not record:
        return None

    return {
        "store_id": store_id,
        "room_type": room_type,
        "dishes": record.dishes or [],
        "dish_count": record.dish_count,
        "tenant_id": tenant_id,
        "status": record.status,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


# ─── 宴席套餐（基于模板扩展） ───


async def create_banquet_package(
    db: AsyncSession,
    name: str,
    dishes: list[dict],
    package_price_fen: int,
    guest_count: int,
    tenant_id: str,
    *,
    description: Optional[str] = None,
) -> dict:
    """创建宴席套餐。

    Args:
        db: 异步数据库会话
        name: 套餐名称
        dishes: 菜品列表
        package_price_fen: 套餐总价（分）
        guest_count: 适用人数
        tenant_id: 租户 ID
        description: 套餐描述

    Returns:
        dict — 宴席套餐记录
    """
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")
    if not name or not name.strip():
        raise ValueError("name 不能为空")
    if not dishes:
        raise ValueError("dishes 不能为空列表")
    if package_price_fen < 0:
        raise ValueError("package_price_fen 不能为负数")
    if guest_count <= 0:
        raise ValueError("guest_count 必须大于 0")

    await _set_tenant(db, tenant_id)

    # 宴席套餐底层复用模板机制，存入同一张表
    tpl = MenuTemplate(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(tenant_id),
        name=name.strip(),
        dishes=list(dishes),
        rules={
            "type": "banquet",
            "package_price_fen": package_price_fen,
            "guest_count": guest_count,
            "description": description,
        },
        status="draft",
        published_stores=[],
        package_price_fen=package_price_fen,
        guest_count=guest_count,
        description=description,
    )
    db.add(tpl)
    await db.flush()

    result = _model_to_template_dict(tpl)
    # 保持与旧接口兼容的额外字段
    result["package_price_fen"] = package_price_fen
    result["guest_count"] = guest_count
    result["description"] = description

    log.info(
        "banquet_package.created",
        tenant_id=tenant_id,
        template_id=str(tpl.id),
        guest_count=guest_count,
        price_fen=package_price_fen,
    )
    return result
