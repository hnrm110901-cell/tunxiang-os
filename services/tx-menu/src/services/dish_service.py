"""菜品档案服务 — CRUD + 按类别/状态/季节筛选

菜品状态: active / inactive / seasonal / sold_out
价格单位: 分(fen)
所有操作强制 tenant_id 租户隔离。
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog

log = structlog.get_logger()

# ─── 菜品状态常量 ───
DISH_STATUS_ACTIVE = "active"
DISH_STATUS_INACTIVE = "inactive"
DISH_STATUS_SEASONAL = "seasonal"
DISH_STATUS_SOLD_OUT = "sold_out"
VALID_DISH_STATUSES = {DISH_STATUS_ACTIVE, DISH_STATUS_INACTIVE, DISH_STATUS_SEASONAL, DISH_STATUS_SOLD_OUT}

# ─── 季节常量 ───
VALID_SEASONS = {"spring", "summer", "autumn", "winter"}

# ─── In-Memory Storage (可替换为 DishRepository) ───
_dishes: dict[str, dict] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_status(*, is_available: bool = True, is_seasonal: bool = False) -> str:
    """根据字段推导菜品状态"""
    if is_seasonal:
        return DISH_STATUS_SEASONAL
    if not is_available:
        return DISH_STATUS_INACTIVE
    return DISH_STATUS_ACTIVE


# ─── CRUD ───


def create_dish(
    *,
    tenant_id: str,
    dish_name: str,
    dish_code: str,
    price_fen: int,
    category_id: Optional[str] = None,
    store_id: Optional[str] = None,
    description: Optional[str] = None,
    image_url: Optional[str] = None,
    kitchen_station: Optional[str] = None,
    preparation_time: Optional[int] = None,
    unit: str = "份",
    spicy_level: int = 0,
    cost_fen: Optional[int] = None,
    tags: Optional[list[str]] = None,
    season: Optional[str] = None,
    is_seasonal: bool = False,
) -> dict:
    """创建菜品档案。

    Args:
        tenant_id: 租户 ID
        dish_name: 菜品名称
        dish_code: 菜品编码（唯一）
        price_fen: 售价（分）
        category_id: 分类 ID
        store_id: 门店 ID，NULL=集团通用
        description: 菜品描述
        image_url: 图片地址
        kitchen_station: 档口
        preparation_time: 制作时间（分钟）
        unit: 单位，默认"份"
        spicy_level: 辣度 0-5
        cost_fen: 成本（分）
        tags: 标签列表
        season: 季节 spring/summer/autumn/winter
        is_seasonal: 是否季节限定

    Returns:
        dict — 完整菜品档案
    """
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")
    if not dish_name or not dish_name.strip():
        raise ValueError("dish_name 不能为空")
    if not dish_code or not dish_code.strip():
        raise ValueError("dish_code 不能为空")
    if price_fen < 0:
        raise ValueError("price_fen 不能为负数")
    if season and season not in VALID_SEASONS:
        raise ValueError(f"season 必须为 {VALID_SEASONS} 之一，收到: {season!r}")

    # 检查 dish_code 唯一
    for d in _dishes.values():
        if d["dish_code"] == dish_code and d["tenant_id"] == tenant_id:
            raise ValueError(f"dish_code 已存在: {dish_code}")

    dish_id = str(uuid.uuid4())
    now = _now_iso()
    status = _resolve_status(is_available=True, is_seasonal=is_seasonal)

    dish = {
        "id": dish_id,
        "tenant_id": tenant_id,
        "store_id": store_id,
        "dish_name": dish_name.strip(),
        "dish_code": dish_code.strip(),
        "price_fen": price_fen,
        "cost_fen": cost_fen,
        "category_id": category_id,
        "description": description,
        "image_url": image_url,
        "kitchen_station": kitchen_station,
        "preparation_time": preparation_time,
        "unit": unit,
        "spicy_level": spicy_level,
        "tags": tags or [],
        "season": season,
        "is_seasonal": is_seasonal,
        "status": status,
        "is_available": True,
        "is_deleted": False,
        "sort_order": 0,
        "total_sales": 0,
        "total_revenue_fen": 0,
        "created_at": now,
        "updated_at": now,
    }

    _dishes[dish_id] = dish
    log.info("dish.created", tenant_id=tenant_id, dish_id=dish_id, dish_code=dish_code)
    return dish


def get_dish(dish_id: str, tenant_id: str) -> Optional[dict]:
    """获取单个菜品详情"""
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")
    dish = _dishes.get(dish_id)
    if dish and dish["tenant_id"] == tenant_id and not dish["is_deleted"]:
        return dish
    return None


def update_dish(dish_id: str, tenant_id: str, **updates) -> dict:
    """更新菜品档案。

    支持更新字段: dish_name, price_fen, cost_fen, description, image_url,
    kitchen_station, preparation_time, unit, spicy_level, tags, season,
    is_seasonal, is_available, sort_order, category_id
    """
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")
    dish = _dishes.get(dish_id)
    if not dish or dish["tenant_id"] != tenant_id or dish["is_deleted"]:
        raise ValueError(f"菜品不存在: {dish_id}")

    updatable = {
        "dish_name",
        "price_fen",
        "cost_fen",
        "description",
        "image_url",
        "kitchen_station",
        "preparation_time",
        "unit",
        "spicy_level",
        "tags",
        "season",
        "is_seasonal",
        "is_available",
        "sort_order",
        "category_id",
    }

    for key, value in updates.items():
        if key in updatable:
            dish[key] = value

    # 价格校验
    if "price_fen" in updates and updates["price_fen"] < 0:
        raise ValueError("price_fen 不能为负数")
    if "season" in updates and updates["season"] and updates["season"] not in VALID_SEASONS:
        raise ValueError(f"season 必须为 {VALID_SEASONS} 之一")

    # 重新推导状态（沽清状态由 stockout_sync 管理，不在此覆盖）
    if dish["status"] != DISH_STATUS_SOLD_OUT:
        dish["status"] = _resolve_status(
            is_available=dish["is_available"],
            is_seasonal=dish["is_seasonal"],
        )

    dish["updated_at"] = _now_iso()
    log.info("dish.updated", tenant_id=tenant_id, dish_id=dish_id, fields=list(updates.keys()))
    return dish


def delete_dish(dish_id: str, tenant_id: str) -> bool:
    """软删除菜品"""
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")
    dish = _dishes.get(dish_id)
    if not dish or dish["tenant_id"] != tenant_id or dish["is_deleted"]:
        return False
    dish["is_deleted"] = True
    dish["updated_at"] = _now_iso()
    log.info("dish.deleted", tenant_id=tenant_id, dish_id=dish_id)
    return True


# ─── 列表 & 筛选 ───


def list_dishes(
    tenant_id: str,
    *,
    store_id: Optional[str] = None,
    category_id: Optional[str] = None,
    status: Optional[str] = None,
    season: Optional[str] = None,
    keyword: Optional[str] = None,
    page: int = 1,
    size: int = 20,
) -> dict:
    """菜品列表，支持按类别/状态/季节/关键词筛选。

    Returns:
        {"items": [...], "total": int, "page": int, "size": int}
    """
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")
    if status and status not in VALID_DISH_STATUSES:
        raise ValueError(f"status 必须为 {VALID_DISH_STATUSES} 之一")

    candidates = [d for d in _dishes.values() if d["tenant_id"] == tenant_id and not d["is_deleted"]]

    # 筛选
    if store_id:
        candidates = [d for d in candidates if d.get("store_id") == store_id]
    if category_id:
        candidates = [d for d in candidates if d.get("category_id") == category_id]
    if status:
        candidates = [d for d in candidates if d["status"] == status]
    if season:
        candidates = [d for d in candidates if d.get("season") == season]
    if keyword:
        kw = keyword.lower()
        candidates = [d for d in candidates if kw in d["dish_name"].lower() or kw in d.get("dish_code", "").lower()]

    # 排序
    candidates.sort(key=lambda d: (d.get("sort_order", 0), d["created_at"]))

    total = len(candidates)
    start = (page - 1) * size
    items = candidates[start : start + size]

    return {"items": items, "total": total, "page": page, "size": size}


def list_dishes_by_category(tenant_id: str, category_id: str) -> list[dict]:
    """按分类查询所有可用菜品（不分页）"""
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")
    return [
        d
        for d in _dishes.values()
        if d["tenant_id"] == tenant_id
        and not d["is_deleted"]
        and d.get("category_id") == category_id
        and d["status"] in {DISH_STATUS_ACTIVE, DISH_STATUS_SEASONAL}
    ]


def list_dishes_by_status(tenant_id: str, status: str) -> list[dict]:
    """按状态查询菜品列表（不分页）"""
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")
    if status not in VALID_DISH_STATUSES:
        raise ValueError(f"status 必须为 {VALID_DISH_STATUSES} 之一")
    return [
        d for d in _dishes.values() if d["tenant_id"] == tenant_id and not d["is_deleted"] and d["status"] == status
    ]


def list_dishes_by_season(tenant_id: str, season: str) -> list[dict]:
    """按季节查询菜品"""
    if not tenant_id:
        raise ValueError("tenant_id 不能为空")
    if season not in VALID_SEASONS:
        raise ValueError(f"season 必须为 {VALID_SEASONS} 之一")
    return [
        d for d in _dishes.values() if d["tenant_id"] == tenant_id and not d["is_deleted"] and d.get("season") == season
    ]


# ─── 内部工具 ───


def _get_store() -> dict[str, dict]:
    """暴露内部存储，仅供测试用"""
    return _dishes


def _clear_store() -> None:
    """清空内部存储，仅供测试用"""
    _dishes.clear()
