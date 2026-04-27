"""客户深度业务逻辑 (A1) — Golden ID合并、渠道归因、场景标签、价值分层、360全景

所有金额单位：分(fen)。
RFM分层: R(1-5) x F(1-5) x M(1-5) → 高价值(>=12)/成长(8-11)/沉睡(5-7)/流失(<5)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Customer, Order, OrderItem

logger = structlog.get_logger(__name__)

# ── RFM 分层阈值 ─────────────────────────────────────────────
RFM_HIGH_VALUE_MIN = 12  # R+F+M >= 12 → 高价值
RFM_GROWTH_MIN = 8  # 8-11 → 成长
RFM_DORMANT_MIN = 5  # 5-7 → 沉睡
# < 5 → 流失

RFM_LEVEL_MAP = {
    "high_value": "高价值",
    "growth": "成长",
    "dormant": "沉睡",
    "churn": "流失",
}


def _to_uuid(val: str) -> uuid.UUID:
    return uuid.UUID(val)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    """设置 RLS tenant 上下文"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _rfm_level(r: int, f: int, m: int) -> str:
    """根据 RFM 总分判断客户价值分层"""
    total = r + f + m
    if total >= RFM_HIGH_VALUE_MIN:
        return "high_value"
    elif total >= RFM_GROWTH_MIN:
        return "growth"
    elif total >= RFM_DORMANT_MIN:
        return "dormant"
    else:
        return "churn"


# ── 1. Golden ID 合并 ─────────────────────────────────────────


async def golden_id_merge(
    phone: str,
    wechat_openid: Optional[str],
    pos_id: Optional[str],
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """Golden ID 合并 — 多渠道身份归一

    同一手机号 + 不同渠道ID → 合并为一个 customer_id。
    规则:
      1. 以 primary_phone 为锚点查找所有匹配记录
      2. 如存在 wechat_openid 匹配但手机号不同的记录，也纳入合并
      3. 选择最早创建的记录作为主记录(golden record)
      4. 其余记录标记 is_merged=True, merged_into=主记录ID

    Returns:
        {golden_id, merged_count, sources, display_name}
    """
    await _set_tenant(db, tenant_id)
    tid = _to_uuid(tenant_id)

    # 1. 按手机号查找候选记录
    candidates_by_phone = await db.execute(
        select(Customer)
        .where(Customer.tenant_id == tid)
        .where(Customer.primary_phone == phone)
        .where(Customer.is_deleted == False)  # noqa: E712
        .order_by(Customer.created_at.asc())
    )
    phone_matches = list(candidates_by_phone.scalars().all())

    # 2. 按 wechat_openid 查找候选记录（如提供）
    openid_matches: list[Customer] = []
    if wechat_openid:
        candidates_by_openid = await db.execute(
            select(Customer)
            .where(Customer.tenant_id == tid)
            .where(Customer.wechat_openid == wechat_openid)
            .where(Customer.is_deleted == False)  # noqa: E712
            .where(Customer.is_merged == False)  # noqa: E712
        )
        openid_matches = list(candidates_by_openid.scalars().all())

    # 3. 合并候选集去重
    seen_ids: set[uuid.UUID] = set()
    all_candidates: list[Customer] = []
    for c in phone_matches + openid_matches:
        if c.id not in seen_ids:
            seen_ids.add(c.id)
            all_candidates.append(c)

    # 按创建时间排序，最早的作为主记录
    all_candidates.sort(key=lambda c: c.created_at or datetime.min.replace(tzinfo=timezone.utc))

    if not all_candidates:
        # 无匹配记录，创建新的 Golden ID 记录
        new_customer = Customer(
            id=uuid.uuid4(),
            tenant_id=tid,
            primary_phone=phone,
            wechat_openid=wechat_openid,
            source="pos" if pos_id else ("wechat" if wechat_openid else "manual"),
            is_merged=False,
            extra={"pos_id": pos_id} if pos_id else {},
        )
        db.add(new_customer)
        await db.flush()

        logger.info(
            "golden_id_created",
            golden_id=str(new_customer.id),
            phone=phone,
            tenant_id=tenant_id,
        )
        return {
            "golden_id": str(new_customer.id),
            "merged_count": 0,
            "sources": [new_customer.source],
            "display_name": None,
            "is_new": True,
        }

    # 4. 主记录(golden record) = 最早创建的那条
    golden = all_candidates[0]
    merged_count = 0
    sources: set[str] = {golden.source or "unknown"}

    # 5. 补充主记录字段
    if wechat_openid and not golden.wechat_openid:
        golden.wechat_openid = wechat_openid
    if pos_id:
        extra = golden.extra or {}
        extra["pos_id"] = pos_id
        golden.extra = extra

    # 6. 合并副记录
    for secondary in all_candidates[1:]:
        if secondary.is_merged:
            continue

        sources.add(secondary.source or "unknown")

        # 累加消费统计
        golden.total_order_count = (golden.total_order_count or 0) + (secondary.total_order_count or 0)
        golden.total_order_amount_fen = (golden.total_order_amount_fen or 0) + (secondary.total_order_amount_fen or 0)

        # 补充缺失字段
        if not golden.display_name and secondary.display_name:
            golden.display_name = secondary.display_name
        if not golden.wechat_openid and secondary.wechat_openid:
            golden.wechat_openid = secondary.wechat_openid
        if not golden.wechat_nickname and secondary.wechat_nickname:
            golden.wechat_nickname = secondary.wechat_nickname

        # 取最早的首单时间
        if secondary.first_order_at:
            if not golden.first_order_at or secondary.first_order_at < golden.first_order_at:
                golden.first_order_at = secondary.first_order_at

        # 取最近的末单时间
        if secondary.last_order_at:
            if not golden.last_order_at or secondary.last_order_at > golden.last_order_at:
                golden.last_order_at = secondary.last_order_at

        # 合并标签
        golden_tags = set(golden.tags or [])
        golden_tags.update(secondary.tags or [])
        golden.tags = list(golden_tags)

        # 标记副记录已合并
        secondary.is_merged = True
        secondary.merged_into = golden.id
        merged_count += 1

        # 将副记录关联的订单指向主记录
        await db.execute(
            update(Order)
            .where(Order.customer_id == secondary.id)
            .where(Order.tenant_id == tid)
            .values(customer_id=golden.id)
        )

    await db.flush()

    logger.info(
        "golden_id_merged",
        golden_id=str(golden.id),
        merged_count=merged_count,
        sources=list(sources),
        tenant_id=tenant_id,
    )

    return {
        "golden_id": str(golden.id),
        "merged_count": merged_count,
        "sources": list(sources),
        "display_name": golden.display_name,
        "is_new": False,
    }


# ── 2. 渠道来源归集 ──────────────────────────────────────────


async def channel_attribution(
    customer_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """渠道来源归集 — 首次/最近/最频繁渠道

    Returns:
        {first_channel, last_channel, top_channel, channel_distribution}
    """
    await _set_tenant(db, tenant_id)
    tid = _to_uuid(tenant_id)
    cid = _to_uuid(customer_id)

    # 查询客户所有订单的渠道分布
    channel_result = await db.execute(
        select(
            func.coalesce(Order.sales_channel_id, "unknown").label("channel"),
            func.count(Order.id).label("cnt"),
            func.min(Order.order_time).label("first_at"),
            func.max(Order.order_time).label("last_at"),
        )
        .where(Order.tenant_id == tid)
        .where(Order.customer_id == cid)
        .where(Order.is_deleted == False)  # noqa: E712
        .group_by("channel")
        .order_by(func.count(Order.id).desc())
    )
    rows = channel_result.all()

    if not rows:
        # 无订单，从 Customer.source 推断
        cust_result = await db.execute(
            select(Customer.source).where(Customer.id == cid).where(Customer.tenant_id == tid)
        )
        source = cust_result.scalar() or "unknown"
        logger.info(
            "channel_attribution_no_orders",
            customer_id=customer_id,
            source=source,
            tenant_id=tenant_id,
        )
        return {
            "customer_id": customer_id,
            "first_channel": source,
            "last_channel": source,
            "top_channel": source,
            "channel_distribution": {source: 0},
            "total_orders": 0,
        }

    total_orders = sum(row.cnt for row in rows)
    channel_distribution = {row.channel: row.cnt for row in rows}

    # 首次渠道 = first_at 最早的
    first_channel = min(rows, key=lambda r: r.first_at).channel
    # 最近渠道 = last_at 最晚的
    last_channel = max(rows, key=lambda r: r.last_at).channel
    # 最频繁渠道 = cnt 最大的 (已按 desc 排序)
    top_channel = rows[0].channel

    logger.info(
        "channel_attribution_computed",
        customer_id=customer_id,
        first_channel=first_channel,
        last_channel=last_channel,
        top_channel=top_channel,
        tenant_id=tenant_id,
    )

    return {
        "customer_id": customer_id,
        "first_channel": first_channel,
        "last_channel": last_channel,
        "top_channel": top_channel,
        "channel_distribution": channel_distribution,
        "total_orders": total_orders,
    }


# ── 3. 场景标签自动推导 ──────────────────────────────────────


async def tag_customer_scene(
    customer_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """场景标签自动推导 — 宴请/家庭/商务/独食

    推导规则:
      - 平均人数 >= 8 且客单价高 → 宴请
      - 平均人数 3-7 且有儿童菜 → 家庭
      - 工作日午餐 2-4 人 → 商务
      - 平均人数 <= 1 → 独食
      - 可叠加多个标签

    Returns:
        {scenes, primary_scene, evidence}
    """
    await _set_tenant(db, tenant_id)
    tid = _to_uuid(tenant_id)
    cid = _to_uuid(customer_id)

    # 查询近90天的订单数据
    now = datetime.now(timezone.utc)
    lookback = now.replace(day=1)  # 近3个月近似
    from datetime import timedelta

    lookback = now - timedelta(days=90)

    orders_result = await db.execute(
        select(
            Order.id,
            Order.guest_count,
            Order.total_amount_fen,
            Order.order_time,
            Order.order_type,
        )
        .where(Order.tenant_id == tid)
        .where(Order.customer_id == cid)
        .where(Order.is_deleted == False)  # noqa: E712
        .where(Order.order_time >= lookback)
    )
    orders = orders_result.all()

    if not orders:
        logger.info(
            "tag_customer_scene_no_orders",
            customer_id=customer_id,
            tenant_id=tenant_id,
        )
        return {
            "customer_id": customer_id,
            "scenes": [],
            "primary_scene": None,
            "evidence": {"order_count": 0},
        }

    # 统计指标
    guest_counts = [o.guest_count for o in orders if o.guest_count and o.guest_count > 0]
    avg_guest = sum(guest_counts) / len(guest_counts) if guest_counts else 1
    avg_spend_fen = sum(o.total_amount_fen for o in orders) / len(orders)
    per_capita_fen = avg_spend_fen / max(avg_guest, 1)

    # 分析用餐时段 (工作日午餐)
    weekday_lunch_count = 0
    for o in orders:
        if o.order_time:
            ot = o.order_time
            if hasattr(ot, "weekday"):
                # 0=Monday ... 4=Friday
                if ot.weekday() < 5 and 11 <= ot.hour <= 14:
                    weekday_lunch_count += 1

    # 查询是否点过儿童菜/套餐
    kid_dish_result = await db.execute(
        select(func.count(OrderItem.id))
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.tenant_id == tid)
        .where(Order.customer_id == cid)
        .where(Order.order_time >= lookback)
        .where(Order.is_deleted == False)  # noqa: E712
        .where(
            OrderItem.item_name.ilike("%儿童%")
            | OrderItem.item_name.ilike("%宝宝%")
            | OrderItem.item_name.ilike("%kids%")
        )
    )
    kid_dish_count = kid_dish_result.scalar() or 0

    # 推导场景标签
    scenes: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {
        "order_count": len(orders),
        "avg_guest_count": round(avg_guest, 1),
        "avg_spend_fen": round(avg_spend_fen),
        "per_capita_fen": round(per_capita_fen),
        "weekday_lunch_ratio": round(weekday_lunch_count / len(orders), 2) if orders else 0,
        "kid_dish_count": kid_dish_count,
    }

    # 宴请: 平均人数 >= 8 且人均消费较高
    if avg_guest >= 8 and per_capita_fen >= 10000:  # 人均 >= 100元
        scenes.append(
            {
                "scene": "banquet",
                "label": "宴请",
                "confidence": min(0.6 + (avg_guest - 8) * 0.05, 1.0),
            }
        )

    # 家庭: 3-7 人且有儿童菜
    if 3 <= avg_guest <= 7 and kid_dish_count > 0:
        scenes.append(
            {
                "scene": "family",
                "label": "家庭",
                "confidence": min(0.5 + kid_dish_count * 0.1, 1.0),
            }
        )
    elif 3 <= avg_guest <= 7:
        # 3-7 人但无儿童菜，低置信度家庭
        scenes.append(
            {
                "scene": "family",
                "label": "家庭",
                "confidence": 0.3,
            }
        )

    # 商务: 工作日午餐 2-4 人占比高
    weekday_lunch_ratio = weekday_lunch_count / len(orders) if orders else 0
    if 2 <= avg_guest <= 4 and weekday_lunch_ratio >= 0.4:
        scenes.append(
            {
                "scene": "business",
                "label": "商务",
                "confidence": min(0.4 + weekday_lunch_ratio * 0.5, 1.0),
            }
        )

    # 独食: 平均人数 <= 1
    if avg_guest <= 1.2:
        scenes.append(
            {
                "scene": "solo",
                "label": "独食",
                "confidence": 0.8 if avg_guest <= 1.0 else 0.5,
            }
        )

    # 按置信度排序
    scenes.sort(key=lambda s: s["confidence"], reverse=True)
    primary_scene = scenes[0]["scene"] if scenes else None

    # 更新客户标签
    if scenes:
        cust_result = await db.execute(select(Customer).where(Customer.id == cid).where(Customer.tenant_id == tid))
        customer = cust_result.scalar_one_or_none()
        if customer:
            existing_tags = set(customer.tags or [])
            scene_tags = {f"scene:{s['scene']}" for s in scenes if s["confidence"] >= 0.5}
            # 清除旧场景标签再添加新的
            existing_tags = {t for t in existing_tags if not t.startswith("scene:")}
            existing_tags.update(scene_tags)
            customer.tags = list(existing_tags)
            await db.flush()

    logger.info(
        "customer_scene_tagged",
        customer_id=customer_id,
        scenes=[s["scene"] for s in scenes],
        primary_scene=primary_scene,
        tenant_id=tenant_id,
    )

    return {
        "customer_id": customer_id,
        "scenes": scenes,
        "primary_scene": primary_scene,
        "evidence": evidence,
    }


# ── 4. 客户价值分层 ──────────────────────────────────────────


async def calculate_customer_value(
    customer_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """客户价值分层 — RFM → 高价值/成长/沉睡/流失

    RFM 总分 = R + F + M (各1-5):
      >= 12 → 高价值
      8-11  → 成长
      5-7   → 沉睡
      < 5   → 流失

    同时重新计算 R/F/M 各维度分数并更新到 Customer 表。

    Returns:
        {level, r_score, f_score, m_score, total_score, label, suggestions}
    """
    await _set_tenant(db, tenant_id)
    tid = _to_uuid(tenant_id)
    cid = _to_uuid(customer_id)

    cust_result = await db.execute(
        select(Customer).where(Customer.id == cid).where(Customer.tenant_id == tid).where(Customer.is_deleted == False)  # noqa: E712
    )
    customer = cust_result.scalar_one_or_none()
    if not customer:
        return {"error": "customer_not_found", "customer_id": customer_id}

    now = datetime.now(timezone.utc)

    # ── 计算 R 分 (Recency) ──
    last_order = customer.last_order_at
    if last_order:
        if last_order.tzinfo is None:
            last_order = last_order.replace(tzinfo=timezone.utc)
        recency_days = (now - last_order).days
    else:
        recency_days = 999

    if recency_days <= 7:
        r_score = 5
    elif recency_days <= 14:
        r_score = 4
    elif recency_days <= 30:
        r_score = 3
    elif recency_days <= 60:
        r_score = 2
    else:
        r_score = 1

    # ── 计算 F 分 (Frequency) ──
    order_count = customer.total_order_count or 0
    if order_count >= 20:
        f_score = 5
    elif order_count >= 10:
        f_score = 4
    elif order_count >= 5:
        f_score = 3
    elif order_count >= 2:
        f_score = 2
    else:
        f_score = 1

    # ── 计算 M 分 (Monetary) ──
    total_fen = customer.total_order_amount_fen or 0
    if total_fen >= 500000:  # >= 5000 元
        m_score = 5
    elif total_fen >= 200000:  # >= 2000 元
        m_score = 4
    elif total_fen >= 80000:  # >= 800 元
        m_score = 3
    elif total_fen >= 30000:  # >= 300 元
        m_score = 2
    else:
        m_score = 1

    # ── 分层 ──
    total_score = r_score + f_score + m_score
    level = _rfm_level(r_score, f_score, m_score)
    label = RFM_LEVEL_MAP[level]

    # ── 运营建议 ──
    suggestions: list[str] = []
    if level == "high_value":
        suggestions = ["专属VIP服务", "生日/纪念日关怀", "新品优先体验"]
    elif level == "growth":
        suggestions = ["提升消费频次", "推荐高毛利菜品", "充值优惠引导"]
    elif level == "dormant":
        suggestions = ["唤醒优惠券推送", "专属回归礼", "电话关怀"]
    else:  # churn
        suggestions = ["大额唤回券", "流失原因调研", "短信+微信双触达"]

    # ── 更新 Customer 表 ──
    customer.r_score = r_score
    customer.f_score = f_score
    customer.m_score = m_score
    customer.rfm_level = f"S{6 - max(r_score, f_score, m_score)}" if level != "churn" else "S5"
    customer.rfm_recency_days = recency_days
    customer.rfm_frequency = order_count
    customer.rfm_monetary_fen = total_fen
    customer.rfm_updated_at = now
    await db.flush()

    logger.info(
        "customer_value_calculated",
        customer_id=customer_id,
        level=level,
        total_score=total_score,
        r=r_score,
        f=f_score,
        m=m_score,
        tenant_id=tenant_id,
    )

    return {
        "customer_id": customer_id,
        "level": level,
        "label": label,
        "r_score": r_score,
        "f_score": f_score,
        "m_score": m_score,
        "total_score": total_score,
        "recency_days": recency_days,
        "order_count": order_count,
        "total_amount_fen": total_fen,
        "suggestions": suggestions,
    }


# ── 5. 客户360全景 ───────────────────────────────────────────


async def get_customer_360(
    customer_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """客户360全景 — 合并所有维度

    聚合: 基础信息 + 价值分层 + 渠道归因 + 场景标签 + 消费偏好

    Returns:
        {profile, value, channel, scenes, preferences, timeline}
    """
    await _set_tenant(db, tenant_id)
    tid = _to_uuid(tenant_id)
    cid = _to_uuid(customer_id)

    # 基础信息
    cust_result = await db.execute(
        select(Customer).where(Customer.id == cid).where(Customer.tenant_id == tid).where(Customer.is_deleted == False)  # noqa: E712
    )
    customer = cust_result.scalar_one_or_none()
    if not customer:
        return {"error": "customer_not_found", "customer_id": customer_id}

    # 并行获取各维度数据
    value_data = await calculate_customer_value(customer_id, tenant_id, db)
    channel_data = await channel_attribution(customer_id, tenant_id, db)
    scene_data = await tag_customer_scene(customer_id, tenant_id, db)

    # 最爱菜品 TOP 5
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
        .limit(5)
    )
    favorite_dishes = [{"name": row[0], "total_qty": int(row[1]), "order_times": row[2]} for row in dish_result.all()]

    # 最近5笔订单时间线
    recent_orders_result = await db.execute(
        select(
            Order.id,
            Order.order_no,
            Order.order_time,
            Order.total_amount_fen,
            Order.final_amount_fen,
            Order.guest_count,
            Order.store_id,
        )
        .where(Order.tenant_id == tid)
        .where(Order.customer_id == cid)
        .where(Order.is_deleted == False)  # noqa: E712
        .order_by(Order.order_time.desc())
        .limit(5)
    )
    timeline = [
        {
            "order_id": str(row.id),
            "order_no": row.order_no,
            "order_time": row.order_time.isoformat() if row.order_time else None,
            "total_amount_fen": row.total_amount_fen,
            "final_amount_fen": row.final_amount_fen,
            "guest_count": row.guest_count,
            "store_id": str(row.store_id),
        }
        for row in recent_orders_result.all()
    ]

    # 组装 360 全景
    profile = {
        "customer_id": str(customer.id),
        "display_name": customer.display_name,
        "primary_phone": customer.primary_phone,
        "gender": customer.gender,
        "birth_date": str(customer.birth_date) if customer.birth_date else None,
        "wechat_nickname": customer.wechat_nickname,
        "source": customer.source,
        "tags": customer.tags or [],
        "dietary_restrictions": customer.dietary_restrictions or [],
        "first_order_at": customer.first_order_at.isoformat() if customer.first_order_at else None,
        "last_order_at": customer.last_order_at.isoformat() if customer.last_order_at else None,
        "total_order_count": customer.total_order_count,
        "total_order_amount_fen": customer.total_order_amount_fen,
        "is_merged": customer.is_merged,
    }

    logger.info(
        "customer_360_generated",
        customer_id=customer_id,
        level=value_data.get("level"),
        scenes_count=len(scene_data.get("scenes", [])),
        tenant_id=tenant_id,
    )

    return {
        "profile": profile,
        "value": value_data,
        "channel": channel_data,
        "scenes": scene_data,
        "preferences": {
            "favorite_dishes": favorite_dishes,
        },
        "timeline": timeline,
    }
