"""Sprint E3 — 小红书核销 TDD 测试

覆盖：
  · webhook_signature：compute / verify 多场景（valid / missing / skew / hmac mismatch）
  · extract_xhs_headers：大小写不敏感
  · oauth_token_service：stub exchanger / code → token / refresh / parse_error
  · TokenPair 属性（needs_refresh / is_expired）
  · v287 迁移静态断言

不覆盖（需 DB + FastAPI integration test）：
  · XhsVerificationService（webhook 端到端）
  · API 端点
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.adapters.xiaohongshu.src.oauth_token_service import (  # noqa: E402
    AUTH_ERROR_THRESHOLD,
    DEFAULT_ACCESS_TOKEN_TTL,
    TokenPair,
    XhsOAuthError,
    XhsOAuthTokenService,
)
from shared.adapters.xiaohongshu.src.webhook_signature import (  # noqa: E402
    DEFAULT_MAX_SKEW_SECONDS,
    VerificationResult,
    compute_signature,
    extract_xhs_headers,
    verify_signature,
)

SECRET = "test_webhook_secret_32_char_xxxxxxxx"
BODY = b'{"verify_code":"XHS123","pay_price":14900}'


def _run(coro):
    return asyncio.run(coro)


# ─────────────────────────────────────────────────────────────
# 1. compute_signature
# ─────────────────────────────────────────────────────────────


class TestComputeSignature:
    def test_stable_for_same_inputs(self):
        sig_a = compute_signature(
            secret=SECRET, timestamp=1700000000, nonce="abc", body=BODY
        )
        sig_b = compute_signature(
            secret=SECRET, timestamp=1700000000, nonce="abc", body=BODY
        )
        assert sig_a == sig_b

    def test_differs_when_body_changes(self):
        sig_a = compute_signature(
            secret=SECRET, timestamp=1700000000, nonce="abc", body=BODY
        )
        sig_b = compute_signature(
            secret=SECRET,
            timestamp=1700000000,
            nonce="abc",
            body=b'{"tampered":true}',
        )
        assert sig_a != sig_b

    def test_differs_when_nonce_changes(self):
        sig_a = compute_signature(
            secret=SECRET, timestamp=1700000000, nonce="nonce1", body=BODY
        )
        sig_b = compute_signature(
            secret=SECRET, timestamp=1700000000, nonce="nonce2", body=BODY
        )
        assert sig_a != sig_b

    def test_accepts_str_or_bytes_body(self):
        sig_bytes = compute_signature(
            secret=SECRET, timestamp=1700000000, nonce="n", body=BODY
        )
        sig_str = compute_signature(
            secret=SECRET,
            timestamp=1700000000,
            nonce="n",
            body=BODY.decode(),
        )
        assert sig_bytes == sig_str

    def test_hex_lowercase_output(self):
        sig = compute_signature(
            secret=SECRET, timestamp=1700000000, nonce="n", body=BODY
        )
        # 64 chars hex
        assert len(sig) == 64
        assert all(c in "0123456789abcdef" for c in sig)

    def test_matches_manual_hmac_sha256(self):
        ts = 1700000000
        nonce = "manual_test"
        msg = f"{ts}\n{nonce}\n{BODY.decode()}".encode()
        expected = hmac.new(SECRET.encode(), msg, hashlib.sha256).hexdigest()
        actual = compute_signature(
            secret=SECRET, timestamp=ts, nonce=nonce, body=BODY
        )
        assert actual == expected


# ─────────────────────────────────────────────────────────────
# 2. verify_signature
# ─────────────────────────────────────────────────────────────


class TestVerifySignature:
    def _valid_inputs(self):
        ts = int(time.time())
        nonce = "valid_nonce_001"
        sig = compute_signature(
            secret=SECRET, timestamp=ts, nonce=nonce, body=BODY
        )
        return {
            "secret": SECRET,
            "signature": sig,
            "timestamp": ts,
            "nonce": nonce,
            "body": BODY,
        }

    def test_valid_happy_path(self):
        result = verify_signature(**self._valid_inputs())
        assert result.ok is True
        assert result.error_code is None

    def test_missing_signature(self):
        inputs = self._valid_inputs()
        inputs["signature"] = None
        result = verify_signature(**inputs)
        assert result.ok is False
        assert result.error_code == "MISSING_HEADER"

    def test_missing_timestamp(self):
        inputs = self._valid_inputs()
        inputs["timestamp"] = None
        result = verify_signature(**inputs)
        assert result.ok is False
        assert result.error_code == "MISSING_HEADER"

    def test_missing_nonce(self):
        inputs = self._valid_inputs()
        inputs["nonce"] = ""
        result = verify_signature(**inputs)
        assert result.ok is False

    def test_invalid_timestamp_type(self):
        inputs = self._valid_inputs()
        inputs["timestamp"] = "not_a_number"
        result = verify_signature(**inputs)
        assert result.ok is False
        assert result.error_code == "INVALID_TIMESTAMP"

    def test_timestamp_too_old(self):
        """时间偏差 > max_skew 秒 → 拒绝"""
        ts_old = int(time.time()) - 1000
        sig = compute_signature(
            secret=SECRET, timestamp=ts_old, nonce="old", body=BODY
        )
        result = verify_signature(
            secret=SECRET,
            signature=sig,
            timestamp=ts_old,
            nonce="old",
            body=BODY,
        )
        assert result.ok is False
        assert result.error_code == "TIMESTAMP_TOO_OLD"

    def test_timestamp_future_also_rejected(self):
        ts_future = int(time.time()) + 1000
        sig = compute_signature(
            secret=SECRET, timestamp=ts_future, nonce="f", body=BODY
        )
        result = verify_signature(
            secret=SECRET,
            signature=sig,
            timestamp=ts_future,
            nonce="f",
            body=BODY,
        )
        assert result.ok is False
        assert result.error_code == "TIMESTAMP_TOO_OLD"

    def test_hmac_mismatch_body_tampered(self):
        ts = int(time.time())
        sig = compute_signature(
            secret=SECRET, timestamp=ts, nonce="n", body=BODY
        )
        result = verify_signature(
            secret=SECRET,
            signature=sig,
            timestamp=ts,
            nonce="n",
            body=b'{"tampered":true}',
        )
        assert result.ok is False
        assert result.error_code == "HMAC_MISMATCH"

    def test_hmac_mismatch_wrong_secret(self):
        inputs = self._valid_inputs()
        inputs["secret"] = "different_secret"
        result = verify_signature(**inputs)
        assert result.ok is False
        assert result.error_code == "HMAC_MISMATCH"

    def test_custom_max_skew(self):
        ts_old = int(time.time()) - 100
        sig = compute_signature(
            secret=SECRET, timestamp=ts_old, nonce="n", body=BODY
        )
        # 给 200s 窗口 OK
        ok_result = verify_signature(
            secret=SECRET,
            signature=sig,
            timestamp=ts_old,
            nonce="n",
            body=BODY,
            max_skew_seconds=200,
        )
        assert ok_result.ok is True
        # 50s 窗口拒绝
        rejected = verify_signature(
            secret=SECRET,
            signature=sig,
            timestamp=ts_old,
            nonce="n",
            body=BODY,
            max_skew_seconds=50,
        )
        assert rejected.ok is False

    def test_default_max_skew_is_300s(self):
        assert DEFAULT_MAX_SKEW_SECONDS == 300


# ─────────────────────────────────────────────────────────────
# 3. extract_xhs_headers
# ─────────────────────────────────────────────────────────────


class TestExtractXhsHeaders:
    def test_lowercase_keys(self):
        headers = {
            "x-xhs-signature": "abc",
            "x-xhs-timestamp": "1700000000",
            "x-xhs-nonce": "n",
        }
        out = extract_xhs_headers(headers)
        assert out["signature"] == "abc"
        assert out["timestamp"] == "1700000000"
        assert out["nonce"] == "n"

    def test_mixed_case_keys(self):
        headers = {
            "X-Xhs-Signature": "abc",
            "X-XHS-Timestamp": "1700000000",
            "x-xhs-Nonce": "n",
        }
        out = extract_xhs_headers(headers)
        assert out["signature"] == "abc"
        assert out["timestamp"] == "1700000000"
        assert out["nonce"] == "n"

    def test_missing_returns_none(self):
        out = extract_xhs_headers({"content-type": "json"})
        assert out == {"signature": None, "timestamp": None, "nonce": None}


# ─────────────────────────────────────────────────────────────
# 4. TokenPair
# ─────────────────────────────────────────────────────────────


class TestTokenPair:
    def test_needs_refresh_when_close_to_expiry(self):
        # 到期前 5 分钟 → needs_refresh=True（因 REFRESH_BUFFER=10min）
        expires = datetime.now(tz=timezone.utc) + timedelta(minutes=5)
        pair = TokenPair(
            access_token="a",
            refresh_token="r",
            expires_at=expires,
        )
        assert pair.needs_refresh is True

    def test_does_not_need_refresh_when_fresh(self):
        expires = datetime.now(tz=timezone.utc) + timedelta(hours=1)
        pair = TokenPair(
            access_token="a", refresh_token="r", expires_at=expires
        )
        assert pair.needs_refresh is False

    def test_is_expired(self):
        past = datetime.now(tz=timezone.utc) - timedelta(minutes=1)
        pair = TokenPair(
            access_token="a", refresh_token="r", expires_at=past
        )
        assert pair.is_expired is True

    def test_to_dict_contract(self):
        pair = TokenPair(
            access_token="a",
            refresh_token="r",
            expires_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            scope="read write",
        )
        d = pair.to_dict()
        for key in ("access_token", "refresh_token", "expires_at", "scope"):
            assert key in d
        assert d["expires_at"].startswith("2026-01-01")


# ─────────────────────────────────────────────────────────────
# 5. XhsOAuthTokenService
# ─────────────────────────────────────────────────────────────


class TestXhsOAuthTokenService:
    def test_exchange_code_with_stub(self):
        service = XhsOAuthTokenService(
            app_id="test_app", app_secret="test_secret"
        )
        pair = _run(service.exchange_code_for_token(code="auth_xxx"))
        assert pair.access_token.startswith("stub_access_")
        assert pair.refresh_token.startswith("stub_refresh_")
        assert not pair.is_expired

    def test_refresh_with_stub(self):
        service = XhsOAuthTokenService(
            app_id="test_app", app_secret="test_secret"
        )
        pair = _run(service.refresh_access_token(refresh_token="old_refresh_12345678"))
        assert pair.access_token.startswith("stub_access_refreshed_")

    def test_exchange_code_with_custom_exchanger(self):
        async def custom(grant):
            return {
                "access_token": "custom_access",
                "refresh_token": "custom_refresh",
                "expires_in": 3600,
                "scope": "scope_x",
            }

        service = XhsOAuthTokenService(
            app_id="x", app_secret="y", token_exchanger=custom
        )
        pair = _run(service.exchange_code_for_token(code="c"))
        assert pair.access_token == "custom_access"
        assert pair.scope == "scope_x"

    def test_exchange_error_response_raises(self):
        async def err(grant):
            return {
                "error": "invalid_grant",
                "error_description": "code expired",
            }

        service = XhsOAuthTokenService(
            app_id="x", app_secret="y", token_exchanger=err
        )
        with pytest.raises(XhsOAuthError, match="invalid_grant"):
            _run(service.exchange_code_for_token(code="bad"))

    def test_exchange_missing_fields_raises(self):
        async def partial(grant):
            return {"access_token": "a"}  # 缺 refresh_token

        service = XhsOAuthTokenService(
            app_id="x", app_secret="y", token_exchanger=partial
        )
        with pytest.raises(XhsOAuthError, match="refresh_token"):
            _run(service.exchange_code_for_token(code="c"))

    def test_ensure_fresh_token_skips_if_fresh(self):
        """需 mock exchanger 以验证 NOT 被调用"""
        called = []

        async def tracking(grant):
            called.append(grant)
            return {
                "access_token": "new",
                "refresh_token": "new_r",
                "expires_in": 3600,
            }

        service = XhsOAuthTokenService(
            app_id="x", app_secret="y", token_exchanger=tracking
        )
        fresh = TokenPair(
            access_token="a",
            refresh_token="r",
            expires_at=datetime.now(tz=timezone.utc) + timedelta(hours=1),
        )
        result = _run(service.ensure_fresh_token(fresh))
        assert result.access_token == "a"  # 原样返回
        assert called == []  # exchanger 未被调

    def test_ensure_fresh_refreshes_when_near_expiry(self):
        async def refresh_exchanger(grant):
            return {
                "access_token": "refreshed",
                "refresh_token": "new_r",
                "expires_in": 7200,
            }

        service = XhsOAuthTokenService(
            app_id="x", app_secret="y", token_exchanger=refresh_exchanger
        )
        near_expiry = TokenPair(
            access_token="old",
            refresh_token="r",
            expires_at=datetime.now(tz=timezone.utc) + timedelta(minutes=3),
        )
        result = _run(service.ensure_fresh_token(near_expiry))
        assert result.access_token == "refreshed"

    def test_default_ttl_is_2_hours(self):
        assert timedelta(hours=2) == DEFAULT_ACCESS_TOKEN_TTL

    def test_auth_error_threshold(self):
        assert AUTH_ERROR_THRESHOLD == 3


# ─────────────────────────────────────────────────────────────
# 6. VerificationResult 契约
# ─────────────────────────────────────────────────────────────


class TestVerificationResult:
    def test_success_factory(self):
        r = VerificationResult.success(timestamp=1700000000, nonce="n")
        assert r.ok is True
        assert r.timestamp == 1700000000

    def test_failure_factory(self):
        r = VerificationResult.failure("HMAC_MISMATCH", "bad sig")
        assert r.ok is False
        assert r.error_code == "HMAC_MISMATCH"
        assert r.error_message == "bad sig"


# ─────────────────────────────────────────────────────────────
# 7. v287 迁移静态断言
# ─────────────────────────────────────────────────────────────


class TestV287Migration:
    @pytest.fixture
    def migration_source(self) -> str:
        path = (
            ROOT
            / "shared"
            / "db-migrations"
            / "versions"
            / "v287_xiaohongshu_verification.py"
        )
        return path.read_text(encoding="utf-8")

    def test_revision_chain(self, migration_source):
        assert 'revision = "v287_xhs_verify"' in migration_source
        assert 'down_revision = "v286_dish_publish"' in migration_source

    def test_both_tables(self, migration_source):
        assert "xiaohongshu_shop_bindings" in migration_source
        assert "xiaohongshu_verify_events" in migration_source

    def test_binding_status_states(self, migration_source):
        for s in ("pending", "active", "expired", "suspended", "unbound"):
            assert f"'{s}'" in migration_source

    def test_event_transform_statuses(self, migration_source):
        for s in (
            "pending",
            "transformed",
            "skipped",
            "failed",
            "replayed",
        ):
            assert f"'{s}'" in migration_source

    def test_has_webhook_secret_field(self, migration_source):
        assert "webhook_secret" in migration_source

    def test_has_oauth_token_fields(self, migration_source):
        for f in ("access_token", "refresh_token", "token_expires_at", "scope"):
            assert f in migration_source

    def test_unique_shop_per_store(self, migration_source):
        assert "ux_xhs_bindings_store" in migration_source

    def test_unique_shop_code_reverse_lookup(self, migration_source):
        assert "ux_xhs_bindings_shop_code" in migration_source

    def test_idempotent_event_sha(self, migration_source):
        assert "ux_xhs_verify_events_sha" in migration_source

    def test_rls_both_tables(self, migration_source):
        assert (
            "ALTER TABLE xiaohongshu_shop_bindings ENABLE ROW LEVEL SECURITY"
            in migration_source
        )
        assert (
            "ALTER TABLE xiaohongshu_verify_events ENABLE ROW LEVEL SECURITY"
            in migration_source
        )

    def test_has_signature_fields(self, migration_source):
        assert "signature_valid" in migration_source
        assert "signature_error" in migration_source

    def test_has_consecutive_auth_errors(self, migration_source):
        assert "consecutive_auth_errors" in migration_source
