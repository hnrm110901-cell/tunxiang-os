"""Tier 1 — Gateway 支付回调白名单验证

漏洞背景:
  AUTH_EXEMPT_PREFIXES 缺 /api/v1/pay/callback，导致微信/支付宝/拉卡拉/收钱吧
  4 渠道支付回调 POST 请求被 AuthMiddleware 以 401 拒绝，永不到达 tx-pay。
  OrderPaymentConfirmed 事件永不发射 → 订单永不标注已付款。

修复: 加 /api/v1/pay/callback 到 AUTH_EXEMPT_PREFIXES (sibling of wecom/callback)。

测试策略:
  - Unit: 直接测试 _is_exempt() 函数，验证白名单逻辑（最快，无网络依赖）
  - Integration: 通过最小 FastAPI TestClient（仅挂 AuthMiddleware）验证 HTTP 层行为

运行方法（从仓库根）:
  PYTHONPATH=services/gateway/src python3 -m pytest \
    services/gateway/tests/tier1/test_gateway_pay_callback_whitelist_tier1.py -v
"""

import os
import sys
import unittest.mock

import pytest

# 确保 gateway src 在 path 中（兼容本地 / CI 两种运行方式）
_gateway_src = os.path.join(os.path.dirname(__file__), "..", "..", "src")
if _gateway_src not in sys.path:
    sys.path.insert(0, _gateway_src)

# 隔离 JWTService 导入（避免 jwt / structlog 级联问题）
_jwt_mock = unittest.mock.MagicMock()
_jwt_mock.verify_access_token.return_value = None  # 默认：token 无效 → 401

if "services.jwt_service" not in sys.modules:
    sys.modules["services.jwt_service"] = _jwt_mock


# ── 导入被测模块 ────────────────────────────────────────────────────────

from middleware.auth_middleware import AUTH_EXEMPT_PREFIXES, _is_exempt  # noqa: E402


# ── Unit Tests: _is_exempt 函数直接验证 ─────────────────────────────────


def test_pay_callback_wechat_bypass_auth():
    """微信支付回调路径免认证 — 第三方无 JWT，不应收到 401"""
    assert _is_exempt("/api/v1/pay/callback/wechat"), (
        "/api/v1/pay/callback/wechat 必须在白名单内（微信支付回调）"
    )


def test_pay_callback_alipay_bypass_auth():
    """支付宝回调路径免认证 — 第三方无 JWT，不应收到 401"""
    assert _is_exempt("/api/v1/pay/callback/alipay"), (
        "/api/v1/pay/callback/alipay 必须在白名单内（支付宝回调）"
    )


def test_pay_callback_lakala_bypass_auth():
    """拉卡拉回调路径免认证 — 第三方无 JWT，不应收到 401"""
    assert _is_exempt("/api/v1/pay/callback/lakala"), (
        "/api/v1/pay/callback/lakala 必须在白名单内（拉卡拉回调）"
    )


def test_pay_callback_shouqianba_bypass_auth():
    """收钱吧回调路径免认证 — 第三方无 JWT，不应收到 401"""
    assert _is_exempt("/api/v1/pay/callback/shouqianba"), (
        "/api/v1/pay/callback/shouqianba 必须在白名单内（收钱吧回调）"
    )


def test_pay_create_still_requires_auth():
    """pay/create 非回调路径仍需认证 — 防止误开非回调路径"""
    assert not _is_exempt("/api/v1/pay/create"), (
        "/api/v1/pay/create 不应在白名单内（收款发起需要鉴权）"
    )


def test_pay_admin_channels_still_requires_auth():
    """pay/admin/channels 管理路径仍需认证 — 防止误开管理接口"""
    assert not _is_exempt("/api/v1/pay/admin/channels"), (
        "/api/v1/pay/admin/channels 不应在白名单内（管理接口需要鉴权）"
    )


# ── 白名单结构完整性断言 ─────────────────────────────────────────────────


def test_pay_callback_prefix_in_exempt_tuple():
    """/api/v1/pay/callback 已加入 AUTH_EXEMPT_PREFIXES 元组"""
    assert "/api/v1/pay/callback" in AUTH_EXEMPT_PREFIXES, (
        f"AUTH_EXEMPT_PREFIXES 缺少 /api/v1/pay/callback。"
        f"当前内容: {AUTH_EXEMPT_PREFIXES}"
    )


def test_wecom_callback_still_exempt():
    """/api/v1/wecom/callback 原有白名单未被意外删除"""
    assert _is_exempt("/api/v1/wecom/callback"), (
        "/api/v1/wecom/callback 被意外从白名单中删除"
    )
