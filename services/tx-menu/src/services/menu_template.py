"""菜单模板管理 — 已迁移到 DB（v095）

本文件的内存实现已由 menu_template_repository.MenuTemplateRepository 替代。
路由层（menu_routes.py）已切换到 Repository，本文件不再被导入。

保留原因：
  1. _clear_all() 供旧版单元测试调用（待测试迁移后删除）
  2. 作为迁移前的历史参考
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog

log = structlog.get_logger()

# ─── 渠道常量 ───
VALID_CHANNELS = {"dine_in", "takeout", "delivery", "miniapp"}

# ─── 季节常量 ───
VALID_SEASONS = {"spring", "summer", "autumn", "winter"}

# ─── 包厢类型常量 ───
VALID_ROOM_TYPES = {"standard", "vip", "luxury", "banquet"}

# ─── In-Memory Storage ───
_templates: dict[str, dict] = {}           # template_id → template
_store_menus: dict[str, dict] = {}         # "{store_id}:{tenant_id}" → published menu
_channel_prices: dict[str, dict] = {}      # "{dish_id}:{channel}:{tenant_id}" → price record
_seasonal_menus: dict[str, dict] = {}      # "{store_id}:{season}:{tenant_id}" → seasonal menu
_room_menus: dict[str, dict] = {}          # "{store_id}:{room_type}:{tenant_id}" → room menu


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── 菜单模板 ───


def create_template(
    name: str,
    dishes: list[dict],
    rules: Optional[dict] = None,
    tenant_id: str = "",
) -> dict:
    """创建菜单模板。

    Args:
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

    template_id = str(uuid.uuid4())
    now = _now_iso()

    template = {
        "template_id": template_id,
        "name": name.strip(),
        "dishes": list(dishes),
        "rules": rules or {},
        "tenant_id": tenant_id,
        "status": "draft",
        "published_stores": [],
        "created_at": now,
        "updated_at": now,
    }

    _templates[template_id] = template
    log.info("menu_template.created", tenant_id=tenant_id, template_id=template_id, dish_count=len(dishes))
    return template


def get_template(template_id: str, tenant_id: str) -> Optional[dict]:
    """获取模板详情"""
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")
    tpl = _templates.get(template_id)
    if tpl and tpl["tenant_id"] == tenant_id:
        return tpl
    return None


def list_templates(tenant_id: str) -> list[dict]:
    """列出租户的所有菜单模板"""
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")
    return [t for t in _templates.values() if t["tenant_id"] == tenant_id]


# ─── 门店发布 ───


def publish_to_store(template_id: str, store_id: str, tenant_id: str) -> dict:
    """将菜单模板发布到门店。

    Args:
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

    template = _templates.get(template_id)
    if not template or template["tenant_id"] != tenant_id:
        raise ValueError(f"模板不存在: {template_id}")

    now = _now_iso()
    menu_key = f"{store_id}:{tenant_id}"

    published_menu = {
        "store_id": store_id,
        "tenant_id": tenant_id,
        "template_id": template_id,
        "template_name": template["name"],
        "dishes": list(template["dishes"]),
        "published_at": now,
        "status": "active",
    }

    _store_menus[menu_key] = published_menu

    # 更新模板的已发布门店列表
    if store_id not in template["published_stores"]:
        template["published_stores"].append(store_id)
    template["status"] = "published"
    template["updated_at"] = now

    log.info(
        "menu_template.published",
        tenant_id=tenant_id,
        template_id=template_id,
        store_id=store_id,
        dish_count=len(template["dishes"]),
    )

    return {
        "store_id": store_id,
        "template_id": template_id,
        "dish_count": len(template["dishes"]),
        "published_at": now,
        "status": "success",
    }


# ─── 门店菜单查询（按渠道） ───


def get_store_menu(store_id: str, channel: str, tenant_id: str) -> dict:
    """获取门店当前菜单（按渠道）。

    根据渠道差异价调整菜品价格，未设置差异价则使用原价。

    Args:
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

    menu_key = f"{store_id}:{tenant_id}"
    menu = _store_menus.get(menu_key)

    if not menu:
        return {
            "store_id": store_id,
            "channel": channel,
            "dishes": [],
            "dish_count": 0,
        }

    # 应用渠道差异价
    dishes_with_price = []
    for dish in menu["dishes"]:
        dish_copy = dict(dish)
        price_key = f"{dish.get('dish_id', '')}:{channel}:{tenant_id}"
        channel_price = _channel_prices.get(price_key)
        if channel_price:
            dish_copy["channel_price_fen"] = channel_price["price_fen"]
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


def set_channel_price(
    dish_id: str,
    channel: str,
    price_fen: int,
    tenant_id: str,
) -> dict:
    """设置菜品在某渠道的差异价。

    Args:
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

    now = _now_iso()
    price_key = f"{dish_id}:{channel}:{tenant_id}"

    record = {
        "dish_id": dish_id,
        "channel": channel,
        "price_fen": price_fen,
        "tenant_id": tenant_id,
        "updated_at": now,
    }

    _channel_prices[price_key] = record
    log.info(
        "channel_price.set",
        tenant_id=tenant_id,
        dish_id=dish_id,
        channel=channel,
        price_fen=price_fen,
    )
    return record


# ─── 季节菜单 ───


def set_seasonal_menu(
    store_id: str,
    season: str,
    dishes: list[dict],
    tenant_id: str,
) -> dict:
    """设置门店季节菜单。

    Args:
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

    now = _now_iso()
    key = f"{store_id}:{season}:{tenant_id}"

    record = {
        "store_id": store_id,
        "season": season,
        "dishes": list(dishes),
        "dish_count": len(dishes),
        "tenant_id": tenant_id,
        "status": "active",
        "updated_at": now,
    }

    _seasonal_menus[key] = record
    log.info(
        "seasonal_menu.set",
        tenant_id=tenant_id,
        store_id=store_id,
        season=season,
        dish_count=len(dishes),
    )
    return record


def get_seasonal_menu(store_id: str, season: str, tenant_id: str) -> Optional[dict]:
    """获取门店季节菜单"""
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")
    key = f"{store_id}:{season}:{tenant_id}"
    return _seasonal_menus.get(key)


# ─── 包厢菜单 ───


def set_room_menu(
    store_id: str,
    room_type: str,
    dishes: list[dict],
    tenant_id: str,
) -> dict:
    """设置门店包厢专属菜单。

    Args:
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

    now = _now_iso()
    key = f"{store_id}:{room_type}:{tenant_id}"

    record = {
        "store_id": store_id,
        "room_type": room_type,
        "dishes": list(dishes),
        "dish_count": len(dishes),
        "tenant_id": tenant_id,
        "status": "active",
        "updated_at": now,
    }

    _room_menus[key] = record
    log.info(
        "room_menu.set",
        tenant_id=tenant_id,
        store_id=store_id,
        room_type=room_type,
        dish_count=len(dishes),
    )
    return record


def get_room_menu(store_id: str, room_type: str, tenant_id: str) -> Optional[dict]:
    """获取门店包厢菜单"""
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")
    key = f"{store_id}:{room_type}:{tenant_id}"
    return _room_menus.get(key)


# ─── 宴席套餐（基于模板扩展） ───


def create_banquet_package(
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

    # 宴席套餐底层复用模板机制
    template = create_template(
        name=name,
        dishes=dishes,
        rules={
            "type": "banquet",
            "package_price_fen": package_price_fen,
            "guest_count": guest_count,
            "description": description,
        },
        tenant_id=tenant_id,
    )
    template["package_price_fen"] = package_price_fen
    template["guest_count"] = guest_count
    template["description"] = description

    log.info(
        "banquet_package.created",
        tenant_id=tenant_id,
        template_id=template["template_id"],
        guest_count=guest_count,
        price_fen=package_price_fen,
    )
    return template


# ─── 测试工具 ───


def _clear_all() -> None:
    """清空所有内部存储，仅供测试用"""
    _templates.clear()
    _store_menus.clear()
    _channel_prices.clear()
    _seasonal_menus.clear()
    _room_menus.clear()
