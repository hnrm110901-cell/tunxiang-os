"""字段级AES-256-GCM加密 — 等保三级合规

用法:
    encryptor = FieldEncryptor(key=os.environ['TX_FIELD_ENCRYPTION_KEY'])
    encrypted = encryptor.encrypt("13812345678")  # → "ENC:base64..."
    decrypted = encryptor.decrypt(encrypted)       # → "13812345678"

特性:
    - AES-256-GCM (认证加密，防篡改)
    - 每次加密使用随机 IV (12字节)
    - 输出格式：ENC:{base64(iv + ciphertext + tag)}
    - 密钥从环境变量 TX_FIELD_ENCRYPTION_KEY 读取
    - 密钥轮换支持（可配置多个密钥，解密时遍历尝试）

与 shared/utils/field_encryption.py 的关系:
    旧模块使用 "enc:v1:" 前缀，本模块使用 "ENC:" 前缀。
    两套前缀互不冲突，可在迁移期共存。新代码应使用本模块。
"""

from __future__ import annotations

import base64
import os
from typing import Optional

import structlog
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = structlog.get_logger(__name__)

PREFIX = "ENC:"
IV_BYTES = 12
KEY_BYTES = 32  # AES-256 = 32字节密钥
TAG_BYTES = 16  # GCM tag = 16字节


class FieldEncryptor:
    """字段级AES-256-GCM加密器，支持密钥轮换。

    Args:
        key: 主加密密钥（32字节 bytes 或 64位 hex 字符串）。
             若不传，从 TX_FIELD_ENCRYPTION_KEY 环境变量读取。
        old_keys: 旧密钥列表，用于密钥轮换期间解密旧数据。
                  格式同 key。也可通过 TX_FIELD_ENCRYPTION_OLD_KEYS
                  环境变量配置（逗号分隔的 hex 字符串）。
    """

    def __init__(
        self,
        key: Optional[bytes | str] = None,
        old_keys: Optional[list[bytes | str]] = None,
    ) -> None:
        self._primary_key = self._parse_key(
            key or os.environ.get("TX_FIELD_ENCRYPTION_KEY", ""),
            label="TX_FIELD_ENCRYPTION_KEY",
        )

        # 旧密钥：用于密钥轮换期间解密
        self._old_keys: list[bytes] = []
        if old_keys:
            for i, k in enumerate(old_keys):
                parsed = self._parse_key(k, label=f"old_key[{i}]")
                if parsed is not None:
                    self._old_keys.append(parsed)
        else:
            env_old = os.environ.get("TX_FIELD_ENCRYPTION_OLD_KEYS", "")
            if env_old.strip():
                for i, hex_key in enumerate(env_old.split(",")):
                    parsed = self._parse_key(hex_key.strip(), label=f"env_old_key[{i}]")
                    if parsed is not None:
                        self._old_keys.append(parsed)

    @staticmethod
    def _parse_key(key: bytes | str, label: str = "key") -> Optional[bytes]:
        """将 hex 字符串或 bytes 解析为 32 字节密钥。"""
        if not key:
            return None
        if isinstance(key, str):
            try:
                key_bytes = bytes.fromhex(key)
            except ValueError as exc:
                raise ValueError(f"{label} 不是有效的 hex 字符串: {exc}") from exc
        else:
            key_bytes = key

        if len(key_bytes) != KEY_BYTES:
            raise ValueError(f"{label} 必须为 {KEY_BYTES} 字节（{KEY_BYTES * 2} 位 hex），实际为 {len(key_bytes)} 字节")
        return key_bytes

    @property
    def is_configured(self) -> bool:
        """主密钥是否已配置。"""
        return self._primary_key is not None

    def encrypt(self, plaintext: str) -> str:
        """加密字符串，返回 ENC:{base64(iv + ciphertext + tag)}。

        已加密的值幂等返回。

        Raises:
            RuntimeError: 主密钥未配置
        """
        if self._primary_key is None:
            raise RuntimeError("加密密钥未配置，无法加密")
        if is_encrypted(plaintext):
            return plaintext

        iv = os.urandom(IV_BYTES)
        aesgcm = AESGCM(self._primary_key)
        ciphertext_with_tag = aesgcm.encrypt(iv, plaintext.encode("utf-8"), None)
        encoded = base64.b64encode(iv + ciphertext_with_tag).decode("ascii")
        return f"{PREFIX}{encoded}"

    def decrypt(self, value: str) -> str:
        """解密。非 ENC: 前缀的值原样返回（明文兼容，用于迁移期）。

        密钥轮换：先用主密钥尝试解密，失败后依次尝试旧密钥。

        Raises:
            RuntimeError: 无可用密钥
            InvalidTag: 所有密钥均无法解密（密文被篡改或密钥不匹配）
            ValueError: base64 格式错误或数据长度不足
        """
        if not is_encrypted(value):
            return value

        keys_to_try = self._all_keys()
        if not keys_to_try:
            raise RuntimeError("加密密钥未配置，无法解密")

        raw = self._decode_payload(value)
        if len(raw) <= IV_BYTES:
            raise ValueError(f"加密字段数据长度不足，期望 > {IV_BYTES} 字节，实际 {len(raw)} 字节")

        iv, ciphertext_with_tag = raw[:IV_BYTES], raw[IV_BYTES:]

        last_exc: InvalidTag | None = None
        for key in keys_to_try:
            try:
                aesgcm = AESGCM(key)
                plaintext_bytes = aesgcm.decrypt(iv, ciphertext_with_tag, None)
                return plaintext_bytes.decode("utf-8")
            except InvalidTag as exc:
                last_exc = exc
                continue

        # 所有密钥都失败
        raise InvalidTag("所有密钥均无法解密，密文可能被篡改或密钥不匹配") from last_exc

    def re_encrypt(self, value: str) -> str:
        """用主密钥重新加密（密钥轮换时批量更新数据用）。

        对已加密值：先解密再用主密钥加密。
        对明文值：直接加密。
        """
        plaintext = self.decrypt(value)
        # 强制重新加密（即使已是 ENC: 格式，解密后再加密会用新主密钥 + 新 IV）
        if self._primary_key is None:
            raise RuntimeError("加密密钥未配置，无法重新加密")
        iv = os.urandom(IV_BYTES)
        aesgcm = AESGCM(self._primary_key)
        ciphertext_with_tag = aesgcm.encrypt(iv, plaintext.encode("utf-8"), None)
        encoded = base64.b64encode(iv + ciphertext_with_tag).decode("ascii")
        return f"{PREFIX}{encoded}"

    def _all_keys(self) -> list[bytes]:
        """返回主密钥 + 旧密钥列表（按优先级排序）。"""
        keys: list[bytes] = []
        if self._primary_key is not None:
            keys.append(self._primary_key)
        keys.extend(self._old_keys)
        return keys

    @staticmethod
    def _decode_payload(value: str) -> bytes:
        """从 ENC:xxx 提取并 base64 解码有效载荷。"""
        encoded = value[len(PREFIX) :]
        try:
            return base64.b64decode(encoded)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"加密字段 base64 格式错误: {exc}") from exc


def is_encrypted(value: str) -> bool:
    """判断字段值是否已被加密（ENC: 前缀）。"""
    return isinstance(value, str) and value.startswith(PREFIX)


# ─── 模块级单例 ───────────────────────────────────────────────────────
_instance: Optional[FieldEncryptor] = None


def get_encryptor() -> FieldEncryptor:
    """获取全局 FieldEncryptor 单例。"""
    global _instance  # noqa: PLW0603
    if _instance is None:
        _instance = FieldEncryptor()
    return _instance


def reset_encryptor() -> None:
    """重置全局单例（仅用于测试）。"""
    global _instance  # noqa: PLW0603
    _instance = None
