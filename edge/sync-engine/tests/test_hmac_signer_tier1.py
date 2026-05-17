"""edge/sync-engine HMAC 客户端签名 Tier 1 测试

审计 NEW-P0 follow-up：验证 EdgeHmacSigner 与服务端
services/tx-trade/src/routers/sync_ingest_router.py::verify_edge_sync_auth
的 HMAC 计算严格对称（同公式、同顺序、同密钥）。

不连真服务，纯单元测试 — 服务端校验逻辑也用同样的 hmac.compare_digest 比对。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

# tests 目录在 edge/sync-engine/tests/，src 在 edge/sync-engine/src/
_SRC = str(Path(__file__).resolve().parent.parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from hmac_signer import EdgeHmacSigner, build_sync_headers  # noqa: E402


class TestEdgeHmacSignerBasics:
    """基础构造与 sign_headers 输出形态。"""

    def test_init_rejects_empty_args(self):
        with pytest.raises(ValueError):
            EdgeHmacSigner("", "tenant-1", "secret-1")
        with pytest.raises(ValueError):
            EdgeHmacSigner("store-1", "", "secret-1")
        with pytest.raises(ValueError):
            EdgeHmacSigner("store-1", "tenant-1", "")

    def test_sign_headers_returns_5_keys(self):
        signer = EdgeHmacSigner("store-1", "tenant-1", "shared-secret")
        h = signer.sign_headers()
        assert set(h.keys()) == {
            "X-Edge-Store-Id",
            "X-Edge-Tenant-Id",
            "X-Edge-Sync-Ts",
            "X-Edge-Sync-Nonce",
            "X-Edge-Store-Token",
        }
        assert h["X-Edge-Store-Id"] == "store-1"
        assert h["X-Edge-Tenant-Id"] == "tenant-1"
        assert len(h["X-Edge-Sync-Nonce"]) == 32  # uuid4 hex


class TestHmacComputationSymmetric:
    """与服务端 verify_edge_sync_auth 公式对称。

    服务端公式（services/tx-trade/src/routers/sync_ingest_router.py L126-127）:
        msg = f"{store_id}.{tenant_id}.{ts}.{nonce}".encode("utf-8")
        expected = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    """

    def test_signature_matches_server_side_formula(self):
        store_id = "czyz-store-001"
        tenant_id = "tenant-uuid-aaa"
        secret = "production-shared-secret-32bytes"
        ts = 1234567890
        nonce = "deadbeef0123456789abcdef00000000"

        signer = EdgeHmacSigner(store_id, tenant_id, secret)
        h = signer.sign_headers(ts=ts, nonce=nonce)

        # 客户端生成的 token
        client_token = h["X-Edge-Store-Token"]

        # 用服务端的同公式独立计算
        msg = f"{store_id}.{tenant_id}.{ts}.{nonce}".encode("utf-8")
        server_expected = hmac.new(
            secret.encode("utf-8"), msg, hashlib.sha256
        ).hexdigest()

        assert client_token == server_expected
        # 用 compare_digest 模拟服务端校验
        assert hmac.compare_digest(client_token, server_expected)

    def test_different_secret_produces_different_signature(self):
        a = EdgeHmacSigner("s1", "t1", "secret-a").sign_headers(ts=1, nonce="n")
        b = EdgeHmacSigner("s1", "t1", "secret-b").sign_headers(ts=1, nonce="n")
        assert a["X-Edge-Store-Token"] != b["X-Edge-Store-Token"]

    def test_different_nonce_produces_different_signature(self):
        s = EdgeHmacSigner("s1", "t1", "secret-a")
        a = s.sign_headers(ts=1, nonce="n1")
        b = s.sign_headers(ts=1, nonce="n2")
        assert a["X-Edge-Store-Token"] != b["X-Edge-Store-Token"]

    def test_different_ts_produces_different_signature(self):
        s = EdgeHmacSigner("s1", "t1", "secret-a")
        a = s.sign_headers(ts=1, nonce="n1")
        b = s.sign_headers(ts=2, nonce="n1")
        assert a["X-Edge-Store-Token"] != b["X-Edge-Store-Token"]


class TestSendTimeFreshness:
    """ts 必须是 send-time（每次 sign_headers 调用即时生成），不能是写入时。"""

    def test_consecutive_calls_produce_distinct_nonces(self):
        s = EdgeHmacSigner("s1", "t1", "secret")
        nonces = {s.sign_headers()["X-Edge-Sync-Nonce"] for _ in range(50)}
        assert len(nonces) == 50, "nonce 必须每次新生成（uuid4 实践上无碰撞）"

    def test_default_ts_close_to_now(self):
        before = int(time.time())
        h = EdgeHmacSigner("s1", "t1", "secret").sign_headers()
        after = int(time.time())
        ts = int(h["X-Edge-Sync-Ts"])
        assert before <= ts <= after, "默认 ts 必须取当前时间，非历史值"


class TestFromEnv:
    """env-driven 工厂方法行为。"""

    def test_from_env_returns_none_without_secret(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            assert EdgeHmacSigner.from_env("tenant-1") is None

    def test_from_env_returns_none_without_store_id(self):
        with mock.patch.dict(
            os.environ,
            {"EDGE_SYNC_HMAC_SECRET": "secret-1"},
            clear=True,
        ):
            assert EdgeHmacSigner.from_env("tenant-1") is None

    def test_from_env_returns_none_without_tenant_id(self):
        with mock.patch.dict(
            os.environ,
            {
                "EDGE_SYNC_HMAC_SECRET": "secret-1",
                "EDGE_STORE_ID": "store-1",
            },
            clear=True,
        ):
            assert EdgeHmacSigner.from_env("") is None

    def test_from_env_succeeds_with_all_three(self):
        with mock.patch.dict(
            os.environ,
            {
                "EDGE_SYNC_HMAC_SECRET": "secret-1",
                "EDGE_STORE_ID": "store-1",
            },
            clear=True,
        ):
            signer = EdgeHmacSigner.from_env("tenant-1")
            assert signer is not None
            h = signer.sign_headers()
            assert h["X-Edge-Store-Id"] == "store-1"
            assert h["X-Edge-Tenant-Id"] == "tenant-1"


class TestBuildSyncHeaders:
    """便捷函数：包含 X-Tenant-ID 和（如果 env 配置）5 个签名 header。"""

    def test_dev_mode_returns_only_tenant_id(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            h = build_sync_headers("tenant-1")
            assert h == {"X-Tenant-ID": "tenant-1"}

    def test_production_mode_includes_signature_headers(self):
        with mock.patch.dict(
            os.environ,
            {
                "EDGE_SYNC_HMAC_SECRET": "secret-1",
                "EDGE_STORE_ID": "store-1",
            },
            clear=True,
        ):
            h = build_sync_headers("tenant-1")
            assert h["X-Tenant-ID"] == "tenant-1"
            assert "X-Edge-Store-Id" in h
            assert "X-Edge-Sync-Ts" in h
            assert "X-Edge-Sync-Nonce" in h
            assert "X-Edge-Store-Token" in h
            assert h["X-Edge-Store-Id"] == "store-1"
            assert h["X-Edge-Tenant-Id"] == "tenant-1"


class TestReplayProtectionContract:
    """与服务端 nonce 防重放契约对齐。

    服务端 verify_edge_sync_auth 用 (store_id, nonce) 作为 nonce_key 防重放，
    客户端必须保证每次 sign_headers 输出的 (store_id, nonce) 在 5 分钟窗口内
    全局唯一，否则同一签名会被服务端拒为重放。
    """

    def test_distinct_nonces_under_load(self):
        """模拟 200 桌高峰下 1 秒内 1000 次签名，nonce 必须无重复。"""
        s = EdgeHmacSigner("store-czyz-001", "tenant-1", "secret")
        nonces = set()
        for _ in range(1000):
            n = s.sign_headers()["X-Edge-Sync-Nonce"]
            assert n not in nonces, f"nonce 重复：{n}"
            nonces.add(n)
        assert len(nonces) == 1000


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
