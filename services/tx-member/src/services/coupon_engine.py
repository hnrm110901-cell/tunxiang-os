"""优惠券引擎 — 7种券类型 + 叠加规则 + 收入核算

券面值单位：分（fen）。
叠加规则：同类型不叠加，不同类型可叠加。
优先级：商品券(free_item/upgrade/buy_gift) > 折扣券(discount) > 代金券(cash)。
"""
import random
import string
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import structlog

logger = structlog.get_logger()


# ─── 券类型枚举 ───


class CouponType(str, Enum):
    CASH = "cash"            # 代金券（固定面值/不找零/门槛）
    DISCOUNT = "discount"    # 折扣券（按订单/菜品/分类）
    FREE_ITEM = "free_item"  # 商品券-免费兑换
    UPGRADE = "upgrade"      # 商品券-加价换购
    BUY_GIFT = "buy_gift"    # 商品券-买赠
    GIFT = "gift"            # 礼品券（实物/批量制券）
    DELIVERY = "delivery"    # 配送券（外卖配送费）


# 优先级：数字越小优先级越高
COUPON_PRIORITY = {
    CouponType.FREE_ITEM: 1,
    CouponType.UPGRADE: 1,
    CouponType.BUY_GIFT: 1,
    CouponType.GIFT: 1,
    CouponType.DISCOUNT: 2,
    CouponType.CASH: 3,
    CouponType.DELIVERY: 4,
}

# 商品券类型集合
ITEM_COUPON_TYPES = {CouponType.FREE_ITEM, CouponType.UPGRADE, CouponType.BUY_GIFT, CouponType.GIFT}


# ─── 内存存储 ───


class _CouponTemplateStore:
    """券模板存储"""
    _templates: dict[str, dict] = {}

    @classmethod
    def save(cls, coupon_id: str, data: dict) -> None:
        cls._templates[coupon_id] = data

    @classmethod
    def get(cls, coupon_id: str) -> Optional[dict]:
        return cls._templates.get(coupon_id)

    @classmethod
    def list_by_tenant(cls, tenant_id: str) -> list[dict]:
        return [t for t in cls._templates.values() if t.get("tenant_id") == tenant_id]

    @classmethod
    def clear(cls) -> None:
        cls._templates.clear()


class _CouponInstanceStore:
    """券实例存储（已发放的券）"""
    _instances: dict[str, dict] = {}

    @classmethod
    def save(cls, code: str, data: dict) -> None:
        cls._instances[code] = data

    @classmethod
    def get(cls, code: str) -> Optional[dict]:
        return cls._instances.get(code)

    @classmethod
    def list_by_tenant(cls, tenant_id: str) -> list[dict]:
        return [i for i in cls._instances.values() if i.get("tenant_id") == tenant_id]

    @classmethod
    def list_by_coupon_id(cls, coupon_id: str) -> list[dict]:
        return [i for i in cls._instances.values() if i.get("coupon_id") == coupon_id]

    @classmethod
    def list_by_customer(cls, customer_id: str, tenant_id: str) -> list[dict]:
        return [
            i for i in cls._instances.values()
            if i.get("customer_id") == customer_id and i.get("tenant_id") == tenant_id
        ]

    @classmethod
    def clear(cls) -> None:
        cls._instances.clear()


class _RevenueRuleStore:
    """券收入规则存储"""
    _rules: dict[str, dict] = {}

    @classmethod
    def save(cls, coupon_id: str, data: dict) -> None:
        cls._rules[coupon_id] = data

    @classmethod
    def get(cls, coupon_id: str) -> Optional[dict]:
        return cls._rules.get(coupon_id)

    @classmethod
    def clear(cls) -> None:
        cls._rules.clear()


def _generate_code(prefix: str = "CPN") -> str:
    """生成唯一券码"""
    rand = "".join(random.choices(string.ascii_uppercase + string.digits, k=10))
    return f"{prefix}-{rand}"


# ─── 创建券模板 ───


async def create_coupon(
    coupon_type: str,
    config: dict,
    tenant_id: str,
    db=None,
) -> dict:
    """创建券模板

    config 字段说明:
    - name: 券名称
    - face_value_fen: 面值（分），代金券/配送券必填
    - discount_rate: 折扣率（0-100），折扣券必填，如85表示8.5折
    - min_order_amount_fen: 门槛金额（分）
    - applicable_scope: 适用范围 {"type": "all"/"category"/"dish", "ids": [...]}
    - valid_days: 有效天数
    - expires_at: 过期时间 ISO 格式
    - max_issue_count: 最大发放数量
    - no_change: 不找零（代金券），默认True
    - item_dish_id: 商品券对应菜品ID
    - upgrade_price_fen: 加价换购价格（分）
    - buy_dish_id / buy_count / gift_dish_id / gift_count: 买赠规则
    """
    try:
        ct = CouponType(coupon_type)
    except ValueError as exc:
        raise ValueError(f"不支持的券类型: {coupon_type}") from exc

    coupon_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    template = {
        "coupon_id": coupon_id,
        "coupon_type": ct.value,
        "tenant_id": tenant_id,
        "name": config.get("name", f"{ct.value}券"),
        "face_value_fen": config.get("face_value_fen", 0),
        "discount_rate": config.get("discount_rate", 100),
        "min_order_amount_fen": config.get("min_order_amount_fen", 0),
        "applicable_scope": config.get("applicable_scope", {"type": "all"}),
        "valid_days": config.get("valid_days"),
        "expires_at": config.get("expires_at"),
        "max_issue_count": config.get("max_issue_count"),
        "no_change": config.get("no_change", True),
        "item_dish_id": config.get("item_dish_id"),
        "upgrade_price_fen": config.get("upgrade_price_fen", 0),
        "buy_dish_id": config.get("buy_dish_id"),
        "buy_count": config.get("buy_count", 0),
        "gift_dish_id": config.get("gift_dish_id"),
        "gift_count": config.get("gift_count", 0),
        "issued_count": 0,
        "redeemed_count": 0,
        "status": "active",
        "created_at": now,
    }

    _CouponTemplateStore.save(coupon_id, template)

    logger.info(
        "coupon_template_created",
        coupon_id=coupon_id,
        coupon_type=ct.value,
        name=template["name"],
        tenant_id=tenant_id,
    )
    return template


# ─── 批量发放 ───


async def batch_issue(
    coupon_id: str,
    target_customers: list[str],
    tenant_id: str,
    db=None,
) -> dict:
    """批量发放券给指定客户列表"""
    template = _CouponTemplateStore.get(coupon_id)
    if not template:
        raise ValueError(f"券模板不存在: {coupon_id}")
    if template["tenant_id"] != tenant_id:
        raise ValueError("租户不匹配")
    if template["status"] != "active":
        raise ValueError(f"券模板状态异常: {template['status']}")

    max_count = template.get("max_issue_count")
    if max_count and template["issued_count"] + len(target_customers) > max_count:
        raise ValueError(
            f"超出最大发放量: 已发{template['issued_count']}, "
            f"本次{len(target_customers)}, 上限{max_count}"
        )

    now = datetime.now(timezone.utc)
    issued = []

    for customer_id in target_customers:
        code = _generate_code()
        expires_at = template.get("expires_at")
        if not expires_at and template.get("valid_days"):
            from datetime import timedelta
            expires_at = (now + timedelta(days=template["valid_days"])).isoformat()

        instance = {
            "code": code,
            "coupon_id": coupon_id,
            "coupon_type": template["coupon_type"],
            "customer_id": customer_id,
            "tenant_id": tenant_id,
            "face_value_fen": template["face_value_fen"],
            "discount_rate": template["discount_rate"],
            "min_order_amount_fen": template["min_order_amount_fen"],
            "applicable_scope": template["applicable_scope"],
            "no_change": template.get("no_change", True),
            "item_dish_id": template.get("item_dish_id"),
            "upgrade_price_fen": template.get("upgrade_price_fen", 0),
            "buy_dish_id": template.get("buy_dish_id"),
            "buy_count": template.get("buy_count", 0),
            "gift_dish_id": template.get("gift_dish_id"),
            "gift_count": template.get("gift_count", 0),
            "status": "active",
            "expires_at": expires_at,
            "issued_at": now.isoformat(),
            "redeemed_at": None,
            "redeemed_order_id": None,
        }
        _CouponInstanceStore.save(code, instance)
        issued.append({"code": code, "customer_id": customer_id})

    template["issued_count"] += len(target_customers)
    _CouponTemplateStore.save(coupon_id, template)

    logger.info(
        "coupons_batch_issued",
        coupon_id=coupon_id,
        count=len(issued),
        tenant_id=tenant_id,
    )
    return {
        "coupon_id": coupon_id,
        "issued_count": len(issued),
        "issued": issued,
    }


# ─── 验证券 ───


async def verify_coupon(
    code: str,
    order_id: str,
    tenant_id: str,
    db=None,
) -> dict:
    """验证券（有效性/门槛/适用范围/过期）"""
    instance = _CouponInstanceStore.get(code)
    if not instance:
        return {"valid": False, "code": code, "reason": "券不存在"}

    if instance["tenant_id"] != tenant_id:
        return {"valid": False, "code": code, "reason": "租户不匹配"}

    if instance["status"] != "active":
        return {"valid": False, "code": code, "reason": f"券状态异常: {instance['status']}"}

    # 检查过期
    now = datetime.now(timezone.utc)
    if instance.get("expires_at"):
        exp = datetime.fromisoformat(instance["expires_at"])
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if now > exp:
            instance["status"] = "expired"
            _CouponInstanceStore.save(code, instance)
            return {"valid": False, "code": code, "reason": "券已过期"}

    logger.info(
        "coupon_verified",
        code=code,
        coupon_type=instance["coupon_type"],
        order_id=order_id,
        tenant_id=tenant_id,
    )
    return {
        "valid": True,
        "code": code,
        "coupon_type": instance["coupon_type"],
        "face_value_fen": instance.get("face_value_fen", 0),
        "discount_rate": instance.get("discount_rate", 100),
        "min_order_amount_fen": instance.get("min_order_amount_fen", 0),
    }


# ─── 核销券 ───


async def redeem_coupon(
    code: str,
    order_id: str,
    tenant_id: str,
    db=None,
) -> dict:
    """核销券 — 标记已使用"""
    verification = await verify_coupon(code, order_id, tenant_id, db)
    if not verification["valid"]:
        raise ValueError(f"券核销失败: {verification['reason']}")

    instance = _CouponInstanceStore.get(code)
    if not instance:
        raise ValueError(f"券不存在: {code}")

    instance["status"] = "redeemed"
    instance["redeemed_at"] = datetime.now(timezone.utc).isoformat()
    instance["redeemed_order_id"] = order_id
    _CouponInstanceStore.save(code, instance)

    # 更新模板统计
    template = _CouponTemplateStore.get(instance["coupon_id"])
    if template:
        template["redeemed_count"] = template.get("redeemed_count", 0) + 1
        _CouponTemplateStore.save(instance["coupon_id"], template)

    logger.info(
        "coupon_redeemed",
        code=code,
        coupon_type=instance["coupon_type"],
        order_id=order_id,
        tenant_id=tenant_id,
    )
    return {
        "code": code,
        "coupon_type": instance["coupon_type"],
        "order_id": order_id,
        "redeemed_at": instance["redeemed_at"],
    }


# ─── 叠加规则检查 ───


async def check_stacking_rules(
    coupons: list[dict],
    order_id: str,
    tenant_id: str,
    db=None,
) -> dict:
    """叠加规则检查

    规则：
    - 同类型不叠加（如两张代金券不可同时使用）
    - 不同类型可叠加（如代金券 + 折扣券）
    - 返回可用券列表（每种类型取优惠最大的一张）
    """
    type_groups: dict[str, list[dict]] = {}
    conflicts: list[dict] = []

    for coupon in coupons:
        ct = coupon.get("coupon_type", "cash")
        if ct not in type_groups:
            type_groups[ct] = []
        type_groups[ct].append(coupon)

    # 检测同类型冲突
    for ct, group in type_groups.items():
        if len(group) > 1:
            conflicts.append({
                "conflict_type": "same_type_stack",
                "coupon_type": ct,
                "count": len(group),
                "message": f"同类型券({ct})不可叠加，已选{len(group)}张",
            })

    # 每种类型取面值/折扣最优的一张
    applicable: list[dict] = []
    for ct, group in type_groups.items():
        if ct in ("cash", "delivery"):
            best = max(group, key=lambda c: c.get("face_value_fen", 0))
        elif ct == "discount":
            best = min(group, key=lambda c: c.get("discount_rate", 100))
        else:
            best = group[0]
        applicable.append(best)

    # 按优先级排序
    applicable.sort(key=lambda c: COUPON_PRIORITY.get(CouponType(c.get("coupon_type", "cash")), 99))

    has_conflict = len(conflicts) > 0

    logger.info(
        "stacking_rules_checked",
        order_id=order_id,
        total_coupons=len(coupons),
        conflicts=len(conflicts),
        applicable=len(applicable),
        tenant_id=tenant_id,
    )
    return {
        "has_conflict": has_conflict,
        "conflicts": conflicts,
        "applicable_coupons": applicable,
        "priority_order": ["free_item/upgrade/buy_gift/gift", "discount", "cash", "delivery"],
    }


# ─── 计算优惠金额 ───


async def calculate_discount(
    coupons: list[dict],
    order: dict,
    tenant_id: str,
    db=None,
) -> dict:
    """计算优惠金额

    order 格式: {"order_id": str, "total_fen": int, "items": [...], "delivery_fee_fen": int}
    按优先级依次计算：商品券 > 折扣券 > 代金券 > 配送券。
    """
    total_fen = order.get("total_fen", 0)
    delivery_fee_fen = order.get("delivery_fee_fen", 0)
    remaining_fen = total_fen
    total_discount_fen = 0
    details: list[dict] = []

    # 按优先级排序
    sorted_coupons = sorted(
        coupons,
        key=lambda c: COUPON_PRIORITY.get(CouponType(c.get("coupon_type", "cash")), 99),
    )

    for coupon in sorted_coupons:
        ct = coupon.get("coupon_type")
        discount_fen = 0

        # 检查门槛
        min_amount = coupon.get("min_order_amount_fen", 0)
        if min_amount > 0 and total_fen < min_amount:
            details.append({
                "code": coupon.get("code"),
                "coupon_type": ct,
                "discount_fen": 0,
                "reason": f"未达门槛: 订单{total_fen}分 < 要求{min_amount}分",
            })
            continue

        if ct == CouponType.CASH.value:
            face = coupon.get("face_value_fen", 0)
            # 代金券不找零
            discount_fen = min(face, remaining_fen)

        elif ct == CouponType.DISCOUNT.value:
            rate = coupon.get("discount_rate", 100)
            discount_fen = remaining_fen - int(remaining_fen * rate / 100)

        elif ct == CouponType.FREE_ITEM.value:
            # 免费兑换：减去商品原价
            item_dish_id = coupon.get("item_dish_id")
            for item in order.get("items", []):
                if item.get("dish_id") == item_dish_id:
                    discount_fen = item.get("price_fen", 0) * item.get("quantity", 1)
                    break

        elif ct == CouponType.UPGRADE.value:
            # 加价换购：原价 - 换购价
            item_dish_id = coupon.get("item_dish_id")
            upgrade_price = coupon.get("upgrade_price_fen", 0)
            for item in order.get("items", []):
                if item.get("dish_id") == item_dish_id:
                    original = item.get("price_fen", 0)
                    if original > upgrade_price:
                        discount_fen = original - upgrade_price
                    break

        elif ct == CouponType.BUY_GIFT.value:
            # 买赠：赠品免费
            gift_dish_id = coupon.get("gift_dish_id")
            gift_count = coupon.get("gift_count", 1)
            for item in order.get("items", []):
                if item.get("dish_id") == gift_dish_id:
                    discount_fen = item.get("price_fen", 0) * min(gift_count, item.get("quantity", 1))
                    break

        elif ct == CouponType.GIFT.value:
            # 礼品券：面值直扣
            face = coupon.get("face_value_fen", 0)
            discount_fen = min(face, remaining_fen)

        elif ct == CouponType.DELIVERY.value:
            # 配送券：减配送费
            face = coupon.get("face_value_fen", 0)
            discount_fen = min(face, delivery_fee_fen)

        discount_fen = max(0, discount_fen)
        remaining_fen = max(0, remaining_fen - discount_fen)
        total_discount_fen += discount_fen

        details.append({
            "code": coupon.get("code"),
            "coupon_type": ct,
            "discount_fen": discount_fen,
        })

    logger.info(
        "discount_calculated",
        order_id=order.get("order_id"),
        total_discount_fen=total_discount_fen,
        remaining_fen=remaining_fen,
        tenant_id=tenant_id,
    )
    return {
        "order_id": order.get("order_id"),
        "original_total_fen": total_fen,
        "total_discount_fen": total_discount_fen,
        "final_amount_fen": remaining_fen,
        "details": details,
    }


# ─── 收入规则 ───


async def set_revenue_rule(
    coupon_id: str,
    config: dict,
    tenant_id: str,
    db=None,
) -> dict:
    """设置券是否记收入

    config: {"count_as_revenue": bool, "revenue_ratio": float (0-1)}
    """
    template = _CouponTemplateStore.get(coupon_id)
    if not template:
        raise ValueError(f"券模板不存在: {coupon_id}")
    if template["tenant_id"] != tenant_id:
        raise ValueError("租户不匹配")

    rule = {
        "coupon_id": coupon_id,
        "tenant_id": tenant_id,
        "count_as_revenue": config.get("count_as_revenue", False),
        "revenue_ratio": config.get("revenue_ratio", 0.0),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _RevenueRuleStore.save(coupon_id, rule)

    logger.info(
        "revenue_rule_set",
        coupon_id=coupon_id,
        count_as_revenue=rule["count_as_revenue"],
        revenue_ratio=rule["revenue_ratio"],
        tenant_id=tenant_id,
    )
    return rule


# ─── 券统计 ───


async def get_coupon_stats(
    tenant_id: str,
    date_range: tuple[str, str],
    db=None,
) -> dict:
    """券统计（发放/核销/过期/成本）"""
    from datetime import date as date_cls

    start = date_cls.fromisoformat(date_range[0])
    end = date_cls.fromisoformat(date_range[1])

    instances = _CouponInstanceStore.list_by_tenant(tenant_id)

    total_issued = 0
    total_redeemed = 0
    total_expired = 0
    total_cost_fen = 0
    by_type: dict[str, dict] = {}

    for inst in instances:
        issued_at = inst.get("issued_at")
        if not issued_at:
            continue
        issued_date = datetime.fromisoformat(issued_at).date()
        if not (start <= issued_date <= end):
            continue

        ct = inst.get("coupon_type", "unknown")
        if ct not in by_type:
            by_type[ct] = {"issued": 0, "redeemed": 0, "expired": 0, "cost_fen": 0}

        total_issued += 1
        by_type[ct]["issued"] += 1

        status = inst.get("status")
        if status == "redeemed":
            total_redeemed += 1
            by_type[ct]["redeemed"] += 1
            cost = inst.get("face_value_fen", 0)
            total_cost_fen += cost
            by_type[ct]["cost_fen"] += cost
        elif status == "expired":
            total_expired += 1
            by_type[ct]["expired"] += 1

    redemption_rate = (total_redeemed / total_issued * 100) if total_issued > 0 else 0.0

    logger.info(
        "coupon_stats_queried",
        tenant_id=tenant_id,
        date_range=date_range,
        total_issued=total_issued,
        total_redeemed=total_redeemed,
        redemption_rate=round(redemption_rate, 2),
    )
    return {
        "tenant_id": tenant_id,
        "date_range": {"start": date_range[0], "end": date_range[1]},
        "total_issued": total_issued,
        "total_redeemed": total_redeemed,
        "total_expired": total_expired,
        "total_cost_fen": total_cost_fen,
        "redemption_rate": round(redemption_rate, 2),
        "by_type": by_type,
    }
