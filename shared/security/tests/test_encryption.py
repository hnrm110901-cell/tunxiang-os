"""字段加密、SQLAlchemy 透明加密类型、数据脱敏 — 单元测试

覆盖:
    - FieldEncryptor: 加解密正确性、随机 IV、篡改检测、密钥轮换、幂等性
    - EncryptedString: 模拟 SQLAlchemy 存取流程
    - masking: 各种格式的脱敏函数
"""

from __future__ import annotations

import base64
import os
from unittest.mock import patch

import pytest
from cryptography.exceptions import InvalidTag

from shared.security.src.encrypted_type import EncryptedString
from shared.security.src.field_encryption import (
    PREFIX,
    FieldEncryptor,
    get_encryptor,
    is_encrypted,
    reset_encryptor,
)
from shared.security.src.masking import (
    mask_bank_card,
    mask_email,
    mask_id_card,
    mask_name,
    mask_phone,
)

# ─── 测试用密钥（仅测试环境使用） ─────────────────────────────────────
TEST_KEY_HEX = "a" * 64  # 32字节全 0xAA
TEST_KEY_BYTES = bytes.fromhex(TEST_KEY_HEX)
OLD_KEY_HEX = "b" * 64  # 旧密钥
OLD_KEY_BYTES = bytes.fromhex(OLD_KEY_HEX)


# ═══════════════════════════════════════════════════════════════════════
# FieldEncryptor 基础测试
# ═══════════════════════════════════════════════════════════════════════


class TestFieldEncryptorBasic:
    """加解密基础功能。"""

    def setup_method(self) -> None:
        self.enc = FieldEncryptor(key=TEST_KEY_HEX)

    def test_encrypt_decrypt_roundtrip(self) -> None:
        """加密后能正确解密回原文。"""
        plaintext = "13812345678"
        encrypted = self.enc.encrypt(plaintext)
        assert encrypted.startswith(PREFIX)
        assert self.enc.decrypt(encrypted) == plaintext

    def test_encrypt_unicode(self) -> None:
        """支持中文等 Unicode 字符。"""
        plaintext = "张三丰的身份证号码"
        encrypted = self.enc.encrypt(plaintext)
        assert self.enc.decrypt(encrypted) == plaintext

    def test_encrypt_empty_string(self) -> None:
        """空字符串也能加解密。"""
        encrypted = self.enc.encrypt("")
        assert self.enc.decrypt(encrypted) == ""

    def test_random_iv_each_time(self) -> None:
        """每次加密结果不同（随机 IV）。"""
        plaintext = "13812345678"
        encrypted_1 = self.enc.encrypt(plaintext)
        encrypted_2 = self.enc.encrypt(plaintext)
        assert encrypted_1 != encrypted_2
        # 但解密结果相同
        assert self.enc.decrypt(encrypted_1) == plaintext
        assert self.enc.decrypt(encrypted_2) == plaintext

    def test_idempotent_encrypt(self) -> None:
        """已加密的值再次加密时幂等返回。"""
        plaintext = "13812345678"
        encrypted = self.enc.encrypt(plaintext)
        double_encrypted = self.enc.encrypt(encrypted)
        assert encrypted == double_encrypted

    def test_plaintext_passthrough_on_decrypt(self) -> None:
        """非 ENC: 前缀的值解密时原样返回（迁移兼容）。"""
        plaintext = "13812345678"
        assert self.enc.decrypt(plaintext) == plaintext

    def test_is_encrypted(self) -> None:
        """is_encrypted 正确判断。"""
        encrypted = self.enc.encrypt("test")
        assert is_encrypted(encrypted) is True
        assert is_encrypted("plaintext") is False
        assert is_encrypted("") is False


class TestFieldEncryptorTamperDetection:
    """篡改检测 — GCM 认证加密的核心安全特性。"""

    def setup_method(self) -> None:
        self.enc = FieldEncryptor(key=TEST_KEY_HEX)

    def test_tampered_ciphertext_raises(self) -> None:
        """修改密文后解密失败 (InvalidTag)。"""
        encrypted = self.enc.encrypt("sensitive data")
        # 提取 base64 部分，修改一个字节
        payload = encrypted[len(PREFIX) :]
        raw = bytearray(base64.b64decode(payload))
        # 翻转密文区域的一个比特（跳过 IV 前12字节）
        raw[15] ^= 0xFF
        tampered = PREFIX + base64.b64encode(bytes(raw)).decode("ascii")
        with pytest.raises(InvalidTag):
            self.enc.decrypt(tampered)

    def test_invalid_base64_raises(self) -> None:
        """base64 格式错误抛出 ValueError。"""
        with pytest.raises(ValueError, match="base64"):
            self.enc.decrypt(f"{PREFIX}not-valid-base64!!!")

    def test_truncated_payload_raises(self) -> None:
        """数据长度不足抛出 ValueError。"""
        short_data = base64.b64encode(b"short").decode("ascii")
        with pytest.raises(ValueError, match="长度不足"):
            self.enc.decrypt(f"{PREFIX}{short_data}")


class TestFieldEncryptorKeyRotation:
    """密钥轮换测试。"""

    def test_decrypt_with_old_key(self) -> None:
        """旧密钥加密的数据，新密钥 + old_keys 可以解密。"""
        # 用旧密钥加密
        old_enc = FieldEncryptor(key=OLD_KEY_HEX)
        encrypted = old_enc.encrypt("13812345678")

        # 用新密钥（带旧密钥列表）解密
        new_enc = FieldEncryptor(key=TEST_KEY_HEX, old_keys=[OLD_KEY_HEX])
        assert new_enc.decrypt(encrypted) == "13812345678"

    def test_re_encrypt_with_new_key(self) -> None:
        """re_encrypt 用新主密钥重新加密。"""
        old_enc = FieldEncryptor(key=OLD_KEY_HEX)
        encrypted_old = old_enc.encrypt("secret")

        new_enc = FieldEncryptor(key=TEST_KEY_HEX, old_keys=[OLD_KEY_HEX])
        re_encrypted = new_enc.re_encrypt(encrypted_old)

        # 重新加密后，仅用新密钥即可解密
        new_only = FieldEncryptor(key=TEST_KEY_HEX)
        assert new_only.decrypt(re_encrypted) == "secret"

    def test_wrong_key_raises(self) -> None:
        """完全错误的密钥无法解密。"""
        enc = FieldEncryptor(key=TEST_KEY_HEX)
        encrypted = enc.encrypt("data")

        wrong_enc = FieldEncryptor(key="c" * 64)
        with pytest.raises(InvalidTag):
            wrong_enc.decrypt(encrypted)


class TestFieldEncryptorConfig:
    """配置与错误处理。"""

    def test_no_key_encrypt_raises(self) -> None:
        """未配置密钥时加密抛出 RuntimeError。"""
        enc = FieldEncryptor(key="")
        with pytest.raises(RuntimeError, match="密钥未配置"):
            enc.encrypt("test")

    def test_no_key_decrypt_encrypted_raises(self) -> None:
        """未配置密钥时解密已加密值抛出 RuntimeError。"""
        enc = FieldEncryptor(key="")
        with pytest.raises(RuntimeError, match="密钥未配置"):
            enc.decrypt(f"{PREFIX}dummydata==")

    def test_invalid_key_length_raises(self) -> None:
        """密钥长度不对抛出 ValueError。"""
        with pytest.raises(ValueError, match="32 字节"):
            FieldEncryptor(key="aa" * 10)  # 10字节，不是32

    def test_is_configured_property(self) -> None:
        """is_configured 正确反映密钥状态。"""
        assert FieldEncryptor(key=TEST_KEY_HEX).is_configured is True
        assert FieldEncryptor(key="").is_configured is False

    def test_key_from_bytes(self) -> None:
        """支持直接传入 bytes 密钥。"""
        enc = FieldEncryptor(key=TEST_KEY_BYTES)
        encrypted = enc.encrypt("test")
        assert enc.decrypt(encrypted) == "test"


class TestSingleton:
    """模块级单例。"""

    def test_get_encryptor_singleton(self) -> None:
        """get_encryptor 返回同一个实例。"""
        reset_encryptor()
        with patch.dict(os.environ, {"TX_FIELD_ENCRYPTION_KEY": TEST_KEY_HEX}):
            reset_encryptor()
            e1 = get_encryptor()
            e2 = get_encryptor()
            assert e1 is e2
            reset_encryptor()


# ═══════════════════════════════════════════════════════════════════════
# EncryptedString SQLAlchemy 类型测试
# ═══════════════════════════════════════════════════════════════════════


class TestEncryptedStringType:
    """模拟 SQLAlchemy TypeDecorator 的 bind/result 流程。"""

    def setup_method(self) -> None:
        reset_encryptor()

    def teardown_method(self) -> None:
        reset_encryptor()

    def test_bind_and_result_roundtrip(self) -> None:
        """写入时加密，读取时解密。"""
        with patch.dict(os.environ, {"TX_FIELD_ENCRYPTION_KEY": TEST_KEY_HEX}):
            reset_encryptor()
            col_type = EncryptedString(200)
            dialect = None  # TypeDecorator 不依赖 dialect

            # 模拟写入
            bound = col_type.process_bind_param("13812345678", dialect)
            assert bound is not None
            assert bound.startswith(PREFIX)

            # 模拟读取
            result = col_type.process_result_value(bound, dialect)
            assert result == "13812345678"

    def test_none_passthrough(self) -> None:
        """None 值透传（nullable 列）。"""
        with patch.dict(os.environ, {"TX_FIELD_ENCRYPTION_KEY": TEST_KEY_HEX}):
            reset_encryptor()
            col_type = EncryptedString(200)
            assert col_type.process_bind_param(None, None) is None
            assert col_type.process_result_value(None, None) is None

    def test_no_key_passthrough(self) -> None:
        """密钥未配置时明文透传（开发环境兼容）。"""
        with patch.dict(os.environ, {}, clear=False):
            # 确保环境变量不存在
            os.environ.pop("TX_FIELD_ENCRYPTION_KEY", None)
            reset_encryptor()
            col_type = EncryptedString(200)
            assert col_type.process_bind_param("plaintext", None) == "plaintext"
            assert col_type.process_result_value("plaintext", None) == "plaintext"


# ═══════════════════════════════════════════════════════════════════════
# 数据脱敏测试
# ═══════════════════════════════════════════════════════════════════════


class TestMaskPhone:
    """手机号脱敏。"""

    def test_standard_11_digits(self) -> None:
        assert mask_phone("13812345678") == "138****5678"

    def test_empty(self) -> None:
        assert mask_phone("") == ""

    def test_short_number(self) -> None:
        assert mask_phone("123") == "***"

    def test_non_standard_length(self) -> None:
        # 8位号码
        result = mask_phone("12345678")
        assert result[0].isdigit()
        assert "*" in result


class TestMaskIdCard:
    """身份证号脱敏。"""

    def test_18_digits(self) -> None:
        assert mask_id_card("420102199001011234") == "4201**********1234"

    def test_15_digits(self) -> None:
        assert mask_id_card("420102900101123") == "4201*******0123"

    def test_empty(self) -> None:
        assert mask_id_card("") == ""

    def test_short(self) -> None:
        assert mask_id_card("1234") == "***"


class TestMaskBankCard:
    """银行卡号脱敏。"""

    def test_16_digits(self) -> None:
        assert mask_bank_card("6222021234567890") == "6222********7890"

    def test_19_digits(self) -> None:
        assert mask_bank_card("6222021234567890123") == "6222***********0123"

    def test_empty(self) -> None:
        assert mask_bank_card("") == ""


class TestMaskName:
    """姓名脱敏。"""

    def test_three_chars(self) -> None:
        assert mask_name("张三丰") == "张**"

    def test_two_chars(self) -> None:
        assert mask_name("张三") == "张*"

    def test_single_char(self) -> None:
        assert mask_name("张") == "*"

    def test_empty(self) -> None:
        assert mask_name("") == ""

    def test_long_name(self) -> None:
        assert mask_name("欧阳娜娜") == "欧***"


class TestMaskEmail:
    """邮箱脱敏。"""

    def test_standard(self) -> None:
        assert mask_email("test@example.com") == "t***@example.com"

    def test_single_char_local(self) -> None:
        assert mask_email("a@example.com") == "a***@example.com"

    def test_empty(self) -> None:
        assert mask_email("") == "***"

    def test_no_at(self) -> None:
        assert mask_email("invalid") == "***"

    def test_long_local(self) -> None:
        assert mask_email("longusername@example.com") == "l***********@example.com"
