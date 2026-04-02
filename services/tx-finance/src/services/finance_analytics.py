"""财务分析服务 (D5) — 营收构成、折扣结构、优惠券成本、门店利润、财务稽核

所有金额单位：分(fen)。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import extract, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Order, OrderItem, Store

logger = structlog.get_logger(__name__)


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


# ── 1. 营收构成分析 ──────────────────────────────────────────

async def revenue_composition(
    store_id: str,
    date_range: tuple[str, str],
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """营收构成分析 — 按来源、按支付方式

    Returns:
        {
            by_source: [{source: "堂食"/"外卖"/"宴席"/..., amount_fen, ratio}],
            by_payment: [{method: "微信"/"支付宝"/"现金"/"会员"/"挂账", amount_fen, ratio}],
            total_revenue_fen,
        }
    """
    await _set_tenant(db, tenant_id)
    tid = _to_uuid(tenant_id)
    sid = _to_uuid(store_id)
    start_dt = datetime.fromisoformat(date_range[0]).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(date_range[1]).replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc,
    )

    # 按订单类型（来源）分组
    source_map = {
        "dine_in": "堂食",
        "takeaway": "外卖",
        "delivery": "外卖",
        "banquet": "宴席",
        "retail": "零售",
        "catering": "团餐",
    }

    source_result = await db.execute(
        select(
            Order.order_type,
            func.sum(Order.final_amount_fen).label("amount"),
            func.count(Order.id).label("order_count"),
        )
        .where(Order.tenant_id == tid)
        .where(Order.store_id == sid)
        .where(Order.is_deleted == False)  # noqa: E712
        .where(Order.order_time >= start_dt)
        .where(Order.order_time <= end_dt)
        .where(Order.status.in_(["completed", "paid"]))
        .group_by(Order.order_type)
    )
    source_rows = source_result.all()

    total_revenue_fen = sum(int(row[1] or 0) for row in source_rows)

    by_source = [
        {
            "source": source_map.get(row[0], row[0] or "其他"),
            "order_type": row[0],
            "amount_fen": int(row[1] or 0),
            "order_count": row[2],
            "ratio": _safe_ratio(int(row[1] or 0), total_revenue_fen),
        }
        for row in source_rows
    ]

    # 按支付方式分析 — 从 order_metadata 中的 payment_method 或 discount_type 推断
    # 这里使用简化的模式：从 Order 表的 metadata JSON 提取
    # 实际部署时应连接 payment 表
    payment_result = await db.execute(
        select(
            func.coalesce(
                Order.order_metadata["payment_method"].as_string(),
                text("'unknown'"),
            ).label("method"),
            func.sum(Order.final_amount_fen).label("amount"),
        )
        .where(Order.tenant_id == tid)
        .where(Order.store_id == sid)
        .where(Order.is_deleted == False)  # noqa: E712
        .where(Order.order_time >= start_dt)
        .where(Order.order_time <= end_dt)
        .where(Order.status.in_(["completed", "paid"]))
        .group_by("method")
    )
    payment_map = {
        "wechat": "微信",
        "alipay": "支付宝",
        "cash": "现金",
        "member_balance": "会员",
        "credit": "挂账",
        "unionpay": "银联",
        "unknown": "未知",
    }
    payment_rows = payment_result.all()
    by_payment = [
        {
            "method": payment_map.get(row[0], row[0] or "未知"),
            "payment_key": row[0],
            "amount_fen": int(row[1] or 0),
            "ratio": _safe_ratio(int(row[1] or 0), total_revenue_fen),
        }
        for row in payment_rows
    ]

    logger.info(
        "revenue_composition_analyzed",
        tenant_id=tenant_id,
        store_id=store_id,
        total_revenue_fen=total_revenue_fen,
    )

    return {
        "by_source": by_source,
        "by_payment": by_payment,
        "total_revenue_fen": total_revenue_fen,
        "date_range": list(date_range),
    }


# ── 2. 折扣结构分析 ──────────────────────────────────────────

async def discount_structure(
    store_id: str,
    date_range: tuple[str, str],
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """折扣结构分析

    Returns:
        {total_discount_fen, discount_rate, by_type: [会员折扣/活动/赠菜/员工餐]}
    """
    await _set_tenant(db, tenant_id)
    tid = _to_uuid(tenant_id)
    sid = _to_uuid(store_id)
    start_dt = datetime.fromisoformat(date_range[0]).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(date_range[1]).replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc,
    )

    # 总营收和总折扣
    totals_result = await db.execute(
        select(
            func.sum(Order.total_amount_fen).label("gross_amount"),
            func.sum(Order.discount_amount_fen).label("total_discount"),
            func.sum(Order.final_amount_fen).label("net_amount"),
        )
        .where(Order.tenant_id == tid)
        .where(Order.store_id == sid)
        .where(Order.is_deleted == False)  # noqa: E712
        .where(Order.order_time >= start_dt)
        .where(Order.order_time <= end_dt)
        .where(Order.status.in_(["completed", "paid"]))
    )
    totals = totals_result.one()
    gross_amount_fen = int(totals[0] or 0)
    total_discount_fen = int(totals[1] or 0)
    net_amount_fen = int(totals[2] or 0)
    discount_rate = _safe_ratio(total_discount_fen, gross_amount_fen)

    # 按折扣类型分组
    discount_type_map = {
        "coupon": "活动优惠",
        "vip": "会员折扣",
        "manager": "经理折扣",
        "promotion": "促销活动",
        None: "其他",
    }

    type_result = await db.execute(
        select(
            func.coalesce(Order.discount_type, text("'other'")).label("dtype"),
            func.sum(Order.discount_amount_fen).label("amount"),
            func.count(Order.id).label("order_count"),
        )
        .where(Order.tenant_id == tid)
        .where(Order.store_id == sid)
        .where(Order.is_deleted == False)  # noqa: E712
        .where(Order.order_time >= start_dt)
        .where(Order.order_time <= end_dt)
        .where(Order.discount_amount_fen > 0)
        .group_by("dtype")
    )

    by_type = [
        {
            "type": discount_type_map.get(row[0], row[0] or "其他"),
            "discount_key": row[0],
            "amount_fen": int(row[1] or 0),
            "order_count": row[2],
            "ratio": _safe_ratio(int(row[1] or 0), total_discount_fen),
        }
        for row in type_result.all()
    ]

    # 赠菜统计
    gift_result = await db.execute(
        select(func.sum(OrderItem.subtotal_fen))
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.tenant_id == tid)
        .where(Order.store_id == sid)
        .where(Order.is_deleted == False)  # noqa: E712
        .where(Order.order_time >= start_dt)
        .where(Order.order_time <= end_dt)
        .where(OrderItem.gift_flag == True)  # noqa: E712
    )
    gift_cost_fen = int(gift_result.scalar() or 0)
    if gift_cost_fen > 0:
        by_type.append({
            "type": "赠菜",
            "discount_key": "gift",
            "amount_fen": gift_cost_fen,
            "order_count": 0,
            "ratio": _safe_ratio(gift_cost_fen, total_discount_fen + gift_cost_fen),
        })

    logger.info(
        "discount_structure_analyzed",
        tenant_id=tenant_id,
        store_id=store_id,
        total_discount_fen=total_discount_fen,
        discount_rate=discount_rate,
    )

    return {
        "total_discount_fen": total_discount_fen,
        "gross_amount_fen": gross_amount_fen,
        "net_amount_fen": net_amount_fen,
        "discount_rate": discount_rate,
        "by_type": by_type,
        "gift_cost_fen": gift_cost_fen,
        "date_range": list(date_range),
    }


# ── 3. 优惠券成本分析 ────────────────────────────────────────

async def coupon_cost_analysis(
    store_id: str,
    date_range: tuple[str, str],
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """优惠券成本与 ROI 分析

    Returns:
        {total_coupon_cost_fen, roi, by_campaign}
    """
    await _set_tenant(db, tenant_id)
    tid = _to_uuid(tenant_id)
    sid = _to_uuid(store_id)
    start_dt = datetime.fromisoformat(date_range[0]).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(date_range[1]).replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc,
    )

    # 优惠券相关订单：discount_type = 'coupon' 或 'promotion'
    coupon_result = await db.execute(
        select(
            func.sum(Order.discount_amount_fen).label("coupon_cost"),
            func.sum(Order.final_amount_fen).label("coupon_revenue"),
            func.count(Order.id).label("coupon_orders"),
        )
        .where(Order.tenant_id == tid)
        .where(Order.store_id == sid)
        .where(Order.is_deleted == False)  # noqa: E712
        .where(Order.order_time >= start_dt)
        .where(Order.order_time <= end_dt)
        .where(Order.discount_type.in_(["coupon", "promotion"]))
        .where(Order.status.in_(["completed", "paid"]))
    )
    row = coupon_result.one()
    total_coupon_cost_fen = int(row[0] or 0)
    coupon_revenue_fen = int(row[1] or 0)
    coupon_order_count = row[2] or 0

    # ROI = (券带来营收 - 券成本) / 券成本
    roi = _safe_ratio(coupon_revenue_fen - total_coupon_cost_fen, total_coupon_cost_fen)

    # 按活动分组（使用 sales_channel_id 作为 campaign 近似标识）
    campaign_result = await db.execute(
        select(
            func.coalesce(Order.sales_channel_id, text("'direct'")).label("campaign"),
            func.sum(Order.discount_amount_fen).label("cost"),
            func.sum(Order.final_amount_fen).label("revenue"),
            func.count(Order.id).label("orders"),
        )
        .where(Order.tenant_id == tid)
        .where(Order.store_id == sid)
        .where(Order.is_deleted == False)  # noqa: E712
        .where(Order.order_time >= start_dt)
        .where(Order.order_time <= end_dt)
        .where(Order.discount_type.in_(["coupon", "promotion"]))
        .where(Order.status.in_(["completed", "paid"]))
        .group_by("campaign")
    )

    by_campaign = [
        {
            "campaign": row[0],
            "cost_fen": int(row[1] or 0),
            "revenue_fen": int(row[2] or 0),
            "order_count": row[3],
            "roi": _safe_ratio(int(row[2] or 0) - int(row[1] or 0), int(row[1] or 0)),
        }
        for row in campaign_result.all()
    ]

    logger.info(
        "coupon_cost_analyzed",
        tenant_id=tenant_id,
        store_id=store_id,
        total_coupon_cost_fen=total_coupon_cost_fen,
        roi=roi,
    )

    return {
        "total_coupon_cost_fen": total_coupon_cost_fen,
        "coupon_revenue_fen": coupon_revenue_fen,
        "coupon_order_count": coupon_order_count,
        "roi": roi,
        "by_campaign": by_campaign,
        "date_range": list(date_range),
    }


# ── 4. 门店利润分析 ──────────────────────────────────────────

async def store_profit_analysis(
    store_id: str,
    date_range: tuple[str, str],
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """门店利润分析（简化版 P&L）

    Returns:
        {revenue_fen, food_cost_fen, labor_cost_fen, rent_fen, other_fen, profit_fen, profit_rate}
    """
    await _set_tenant(db, tenant_id)
    tid = _to_uuid(tenant_id)
    sid = _to_uuid(store_id)
    start_dt = datetime.fromisoformat(date_range[0]).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(date_range[1]).replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc,
    )

    # 营收
    revenue_result = await db.execute(
        select(func.sum(Order.final_amount_fen))
        .where(Order.tenant_id == tid)
        .where(Order.store_id == sid)
        .where(Order.is_deleted == False)  # noqa: E712
        .where(Order.order_time >= start_dt)
        .where(Order.order_time <= end_dt)
        .where(Order.status.in_(["completed", "paid"]))
    )
    revenue_fen = int(revenue_result.scalar() or 0)

    # 食材成本（从 OrderItem.food_cost_fen 累计）
    food_cost_result = await db.execute(
        select(func.sum(OrderItem.food_cost_fen))
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.tenant_id == tid)
        .where(Order.store_id == sid)
        .where(Order.is_deleted == False)  # noqa: E712
        .where(Order.order_time >= start_dt)
        .where(Order.order_time <= end_dt)
        .where(Order.status.in_(["completed", "paid"]))
    )
    food_cost_fen = int(food_cost_result.scalar() or 0)

    # 门店配置中的固定成本（从 Store 表读取目标值作为预算基准）
    store_result = await db.execute(
        select(Store)
        .where(Store.id == sid)
        .where(Store.tenant_id == tid)
    )
    store = store_result.scalar_one_or_none()

    # 人工/租金等按月度目标估算（实际部署应从财务模块获取）
    days = max((end_dt - start_dt).days, 1)
    monthly_target = store.monthly_revenue_target_fen if store else 0
    labor_ratio = store.labor_cost_ratio_target if store and store.labor_cost_ratio_target else 0.25
    cost_ratio = store.cost_ratio_target if store and store.cost_ratio_target else 0.35

    labor_cost_fen = int(revenue_fen * labor_ratio)
    rent_fen = int(revenue_fen * 0.10)  # 租金按营收 10% 预估
    other_fen = int(revenue_fen * 0.05)  # 其他费用按 5% 预估

    profit_fen = revenue_fen - food_cost_fen - labor_cost_fen - rent_fen - other_fen
    profit_rate = _safe_ratio(profit_fen, revenue_fen)

    # 毛利率
    gross_profit_fen = revenue_fen - food_cost_fen
    gross_margin = _safe_ratio(gross_profit_fen, revenue_fen)

    logger.info(
        "store_profit_analyzed",
        tenant_id=tenant_id,
        store_id=store_id,
        revenue_fen=revenue_fen,
        profit_fen=profit_fen,
        profit_rate=profit_rate,
    )

    return {
        "store_id": store_id,
        "revenue_fen": revenue_fen,
        "food_cost_fen": food_cost_fen,
        "labor_cost_fen": labor_cost_fen,
        "rent_fen": rent_fen,
        "other_fen": other_fen,
        "gross_profit_fen": gross_profit_fen,
        "gross_margin": gross_margin,
        "profit_fen": profit_fen,
        "profit_rate": profit_rate,
        "date_range": list(date_range),
    }


# ── 5. 财务稽核视图 ──────────────────────────────────────────

async def financial_audit_view(
    store_id: str,
    audit_date: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """财务稽核视图 — 当日收支明细

    Returns:
        日维度的完整收支明细，用于财务对账
    """
    await _set_tenant(db, tenant_id)
    tid = _to_uuid(tenant_id)
    sid = _to_uuid(store_id)
    day_start = datetime.fromisoformat(audit_date).replace(
        hour=0, minute=0, second=0, tzinfo=timezone.utc,
    )
    day_end = datetime.fromisoformat(audit_date).replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc,
    )

    # 订单汇总
    orders_result = await db.execute(
        select(
            func.count(Order.id).label("order_count"),
            func.sum(Order.total_amount_fen).label("gross_revenue"),
            func.sum(Order.discount_amount_fen).label("total_discount"),
            func.sum(Order.final_amount_fen).label("net_revenue"),
        )
        .where(Order.tenant_id == tid)
        .where(Order.store_id == sid)
        .where(Order.is_deleted == False)  # noqa: E712
        .where(Order.order_time >= day_start)
        .where(Order.order_time <= day_end)
        .where(Order.status.in_(["completed", "paid"]))
    )
    summary = orders_result.one()
    order_count = summary[0] or 0
    gross_revenue_fen = int(summary[1] or 0)
    total_discount_fen = int(summary[2] or 0)
    net_revenue_fen = int(summary[3] or 0)

    # 退菜/退单统计
    return_result = await db.execute(
        select(
            func.count(OrderItem.id).label("return_count"),
            func.sum(OrderItem.subtotal_fen).label("return_amount"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.tenant_id == tid)
        .where(Order.store_id == sid)
        .where(Order.order_time >= day_start)
        .where(Order.order_time <= day_end)
        .where(OrderItem.return_flag == True)  # noqa: E712
    )
    return_row = return_result.one()
    return_count = return_row[0] or 0
    return_amount_fen = int(return_row[1] or 0)

    # 赠菜统计
    gift_result = await db.execute(
        select(
            func.count(OrderItem.id).label("gift_count"),
            func.sum(OrderItem.subtotal_fen).label("gift_amount"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.tenant_id == tid)
        .where(Order.store_id == sid)
        .where(Order.order_time >= day_start)
        .where(Order.order_time <= day_end)
        .where(OrderItem.gift_flag == True)  # noqa: E712
    )
    gift_row = gift_result.one()
    gift_count = gift_row[0] or 0
    gift_amount_fen = int(gift_row[1] or 0)

    # 异常订单
    abnormal_result = await db.execute(
        select(func.count(Order.id))
        .where(Order.tenant_id == tid)
        .where(Order.store_id == sid)
        .where(Order.order_time >= day_start)
        .where(Order.order_time <= day_end)
        .where(Order.abnormal_flag == True)  # noqa: E712
    )
    abnormal_count = abnormal_result.scalar() or 0

    # 毛利告警
    margin_alert_result = await db.execute(
        select(func.count(Order.id))
        .where(Order.tenant_id == tid)
        .where(Order.store_id == sid)
        .where(Order.order_time >= day_start)
        .where(Order.order_time <= day_end)
        .where(Order.margin_alert_flag == True)  # noqa: E712
    )
    margin_alert_count = margin_alert_result.scalar() or 0

    # 按小时分布
    hourly_result = await db.execute(
        select(
            extract("hour", Order.order_time).label("hour"),
            func.count(Order.id).label("cnt"),
            func.sum(Order.final_amount_fen).label("amount"),
        )
        .where(Order.tenant_id == tid)
        .where(Order.store_id == sid)
        .where(Order.is_deleted == False)  # noqa: E712
        .where(Order.order_time >= day_start)
        .where(Order.order_time <= day_end)
        .where(Order.status.in_(["completed", "paid"]))
        .group_by("hour")
        .order_by("hour")
    )
    hourly_breakdown = [
        {
            "hour": f"{int(row[0]):02d}:00",
            "order_count": row[1],
            "revenue_fen": int(row[2] or 0),
        }
        for row in hourly_result.all()
    ]

    logger.info(
        "financial_audit_view_generated",
        tenant_id=tenant_id,
        store_id=store_id,
        audit_date=audit_date,
        order_count=order_count,
        net_revenue_fen=net_revenue_fen,
    )

    return {
        "store_id": store_id,
        "audit_date": audit_date,
        "summary": {
            "order_count": order_count,
            "gross_revenue_fen": gross_revenue_fen,
            "total_discount_fen": total_discount_fen,
            "net_revenue_fen": net_revenue_fen,
        },
        "returns": {
            "return_count": return_count,
            "return_amount_fen": return_amount_fen,
        },
        "gifts": {
            "gift_count": gift_count,
            "gift_amount_fen": gift_amount_fen,
        },
        "alerts": {
            "abnormal_order_count": abnormal_count,
            "margin_alert_count": margin_alert_count,
        },
        "hourly_breakdown": hourly_breakdown,
    }
