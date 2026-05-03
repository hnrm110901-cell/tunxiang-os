"""API Key 生成器 — 安全生成/哈希/验证

密钥格式: `tx_` + 48 位 base62 随机字符 (字符集: 0-9a-zA-Z)
全密钥仅在创建时返回一次，数据库存储 SHA-256 哈希。
"""
import hashlib
import secrets
import string

ALPHABET = string.digits + string.ascii_uppercase + string.ascii_lowercase  # 62 chars
KEY_PREFIX = "tx_"
KEY_BODY_LENGTH = 48
FULL_KEY_LENGTH = len(KEY_PREFIX) + KEY_BODY_LENGTH  # 51 chars


def generate_api_key() -> tuple[str, str, str]:
    """生成 API 密钥对。

    Returns:
        (full_key, key_prefix, key_hash)
        - full_key:  唯一完整密钥（仅返回一次）
        - key_prefix: 前 10 位，用于识别和索引
        - key_hash:   SHA-256 十六进制摘要
    """
    body = "".join(secrets.choice(ALPHABET) for _ in range(KEY_BODY_LENGTH))
    full_key = KEY_PREFIX + body
    key_prefix = full_key[: len(KEY_PREFIX) + 7]  # "tx_" + 7 chars = 10
    key_hash = hashlib.sha256(full_key.encode()).hexdigest()
    return full_key, key_prefix, key_hash


def hash_api_key(full_key: str) -> str:
    """对完整密钥进行 SHA-256 哈希。"""
    return hashlib.sha256(full_key.encode()).hexdigest()


def validate_key_format(full_key: str) -> bool:
    """校验密钥格式是否正确。"""
    if not full_key.startswith(KEY_PREFIX):
        return False
    if len(full_key) != FULL_KEY_LENGTH:
        return False
    body = full_key[len(KEY_PREFIX) :]
    return all(c in ALPHABET for c in body)
