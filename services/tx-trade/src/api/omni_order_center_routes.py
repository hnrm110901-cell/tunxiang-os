"""
全渠道订单中心 — 堂食+外卖+小程序+团餐+宴席 统一视图
Y-A12: 聚合查询 API（Mock 数据层，v195 迁移可选）

端点：
  GET  /api/v1/trade/omni-orders                      — 全渠道统一订单列表
  GET  /api/v1/trade/omni-orders/stats                — 全渠道汇总统计
  GET  /api/v1/trade/omni-orders/search               — 快速搜索
  GET  /api/v1/trade/omni-orders/customer/{golden_id} — 会员跨渠道历史
  GET  /api/v1/trade/omni-orders/{order_id}           — 订单详情
"""
import structlog
from fastapi import APIRouter, Query, Header, Path
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, date, timedelta, timezone
import uuid

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/trade/omni-orders", tags=["omni-order-center"])

# ─── 渠道配置 ────────────────────────────────────────────────────────────────────

CHANNEL_CONFIG: dict[str, dict] = {
    "dine_in":    {"label": "堂食",     "color": "blue",   "icon": "🍽️"},
    "takeaway":   {"label": "美团外卖", "color": "orange", "icon": "🛵"},
    "miniapp":    {"label": "小程序自助","color": "green",  "icon": "📱"},
    "group_meal": {"label": "团餐企业", "color": "purple", "icon": "🏢"},
    "banquet":    {"label": "宴席预订", "color": "gold",   "icon": "🥂"},
}

ALL_CHANNELS = list(CHANNEL_CONFIG.keys())

STATUS_LABELS: dict[str, str] = {
    "open":      "进行中",
    "closed":    "已完成",
    "cancelled": "已取消",
    "voided":    "已废单",
    "pending":   "待处理",
}

# ─── Mock 数据集 ─────────────────────────────────────────────────────────────────

def _ts(offset_minutes: int = 0) -> str:
    """生成相对于现在的时间戳字符串"""
    t = datetime.now(tz=timezone.utc) - timedelta(minutes=offset_minutes)
    return t.isoformat()

MOCK_OMNI_ORDERS: list[dict] = [
    {
        "order_id": "ord-001",
        "channel": "dine_in",
        "channel_label": "堂食",
        "order_no": "2026040600001",
        "channel_order_id": None,
        "store_name": "五一广场店",
        "store_id": "store-001",
        "table_no": "A8",
        "customer_name": "张**",
        "customer_phone": "138****1234",
        "golden_id": "gid-1001",
        "items_count": 5,
        "total_fen": 28_800,
        "discount_fen": 2_000,
        "paid_fen": 26_800,
        "payment_method": "wechat",
        "status": "closed",
        "created_at": _ts(120),
        "closed_at": _ts(60),
        "items": [
            {"name": "剁椒鱼头", "quantity": 1, "price_fen": 12_800, "notes": "微辣"},
            {"name": "手撕鸡", "quantity": 1, "price_fen": 6_800, "notes": ""},
            {"name": "豆腐脑", "quantity": 2, "price_fen": 1_200, "notes": ""},
            {"name": "米饭", "quantity": 3, "price_fen": 600, "notes": ""},
            {"name": "老冰棍", "quantity": 2, "price_fen": 800, "notes": ""},
        ],
        "payment_records": [
            {"method": "wechat", "amount_fen": 26_800, "paid_at": _ts(62)}
        ],
    },
    {
        "order_id": "ord-002",
        "channel": "takeaway",
        "channel_label": "美团外卖",
        "order_no": "MT2026040600002",
        "channel_order_id": "MT-12345678",
        "store_name": "五一广场店",
        "store_id": "store-001",
        "table_no": None,
        "customer_name": "李**",
        "customer_phone": "139****5678",
        "golden_id": "gid-1002",
        "items_count": 2,
        "total_fen": 6_800,
        "discount_fen": 500,
        "paid_fen": 6_300,
        "payment_method": "meituan_pay",
        "status": "closed",
        "created_at": _ts(90),
        "closed_at": _ts(45),
        "items": [
            {"name": "麻辣香锅（小份）", "quantity": 1, "price_fen": 5_800, "notes": "不要花生"},
            {"name": "可乐", "quantity": 1, "price_fen": 1_000, "notes": ""},
        ],
        "payment_records": [
            {"method": "meituan_pay", "amount_fen": 6_300, "paid_at": _ts(89)}
        ],
    },
    {
        "order_id": "ord-003",
        "channel": "miniapp",
        "channel_label": "小程序自助",
        "order_no": "MP2026040600003",
        "channel_order_id": None,
        "store_name": "解放西路店",
        "store_id": "store-002",
        "table_no": "B12",
        "customer_name": "王**",
        "customer_phone": "177****9012",
        "golden_id": "gid-1003",
        "items_count": 3,
        "total_fen": 15_200,
        "discount_fen": 0,
        "paid_fen": 15_200,
        "payment_method": "wechat",
        "status": "open",
        "created_at": _ts(20),
        "closed_at": None,
        "items": [
            {"name": "湘式烤鱼", "quantity": 1, "price_fen": 9_800, "notes": "加辣"},
            {"name": "擂辣椒皮蛋", "quantity": 1, "price_fen": 3_200, "notes": ""},
            {"name": "酸辣粉", "quantity": 1, "price_fen": 2_200, "notes": "少辣"},
        ],
        "payment_records": [
            {"method": "wechat", "amount_fen": 15_200, "paid_at": _ts(19)}
        ],
    },
    {
        "order_id": "ord-004",
        "channel": "group_meal",
        "channel_label": "团餐企业",
        "order_no": "GM2026040600004",
        "channel_order_id": "CORP-2026-00412",
        "store_name": "五一广场店",
        "store_id": "store-001",
        "table_no": "VIP厅",
        "customer_name": "某科技公司",
        "customer_phone": "0731-88001234",
        "golden_id": "gid-corp-001",
        "items_count": 12,
        "total_fen": 128_000,
        "discount_fen": 12_800,
        "paid_fen": 115_200,
        "payment_method": "bank_transfer",
        "status": "closed",
        "created_at": _ts(360),
        "closed_at": _ts(300),
        "items": [
            {"name": "套餐A（10人标准）", "quantity": 2, "price_fen": 49_800, "notes": "无辣"},
            {"name": "招牌汤", "quantity": 2, "price_fen": 8_800, "notes": ""},
            {"name": "精品饮料套装", "quantity": 2, "price_fen": 9_800, "notes": ""},
        ],
        "payment_records": [
            {"method": "bank_transfer", "amount_fen": 115_200, "paid_at": _ts(310)}
        ],
    },
    {
        "order_id": "ord-005",
        "channel": "banquet",
        "channel_label": "宴席预订",
        "order_no": "BQ2026040600005",
        "channel_order_id": None,
        "store_name": "五一广场店",
        "store_id": "store-001",
        "table_no": "宴会厅A",
        "customer_name": "赵总婚宴",
        "customer_phone": "135****3456",
        "golden_id": "gid-1005",
        "items_count": 22,
        "total_fen": 580_000,
        "discount_fen": 30_000,
        "paid_fen": 550_000,
        "payment_method": "deposit_deduct",
        "status": "open",
        "created_at": _ts(1440),
        "closed_at": None,
        "items": [
            {"name": "婚宴豪华套餐（30桌）", "quantity": 30, "price_fen": 18_800, "notes": "2026-04-08晚宴"},
            {"name": "定制婚宴蛋糕", "quantity": 1, "price_fen": 16_000, "notes": ""},
        ],
        "payment_records": [
            {"method": "deposit_deduct", "amount_fen": 100_000, "paid_at": _ts(1440)},
            {"method": "wechat", "amount_fen": 450_000, "paid_at": _ts(1430)},
        ],
    },
    # 补充更多订单以支持分页/搜索测试
    {
        "order_id": "ord-006",
        "channel": "dine_in",
        "channel_label": "堂食",
        "order_no": "2026040600006",
        "channel_order_id": None,
        "store_name": "解放西路店",
        "store_id": "store-002",
        "table_no": "C3",
        "customer_name": "陈**",
        "customer_phone": "150****7890",
        "golden_id": "gid-1006",
        "items_count": 3,
        "total_fen": 9_600,
        "discount_fen": 0,
        "paid_fen": 9_600,
        "payment_method": "alipay",
        "status": "closed",
        "created_at": _ts(200),
        "closed_at": _ts(140),
        "items": [
            {"name": "红烧肉", "quantity": 1, "price_fen": 5_800, "notes": ""},
            {"name": "炒土豆丝", "quantity": 1, "price_fen": 2_200, "notes": ""},
            {"name": "米饭", "quantity": 2, "price_fen": 800, "notes": ""},
        ],
        "payment_records": [
            {"method": "alipay", "amount_fen": 9_600, "paid_at": _ts(142)}
        ],
    },
    {
        "order_id": "ord-007",
        "channel": "takeaway",
        "channel_label": "美团外卖",
        "order_no": "MT2026040600007",
        "channel_order_id": "MT-87654321",
        "store_name": "解放西路店",
        "store_id": "store-002",
        "table_no": None,
        "customer_name": "孙**",
        "customer_phone": "182****2345",
        "golden_id": "gid-1007",
        "items_count": 1,
        "total_fen": 3_200,
        "discount_fen": 200,
        "paid_fen": 3_000,
        "payment_method": "meituan_pay",
        "status": "cancelled",
        "created_at": _ts(150),
        "closed_at": _ts(148),
        "items": [
            {"name": "盖浇饭（鱼香肉丝）", "quantity": 1, "price_fen": 3_200, "notes": "不要葱"}
        ],
        "payment_records": [],
    },
]

# 汇总统计的 Mock 基准
MOCK_CHANNEL_STATS_BASE: dict[str, dict] = {
    "dine_in":    {"order_count": 856,  "revenue_fen": 15_234_400, "prev_revenue_fen": 14_100_000},
    "takeaway":   {"order_count": 312,  "revenue_fen": 4_876_800,  "prev_revenue_fen": 4_500_000},
    "miniapp":    {"order_count": 89,   "revenue_fen": 1_352_800,  "prev_revenue_fen": 1_200_000},
    "group_meal": {"order_count": 26,   "revenue_fen": 3_328_000,  "prev_revenue_fen": 2_980_000},
    "banquet":    {"order_count": 8,    "revenue_fen": 4_640_000,  "prev_revenue_fen": 5_100_000},
}


# ─── 工具函数 ─────────────────────────────────────────────────────────────────────

def _mask_phone(phone: Optional[str]) -> Optional[str]:
    """手机号脱敏：保留前3位和后4位"""
    if not phone or len(phone) < 8:
        return phone
    return phone[:3] + "****" + phone[-4:]


def _filter_orders(
    orders: list[dict],
    channel: Optional[str],
    status: Optional[str],
    store_id: Optional[str],
    date_from: Optional[date],
    date_to: Optional[date],
    phone: Optional[str],
) -> list[dict]:
    """在内存中对 Mock 数据进行多条件过滤"""
    result = []
    for o in orders:
        if channel and channel != "all" and o["channel"] != channel:
            continue
        if status and status != "all" and o["status"] != status:
            continue
        if store_id and o.get("store_id") != store_id:
            continue
        if phone:
            # 匹配手机号尾4位或完整手机号
            raw_phone = o.get("customer_phone", "")
            if phone not in raw_phone and phone not in (raw_phone[-4:] if len(raw_phone) >= 4 else ""):
                continue
        if date_from:
            created = o.get("created_at", "")
            if created and created[:10] < date_from.isoformat():
                continue
        if date_to:
            created = o.get("created_at", "")
            if created and created[:10] > date_to.isoformat():
                continue
        result.append(o)
    return result


def _safe_order_view(o: dict) -> dict:
    """返回脱敏后的订单摘要（列表视图）"""
    cfg = CHANNEL_CONFIG.get(o["channel"], {"label": o["channel"], "color": "default"})
    return {
        "order_id": o["order_id"],
        "channel": o["channel"],
        "channel_label": cfg["label"],
        "channel_color": cfg["color"],
        "order_no": o["order_no"],
        "channel_order_id": o.get("channel_order_id"),
        "store_name": o.get("store_name"),
        "store_id": o.get("store_id"),
        "table_no": o.get("table_no"),
        "customer_name": o.get("customer_name"),
        "customer_phone": _mask_phone(o.get("customer_phone")),
        "golden_id": o.get("golden_id"),
        "items_count": o.get("items_count", 0),
        "total_fen": o.get("total_fen", 0),
        "discount_fen": o.get("discount_fen", 0),
        "paid_fen": o.get("paid_fen", 0),
        "payment_method": o.get("payment_method"),
        "status": o.get("status"),
        "status_label": STATUS_LABELS.get(o.get("status", ""), o.get("status", "")),
        "created_at": o.get("created_at"),
        "closed_at": o.get("closed_at"),
    }


# ─── 端点1：全渠道订单统一列表 ───────────────────────────────────────────────────

@router.get("", summary="全渠道订单统一列表")
async def list_omni_orders(
    channel: Optional[str] = Query(None, description="渠道过滤：dine_in/takeaway/miniapp/group_meal/banquet/all"),
    status: Optional[str] = Query(None, description="状态：open/closed/cancelled/all"),
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[date] = Query(None, description="开始日期"),
    date_to: Optional[date] = Query(None, description="结束日期"),
    phone: Optional[str] = Query(None, description="顾客手机号（支持尾4位）"),
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(20, ge=1, le=100, description="每页数量"),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
) -> dict:
    """
    全渠道订单统一列表：堂食/外卖/小程序/团餐/宴席归一化展示。

    各渠道订单的差异字段（如外卖的 channel_order_id、宴席的桌台号）
    在 channel_order_id 和 table_no 中统一承载。
    """
    log = logger.bind(
        tenant=x_tenant_id,
        channel=channel,
        status=status,
        store_id=store_id,
    )

    # 过滤
    filtered = _filter_orders(
        MOCK_OMNI_ORDERS,
        channel=channel if channel != "all" else None,
        status=status if status != "all" else None,
        store_id=store_id,
        date_from=date_from,
        date_to=date_to,
        phone=phone,
    )

    total = len(filtered)
    page_items = filtered[(page - 1) * size: page * size]
    items = [_safe_order_view(o) for o in page_items]

    # 各渠道汇总（以完整过滤结果为基础）
    channel_summary: dict[str, int] = {}
    for ch in ALL_CHANNELS:
        channel_summary[ch] = sum(1 for o in filtered if o["channel"] == ch)

    log.info("omni_orders.list.ok", total=total, page=page)

    return {
        "ok": True,
        "data": {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
            "channel_summary": channel_summary,
        },
        "error": None,
    }


# ─── 端点2：全渠道汇总统计 ───────────────────────────────────────────────────────

@router.get("/stats", summary="全渠道汇总统计")
async def get_omni_stats(
    date_from: Optional[date] = Query(None, description="开始日期，默认今日"),
    date_to: Optional[date] = Query(None, description="结束日期，默认今日"),
    store_id: Optional[str] = Query(None, description="门店ID"),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
) -> dict:
    """
    全渠道汇总统计：各渠道订单数/营业额/客单价/增长率（vs上期）。

    对比周期 = 同等时间跨度的上一周期（默认今日 vs 昨日）。
    """
    today = date.today()
    d_to = date_to or today
    d_from = date_from or today
    days = max((d_to - d_from).days + 1, 1)
    log = logger.bind(tenant=x_tenant_id, date_from=str(d_from), date_to=str(d_to))

    channel_stats: list[dict] = []
    total_revenue = 0
    total_orders = 0

    for ch, base in MOCK_CHANNEL_STATS_BASE.items():
        cfg = CHANNEL_CONFIG[ch]
        rev = base["revenue_fen"]
        prev_rev = base["prev_revenue_fen"]
        cnt = base["order_count"]
        avg_ticket = rev // cnt if cnt > 0 else 0
        growth = round((rev - prev_rev) / prev_rev, 4) if prev_rev else 0.0
        total_revenue += rev
        total_orders += cnt

        channel_stats.append({
            "channel": ch,
            "channel_label": cfg["label"],
            "channel_color": cfg["color"],
            "order_count": cnt,
            "revenue_fen": rev,
            "avg_ticket_fen": avg_ticket,
            "growth_rate": growth,
            "prev_revenue_fen": prev_rev,
        })

    # 整体增长
    total_prev = sum(s["prev_revenue_fen"] for s in channel_stats)
    overall_growth = round((total_revenue - total_prev) / total_prev, 4) if total_prev else 0.0

    log.info("omni_orders.stats.ok", channels=len(channel_stats))

    return {
        "ok": True,
        "data": {
            "date_from": d_from.isoformat(),
            "date_to": d_to.isoformat(),
            "days": days,
            "total_order_count": total_orders,
            "total_revenue_fen": total_revenue,
            "overall_growth_rate": overall_growth,
            "channel_stats": channel_stats,
        },
        "error": None,
    }


# ─── 端点3：快速搜索 ─────────────────────────────────────────────────────────────

@router.get("/search", summary="快速搜索订单（订单号/手机尾4位/桌台号/顾客名）")
async def search_omni_orders(
    q: str = Query(..., min_length=1, description="搜索关键词：订单号/手机尾4位/桌台号/顾客姓名"),
    limit: int = Query(20, ge=1, le=50, description="返回条数上限"),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
) -> dict:
    """
    全文快速搜索：在订单号、渠道订单号、手机号、桌台号、顾客名中做包含匹配。
    结果按相关度（精确匹配优先）+ 下单时间降序排列。
    """
    q_lower = q.lower().strip()
    log = logger.bind(tenant=x_tenant_id, q=q)

    scored: list[tuple[int, dict]] = []
    for o in MOCK_OMNI_ORDERS:
        score = 0
        if q_lower in (o.get("order_no", "") or "").lower():
            score += 100
        if q_lower in (o.get("channel_order_id", "") or "").lower():
            score += 90
        raw_phone = (o.get("customer_phone", "") or "")
        if q_lower in raw_phone or (len(raw_phone) >= 4 and q_lower == raw_phone[-4:]):
            score += 80
        if q_lower in (o.get("table_no", "") or "").lower():
            score += 70
        if q_lower in (o.get("customer_name", "") or "").lower():
            score += 60
        if q_lower in (o.get("store_name", "") or "").lower():
            score += 50
        # 渠道标签搜索（如"美团"→ takeaway，"宴席"→ banquet）
        cfg = CHANNEL_CONFIG.get(o["channel"], {})
        if q_lower in (cfg.get("label", "") or "").lower():
            score += 40
        if score > 0:
            scored.append((score, o))

    # 按 score 降序，同分按 created_at 降序
    scored.sort(key=lambda x: (-x[0], -(x[1].get("created_at") or "") ))
    top = [_safe_order_view(o) for _, o in scored[:limit]]

    log.info("omni_orders.search.ok", q=q, hits=len(top))

    return {
        "ok": True,
        "data": {
            "query": q,
            "items": top,
            "total": len(top),
        },
        "error": None,
    }


# ─── 端点4：会员跨渠道订单历史 ──────────────────────────────────────────────────

@router.get("/customer/{golden_id}", summary="会员跨渠道订单历史")
async def get_customer_order_history(
    golden_id: str = Path(..., description="Golden ID"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
) -> dict:
    """
    按 Golden ID 查询该会员在所有渠道的消费记录（时间倒序）。
    聚合各渠道消费汇总：总消费额/订单数/首次/末次消费时间。
    """
    log = logger.bind(tenant=x_tenant_id, golden_id=golden_id)

    orders = [o for o in MOCK_OMNI_ORDERS if o.get("golden_id") == golden_id]
    orders.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    total = len(orders)
    page_items = orders[(page - 1) * size: page * size]
    items = [_safe_order_view(o) for o in page_items]

    # 消费汇总
    total_paid = sum(o.get("paid_fen", 0) for o in orders if o.get("status") == "closed")
    channel_breakdown: dict[str, int] = {}
    for o in orders:
        ch = o["channel"]
        channel_breakdown[ch] = channel_breakdown.get(ch, 0) + 1

    first_order = orders[-1]["created_at"] if orders else None
    last_order = orders[0]["created_at"] if orders else None

    log.info("omni_orders.customer_history.ok", golden_id=golden_id, total=total)

    return {
        "ok": True,
        "data": {
            "golden_id": golden_id,
            "total_order_count": total,
            "total_paid_fen": total_paid,
            "channel_breakdown": channel_breakdown,
            "first_order_at": first_order,
            "last_order_at": last_order,
            "items": items,
            "page": page,
            "size": size,
        },
        "error": None,
    }


# ─── 端点5：订单详情 ─────────────────────────────────────────────────────────────

@router.get("/{order_id}", summary="订单详情（含品项/支付/渠道特定信息）")
async def get_omni_order_detail(
    order_id: str = Path(..., description="订单ID（order_id字段）"),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
) -> dict:
    """
    单笔订单详情：包含完整品项明细、支付记录、渠道专属信息。

    渠道特定字段：
    - takeaway：channel_order_id（平台单号）
    - group_meal：channel_order_id（企业采购单号）
    - banquet：table_no（宴会厅）、预订日期
    - miniapp：二维码自助下单标识
    """
    log = logger.bind(tenant=x_tenant_id, order_id=order_id)

    order = next((o for o in MOCK_OMNI_ORDERS if o["order_id"] == order_id), None)
    if order is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"订单 {order_id} 不存在")

    cfg = CHANNEL_CONFIG.get(order["channel"], {"label": order["channel"], "color": "default"})

    # 构建详情视图（含原始手机号用于详情页，实际生产需鉴权）
    detail = {
        **_safe_order_view(order),
        # 详情页额外字段
        "items": order.get("items", []),
        "payment_records": order.get("payment_records", []),
        "channel_info": {
            "channel": order["channel"],
            "label": cfg["label"],
            "color": cfg["color"],
            "channel_order_id": order.get("channel_order_id"),
        },
        "discount_detail": {
            "total_discount_fen": order.get("discount_fen", 0),
            "discount_rate": round(
                order.get("discount_fen", 0) / order.get("total_fen", 1), 4
            ) if order.get("total_fen") else 0,
        },
    }

    log.info("omni_orders.detail.ok", order_id=order_id, channel=order["channel"])

    return {
        "ok": True,
        "data": detail,
        "error": None,
    }
