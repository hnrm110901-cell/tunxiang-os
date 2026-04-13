"""微信支付 V3 回调验签辅助函数单测。"""
from __future__ import annotations

import base64

import pytest
from starlette.datastructures import Headers
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa


def test_verify_rsa_sha256_pkcs1v15_accepts_valid_signature() -> None:
    from shared.integrations.wechat_pay import _verify_rsa_sha256_pkcs1v15

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    message = b'1737123456\nabc\n{"x":1}\n'
    sig = private_key.sign(message, padding.PKCS1v15(), hashes.SHA256())
    sig_b64 = base64.b64encode(sig).decode("ascii")
    _verify_rsa_sha256_pkcs1v15(public_key, message, sig_b64)


def test_get_wechatpay_header_starlette_lowercase_keys() -> None:
    from shared.integrations.wechat_pay import _get_wechatpay_header

    h = dict(Headers({"Wechatpay-Timestamp": "1737", "Wechatpay-Serial": "ABC"}))
    assert _get_wechatpay_header(h, "timestamp") == "1737"
    assert _get_wechatpay_header(h, "serial") == "ABC"


def test_verify_rsa_sha256_pkcs1v15_rejects_tampered_message() -> None:
    from shared.integrations.wechat_pay import _verify_rsa_sha256_pkcs1v15

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    message = b'1737123456\nabc\n{"x":1}\n'
    sig = private_key.sign(message, padding.PKCS1v15(), hashes.SHA256())
    sig_b64 = base64.b64encode(sig).decode("ascii")
    bad_message = message + b"x"
    with pytest.raises(ValueError, match="签名验证失败"):
        _verify_rsa_sha256_pkcs1v15(public_key, bad_message, sig_b64)
