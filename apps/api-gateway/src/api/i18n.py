"""
i18n API 路由 — 前端拉取翻译 / 管理端编辑
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.middleware.locale_middleware import DEFAULT_LOCALE, SUPPORTED_LOCALES
from src.models.i18n import I18nTextKey, I18nTranslation, Locale
from src.services.i18n_service import I18nService, clear_i18n_cache

router = APIRouter(prefix="/api/v1/i18n", tags=["i18n"])


class TranslationOut(BaseModel):
    namespace: str
    key: str
    value: str


class RegisterTextIn(BaseModel):
    namespace: str
    key: str
    zh_value: str
    description: Optional[str] = None


class UpsertTranslationIn(BaseModel):
    text_key_id: str
    locale_code: str
    translated_value: str
    reviewed: bool = True


@router.get("/locales")
async def list_locales(db: AsyncSession = Depends(get_db)) -> List[Dict[str, Any]]:
    """列出所有支持的语种（供前端 LanguageSwitcher）"""
    rows = (await db.execute(select(Locale).where(Locale.is_active.is_(True)))).scalars().all()
    if rows:
        return [
            {
                "code": r.code,
                "name": r.name,
                "flag_emoji": r.flag_emoji,
                "is_default": r.is_default,
            }
            for r in rows
        ]
    # 表为空时返回硬编码兜底
    return [
        {"code": "zh-CN", "name": "简体中文", "flag_emoji": "🇨🇳", "is_default": True},
        {"code": "zh-TW", "name": "繁體中文", "flag_emoji": "🇭🇰", "is_default": False},
        {"code": "en-US", "name": "English", "flag_emoji": "🇺🇸", "is_default": False},
        {"code": "vi-VN", "name": "Tiếng Việt", "flag_emoji": "🇻🇳", "is_default": False},
        {"code": "th-TH", "name": "ภาษาไทย", "flag_emoji": "🇹🇭", "is_default": False},
        {"code": "id-ID", "name": "Bahasa Indonesia", "flag_emoji": "🇮🇩", "is_default": False},
    ]


@router.get("/translations")
async def get_translations(
    request: Request,
    locale: Optional[str] = None,
    namespace: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Dict[str, str]]:
    """
    拉取某语种的全部翻译，返回 { namespace: { key: value } }
    前端在应用启动时调用一次，缓存到 localStorage。
    """
    loc = locale or getattr(request.state, "locale", None) or DEFAULT_LOCALE
    if loc not in SUPPORTED_LOCALES:
        raise HTTPException(status_code=400, detail=f"unsupported locale: {loc}")

    stmt = select(I18nTextKey, I18nTranslation).outerjoin(
        I18nTranslation,
        (I18nTranslation.text_key_id == I18nTextKey.id)
        & (I18nTranslation.locale_code == loc),
    )
    if namespace:
        stmt = stmt.where(I18nTextKey.namespace == namespace)

    result: Dict[str, Dict[str, str]] = {}
    for tk, tr in (await db.execute(stmt)).all():
        value = tr.translated_value if tr and tr.translated_value else tk.default_value_zh
        result.setdefault(tk.namespace, {})[tk.key] = value
    return result


@router.post("/text-keys")
async def register_text_key(
    payload: RegisterTextIn, db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """注册新文案 key（管理端）"""
    svc = I18nService(db)
    tk = await svc.register_text(
        payload.namespace, payload.key, payload.zh_value, payload.description
    )
    await db.commit()
    return {"id": str(tk.id), "namespace": tk.namespace, "key": tk.key}


@router.put("/translations")
async def upsert_translation(
    payload: UpsertTranslationIn, db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """人工审核/编辑翻译"""
    if payload.locale_code not in SUPPORTED_LOCALES:
        raise HTTPException(status_code=400, detail="unsupported locale")
    stmt = select(I18nTranslation).where(
        I18nTranslation.text_key_id == payload.text_key_id,
        I18nTranslation.locale_code == payload.locale_code,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        existing.translated_value = payload.translated_value
        existing.reviewed = payload.reviewed
        existing.translator = "human"
    else:
        db.add(
            I18nTranslation(
                text_key_id=payload.text_key_id,
                locale_code=payload.locale_code,
                translated_value=payload.translated_value,
                reviewed=payload.reviewed,
                translator="human",
            )
        )
    await db.commit()
    clear_i18n_cache()
    return {"ok": True}


@router.post("/auto-translate")
async def auto_translate(
    locale: str,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """对缺失翻译的 key 调用 LLM 批量翻译（AI 生成，等待人工审核）"""
    if locale not in SUPPORTED_LOCALES:
        raise HTTPException(status_code=400, detail="unsupported locale")
    svc = I18nService(db)
    count = await svc.auto_translate_missing(locale, limit=limit)
    await db.commit()
    return {"created": count, "locale": locale}
