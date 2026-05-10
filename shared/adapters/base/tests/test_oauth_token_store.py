"""[Tier1] oauth_token_store.py 单元测试

CH-01（issue #375）。覆盖范围：
  1. Fernet 加解密往返
  2. 不同密钥解密失败
  3. _load_fernet env 缺失抛错
  4. OAuthToken.is_expiring_within 阈值判断
  5. _encrypt / _decrypt None 处理
  6. TokenDecryptError 包装

DB 交互不在本文件 — 见 shared/db-migrations/tests/test_v411_oauth_tokens_tier1.py
（真 PG 反测，opt-in via INTEGRATION_PG_DSN）。
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from shared.adapters.base.src.oauth_token_store import (
    OAuthToken,
    OAuthTokenStoreError,
    TokenDecryptError,
    _decrypt,
    _encrypt,
    _load_fernet,
)


# ─────────────────────────────────────────────────────────────────
# 1. Fernet 加解密往返
# ─────────────────────────────────────────────────────────────────


def test_encrypt_decrypt_roundtrip():
    f = Fernet(Fernet.generate_key())
    plain = "meituan-access-token-abc123"
    enc = _encrypt(f, plain)
    assert isinstance(enc, bytes)
    assert enc != plain.encode()
    assert _decrypt(f, enc) == plain


def test_encrypt_decrypt_unicode():
    f = Fernet(Fernet.generate_key())
    plain = "token-含中文-🍜"
    assert _decrypt(f, _encrypt(f, plain)) == plain


def test_encrypt_none_returns_none():
    f = Fernet(Fernet.generate_key())
    assert _encrypt(f, None) is None


def test_decrypt_none_returns_none():
    f = Fernet(Fernet.generate_key())
    assert _decrypt(f, None) is None


# ─────────────────────────────────────────────────────────────────
# 2. 不同密钥解密失败
# ─────────────────────────────────────────────────────────────────


def test_decrypt_with_wrong_key_raises():
    f1 = Fernet(Fernet.generate_key())
    f2 = Fernet(Fernet.generate_key())
    enc = _encrypt(f1, "secret")
    with pytest.raises(TokenDecryptError):
        _decrypt(f2, enc)


def test_decrypt_tampered_data_raises():
    f = Fernet(Fernet.generate_key())
    enc = _encrypt(f, "secret")
    tampered = enc[:-5] + b"XXXXX"
    with pytest.raises(TokenDecryptError):
        _decrypt(f, tampered)


# ─────────────────────────────────────────────────────────────────
# 3. _load_fernet env 处理
# ─────────────────────────────────────────────────────────────────


def test_load_fernet_missing_env_raises():
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(OAuthTokenStoreError, match="OAUTH_TOKEN_ENCRYPTION_KEY"):
            _load_fernet()


def test_load_fernet_invalid_key_raises():
    with patch.dict(os.environ, {"OAUTH_TOKEN_ENCRYPTION_KEY": "not-a-valid-key"}):
        with pytest.raises(OAuthTokenStoreError, match="格式错误"):
            _load_fernet()


def test_load_fernet_valid_key_returns_fernet():
    valid_key = Fernet.generate_key().decode()
    with patch.dict(os.environ, {"OAUTH_TOKEN_ENCRYPTION_KEY": valid_key}):
        f = _load_fernet()
        assert isinstance(f, Fernet)
        # 能用于加密
        assert f.decrypt(f.encrypt(b"hello")) == b"hello"


# ─────────────────────────────────────────────────────────────────
# 4. OAuthToken.is_expiring_within
# ─────────────────────────────────────────────────────────────────


def _make_token(expires_at: datetime) -> OAuthToken:
    return OAuthToken(
        token_id=uuid4(),
        tenant_id=uuid4(),
        store_id=uuid4(),
        platform="meituan",
        account_id="POI001",
        access_token="x",
        refresh_token=None,
        token_type="Bearer",
        expires_at=expires_at,
        refresh_expires_at=None,
        scope=None,
        last_refreshed_at=datetime.now(timezone.utc),
        refresh_failure_count=0,
    )


def test_is_expiring_within_already_expired():
    token = _make_token(datetime.now(timezone.utc) - timedelta(seconds=1))
    assert token.is_expiring_within(60) is True


def test_is_expiring_within_threshold_zone():
    token = _make_token(datetime.now(timezone.utc) + timedelta(seconds=30))
    assert token.is_expiring_within(60) is True


def test_is_expiring_within_far_future():
    token = _make_token(datetime.now(timezone.utc) + timedelta(hours=1))
    assert token.is_expiring_within(60) is False


def test_is_expiring_within_at_exact_threshold():
    """边界：恰好等于阈值 → 应视为"将过期"。"""
    threshold = 60
    token = _make_token(datetime.now(timezone.utc) + timedelta(seconds=threshold - 1))
    assert token.is_expiring_within(threshold) is True


# ─────────────────────────────────────────────────────────────────
# 5. 加密对象语义校验
# ─────────────────────────────────────────────────────────────────


def test_encrypted_value_different_each_call():
    """Fernet 加密含 IV，同明文两次加密结果应不同（防离线相等性攻击）。"""
    f = Fernet(Fernet.generate_key())
    enc1 = _encrypt(f, "secret")
    enc2 = _encrypt(f, "secret")
    assert enc1 != enc2
    # 但都能正确解密
    assert _decrypt(f, enc1) == "secret"
    assert _decrypt(f, enc2) == "secret"
