"""数字菜单展示屏 API 路由

提供菜单大屏所需的全部数据接口：
  GET  /api/v1/menu/board-data          → 当前菜单数据（含库存状态）
  GET  /api/v1/menu/board-config        → 展示配置（分类顺序、特价菜、推荐菜）
  POST /api/v1/menu/board-announcement  → 更新公告内容，通过 Redis Pub/Sub 广播

WS /ws/menu-board-updates 由 mac-station 转发 Redis 消息到前端。
"""
import json
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db

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
        import redis.asyncio as aioredis  # type: ignore
        import os
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

    # TODO: 从数据库查询真实菜单数据
    # dishes = await dish_repo.get_board_dishes(db, tenant_id=x_tenant_id, store_id=store_id)
    mock_dishes = [
        {
            "id": "d1",
            "name": "宫保鸡丁",
            "price": 3800,
            "original_price": None,
            "image_url": None,
            "category": "热菜",
            "is_available": True,
            "is_new": False,
            "is_special": False,
        },
        {
            "id": "d2",
            "name": "佛跳墙",
            "price": 18800,
            "original_price": 22800,
            "image_url": None,
            "category": "热菜",
            "is_available": True,
            "is_new": False,
            "is_special": True,
        },
        {
            "id": "d3",
            "name": "清蒸鲈鱼",
            "price": 9800,
            "original_price": None,
            "image_url": None,
            "category": "海鲜",
            "is_available": False,
            "is_new": False,
            "is_special": False,
        },
        {
            "id": "d4",
            "name": "醉鹅",
            "price": 8800,
            "original_price": None,
            "image_url": None,
            "category": "热菜",
            "is_available": True,
            "is_new": True,
            "is_special": False,
        },
    ]

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "dishes": mock_dishes,
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

    # TODO: 从数据库查询门店菜单屏配置
    config = {
        "store_name": "屯象餐厅",
        "logo_url": None,
        "announcement": "今日特供：佛跳墙限量10份 · 营业时间 10:00–22:00 · 服务电话 400-888-8888 · 欢迎光临，祝您用餐愉快！",
        "category_order": ["热菜", "海鲜", "凉菜", "主食", "汤品", "饮品"],
        "featured_dish_ids": ["d4"],
        "special_dish_ids": ["d2"],
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

    # TODO: 持久化公告到数据库（下次 board-config 接口能读到）

    return {
        "ok": True,
        "data": {
            "store_id": body.store_id,
            "announcement": body.announcement,
            "broadcast_ok": published,
            "channel": channel,
        },
    }
