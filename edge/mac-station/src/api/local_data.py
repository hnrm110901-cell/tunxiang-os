"""本地数据 API — 门店实时数据直查

端点：
  GET  /api/v1/local/orders/today   今日订单（本地PG直查）
  GET  /api/v1/local/menu           当前菜单（本地缓存）
  GET  /api/v1/local/tables         桌台状态（本地实时）
  GET  /api/v1/local/inventory      库存（本地PG）
  POST /api/v1/local/orders         下单（离线时写入队列）

Mock 模式：不依赖真实 PG，返回模拟数据。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from config import get_config
from fastapi import APIRouter, Query
from services.offline_cache import get_offline_cache

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/local", tags=["local-data"])


# ── Mock 数据工厂 ──


def _mock_today_orders(store_id: str) -> list[dict[str, Any]]:
    """生成 Mock 今日订单。"""
    now = datetime.now(tz=timezone.utc).isoformat()
    return [
        {
            "order_id": "ord_mock_001",
            "order_no": "20260402001",
            "table_id": "table_03",
            "status": "paid",
            "total_amount_fen": 12800,
            "item_count": 4,
            "created_at": now,
            "source": "mock",
        },
        {
            "order_id": "ord_mock_002",
            "order_no": "20260402002",
            "table_id": "table_07",
            "status": "preparing",
            "total_amount_fen": 8600,
            "item_count": 3,
            "created_at": now,
            "source": "mock",
        },
        {
            "order_id": "ord_mock_003",
            "order_no": "20260402003",
            "table_id": "table_01",
            "status": "pending",
            "total_amount_fen": 5400,
            "item_count": 2,
            "created_at": now,
            "source": "mock",
        },
    ]


def _mock_menu() -> list[dict[str, Any]]:
    """生成 Mock 菜单。"""
    return [
        {
            "dish_id": "dish_001",
            "name": "红烧肉",
            "price_fen": 6800,
            "category": "热菜",
            "available": True,
            "sold_out": False,
        },
        {
            "dish_id": "dish_002",
            "name": "宫保鸡丁",
            "price_fen": 4800,
            "category": "热菜",
            "available": True,
            "sold_out": False,
        },
        {
            "dish_id": "dish_003",
            "name": "麻婆豆腐",
            "price_fen": 2800,
            "category": "热菜",
            "available": True,
            "sold_out": False,
        },
        {
            "dish_id": "dish_004",
            "name": "酸辣土豆丝",
            "price_fen": 1800,
            "category": "凉菜",
            "available": True,
            "sold_out": False,
        },
        {
            "dish_id": "dish_005",
            "name": "番茄蛋汤",
            "price_fen": 1200,
            "category": "汤类",
            "available": True,
            "sold_out": False,
        },
        {
            "dish_id": "dish_006",
            "name": "蛋炒饭",
            "price_fen": 1500,
            "category": "主食",
            "available": True,
            "sold_out": False,
        },
        {
            "dish_id": "dish_007",
            "name": "水煮鱼",
            "price_fen": 7800,
            "category": "热菜",
            "available": True,
            "sold_out": True,
        },
    ]


def _mock_tables() -> list[dict[str, Any]]:
    """生成 Mock 桌台状态。"""
    return [
        {
            "table_id": "table_01",
            "table_no": "A1",
            "seats": 4,
            "status": "occupied",
            "current_order_id": "ord_mock_003",
            "occupied_since": "2026-04-02T11:30:00Z",
        },
        {
            "table_id": "table_02",
            "table_no": "A2",
            "seats": 4,
            "status": "free",
            "current_order_id": None,
            "occupied_since": None,
        },
        {
            "table_id": "table_03",
            "table_no": "A3",
            "seats": 6,
            "status": "free",
            "current_order_id": None,
            "occupied_since": None,
        },
        {
            "table_id": "table_04",
            "table_no": "B1",
            "seats": 2,
            "status": "reserved",
            "current_order_id": None,
            "occupied_since": None,
        },
        {
            "table_id": "table_05",
            "table_no": "B2",
            "seats": 2,
            "status": "free",
            "current_order_id": None,
            "occupied_since": None,
        },
        {
            "table_id": "table_06",
            "table_no": "C1",
            "seats": 8,
            "status": "occupied",
            "current_order_id": "ord_mock_002",
            "occupied_since": "2026-04-02T11:45:00Z",
        },
        {
            "table_id": "table_07",
            "table_no": "C2",
            "seats": 10,
            "status": "free",
            "current_order_id": None,
            "occupied_since": None,
        },
    ]


def _mock_inventory(store_id: str) -> list[dict[str, Any]]:
    """生成 Mock 库存。"""
    return [
        {
            "ingredient_id": "ing_001",
            "name": "五花肉",
            "unit": "kg",
            "quantity": 15.5,
            "min_stock": 5.0,
            "is_low": False,
            "category": "肉类",
        },
        {
            "ingredient_id": "ing_002",
            "name": "鸡胸肉",
            "unit": "kg",
            "quantity": 3.2,
            "min_stock": 5.0,
            "is_low": True,
            "category": "肉类",
        },
        {
            "ingredient_id": "ing_003",
            "name": "豆腐",
            "unit": "kg",
            "quantity": 8.0,
            "min_stock": 3.0,
            "is_low": False,
            "category": "豆制品",
        },
        {
            "ingredient_id": "ing_004",
            "name": "土豆",
            "unit": "kg",
            "quantity": 12.0,
            "min_stock": 5.0,
            "is_low": False,
            "category": "蔬菜",
        },
        {
            "ingredient_id": "ing_005",
            "name": "鸡蛋",
            "unit": "个",
            "quantity": 45.0,
            "min_stock": 30.0,
            "is_low": False,
            "category": "蛋类",
        },
        {
            "ingredient_id": "ing_006",
            "name": "草鱼",
            "unit": "kg",
            "quantity": 1.5,
            "min_stock": 3.0,
            "is_low": True,
            "category": "水产",
        },
    ]


# ── 端点 ──


@router.get("/orders/today", summary="今日订单")
async def get_today_orders(
    store_id: str = Query("", description="门店ID（为空则取配置默认值）"),
    status: str = Query("", description="按状态过滤: pending/preparing/ready/paid/cancelled"),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """从本地 PG 查询今日订单。

    Mock 模式下返回模拟数据。
    """
    cfg = get_config()
    sid = store_id or cfg.store_id

    # TODO: 接入本地 PG 真实查询（替换 Mock）
    orders = _mock_today_orders(sid)

    if status:
        orders = [o for o in orders if o["status"] == status]

    orders = orders[:limit]

    logger.info("local_orders_today", store_id=sid, count=len(orders), status=status or "all")
    return {
        "ok": True,
        "data": {
            "store_id": sid,
            "date": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d"),
            "orders": orders,
            "total": len(orders),
            "source": "mock",
        },
    }


@router.get("/menu", summary="当前菜单")
async def get_menu(
    store_id: str = Query("", description="门店ID"),
    category: str = Query("", description="按分类过滤"),
) -> dict[str, Any]:
    """获取当前门店菜单。

    优先从本地缓存读取，缓存未命中则查本地 PG。
    Mock 模式下返回模拟菜单。
    """
    cfg = get_config()
    sid = store_id or cfg.store_id
    cache = get_offline_cache()

    # 尝试读缓存
    cache_key = f"menu:{sid}"
    cached = cache.cache_get(cache_key)
    if cached is not None:
        logger.debug("local_menu_cache_hit", store_id=sid)
        items = cached.get("items", [])
        if category:
            items = [d for d in items if d.get("category") == category]
        return {
            "ok": True,
            "data": {
                "store_id": sid,
                "items": items,
                "total": len(items),
                "source": "cache",
            },
        }

    # TODO: 接入本地 PG 真实查询
    items = _mock_menu()

    # 写入缓存
    cache.cache_set(cache_key, {"items": items})

    if category:
        items = [d for d in items if d.get("category") == category]

    logger.info("local_menu_loaded", store_id=sid, total=len(items))
    return {
        "ok": True,
        "data": {
            "store_id": sid,
            "items": items,
            "total": len(items),
            "source": "mock",
        },
    }


@router.get("/tables", summary="桌台状态")
async def get_tables(
    store_id: str = Query("", description="门店ID"),
    status: str = Query("", description="按状态过滤: free/occupied/reserved"),
) -> dict[str, Any]:
    """获取门店桌台实时状态。

    Mock 模式下返回模拟数据。
    """
    cfg = get_config()
    sid = store_id or cfg.store_id

    # TODO: 接入本地 PG 真实查询
    tables = _mock_tables()

    if status:
        tables = [t for t in tables if t["status"] == status]

    summary = {
        "total": len(_mock_tables()),
        "free": sum(1 for t in _mock_tables() if t["status"] == "free"),
        "occupied": sum(1 for t in _mock_tables() if t["status"] == "occupied"),
        "reserved": sum(1 for t in _mock_tables() if t["status"] == "reserved"),
    }

    logger.info("local_tables_queried", store_id=sid, count=len(tables))
    return {
        "ok": True,
        "data": {
            "store_id": sid,
            "tables": tables,
            "summary": summary,
            "source": "mock",
        },
    }


@router.get("/inventory", summary="库存查询")
async def get_inventory(
    store_id: str = Query("", description="门店ID"),
    low_stock_only: bool = Query(False, description="仅返回低库存项"),
) -> dict[str, Any]:
    """获取门店库存数据。

    Mock 模式下返回模拟数据。
    """
    cfg = get_config()
    sid = store_id or cfg.store_id

    # TODO: 接入本地 PG 真实查询
    items = _mock_inventory(sid)

    if low_stock_only:
        items = [i for i in items if i["is_low"]]

    logger.info("local_inventory_queried", store_id=sid, total=len(items), low_stock_only=low_stock_only)
    return {
        "ok": True,
        "data": {
            "store_id": sid,
            "items": items,
            "total": len(items),
            "low_stock_count": sum(1 for i in items if i["is_low"]),
            "source": "mock",
        },
    }


@router.post("/orders", summary="下单")
async def create_order(data: dict[str, Any]) -> dict[str, Any]:
    """创建新订单。

    在线模式：转发到云端 tx-trade 创建订单。
    离线模式：写入本地离线队列，恢复连接后自动同步。
    """
    cfg = get_config()
    cache = get_offline_cache()

    store_id = data.get("store_id") or cfg.store_id
    table_id = data.get("table_id", "")
    items = data.get("items", [])

    if not items:
        return {
            "ok": False,
            "error": {"code": "EMPTY_ORDER", "message": "订单项不能为空"},
        }

    order_id = f"ord_{uuid.uuid4().hex[:12]}"
    now = datetime.now(tz=timezone.utc).isoformat()

    order_payload = {
        "order_id": order_id,
        "store_id": store_id,
        "tenant_id": cfg.tenant_id,
        "table_id": table_id,
        "items": items,
        "status": "pending",
        "created_at": now,
    }

    if cfg.offline:
        # 离线模式 → 写入队列
        entry = cache.enqueue_write(
            operation="create_order",
            endpoint="/api/v1/orders",
            method="POST",
            payload=order_payload,
            store_id=store_id,
            tenant_id=cfg.tenant_id,
        )
        logger.info(
            "local_order_created_offline",
            order_id=order_id,
            queue_entry=entry.entry_id,
            item_count=len(items),
        )
        return {
            "ok": True,
            "data": {
                "order_id": order_id,
                "status": "pending",
                "mode": "offline",
                "queue_entry_id": entry.entry_id,
                "message": "订单已缓存，恢复网络后自动同步",
            },
        }

    # 在线模式 → 转发到云端（Mock 模式下直接返回成功）
    # TODO: 接入真实云端 API 转发
    logger.info(
        "local_order_created_online",
        order_id=order_id,
        item_count=len(items),
    )
    return {
        "ok": True,
        "data": {
            "order_id": order_id,
            "status": "pending",
            "mode": "online",
            "source": "mock",
            "message": "订单已创建（Mock模式）",
        },
    }
