"""外卖平台 Webhook + 微信支付路由 — 单元测试

覆盖文件:
  - api/webhook_routes.py   (美团/饿了么/抖音 Webhook 回调)
  - api/wechat_pay_routes.py (预支付/回调/查询/退款)

场景（共 10 个）:
 1. [webhook] 美团推送缺少 sign 字段 → 403
 2. [webhook] 美团推送签名验证失败 → 403
 3. [webhook] 美团推送验签成功 → 200 ok=True，adapter.receive_order 被调用
 4. [webhook] 饿了么推送签名验证失败 → 403
 5. [webhook] 抖音推送验签成功 → 200 ok=True，adapter.receive_order 被调用
 6. [wechat]  prepay 缺少 X-Tenant-ID → 400
 7. [wechat]  prepay 正常 → 200 ok=True，返回支付参数
 8. [wechat]  callback 验签失败 → 返回 code=FAIL
 9. [wechat]  query_order 正常 → 200 ok=True，返回订单状态
10. [wechat]  apply_refund 退款金额超过订单金额 → 400
"""
import hashlib
import hmac as hmac_mod
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ─── 存根注入：处理相对导入 ─────────────────────────────────────────────────────

import types

# shared.events 存根
_events_pkg = types.ModuleType("shared")
_events_pkg.events = types.ModuleType("shared.events")
_events_pkg.events.src = types.ModuleType("shared.events.src")

async def _noop_emit(**_kwargs):
    pass

_events_pkg.events.src.emitter = types.ModuleType("shared.events.src.emitter")
_events_pkg.events.src.emitter.emit_event = _noop_emit

_event_types_mod = types.ModuleType("shared.events.src.event_types")

class _ChannelEventType:
    ORDER_SYNCED = "CHANNEL.ORDER_SYNCED"

_event_types_mod.ChannelEventType = _ChannelEventType

sys.modules.setdefault("shared", _events_pkg)
sys.modules.setdefault("shared.events", _events_pkg.events)
sys.modules.setdefault("shared.events.src", _events_pkg.events.src)
sys.modules.setdefault("shared.events.src.emitter", _events_pkg.events.src.emitter)
sys.modules.setdefault("shared.events.src.event_types", _event_types_mod)

# shared.ontology.src.database 存根
_ontology_pkg = types.ModuleType("shared.ontology")
_ontology_src = types.ModuleType("shared.ontology.src")
_ontology_db = types.ModuleType("shared.ontology.src.database")

async def get_db():
    yield None

_ontology_db.get_db = get_db
sys.modules.setdefault("shared.ontology", _ontology_pkg)
sys.modules.setdefault("shared.ontology.src", _ontology_src)
sys.modules.setdefault("shared.ontology.src.database", _ontology_db)

# shared.integrations.wechat_pay 存根
_integrations_pkg = types.ModuleType("shared.integrations")
_wechat_pay_mod = types.ModuleType("shared.integrations.wechat_pay")

class _FakeWechatPayService:
    async def create_prepay(self, **_kw):
        return {"prepay_id": "px_test123", "sign": "SIGN123"}

    async def verify_callback(self, headers, body):
        raise ValueError("签名验证失败")

    async def query_order(self, out_trade_no):
        return {"trade_state": "SUCCESS", "out_trade_no": out_trade_no}

    async def refund(self, **_kw):
        return {"refund_id": "RF_TEST"}

_wechat_pay_mod.get_wechat_pay_service = lambda: _FakeWechatPayService()
sys.modules.setdefault("shared.integrations", _integrations_pkg)
sys.modules.setdefault("shared.integrations.wechat_pay", _wechat_pay_mod)

# ─── 导入被测模块 ────────────────────────────────────────────────────────────────

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ─── 工具函数 ────────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
BASE_HEADERS = {"X-Tenant-ID": TENANT_ID}


def _make_webhook_app():
    """构建包含 webhook_routes 的测试 FastAPI 应用"""
    # 延迟导入避免循环
    from api.webhook_routes import router
    app = FastAPI()
    app.include_router(router)
    return app


def _make_wechat_app():
    """构建包含 wechat_pay_routes 的测试 FastAPI 应用"""
    from api.wechat_pay_routes import router
    from shared.ontology.src.database import get_db as real_get_db
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[real_get_db] = lambda: None
    return app


def _meituan_sign(params: dict, secret: str) -> str:
    """重现美团签名算法"""
    filtered = {k: v for k, v in params.items() if k != "sign"}
    sorted_pairs = sorted(filtered.items(), key=lambda kv: kv[0])
    param_str = "".join(f"{k}={v}" for k, v in sorted_pairs)
    raw = param_str + secret
    return hashlib.md5(raw.encode("utf-8")).hexdigest().lower()


def _eleme_sign(payload: str, timestamp: str, secret: str) -> str:
    """重现饿了么签名算法"""
    sign_str = f"{secret}{payload}{timestamp}{secret}"
    return hashlib.sha256(sign_str.encode("utf-8")).hexdigest().upper()


def _douyin_sign(payload: str, timestamp: str, secret: str) -> str:
    """重现抖音 HMAC-SHA256 签名算法"""
    sign_str = f"{timestamp}\n{payload}"
    return hmac_mod.new(
        secret.encode("utf-8"),
        sign_str.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 1: 美团推送 — 缺少 sign 字段 → 403
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_meituan_webhook_missing_sign():
    """美团 Webhook 缺少 sign 字段时应返回 403"""
    app = _make_webhook_app()
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/api/v1/webhook/meituan/order",
        data={"order_id": "MT001", "app_poi_code": "STORE_001"},
        headers=BASE_HEADERS,
    )
    assert resp.status_code == 403
    assert "签名" in resp.json()["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 2: 美团推送 — 签名验证失败 → 403
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_meituan_webhook_invalid_sign():
    """美团 Webhook 签名错误时应返回 403"""
    # 设置一个 secret 让验签路径走到比较逻辑
    with patch.dict(os.environ, {"MEITUAN_APP_SECRET": "test_secret_key"}):
        # 重新导入模块使环境变量生效
        import importlib
        import api.webhook_routes as wh_mod
        importlib.reload(wh_mod)

        ts = str(int(time.time()))
        app = FastAPI()
        app.include_router(wh_mod.router)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/api/v1/webhook/meituan/order",
            data={
                "order_id": "MT001",
                "app_poi_code": "STORE_001",
                "timestamp": ts,
                "sign": "000000000000000000000000000000bad",  # 错误签名
            },
            headers=BASE_HEADERS,
        )
    assert resp.status_code == 403
    assert "签名验证失败" in resp.json()["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 3: 美团推送 — 验签成功 → 200, adapter.receive_order 被调用
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_meituan_webhook_valid_push():
    """美团 Webhook 验签通过时应调用 adapter 并返回 ok=True"""
    secret = "meituan_test_secret"
    ts = str(int(time.time()))

    params = {
        "order_id": "MT_VALID_001",
        "app_poi_code": "STORE_001",
        "order_total_price": "5800",
        "timestamp": ts,
        "detail": "",
        "recipient_phone": "138****1234",
        "recipient_address": "长沙市岳麓区xxx",
        "delivery_time": "2026-04-04T12:00:00",
        "caution": "少辣",
    }
    sign = _meituan_sign(params, secret)
    params["sign"] = sign

    mock_adapter = MagicMock()
    mock_adapter.receive_order = AsyncMock(return_value={
        "order_id": str(uuid.uuid4()),
        "order_no": "ORD20260404001",
    })

    with patch.dict(os.environ, {"MEITUAN_APP_SECRET": secret}):
        import importlib
        import api.webhook_routes as wh_mod
        importlib.reload(wh_mod)

        with patch.object(wh_mod, "DeliveryPlatformAdapter", return_value=mock_adapter):
            app = FastAPI()
            app.include_router(wh_mod.router)
            client = TestClient(app, raise_server_exceptions=False)

            resp = client.post(
                "/api/v1/webhook/meituan/order",
                data=params,
                headers=BASE_HEADERS,
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    mock_adapter.receive_order.assert_awaited_once()
    call_kwargs = mock_adapter.receive_order.call_args.kwargs
    assert call_kwargs["platform"] == "meituan"
    assert call_kwargs["platform_order_id"] == "MT_VALID_001"
    assert call_kwargs["total_fen"] == 5800


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 4: 饿了么推送 — 签名验证失败 → 403
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_eleme_webhook_invalid_signature():
    """饿了么 Webhook 签名错误时应返回 403"""
    import json as _json
    with patch.dict(os.environ, {"ELEME_APP_SECRET": "eleme_test_secret"}):
        import importlib
        import api.webhook_routes as wh_mod
        importlib.reload(wh_mod)

        ts = str(int(time.time()))
        payload = _json.dumps({"type": "new_order", "data": {"order_id": "EL001"}})

        app = FastAPI()
        app.include_router(wh_mod.router)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/api/v1/webhook/eleme/order",
            content=payload,
            headers={
                **BASE_HEADERS,
                "Content-Type": "application/json",
                "X-Eleme-Signature": "BADSIGNATURE",
                "X-Eleme-Timestamp": ts,
            },
        )

    assert resp.status_code == 403
    assert "签名验证失败" in resp.json()["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 5: 抖音推送 — 验签成功 → 200, adapter.receive_order 被调用
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_douyin_webhook_valid_push():
    """抖音 Webhook 验签通过时应调用 adapter 并返回 ok=True"""
    import json as _json
    secret = "douyin_test_secret"
    ts = str(int(time.time()))

    order_data = {
        "order_id": "DY_VALID_001",
        "shop_id": "STORE_DY_001",
        "pay_amount": 3200,
        "phone": "139****5678",
        "address": "北京市朝阳区xxx",
        "delivery_time": "2026-04-04T18:00:00",
        "remark": "不要香菜",
        "item_list": [
            {"product_name": "烤鸭", "count": 1, "origin_amount": 3200, "product_id": "P001"}
        ],
    }
    body_dict = {"event": "new_order", "data": order_data}
    payload = _json.dumps(body_dict)
    sign = _douyin_sign(payload, ts, secret)

    mock_adapter = MagicMock()
    mock_adapter.receive_order = AsyncMock(return_value={
        "order_id": str(uuid.uuid4()),
        "order_no": "ORD20260404002",
    })

    with patch.dict(os.environ, {"DOUYIN_APP_SECRET": secret}):
        import importlib
        import api.webhook_routes as wh_mod
        importlib.reload(wh_mod)

        with patch.object(wh_mod, "DeliveryPlatformAdapter", return_value=mock_adapter):
            app = FastAPI()
            app.include_router(wh_mod.router)
            client = TestClient(app, raise_server_exceptions=False)

            resp = client.post(
                "/api/v1/webhook/douyin/order",
                content=payload,
                headers={
                    **BASE_HEADERS,
                    "Content-Type": "application/json",
                    "X-Douyin-Signature": sign,
                    "X-Douyin-Timestamp": ts,
                },
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    mock_adapter.receive_order.assert_awaited_once()
    call_kwargs = mock_adapter.receive_order.call_args.kwargs
    assert call_kwargs["platform"] == "douyin"
    assert call_kwargs["platform_order_id"] == "DY_VALID_001"
    assert call_kwargs["total_fen"] == 3200
    assert call_kwargs["notes"] == "不要香菜"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 6: 微信预支付 — 缺少 X-Tenant-ID → 400
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_wechat_prepay_missing_tenant():
    """预支付接口缺少 X-Tenant-ID header 时应返回 400"""
    app = _make_wechat_app()
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        "/api/v1/trade/payment/wechat/prepay",
        json={
            "order_id": "ORD_TEST_001",
            "total_fen": 8800,
            "openid": "oABC123456",
        },
        # 不传 X-Tenant-ID
    )
    assert resp.status_code == 400
    assert "X-Tenant-ID" in resp.json()["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 7: 微信预支付 — 正常调用 → 200, ok=True, 返回支付参数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_wechat_prepay_success():
    """预支付正常调用时应返回 ok=True 及 prepay_id"""
    mock_svc = MagicMock()
    mock_svc.create_prepay = AsyncMock(return_value={
        "prepay_id": "px_test456",
        "sign": "ABCDEF123456",
        "nonce_str": "RANDOMNONCE",
        "timestamp": str(int(time.time())),
    })

    with patch("api.wechat_pay_routes.get_wechat_pay_service", return_value=mock_svc):
        app = _make_wechat_app()
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/api/v1/trade/payment/wechat/prepay",
            json={
                "order_id": "ORD_TEST_002",
                "total_fen": 12800,
                "description": "屯象OS堂食订单",
                "openid": "oXYZ987654",
            },
            headers=BASE_HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["prepay_id"] == "px_test456"
    mock_svc.create_prepay.assert_awaited_once()
    call_kwargs = mock_svc.create_prepay.call_args.kwargs
    assert call_kwargs["out_trade_no"] == "ORD_TEST_002"
    assert call_kwargs["total_fen"] == 12800
    assert call_kwargs["openid"] == "oXYZ987654"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 8: 微信支付回调 — 验签失败 → 返回 code=FAIL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_wechat_callback_verify_fail():
    """微信支付回调验签失败时应返回 code=FAIL，不抛 500"""
    mock_svc = MagicMock()
    mock_svc.verify_callback = AsyncMock(side_effect=ValueError("微信回调签名无效"))

    with patch("api.wechat_pay_routes.get_wechat_pay_service", return_value=mock_svc):
        app = _make_wechat_app()
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/api/v1/trade/payment/wechat/callback",
            content=b'{"resource": {"ciphertext": "bad"}}',
            headers={"Content-Type": "application/json"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "FAIL"
    assert "签名" in body["message"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 9: 微信查询订单 — 正常 → 200, ok=True, 返回 trade_state
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_wechat_query_order_success():
    """主动查询订单状态正常时应返回 ok=True 及 trade_state"""
    mock_svc = MagicMock()
    mock_svc.query_order = AsyncMock(return_value={
        "trade_state": "SUCCESS",
        "out_trade_no": "ORD_QUERY_001",
        "transaction_id": "TXN20260404001",
        "amount": {"total": 8800},
    })

    with patch("api.wechat_pay_routes.get_wechat_pay_service", return_value=mock_svc):
        app = _make_wechat_app()
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get(
            "/api/v1/trade/payment/wechat/query/ORD_QUERY_001",
            headers=BASE_HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["trade_state"] == "SUCCESS"
    assert body["data"]["transaction_id"] == "TXN20260404001"
    mock_svc.query_order.assert_awaited_once_with("ORD_QUERY_001")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 10: 微信退款 — 退款金额超过订单金额 → 400
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_wechat_refund_amount_exceeds_total():
    """退款金额超过订单金额时应返回 400"""
    app = _make_wechat_app()
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        "/api/v1/trade/payment/wechat/refund",
        json={
            "order_id": "ORD_REFUND_001",
            "total_fen": 5000,
            "refund_fen": 9999,   # 超出订单金额
            "reason": "顾客取消",
        },
        headers=BASE_HEADERS,
    )

    assert resp.status_code == 400
    assert "退款金额不能超过订单金额" in resp.json()["detail"]
