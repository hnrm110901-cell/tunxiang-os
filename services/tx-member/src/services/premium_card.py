"""超级年卡 — 付费会员体系（银卡/金卡/钻石）

徐记海鲜高端会员年卡：权益包含折扣/免费菜/优先预订/专属客服。
所有金额单位：分(fen)。
年卡价格：银卡 69800 / 金卡 129800 / 钻石 299800（分）。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


# ── 年卡方案常量 ──────────────────────────────────────────────

ANNUAL_PLANS = {
    "silver": {
        "name": "银卡",
        "price_fen": 69800,
        "duration_days": 365,
        "benefits": [
            {"key": "dining_discount", "name": "堂食折扣", "value": 95, "unit": "percent"},
            {"key": "retail_discount", "name": "甄选商城折扣", "value": 95, "unit": "percent"},
            {"key": "free_dish_monthly", "name": "每月免费菜", "value": 1, "unit": "count"},
            {"key": "birthday_gift", "name": "生日专属礼遇", "value": 1, "unit": "count"},
            {"key": "priority_booking", "name": "优先预订", "value": 0, "unit": "flag"},
        ],
    },
    "gold": {
        "name": "金卡",
        "price_fen": 129800,
        "duration_days": 365,
        "benefits": [
            {"key": "dining_discount", "name": "堂食折扣", "value": 90, "unit": "percent"},
            {"key": "retail_discount", "name": "甄选商城折扣", "value": 90, "unit": "percent"},
            {"key": "free_dish_monthly", "name": "每月免费菜", "value": 2, "unit": "count"},
            {"key": "birthday_gift", "name": "生日专属礼遇", "value": 1, "unit": "count"},
            {"key": "priority_booking", "name": "优先预订", "value": 1, "unit": "flag"},
            {"key": "dedicated_service", "name": "专属客服", "value": 0, "unit": "flag"},
            {"key": "free_parking", "name": "免费停车", "value": 2, "unit": "hours"},
        ],
    },
    "diamond": {
        "name": "钻石卡",
        "price_fen": 299800,
        "duration_days": 365,
        "benefits": [
            {"key": "dining_discount", "name": "堂食折扣", "value": 85, "unit": "percent"},
            {"key": "retail_discount", "name": "甄选商城折扣", "value": 85, "unit": "percent"},
            {"key": "free_dish_monthly", "name": "每月免费菜", "value": 4, "unit": "count"},
            {"key": "birthday_gift", "name": "生日专属礼遇", "value": 1, "unit": "count"},
            {"key": "priority_booking", "name": "优先预订", "value": 1, "unit": "flag"},
            {"key": "dedicated_service", "name": "专属客服(1对1)", "value": 1, "unit": "flag"},
            {"key": "free_parking", "name": "免费停车", "value": 4, "unit": "hours"},
            {"key": "private_room_priority", "name": "包厢优先", "value": 1, "unit": "flag"},
            {"key": "annual_banquet", "name": "年度答谢宴", "value": 1, "unit": "count"},
        ],
    },
}


# ── 工具函数 ──────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    """设置 RLS tenant 上下文"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ── 服务函数 ──────────────────────────────────────────────────


async def list_annual_plans(
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """年卡方案列表 — 银卡/金卡/钻石，展示不同权益

    Returns:
        {"plans": [{"plan_id", "name", "price_fen", "benefits", ...}]}
    """
    await _set_tenant(db, tenant_id)

    # 查询租户自定义方案（若有），否则使用默认
    row = await db.execute(
        text("""
            SELECT plans_config::text FROM premium_card_config
            WHERE tenant_id = :tid AND is_deleted = false
        """),
        {"tid": tenant_id},
    )
    custom = row.mappings().first()

    if custom and custom.get("plans_config"):
        plans = json.loads(custom["plans_config"])
    else:
        plans = [
            {"plan_id": k, **v}
            for k, v in ANNUAL_PLANS.items()
        ]

    logger.info(
        "annual_plans_listed",
        tenant_id=tenant_id,
        plans_count=len(plans),
    )

    return {"plans": plans}


async def purchase_annual_card(
    customer_id: str,
    plan_id: str,
    payment_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """购买年卡

    Args:
        customer_id: 客户 ID
        plan_id: 方案 ID (silver/gold/diamond)
        payment_id: 支付单 ID
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        {"card_id", "plan_id", "plan_name", "price_fen", "start_date", "end_date", "benefits"}
    """
    await _set_tenant(db, tenant_id)

    plan = ANNUAL_PLANS.get(plan_id)
    if not plan:
        raise ValueError(f"invalid_plan_id:{plan_id}, valid: {list(ANNUAL_PLANS.keys())}")

    # 检查是否已有有效年卡
    existing = await db.execute(
        text("""
            SELECT id, plan_id, end_date FROM premium_cards
            WHERE customer_id = :cid AND tenant_id = :tid
              AND status = 'active' AND end_date > :now AND is_deleted = false
            ORDER BY end_date DESC LIMIT 1
        """),
        {"cid": customer_id, "tid": tenant_id, "now": _now_utc()},
    )
    existing_card = existing.mappings().first()
    if existing_card:
        raise ValueError(f"active_card_exists:{existing_card['id']}")

    card_id = str(uuid.uuid4())
    now = _now_utc()
    end_date = now + timedelta(days=plan["duration_days"])

    await db.execute(
        text("""
            INSERT INTO premium_cards
                (id, tenant_id, customer_id, plan_id, payment_id,
                 price_fen, status, benefits,
                 start_date, end_date, created_at, updated_at, is_deleted)
            VALUES (:id, :tid, :cid, :pid, :pay,
                    :price, 'active', :benefits::jsonb,
                    :start, :end, :now, :now, false)
        """),
        {
            "id": card_id,
            "tid": tenant_id,
            "cid": customer_id,
            "pid": plan_id,
            "pay": payment_id,
            "price": plan["price_fen"],
            "benefits": json.dumps(plan["benefits"], ensure_ascii=False),
            "start": now,
            "end": end_date,
            "now": now,
        },
    )
    await db.flush()

    logger.info(
        "premium_card_purchased",
        tenant_id=tenant_id,
        card_id=card_id,
        customer_id=customer_id,
        plan_id=plan_id,
        price_fen=plan["price_fen"],
    )

    return {
        "card_id": card_id,
        "customer_id": customer_id,
        "plan_id": plan_id,
        "plan_name": plan["name"],
        "price_fen": plan["price_fen"],
        "start_date": now.isoformat(),
        "end_date": end_date.isoformat(),
        "benefits": plan["benefits"],
        "status": "active",
    }


async def get_card_benefits(
    card_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """权益清单 — 折扣/免费菜/优先预订/专属客服

    Returns:
        {"card_id", "plan_name", "benefits", "status", "days_remaining"}
    """
    await _set_tenant(db, tenant_id)

    row = await db.execute(
        text("""
            SELECT id, plan_id, benefits::text, status, start_date, end_date
            FROM premium_cards
            WHERE id = :cid AND tenant_id = :tid AND is_deleted = false
        """),
        {"cid": card_id, "tid": tenant_id},
    )
    card = row.mappings().first()
    if not card:
        raise ValueError("card_not_found")

    benefits = json.loads(card["benefits"]) if card["benefits"] else []
    plan = ANNUAL_PLANS.get(card["plan_id"], {})
    now = _now_utc()
    days_remaining = max(0, (card["end_date"] - now).days) if card["end_date"] else 0

    logger.info(
        "premium_card_benefits_retrieved",
        tenant_id=tenant_id,
        card_id=card_id,
        plan_id=card["plan_id"],
        benefits_count=len(benefits),
    )

    return {
        "card_id": card_id,
        "plan_id": card["plan_id"],
        "plan_name": plan.get("name", card["plan_id"]),
        "benefits": benefits,
        "status": card["status"],
        "start_date": card["start_date"].isoformat() if card["start_date"] else None,
        "end_date": card["end_date"].isoformat() if card["end_date"] else None,
        "days_remaining": days_remaining,
    }


async def check_benefit_usage(
    card_id: str,
    benefit_type: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """权益使用情况 — 查询某项权益的已用/剩余次数

    Args:
        card_id: 年卡 ID
        benefit_type: 权益类型 key (如 free_dish_monthly)
        tenant_id: 租户 ID

    Returns:
        {"card_id", "benefit_type", "total_quota", "used", "remaining", "period"}
    """
    await _set_tenant(db, tenant_id)

    # 获取年卡信息
    card_row = await db.execute(
        text("""
            SELECT plan_id, benefits::text, start_date FROM premium_cards
            WHERE id = :cid AND tenant_id = :tid AND status = 'active' AND is_deleted = false
        """),
        {"cid": card_id, "tid": tenant_id},
    )
    card = card_row.mappings().first()
    if not card:
        raise ValueError("card_not_found_or_inactive")

    benefits = json.loads(card["benefits"]) if card["benefits"] else []
    target_benefit = None
    for b in benefits:
        if b.get("key") == benefit_type:
            target_benefit = b
            break
    if not target_benefit:
        raise ValueError(f"benefit_type_not_found:{benefit_type}")

    total_quota = target_benefit.get("value", 0)

    # 查询当月已使用次数
    now = _now_utc()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    usage_row = await db.execute(
        text("""
            SELECT COUNT(*) FROM premium_benefit_usage
            WHERE card_id = :cid AND tenant_id = :tid
              AND benefit_type = :btype AND used_at >= :month_start
        """),
        {"cid": card_id, "tid": tenant_id, "btype": benefit_type, "month_start": month_start},
    )
    used = usage_row.scalar() or 0
    remaining = max(0, total_quota - used)

    logger.info(
        "premium_benefit_usage_checked",
        tenant_id=tenant_id,
        card_id=card_id,
        benefit_type=benefit_type,
        total_quota=total_quota,
        used=used,
        remaining=remaining,
    )

    return {
        "card_id": card_id,
        "benefit_type": benefit_type,
        "benefit_name": target_benefit.get("name", benefit_type),
        "total_quota": total_quota,
        "used": used,
        "remaining": remaining,
        "period": "monthly",
        "period_start": month_start.isoformat(),
    }


async def renew_card(
    card_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """续费年卡 — 在到期日基础上延长一年

    Returns:
        {"card_id", "old_end_date", "new_end_date", "renewed": bool}
    """
    await _set_tenant(db, tenant_id)

    row = await db.execute(
        text("""
            SELECT id, plan_id, end_date, status FROM premium_cards
            WHERE id = :cid AND tenant_id = :tid AND is_deleted = false
        """),
        {"cid": card_id, "tid": tenant_id},
    )
    card = row.mappings().first()
    if not card:
        raise ValueError("card_not_found")

    plan = ANNUAL_PLANS.get(card["plan_id"])
    if not plan:
        raise ValueError(f"plan_config_missing:{card['plan_id']}")

    now = _now_utc()
    old_end = card["end_date"]
    # 若已过期从今天开始，若未过期从到期日开始
    base_date = old_end if old_end and old_end > now else now
    new_end = base_date + timedelta(days=plan["duration_days"])

    await db.execute(
        text("""
            UPDATE premium_cards
            SET end_date = :new_end, status = 'active', updated_at = :now
            WHERE id = :cid AND tenant_id = :tid
        """),
        {"new_end": new_end, "cid": card_id, "tid": tenant_id, "now": now},
    )
    await db.flush()

    logger.info(
        "premium_card_renewed",
        tenant_id=tenant_id,
        card_id=card_id,
        old_end_date=old_end.isoformat() if old_end else None,
        new_end_date=new_end.isoformat(),
    )

    return {
        "card_id": card_id,
        "old_end_date": old_end.isoformat() if old_end else None,
        "new_end_date": new_end.isoformat(),
        "renewed": True,
    }


async def gift_card(
    sender_id: str,
    receiver_phone: str,
    plan_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """赠送年卡 — 购买并赠送给指定手机号用户

    Args:
        sender_id: 赠送人客户 ID
        receiver_phone: 接收人手机号
        plan_id: 方案 ID
        tenant_id: 租户 ID

    Returns:
        {"gift_id", "sender_id", "receiver_phone", "plan_id", "status", "redeem_code"}
    """
    await _set_tenant(db, tenant_id)

    plan = ANNUAL_PLANS.get(plan_id)
    if not plan:
        raise ValueError(f"invalid_plan_id:{plan_id}")

    if not receiver_phone or len(receiver_phone) != 11:
        raise ValueError("invalid_phone_number")

    gift_id = str(uuid.uuid4())
    redeem_code = uuid.uuid4().hex[:8].upper()
    now = _now_utc()

    await db.execute(
        text("""
            INSERT INTO premium_card_gifts
                (id, tenant_id, sender_id, receiver_phone, plan_id,
                 price_fen, redeem_code, status, created_at, updated_at, is_deleted)
            VALUES (:id, :tid, :sid, :phone, :pid,
                    :price, :code, 'pending', :now, :now, false)
        """),
        {
            "id": gift_id,
            "tid": tenant_id,
            "sid": sender_id,
            "phone": receiver_phone,
            "pid": plan_id,
            "price": plan["price_fen"],
            "code": redeem_code,
            "now": now,
        },
    )
    await db.flush()

    logger.info(
        "premium_card_gifted",
        tenant_id=tenant_id,
        gift_id=gift_id,
        sender_id=sender_id,
        receiver_phone=receiver_phone[-4:],  # 脱敏
        plan_id=plan_id,
    )

    return {
        "gift_id": gift_id,
        "sender_id": sender_id,
        "receiver_phone": receiver_phone,
        "plan_id": plan_id,
        "plan_name": plan["name"],
        "price_fen": plan["price_fen"],
        "redeem_code": redeem_code,
        "status": "pending",
        "created_at": now.isoformat(),
    }
