"""Tier 1 — Gateway 第三方外卖/预订 webhook 白名单验证

漏洞背景:
  AUTH_EXEMPT_PREFIXES 缺 /api/v1/webhook + /api/v1/booking/webhook，导致
  美团/饿了么/抖音外卖 webhook + 美团/点评/微信预订 webhook 被 AuthMiddleware
  以 401 拒绝，永不到达 tx-trade。两 prefix 路由代码已在 v412 上线 (PR #405,
  5/10 merged) 但因白名单缺漏从未真跑过。5/13 资质上线即翻车。

修复: 加 /api/v1/webhook + /api/v1/booking/webhook 到 AUTH_EXEMPT_PREFIXES
(sibling of /api/v1/pay/callback).

收窄说明:
  booking prefix 收窄到 /api/v1/booking/webhook 而非 /api/v1/booking，
  原因: booking_webhook_routes.py prefix 是 /api/v1/booking，下面除了 3 个
  /webhook/{平台} 还有 /mock/new-reservation 与 /ws/{store_id}，后两条若一并
  bypass 等于把 dev mock 与 WebSocket 暴露给公网。

测试策略:
  - Unit: 直接测试 _is_exempt() 函数，验证白名单逻辑（最快，无网络依赖）
  - 覆盖: 6 第三方 bypass + 2 元组完整性 + 3 负向（业务路由 / mock / WS）

运行方法（从仓库根）:
  PYTHONPATH=services/gateway/src python3 -m pytest \
    services/gateway/tests/tier1/test_gateway_thirdparty_callback_whitelist_tier1.py -v
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


# ── Unit Tests: webhook prefix bypass ───────────────────────────────────


def test_webhook_meituan_order_bypass_auth():
    """美团外卖订单 webhook 免认证 — 第三方无 JWT，不应收到 401"""
    assert _is_exempt("/api/v1/webhook/meituan/order"), (
        "/api/v1/webhook/meituan/order 必须在白名单内（美团外卖 webhook）"
    )


def test_webhook_eleme_order_bypass_auth():
    """饿了么外卖订单 webhook 免认证 — 第三方无 JWT，不应收到 401"""
    assert _is_exempt("/api/v1/webhook/eleme/order"), (
        "/api/v1/webhook/eleme/order 必须在白名单内（饿了么 webhook）"
    )


def test_webhook_douyin_order_bypass_auth():
    """抖音外卖订单 webhook 免认证 — 第三方无 JWT，不应收到 401"""
    assert _is_exempt("/api/v1/webhook/douyin/order"), (
        "/api/v1/webhook/douyin/order 必须在白名单内（抖音外卖 webhook）"
    )


# ── Unit Tests: booking prefix bypass ───────────────────────────────────


def test_booking_webhook_meituan_bypass_auth():
    """美团预订 webhook 免认证 — 第三方无 JWT，不应收到 401"""
    assert _is_exempt("/api/v1/booking/webhook/meituan"), (
        "/api/v1/booking/webhook/meituan 必须在白名单内（美团预订 webhook）"
    )


def test_booking_webhook_dianping_bypass_auth():
    """点评预订 webhook 免认证 — 第三方无 JWT，不应收到 401"""
    assert _is_exempt("/api/v1/booking/webhook/dianping"), (
        "/api/v1/booking/webhook/dianping 必须在白名单内（点评预订 webhook）"
    )


def test_booking_webhook_wechat_bypass_auth():
    """微信预订 webhook 免认证 — 第三方无 JWT，不应收到 401"""
    assert _is_exempt("/api/v1/booking/webhook/wechat"), (
        "/api/v1/booking/webhook/wechat 必须在白名单内（微信预订 webhook）"
    )


# ── 白名单结构完整性断言（mutation kill）────────────────────────────────


def test_webhook_prefix_in_exempt_tuple():
    """/api/v1/webhook 已加入 AUTH_EXEMPT_PREFIXES 元组"""
    assert "/api/v1/webhook" in AUTH_EXEMPT_PREFIXES, (
        f"AUTH_EXEMPT_PREFIXES 缺少 /api/v1/webhook。"
        f"当前内容: {AUTH_EXEMPT_PREFIXES}"
    )


def test_booking_webhook_prefix_in_exempt_tuple():
    """/api/v1/booking/webhook 已加入 AUTH_EXEMPT_PREFIXES 元组（收窄过的精确 prefix）"""
    assert "/api/v1/booking/webhook" in AUTH_EXEMPT_PREFIXES, (
        f"AUTH_EXEMPT_PREFIXES 缺少 /api/v1/booking/webhook。"
        f"当前内容: {AUTH_EXEMPT_PREFIXES}"
    )


def test_booking_bare_prefix_NOT_in_exempt_tuple():
    """/api/v1/booking 裸 prefix 不得加入元组（防 prefix 被回退放宽）"""
    assert "/api/v1/booking" not in AUTH_EXEMPT_PREFIXES, (
        f"AUTH_EXEMPT_PREFIXES 不应有裸 /api/v1/booking（会把 /mock/* 与 /ws/* 一并 bypass）。"
        f"当前内容: {AUTH_EXEMPT_PREFIXES}"
    )


# ── 负向测试: 非白名单路径仍需认证 ──────────────────────────────────────


def test_orders_create_still_requires_auth():
    """非 webhook/booking 路径仍需认证 — 防止白名单误开业务路由"""
    assert not _is_exempt("/api/v1/trade/orders"), (
        "/api/v1/trade/orders 不应在白名单内（业务路由需要鉴权）"
    )


def test_booking_mock_reservation_still_requires_auth():
    """booking_webhook_routes.py:602 /mock/new-reservation 仍需认证 — 防止 dev mock 被公网误开"""
    assert not _is_exempt("/api/v1/booking/mock/new-reservation"), (
        "/api/v1/booking/mock/new-reservation 不应在白名单内（dev mock 路由，会直接写 customer_bookings）"
    )


def test_booking_ws_still_requires_auth():
    """booking_webhook_routes.py:190 /ws/{store_id} WebSocket 仍需认证 — 防止未授权订阅推送"""
    assert not _is_exempt("/api/v1/booking/ws/store_001"), (
        "/api/v1/booking/ws/{store_id} 不应在白名单内（WebSocket 推送通道）"
    )


def test_customer_booking_business_routes_still_require_auth():
    """customer_booking_routes.py 的 create/list/cancel 业务路由仍需认证（latent trap 防御）"""
    for path in ("/api/v1/booking/create", "/api/v1/booking/list", "/api/v1/booking/abc/cancel"):
        assert not _is_exempt(path), (
            f"{path} 不应在白名单内（customer 业务路由，当前虽未在 main register 但绝对路径写死等未来 trap）"
        )
