"""分账通道通知 — HMAC 验签单元测试（不依赖 DB）。"""

import hashlib
import hmac
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.split_notify_security import verify_split_channel_notify_signature


def test_verify_skips_when_no_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TX_FINANCE_SPLIT_NOTIFY_SECRET", raising=False)
    verify_split_channel_notify_signature(b"{}", None)


def test_verify_requires_header_when_secret_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TX_FINANCE_SPLIT_NOTIFY_SECRET", "x")
    with pytest.raises(ValueError, match="missing"):
        verify_split_channel_notify_signature(b'{"a":1}', None)


def test_verify_accepts_hmac(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TX_FINANCE_SPLIT_NOTIFY_SECRET", "secret")
    body = b'{"a":1}'
    sig = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    verify_split_channel_notify_signature(body, sig)


def test_verify_rejects_bad_hmac(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TX_FINANCE_SPLIT_NOTIFY_SECRET", "secret")
    with pytest.raises(ValueError, match="invalid"):
        verify_split_channel_notify_signature(b'{"a":1}', "deadbeef")
