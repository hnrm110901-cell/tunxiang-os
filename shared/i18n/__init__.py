"""屯象OS 多语言支持（i18n）

语言切换器 — 根据 lang 参数加载对应语言模块。
默认语言: zh_CN（简体中文）
支持: zh_CN, en_US, ja_JP, ko_KR
"""
from typing import Any

from . import zh_CN, en_US, ja_JP, ko_KR

# 语言注册表
_LANGUAGES: dict[str, Any] = {
    "zh_CN": zh_CN,
    "en_US": en_US,
    "ja_JP": ja_JP,
    "ko_KR": ko_KR,
}

DEFAULT_LANG = "zh_CN"


def get_lang_module(lang: str = DEFAULT_LANG) -> Any:
    """获取语言模块"""
    return _LANGUAGES.get(lang, _LANGUAGES[DEFAULT_LANG])


def get_supported_languages() -> list[dict[str, str]]:
    """获取支持的语言列表"""
    return [
        {"code": mod.LANG_CODE, "name": mod.LANG_NAME}
        for mod in _LANGUAGES.values()
    ]


def get_text(key: str, section: str = "UI", lang: str = DEFAULT_LANG) -> str:
    """获取翻译文本

    Args:
        key: 文本键名
        section: 文本分区 (UI / CATEGORIES / DISH_NAMES / RECEIPT)
        lang: 语言代码
    Returns:
        翻译后的文本，找不到则返回 key 本身
    """
    mod = get_lang_module(lang)
    mapping = getattr(mod, section, {})
    return mapping.get(key, key)
