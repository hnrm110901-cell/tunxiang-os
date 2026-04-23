"""收入分析 API 路由

端点：
  GET /api/v1/finance/revenue/daily         — 日收入（按渠道/时段）
  GET /api/v1/finance/revenue/channel-mix   — 渠道构成趋势（?store_id=&days=）
  GET /api/v1/finance/revenue/hourly        — 小时收入分布（热力图数据）
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from services.pnl_engine import PnLEngine
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["finance-revenue"])

_pnl_engine = PnLEngine()


# ─── 依赖注入 ─────────────────────────────────────────────────────────────────


async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _parse_uuid(val: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(val)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"无效的 {field_name}: {val}") from exc


def _parse_date_param(d: str) -> date:
    if d == "today":
        return date.today()
    try:
        return date.fromisoformat(d)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"日期格式错误: {d}，请使用 YYYY-MM-DD") from exc


# ─── GET /revenue/daily ───────────────────────────────────────────────────────


@router.get("/revenue/daily", summary="日收入（按渠道/时段分析）")
async def get_daily_revenue(
    store_id: str = Query(..., description="门店ID"),
    revenue_date: str = Query("today", alias="date", description="日期 YYYY-MM-DD 或 today"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """
    查询指定门店指定日期的收入详情，按渠道和时段拆分。

    返回：
    - 各渠道（堂食/外卖/宴席/自助点餐）收入和占比
    - 各时段（早市/午市/下午茶/晚市/夜宵）收入
    - 支付方式构成
    - 团购实际到账估算
    """
    sid = _parse_uuid(store_id, "store_id")
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    biz_date = _parse_date_param(revenue_date)

    # 按渠道聚合（从 revenue_records 表）
    channel_result = await db.execute(
        text("""
            SELECT
                channel,
                COUNT(*) AS order_count,
                SUM(gross_amount_fen) AS gross_fen,
                SUM(discount_fen) AS discount_fen,
                SUM(net_amount_fen) AS net_fen,
                SUM(actual_revenue_fen) AS actual_fen,
                BOOL_OR(NOT is_actual_revenue) AS has_group_buy
            FROM revenue_records
            WHERE tenant_id = :tenant_id::UUID
              AND store_id = :store_id::UUID
              AND record_date = :record_date
              AND is_deleted = FALSE
            GROUP BY channel
            ORDER BY net_fen DESC
        """),
        {
            "tenant_id": str(tid),
            "store_id": str(sid),
            "record_date": biz_date.isoformat(),
        },
    )
    channel_rows = channel_result.fetchall()

    # 若 revenue_records 无数据，尝试从 orders 直接查（实时）
    if not channel_rows:
        channel_result_fallback = await db.execute(
            text("""
                SELECT
                    channel,
                    COUNT(*) AS order_count,
                    SUM(total_amount_fen) AS gross_fen,
                    SUM(COALESCE(discount_amount_fen, 0)) AS discount_fen,
                    SUM(total_amount_fen - COALESCE(discount_amount_fen, 0)) AS net_fen
                FROM orders
                WHERE tenant_id = :tenant_id::UUID
                  AND store_id = :store_id::UUID
                  AND status IN ('completed', 'settled', 'paid')
                  AND order_time::date = :record_date
                  AND is_deleted = FALSE
                GROUP BY channel
                ORDER BY net_fen DESC
            """),
            {
                "tenant_id": str(tid),
                "store_id": str(sid),
                "record_date": biz_date.isoformat(),
            },
        )
        channel_rows_raw = channel_result_fallback.fetchall()

        total_net = sum(int(r[4] or 0) for r in channel_rows_raw)
        channels = [
            {
                "channel": r[0] or "unknown",
                "order_count": int(r[1]),
                "gross_amount_fen": int(r[2] or 0),
                "discount_fen": int(r[3] or 0),
                "net_amount_fen": int(r[4] or 0),
                "actual_revenue_fen": int(r[4] or 0),
                "ratio": round(int(r[4] or 0) / total_net, 4) if total_net > 0 else 0.0,
                "source": "orders_realtime",
            }
            for r in channel_rows_raw
        ]
    else:
        total_net = sum(int(r[4] or 0) for r in channel_rows)
        channels = [
            {
                "channel": r[0],
                "order_count": int(r[1]),
                "gross_amount_fen": int(r[2] or 0),
                "discount_fen": int(r[3] or 0),
                "net_amount_fen": int(r[4] or 0),
                "actual_revenue_fen": int(r[5] or 0),
                "has_group_buy": bool(r[6]),
                "ratio": round(int(r[4] or 0) / total_net, 4) if total_net > 0 else 0.0,
                "source": "revenue_records",
            }
            for r in channel_rows
        ]

    # 按支付方式聚合
    payment_result = await db.execute(
        text("""
            SELECT
                payment_method,
                COUNT(*) AS cnt,
                SUM(net_amount_fen) AS net_fen
            FROM revenue_records
            WHERE tenant_id = :tenant_id::UUID
              AND store_id = :store_id::UUID
              AND record_date = :record_date
              AND is_deleted = FALSE
            GROUP BY payment_method
            ORDER BY net_fen DESC
        """),
        {
            "tenant_id": str(tid),
            "store_id": str(sid),
            "record_date": biz_date.isoformat(),
        },
    )
    payment_rows = payment_result.fetchall()
    payment_mix = [
        {
            "payment_method": r[0] or "unknown",
            "order_count": int(r[1]),
            "net_amount_fen": int(r[2] or 0),
        }
        for r in payment_rows
    ]

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "date": str(biz_date),
            "total_net_revenue_fen": total_net,
            "channels": channels,
            "payment_mix": payment_mix,
        },
    }


# ─── GET /revenue/channel-mix ─────────────────────────────────────────────────


@router.get("/revenue/channel-mix", summary="渠道构成趋势")
async def get_channel_mix_trend(
    store_id: str = Query(..., description="门店ID"),
    days: int = Query(30, ge=7, le=180, description="查询天数（默认30天）"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """
    查询指定门店最近 N 天的渠道构成趋势。

    返回每日各渠道收入金额，用于叠加面积图或折线图展示渠道结构变化。
    """
    sid = _parse_uuid(store_id, "store_id")
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")

    end_date = date.today()
    start_date = end_date - timedelta(days=days - 1)

    result = await db.execute(
        text("""
            SELECT
                record_date,
                channel,
                SUM(net_amount_fen) AS net_fen
            FROM revenue_records
            WHERE tenant_id = :tenant_id::UUID
              AND store_id = :store_id::UUID
              AND record_date BETWEEN :start_date AND :end_date
              AND is_deleted = FALSE
            GROUP BY record_date, channel
            ORDER BY record_date ASC, net_fen DESC
        """),
        {
            "tenant_id": str(tid),
            "store_id": str(sid),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
    )
    rows = result.fetchall()

    # 按日期聚合，每日包含各渠道数据
    daily_map: dict[str, dict] = {}
    for r in rows:
        d = str(r[0])
        if d not in daily_map:
            daily_map[d] = {"date": d, "channels": {}, "total_fen": 0}
        daily_map[d]["channels"][r[1]] = int(r[2] or 0)
        daily_map[d]["total_fen"] += int(r[2] or 0)

    trend = list(daily_map.values())

    # 汇总各渠道在整段时期的总占比
    channel_totals: dict[str, int] = {}
    for day_data in trend:
        for ch, amt in day_data["channels"].items():
            channel_totals[ch] = channel_totals.get(ch, 0) + amt

    period_total = sum(channel_totals.values())
    channel_summary = [
        {
            "channel": ch,
            "total_fen": amt,
            "ratio": round(amt / period_total, 4) if period_total > 0 else 0.0,
        }
        for ch, amt in sorted(channel_totals.items(), key=lambda x: -x[1])
    ]

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "start_date": str(start_date),
            "end_date": str(end_date),
            "days": days,
            "period_total_fen": period_total,
            "channel_summary": channel_summary,
            "trend": trend,
        },
    }


# ─── GET /revenue/hourly ──────────────────────────────────────────────────────


@router.get("/revenue/hourly", summary="小时收入分布（热力图数据）")
async def get_hourly_revenue(
    store_id: str = Query(..., description="门店ID"),
    revenue_date: str = Query("today", alias="date", description="日期 YYYY-MM-DD 或 today"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """
    查询指定门店指定日期的小时收入分布，返回 0-23 点的收入数据。

    适用于：
    - 客流高峰热力图
    - 营业时段分析
    - 排班优化参考

    数据直接从 orders 表按小时聚合（UTC+8 时区）。
    """
    sid = _parse_uuid(store_id, "store_id")
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    biz_date = _parse_date_param(revenue_date)

    result = await db.execute(
        text("""
            SELECT
                EXTRACT(HOUR FROM order_time AT TIME ZONE 'Asia/Shanghai')::INT AS hour,
                COUNT(*) AS order_count,
                SUM(total_amount_fen - COALESCE(discount_amount_fen, 0)) AS net_fen,
                SUM(COALESCE(discount_amount_fen, 0)) AS discount_fen
            FROM orders
            WHERE tenant_id = :tenant_id::UUID
              AND store_id = :store_id::UUID
              AND status IN ('completed', 'settled', 'paid')
              AND (order_time AT TIME ZONE 'Asia/Shanghai')::date = :biz_date
              AND is_deleted = FALSE
            GROUP BY hour
            ORDER BY hour ASC
        """),
        {
            "tenant_id": str(tid),
            "store_id": str(sid),
            "biz_date": biz_date.isoformat(),
        },
    )
    rows = result.fetchall()

    # 填充 0-23 小时的完整数组（无数据的小时填 0）
    hourly_map: dict[int, dict] = {
        h: {"hour": h, "order_count": 0, "net_revenue_fen": 0, "discount_fen": 0} for h in range(24)
    }
    for r in rows:
        h = int(r[0])
        hourly_map[h] = {
            "hour": h,
            "order_count": int(r[1]),
            "net_revenue_fen": int(r[2] or 0),
            "discount_fen": int(r[3] or 0),
        }

    hourly = [hourly_map[h] for h in range(24)]

    # 标记高峰时段（收入 TOP3 小时）
    sorted_by_revenue = sorted(hourly, key=lambda x: -x["net_revenue_fen"])
    peak_hours = {h["hour"] for h in sorted_by_revenue[:3] if h["net_revenue_fen"] > 0}
    for h_data in hourly:
        h_data["is_peak"] = h_data["hour"] in peak_hours

    total_revenue = sum(h["net_revenue_fen"] for h in hourly)
    total_orders = sum(h["order_count"] for h in hourly)

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "date": str(biz_date),
            "total_net_revenue_fen": total_revenue,
            "total_orders": total_orders,
            "peak_hours": sorted(list(peak_hours)),
            "hourly": hourly,
        },
    }
