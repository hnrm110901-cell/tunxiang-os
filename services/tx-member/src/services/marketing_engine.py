"""营销方案计算引擎 — 纯函数，无 DB 依赖

支持 7 种方案类型：
  special_price    特价优惠
  buy_gift         买赠优惠（买N赠M）
  add_on           加价换购
  rebuy            再买优惠（第二份半价等）
  member           会员优惠
  order_discount   订单折扣（整单打折）
  threshold        满减优惠

金额单位：分(fen)
"""

from typing import Any

SCHEME_TYPES = [
    "special_price",
    "buy_gift",
    "add_on",
    "rebuy",
    "member",
    "order_discount",
    "threshold",
]


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _items_total_fen(items: list[dict]) -> int:
    """计算 items 列表的总金额（分）"""
    return sum(it["price_fen"] * it.get("quantity", 1) for it in items)


def _empty_result() -> dict:
    return {"discount_fen": 0, "details": [], "applied_schemes": []}


# ---------------------------------------------------------------------------
# 1. 特价优惠
# ---------------------------------------------------------------------------


def calculate_special_price(items: list[dict], rules: dict) -> dict:
    """特价优惠：指定菜品以特价出售。

    rules 格式:
        {
            "dish_prices": {
                "d1": 5800,   # dish_id -> 特价(分)
                "d2": 3900,
            }
        }
    """
    discount_fen = 0
    details: list[dict] = []
    dish_prices: dict[str, int] = rules.get("dish_prices", {})

    for item in items:
        did = item["dish_id"]
        if did in dish_prices:
            special = dish_prices[did]
            qty = item.get("quantity", 1)
            saved = (item["price_fen"] - special) * qty
            if saved > 0:
                discount_fen += saved
                details.append(
                    {
                        "dish_id": did,
                        "name": item.get("name", ""),
                        "original_fen": item["price_fen"],
                        "special_fen": special,
                        "quantity": qty,
                        "saved_fen": saved,
                    }
                )

    return {
        "discount_fen": discount_fen,
        "details": details,
        "applied_schemes": ["special_price"] if discount_fen > 0 else [],
    }


# ---------------------------------------------------------------------------
# 2. 买赠优惠（买N赠M）
# ---------------------------------------------------------------------------


def calculate_buy_gift(items: list[dict], rules: dict) -> dict:
    """买赠优惠。

    rules 格式:
        {
            "buy_dish_id": "d1",
            "buy_count": 2,
            "gift_dish_id": "d_gift",
            "gift_count": 1,
            "gift_price_fen": 2800,   # 赠品原价，用于计算优惠金额
        }
    """
    buy_dish_id: str = rules["buy_dish_id"]
    buy_count: int = rules["buy_count"]
    gift_count: int = rules.get("gift_count", 1)
    gift_price_fen: int = rules.get("gift_price_fen", 0)

    total_buy_qty = sum(it.get("quantity", 1) for it in items if it["dish_id"] == buy_dish_id)

    times = total_buy_qty // buy_count  # 满足几次
    if times <= 0:
        return _empty_result()

    gifted = times * gift_count
    discount_fen = gifted * gift_price_fen

    return {
        "discount_fen": discount_fen,
        "details": [
            {
                "type": "buy_gift",
                "buy_dish_id": buy_dish_id,
                "buy_count": buy_count,
                "times": times,
                "gifted_count": gifted,
                "gift_dish_id": rules.get("gift_dish_id", ""),
                "saved_fen": discount_fen,
            }
        ],
        "applied_schemes": ["buy_gift"] if discount_fen > 0 else [],
    }


# ---------------------------------------------------------------------------
# 3. 加价换购
# ---------------------------------------------------------------------------


def calculate_add_on(items: list[dict], rules: dict) -> dict:
    """加价换购：订单满足条件后，可低价换购指定商品。

    rules 格式:
        {
            "min_order_fen": 10000,    # 订单需满多少分
            "add_on_dish_id": "d_x",
            "add_on_price_fen": 100,   # 换购价（分）
            "original_price_fen": 1800, # 原价（分）
            "max_count": 1,            # 最多换购数量
        }
    """
    order_total = _items_total_fen(items)
    min_order = rules.get("min_order_fen", 0)
    if order_total < min_order:
        return _empty_result()

    original = rules.get("original_price_fen", 0)
    add_on_price = rules.get("add_on_price_fen", 0)
    max_count = rules.get("max_count", 1)
    saved_per = original - add_on_price
    if saved_per <= 0:
        return _empty_result()

    discount_fen = saved_per * max_count
    return {
        "discount_fen": discount_fen,
        "details": [
            {
                "type": "add_on",
                "add_on_dish_id": rules.get("add_on_dish_id", ""),
                "add_on_price_fen": add_on_price,
                "original_price_fen": original,
                "count": max_count,
                "saved_fen": discount_fen,
            }
        ],
        "applied_schemes": ["add_on"],
    }


# ---------------------------------------------------------------------------
# 4. 再买优惠（第二份半价等）
# ---------------------------------------------------------------------------


def calculate_rebuy(items: list[dict], rules: dict) -> dict:
    """再买优惠：同一菜品第 N 份享折扣。

    rules 格式:
        {
            "dish_id": "d1",
            "nth": 2,                # 第几份享优惠（默认2=第二份）
            "discount_rate": 50,     # 折扣百分比，50表示半价
        }
    """
    dish_id: str = rules["dish_id"]
    nth: int = rules.get("nth", 2)
    discount_rate: int = rules.get("discount_rate", 50)

    matched = [it for it in items if it["dish_id"] == dish_id]
    if not matched:
        return _empty_result()

    total_qty = sum(it.get("quantity", 1) for it in matched)
    if total_qty < nth:
        return _empty_result()

    price_fen = matched[0]["price_fen"]
    # 每达到 nth 份，第 nth 份享折扣
    discounted_count = total_qty // nth
    saved_per = price_fen - (price_fen * discount_rate // 100)
    discount_fen = saved_per * discounted_count

    return {
        "discount_fen": discount_fen,
        "details": [
            {
                "type": "rebuy",
                "dish_id": dish_id,
                "nth": nth,
                "discount_rate": discount_rate,
                "discounted_count": discounted_count,
                "saved_fen": discount_fen,
            }
        ],
        "applied_schemes": ["rebuy"] if discount_fen > 0 else [],
    }


# ---------------------------------------------------------------------------
# 5. 会员优惠
# ---------------------------------------------------------------------------


def calculate_member_discount(
    items: list[dict],
    member_level: str | None,
    rules: dict,
) -> dict:
    """会员等级折扣：不同等级享不同折扣率。

    rules 格式:
        {
            "level_discounts": {
                "silver": 95,   # 95折
                "gold": 90,
                "diamond": 85,
            }
        }
    """
    if not member_level:
        return _empty_result()

    level_discounts: dict[str, int] = rules.get("level_discounts", {})
    rate = level_discounts.get(member_level)
    if rate is None or rate >= 100:
        return _empty_result()

    order_total = _items_total_fen(items)
    discounted_total = order_total * rate // 100
    discount_fen = order_total - discounted_total

    return {
        "discount_fen": discount_fen,
        "details": [
            {
                "type": "member",
                "member_level": member_level,
                "rate": rate,
                "original_total_fen": order_total,
                "discounted_total_fen": discounted_total,
                "saved_fen": discount_fen,
            }
        ],
        "applied_schemes": ["member"] if discount_fen > 0 else [],
    }


# ---------------------------------------------------------------------------
# 6. 订单折扣（整单打折）
# ---------------------------------------------------------------------------


def calculate_order_discount(order_total_fen: int, rules: dict) -> dict:
    """整单打折。

    rules 格式:
        {
            "discount_rate": 88,   # 88折
        }
    """
    rate: int = rules.get("discount_rate", 100)
    if rate >= 100:
        return _empty_result()

    discounted = order_total_fen * rate // 100
    discount_fen = order_total_fen - discounted

    return {
        "discount_fen": discount_fen,
        "details": [
            {
                "type": "order_discount",
                "rate": rate,
                "original_fen": order_total_fen,
                "discounted_fen": discounted,
                "saved_fen": discount_fen,
            }
        ],
        "applied_schemes": ["order_discount"] if discount_fen > 0 else [],
    }


# ---------------------------------------------------------------------------
# 7. 满减优惠
# ---------------------------------------------------------------------------


def calculate_threshold(order_total_fen: int, rules: dict) -> dict:
    """满减优惠：达到门槛后减免固定金额。

    rules 格式:
        {
            "tiers": [
                {"threshold_fen": 10000, "reduce_fen": 500},
                {"threshold_fen": 20000, "reduce_fen": 1500},
                {"threshold_fen": 30000, "reduce_fen": 3000},
            ]
        }
    按最高匹配门槛执行。
    """
    tiers: list[dict] = rules.get("tiers", [])
    if not tiers:
        return _empty_result()

    # 按门槛从高到低排序，取第一个匹配
    sorted_tiers = sorted(tiers, key=lambda t: t["threshold_fen"], reverse=True)
    for tier in sorted_tiers:
        if order_total_fen >= tier["threshold_fen"]:
            reduce = tier["reduce_fen"]
            return {
                "discount_fen": reduce,
                "details": [
                    {
                        "type": "threshold",
                        "threshold_fen": tier["threshold_fen"],
                        "reduce_fen": reduce,
                        "order_total_fen": order_total_fen,
                    }
                ],
                "applied_schemes": ["threshold"],
            }

    return _empty_result()


# ---------------------------------------------------------------------------
# 互斥规则检查
# ---------------------------------------------------------------------------


def check_exclusion(
    scheme_a: str,
    scheme_b: str,
    exclusion_rules: list[tuple[str, str]] | list[list[str]],
) -> bool:
    """检查两个方案是否互斥。

    exclusion_rules: [("special_price", "order_discount"), ...]
    返回 True 表示互斥，不可同时使用。
    """
    for rule in exclusion_rules:
        pair = set(rule)
        if {scheme_a, scheme_b} == pair:
            return True
    return False


# ---------------------------------------------------------------------------
# 计算函数分派表
# ---------------------------------------------------------------------------

_CALCULATORS: dict[str, Any] = {
    "special_price": lambda items, order_total, rules, ml: calculate_special_price(items, rules),
    "buy_gift": lambda items, order_total, rules, ml: calculate_buy_gift(items, rules),
    "add_on": lambda items, order_total, rules, ml: calculate_add_on(items, rules),
    "rebuy": lambda items, order_total, rules, ml: calculate_rebuy(items, rules),
    "member": lambda items, order_total, rules, ml: calculate_member_discount(items, ml, rules),
    "order_discount": lambda items, order_total, rules, ml: calculate_order_discount(order_total, rules),
    "threshold": lambda items, order_total, rules, ml: calculate_threshold(order_total, rules),
}


# ---------------------------------------------------------------------------
# 执行顺序引擎
# ---------------------------------------------------------------------------


def apply_schemes_in_order(
    items: list[dict],
    order_total_fen: int,
    schemes: list[dict],
    member_level: str | None = None,
) -> dict:
    """按优先级依次计算方案，考虑互斥规则。

    schemes 格式:
        [
            {
                "scheme_type": "special_price",
                "priority": 1,         # 数字越小优先级越高
                "rules": { ... },
                "exclusion_rules": [("special_price", "order_discount")],
            },
            ...
        ]

    返回:
        {
            "original_total_fen": 原价,
            "total_discount_fen": 总优惠,
            "final_total_fen": 最终价,
            "applied_schemes": [已应用的方案类型列表],
            "details": [每个方案的明细],
            "skipped_schemes": [因互斥被跳过的方案],
        }
    """
    # 按 priority 排序（升序=高优先级先执行）
    sorted_schemes = sorted(schemes, key=lambda s: s.get("priority", 99))

    applied: list[str] = []
    all_details: list[dict] = []
    total_discount = 0
    skipped: list[dict] = []

    for scheme in sorted_schemes:
        stype = scheme["scheme_type"]
        rules = scheme.get("rules", {})
        excl = scheme.get("exclusion_rules", [])

        # 互斥检查：如果与任何已应用方案互斥，则跳过
        excluded = False
        for applied_type in applied:
            if check_exclusion(stype, applied_type, excl):
                excluded = True
                skipped.append(
                    {
                        "scheme_type": stype,
                        "reason": f"与已应用的 {applied_type} 互斥",
                    }
                )
                break

        if excluded:
            continue

        calculator = _CALCULATORS.get(stype)
        if calculator is None:
            continue

        result = calculator(items, order_total_fen, rules, member_level)
        if result["discount_fen"] > 0:
            total_discount += result["discount_fen"]
            applied.extend(result["applied_schemes"])
            all_details.extend(result["details"])

    original = order_total_fen if order_total_fen > 0 else _items_total_fen(items)
    final = max(original - total_discount, 0)

    return {
        "original_total_fen": original,
        "total_discount_fen": total_discount,
        "final_total_fen": final,
        "applied_schemes": applied,
        "details": all_details,
        "skipped_schemes": skipped,
    }
