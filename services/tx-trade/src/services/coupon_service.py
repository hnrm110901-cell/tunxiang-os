"""券权益与会员识别服务

储值卡余额单位：分（fen）。
券叠加规则：同类型不叠加，不同类型可叠加。
权益优先级：会员价 > 活动券 > 通用券。
"""
import uuid
from datetime import date, datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Customer, Order

logger = structlog.get_logger()


# ─── 内存存储（轻量模拟，生产环境替换为数据库表） ───


class _CouponStore:
    """优惠券存储"""

    _coupons: dict[str, dict] = {}

    @classmethod
    def save(cls, code: str, data: dict) -> None:
        cls._coupons[code] = data

    @classmethod
    def get(cls, code: str) -> Optional[dict]:
        return cls._coupons.get(code)

    @classmethod
    def list_by_store(cls, store_id: str, start_date: date, end_date: date) -> list[dict]:
        results = []
        for data in cls._coupons.values():
            if data.get("store_id") == store_id and data.get("status") == "redeemed":
                redeemed_at = data.get("redeemed_at")
                if redeemed_at:
                    rd = datetime.fromisoformat(redeemed_at).date()
                    if start_date <= rd <= end_date:
                        results.append(data)
        return results


class _StoredValueStore:
    """储值卡存储"""

    _cards: dict[str, dict] = {}

    @classmethod
    def save(cls, card_id: str, data: dict) -> None:
        cls._cards[card_id] = data

    @classmethod
    def get(cls, card_id: str) -> Optional[dict]:
        return cls._cards.get(card_id)


class _MemberPriceStore:
    """会员价配置存储"""

    _prices: dict[str, dict] = {}  # key: f"{dish_id}:{level}"

    @classmethod
    def save(cls, dish_id: str, level: str, price_fen: int) -> None:
        cls._prices[f"{dish_id}:{level}"] = {
            "dish_id": dish_id,
            "level": level,
            "member_price_fen": price_fen,
        }

    @classmethod
    def get(cls, dish_id: str, level: str) -> Optional[dict]:
        return cls._prices.get(f"{dish_id}:{level}")


# ─── 券类型与叠加规则 ───

COUPON_TYPES = {
    "member_price": "会员价",
    "activity": "活动券",
    "general": "通用券",
    "stored_value": "储值消费",
}

# 权益优先级：数字越小优先级越高
BENEFIT_PRIORITY = {
    "member_price": 1,
    "activity": 2,
    "general": 3,
    "stored_value": 4,
}


# ─── 会员识别 ───


async def identify_member(
    phone_or_card: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """会员识别 — 返回等级/积分/余额/偏好

    通过手机号或卡号查询CDP Customer实体。
    """
    result = await db.execute(
        select(Customer).where(
            Customer.primary_phone == phone_or_card,
            Customer.tenant_id == uuid.UUID(tenant_id),
            Customer.is_merged == False,  # noqa: E712
        )
    )
    customer = result.scalar_one_or_none()
    if not customer:
        logger.info(
            "member_not_found",
            phone_or_card=phone_or_card,
            tenant_id=tenant_id,
        )
        return {"found": False, "phone_or_card": phone_or_card}

    member_info = {
        "found": True,
        "customer_id": str(customer.id),
        "display_name": customer.display_name,
        "phone": customer.primary_phone,
        "rfm_level": customer.rfm_level or "S3",
        "total_order_count": customer.total_order_count or 0,
        "total_order_amount_fen": customer.total_order_amount_fen or 0,
        "tags": customer.tags or [],
        "dietary_restrictions": customer.dietary_restrictions or [],
        "risk_score": customer.risk_score or 0.0,
    }

    logger.info(
        "member_identified",
        customer_id=str(customer.id),
        rfm_level=member_info["rfm_level"],
        tenant_id=tenant_id,
    )
    return member_info


# ─── 储值卡开卡 ───


async def create_stored_value_card(
    customer_id: str,
    initial_amount_fen: int,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """储值卡开卡"""
    if initial_amount_fen < 0:
        raise ValueError("初始金额不能为负")

    card_id = str(uuid.uuid4())
    card_data = {
        "card_id": card_id,
        "customer_id": customer_id,
        "tenant_id": tenant_id,
        "balance_fen": initial_amount_fen,
        "total_recharged_fen": initial_amount_fen,
        "total_consumed_fen": 0,
        "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "transactions": [
            {
                "type": "initial",
                "amount_fen": initial_amount_fen,
                "balance_after_fen": initial_amount_fen,
                "at": datetime.now(timezone.utc).isoformat(),
            }
        ],
    }
    _StoredValueStore.save(card_id, card_data)

    logger.info(
        "stored_value_card_created",
        card_id=card_id,
        customer_id=customer_id,
        initial_amount_fen=initial_amount_fen,
        tenant_id=tenant_id,
    )
    return card_data


# ─── 储值充值 ───


async def recharge(
    card_id: str,
    amount_fen: int,
    payment_method: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """储值充值"""
    if amount_fen <= 0:
        raise ValueError("充值金额必须大于0")

    card = _StoredValueStore.get(card_id)
    if not card:
        raise ValueError(f"储值卡不存在: {card_id}")
    if card["tenant_id"] != tenant_id:
        raise ValueError("租户不匹配")
    if card["status"] != "active":
        raise ValueError(f"储值卡状态异常: {card['status']}")

    card["balance_fen"] += amount_fen
    card["total_recharged_fen"] += amount_fen
    card["transactions"].append({
        "type": "recharge",
        "amount_fen": amount_fen,
        "payment_method": payment_method,
        "balance_after_fen": card["balance_fen"],
        "at": datetime.now(timezone.utc).isoformat(),
    })
    _StoredValueStore.save(card_id, card)

    logger.info(
        "stored_value_recharged",
        card_id=card_id,
        amount_fen=amount_fen,
        new_balance_fen=card["balance_fen"],
        tenant_id=tenant_id,
    )
    return {
        "card_id": card_id,
        "recharged_fen": amount_fen,
        "balance_fen": card["balance_fen"],
    }


# ─── 储值消费 ───


async def deduct_stored_value(
    card_id: str,
    amount_fen: int,
    order_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """储值消费 — 从储值卡扣款"""
    if amount_fen <= 0:
        raise ValueError("扣款金额必须大于0")

    card = _StoredValueStore.get(card_id)
    if not card:
        raise ValueError(f"储值卡不存在: {card_id}")
    if card["tenant_id"] != tenant_id:
        raise ValueError("租户不匹配")
    if card["status"] != "active":
        raise ValueError(f"储值卡状态异常: {card['status']}")
    if card["balance_fen"] < amount_fen:
        raise ValueError(
            f"余额不足: 当前{card['balance_fen']}分, 需扣{amount_fen}分"
        )

    card["balance_fen"] -= amount_fen
    card["total_consumed_fen"] += amount_fen
    card["transactions"].append({
        "type": "consume",
        "amount_fen": -amount_fen,
        "order_id": order_id,
        "balance_after_fen": card["balance_fen"],
        "at": datetime.now(timezone.utc).isoformat(),
    })
    _StoredValueStore.save(card_id, card)

    logger.info(
        "stored_value_deducted",
        card_id=card_id,
        amount_fen=amount_fen,
        order_id=order_id,
        remaining_fen=card["balance_fen"],
        tenant_id=tenant_id,
    )
    return {
        "card_id": card_id,
        "deducted_fen": amount_fen,
        "balance_fen": card["balance_fen"],
        "order_id": order_id,
    }


# ─── 券验证 ───


async def verify_coupon(
    coupon_code: str,
    order_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """券验证 — 有效性/适用范围/叠加规则"""
    coupon = _CouponStore.get(coupon_code)
    if not coupon:
        return {
            "valid": False,
            "coupon_code": coupon_code,
            "reason": "券不存在",
        }

    if coupon.get("tenant_id") != tenant_id:
        return {"valid": False, "coupon_code": coupon_code, "reason": "租户不匹配"}

    if coupon.get("status") != "active":
        return {
            "valid": False,
            "coupon_code": coupon_code,
            "reason": f"券状态异常: {coupon.get('status')}",
        }

    # 检查有效期
    now = datetime.now(timezone.utc)
    expires_at = coupon.get("expires_at")
    if expires_at:
        exp = datetime.fromisoformat(expires_at)
        if now > exp:
            return {
                "valid": False,
                "coupon_code": coupon_code,
                "reason": "券已过期",
            }

    # 检查最低消费
    min_amount_fen = coupon.get("min_order_amount_fen", 0)
    if min_amount_fen > 0 and order_id:
        result = await db.execute(
            select(Order).where(Order.id == uuid.UUID(order_id))
        )
        order = result.scalar_one_or_none()
        if order and order.total_amount_fen < min_amount_fen:
            return {
                "valid": False,
                "coupon_code": coupon_code,
                "reason": f"未达最低消费: 订单{order.total_amount_fen}分 < 要求{min_amount_fen}分",
            }

    logger.info(
        "coupon_verified",
        coupon_code=coupon_code,
        coupon_type=coupon.get("coupon_type"),
        order_id=order_id,
        tenant_id=tenant_id,
    )
    return {
        "valid": True,
        "coupon_code": coupon_code,
        "coupon_type": coupon.get("coupon_type"),
        "discount_fen": coupon.get("discount_fen", 0),
        "min_order_amount_fen": min_amount_fen,
        "stackable": coupon.get("stackable", True),
    }


# ─── 券核销 ───


async def redeem_coupon(
    coupon_code: str,
    order_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """券核销 — 标记已使用"""
    verification = await verify_coupon(coupon_code, order_id, tenant_id, db)
    if not verification["valid"]:
        raise ValueError(f"券核销失败: {verification['reason']}")

    coupon = _CouponStore.get(coupon_code)
    if not coupon:
        raise ValueError(f"券不存在: {coupon_code}")

    coupon["status"] = "redeemed"
    coupon["redeemed_at"] = datetime.now(timezone.utc).isoformat()
    coupon["redeemed_order_id"] = order_id
    _CouponStore.save(coupon_code, coupon)

    logger.info(
        "coupon_redeemed",
        coupon_code=coupon_code,
        order_id=order_id,
        discount_fen=coupon.get("discount_fen", 0),
        tenant_id=tenant_id,
    )
    return {
        "coupon_code": coupon_code,
        "order_id": order_id,
        "discount_fen": coupon.get("discount_fen", 0),
        "coupon_type": coupon.get("coupon_type"),
        "redeemed_at": coupon["redeemed_at"],
    }


# ─── 权益冲突校验 ───


async def check_benefit_conflict(
    benefits: list[dict],
    order_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """权益冲突校验

    规则：
    - 同类型不叠加（如两张通用券不可同时使用）
    - 不同类型可叠加（如会员价 + 活动券）
    - 按优先级排序：会员价 > 活动券 > 通用券
    """
    type_counts: dict[str, int] = {}
    conflicts: list[dict] = []
    applicable: list[dict] = []

    for benefit in benefits:
        btype = benefit.get("benefit_type", "general")
        type_counts[btype] = type_counts.get(btype, 0) + 1

    # 检测同类型冲突
    for btype, count in type_counts.items():
        if count > 1:
            conflicts.append({
                "conflict_type": "same_type_stack",
                "benefit_type": btype,
                "count": count,
                "message": f"同类型权益({COUPON_TYPES.get(btype, btype)})不可叠加，已选{count}个",
            })

    # 按优先级排序可用权益（每种类型取第一个）
    seen_types: set[str] = set()
    sorted_benefits = sorted(
        benefits,
        key=lambda b: BENEFIT_PRIORITY.get(b.get("benefit_type", "general"), 99),
    )
    for benefit in sorted_benefits:
        btype = benefit.get("benefit_type", "general")
        if btype not in seen_types:
            applicable.append(benefit)
            seen_types.add(btype)

    has_conflict = len(conflicts) > 0

    logger.info(
        "benefit_conflict_checked",
        order_id=order_id,
        total_benefits=len(benefits),
        conflicts=len(conflicts),
        applicable=len(applicable),
        tenant_id=tenant_id,
    )
    return {
        "has_conflict": has_conflict,
        "conflicts": conflicts,
        "applicable_benefits": applicable,
        "priority_order": ["member_price", "activity", "general"],
    }


# ─── 会员价计算 ───


async def calculate_member_price(
    dish_id: str,
    member_level: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """会员价计算

    基于会员等级查找对应折扣。默认折扣率：
    - S1 (VIP): 8.5折
    - S2 (金卡): 9.0折
    - S3 (银卡): 9.5折
    - S4/S5 (普通): 无折扣
    """
    # 先查自定义会员价
    custom_price = _MemberPriceStore.get(dish_id, member_level)
    if custom_price:
        logger.info(
            "member_price_custom",
            dish_id=dish_id,
            member_level=member_level,
            price_fen=custom_price["member_price_fen"],
            tenant_id=tenant_id,
        )
        return {
            "dish_id": dish_id,
            "member_level": member_level,
            "has_member_price": True,
            "member_price_fen": custom_price["member_price_fen"],
            "source": "custom",
        }

    # 默认等级折扣
    level_discounts = {
        "S1": 0.85,
        "S2": 0.90,
        "S3": 0.95,
        "S4": 1.0,
        "S5": 1.0,
    }
    discount_rate = level_discounts.get(member_level, 1.0)
    has_discount = discount_rate < 1.0

    logger.info(
        "member_price_calculated",
        dish_id=dish_id,
        member_level=member_level,
        discount_rate=discount_rate,
        tenant_id=tenant_id,
    )
    return {
        "dish_id": dish_id,
        "member_level": member_level,
        "has_member_price": has_discount,
        "discount_rate": discount_rate,
        "source": "default_level",
    }


# ─── 券核销审计 ───


async def get_coupon_audit(
    store_id: str,
    date_range: tuple[str, str],
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """券核销审计 — 查询门店指定日期范围内的券核销记录"""
    start_date = date.fromisoformat(date_range[0])
    end_date = date.fromisoformat(date_range[1])

    records = _CouponStore.list_by_store(store_id, start_date, end_date)

    total_discount_fen = sum(r.get("discount_fen", 0) for r in records)

    # 按券类型分组统计
    by_type: dict[str, dict] = {}
    for r in records:
        ctype = r.get("coupon_type", "unknown")
        if ctype not in by_type:
            by_type[ctype] = {"count": 0, "total_discount_fen": 0}
        by_type[ctype]["count"] += 1
        by_type[ctype]["total_discount_fen"] += r.get("discount_fen", 0)

    logger.info(
        "coupon_audit_queried",
        store_id=store_id,
        date_range=date_range,
        record_count=len(records),
        total_discount_fen=total_discount_fen,
        tenant_id=tenant_id,
    )
    return {
        "store_id": store_id,
        "date_range": {"start": date_range[0], "end": date_range[1]},
        "record_count": len(records),
        "total_discount_fen": total_discount_fen,
        "by_type": by_type,
        "records": records,
    }
