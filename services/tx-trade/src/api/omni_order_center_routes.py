"""
全渠道订单中心 — 堂食+外卖+小程序+团餐+宴席 统一视图
Y-A12 Mock→DB 改造

从 orders + aggregator_orders + corporate_orders 聚合查询，替代内存Mock。

端点：
  GET  /api/v1/trade/omni-orders                      — 全渠道统一订单列表
  GET  /api/v1/trade/omni-orders/stats                — 全渠道汇总统计
  GET  /api/v1/trade/omni-orders/search               — 快速搜索
  GET  /api/v1/trade/omni-orders/customer/{golden_id} — 会员跨渠道历史
  GET  /api/v1/trade/omni-orders/{order_id}           — 订单详情
"""

from datetime import date
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/trade/omni-orders", tags=["omni-order-center"])

CHANNEL_CONFIG: dict[str, dict] = {
    "dine_in": {"label": "堂食", "color": "blue", "icon": "🍽️"},
    "takeaway": {"label": "外卖", "color": "orange", "icon": "🛵"},
    "miniapp": {"label": "小程序", "color": "green", "icon": "📱"},
    "group_meal": {"label": "团餐企业", "color": "purple", "icon": "🏢"},
    "banquet": {"label": "宴席预订", "color": "gold", "icon": "🥂"},
}


def _get_tenant_id(request: Request) -> str:
    return request.headers.get("X-Tenant-Id", request.headers.get("X-Tenant-ID", "default"))


async def _get_db(request: Request):
    tenant_id = _get_tenant_id(request)
    async for session in get_db_with_tenant(tenant_id):
        yield session


def _ok(data) -> dict:
    return {"ok": True, "data": data, "error": None}


# 全渠道聚合SQL（UNION ALL 各来源表）
_OMNI_CTE = """
WITH omni AS (
    -- 堂食+小程序（orders表，channel标记区分）
    SELECT id::text AS order_id,
           COALESCE(channel, 'dine_in') AS channel,
           order_no, store_id, final_amount AS amount_fen,
           consumer_id::text AS golden_id,
           customer_name, customer_phone,
           status, covers, created_at
    FROM orders

    UNION ALL

    -- 外卖聚合订单
    SELECT id::text, 'takeaway', platform_order_id, store_id, total_fen,
           NULL, customer_phone_masked, NULL,
           status, 1, created_at
    FROM aggregator_orders

    UNION ALL

    -- 团餐企业订单
    SELECT co.id::text, 'group_meal', co.order_no, co.store_id, co.final_amount_fen,
           NULL, NULL, NULL,
           co.status, co.covers, co.ordered_at
    FROM corporate_orders co
)
"""


@router.get("", summary="全渠道统一订单列表")
async def list_omni_orders(
    request: Request,
    channel: Optional[str] = Query(None, description="渠道过滤"),
    status: Optional[str] = Query(None),
    store_id: Optional[str] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    conds = ["1=1"]
    params: dict = {"limit": size, "offset": (page - 1) * size}
    if channel:
        conds.append("channel = :channel")
        params["channel"] = channel
    if status:
        conds.append("status = :status")
        params["status"] = status
    if store_id:
        conds.append("store_id = :store_id")
        params["store_id"] = store_id
    if date_from:
        conds.append("created_at::date >= :date_from")
        params["date_from"] = date_from
    if date_to:
        conds.append("created_at::date <= :date_to")
        params["date_to"] = date_to

    where = " AND ".join(conds)

    total = (await db.execute(text(f"{_OMNI_CTE} SELECT COUNT(*) FROM omni WHERE {where}"), params)).scalar() or 0

    rows = await db.execute(
        text(f"""
        {_OMNI_CTE}
        SELECT order_id, channel, order_no, store_id, amount_fen,
               golden_id, customer_name, customer_phone,
               status, covers, created_at
        FROM omni WHERE {where}
        ORDER BY created_at DESC LIMIT :limit OFFSET :offset
    """),
        params,
    )

    items = []
    for r in rows.fetchall():
        d = dict(r._mapping)
        cfg = CHANNEL_CONFIG.get(d["channel"], {})
        d["channel_label"] = cfg.get("label", d["channel"])
        d["channel_color"] = cfg.get("color", "default")
        d["channel_icon"] = cfg.get("icon", "")
        d["amount_yuan"] = round(d.get("amount_fen", 0) / 100, 2)
        items.append(d)

    return _ok({"items": items, "total": total, "page": page, "size": size})


@router.get("/stats", summary="全渠道汇总统计")
async def get_omni_stats(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    conds = ["1=1"]
    params: dict = {}
    if date_from:
        conds.append("created_at::date >= :date_from")
        params["date_from"] = date_from
    if date_to:
        conds.append("created_at::date <= :date_to")
        params["date_to"] = date_to
    where = " AND ".join(conds)

    rows = await db.execute(
        text(f"""
        {_OMNI_CTE}
        SELECT channel, COUNT(*) AS order_count, COALESCE(SUM(amount_fen), 0) AS total_fen
        FROM omni WHERE {where} GROUP BY channel
    """),
        params,
    )
    stats = []
    grand_total_fen = 0
    grand_count = 0
    for r in rows.fetchall():
        cfg = CHANNEL_CONFIG.get(r.channel, {})
        stats.append(
            {
                "channel": r.channel,
                "label": cfg.get("label", r.channel),
                "color": cfg.get("color", "default"),
                "order_count": r.order_count,
                "total_fen": r.total_fen,
                "total_yuan": round(r.total_fen / 100, 2),
            }
        )
        grand_total_fen += r.total_fen
        grand_count += r.order_count

    return _ok(
        {
            "channels": stats,
            "grand_total_fen": grand_total_fen,
            "grand_total_yuan": round(grand_total_fen / 100, 2),
            "grand_order_count": grand_count,
        }
    )


@router.get("/search", summary="快速搜索（订单号/手机号）")
async def search_orders(
    q: str = Query(..., min_length=1, description="搜索词"),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    rows = await db.execute(
        text(f"""
        {_OMNI_CTE}
        SELECT order_id, channel, order_no, store_id, amount_fen, status, created_at
        FROM omni
        WHERE order_no ILIKE :q OR customer_phone ILIKE :q
        ORDER BY created_at DESC LIMIT :limit
    """),
        {"q": f"%{q}%", "limit": limit},
    )
    items = [dict(r._mapping) for r in rows.fetchall()]
    return _ok(items)


@router.get("/customer/{golden_id}", summary="会员跨渠道历史")
async def get_customer_orders(
    golden_id: str = Path(...),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    rows = await db.execute(
        text(f"""
        {_OMNI_CTE}
        SELECT order_id, channel, order_no, store_id, amount_fen, status, created_at
        FROM omni WHERE golden_id = :gid
        ORDER BY created_at DESC LIMIT :limit
    """),
        {"gid": golden_id, "limit": limit},
    )
    items = [dict(r._mapping) for r in rows.fetchall()]
    return _ok({"golden_id": golden_id, "orders": items, "total": len(items)})


@router.get("/{order_id}", summary="订单详情")
async def get_order_detail(order_id: str = Path(...), db: AsyncSession = Depends(_get_db)) -> dict:
    # 先查 orders 表
    row = await db.execute(text("SELECT * FROM orders WHERE id::text = :oid"), {"oid": order_id})
    order = row.fetchone()
    if order:
        d = dict(order._mapping)
        d["channel"] = d.get("channel", "dine_in")
        d["source_table"] = "orders"
        return _ok(d)

    # 查 aggregator_orders
    row = await db.execute(text("SELECT * FROM aggregator_orders WHERE id::text = :oid"), {"oid": order_id})
    order = row.fetchone()
    if order:
        d = dict(order._mapping)
        d["channel"] = "takeaway"
        d["source_table"] = "aggregator_orders"
        return _ok(d)

    # 查 corporate_orders
    row = await db.execute(text("SELECT * FROM corporate_orders WHERE id::text = :oid"), {"oid": order_id})
    order = row.fetchone()
    if order:
        d = dict(order._mapping)
        d["channel"] = "group_meal"
        d["source_table"] = "corporate_orders"
        return _ok(d)

    from fastapi import HTTPException

    raise HTTPException(status_code=404, detail={"ok": False, "error": {"code": "ORDER_NOT_FOUND"}})
