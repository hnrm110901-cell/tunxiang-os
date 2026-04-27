"""
AES-256-GCM字段级加密
密钥：TX_FIELD_ENCRYPTION_KEY 环境变量（64位hex字符串=32字节）
格式：enc:v1:<base64(12字节nonce||16字节tag||ciphertext)>
迁移兼容：非enc:v1:前缀的值原样返回（渐进式迁移）
"""

from __future__ import annotations

import base64
import os
from typing import Optional

import structlog
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = structlog.get_logger(__name__)

PREFIX = "enc:v1:"
NONCE_BYTES = 12
KEY_BYTES = 32  # AES-256 = 32字节密钥


class FieldEncryption:
    def __init__(self) -> None:
        hex_key = os.environ.get("TX_FIELD_ENCRYPTION_KEY", "")
        if not hex_key:
            logger.warning("TX_FIELD_ENCRYPTION_KEY未配置，字段加密不可用")
            self._key: Optional[bytes] = None
        else:
            key_bytes = bytes.fromhex(hex_key)
            if len(key_bytes) != KEY_BYTES:
                raise ValueError(f"TX_FIELD_ENCRYPTION_KEY必须为64位hex（32字节），实际为{len(key_bytes)}字节")
            self._key = key_bytes

    def encrypt(self, plaintext: str) -> str:
        """加密字符串，返回 enc:v1:<base64>。已加密则幂等返回。"""
        if self._key is None:
            raise RuntimeError("TX_FIELD_ENCRYPTION_KEY未配置，无法加密")
        if self.is_encrypted(plaintext):
            return plaintext  # 已加密，幂等

        nonce = os.urandom(NONCE_BYTES)
        aesgcm = AESGCM(self._key)
        # encrypt() 返回 ciphertext || 16字节GCM tag（cryptography库已合并）
        ciphertext_with_tag = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        encoded = base64.b64encode(nonce + ciphertext_with_tag).decode("ascii")
        return f"{PREFIX}{encoded}"

    def decrypt(self, value: str) -> str:
        """解密。非enc:v1:前缀原样返回（明文兼容，用于迁移期）。

        Raises:
            RuntimeError: 密钥未配置但需要解密
            InvalidTag: 密文被篡改或密钥不匹配
            ValueError: base64格式错误或数据长度不足
        """
        if not self.is_encrypted(value):
            return value  # 明文兼容，迁移期透传

        if self._key is None:
            raise RuntimeError("TX_FIELD_ENCRYPTION_KEY未配置，无法解密")

        encoded = value[len(PREFIX) :]
        try:
            raw = base64.b64decode(encoded)
        except Exception as exc:
            raise ValueError(f"加密字段base64格式错误: {exc}") from exc

        if len(raw) <= NONCE_BYTES:
            raise ValueError(f"加密字段数据长度不足，期望>{NONCE_BYTES}字节，实际{len(raw)}字节")

        nonce, ciphertext_with_tag = raw[:NONCE_BYTES], raw[NONCE_BYTES:]
        aesgcm = AESGCM(self._key)
        # 可能抛出 cryptography.exceptions.InvalidTag（密文被篡改）
        plaintext_bytes = aesgcm.decrypt(nonce, ciphertext_with_tag, None)
        return plaintext_bytes.decode("utf-8")

    def is_encrypted(self, value: str) -> bool:
        """判断字段是否已被加密。"""
        return isinstance(value, str) and value.startswith(PREFIX)

    def encrypt_phone(self, phone: str) -> tuple[str, str]:
        """加密手机号，返回 (encrypted_full, last4明文)。

        Returns:
            (加密后的完整手机号, 最后4位明文——用于展示和模糊查询)
        """
        last4 = phone[-4:] if len(phone) >= 4 else phone
        return self.encrypt(phone), last4

    def mask_phone(self, phone: str) -> str:
        """138****6789 格式脱敏，用于日志/展示（不解密，直接处理明文手机号）。"""
        if len(phone) == 11:
            return f"{phone[:3]}****{phone[-4:]}"
        return "***"

    def mask_decrypted_phone(self, phone: str) -> str:
        """对已解密手机号脱敏，日志输出专用。"""
        return self.mask_phone(phone) if phone else "***"


# 模块级单例，避免重复读取环境变量
_instance: Optional[FieldEncryption] = None


def get_encryption() -> FieldEncryption:
    """获取全局FieldEncryption单例。"""
    global _instance
    if _instance is None:
        _instance = FieldEncryption()
    return _instance
