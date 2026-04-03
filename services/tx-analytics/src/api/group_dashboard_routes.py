"""集团跨店数据看板 API

GET /api/v1/analytics/group/today?brand_id=   — 所有门店今日实时汇总
GET /api/v1/analytics/group/trend?brand_id=&days=7  — 7/30天营收趋势
GET /api/v1/analytics/group/alerts?brand_id=  — 集团级异常告警

TODO: 全部接口目前返回 Mock 数据。接入真实数据源时：
  - today  → 查询 orders/tables 实时快照视图（PostgreSQL materialized view）
  - trend  → 查询 daily_revenue_summary 聚合表（按 brand_id + store_id + date）
  - alerts → 查询 analytics_alerts 事件表（由 tx-agent 折扣守护/出餐调度写入）
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/analytics/group", tags=["group-dashboard"])


# ─── 工具 ───

def _require_tenant(tenant_id: Optional[str]) -> str:
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    return tenant_id


# ─── Pydantic 响应模型 ───

class StoreTodayData(BaseModel):
    store_id: str
    store_name: str
    status: str                   # open | prep | closed | error
    revenue_fen: int
    order_count: int
    table_turnover: float
    occupied_tables: int
    total_tables: int
    current_diners: int
    avg_serve_time_min: int
    revenue_vs_yesterday_pct: float
    alerts: list[str]


class GroupSummary(BaseModel):
    total_revenue_fen: int
    total_orders: int
    avg_table_turnover: float
    active_stores: int
    total_stores: int
    revenue_vs_yesterday_pct: float
    current_diners: int


class GroupTodayResponse(BaseModel):
    summary: GroupSummary
    stores: list[StoreTodayData]


class GroupTrendResponse(BaseModel):
    dates: list[str]
    total_revenue: list[int]
    by_store: dict[str, list[int]]


class AlertItem(BaseModel):
    severity: str                 # danger | warning | info
    store_name: str
    type: str
    title: str
    body: str
    created_at: str


class GroupAlertsResponse(BaseModel):
    alerts: list[AlertItem]


# ─── Mock 数据生成 ───

# TODO: 替换为真实门店列表查询
#   SELECT store_id, store_name FROM stores WHERE brand_id = :brand_id AND is_deleted = false
_MOCK_STORES = [
    {"store_id": "store-001", "store_name": "解放西路店", "total_tables": 24},
    {"store_id": "store-002", "store_name": "五一广场店", "total_tables": 20},
    {"store_id": "store-003", "store_name": "湘江新区店", "total_tables": 18},
    {"store_id": "store-004", "store_name": "梅溪湖店",   "total_tables": 22},
    {"store_id": "store-005", "store_name": "望城店",     "total_tables": 16},
    {"store_id": "store-006", "store_name": "星沙店",     "total_tables": 20},
]


def _mock_store_today(store: dict, idx: int) -> StoreTodayData:
    """
    TODO: 接入真实数据时替换此函数，改为从以下来源聚合：
      - revenue_fen / order_count: SELECT SUM(pay_fen), COUNT(*) FROM orders WHERE store_id=...
          AND DATE(created_at) = today AND status = 'paid'
      - occupied_tables / current_diners: 查询 tables 实时状态快照
      - avg_serve_time_min: SELECT AVG(serve_duration_sec)/60 FROM order_serve_log WHERE ...
      - revenue_vs_yesterday_pct: 与昨日同时段对比
      - alerts: 查询 analytics_alerts WHERE store_id=... AND DATE(created_at)=today AND resolved=false
    """
    random.seed(idx * 7 + 42)
    is_closed = idx == 5  # 星沙店今天休息（演示）

    if is_closed:
        return StoreTodayData(
            store_id=store["store_id"],
            store_name=store["store_name"],
            status="closed",
            revenue_fen=0,
            order_count=0,
            table_turnover=0.0,
            occupied_tables=0,
            total_tables=store["total_tables"],
            current_diners=0,
            avg_serve_time_min=0,
            revenue_vs_yesterday_pct=0.0,
            alerts=[],
        )

    revenue = random.randint(28000, 65000)
    orders = random.randint(15, 35)
    occupied = random.randint(8, store["total_tables"] - 2)
    diners = occupied * random.randint(2, 4)
    turnover = round(random.uniform(1.2, 3.5), 1)
    serve_time = random.randint(28, 55)
    vs_yesterday = round(random.uniform(-40, 30), 1)

    # 演示：五一广场店营收大幅下滑
    if idx == 1:
        revenue = 18000
        vs_yesterday = -38.0

    alerts: list[str] = []
    if serve_time > 45:
        alerts.append(f"出餐超时{random.randint(1,3)}单")
    if vs_yesterday < -20:
        alerts.append("今日营收大幅下滑")
    if random.random() < 0.3:
        alerts.append("折扣率偏高")

    return StoreTodayData(
        store_id=store["store_id"],
        store_name=store["store_name"],
        status="open",
        revenue_fen=revenue,
        order_count=orders,
        table_turnover=turnover,
        occupied_tables=occupied,
        total_tables=store["total_tables"],
        current_diners=diners,
        avg_serve_time_min=serve_time,
        revenue_vs_yesterday_pct=vs_yesterday,
        alerts=alerts,
    )


# ─── 路由处理器 ───

@router.get("/today", response_model=dict)
async def get_group_today(
    brand_id: str = Query(..., description="品牌 ID"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """
    今日集团实时数据汇总（所有门店）

    TODO: brand_id 过滤需要查询 stores 表
    TODO: 在此处建立 DB session，传入各 store 数据查询函数
    """
    _require_tenant(x_tenant_id)

    stores_data = [_mock_store_today(s, i) for i, s in enumerate(_MOCK_STORES)]

    active = [s for s in stores_data if s.status == "open"]
    total_revenue = sum(s.revenue_fen for s in active)
    total_orders = sum(s.order_count for s in active)
    total_diners = sum(s.current_diners for s in active)
    avg_turnover = round(
        sum(s.table_turnover for s in active) / len(active) if active else 0, 1
    )
    # 汇总环比：活跃门店加权平均
    if active:
        avg_vs_yesterday = round(
            sum(s.revenue_vs_yesterday_pct for s in active) / len(active), 1
        )
    else:
        avg_vs_yesterday = 0.0

    summary = GroupSummary(
        total_revenue_fen=total_revenue,
        total_orders=total_orders,
        avg_table_turnover=avg_turnover,
        active_stores=len(active),
        total_stores=len(stores_data),
        revenue_vs_yesterday_pct=avg_vs_yesterday,
        current_diners=total_diners,
    )

    return {
        "ok": True,
        "data": GroupTodayResponse(summary=summary, stores=stores_data).model_dump(),
    }


@router.get("/trend", response_model=dict)
async def get_group_trend(
    brand_id: str = Query(..., description="品牌 ID"),
    days: int = Query(7, ge=1, le=30, description="天数，支持 7 / 30"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """
    集团营收趋势（N 天）

    TODO: 替换 Mock 数据，改为：
      SELECT DATE(created_at) as dt, store_id, SUM(pay_fen) as revenue
      FROM orders
      WHERE brand_id = :brand_id
        AND created_at >= NOW() - INTERVAL ':days days'
        AND status = 'paid'
      GROUP BY dt, store_id
      ORDER BY dt
    """
    _require_tenant(x_tenant_id)

    today = date.today()
    dates = [(today - timedelta(days=days - 1 - i)).isoformat() for i in range(days)]

    # TODO: 从 DB 聚合真实数据
    by_store: dict[str, list[int]] = {}
    total_revenue: list[int] = [0] * days

    for idx, store in enumerate(_MOCK_STORES):
        if store["store_name"] == "星沙店":
            # 休息门店（周一休息模拟）
            revenues = [0 if i % 7 == 0 else random.randint(20000, 50000) for i in range(days)]
        else:
            random.seed(idx * 13 + 99)
            base = random.randint(30000, 55000)
            revenues = [
                int(base * random.uniform(0.75, 1.3)) for _ in range(days)
            ]
        by_store[store["store_name"]] = revenues
        for i, v in enumerate(revenues):
            total_revenue[i] += v

    return {
        "ok": True,
        "data": GroupTrendResponse(
            dates=dates,
            total_revenue=total_revenue,
            by_store=by_store,
        ).model_dump(),
    }


@router.get("/alerts", response_model=dict)
async def get_group_alerts(
    brand_id: str = Query(..., description="品牌 ID"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """
    集团级异常告警列表

    TODO: 替换 Mock 数据，改为：
      SELECT * FROM analytics_alerts
      WHERE brand_id = :brand_id
        AND DATE(created_at) = today
        AND resolved = false
      ORDER BY severity DESC, created_at DESC
    告警由 tx-agent 的折扣守护、出餐调度等 Skill Agent 写入 analytics_alerts 表。
    """
    _require_tenant(x_tenant_id)

    now_str = datetime.now().isoformat(timespec="seconds")

    # TODO: 从 analytics_alerts 表查询真实告警
    mock_alerts = [
        AlertItem(
            severity="danger",
            store_name="五一广场店",
            type="revenue_drop",
            title="今日营收下滑38%",
            body="较昨日同期下滑38%，截至当前营收仅¥180，需立即关注",
            created_at=now_str,
        ),
        AlertItem(
            severity="warning",
            store_name="解放西路店",
            type="discount_abuse",
            title="折扣使用异常",
            body="今日折扣总额¥1,280，较日均高出3.2倍，请核查",
            created_at=now_str,
        ),
        AlertItem(
            severity="warning",
            store_name="湘江新区店",
            type="slow_serve",
            title="出餐超时2单",
            body="2单出餐时间超过55分钟，顾客满意度风险",
            created_at=now_str,
        ),
        AlertItem(
            severity="info",
            store_name="梅溪湖店",
            type="peak_incoming",
            title="预测15分钟内高峰",
            body="AI预测14:30将迎来就餐高峰，建议提前备货",
            created_at=now_str,
        ),
    ]

    return {"ok": True, "data": {"alerts": [a.model_dump() for a in mock_alerts]}}
