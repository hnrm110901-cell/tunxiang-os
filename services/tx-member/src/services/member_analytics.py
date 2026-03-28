"""会员分析服务 (D4) — 增长、活跃、复购、流失预警、偏好洞察

所有金额单位：分(fen)。
RFM: R(最近消费天数) F(消费频次) M(消费金额) 各1-5分。
流失预警: >60天未消费=高风险, 30-60天=中风险。
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import select, func, case, text, and_, extract
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Customer, Order, OrderItem

logger = structlog.get_logger(__name__)

# ── 常量 ──────────────────────────────────────────────────────
CHURN_HIGH_RISK_DAYS = 60
CHURN_MEDIUM_RISK_DAYS = 30

FREQUENCY_BANDS = [
    ("1次", 1, 1),
    ("2-3次", 2, 3),
    ("4-6次", 4, 6),
    ("7-12次", 7, 12),
    ("13次以上", 13, 999999),
]


def _safe_ratio(numerator: int | float, denominator: int | float) -> float:
    """安全计算比率，避免除零"""
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 4)


def _to_uuid(val: str) -> uuid.UUID:
    return uuid.UUID(val)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    """设置 RLS tenant 上下文"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ── 1. 会员增长分析 ──────────────────────────────────────────

async def member_growth(
    tenant_id: str,
    date_range: tuple[str, str],
    db: AsyncSession,
) -> dict[str, Any]:
    """会员增长分析

    Args:
        tenant_id: 租户 ID
        date_range: (start_date, end_date) YYYY-MM-DD
        db: 数据库会话

    Returns:
        {new_members, total, growth_rate, by_channel}
    """
    await _set_tenant(db, tenant_id)
    tid = _to_uuid(tenant_id)
    start_dt = datetime.fromisoformat(date_range[0]).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(date_range[1]).replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc,
    )

    # 期间新增会员数
    new_count_result = await db.execute(
        select(func.count(Customer.id))
        .where(Customer.tenant_id == tid)
        .where(Customer.is_deleted == False)  # noqa: E712
        .where(Customer.is_merged == False)  # noqa: E712
        .where(Customer.created_at >= start_dt)
        .where(Customer.created_at <= end_dt)
    )
    new_members = new_count_result.scalar() or 0

    # 总会员数（截至 end_dt）
    total_result = await db.execute(
        select(func.count(Customer.id))
        .where(Customer.tenant_id == tid)
        .where(Customer.is_deleted == False)  # noqa: E712
        .where(Customer.is_merged == False)  # noqa: E712
        .where(Customer.created_at <= end_dt)
    )
    total = total_result.scalar() or 0

    # 前期总数
    prev_total = total - new_members
    growth_rate = _safe_ratio(new_members, prev_total) if prev_total > 0 else 0.0

    # 按来源渠道分布
    channel_result = await db.execute(
        select(
            func.coalesce(Customer.source, "unknown").label("channel"),
            func.count(Customer.id).label("cnt"),
        )
        .where(Customer.tenant_id == tid)
        .where(Customer.is_deleted == False)  # noqa: E712
        .where(Customer.is_merged == False)  # noqa: E712
        .where(Customer.created_at >= start_dt)
        .where(Customer.created_at <= end_dt)
        .group_by("channel")
    )
    by_channel = {row[0]: row[1] for row in channel_result.all()}

    logger.info(
        "member_growth_analyzed",
        tenant_id=tenant_id,
        new_members=new_members,
        total=total,
        growth_rate=growth_rate,
    )

    return {
        "new_members": new_members,
        "total": total,
        "growth_rate": growth_rate,
        "by_channel": by_channel,
        "date_range": list(date_range),
    }


# ── 2. 活跃度分析 ─────────────────────────────────────────────

async def activity_analysis(
    tenant_id: str,
    date_range: tuple[str, str],
    db: AsyncSession,
) -> dict[str, Any]:
    """会员活跃度分析

    Returns:
        {active_rate, dau, mau, by_store}
    """
    await _set_tenant(db, tenant_id)
    tid = _to_uuid(tenant_id)
    start_dt = datetime.fromisoformat(date_range[0]).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(date_range[1]).replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc,
    )

    # 总会员数
    total_result = await db.execute(
        select(func.count(Customer.id))
        .where(Customer.tenant_id == tid)
        .where(Customer.is_deleted == False)  # noqa: E712
        .where(Customer.is_merged == False)  # noqa: E712
    )
    total_members = total_result.scalar() or 0

    # 期间内有消费的去重会员数（活跃会员）
    active_result = await db.execute(
        select(func.count(func.distinct(Order.customer_id)))
        .where(Order.tenant_id == tid)
        .where(Order.is_deleted == False)  # noqa: E712
        .where(Order.order_time >= start_dt)
        .where(Order.order_time <= end_dt)
        .where(Order.customer_id.isnot(None))
    )
    active_members = active_result.scalar() or 0
    active_rate = _safe_ratio(active_members, total_members)

    # 日均活跃（DAU 近似：期间内去重客户 / 天数）
    days = max((end_dt - start_dt).days, 1)
    dau = round(active_members / days, 1)

    # 月活（取最近30天去重）
    mau_start = end_dt - timedelta(days=30)
    mau_result = await db.execute(
        select(func.count(func.distinct(Order.customer_id)))
        .where(Order.tenant_id == tid)
        .where(Order.is_deleted == False)  # noqa: E712
        .where(Order.order_time >= mau_start)
        .where(Order.order_time <= end_dt)
        .where(Order.customer_id.isnot(None))
    )
    mau = mau_result.scalar() or 0

    # 按门店分布
    store_result = await db.execute(
        select(
            Order.store_id,
            func.count(func.distinct(Order.customer_id)).label("active_count"),
        )
        .where(Order.tenant_id == tid)
        .where(Order.is_deleted == False)  # noqa: E712
        .where(Order.order_time >= start_dt)
        .where(Order.order_time <= end_dt)
        .where(Order.customer_id.isnot(None))
        .group_by(Order.store_id)
    )
    by_store = {str(row[0]): row[1] for row in store_result.all()}

    logger.info(
        "activity_analyzed",
        tenant_id=tenant_id,
        active_rate=active_rate,
        dau=dau,
        mau=mau,
    )

    return {
        "active_rate": active_rate,
        "active_members": active_members,
        "total_members": total_members,
        "dau": dau,
        "mau": mau,
        "by_store": by_store,
        "date_range": list(date_range),
    }


# ── 3. 复购分析 ───────────────────────────────────────────────

async def repurchase_analysis(
    tenant_id: str,
    date_range: tuple[str, str],
    db: AsyncSession,
) -> dict[str, Any]:
    """复购率分析

    Returns:
        {repurchase_rate, avg_interval_days, by_frequency_band}
    """
    await _set_tenant(db, tenant_id)
    tid = _to_uuid(tenant_id)
    start_dt = datetime.fromisoformat(date_range[0]).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(date_range[1]).replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc,
    )

    # 每位会员在期间内的消费次数
    freq_sub = (
        select(
            Order.customer_id,
            func.count(Order.id).label("order_count"),
        )
        .where(Order.tenant_id == tid)
        .where(Order.is_deleted == False)  # noqa: E712
        .where(Order.order_time >= start_dt)
        .where(Order.order_time <= end_dt)
        .where(Order.customer_id.isnot(None))
        .group_by(Order.customer_id)
    ).subquery()

    # 总消费会员数
    total_result = await db.execute(
        select(func.count()).select_from(freq_sub)
    )
    total_buyers = total_result.scalar() or 0

    # 复购会员数（消费 >= 2 次）
    repurchase_result = await db.execute(
        select(func.count()).select_from(
            select(freq_sub.c.customer_id)
            .where(freq_sub.c.order_count >= 2)
            .subquery()
        )
    )
    repurchase_count = repurchase_result.scalar() or 0
    repurchase_rate = _safe_ratio(repurchase_count, total_buyers)

    # 平均复购间隔天数（从 Customer 表的统计字段近似）
    interval_result = await db.execute(
        select(func.avg(Customer.rfm_recency_days))
        .where(Customer.tenant_id == tid)
        .where(Customer.is_deleted == False)  # noqa: E712
        .where(Customer.is_merged == False)  # noqa: E712
        .where(Customer.total_order_count >= 2)
    )
    avg_interval_days = round(float(interval_result.scalar() or 0), 1)

    # 按频次带分布
    by_frequency_band: list[dict] = []
    for label, low, high in FREQUENCY_BANDS:
        band_result = await db.execute(
            select(func.count()).select_from(
                select(freq_sub.c.customer_id)
                .where(freq_sub.c.order_count >= low)
                .where(freq_sub.c.order_count <= high)
                .subquery()
            )
        )
        cnt = band_result.scalar() or 0
        by_frequency_band.append({
            "band": label,
            "count": cnt,
            "ratio": _safe_ratio(cnt, total_buyers),
        })

    logger.info(
        "repurchase_analyzed",
        tenant_id=tenant_id,
        repurchase_rate=repurchase_rate,
        avg_interval_days=avg_interval_days,
    )

    return {
        "repurchase_rate": repurchase_rate,
        "repurchase_count": repurchase_count,
        "total_buyers": total_buyers,
        "avg_interval_days": avg_interval_days,
        "by_frequency_band": by_frequency_band,
        "date_range": list(date_range),
    }


# ── 4. 流失预警 ───────────────────────────────────────────────

async def churn_prediction(
    tenant_id: str,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """流失预警预测

    规则：
      >60天未消费 → 高风险 (risk_score >= 0.7)
      30-60天未消费 → 中风险 (risk_score 0.4-0.7)
      <30天 → 低风险

    Returns:
        [{customer_id, risk_score, last_visit, days_since, predicted_churn_prob}]
    """
    await _set_tenant(db, tenant_id)
    tid = _to_uuid(tenant_id)
    now = datetime.now(timezone.utc)

    # 查找有消费记录但近期不活跃的会员
    result = await db.execute(
        select(Customer)
        .where(Customer.tenant_id == tid)
        .where(Customer.is_deleted == False)  # noqa: E712
        .where(Customer.is_merged == False)  # noqa: E712
        .where(Customer.last_order_at.isnot(None))
        .where(Customer.total_order_count >= 1)
        .order_by(Customer.last_order_at.asc())  # 最久未消费排前
        .limit(200)
    )
    customers = result.scalars().all()

    predictions: list[dict] = []
    for c in customers:
        last_visit = c.last_order_at
        if last_visit is None:
            continue

        # 确保 last_visit 有时区信息
        if last_visit.tzinfo is None:
            last_visit = last_visit.replace(tzinfo=timezone.utc)

        days_since = (now - last_visit).days

        # 计算风险分
        if days_since > CHURN_HIGH_RISK_DAYS:
            risk_score = min(0.7 + (days_since - CHURN_HIGH_RISK_DAYS) * 0.003, 1.0)
        elif days_since > CHURN_MEDIUM_RISK_DAYS:
            risk_score = 0.4 + (days_since - CHURN_MEDIUM_RISK_DAYS) / (
                CHURN_HIGH_RISK_DAYS - CHURN_MEDIUM_RISK_DAYS
            ) * 0.3
        else:
            risk_score = days_since / CHURN_MEDIUM_RISK_DAYS * 0.4

        risk_score = round(risk_score, 3)

        # 综合 RFM 调整流失概率
        r_score = c.r_score or 3
        f_score = c.f_score or 3
        # R 低（=长期未消费）且 F 低（=不常来）→ 流失概率更高
        rfm_factor = 1.0 + (5 - r_score) * 0.05 + (5 - f_score) * 0.03
        predicted_churn_prob = round(min(risk_score * rfm_factor, 1.0), 3)

        # 只返回中风险以上
        if days_since >= CHURN_MEDIUM_RISK_DAYS:
            predictions.append({
                "customer_id": str(c.id),
                "display_name": c.display_name,
                "primary_phone": c.primary_phone,
                "risk_score": risk_score,
                "last_visit": last_visit.isoformat(),
                "days_since": days_since,
                "predicted_churn_prob": predicted_churn_prob,
                "risk_level": "high" if days_since > CHURN_HIGH_RISK_DAYS else "medium",
                "rfm_level": c.rfm_level,
                "total_order_count": c.total_order_count,
                "total_order_amount_fen": c.total_order_amount_fen,
            })

    # 按风险分降序
    predictions.sort(key=lambda x: x["risk_score"], reverse=True)

    logger.info(
        "churn_prediction_completed",
        tenant_id=tenant_id,
        high_risk=sum(1 for p in predictions if p["risk_level"] == "high"),
        medium_risk=sum(1 for p in predictions if p["risk_level"] == "medium"),
        total=len(predictions),
    )

    return predictions


# ── 5. 偏好洞察 ───────────────────────────────────────────────

async def preference_insight(
    customer_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """单个会员偏好洞察

    Returns:
        {favorite_dishes, visit_pattern, avg_spend_fen, preferred_time}
    """
    await _set_tenant(db, tenant_id)
    tid = _to_uuid(tenant_id)
    cid = _to_uuid(customer_id)

    # 会员基础信息
    cust_result = await db.execute(
        select(Customer)
        .where(Customer.id == cid)
        .where(Customer.tenant_id == tid)
        .where(Customer.is_deleted == False)  # noqa: E712
    )
    customer = cust_result.scalar_one_or_none()
    if not customer:
        return {"error": "customer_not_found"}

    # 最爱菜品 TOP 10（按点单次数）
    dish_result = await db.execute(
        select(
            OrderItem.item_name,
            func.sum(OrderItem.quantity).label("total_qty"),
            func.count(OrderItem.id).label("order_times"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.tenant_id == tid)
        .where(Order.customer_id == cid)
        .where(Order.is_deleted == False)  # noqa: E712
        .group_by(OrderItem.item_name)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(10)
    )
    favorite_dishes = [
        {"name": row[0], "total_qty": int(row[1]), "order_times": row[2]}
        for row in dish_result.all()
    ]

    # 到店时段分布
    time_result = await db.execute(
        select(
            extract("hour", Order.order_time).label("hour"),
            func.count(Order.id).label("cnt"),
        )
        .where(Order.tenant_id == tid)
        .where(Order.customer_id == cid)
        .where(Order.is_deleted == False)  # noqa: E712
        .group_by("hour")
        .order_by(func.count(Order.id).desc())
    )
    time_rows = time_result.all()
    visit_pattern = {f"{int(row[0]):02d}:00": row[1] for row in time_rows}
    preferred_time = f"{int(time_rows[0][0]):02d}:00" if time_rows else None

    # 到店星期分布
    dow_result = await db.execute(
        select(
            extract("dow", Order.order_time).label("dow"),
            func.count(Order.id).label("cnt"),
        )
        .where(Order.tenant_id == tid)
        .where(Order.customer_id == cid)
        .where(Order.is_deleted == False)  # noqa: E712
        .group_by("dow")
        .order_by(func.count(Order.id).desc())
    )
    dow_map = {0: "周日", 1: "周一", 2: "周二", 3: "周三", 4: "周四", 5: "周五", 6: "周六"}
    day_pattern = {dow_map.get(int(row[0]), str(row[0])): row[1] for row in dow_result.all()}

    # 平均消费金额
    avg_spend_fen = customer.total_order_amount_fen // max(customer.total_order_count, 1)

    logger.info(
        "preference_insight_generated",
        tenant_id=tenant_id,
        customer_id=customer_id,
        favorite_count=len(favorite_dishes),
    )

    return {
        "customer_id": customer_id,
        "display_name": customer.display_name,
        "favorite_dishes": favorite_dishes,
        "visit_pattern": visit_pattern,
        "day_pattern": day_pattern,
        "avg_spend_fen": avg_spend_fen,
        "preferred_time": preferred_time,
        "rfm": {
            "r_score": customer.r_score,
            "f_score": customer.f_score,
            "m_score": customer.m_score,
            "level": customer.rfm_level,
        },
        "total_order_count": customer.total_order_count,
        "total_order_amount_fen": customer.total_order_amount_fen,
        "tags": customer.tags,
    }
