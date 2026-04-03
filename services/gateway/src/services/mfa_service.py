"""TOTP双因素认证服务 — 等保三级要求

依赖：pyotp（TOTP算法）
Secret存储：简单XOR加密，避免明文存储。
加密密钥来自环境变量 TX_MFA_ENCRYPT_KEY（64位十六进制字符串，即32字节）。

注意：XOR加密为轻量保护，生产环境建议升级为 AES-256-GCM。
"""

import base64
import hashlib
import os
import secrets
from typing import Optional

import pyotp
import structlog

logger = structlog.get_logger(__name__)

ISSUER = "屯象OS"
BACKUP_CODE_COUNT = 8
BACKUP_CODE_BYTES = 4   # secrets.token_hex(4) → 8字符十六进制


def _load_encrypt_key() -> bytes:
    """从环境变量加载MFA加密密钥。未配置时随机生成（每次重启失效，仅供开发）。"""
    key_hex = os.environ.get("TX_MFA_ENCRYPT_KEY", "")
    if key_hex:
        try:
            key = bytes.fromhex(key_hex)
            if len(key) < 16:
                logger.warning(
                    "mfa_key_too_short",
                    length=len(key),
                    message="TX_MFA_ENCRYPT_KEY长度不足16字节",
                )
            return key
        except ValueError:
            logger.error(
                "mfa_key_invalid_hex",
                message="TX_MFA_ENCRYPT_KEY不是有效的十六进制字符串，使用随机密钥",
            )
    logger.warning(
        "mfa_key_not_set",
        message="TX_MFA_ENCRYPT_KEY未设置，使用随机密钥（重启后TOTP secret将无法解密）",
    )
    return os.urandom(32)


class MFAService:
    """TOTP双因素认证服务。

    所有对 mfa_secret_enc 的读写都经过 XOR 加密/解密。
    备用码存储为 SHA256 哈希列表（原始码仅在生成时返回给用户一次）。
    """

    def __init__(self) -> None:
        self._key: bytes = _load_encrypt_key()

    # ─────────────────────────────────────────────────────────────────
    # 加密工具
    # ─────────────────────────────────────────────────────────────────

    def _xor_encrypt(self, plaintext: str) -> str:
        """XOR加密，返回base64编码的密文。"""
        data = plaintext.encode("utf-8")
        key_len = len(self._key)
        key_cycle = bytes(self._key[i % key_len] for i in range(len(data)))
        ciphertext = bytes(a ^ b for a, b in zip(data, key_cycle))
        return base64.b64encode(ciphertext).decode("ascii")

    def _xor_decrypt(self, ciphertext: str) -> str:
        """XOR解密，输入base64编码的密文，返回明文。"""
        data = base64.b64decode(ciphertext)
        key_len = len(self._key)
        key_cycle = bytes(self._key[i % key_len] for i in range(len(data)))
        plaintext_bytes = bytes(a ^ b for a, b in zip(data, key_cycle))
        return plaintext_bytes.decode("utf-8")

    # ─────────────────────────────────────────────────────────────────
    # TOTP Secret 管理
    # ─────────────────────────────────────────────────────────────────

    def generate_secret(self) -> str:
        """生成新的TOTP secret（明文Base32字符串）。

        调用方应立即调用 encrypt_secret() 后再存储。
        """
        return pyotp.random_base32()

    def encrypt_secret(self, secret: str) -> str:
        """加密TOTP secret，返回适合存入数据库的密文。"""
        return self._xor_encrypt(secret)

    def get_totp_uri(self, encrypted_secret: str, username: str) -> str:
        """解密secret并生成 otpauth:// URI（用于生成二维码）。

        Args:
            encrypted_secret: 数据库中存储的加密secret。
            username: 用户名（显示在验证器App中）。

        Returns:
            otpauth://totp/... URI字符串。

        Raises:
            ValueError: 密文格式错误（base64解码失败）。
        """
        try:
            secret = self._xor_decrypt(encrypted_secret)
        except (ValueError, Exception) as exc:
            logger.error("totp_uri_decrypt_failed", error=str(exc))
            raise ValueError("无法解密TOTP secret") from exc
        totp = pyotp.TOTP(secret)
        return totp.provisioning_uri(name=username, issuer_name=ISSUER)

    def verify_totp(
        self,
        encrypted_secret: str,
        token: str,
        valid_window: int = 1,
    ) -> bool:
        """验证6位TOTP码。

        Args:
            encrypted_secret: 数据库中存储的加密secret。
            token: 用户输入的6位数字码。
            valid_window: 允许的时间窗口偏差（1 = 前后各30秒）。

        Returns:
            True 表示验证通过。
        """
        if not token or not token.isdigit() or len(token) != 6:
            logger.warning("totp_invalid_format", token_len=len(token) if token else 0)
            return False
        try:
            secret = self._xor_decrypt(encrypted_secret)
            totp = pyotp.TOTP(secret)
            result: bool = totp.verify(token, valid_window=valid_window)
            if not result:
                logger.info("totp_verify_failed")
            return result
        except (ValueError, KeyError) as exc:
            logger.warning("totp_verify_error", error=str(exc))
            return False

    # ─────────────────────────────────────────────────────────────────
    # 备用码管理
    # ─────────────────────────────────────────────────────────────────

    def generate_backup_codes(self) -> list[str]:
        """生成8个一次性备用码（明文，仅返回给用户一次）。

        Returns:
            8个8字符的大写十六进制字符串，例如 ["A3F9B21C", ...]。
        """
        return [
            secrets.token_hex(BACKUP_CODE_BYTES).upper()
            for _ in range(BACKUP_CODE_COUNT)
        ]

    def hash_backup_codes(self, codes: list[str]) -> list[str]:
        """对备用码做 SHA256 哈希，用于数据库存储。

        存储哈希而非明文，即使数据库泄露也无法直接使用备用码。

        Args:
            codes: 明文备用码列表（generate_backup_codes 的输出）。

        Returns:
            SHA256 哈希字符串列表（十六进制）。
        """
        return [hashlib.sha256(c.upper().encode("utf-8")).hexdigest() for c in codes]

    def verify_backup_code(
        self,
        hashed_codes: list[str],
        input_code: str,
    ) -> Optional[int]:
        """验证备用码，返回匹配的索引（调用方负责从列表中删除该索引）。

        Args:
            hashed_codes: 数据库中存储的哈希码列表。
            input_code:   用户输入的备用码（不区分大小写）。

        Returns:
            匹配的索引；未匹配返回 None。
        """
        hashed_input = hashlib.sha256(input_code.upper().encode("utf-8")).hexdigest()
        try:
            return hashed_codes.index(hashed_input)
        except ValueError:
            return None
