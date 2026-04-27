"""宴会分析服务 — S7 宴会分析报表

数据来源：
  - banquet_orders / banquet_leads      宴会订单和商机（tx-trade 已有）
  - banquet_analytics_snapshots          聚合快照（v289 新建）
  - banquet_lost_reasons                 丢单原因（v289 新建）
  - orders + order_items                 实际订单数据

核心分析维度：
  1. 来源转化率 — 各渠道商机→订单转化
  2. 商机转化率按销售 — 销售个人业绩漏斗
  3. 订单分析按类型 — 婚宴/生日/宝宝宴/寿宴等
  4. 销售排名 — 销售业绩排行
  5. 丢单原因TOP10 — 丢单原因分析
  6. 营收趋势 — 按日/周/月宴会营收走势
  7. 宴会仪表盘 — 综合看板
  8. 记录丢单原因 — 写入操作
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


# ─── 宴会类型常量 ──────────────────────────────────────────────────────────────

BANQUET_TYPES = [
    "wedding",  # 婚宴
    "birthday",  # 生日宴
    "baby",  # 宝宝宴
    "longevity",  # 寿宴
    "corporate",  # 商务宴
    "graduation",  # 升学宴
    "housewarming",  # 乔迁宴
    "other",  # 其他
]

BANQUET_TYPE_LABELS = {
    "wedding": "婚宴",
    "birthday": "生日宴",
    "baby": "宝宝宴",
    "longevity": "寿宴",
    "corporate": "商务宴",
    "graduation": "升学宴",
    "housewarming": "乔迁宴",
    "other": "其他",
}

SOURCE_CHANNELS = [
    "walk_in",  # 到店
    "phone",  # 电话
    "wechat",  # 微信
    "miniapp",  # 小程序
    "referral",  # 转介绍
    "wedding_planner",  # 婚庆公司
    "douyin",  # 抖音
    "other",  # 其他
]


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 来源转化率
# ═══════════════════════════════════════════════════════════════════════════════


async def get_source_conversion(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    date_from: date,
    date_to: date,
) -> list[dict]:
    """各渠道商机→订单转化率

    返回每个来源渠道的：线索数、跟进数、转化数、转化率、营收
    """
    result = await db.execute(
        text("""
            SELECT
                COALESCE(source_channel, 'other')               AS source_channel,
                COUNT(*)                                         AS total_leads,
                COUNT(*) FILTER (WHERE status IN
                    ('following', 'quoted', 'confirmed', 'completed'))
                                                                 AS followed_leads,
                COUNT(*) FILTER (WHERE status IN
                    ('confirmed', 'completed'))                  AS converted_leads,
                ROUND(
                    100.0 * COUNT(*) FILTER (WHERE status IN ('confirmed', 'completed'))
                    / NULLIF(COUNT(*), 0),
                    1
                )::float                                         AS conversion_rate_pct,
                COALESCE(SUM(estimated_revenue_fen)
                    FILTER (WHERE status IN ('confirmed', 'completed')), 0)
                                                                 AS converted_revenue_fen
            FROM banquet_leads
            WHERE tenant_id  = :tenant_id
              AND store_id   = :store_id
              AND created_at >= :date_from
              AND created_at <  :date_to + INTERVAL '1 day'
              AND is_deleted  = false
            GROUP BY COALESCE(source_channel, 'other')
            ORDER BY converted_revenue_fen DESC
        """),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "date_from": str(date_from),
            "date_to": str(date_to),
        },
    )
    rows = [dict(r) for r in result.mappings()]
    for row in rows:
        ch = row.get("source_channel", "other")
        row["source_channel_label"] = _channel_label(ch)
    return rows


# ═══════════════════════════════════════════════════════════════════════════════
# 2. 商机转化率按销售
# ═══════════════════════════════════════════════════════════════════════════════


async def get_lead_conversion_by_salesperson(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    date_from: date,
    date_to: date,
) -> list[dict]:
    """按销售员统计商机转化漏斗"""
    result = await db.execute(
        text("""
            SELECT
                salesperson_id,
                salesperson_name,
                COUNT(*)                                         AS total_leads,
                COUNT(*) FILTER (WHERE status IN
                    ('following', 'quoted', 'confirmed', 'completed'))
                                                                 AS followed_leads,
                COUNT(*) FILTER (WHERE status = 'quoted')        AS quoted_leads,
                COUNT(*) FILTER (WHERE status IN
                    ('confirmed', 'completed'))                  AS converted_leads,
                COUNT(*) FILTER (WHERE status = 'lost')          AS lost_leads,
                ROUND(
                    100.0 * COUNT(*) FILTER (WHERE status IN ('confirmed', 'completed'))
                    / NULLIF(COUNT(*), 0),
                    1
                )::float                                         AS conversion_rate_pct,
                COALESCE(SUM(estimated_revenue_fen)
                    FILTER (WHERE status IN ('confirmed', 'completed')), 0)
                                                                 AS converted_revenue_fen
            FROM banquet_leads
            WHERE tenant_id  = :tenant_id
              AND store_id   = :store_id
              AND created_at >= :date_from
              AND created_at <  :date_to + INTERVAL '1 day'
              AND is_deleted  = false
            GROUP BY salesperson_id, salesperson_name
            ORDER BY converted_revenue_fen DESC
        """),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "date_from": str(date_from),
            "date_to": str(date_to),
        },
    )
    return [dict(r) for r in result.mappings()]


# ═══════════════════════════════════════════════════════════════════════════════
# 3. 订单分析按类型
# ═══════════════════════════════════════════════════════════════════════════════


async def get_banquet_order_analysis(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    date_from: date,
    date_to: date,
    banquet_type: Optional[str] = None,
) -> list[dict]:
    """按宴会类型分析订单数量、桌数、营收、桌均"""
    type_filter = ""
    params: dict = {
        "tenant_id": tenant_id,
        "store_id": store_id,
        "date_from": str(date_from),
        "date_to": str(date_to),
    }
    if banquet_type:
        type_filter = "AND banquet_type = :banquet_type"
        params["banquet_type"] = banquet_type

    result = await db.execute(
        text(f"""
            SELECT
                COALESCE(banquet_type, 'other')                  AS banquet_type,
                COUNT(*)                                          AS order_count,
                COALESCE(SUM(table_count), 0)                    AS total_tables,
                COALESCE(SUM(guest_count), 0)                    AS total_guests,
                COALESCE(SUM(total_amount_fen), 0)               AS total_revenue_fen,
                CASE WHEN SUM(table_count) > 0
                    THEN (SUM(total_amount_fen) / SUM(table_count))::bigint
                    ELSE 0
                END                                               AS avg_table_price_fen,
                CASE WHEN COUNT(*) > 0
                    THEN (SUM(total_amount_fen) / COUNT(*))::bigint
                    ELSE 0
                END                                               AS avg_order_fen,
                COALESCE(SUM(deposit_amount_fen), 0)             AS total_deposit_fen,
                COALESCE(SUM(final_payment_fen), 0)              AS total_final_fen
            FROM banquet_orders
            WHERE tenant_id  = :tenant_id
              AND store_id   = :store_id
              AND event_date >= :date_from
              AND event_date <  :date_to + INTERVAL '1 day'
              AND is_deleted  = false
              {type_filter}
            GROUP BY COALESCE(banquet_type, 'other')
            ORDER BY total_revenue_fen DESC
        """),
        params,
    )
    rows = [dict(r) for r in result.mappings()]
    for row in rows:
        bt = row.get("banquet_type", "other")
        row["banquet_type_label"] = BANQUET_TYPE_LABELS.get(bt, bt)
    return rows


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 销售排名
# ═══════════════════════════════════════════════════════════════════════════════


async def get_salesperson_ranking(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    date_from: date,
    date_to: date,
    sort_by: str = "revenue",
    limit: int = 20,
) -> list[dict]:
    """销售业绩排名 — 按营收或成单数排序"""
    order_clause = "total_revenue_fen DESC" if sort_by == "revenue" else "order_count DESC"

    result = await db.execute(
        text(f"""
            SELECT
                salesperson_id,
                salesperson_name,
                COUNT(*)                                          AS order_count,
                COALESCE(SUM(table_count), 0)                    AS total_tables,
                COALESCE(SUM(total_amount_fen), 0)               AS total_revenue_fen,
                CASE WHEN COUNT(*) > 0
                    THEN (SUM(total_amount_fen) / COUNT(*))::bigint
                    ELSE 0
                END                                               AS avg_order_fen,
                ROUND(
                    100.0 * SUM(total_amount_fen)
                    / NULLIF(SUM(SUM(total_amount_fen)) OVER (), 0),
                    1
                )::float                                          AS revenue_share_pct
            FROM banquet_orders
            WHERE tenant_id  = :tenant_id
              AND store_id   = :store_id
              AND event_date >= :date_from
              AND event_date <  :date_to + INTERVAL '1 day'
              AND is_deleted  = false
              AND salesperson_id IS NOT NULL
            GROUP BY salesperson_id, salesperson_name
            ORDER BY {order_clause}
            LIMIT :limit
        """),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "date_from": str(date_from),
            "date_to": str(date_to),
            "limit": limit,
        },
    )
    rows = [dict(r) for r in result.mappings()]
    for idx, row in enumerate(rows, start=1):
        row["rank"] = idx
    return rows


# ═══════════════════════════════════════════════════════════════════════════════
# 5. 丢单原因 TOP10
# ═══════════════════════════════════════════════════════════════════════════════


async def get_lost_reason_analysis(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    date_from: date,
    date_to: date,
    top_n: int = 10,
) -> dict:
    """丢单原因分析 — TOP N 原因 + 总损失金额"""
    # 按原因分类统计
    result = await db.execute(
        text("""
            SELECT
                reason_category,
                COUNT(*)                                          AS lost_count,
                COALESCE(SUM(lost_revenue_fen), 0)               AS lost_revenue_fen,
                COALESCE(SUM(lost_tables), 0)                    AS lost_tables,
                ROUND(
                    100.0 * COUNT(*)
                    / NULLIF(SUM(COUNT(*)) OVER (), 0),
                    1
                )::float                                          AS proportion_pct
            FROM banquet_lost_reasons
            WHERE tenant_id  = :tenant_id
              AND store_id   = :store_id
              AND recorded_at >= :date_from
              AND recorded_at <  :date_to + INTERVAL '1 day'
              AND is_deleted  = false
            GROUP BY reason_category
            ORDER BY lost_count DESC
            LIMIT :top_n
        """),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "date_from": str(date_from),
            "date_to": str(date_to),
            "top_n": top_n,
        },
    )
    reasons = [dict(r) for r in result.mappings()]

    # 竞品分析
    competitor_result = await db.execute(
        text("""
            SELECT
                competitor_name,
                COUNT(*)                                          AS lost_count,
                COALESCE(SUM(lost_revenue_fen), 0)               AS lost_revenue_fen
            FROM banquet_lost_reasons
            WHERE tenant_id  = :tenant_id
              AND store_id   = :store_id
              AND recorded_at >= :date_from
              AND recorded_at <  :date_to + INTERVAL '1 day'
              AND is_deleted  = false
              AND competitor_name IS NOT NULL
              AND competitor_name != ''
            GROUP BY competitor_name
            ORDER BY lost_count DESC
            LIMIT 10
        """),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "date_from": str(date_from),
            "date_to": str(date_to),
        },
    )
    competitors = [dict(r) for r in competitor_result.mappings()]

    total_lost = sum(r.get("lost_count", 0) for r in reasons)
    total_lost_revenue = sum(r.get("lost_revenue_fen", 0) for r in reasons)

    return {
        "total_lost_count": total_lost,
        "total_lost_revenue_fen": total_lost_revenue,
        "reasons": reasons,
        "competitors": competitors,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 6. 营收趋势
# ═══════════════════════════════════════════════════════════════════════════════


async def get_banquet_revenue_trend(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    date_from: date,
    date_to: date,
    granularity: str = "day",
) -> list[dict]:
    """宴会营收趋势 — 按日/周/月聚合"""
    if granularity not in ("day", "week", "month"):
        granularity = "day"

    result = await db.execute(
        text(f"""
            SELECT
                DATE_TRUNC('{granularity}', event_date)::date    AS period,
                COUNT(*)                                          AS order_count,
                COALESCE(SUM(table_count), 0)                    AS total_tables,
                COALESCE(SUM(total_amount_fen), 0)               AS total_revenue_fen,
                COALESCE(SUM(deposit_amount_fen), 0)             AS deposit_fen,
                COALESCE(SUM(final_payment_fen), 0)              AS final_payment_fen,
                CASE WHEN SUM(table_count) > 0
                    THEN (SUM(total_amount_fen) / SUM(table_count))::bigint
                    ELSE 0
                END                                               AS avg_table_price_fen
            FROM banquet_orders
            WHERE tenant_id  = :tenant_id
              AND store_id   = :store_id
              AND event_date >= :date_from
              AND event_date <  :date_to + INTERVAL '1 day'
              AND is_deleted  = false
            GROUP BY DATE_TRUNC('{granularity}', event_date)
            ORDER BY period
        """),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "date_from": str(date_from),
            "date_to": str(date_to),
        },
    )
    items = [dict(r) for r in result.mappings()]
    for item in items:
        if item.get("period") is not None:
            item["period"] = str(item["period"])
    return items


# ═══════════════════════════════════════════════════════════════════════════════
# 7. 宴会仪表盘
# ═══════════════════════════════════════════════════════════════════════════════


async def get_banquet_dashboard(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    date_from: date,
    date_to: date,
) -> dict:
    """宴会综合仪表盘 — 汇总所有核心指标"""

    # 1) 订单总览
    overview_result = await db.execute(
        text("""
            SELECT
                COUNT(*)                                          AS total_orders,
                COALESCE(SUM(table_count), 0)                    AS total_tables,
                COALESCE(SUM(guest_count), 0)                    AS total_guests,
                COALESCE(SUM(total_amount_fen), 0)               AS total_revenue_fen,
                CASE WHEN COUNT(*) > 0
                    THEN (SUM(total_amount_fen) / COUNT(*))::bigint
                    ELSE 0
                END                                               AS avg_order_fen,
                CASE WHEN SUM(table_count) > 0
                    THEN (SUM(total_amount_fen) / SUM(table_count))::bigint
                    ELSE 0
                END                                               AS avg_table_price_fen,
                COALESCE(SUM(deposit_amount_fen), 0)             AS total_deposit_fen,
                COALESCE(SUM(final_payment_fen), 0)              AS total_final_fen
            FROM banquet_orders
            WHERE tenant_id  = :tenant_id
              AND store_id   = :store_id
              AND event_date >= :date_from
              AND event_date <  :date_to + INTERVAL '1 day'
              AND is_deleted  = false
        """),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "date_from": str(date_from),
            "date_to": str(date_to),
        },
    )
    overview_row = overview_result.mappings().first()
    overview = (
        dict(overview_row)
        if overview_row
        else {
            "total_orders": 0,
            "total_tables": 0,
            "total_guests": 0,
            "total_revenue_fen": 0,
            "avg_order_fen": 0,
            "avg_table_price_fen": 0,
            "total_deposit_fen": 0,
            "total_final_fen": 0,
        }
    )

    # 2) 商机漏斗
    funnel_result = await db.execute(
        text("""
            SELECT
                COUNT(*)                                          AS total_leads,
                COUNT(*) FILTER (WHERE status IN
                    ('following', 'quoted', 'confirmed', 'completed'))
                                                                  AS followed,
                COUNT(*) FILTER (WHERE status = 'quoted')         AS quoted,
                COUNT(*) FILTER (WHERE status IN
                    ('confirmed', 'completed'))                   AS converted,
                COUNT(*) FILTER (WHERE status = 'lost')           AS lost,
                ROUND(
                    100.0 * COUNT(*) FILTER (WHERE status IN ('confirmed', 'completed'))
                    / NULLIF(COUNT(*), 0),
                    1
                )::float                                          AS conversion_rate_pct
            FROM banquet_leads
            WHERE tenant_id  = :tenant_id
              AND store_id   = :store_id
              AND created_at >= :date_from
              AND created_at <  :date_to + INTERVAL '1 day'
              AND is_deleted  = false
        """),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "date_from": str(date_from),
            "date_to": str(date_to),
        },
    )
    funnel_row = funnel_result.mappings().first()
    funnel = (
        dict(funnel_row)
        if funnel_row
        else {
            "total_leads": 0,
            "followed": 0,
            "quoted": 0,
            "converted": 0,
            "lost": 0,
            "conversion_rate_pct": 0.0,
        }
    )

    # 3) 按类型分布（饼图数据）
    type_distribution = await get_banquet_order_analysis(db, tenant_id, store_id, date_from, date_to)

    # 4) 近期宴会（未来7天）
    upcoming_result = await db.execute(
        text("""
            SELECT
                id, banquet_type, event_date, host_name,
                table_count, guest_count, total_amount_fen,
                status, salesperson_name
            FROM banquet_orders
            WHERE tenant_id  = :tenant_id
              AND store_id   = :store_id
              AND event_date >= NOW()
              AND event_date <  NOW() + INTERVAL '7 days'
              AND is_deleted  = false
            ORDER BY event_date
            LIMIT 10
        """),
        {"tenant_id": tenant_id, "store_id": store_id},
    )
    upcoming = []
    for r in upcoming_result.mappings():
        row = dict(r)
        row["id"] = str(row["id"])
        if row.get("event_date"):
            row["event_date"] = str(row["event_date"])
        bt = row.get("banquet_type", "other")
        row["banquet_type_label"] = BANQUET_TYPE_LABELS.get(bt, bt)
        upcoming.append(row)

    return {
        "overview": overview,
        "funnel": funnel,
        "type_distribution": type_distribution,
        "upcoming_banquets": upcoming,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 8. 记录丢单原因
# ═══════════════════════════════════════════════════════════════════════════════


async def record_lost_reason(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    data: dict,
) -> dict:
    """记录宴会丢单原因"""
    record_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    await db.execute(
        text("""
            INSERT INTO banquet_lost_reasons (
                id, tenant_id, store_id, banquet_lead_id,
                banquet_type, reason_category, reason_detail,
                competitor_name, lost_revenue_fen, lost_tables,
                salesperson_id, salesperson_name,
                recorded_by, recorded_at, created_at, updated_at
            ) VALUES (
                :id, :tenant_id, :store_id, :banquet_lead_id,
                :banquet_type, :reason_category, :reason_detail,
                :competitor_name, :lost_revenue_fen, :lost_tables,
                :salesperson_id, :salesperson_name,
                :recorded_by, :recorded_at, :created_at, :updated_at
            )
        """),
        {
            "id": record_id,
            "tenant_id": tenant_id,
            "store_id": store_id,
            "banquet_lead_id": data.get("banquet_lead_id"),
            "banquet_type": data.get("banquet_type"),
            "reason_category": data["reason_category"],
            "reason_detail": data.get("reason_detail"),
            "competitor_name": data.get("competitor_name"),
            "lost_revenue_fen": data.get("lost_revenue_fen", 0),
            "lost_tables": data.get("lost_tables", 0),
            "salesperson_id": data.get("salesperson_id"),
            "salesperson_name": data.get("salesperson_name"),
            "recorded_by": data["recorded_by"],
            "recorded_at": now,
            "created_at": now,
            "updated_at": now,
        },
    )
    await db.commit()

    logger.info(
        "banquet_lost_reason_recorded",
        record_id=record_id,
        tenant_id=tenant_id,
        store_id=store_id,
        reason_category=data["reason_category"],
    )

    return {
        "id": record_id,
        "reason_category": data["reason_category"],
        "recorded_at": now.isoformat(),
    }


# ─── 内部辅助 ─────────────────────────────────────────────────────────────────


def _channel_label(channel: str) -> str:
    """来源渠道 code → 中文标签"""
    labels = {
        "walk_in": "到店",
        "phone": "电话",
        "wechat": "微信",
        "miniapp": "小程序",
        "referral": "转介绍",
        "wedding_planner": "婚庆公司",
        "douyin": "抖音",
        "other": "其他",
    }
    return labels.get(channel, channel)
