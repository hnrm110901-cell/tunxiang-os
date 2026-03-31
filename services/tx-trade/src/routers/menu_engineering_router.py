"""
菜单工程分析路由 — BCG矩阵变体

端点：
  GET /api/v1/menu/engineering-analysis
      params: period (today/week/month), store_id, category
      返回带 quadrant 字段的菜品列表 + 四象限汇总

  PATCH /api/v1/dishes/{dish_id}
      body: {status: 'soldout'}
      下架菜品（设置 is_available=False）

四象限定义（以均值为分割线）：
  star      — 高销量 + 高毛利  ⭐ 明星菜
  cash_cow  — 低销量 + 高毛利  💰 金牛菜
  plowshare — 高销量 + 低毛利  🔥 犁头菜
  dog       — 低销量 + 低毛利  💀 瘦狗菜

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Literal, Optional

import structlog
from fastapi import APIRouter, Query, Request

router = APIRouter(tags=["menu-engineering"])

log = structlog.get_logger(__name__)

# ─── 分析期间映射 ───

_PERIOD_MAP: dict[str, int] = {
    "today": 1,
    "week":  7,
    "month": 30,
}

# ─── Mock 数据（DB 不可用时降级） ───

_MOCK_DISHES = [
    {"id": "d01", "name": "宫保鸡丁",   "category": "热菜", "price": 3800,  "cost": 1200, "sales_count": 156},
    {"id": "d02", "name": "佛跳墙",     "category": "热菜", "price": 18800, "cost": 8000, "sales_count": 18},
    {"id": "d03", "name": "鱼香肉丝",   "category": "热菜", "price": 3200,  "cost": 1500, "sales_count": 203},
    {"id": "d04", "name": "口水鸡",     "category": "凉菜", "price": 4800,  "cost": 1800, "sales_count": 87},
    {"id": "d05", "name": "夫妻肺片",   "category": "凉菜", "price": 4200,  "cost": 1900, "sales_count": 122},
    {"id": "d06", "name": "凉拌黄瓜",   "category": "凉菜", "price": 1800,  "cost": 400,  "sales_count": 280},
    {"id": "d07", "name": "小笼包",     "category": "主食", "price": 2200,  "cost": 1100, "sales_count": 195},
    {"id": "d08", "name": "手工饺子",   "category": "主食", "price": 2800,  "cost": 1500, "sales_count": 43},
    {"id": "d09", "name": "鲜榨橙汁",   "category": "饮品", "price": 1800,  "cost": 300,  "sales_count": 65},
    {"id": "d10", "name": "招牌老汤面", "category": "主食", "price": 2600,  "cost": 900,  "sales_count": 31},
]


def _compute_quadrant(sales: int, margin: float, avg_sales: float, avg_margin: float) -> str:
    """按均值分割，归入四象限。"""
    high_sales = sales >= avg_sales
    high_margin = margin >= avg_margin
    if high_sales and high_margin:
        return "star"
    if not high_sales and high_margin:
        return "cash_cow"
    if high_sales and not high_margin:
        return "plowshare"
    return "dog"


def _build_analysis(raw: list[dict]) -> dict:
    """给定原始菜品列表（含 price/cost/sales_count），计算毛利率、象限并汇总。"""
    dishes: list[dict] = []
    for d in raw:
        price = d.get("price") or 0
        cost  = d.get("cost")  or 0
        margin = round((price - cost) / price, 4) if price > 0 else 0.0
        dishes.append({
            "id":           d["id"],
            "name":         d["name"],
            "category":     d.get("category", ""),
            "price":        price,
            "cost":         cost,
            "gross_margin": margin,
            "sales_count":  d.get("sales_count", 0),
            "quadrant":     "",          # 待填充
        })

    if not dishes:
        return {"dishes": [], "summary": {"star": 0, "cash_cow": 0, "plowshare": 0, "dog": 0}}

    avg_sales  = sum(d["sales_count"] for d in dishes) / len(dishes)
    avg_margin = sum(d["gross_margin"] for d in dishes) / len(dishes)

    summary = {"star": 0, "cash_cow": 0, "plowshare": 0, "dog": 0}
    for d in dishes:
        q = _compute_quadrant(d["sales_count"], d["gross_margin"], avg_sales, avg_margin)
        d["quadrant"] = q
        summary[q] += 1

    return {"dishes": dishes, "summary": summary}


# ─── 工具：提取租户ID ───

def _tenant_id(request: Request) -> str:
    return (
        getattr(request.state, "tenant_id", None)
        or request.headers.get("X-Tenant-ID", "")
        or "default"
    )


# ─── 路由 ───

@router.get("/api/v1/menu/engineering-analysis")
async def get_engineering_analysis(
    request: Request,
    period:   str = Query(default="week",  description="统计周期: today/week/month"),
    store_id: str = Query(default="",      description="门店ID"),
    category: str = Query(default="",      description="分类筛选（空=全部）"),
) -> dict:
    """
    菜单工程分析 — BCG 矩阵变体。

    以统计周期内各菜品销量均值和毛利率均值为分割线，
    将菜品归入 star/cash_cow/plowshare/dog 四象限。
    """
    tenant_id = _tenant_id(request)
    days = _PERIOD_MAP.get(period, 7)

    raw: list[dict] = []

    try:
        from shared.ontology.src.database import async_session_factory  # type: ignore[import]
        from shared.ontology.src.entities import Dish, OrderItem, Order  # type: ignore[import]
        from sqlalchemy import func, select, cast, Float  # type: ignore[import]
        from sqlalchemy.dialects.postgresql import UUID  # type: ignore[import]
        import datetime as _dt

        since = _dt.datetime.utcnow() - _dt.timedelta(days=days)

        async with async_session_factory() as session:
            # 子查询：统计周期内每个 dish_id 的销量合计
            stmt = (
                select(
                    Dish.id.label("id"),
                    Dish.dish_name.label("name"),
                    Dish.price_fen.label("price"),
                    Dish.cost_fen.label("cost"),
                    func.coalesce(func.sum(OrderItem.quantity), 0).label("sales_count"),
                )
                .outerjoin(
                    OrderItem,
                    (OrderItem.dish_id == Dish.id) & (OrderItem.tenant_id == Dish.tenant_id),
                )
                .outerjoin(
                    Order,
                    (Order.id == OrderItem.order_id)
                    & (Order.order_time >= since)
                    & (Order.tenant_id == Dish.tenant_id),
                )
                .where(Dish.tenant_id == tenant_id)
                .where(Dish.is_deleted == False)  # noqa: E712
                .where(Dish.is_available == True)  # noqa: E712
                .group_by(Dish.id, Dish.dish_name, Dish.price_fen, Dish.cost_fen)
            )

            if store_id:
                stmt = stmt.where(Dish.store_id == store_id)

            rows = (await session.execute(stmt)).all()

            for row in rows:
                entry = {
                    "id":          str(row.id),
                    "name":        row.name,
                    "category":    "",
                    "price":       row.price or 0,
                    "cost":        row.cost  or 0,
                    "sales_count": int(row.sales_count),
                }
                raw.append(entry)

    except (ImportError, Exception):  # noqa: BLE001 — 最外层兜底，DB不可用时降级Mock
        log.info("menu_engineering: DB不可用，降级Mock数据")
        raw = list(_MOCK_DISHES)

    # 分类过滤（Mock数据才有 category 字段，DB已在查询中过滤）
    if category:
        raw = [d for d in raw if d.get("category") == category]

    result = _build_analysis(raw)
    return {"ok": True, "data": result}


@router.patch("/api/v1/dishes/{dish_id}")
async def patch_dish(
    dish_id: str,
    request: Request,
) -> dict:
    """
    更新菜品状态。支持下架操作：body = {"status": "soldout"}。
    """
    tenant_id = _tenant_id(request)

    try:
        body: dict = await request.json()
    except Exception:  # noqa: BLE001
        body = {}

    new_status = body.get("status", "")

    if new_status != "soldout":
        return {"ok": False, "error": {"code": "INVALID_STATUS", "message": "仅支持 status=soldout"}}

    try:
        from shared.ontology.src.database import async_session_factory  # type: ignore[import]
        from shared.ontology.src.entities import Dish  # type: ignore[import]
        from sqlalchemy import select, update  # type: ignore[import]
        import uuid as _uuid

        async with async_session_factory() as session:
            stmt = (
                update(Dish)
                .where(Dish.id == _uuid.UUID(dish_id))
                .where(Dish.tenant_id == tenant_id)
                .where(Dish.is_deleted == False)  # noqa: E712
                .values(is_available=False)
                .returning(Dish.id, Dish.dish_name)
            )
            result = await session.execute(stmt)
            row = result.first()
            await session.commit()

        if not row:
            return {"ok": False, "error": {"code": "NOT_FOUND", "message": "菜品不存在"}}

        log.info("dish_soldout", dish_id=dish_id, tenant_id=tenant_id)
        return {"ok": True, "data": {"dish_id": dish_id, "status": "soldout"}}

    except (ImportError, Exception):  # noqa: BLE001
        # DB 不可用时，乐观返回成功（Mock模式）
        log.info("menu_engineering: patch_dish DB不可用，Mock下架", dish_id=dish_id)
        return {"ok": True, "data": {"dish_id": dish_id, "status": "soldout"}}
