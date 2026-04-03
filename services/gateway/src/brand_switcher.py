"""多品牌切换 — 集团化核心能力

支持集团下多品牌管理，品牌切换时菜单/门店/会员数据联动。
积分可跨品牌通用。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# ── 内存存储 ──────────────────────────────────────────────────

_brands: dict[str, dict] = {}  # brand_id -> brand
_customer_brand_ctx: dict[str, dict] = {}  # customer_id -> {current_brand_id, ...}
_cross_brand_benefits: dict[str, list[dict]] = {}  # tenant_id -> [benefit_rule]


# ── 工具函数 ──────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ── 服务函数 ──────────────────────────────────────────────────


async def list_brands(
    tenant_id: str,
    db: Any = None,
) -> dict[str, Any]:
    """获取集团下所有品牌

    Args:
        tenant_id: 租户ID（集团级）
        db: 数据库会话

    Returns:
        {"tenant_id", "brands", "total"}
    """
    brands = [
        b for b in _brands.values()
        if b.get("tenant_id") == tenant_id and not b.get("is_deleted", False)
    ]
    brands.sort(key=lambda b: b.get("sort_order", 0))

    brand_list = []
    for b in brands:
        brand_list.append({
            "brand_id": b["brand_id"],
            "name": b["name"],
            "logo_url": b.get("logo_url", ""),
            "theme_color": b.get("theme_color", "#FF6B2C"),
            "business_type": b.get("business_type", ""),
            "store_count": b.get("store_count", 0),
            "status": b.get("status", "active"),
        })

    logger.info(
        "brand.list",
        tenant_id=tenant_id,
        count=len(brand_list),
    )

    return {
        "tenant_id": tenant_id,
        "brands": brand_list,
        "total": len(brand_list),
    }


async def switch_brand(
    customer_id: str,
    brand_id: str,
    tenant_id: str,
    db: Any = None,
) -> dict[str, Any]:
    """切换品牌（菜单/门店/会员数据联动）

    Args:
        customer_id: 客户ID
        brand_id: 目标品牌ID
        tenant_id: 租户ID
        db: 数据库会话

    Returns:
        {"customer_id", "brand_id", "brand_name", "menu_switched",
         "stores_switched", "member_data_loaded"}
    """
    brand = _brands.get(brand_id)
    if not brand:
        raise ValueError(f"brand_not_found:{brand_id}")
    if brand.get("tenant_id") != tenant_id:
        raise ValueError("tenant_mismatch")
    if brand.get("is_deleted", False):
        raise ValueError("brand_deleted")
    if brand.get("status") != "active":
        raise ValueError(f"brand_not_active:{brand.get('status')}")

    now = _now_utc()

    # 记录切换上下文
    prev_ctx = _customer_brand_ctx.get(customer_id, {})
    prev_brand_id = prev_ctx.get("current_brand_id")

    _customer_brand_ctx[customer_id] = {
        "current_brand_id": brand_id,
        "tenant_id": tenant_id,
        "switched_at": now.isoformat(),
        "previous_brand_id": prev_brand_id,
    }

    # 联动数据准备（实际会查询各域服务）
    menu_config = brand.get("menu_config", {})
    stores = brand.get("stores", [])
    member_data = {
        "points_shared": brand.get("points_shared", True),
        "coupons_shared": brand.get("coupons_shared", False),
    }

    logger.info(
        "brand.switched",
        customer_id=customer_id,
        brand_id=brand_id,
        brand_name=brand["name"],
        previous_brand_id=prev_brand_id,
        tenant_id=tenant_id,
    )

    return {
        "customer_id": customer_id,
        "brand_id": brand_id,
        "brand_name": brand["name"],
        "logo_url": brand.get("logo_url", ""),
        "theme_color": brand.get("theme_color", "#FF6B2C"),
        "menu_switched": True,
        "stores_switched": True,
        "member_data_loaded": True,
        "store_count": len(stores),
        "points_shared": member_data["points_shared"],
        "coupons_shared": member_data["coupons_shared"],
        "switched_at": now.isoformat(),
    }


async def get_cross_brand_benefits(
    customer_id: str,
    tenant_id: str,
    db: Any = None,
) -> dict[str, Any]:
    """获取跨品牌权益（通用积分/通用券）

    Args:
        customer_id: 客户ID
        tenant_id: 租户ID
        db: 数据库会话

    Returns:
        {"customer_id", "shared_points", "shared_coupons",
         "brand_specific_benefits", "cross_brand_rules"}
    """
    # 获取集团所有品牌
    brands_result = await list_brands(tenant_id, db)
    brands = brands_result.get("brands", [])

    # 跨品牌权益规则
    rules = _cross_brand_benefits.get(tenant_id, [])

    # 模拟积分汇总（实际从各品牌数据库聚合）
    shared_points = 0
    brand_points: dict[str, int] = {}
    for b in brands:
        brand_id = b["brand_id"]
        brand_data = _brands.get(brand_id, {})
        pts = brand_data.get("customer_points", {}).get(customer_id, 0)
        brand_points[brand_id] = pts
        if brand_data.get("points_shared", True):
            shared_points += pts

    # 通用券
    shared_coupons: list[dict] = []
    brand_coupons: dict[str, list[dict]] = {}
    for b in brands:
        brand_id = b["brand_id"]
        brand_data = _brands.get(brand_id, {})
        coupons = brand_data.get("customer_coupons", {}).get(customer_id, [])
        brand_coupons[brand_id] = coupons
        if brand_data.get("coupons_shared", False):
            shared_coupons.extend(coupons)

    # 各品牌专属权益
    brand_specific = []
    for b in brands:
        brand_id = b["brand_id"]
        brand_data = _brands.get(brand_id, {})
        specific_benefits = brand_data.get("specific_benefits", [])
        if specific_benefits:
            brand_specific.append({
                "brand_id": brand_id,
                "brand_name": b["name"],
                "benefits": specific_benefits,
            })

    logger.info(
        "brand.cross_benefits",
        customer_id=customer_id,
        shared_points=shared_points,
        shared_coupons_count=len(shared_coupons),
        brand_count=len(brands),
        tenant_id=tenant_id,
    )

    return {
        "customer_id": customer_id,
        "shared_points": shared_points,
        "shared_coupons": shared_coupons,
        "brand_points": brand_points,
        "brand_specific_benefits": brand_specific,
        "cross_brand_rules": rules,
    }


# ── 数据注入（测试/管理用） ────────────────────────────────────


def register_brand(
    tenant_id: str,
    name: str,
    logo_url: str = "",
    theme_color: str = "#FF6B2C",
    business_type: str = "fine_dining",
    points_shared: bool = True,
    coupons_shared: bool = False,
    sort_order: int = 0,
) -> dict:
    """注册品牌（内部调用）"""
    brand_id = f"brand_{uuid.uuid4().hex[:8]}"
    now = _now_utc()

    brand = {
        "brand_id": brand_id,
        "tenant_id": tenant_id,
        "name": name,
        "logo_url": logo_url,
        "theme_color": theme_color,
        "business_type": business_type,
        "points_shared": points_shared,
        "coupons_shared": coupons_shared,
        "sort_order": sort_order,
        "store_count": 0,
        "stores": [],
        "status": "active",
        "is_deleted": False,
        "menu_config": {},
        "customer_points": {},
        "customer_coupons": {},
        "specific_benefits": [],
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }
    _brands[brand_id] = brand
    return brand


def set_cross_brand_rules(tenant_id: str, rules: list[dict]) -> None:
    """设置跨品牌权益规则"""
    _cross_brand_benefits[tenant_id] = rules


def set_customer_brand_points(brand_id: str, customer_id: str, points: int) -> None:
    """设置客户在某品牌的积分"""
    brand = _brands.get(brand_id)
    if brand:
        brand.setdefault("customer_points", {})[customer_id] = points


def clear_all_brand_data() -> None:
    """清空所有数据 (仅测试用)"""
    _brands.clear()
    _customer_brand_ctx.clear()
    _cross_brand_benefits.clear()
