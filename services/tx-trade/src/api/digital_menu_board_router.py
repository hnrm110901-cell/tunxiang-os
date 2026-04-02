"""数字菜单展示屏 API 路由

提供菜单大屏所需的全部数据接口：
  GET  /api/v1/menu/board-data          → 当前菜单数据（含库存状态）
  GET  /api/v1/menu/board-config        → 展示配置（分类顺序、特价菜、推荐菜）
  POST /api/v1/menu/board-announcement  → 更新公告内容，通过 Redis Pub/Sub 广播

WS /ws/menu-board-updates 由 mac-station 转发 Redis 消息到前端。
"""
import json
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from shared.ontology.src.entities import Dish, DishCategory, Store

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/menu", tags=["digital-menu-board"])


# ─── Pydantic models ───

class DishBoardItem(BaseModel):
    id: str
    name: str
    price: int             # 分
    original_price: Optional[int] = None
    image_url: Optional[str] = None
    category: str
    is_available: bool
    is_new: bool = False
    is_special: bool = False


class BoardDataResponse(BaseModel):
    store_id: str
    dishes: list[DishBoardItem]


class BoardConfigResponse(BaseModel):
    store_name: str
    logo_url: Optional[str] = None
    announcement: str
    category_order: list[str]
    featured_dish_ids: list[str] = []
    special_dish_ids: list[str] = []


class UpdateAnnouncementRequest(BaseModel):
    store_id: str
    announcement: str


# ─── Redis helper（可选依赖，不可用时降级为 noop） ───

async def _publish_to_redis(channel: str, message: dict) -> bool:
    """向 Redis Pub/Sub 发布消息，供 mac-station WS 转发到前端。

    Redis 不可用时仅记录警告，不抛异常。
    """
    try:
        import os

        import redis.asyncio as aioredis  # type: ignore
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        async with aioredis.from_url(redis_url, decode_responses=True) as client:
            await client.publish(channel, json.dumps(message, ensure_ascii=False))
        return True
    except ImportError:
        logger.warning("redis_not_installed", channel=channel)
        return False
    except (ConnectionError, OSError) as e:
        logger.warning("redis_publish_failed", channel=channel, error=str(e))
        return False


# ─── Endpoints ───

@router.get("/board-data", response_model=dict)
async def get_board_data(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """返回当前门店菜单数据（含库存/沽清状态）。

    TODO: 接入菜品表和库存表进行真实查询。
    目前返回结构化示例数据供前端开发对接。
    """
    logger.info("board_data_requested", store_id=store_id, tenant_id=x_tenant_id)

    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": x_tenant_id},
    )
    tid = uuid.UUID(x_tenant_id)
    sid = uuid.UUID(store_id)

    result = await db.execute(
        select(Dish, DishCategory.name)
        .outerjoin(DishCategory, Dish.category_id == DishCategory.id)
        .where(
            Dish.tenant_id == tid,
            Dish.is_deleted.is_(False),
            (Dish.store_id == sid) | (Dish.store_id.is_(None)),
        )
        .order_by(DishCategory.sort_order, Dish.dish_name)
    )
    rows = result.all()
    dishes = [
        {
            "id": str(dish.id),
            "name": dish.dish_name,
            "price": dish.price_fen,
            "original_price": dish.original_price_fen,
            "image_url": dish.image_url,
            "category": category_name or "其他",
            "is_available": dish.is_available,
            "is_new": bool(dish.tags and "新品" in dish.tags),
            "is_special": bool(dish.tags and "特价" in dish.tags),
        }
        for dish, category_name in rows
    ]

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "dishes": dishes,
        },
    }


@router.get("/board-config", response_model=dict)
async def get_board_config(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """返回菜单大屏展示配置（分类顺序、特价菜、推荐菜）。

    TODO: 接入门店配置表进行真实查询。
    """
    logger.info("board_config_requested", store_id=store_id, tenant_id=x_tenant_id)

    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": x_tenant_id},
    )
    tid = uuid.UUID(x_tenant_id)
    sid = uuid.UUID(store_id)

    store_result = await db.execute(
        select(Store.store_name, Store.config).where(Store.id == sid, Store.tenant_id == tid)
    )
    store_row = store_result.one_or_none()
    store_name = store_row[0] if store_row else "屯象餐厅"
    store_config = store_row[1] if store_row else {}
    announcement = (store_config or {}).get("board_announcement", "")

    cat_result = await db.execute(
        select(DishCategory.name)
        .where(DishCategory.tenant_id == tid, DishCategory.is_active.is_(True))
        .order_by(DishCategory.sort_order)
    )
    category_order = [r for (r,) in cat_result.all()] or ["热菜", "海鲜", "凉菜", "主食", "汤品", "饮品"]

    special_result = await db.execute(
        select(Dish.id)
        .where(
            Dish.tenant_id == tid,
            Dish.is_deleted.is_(False),
            Dish.is_available.is_(True),
            text("tags @> ARRAY['特价']"),
        )
    )
    special_ids = [str(r) for (r,) in special_result.all()]

    featured_result = await db.execute(
        select(Dish.id)
        .where(
            Dish.tenant_id == tid,
            Dish.is_deleted.is_(False),
            Dish.is_available.is_(True),
            text("tags @> ARRAY['新品']"),
        )
    )
    featured_ids = [str(r) for (r,) in featured_result.all()]

    config = {
        "store_name": store_name,
        "logo_url": None,
        "announcement": announcement,
        "category_order": category_order,
        "featured_dish_ids": featured_ids,
        "special_dish_ids": special_ids,
    }

    return {"ok": True, "data": config}


@router.post("/board-announcement", response_model=dict)
async def update_board_announcement(
    body: UpdateAnnouncementRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新公告内容，通过 Redis Pub/Sub 广播到 mac-station WS，
    mac-station 再转发到所有订阅 /ws/menu-board-updates 的前端。

    广播的 WS 消息格式：
        { "event": "announcement_update", "data": { "announcement": "..." } }
    """
    if not body.announcement.strip():
        raise HTTPException(status_code=400, detail="公告内容不能为空")

    logger.info(
        "board_announcement_update",
        store_id=body.store_id,
        tenant_id=x_tenant_id,
        announcement_len=len(body.announcement),
    )

    channel = f"menu_board:{x_tenant_id}:{body.store_id}"
    ws_message = {
        "event": "announcement_update",
        "data": {"announcement": body.announcement},
    }
    published = await _publish_to_redis(channel, ws_message)

    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": x_tenant_id},
    )
    await db.execute(
        text("""
            UPDATE stores
               SET config = COALESCE(config, '{}') || jsonb_build_object('board_announcement', :msg)
             WHERE id = :sid::uuid AND tenant_id = :tid::uuid
        """),
        {"tid": x_tenant_id, "sid": body.store_id, "msg": body.announcement},
    )
    await db.commit()

    return {
        "ok": True,
        "data": {
            "store_id": body.store_id,
            "announcement": body.announcement,
            "broadcast_ok": published,
            "channel": channel,
        },
    }
