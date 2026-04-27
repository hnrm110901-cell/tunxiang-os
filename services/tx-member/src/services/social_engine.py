"""社交裂变引擎 -- 拼单/请客/分享有礼/推荐追踪/社交统计

多租户 RLS 隔离，structlog 日志。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


# ── 工具函数 ──────────────────────────────────────────────────


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ── 1. 创建拼单 ─────────────────────────────────────────────


async def create_group_order(
    initiator_id: str,
    store_id: str,
    table_id: Optional[str],
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """创建拼单 -- 多人各点各的

    Returns:
        {"group_id", "invite_code", "initiator_id", "store_id", "status", "expires_at"}
    """
    await _set_tenant(db, tenant_id)

    group_id = str(uuid.uuid4())
    invite_code = uuid.uuid4().hex[:8].upper()
    now = _now_utc()
    expires_at = now + timedelta(hours=2)

    await db.execute(
        text("""
            INSERT INTO group_orders
                (id, tenant_id, initiator_id, store_id, table_id,
                 invite_code, status, member_count, created_at, expires_at)
            VALUES (:gid, :tid, :iid, :sid, :tbl,
                    :code, 'open', 1, :now, :exp)
        """),
        {
            "gid": group_id,
            "tid": tenant_id,
            "iid": initiator_id,
            "sid": store_id,
            "tbl": table_id,
            "code": invite_code,
            "now": now,
            "exp": expires_at,
        },
    )

    # 发起人自动作为第一个成员
    member_id = str(uuid.uuid4())
    await db.execute(
        text("""
            INSERT INTO group_order_members
                (id, tenant_id, group_id, customer_id, role, joined_at)
            VALUES (:mid, :tid, :gid, :cid, 'creator', :now)
        """),
        {"mid": member_id, "tid": tenant_id, "gid": group_id, "cid": initiator_id, "now": now},
    )
    await db.flush()

    logger.info(
        "social.group_order.create",
        tenant_id=tenant_id,
        group_id=group_id,
        initiator_id=initiator_id,
        store_id=store_id,
    )

    return {
        "group_id": group_id,
        "invite_code": invite_code,
        "initiator_id": initiator_id,
        "store_id": store_id,
        "table_id": table_id,
        "status": "open",
        "member_count": 1,
        "expires_at": expires_at.isoformat(),
    }


# ── 2. 加入拼单 ─────────────────────────────────────────────


async def join_group_order(
    group_id: str,
    customer_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """加入拼单

    Returns:
        {"joined", "group_id", "customer_id", "member_count"}
    """
    await _set_tenant(db, tenant_id)

    # 校验拼单状态
    row = await db.execute(
        text("""
            SELECT status, expires_at, member_count
            FROM group_orders
            WHERE id = :gid AND tenant_id = :tid
        """),
        {"gid": group_id, "tid": tenant_id},
    )
    group = row.mappings().first()
    if not group:
        raise ValueError("group_order_not_found")
    if group["status"] != "open":
        raise ValueError("group_order_not_open")
    if group["expires_at"] and group["expires_at"] < _now_utc():
        raise ValueError("group_order_expired")

    # 检查是否已加入
    exist_row = await db.execute(
        text("""
            SELECT id FROM group_order_members
            WHERE group_id = :gid AND customer_id = :cid AND tenant_id = :tid
        """),
        {"gid": group_id, "cid": customer_id, "tid": tenant_id},
    )
    if exist_row.scalar():
        raise ValueError("already_in_group")

    now = _now_utc()
    member_id = str(uuid.uuid4())
    await db.execute(
        text("""
            INSERT INTO group_order_members
                (id, tenant_id, group_id, customer_id, role, joined_at)
            VALUES (:mid, :tid, :gid, :cid, 'member', :now)
        """),
        {"mid": member_id, "tid": tenant_id, "gid": group_id, "cid": customer_id, "now": now},
    )

    new_count = group["member_count"] + 1
    await db.execute(
        text("""
            UPDATE group_orders SET member_count = :cnt, updated_at = :now
            WHERE id = :gid AND tenant_id = :tid
        """),
        {"cnt": new_count, "gid": group_id, "tid": tenant_id, "now": now},
    )
    await db.flush()

    logger.info(
        "social.group_order.join",
        tenant_id=tenant_id,
        group_id=group_id,
        customer_id=customer_id,
        member_count=new_count,
    )

    return {
        "joined": True,
        "group_id": group_id,
        "customer_id": customer_id,
        "member_count": new_count,
    }


# ── 3. 请客/送菜品/送礼品卡 ──────────────────────────────────


async def send_gift(
    sender_id: str,
    receiver_phone: str,
    gift_type: str,
    gift_config: dict[str, Any],
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """请客/送菜品/送礼品卡

    Args:
        gift_type: "dish" | "card" | "coupon"
        gift_config: {"amount_fen", "dish_ids", "coupon_id", "message"}

    Returns:
        {"gift_id", "share_code", "share_url", "gift_type", "status", "expires_at"}
    """
    await _set_tenant(db, tenant_id)

    if gift_type not in ("dish", "card", "coupon"):
        raise ValueError("invalid_gift_type")

    gift_id = str(uuid.uuid4())
    share_code = uuid.uuid4().hex[:10].upper()
    now = _now_utc()
    expires_at = now + timedelta(days=7)

    import json

    await db.execute(
        text("""
            INSERT INTO gifts
                (id, tenant_id, sender_id, receiver_phone, gift_type,
                 gift_config, share_code, status, created_at, expires_at)
            VALUES (:gid, :tid, :sid, :phone, :gtype,
                    :cfg::jsonb, :code, 'pending', :now, :exp)
        """),
        {
            "gid": gift_id,
            "tid": tenant_id,
            "sid": sender_id,
            "phone": receiver_phone,
            "gtype": gift_type,
            "cfg": json.dumps(gift_config, ensure_ascii=False),
            "code": share_code,
            "now": now,
            "exp": expires_at,
        },
    )
    await db.flush()

    logger.info(
        "social.gift.send",
        tenant_id=tenant_id,
        gift_id=gift_id,
        sender_id=sender_id,
        gift_type=gift_type,
    )

    return {
        "gift_id": gift_id,
        "share_code": share_code,
        "share_url": f"https://mp.tunxiangos.com/gift/{share_code}",
        "gift_type": gift_type,
        "receiver_phone": receiver_phone,
        "status": "pending",
        "expires_at": expires_at.isoformat(),
    }


# ── 4. 分享有礼链接 ─────────────────────────────────────────


async def create_share_link(
    customer_id: str,
    campaign_type: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """分享有礼链接

    Args:
        campaign_type: "new_user" | "reactivation" | "group_buy"

    Returns:
        {"link_id", "share_url", "referral_code", "campaign_type", "reward_description"}
    """
    await _set_tenant(db, tenant_id)

    if campaign_type not in ("new_user", "reactivation", "group_buy"):
        raise ValueError("invalid_campaign_type")

    link_id = str(uuid.uuid4())
    referral_code = uuid.uuid4().hex[:8].upper()
    now = _now_utc()
    expires_at = now + timedelta(days=30)

    await db.execute(
        text("""
            INSERT INTO share_links
                (id, tenant_id, customer_id, campaign_type,
                 referral_code, click_count, convert_count, created_at, expires_at)
            VALUES (:lid, :tid, :cid, :ctype,
                    :code, 0, 0, :now, :exp)
        """),
        {
            "lid": link_id,
            "tid": tenant_id,
            "cid": customer_id,
            "ctype": campaign_type,
            "code": referral_code,
            "now": now,
            "exp": expires_at,
        },
    )
    await db.flush()

    reward_map = {
        "new_user": "好友注册后双方各获10积分",
        "reactivation": "好友回归消费后你获20积分",
        "group_buy": "拼团成功享8折优惠",
    }

    logger.info(
        "social.share_link.create",
        tenant_id=tenant_id,
        link_id=link_id,
        customer_id=customer_id,
        campaign_type=campaign_type,
    )

    return {
        "link_id": link_id,
        "share_url": f"https://mp.tunxiangos.com/invite/{referral_code}",
        "referral_code": referral_code,
        "campaign_type": campaign_type,
        "reward_description": reward_map.get(campaign_type, ""),
        "expires_at": expires_at.isoformat(),
    }


# ── 5. 追踪推荐关系 + 发放奖励 ──────────────────────────────


async def track_referral(
    referrer_id: str,
    new_customer_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """追踪推荐关系 + 发放奖励

    Returns:
        {"referral_id", "referrer_id", "new_customer_id", "referrer_reward", "referee_reward"}
    """
    await _set_tenant(db, tenant_id)

    now = _now_utc()
    referral_id = str(uuid.uuid4())

    # 查是否已存在推荐关系
    exist_row = await db.execute(
        text("""
            SELECT id FROM referrals
            WHERE referrer_id = :rid AND new_customer_id = :nid AND tenant_id = :tid
        """),
        {"rid": referrer_id, "nid": new_customer_id, "tid": tenant_id},
    )
    if exist_row.scalar():
        raise ValueError("referral_already_exists")

    # 记录推荐关系
    await db.execute(
        text("""
            INSERT INTO referrals
                (id, tenant_id, referrer_id, new_customer_id,
                 referrer_reward_points, referee_reward_points, created_at)
            VALUES (:rid, :tid, :refid, :nid, 10, 10, :now)
        """),
        {
            "rid": referral_id,
            "tid": tenant_id,
            "refid": referrer_id,
            "nid": new_customer_id,
            "now": now,
        },
    )

    # 发放积分给推荐人
    await db.execute(
        text("""
            UPDATE member_cards SET points = points + 10, updated_at = :now
            WHERE customer_id = :cid AND tenant_id = :tid AND is_deleted = false
        """),
        {"cid": referrer_id, "tid": tenant_id, "now": now},
    )

    # 发放积分给被推荐人
    await db.execute(
        text("""
            UPDATE member_cards SET points = points + 10, updated_at = :now
            WHERE customer_id = :cid AND tenant_id = :tid AND is_deleted = false
        """),
        {"cid": new_customer_id, "tid": tenant_id, "now": now},
    )
    await db.flush()

    logger.info(
        "social.referral.track",
        tenant_id=tenant_id,
        referral_id=referral_id,
        referrer_id=referrer_id,
        new_customer_id=new_customer_id,
    )

    return {
        "referral_id": referral_id,
        "referrer_id": referrer_id,
        "new_customer_id": new_customer_id,
        "referrer_reward_points": 10,
        "referee_reward_points": 10,
    }


# ── 6. 社交统计 ─────────────────────────────────────────────


async def get_social_stats(
    customer_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """社交统计 -- 推荐人数 / 获得奖励 / 拼单次数

    Returns:
        {"customer_id", "referral_count", "total_reward_points",
         "group_order_count", "gift_sent_count"}
    """
    await _set_tenant(db, tenant_id)

    # 推荐人数
    ref_row = await db.execute(
        text("""
            SELECT COUNT(*) as cnt, COALESCE(SUM(referrer_reward_points), 0) as reward
            FROM referrals
            WHERE referrer_id = :cid AND tenant_id = :tid
        """),
        {"cid": customer_id, "tid": tenant_id},
    )
    ref_data = ref_row.mappings().first()
    referral_count = ref_data["cnt"] if ref_data else 0
    total_reward = ref_data["reward"] if ref_data else 0

    # 拼单次数
    group_row = await db.execute(
        text("""
            SELECT COUNT(*) as cnt
            FROM group_order_members
            WHERE customer_id = :cid AND tenant_id = :tid
        """),
        {"cid": customer_id, "tid": tenant_id},
    )
    group_count = group_row.scalar() or 0

    # 送礼次数
    gift_row = await db.execute(
        text("""
            SELECT COUNT(*) as cnt
            FROM gifts
            WHERE sender_id = :cid AND tenant_id = :tid
        """),
        {"cid": customer_id, "tid": tenant_id},
    )
    gift_count = gift_row.scalar() or 0

    logger.info(
        "social.stats",
        tenant_id=tenant_id,
        customer_id=customer_id,
        referrals=referral_count,
        groups=group_count,
        gifts=gift_count,
    )

    return {
        "customer_id": customer_id,
        "referral_count": referral_count,
        "total_reward_points": int(total_reward),
        "group_order_count": group_count,
        "gift_sent_count": gift_count,
    }
