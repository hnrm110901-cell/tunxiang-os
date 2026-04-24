"""微信支付 Mock 门禁：生产环境禁止静默 Mock。"""

from __future__ import annotations

import importlib
import sys

import pytest


def _reload_wechat_pay(monkeypatch: pytest.MonkeyPatch) -> object:
    """按当前 os.environ 重新加载 wechat_pay 模块（模块级凭据在 import 时快照）。"""
    monkeypatch.delenv("WECHAT_PAY_MCH_ID", raising=False)
    monkeypatch.delenv("WECHAT_PAY_API_KEY_V3", raising=False)
    monkeypatch.delenv("WECHAT_PAY_CERT_PATH", raising=False)
    monkeypatch.delenv("WECHAT_PAY_APPID", raising=False)
    name = "shared.integrations.wechat_pay"
    if name in sys.modules:
        del sys.modules[name]
    return importlib.import_module(name)


def test_production_rejects_unconfigured_mock_without_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("TX_WECHAT_PAY_ALLOW_MOCK", raising=False)
    wp = _reload_wechat_pay(monkeypatch)
    with pytest.raises(RuntimeError, match="生产环境禁止微信支付 Mock"):
        wp.WechatPayService()


def test_production_allows_mock_when_explicit_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("TX_WECHAT_PAY_ALLOW_MOCK", "1")
    wp = _reload_wechat_pay(monkeypatch)
    svc = wp.WechatPayService()
    assert svc._mock_mode is True


def test_development_allows_unconfigured_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    wp = _reload_wechat_pay(monkeypatch)
    svc = wp.WechatPayService()
    assert svc._mock_mode is True
