"""
业态模板注册表 — 通过 RestaurantType 枚举获取对应模板实例。
"""

from .base import BaseTemplate, RestaurantType
from .templates import (
    BanquetTemplate,
    CafeTeaTemplate,
    CasualDiningTemplate,
    FastFoodTemplate,
    HotPotTemplate,
)

_REGISTRY: dict[RestaurantType, BaseTemplate] = {
    RestaurantType.CASUAL_DINING: CasualDiningTemplate(),
    RestaurantType.HOT_POT: HotPotTemplate(),
    RestaurantType.FAST_FOOD: FastFoodTemplate(),
    RestaurantType.BANQUET: BanquetTemplate(),
    RestaurantType.CAFE_TEA: CafeTeaTemplate(),
}


def get_template(restaurant_type: RestaurantType) -> BaseTemplate:
    """返回指定业态的模板实例。"""
    tpl = _REGISTRY.get(restaurant_type)
    if tpl is None:
        raise ValueError(f"未知业态类型: {restaurant_type}")
    return tpl


def list_templates() -> list[dict]:
    """返回所有可用模板的元信息列表（供前端展示业态选择器）。"""
    return [
        {
            "type": tpl.restaurant_type.value,
            "display_name": tpl.display_name,
            "description": tpl.description,
        }
        for tpl in _REGISTRY.values()
    ]
