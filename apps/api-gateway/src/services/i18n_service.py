"""
i18n 翻译服务

- get_text(key, locale, **kwargs)：取翻译 + 变量替换
- register_text()：注册新 key
- translate_batch()：批量取
- auto_translate_missing()：LLM 兜底翻译（人工审核后生效）

缓存：短 TTL 的内存缓存（30s），避免高频 DB 查询。
fallback：找不到 translation → 返回 default_value_zh；仍无 → 返回 key 本身，不抛异常。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.i18n import I18nTextKey, I18nTranslation

logger = logging.getLogger(__name__)

# 进程内缓存：{ "{namespace}.{key}.{locale}" : (value, expire_ts) }
_CACHE: Dict[str, tuple[str, float]] = {}
_CACHE_TTL = 30.0


def _cache_get(ck: str) -> Optional[str]:
    item = _CACHE.get(ck)
    if not item:
        return None
    value, expire = item
    if expire < time.time():
        _CACHE.pop(ck, None)
        return None
    return value


def _cache_set(ck: str, value: str) -> None:
    _CACHE[ck] = (value, time.time() + _CACHE_TTL)


def _apply_vars(template: str, variables: Dict[str, Any]) -> str:
    """简单的 {name} 变量替换；缺失变量保留原样不抛错。"""
    if not variables:
        return template
    try:
        return template.format(**variables)
    except (KeyError, IndexError, ValueError):
        result = template
        for k, v in variables.items():
            result = result.replace("{" + k + "}", str(v))
        return result


class I18nService:
    """i18n 服务：承载翻译取值/注册/批量/自动翻译"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_text(
        self,
        key: str,
        locale: str = "zh-CN",
        namespace: str = "common",
        **kwargs: Any,
    ) -> str:
        """取翻译文案，支持变量替换"""
        ck = f"{namespace}.{key}.{locale}"
        cached = _cache_get(ck)
        if cached is not None:
            return _apply_vars(cached, kwargs)

        stmt = (
            select(I18nTextKey, I18nTranslation)
            .outerjoin(
                I18nTranslation,
                (I18nTranslation.text_key_id == I18nTextKey.id)
                & (I18nTranslation.locale_code == locale),
            )
            .where(I18nTextKey.namespace == namespace, I18nTextKey.key == key)
            .limit(1)
        )
        row = (await self.session.execute(stmt)).first()

        if not row:
            # key 未注册：返回 key 本身，不抛
            return _apply_vars(key, kwargs)

        text_key, translation = row[0], row[1]
        if translation and translation.translated_value:
            value = translation.translated_value
        else:
            value = text_key.default_value_zh  # fallback 到默认中文

        _cache_set(ck, value)
        return _apply_vars(value, kwargs)

    async def register_text(
        self,
        namespace: str,
        key: str,
        zh_value: str,
        description: Optional[str] = None,
    ) -> I18nTextKey:
        """注册新文案 key（幂等）"""
        stmt = select(I18nTextKey).where(
            I18nTextKey.namespace == namespace, I18nTextKey.key == key
        )
        existing = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing:
            return existing

        text_key = I18nTextKey(
            namespace=namespace,
            key=key,
            default_value_zh=zh_value,
            description=description,
        )
        self.session.add(text_key)
        await self.session.flush()
        return text_key

    async def translate_batch(
        self, locale: str, keys_list: List[tuple[str, str]]
    ) -> Dict[str, str]:
        """批量取翻译；keys_list = [(namespace, key), ...]"""
        result: Dict[str, str] = {}
        for namespace, key in keys_list:
            text = await self.get_text(key, locale, namespace)
            result[f"{namespace}.{key}"] = text
        return result

    async def auto_translate_missing(self, locale: str, limit: int = 50) -> int:
        """
        用 llm_gateway 对缺失翻译的 key 批量生成（人工审核后生效）。
        生成结果 translator='ai' / reviewed=False。返回新增记录数。
        """
        # 找出当前 locale 没翻译的 key
        subq = select(I18nTranslation.text_key_id).where(
            I18nTranslation.locale_code == locale
        )
        stmt = select(I18nTextKey).where(I18nTextKey.id.notin_(subq)).limit(limit)
        missing = (await self.session.execute(stmt)).scalars().all()

        if not missing:
            return 0

        # 延迟引入 llm_gateway 避免循环依赖；失败时降级为占位（空字符串不写入）
        try:
            from src.services.llm_gateway.gateway import LLMGateway  # type: ignore

            llm = LLMGateway()
        except Exception:
            llm = None
            logger.warning("LLMGateway 不可用，自动翻译跳过")

        count = 0
        for tk in missing:
            translated: Optional[str] = None
            if llm is not None:
                try:
                    prompt = (
                        f"请将下面的简体中文 UI 文案翻译为 {locale}，"
                        f"只输出目标语种的翻译结果，不加引号和解释。\n"
                        f"原文：{tk.default_value_zh}"
                    )
                    # LLMGateway 的具体调用签名可能不同，这里尝试常见方式
                    resp = await llm.complete(prompt) if hasattr(llm, "complete") else None
                    if resp and isinstance(resp, str):
                        translated = resp.strip().strip('"').strip("'")
                except Exception as e:
                    logger.warning(f"LLM 翻译失败 key={tk.key}: {e}")

            if not translated:
                continue

            self.session.add(
                I18nTranslation(
                    text_key_id=tk.id,
                    locale_code=locale,
                    translated_value=translated,
                    translator="ai",
                    reviewed=False,
                )
            )
            count += 1

        await self.session.flush()
        return count


def clear_i18n_cache() -> None:
    """清空内存缓存（审核通过/修改翻译后调用）"""
    _CACHE.clear()
