"""
i18n 多语言基础模型（v3.3 出海）

- Locale：支持的语种
- I18nTextKey：文案 key（带命名空间）
- I18nTranslation：具体翻译（按 locale）
"""

import uuid

from sqlalchemy import Boolean, Column, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from .base import Base, TimestampMixin


class Locale(Base, TimestampMixin):
    """支持的语种配置表"""

    __tablename__ = "locales"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(10), unique=True, nullable=False, index=True)  # zh-CN / zh-TW / en-US / vi-VN / th-TH / id-ID
    name = Column(String(50), nullable=False)  # 简体中文 / English ...
    is_active = Column(Boolean, default=True, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)
    flag_emoji = Column(String(10), nullable=True)  # 🇨🇳 🇭🇰 🇺🇸 🇻🇳 🇹🇭 🇮🇩


class I18nTextKey(Base, TimestampMixin):
    """文案 key 注册表"""

    __tablename__ = "i18n_text_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    namespace = Column(String(50), nullable=False, index=True)  # common / hr / finance / payroll / ...
    key = Column(String(200), nullable=False, index=True)  # save / employee / amount
    default_value_zh = Column(Text, nullable=False)  # 默认中文 fallback
    description = Column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("namespace", "key", name="uq_i18n_namespace_key"),)


class I18nTranslation(Base, TimestampMixin):
    """具体翻译（每个 key × locale 一行）"""

    __tablename__ = "i18n_translations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    text_key_id = Column(
        UUID(as_uuid=True),
        ForeignKey("i18n_text_keys.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    locale_code = Column(String(10), nullable=False, index=True)
    translated_value = Column(Text, nullable=False)
    translator = Column(String(20), default="human", nullable=False)  # human / ai
    reviewed = Column(Boolean, default=False, nullable=False)

    __table_args__ = (
        UniqueConstraint("text_key_id", "locale_code", name="uq_i18n_translation_key_locale"),
    )
