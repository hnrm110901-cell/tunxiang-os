"""翻译服务 — 菜单翻译、小票翻译、文本获取

菜品名翻译优先使用 dishes 表 metadata 中的翻译，
找不到时回退到 i18n 语言包中的 DISH_NAMES 映射。
"""
from typing import Any, Optional

import structlog

from . import get_lang_module, get_text, get_supported_languages, DEFAULT_LANG

logger = structlog.get_logger()


def translate_menu(
    dishes: list[dict[str, Any]],
    target_lang: str,
    tenant_id: str,
    db: Optional[Any] = None,
) -> list[dict[str, Any]]:
    """翻译菜单菜品列表

    优先级:
    1. dish.metadata.translations[target_lang] （数据库中的翻译）
    2. i18n 语言包 DISH_NAMES 映射
    3. 保留原始中文名

    Args:
        dishes: 菜品列表，每个含 name, category, description 等
        target_lang: 目标语言代码
        tenant_id: 租户ID
        db: 数据库连接（可选，用于查询 metadata 翻译）
    Returns:
        翻译后的菜品列表
    """
    if target_lang == "zh_CN":
        return dishes

    lang_mod = get_lang_module(target_lang)
    dish_names = getattr(lang_mod, "DISH_NAMES", {})
    categories = getattr(lang_mod, "CATEGORIES", {})

    # 构建中文名→翻译键的反向映射
    zh_mod = get_lang_module("zh_CN")
    zh_dish_names = getattr(zh_mod, "DISH_NAMES", {})
    zh_to_key = {v: k for k, v in zh_dish_names.items()}

    translated: list[dict[str, Any]] = []
    for dish in dishes:
        item = {**dish}
        original_name = dish.get("name", "")

        # 优先: metadata 翻译
        metadata_translations = dish.get("metadata", {}).get("translations", {})
        if target_lang in metadata_translations:
            item["name_translated"] = metadata_translations[target_lang]
        else:
            # 回退: i18n 语言包
            key = zh_to_key.get(original_name, "")
            if key and key in dish_names:
                item["name_translated"] = dish_names[key]
            else:
                item["name_translated"] = original_name  # 保留中文

        item["name_original"] = original_name

        # 翻译分类
        cat_key = dish.get("category_key", "")
        if cat_key and cat_key in categories:
            item["category_translated"] = categories[cat_key]

        translated.append(item)

    logger.info("menu_translated",
                 tenant_id=tenant_id, target_lang=target_lang,
                 dish_count=len(translated))

    return translated


def translate_receipt(
    receipt_data: dict[str, Any],
    target_lang: str,
) -> dict[str, Any]:
    """翻译小票内容

    Args:
        receipt_data: 小票数据 (含 items, total, store_name 等)
        target_lang: 目标语言代码
    Returns:
        翻译后的小票数据
    """
    if target_lang == "zh_CN":
        return receipt_data

    lang_mod = get_lang_module(target_lang)
    receipt_texts = getattr(lang_mod, "RECEIPT", {})

    translated = {**receipt_data}

    # 翻译标签
    translated["labels"] = {
        key: receipt_texts.get(key, key)
        for key in [
            "header", "store_name", "order_no", "table_no", "cashier",
            "time", "item", "qty", "price", "subtotal", "total",
            "discount", "payable", "paid", "change", "payment_method",
            "footer", "vat_note",
        ]
    }

    # 翻译菜品名
    items = receipt_data.get("items", [])
    zh_mod = get_lang_module("zh_CN")
    zh_dish_names = getattr(zh_mod, "DISH_NAMES", {})
    dish_names = getattr(lang_mod, "DISH_NAMES", {})
    zh_to_key = {v: k for k, v in zh_dish_names.items()}

    translated_items = []
    for item in items:
        t_item = {**item}
        original_name = item.get("name", "")
        key = zh_to_key.get(original_name, "")
        if key and key in dish_names:
            t_item["name_translated"] = dish_names[key]
        else:
            t_item["name_translated"] = original_name
        t_item["name_original"] = original_name
        translated_items.append(t_item)

    translated["items"] = translated_items
    translated["target_lang"] = target_lang

    logger.info("receipt_translated", target_lang=target_lang)

    return translated
