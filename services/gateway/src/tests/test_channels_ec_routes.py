"""test_channels_ec_routes — VC-1.1 Gateway 视频号小店回调路由覆盖

Tier 2 覆盖：
  1. GET /api/v1/channels-ec/callback — URL 验签成功（返回 echostr）
  2. GET /api/v1/channels-ec/callback — 签名失败返回 403
  3. GET /api/v1/channels-ec/callback — 缺少参数返回 400
  4. POST /api/v1/channels-ec/callback — 有效签名转发至 tx-trade
  5. POST /api/v1/channels-ec/callback — 签名无效返回 403
  6. POST /api/v1/channels-ec/callback — tx-trade 超时返回 504
"""

from __future__ import annotations

import hashlib
import os
import sys
import time
import types
from unittest.mock import AsyncMock, patch

_TESTS_DIR = os.path.dirname(__file__)
_SRC_DIR = os.path.abspath(os.path.join(_TESTS_DIR, ".."))
_ROOT_DIR = os.path.abspath(os.path.join(_TESTS_DIR, "..", "..", "..", ".."))

for _p in [_SRC_DIR, _ROOT_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _ensure_pkg(name: str, path: str) -> None:
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = [path]
        mod.__package__ = name
        sys.modules[name] = mod


_ensure_pkg("src", _SRC_DIR)
_ensure_pkg("src.api", os.path.join(_SRC_DIR, "api"))

os.environ["CHANNELS_EC_APP_ID"] = "wx_test_appid"
os.environ["CHANNELS_EC_TOKEN"] = "test_token_123"
os.environ["CHANNELS_EC_ENCODING_AES_KEY"] = ""
os.environ["TRADE_WEBHOOK_BASE"] = "http://tx-trade:8001"
# 清除代理避免 httpx.AsyncClient 初始化时检测到 SOCKS 代理
os.environ.pop("ALL_PROXY", None)
os.environ.pop("all_proxy", None)
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.channels_ec_routes import router


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def app() -> FastAPI:
    _app = FastAPI()
    _app.include_router(router)
    return _app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# ─── 签名生成（与 Gateway 端算法一致） ─────────────────────────────────────────

def _gen_sign(token: str, timestamp: str, nonce: str) -> str:
    sign_list = sorted([token, timestamp, nonce])
    sign_str = "".join(sign_list)
    return hashlib.sha1(sign_str.encode("utf-8")).hexdigest()


# ─── GET /callback — URL 验签 ────────────────────────────────────────────────


class TestGetCallback:
    """微信配置回调 URL 时的 GET 验签"""

    def test_verify_success_returns_echostr(self, client):
        """签名正确时返回 echostr"""
        ts = str(int(time.time()))
        nonce = "123456"
        echostr = "echostr_test_value_2026"
        sig = _gen_sign("test_token_123", ts, nonce)

        resp = client.get(
            "/api/v1/channels-ec/callback",
            params={"signature": sig, "timestamp": ts, "nonce": nonce, "echostr": echostr},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["msg"] == echostr

    def test_verify_success_without_echostr(self, client):
        """签名正确但没有 echostr 时返回 ok"""
        ts = str(int(time.time()))
        nonce = "654321"
        sig = _gen_sign("test_token_123", ts, nonce)

        resp = client.get(
            "/api/v1/channels-ec/callback",
            params={"signature": sig, "timestamp": ts, "nonce": nonce},
        )
        assert resp.status_code == 200
        assert resp.json()["msg"] == "ok"

    def test_verify_bad_signature_returns_403(self, client):
        """签名错误时返回 403"""
        ts = str(int(time.time()))
        resp = client.get(
            "/api/v1/channels-ec/callback",
            params={"signature": "bad_sig", "timestamp": ts, "nonce": "123456"},
        )
        assert resp.status_code == 403

    def test_verify_expired_timestamp_returns_403(self, client):
        """超时签名（>300s）返回 403"""
        ts = str(int(time.time()) - 600)
        nonce = "111111"
        sig = _gen_sign("test_token_123", ts, nonce)

        resp = client.get(
            "/api/v1/channels-ec/callback",
            params={"signature": sig, "timestamp": ts, "nonce": nonce},
        )
        assert resp.status_code == 403

    def test_verify_missing_params_returns_400(self, client):
        """缺少签名参数时返回 400"""
        resp = client.get(
            "/api/v1/channels-ec/callback",
            params={"signature": "abc"},
        )
        assert resp.status_code == 400

    def test_verify_no_params_returns_400(self, client):
        """没有签名参数时返回 400"""
        resp = client.get("/api/v1/channels-ec/callback")
        assert resp.status_code == 400


# ─── POST /callback — 事件推送 ────────────────────────────────────────────────


class TestPostCallback:
    """视频号小店事件推送"""

    def test_post_valid_signature_forwards_to_trade(self, client):
        """有效签名转发到 tx-trade"""
        ts = str(int(time.time()))
        nonce = "999999"
        sig = _gen_sign("test_token_123", ts, nonce)

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.json = lambda: {"ok": True, "data": {"internal_order_id": "ord_001"}}
        mock_resp.raise_for_status = lambda: None

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_resp

        with patch.object(httpx, "AsyncClient", return_value=mock_client):
            resp = client.post(
                "/api/v1/channels-ec/callback",
                json={"event": "order_create", "order_id": "ec_001"},
                headers={
                    "X-Wechat-Signature": sig,
                    "X-Wechat-Timestamp": ts,
                    "X-Wechat-Nonce": nonce,
                    "X-Tenant-ID": "tenant_001",
                    "X-Store-ID": "store_001",
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    def test_post_invalid_signature_returns_403(self, client):
        """签名无效返回 403"""
        ts = str(int(time.time()))
        resp = client.post(
            "/api/v1/channels-ec/callback",
            json={"event": "order_create"},
            headers={
                "X-Wechat-Signature": "bad_sig",
                "X-Wechat-Timestamp": ts,
                "X-Wechat-Nonce": "123456",
            },
        )
        assert resp.status_code == 403

    def test_post_forward_timeout_returns_504(self, client):
        """tx-trade 超时返回 504"""
        ts = str(int(time.time()))
        nonce = "888888"
        sig = _gen_sign("test_token_123", ts, nonce)

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post.side_effect = httpx.TimeoutException("timeout")

        with patch.object(httpx, "AsyncClient", return_value=mock_client):
            resp = client.post(
                "/api/v1/channels-ec/callback",
                json={"event": "order_pay", "order_id": "ec_002"},
                headers={
                    "X-Wechat-Signature": sig,
                    "X-Wechat-Timestamp": ts,
                    "X-Wechat-Nonce": nonce,
                },
            )
        assert resp.status_code == 504

    def test_post_forward_connect_error_returns_502(self, client):
        """无法连接 tx-trade 返回 502"""
        ts = str(int(time.time()))
        nonce = "777777"
        sig = _gen_sign("test_token_123", ts, nonce)

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post.side_effect = httpx.ConnectError("refused")

        with patch.object(httpx, "AsyncClient", return_value=mock_client):
            resp = client.post(
                "/api/v1/channels-ec/callback",
                json={"event": "order_refund", "order_id": "ec_003"},
                headers={
                    "X-Wechat-Signature": sig,
                    "X-Wechat-Timestamp": ts,
                    "X-Wechat-Nonce": nonce,
                },
            )
        assert resp.status_code == 502

    def test_post_bad_json_returns_400(self, client):
        """非 JSON 请求体返回 400"""
        ts = str(int(time.time()))
        nonce = "666666"
        sig = _gen_sign("test_token_123", ts, nonce)

        resp = client.post(
            "/api/v1/channels-ec/callback",
            content="not-json-body",
            headers={
                "X-Wechat-Signature": sig,
                "X-Wechat-Timestamp": ts,
                "X-Wechat-Nonce": nonce,
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 400
