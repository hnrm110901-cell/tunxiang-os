"""宴席定金 JSAPI 参数构建（无 DB / 无 ORM 导入链）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.banquet_payment_service import _build_wechat_jsapi_order_result


def test_build_jsapi_new_prepay():
    r = _build_wechat_jsapi_order_result(
        "PAYTEST001",
        100,
        "openid-x",
        "https://example.com/notify",
    )
    assert r["prepay_id"] == "mock_prepay_PAYTEST001"
    assert "prepay_id=" in r["jsapi_params"]["package"]
    assert r["jsapi_params"]["signType"] == "RSA"


def test_build_jsapi_reuse_prepay():
    r = _build_wechat_jsapi_order_result(
        "PAYTEST001",
        100,
        "openid-x",
        "https://example.com/notify",
        existing_prepay_id="wx_real_prepay_abc",
    )
    assert r["prepay_id"] == "wx_real_prepay_abc"
    assert r["jsapi_params"]["package"] == "prepay_id=wx_real_prepay_abc"


def test_build_jsapi_respects_wechat_app_id_in_sign_input(monkeypatch):
    monkeypatch.setenv("WECHAT_APP_ID", "wx_custom")
    r = _build_wechat_jsapi_order_result("PN", 1, "o", "u")
    assert r["jsapi_params"]["paySign"]
    assert len(r["jsapi_params"]["nonceStr"]) == 32
