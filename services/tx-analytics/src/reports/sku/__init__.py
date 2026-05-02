"""固定报表SKU模板 — BI-1.5，补充传统餐饮客户200+固定表样需求

按业务域组织：sales / dish / member / supply / finance / hr
每个模板是一个函数，返回 {sku_id, name, description, domain, columns, sql, default_params}
"""

from __future__ import annotations

from typing import Any

from .sales_sku import SALES_SKUS
from .dish_sku import DISH_SKUS
from .member_sku import MEMBER_SKUS
from .supply_sku import SUPPLY_SKUS
from .finance_sku import FINANCE_SKUS
from .hr_sku import HR_SKUS

ALL_SKUS: dict[str, list[dict[str, Any]]] = {
    "sales": SALES_SKUS,
    "dish": DISH_SKUS,
    "member": MEMBER_SKUS,
    "supply": SUPPLY_SKUS,
    "finance": FINANCE_SKUS,
    "hr": HR_SKUS,
}

TOTAL_COUNT = sum(len(skus) for skus in ALL_SKUS.values())


def get_sku(domain: str, sku_id: str) -> dict[str, Any] | None:
    """获取单个SKU模板"""
    for sku in ALL_SKUS.get(domain, []):
        if sku["sku_id"] == sku_id:
            return sku
    return None


def list_skus(domain: str | None = None) -> list[dict[str, Any]]:
    """列出所有SKU（可按域筛选）"""
    if domain:
        return ALL_SKUS.get(domain, [])
    result: list[dict[str, Any]] = []
    for skus in ALL_SKUS.values():
        result.extend(skus)
    return result


def search_skus(keyword: str) -> list[dict[str, Any]]:
    """按关键词搜索SKU"""
    kw = keyword.lower()
    return [
        s for s in list_skus()
        if kw in s["name"].lower() or kw in s.get("description", "").lower()
    ]
