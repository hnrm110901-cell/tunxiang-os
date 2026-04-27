"""SQLAlchemy 透明加密列类型 — 等保三级合规

用法 (在 Entity 模型中):
    from shared.security.src.encrypted_type import EncryptedString

    class Customer(Base):
        phone = Column(EncryptedString(100))  # 存储时自动加密，读取时自动解密
        id_card = Column(EncryptedString(200))
        bank_account = Column(EncryptedString(200))

注意:
    - 加密后的密文长度约为原文长度的 2-3 倍，建议 length 设大一些
    - 底层存储为 VARCHAR(length)，存的是 "ENC:base64..." 字符串
    - 查询时不支持 LIKE / = 等操作（密文不可比较），需要模糊搜索请配合
      明文辅助列（如 phone_last4）
"""

from __future__ import annotations

from typing import Optional

import sqlalchemy as sa
from sqlalchemy import String
from sqlalchemy.engine import Dialect

from .field_encryption import get_encryptor


class EncryptedString(sa.types.TypeDecorator):
    """透明加密/解密的 SQLAlchemy 列类型。

    写入 DB 时自动调用 FieldEncryptor.encrypt()。
    从 DB 读取时自动调用 FieldEncryptor.decrypt()。
    """

    impl = String
    cache_ok = True

    def __init__(self, length: int = 512, **kwargs: object) -> None:
        super().__init__(length=length, **kwargs)

    def process_bind_param(self, value: Optional[str], dialect: Dialect) -> Optional[str]:
        """写入 DB 前加密。"""
        if value is None:
            return None
        encryptor = get_encryptor()
        if not encryptor.is_configured:
            # 密钥未配置时直接存明文（开发环境 / 迁移期兼容）
            return value
        return encryptor.encrypt(value)

    def process_result_value(self, value: Optional[str], dialect: Dialect) -> Optional[str]:
        """从 DB 读取后解密。"""
        if value is None:
            return None
        encryptor = get_encryptor()
        if not encryptor.is_configured:
            return value
        return encryptor.decrypt(value)
