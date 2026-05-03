"""微信支付营销 API 单元测试：Mock 门禁 & 主要方法 Mock 响应。"""

from __future__ import annotations

import importlib
import sys

import pytest


def _reload_module(monkeypatch: pytest.MonkeyPatch) -> object:
    """清除环境变量后重新加载模块（触发 Mock 模式）。"""
    monkeypatch.delenv("WECHAT_PAY_MCH_ID", raising=False)
    monkeypatch.delenv("WECHAT_PAY_API_KEY_V3", raising=False)
    monkeypatch.delenv("WECHAT_PAY_CERT_PATH", raising=False)
    monkeypatch.delenv("WECHAT_PAY_APPID", raising=False)
    name = "shared.integrations.wechat_pay_promotion"
    if name in sys.modules:
        del sys.modules[name]
    parent = "shared.integrations.wechat_pay"
    if parent in sys.modules:
        del sys.modules[parent]
    return importlib.import_module(name)


# ─── Mock 门禁 ───


def test_production_rejects_unconfigured_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("TX_WECHAT_PAY_ALLOW_MOCK", raising=False)
    mod = _reload_module(monkeypatch)
    with pytest.raises(RuntimeError, match="生产环境禁止微信支付营销 Mock"):
        mod.WechatPayPromotionService()


def test_production_allows_mock_when_explicit_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("TX_WECHAT_PAY_ALLOW_MOCK", "1")
    mod = _reload_module(monkeypatch)
    svc = mod.WechatPayPromotionService()
    assert svc._mock_mode is True


def test_development_allows_unconfigured_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    mod = _reload_module(monkeypatch)
    svc = mod.WechatPayPromotionService()
    assert svc._mock_mode is True


# ─── 单例 ───


def test_get_service_returns_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    mod = _reload_module(monkeypatch)
    svc1 = mod.get_wechat_pay_promotion_service()
    svc2 = mod.get_wechat_pay_promotion_service()
    assert svc1 is svc2


# ─── 摇一摇优惠活动 ───


@pytest.mark.asyncio
async def test_create_shake_coupon_activity_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    mod = _reload_module(monkeypatch)
    svc = mod.WechatPayPromotionService()

    result = await svc.create_shake_coupon_activity(
        activity_name="测试摇优惠",
        begin_time="2026-05-01T00:00:00+08:00",
        end_time="2026-06-01T00:00:00+08:00",
        award_amount_fen=500,
        total_count=1000,
    )
    assert result["status"] == "CREATED"
    assert result["activity_id"].startswith("MOCK_SHAKE_")
    assert result["activity_name"] == "测试摇优惠"


# ─── 商家名片 ───


@pytest.mark.asyncio
async def test_create_merchant_card_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    mod = _reload_module(monkeypatch)
    svc = mod.WechatPayPromotionService()

    result = await svc.create_merchant_card(
        card_name="徐记海鲜会员卡",
        card_type="membership",
    )
    assert result["status"] == "CREATED"
    assert result["card_id"].startswith("MOCK_CARD_")


# ─── 投放计划 ───


@pytest.mark.asyncio
async def test_create_promotion_plan_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    mod = _reload_module(monkeypatch)
    svc = mod.WechatPayPromotionService()

    result = await svc.create_promotion_plan(
        plan_name="618 大促投放",
        plan_type="coupon",
        begin_time="2026-06-01T00:00:00+08:00",
        end_time="2026-06-20T00:00:00+08:00",
    )
    assert result["status"] == "CREATED"
    assert result["plan_id"].startswith("MOCK_PLAN_")


# ─── 旁路触发摇优惠 ───


@pytest.mark.asyncio
async def test_trigger_shake_coupon_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    mod = _reload_module(monkeypatch)
    svc = mod.WechatPayPromotionService()

    result = await svc.trigger_shake_coupon(
        openid="mock_openid",
        store_id="store_001",
        amount_fen=8800,
    )
    assert result["triggered"] is True
    assert result["openid"] == "mock_openid"
    assert result["store_id"] == "store_001"
    assert result["amount_fen"] == 8800
    assert result["mock"] is True
