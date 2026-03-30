"""会员等级智能调度引擎

根据会员等级(钻石/金卡/银卡/普通)和用户场景(到店/外卖/预订/排队)
动态调整业务行为，实现个性化服务体验。

等级权益矩阵:
  钻石(diamond): 优先包厢+专属菜单+免排队+专属客服+生日宴免服务费  年消费≥50000元
  金卡(gold):    优先排队+生日特权+会员价+免费停车                年消费≥20000元
  银卡(silver):  会员价+积分加速+生日券                         年消费≥5000元
  普通(normal):  标准服务+积分累计
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = structlog.get_logger(__name__)

# ── 常量 ──────────────────────────────────────────────────────

LEVEL_RANK = {"diamond": 4, "gold": 3, "silver": 2, "normal": 1}
LEVEL_NAMES_CN = {"diamond": "钻石会员", "gold": "金卡会员", "silver": "银卡会员", "normal": "普通会员"}

# 年消费升级阈值（单位：分 fen）
UPGRADE_THRESHOLDS_FEN = {
    "diamond": 5_000_000,   # 50000元
    "gold": 2_000_000,      # 20000元
    "silver": 500_000,      # 5000元
    "normal": 0,
}

# 排队优先权重（越大越靠前）
QUEUE_PRIORITY = {"diamond": 1000, "gold": 300, "silver": 0, "normal": 0}

# 积分加速倍率
POINTS_MULTIPLIER = {"diamond": 3.0, "gold": 2.0, "silver": 1.5, "normal": 1.0}

# 通知渠道
NOTIFICATION_CHANNELS = {
    "diamond": ["dedicated_service", "wechat", "sms"],
    "gold": ["wechat_service", "sms"],
    "silver": ["wechat_service"],
    "normal": ["wechat_service"],
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


def _rank_to_level(rank: int) -> str:
    """将数字 rank 映射为等级名称"""
    for level, r in LEVEL_RANK.items():
        if r == rank:
            return level
    return "normal"


# ── 核心: 获取会员等级 ────────────────────────────────────────

async def get_member_level(customer_id: str, tenant_id: str, db: AsyncSession) -> str:
    """获取会员等级: diamond/gold/silver/normal

    从 member_cards 表查询最高等级的活跃卡。
    """
    await _set_tenant(db, tenant_id)

    result = await db.execute(
        text("""
            SELECT COALESCE(MAX(level_rank), 0) AS max_rank
            FROM member_cards
            WHERE customer_id = :cid AND tenant_id = :tid
              AND status = 'active' AND is_deleted = false
        """),
        {"cid": customer_id, "tid": tenant_id},
    )
    row = result.mappings().first()
    max_rank = row["max_rank"] if row else 0

    level = _rank_to_level(max_rank)
    logger.info(
        "member_level_resolved",
        tenant_id=tenant_id,
        customer_id=customer_id,
        level=level,
        rank=max_rank,
    )
    return level


# ── 1. 预订调度 ──────────────────────────────────────────────

async def dispatch_reservation(
    customer_id: str,
    request: dict,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """预订调度: 高等级会员优先分配包厢

    - 钻石: 可预订VIP包厢+优先确认+免费升包
    - 金卡: 优先确认+包厢可选
    - 银卡: 正常排期
    - 普通: 正常排期,包厢需加收
    """
    level = await get_member_level(customer_id, tenant_id, db)
    reservation_id = str(uuid.uuid4())

    dispatch_result: dict[str, Any] = {
        "reservation_id": reservation_id,
        "customer_id": customer_id,
        "level": level,
        "party_size": request.get("party_size", 2),
        "requested_date": request.get("date"),
        "store_id": request.get("store_id"),
    }

    if level == "diamond":
        dispatch_result.update({
            "room_type": "vip_private",
            "priority": "immediate_confirm",
            "free_upgrade": True,
            "perks": ["VIP包厢", "优先确认", "免费升包", "欢迎果盘"],
        })
    elif level == "gold":
        dispatch_result.update({
            "room_type": "private_optional",
            "priority": "priority_confirm",
            "free_upgrade": False,
            "perks": ["优先确认", "包厢可选"],
        })
    elif level == "silver":
        dispatch_result.update({
            "room_type": "standard",
            "priority": "normal",
            "free_upgrade": False,
            "perks": ["正常排期"],
        })
    else:
        dispatch_result.update({
            "room_type": "standard",
            "priority": "normal",
            "free_upgrade": False,
            "perks": ["正常排期", "包厢需加收"],
            "room_surcharge": True,
        })

    logger.info(
        "reservation_dispatched",
        tenant_id=tenant_id,
        customer_id=customer_id,
        level=level,
        reservation_id=reservation_id,
        priority=dispatch_result["priority"],
    )
    return dispatch_result


# ── 2. 排队调度 ──────────────────────────────────────────────

async def dispatch_queue(
    customer_id: str,
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """排队调度: VIP快速通道

    - 钻石: 免排队直接入座(有空位时)
    - 金卡: VIP快速通道(插队到前30%)
    - 银卡/普通: 正常排队
    """
    level = await get_member_level(customer_id, tenant_id, db)
    queue_ticket = str(uuid.uuid4())[:8].upper()

    result: dict[str, Any] = {
        "queue_ticket": queue_ticket,
        "customer_id": customer_id,
        "store_id": store_id,
        "level": level,
        "priority_score": QUEUE_PRIORITY.get(level, 0),
    }

    if level == "diamond":
        result.update({
            "queue_type": "skip",
            "estimated_wait_minutes": 0,
            "message": "尊敬的钻石会员，已为您安排免排队直接入座",
            "perks": ["免排队", "优先选座", "专属等候区"],
        })
    elif level == "gold":
        result.update({
            "queue_type": "vip_fast",
            "estimated_wait_minutes": 5,
            "message": "尊贵的金卡会员，已为您开通VIP快速通道",
            "perks": ["VIP快速通道", "专属等候区"],
        })
    elif level == "silver":
        result.update({
            "queue_type": "normal",
            "estimated_wait_minutes": 15,
            "message": "银卡会员您好，已为您取号",
            "perks": ["正常排队"],
        })
    else:
        result.update({
            "queue_type": "normal",
            "estimated_wait_minutes": 20,
            "message": "您好，已为您取号，请耐心等候",
            "perks": ["正常排队"],
        })

    logger.info(
        "queue_dispatched",
        tenant_id=tenant_id,
        customer_id=customer_id,
        store_id=store_id,
        level=level,
        queue_type=result["queue_type"],
    )
    return result


# ── 3. 菜单调度 ──────────────────────────────────────────────

async def dispatch_menu(
    customer_id: str,
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """菜单调度: 按等级展示专属菜品/价格

    - 钻石: 专属隐藏菜单+钻石价+限量菜品
    - 金卡: 会员价+推荐高端菜品
    - 银卡: 会员价
    - 普通: 标准菜单+引导升级
    """
    level = await get_member_level(customer_id, tenant_id, db)

    result: dict[str, Any] = {
        "customer_id": customer_id,
        "store_id": store_id,
        "level": level,
        "menu_type": "standard",
        "price_tag": "standard",
        "sections": [],
    }

    if level == "diamond":
        result.update({
            "menu_type": "diamond_exclusive",
            "price_tag": "diamond_price",
            "sections": ["hidden_chef_special", "limited_seasonal", "standard"],
            "show_diamond_badge": True,
            "perks": ["专属隐藏菜单", "钻石专属价", "限量菜品优先预订"],
        })
    elif level == "gold":
        result.update({
            "menu_type": "gold_enhanced",
            "price_tag": "member_price",
            "sections": ["recommended_premium", "standard"],
            "show_gold_badge": True,
            "perks": ["会员价", "高端菜品推荐"],
        })
    elif level == "silver":
        result.update({
            "menu_type": "member",
            "price_tag": "member_price",
            "sections": ["standard"],
            "perks": ["会员价"],
        })
    else:
        result.update({
            "menu_type": "standard",
            "price_tag": "standard",
            "sections": ["standard"],
            "show_upgrade_banner": True,
            "perks": ["标准菜单"],
            "upgrade_hint": "开通会员即可享受会员价优惠",
        })

    logger.info(
        "menu_dispatched",
        tenant_id=tenant_id,
        customer_id=customer_id,
        store_id=store_id,
        level=level,
        menu_type=result["menu_type"],
    )
    return result


# ── 4. 服务调度 ──────────────────────────────────────────────

async def dispatch_service(
    customer_id: str,
    order_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """服务调度: 高等级会员专属服务

    - 钻石: 指定资深服务员+优先出餐+赠送饭后甜品
    - 金卡: 优先出餐
    - 银卡/普通: 标准服务
    """
    level = await get_member_level(customer_id, tenant_id, db)

    result: dict[str, Any] = {
        "customer_id": customer_id,
        "order_id": order_id,
        "level": level,
        "service_tier": "standard",
    }

    if level == "diamond":
        result.update({
            "service_tier": "vip",
            "assign_senior_waiter": True,
            "priority_cooking": True,
            "complimentary_dessert": True,
            "perks": ["资深服务员专属服务", "优先出餐", "赠送饭后甜品"],
        })
    elif level == "gold":
        result.update({
            "service_tier": "priority",
            "assign_senior_waiter": False,
            "priority_cooking": True,
            "complimentary_dessert": False,
            "perks": ["优先出餐"],
        })
    elif level == "silver":
        result.update({
            "service_tier": "standard",
            "assign_senior_waiter": False,
            "priority_cooking": False,
            "complimentary_dessert": False,
            "perks": ["标准服务"],
        })
    else:
        result.update({
            "service_tier": "standard",
            "assign_senior_waiter": False,
            "priority_cooking": False,
            "complimentary_dessert": False,
            "perks": ["标准服务"],
        })

    logger.info(
        "service_dispatched",
        tenant_id=tenant_id,
        customer_id=customer_id,
        order_id=order_id,
        level=level,
        service_tier=result["service_tier"],
    )
    return result


# ── 5. 优惠调度 ──────────────────────────────────────────────

async def dispatch_offer(
    customer_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """优惠调度: 按等级推送个性化优惠

    - 钻石: 专属折扣+限量套餐+免费升级
    - 金卡: 生日双倍积分+专属券
    - 银卡: 消费返积分加速
    - 普通: 新客专享+升级引导
    """
    level = await get_member_level(customer_id, tenant_id, db)

    result: dict[str, Any] = {
        "customer_id": customer_id,
        "level": level,
        "offers": [],
    }

    if level == "diamond":
        result["offers"] = [
            {"type": "exclusive_discount", "name": "钻石专属9折", "discount_rate": 0.90},
            {"type": "limited_set", "name": "限量主厨套餐", "price_fen": 88800},
            {"type": "free_upgrade", "name": "免费包厢升级券", "valid_days": 30},
            {"type": "birthday_banquet", "name": "生日宴免服务费", "valid_days": 7},
        ]
    elif level == "gold":
        result["offers"] = [
            {"type": "birthday_bonus", "name": "生日双倍积分", "multiplier": 2.0},
            {"type": "exclusive_coupon", "name": "金卡专属50元券", "amount_fen": 5000},
            {"type": "parking", "name": "免费停车2小时", "hours": 2},
        ]
    elif level == "silver":
        result["offers"] = [
            {"type": "points_boost", "name": "消费返积分1.5倍", "multiplier": 1.5},
            {"type": "birthday_coupon", "name": "生日30元券", "amount_fen": 3000},
        ]
    else:
        result["offers"] = [
            {"type": "new_customer", "name": "新客满100减20", "threshold_fen": 10000, "amount_fen": 2000},
            {"type": "upgrade_guide", "name": "升级银卡享会员价", "target_level": "silver"},
        ]

    logger.info(
        "offer_dispatched",
        tenant_id=tenant_id,
        customer_id=customer_id,
        level=level,
        offers_count=len(result["offers"]),
    )
    return result


# ── 6. 通知调度 ──────────────────────────────────────────────

async def dispatch_notification(
    customer_id: str,
    event_type: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """通知调度: 按等级选择通知渠道

    - 钻石: 专属客服电话+微信+短信
    - 金卡: 微信服务号+短信
    - 银卡/普通: 微信服务号
    """
    level = await get_member_level(customer_id, tenant_id, db)
    channels = NOTIFICATION_CHANNELS.get(level, ["wechat_service"])

    result: dict[str, Any] = {
        "customer_id": customer_id,
        "event_type": event_type,
        "level": level,
        "channels": channels,
        "notification_id": str(uuid.uuid4()),
    }

    logger.info(
        "notification_dispatched",
        tenant_id=tenant_id,
        customer_id=customer_id,
        event_type=event_type,
        level=level,
        channels=channels,
    )
    return result


# ── 7. 个性化首页 ────────────────────────────────────────────

async def get_personalized_home(
    customer_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """个性化首页: 按等级+历史+场景定制

    返回:
        greeting: 问候语
        exclusive_banner: 等级专属Banner
        recommended_dishes: 基于历史的推荐
        available_benefits: 可用权益列表
        upgrade_progress: 升级进度(距下一等级)
        scene_actions: 场景化快捷入口
    """
    level = await get_member_level(customer_id, tenant_id, db)
    level_cn = LEVEL_NAMES_CN.get(level, "会员")

    # 获取年度消费用于计算升级进度
    await _set_tenant(db, tenant_id)
    spend_result = await db.execute(
        text("""
            SELECT COALESCE(SUM(balance_fen), 0) AS total_spend_fen
            FROM member_cards
            WHERE customer_id = :cid AND tenant_id = :tid
              AND status = 'active' AND is_deleted = false
        """),
        {"cid": customer_id, "tid": tenant_id},
    )
    spend_row = spend_result.mappings().first()
    total_spend_fen = spend_row["total_spend_fen"] if spend_row else 0

    # 计算升级进度
    upgrade_info = _calc_upgrade_progress(level, total_spend_fen)

    result: dict[str, Any] = {
        "customer_id": customer_id,
        "level": level,
        "greeting": f"尊敬的{level_cn}",
        "exclusive_banner": _get_banner(level),
        "recommended_dishes": [],  # 实际由推荐引擎填充
        "available_benefits": _get_available_benefits(level),
        "upgrade_progress": upgrade_info,
        "scene_actions": _get_scene_actions(level),
    }

    logger.info(
        "personalized_home_generated",
        tenant_id=tenant_id,
        customer_id=customer_id,
        level=level,
    )
    return result


# ── 8. 升级机会检测 ──────────────────────────────────────────

async def check_upgrade_opportunity(
    customer_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """升级机会检测: 提示"再消费XX元即可升级金卡"

    用于购物车/结账页面的升级激励。
    """
    level = await get_member_level(customer_id, tenant_id, db)

    await _set_tenant(db, tenant_id)
    spend_result = await db.execute(
        text("""
            SELECT COALESCE(SUM(growth_value), 0) AS total_growth
            FROM member_cards
            WHERE customer_id = :cid AND tenant_id = :tid
              AND status = 'active' AND is_deleted = false
        """),
        {"cid": customer_id, "tid": tenant_id},
    )
    spend_row = spend_result.mappings().first()
    total_growth = spend_row["total_growth"] if spend_row else 0

    upgrade_info = _calc_upgrade_progress(level, total_growth)

    result: dict[str, Any] = {
        "customer_id": customer_id,
        "current_level": level,
        "current_level_cn": LEVEL_NAMES_CN.get(level, "会员"),
        "total_growth_value": total_growth,
        **upgrade_info,
    }

    logger.info(
        "upgrade_opportunity_checked",
        tenant_id=tenant_id,
        customer_id=customer_id,
        level=level,
        has_opportunity=upgrade_info.get("has_next_level", False),
    )
    return result


# ── 9. 自动应用等级权益到订单 ─────────────────────────────────

async def apply_level_benefits(
    customer_id: str,
    order_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """自动应用等级权益到订单:

    - 自动应用会员价
    - 自动匹配最优等级券
    - 计算等级积分加速
    - 应用免费升级(如有)

    权益自动应用不需要用户操作。
    """
    level = await get_member_level(customer_id, tenant_id, db)
    applied_benefits: list[dict] = []

    # 1. 会员价
    if level in ("diamond", "gold", "silver"):
        price_tag = "diamond_price" if level == "diamond" else "member_price"
        applied_benefits.append({
            "type": "member_price",
            "price_tag": price_tag,
            "description": f"{'钻石专属价' if level == 'diamond' else '会员价'}已自动应用",
        })

    # 2. 积分加速
    multiplier = POINTS_MULTIPLIER.get(level, 1.0)
    if multiplier > 1.0:
        applied_benefits.append({
            "type": "points_multiplier",
            "multiplier": multiplier,
            "description": f"积分{multiplier}倍加速",
        })

    # 3. 钻石专属: 赠送甜品
    if level == "diamond":
        applied_benefits.append({
            "type": "complimentary_item",
            "item": "dessert",
            "description": "钻石会员专属饭后甜品",
        })

    # 4. 金卡: 免费停车
    if level == "gold":
        applied_benefits.append({
            "type": "free_parking",
            "hours": 2,
            "description": "金卡会员免费停车2小时",
        })

    result: dict[str, Any] = {
        "customer_id": customer_id,
        "order_id": order_id,
        "level": level,
        "applied_benefits": applied_benefits,
        "benefits_count": len(applied_benefits),
        "auto_applied": True,
    }

    logger.info(
        "level_benefits_applied",
        tenant_id=tenant_id,
        customer_id=customer_id,
        order_id=order_id,
        level=level,
        benefits_count=len(applied_benefits),
    )
    return result


# ── 内部辅助函数 ──────────────────────────────────────────────

def _calc_upgrade_progress(current_level: str, current_spend_fen: int) -> dict[str, Any]:
    """计算升级进度"""
    level_order = ["normal", "silver", "gold", "diamond"]
    current_idx = level_order.index(current_level) if current_level in level_order else 0

    if current_idx >= len(level_order) - 1:
        return {
            "has_next_level": False,
            "next_level": None,
            "next_level_cn": None,
            "remaining_fen": 0,
            "progress_percent": 100.0,
            "message": "您已达到最高等级",
        }

    next_level = level_order[current_idx + 1]
    next_threshold = UPGRADE_THRESHOLDS_FEN[next_level]
    current_threshold = UPGRADE_THRESHOLDS_FEN[current_level]

    remaining = max(0, next_threshold - current_spend_fen)
    range_fen = next_threshold - current_threshold
    progress = min(100.0, ((current_spend_fen - current_threshold) / range_fen * 100)) if range_fen > 0 else 0.0
    progress = max(0.0, progress)

    remaining_yuan = remaining / 100

    return {
        "has_next_level": True,
        "next_level": next_level,
        "next_level_cn": LEVEL_NAMES_CN[next_level],
        "remaining_fen": remaining,
        "progress_percent": round(progress, 1),
        "message": f"再消费{remaining_yuan:.0f}元即可升级{LEVEL_NAMES_CN[next_level]}",
    }


def _get_banner(level: str) -> dict[str, str]:
    """获取等级专属Banner"""
    banners = {
        "diamond": {"image": "banner_diamond.png", "title": "钻石尊享 · 极致体验", "color": "#1a1a2e"},
        "gold": {"image": "banner_gold.png", "title": "金卡优享 · 品质生活", "color": "#d4a373"},
        "silver": {"image": "banner_silver.png", "title": "银卡专属 · 超值好味", "color": "#8d99ae"},
        "normal": {"image": "banner_normal.png", "title": "欢迎光临 · 开启美味之旅", "color": "#588157"},
    }
    return banners.get(level, banners["normal"])


def _get_available_benefits(level: str) -> list[dict[str, str]]:
    """获取等级可用权益列表"""
    benefits_map = {
        "diamond": [
            {"key": "vip_room", "name": "VIP包厢优先"},
            {"key": "skip_queue", "name": "免排队直接入座"},
            {"key": "exclusive_menu", "name": "专属隐藏菜单"},
            {"key": "senior_waiter", "name": "资深服务员"},
            {"key": "priority_cooking", "name": "优先出餐"},
            {"key": "complimentary_dessert", "name": "赠送甜品"},
            {"key": "birthday_banquet", "name": "生日宴免服务费"},
            {"key": "points_3x", "name": "积分3倍加速"},
        ],
        "gold": [
            {"key": "fast_queue", "name": "VIP快速通道"},
            {"key": "member_price", "name": "会员价"},
            {"key": "priority_cooking", "name": "优先出餐"},
            {"key": "birthday_bonus", "name": "生日双倍积分"},
            {"key": "free_parking", "name": "免费停车"},
            {"key": "points_2x", "name": "积分2倍加速"},
        ],
        "silver": [
            {"key": "member_price", "name": "会员价"},
            {"key": "points_1_5x", "name": "积分1.5倍加速"},
            {"key": "birthday_coupon", "name": "生日券"},
        ],
        "normal": [
            {"key": "points", "name": "消费积分"},
        ],
    }
    return benefits_map.get(level, benefits_map["normal"])


def _get_scene_actions(level: str) -> list[dict[str, str]]:
    """获取场景化快捷入口"""
    base_actions = [
        {"key": "scan_order", "name": "扫码点餐", "icon": "scan"},
        {"key": "queue", "name": "在线排队", "icon": "queue"},
        {"key": "reservation", "name": "预订包厢", "icon": "calendar"},
        {"key": "takeout", "name": "外卖到家", "icon": "delivery"},
    ]

    if level in ("diamond", "gold"):
        base_actions.insert(0, {"key": "vip_service", "name": "专属服务", "icon": "crown"})

    if level == "diamond":
        base_actions.insert(1, {"key": "chef_special", "name": "主厨推荐", "icon": "chef"})

    return base_actions
