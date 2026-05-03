"""物流适配器单元测试

覆盖:
  - 初始化
  - query_track (成功 / 幂等 / API 错误)
  - auto_detect (成功 / 幂等)
  - subscribe_push (成功 / 幂等)
  - 事件发射 (验证 emit_event 被调用)
  - LogisticsAPIError 异常
  - close 方法

通过 mock Kuaidi100Client 避免真实 HTTP 调用。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.adapters.logistics.src.adapter import LogisticsAdapter, LogisticsAPIError  # noqa: E402

CONFIG = {
    "tenant_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "customer": "test_customer",
    "key": "test_key",
}

SAMPLE_TRACK_RESULT = {
    "status": "ok",
    "state": "3",
    "carrier_code": "shunfeng",
    "tracking_no": "SF1234567890",
    "traces": [
        {"time": "2026-04-01 08:00:00", "context": "包裹已揽收"},
        {"time": "2026-04-01 14:00:00", "context": "包裹已到达长沙分拨中心"},
    ],
}

SAMPLE_AUTO_DETECT_RESULT = {
    "carrier_code": "zhongtong",
    "carrier_name": "中通快递",
}

SAMPLE_SUBSCRIBE_RESULT = {
    "status": "ok",
    "subscribed": True,
}


def _run(coro):
    return asyncio.run(coro)


# ─────────────────────────────────────────────────────────────
# 1. 初始化
# ─────────────────────────────────────────────────────────────


class TestInit:
    def test_init_with_config(self):
        adapter = LogisticsAdapter(**CONFIG)
        assert adapter._tenant_id == CONFIG["tenant_id"]
        assert adapter._customer == CONFIG["customer"]
        assert adapter._key == CONFIG["key"]
        assert adapter._client is not None

    def test_init_empty_config(self):
        adapter = LogisticsAdapter()
        assert adapter._tenant_id == ""
        assert adapter._customer == ""
        assert adapter._key == ""


# ─────────────────────────────────────────────────────────────
# 2. query_track
# ─────────────────────────────────────────────────────────────


class TestQueryTrack:
    @patch("shared.adapters.logistics.src.adapter.LogisticsAdapter._emit_sync_event")
    def test_success(self, mock_emit):
        adapter = LogisticsAdapter(**CONFIG)
        adapter._client.query_track = AsyncMock(return_value=SAMPLE_TRACK_RESULT)

        result = _run(adapter.query_track("SF1234567890", "shunfeng"))

        assert result["status"] == "ok"
        assert result["state"] == "3"
        assert len(result["traces"]) == 2
        # 验证事件被发射
        mock_emit.assert_awaited_once()

    @patch("shared.adapters.logistics.src.adapter.LogisticsAdapter._emit_sync_event")
    def test_idempotency_skips_duplicate(self, mock_emit):
        adapter = LogisticsAdapter(**CONFIG)
        adapter._client.query_track = AsyncMock(return_value=SAMPLE_TRACK_RESULT)

        # 第一次调用
        first = _run(adapter.query_track("SF1234567890", "shunfeng"))
        assert first["status"] == "ok"
        assert "duplicate" not in first

        # 第二次调用（相同参数）应被幂等跳过
        second = _run(adapter.query_track("SF1234567890", "shunfeng"))
        assert second["duplicate"] is True

        # _emit_sync_event 应该被调用 2 次（第一次成功 + 幂等跳过也调用）
        assert mock_emit.await_count == 2

    @patch("shared.adapters.logistics.src.adapter.LogisticsAdapter._emit_sync_event")
    def test_different_params_not_idempotent(self, mock_emit):
        adapter = LogisticsAdapter(**CONFIG)
        adapter._client.query_track = AsyncMock(return_value=SAMPLE_TRACK_RESULT)

        first = _run(adapter.query_track("SF1234567890", "shunfeng"))
        assert "duplicate" not in first

        second = _run(adapter.query_track("SF9999999999", "zhongtong"))
        assert "duplicate" not in second

        assert mock_emit.await_count == 2

    @patch("shared.adapters.logistics.src.adapter.LogisticsAdapter._emit_sync_event")
    def test_api_error_raises(self, mock_emit):
        adapter = LogisticsAdapter(**CONFIG)
        adapter._client.query_track = AsyncMock(
            side_effect=LogisticsAPIError("API timeout", code="E_QUERY_FAILED", method="query_track")
        )

        with pytest.raises(LogisticsAPIError, match="API timeout"):
            _run(adapter.query_track("SF1234567890", "shunfeng"))

    @patch("shared.adapters.logistics.src.adapter.LogisticsAdapter._emit_sync_event")
    def test_query_track_without_carrier(self, mock_emit):
        """不传 carrier_code 时，内部应调用 auto_detect"""
        adapter = LogisticsAdapter(**CONFIG)
        adapter._client.auto_detect = AsyncMock(return_value=SAMPLE_AUTO_DETECT_RESULT)
        adapter._client.query_track = AsyncMock(return_value=SAMPLE_TRACK_RESULT)

        result = _run(adapter.query_track("SF1234567890"))
        assert result["status"] == "ok"


# ─────────────────────────────────────────────────────────────
# 3. auto_detect
# ─────────────────────────────────────────────────────────────


class TestAutoDetect:
    @patch("shared.adapters.logistics.src.adapter.LogisticsAdapter._emit_sync_event")
    def test_success(self, mock_emit):
        adapter = LogisticsAdapter(**CONFIG)
        adapter._client.auto_detect = AsyncMock(return_value=SAMPLE_AUTO_DETECT_RESULT)

        result = _run(adapter.auto_detect("SF1234567890"))

        assert result["carrier_code"] == "zhongtong"
        assert result["carrier_name"] == "中通快递"
        mock_emit.assert_awaited_once()

    @patch("shared.adapters.logistics.src.adapter.LogisticsAdapter._emit_sync_event")
    def test_idempotency(self, mock_emit):
        adapter = LogisticsAdapter(**CONFIG)
        adapter._client.auto_detect = AsyncMock(return_value=SAMPLE_AUTO_DETECT_RESULT)

        _run(adapter.auto_detect("SF1234567890"))
        second = _run(adapter.auto_detect("SF1234567890"))
        assert second["duplicate"] is True

    @patch("shared.adapters.logistics.src.adapter.LogisticsAdapter._emit_sync_event")
    def test_error_raises(self, mock_emit):
        adapter = LogisticsAdapter(**CONFIG)
        adapter._client.auto_detect = AsyncMock(
            side_effect=LogisticsAPIError("detect failed", code="E_AUTO_DETECT_FAILED")
        )

        with pytest.raises(LogisticsAPIError, match="detect failed"):
            _run(adapter.auto_detect("UNKNOWN"))


# ─────────────────────────────────────────────────────────────
# 4. subscribe_push
# ─────────────────────────────────────────────────────────────


class TestSubscribePush:
    @patch("shared.adapters.logistics.src.adapter.LogisticsAdapter._emit_sync_event")
    def test_success(self, mock_emit):
        adapter = LogisticsAdapter(**CONFIG)
        adapter._client.subscribe_push = AsyncMock(return_value=SAMPLE_SUBSCRIBE_RESULT)

        result = _run(adapter.subscribe_push("SF1234567890", "shunfeng", "https://example.com/callback"))

        assert result["status"] == "ok"
        assert result["subscribed"] is True
        mock_emit.assert_awaited_once()

    @patch("shared.adapters.logistics.src.adapter.LogisticsAdapter._emit_sync_event")
    def test_idempotency(self, mock_emit):
        adapter = LogisticsAdapter(**CONFIG)
        adapter._client.subscribe_push = AsyncMock(return_value=SAMPLE_SUBSCRIBE_RESULT)

        _run(adapter.subscribe_push("SF1234567890", "shunfeng", "https://example.com/callback"))
        second = _run(adapter.subscribe_push("SF1234567890", "shunfeng", "https://example.com/callback"))
        assert second["duplicate"] is True

    @patch("shared.adapters.logistics.src.adapter.LogisticsAdapter._emit_sync_event")
    def test_error_raises(self, mock_emit):
        adapter = LogisticsAdapter(**CONFIG)
        adapter._client.subscribe_push = AsyncMock(
            side_effect=LogisticsAPIError("subscribe failed", code="E_SUBSCRIBE_FAILED")
        )

        with pytest.raises(LogisticsAPIError, match="subscribe failed"):
            _run(adapter.subscribe_push("SF1234567890", "shunfeng", "https://example.com/callback"))


# ─────────────────────────────────────────────────────────────
# 5. 幂等性方法
# ─────────────────────────────────────────────────────────────


class TestIdempotency:
    def test_idempotency_key_stable(self):
        adapter = LogisticsAdapter(**CONFIG)
        key_a = adapter.idempotency_key("query_track", {"tracking_no": "SF123"})
        key_b = adapter.idempotency_key("query_track", {"tracking_no": "SF123"})
        assert key_a == key_b

    def test_idempotency_key_different(self):
        adapter = LogisticsAdapter(**CONFIG)
        key_a = adapter.idempotency_key("query_track", {"tracking_no": "SF123"})
        key_b = adapter.idempotency_key("query_track", {"tracking_no": "SF999"})
        assert key_a != key_b

    def test_mark_and_check(self):
        adapter = LogisticsAdapter(**CONFIG)
        key = "test_key_123"
        assert adapter.is_duplicate(key) is False
        adapter.mark_idempotent(key)
        assert adapter.is_duplicate(key) is True


# ─────────────────────────────────────────────────────────────
# 6. close
# ─────────────────────────────────────────────────────────────


class TestClose:
    def test_close_clears_nonce_store(self):
        adapter = LogisticsAdapter(**CONFIG)
        adapter.mark_idempotent("some_key")
        assert len(adapter._nonce_store) == 1
        _run(adapter.close())
        assert len(adapter._nonce_store) == 0
