"""小红书适配器单元测试

覆盖:
  - 初始化
  - verify_coupon (成功 / 幂等 / API 错误)
  - sync_poi (绑定门店 / 同步信息 / 幂等 / API 错误)
  - query_reviews (成功 / 幂等 / API 错误)
  - 事件发射 (验证 _emit_sync_event 被调用)
  - XiaohongshuAPIError 异常
  - close 方法

通过 mock 服务类避免真实 HTTP 调用和 DB 依赖。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.adapters.xiaohongshu.src.adapter import XiaohongshuAdapter, XiaohongshuAPIError  # noqa: E402

CONFIG = {
    "tenant_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "app_id": "test_app_id",
    "app_secret": "test_app_secret",
}

SAMPLE_VERIFY_RESULT = {
    "verified": True,
    "record_id": "rec-001",
    "coupon_code": "XHS123",
    "coupon_info": {"type": "group_buy", "paid_fen": 5000},
}

SAMPLE_BIND_RESULT = {
    "action": "created",
    "mapping_id": "map-001",
    "store_id": "store-001",
    "xhs_poi_id": "poi-001",
}

SAMPLE_SYNC_RESULT = {
    "synced": True,
    "store_id": "store-001",
    "api_response": {"code": 0},
}

SAMPLE_REVIEW_RESULT = {
    "store_id": "store-001",
    "notes_count": 2,
    "comments_count": 5,
    "reviews": [
        {
            "source": "xiaohongshu",
            "note_id": "note-001",
            "title": "好吃推荐",
            "author": "吃货小 A",
            "content": "这家店味道不错",
            "likes": 10,
            "comments_count": 2,
            "published_at": "2026-04-01T12:00:00",
            "comments": [
                {"author": "用户X", "content": "确实好吃", "created_at": "2026-04-01T13:00:00"}
            ],
        }
    ],
}


def _run(coro):
    return asyncio.run(coro)


# ─────────────────────────────────────────────────────────────
# 1. 初始化
# ─────────────────────────────────────────────────────────────


class TestInit:
    def test_init_with_config(self):
        adapter = XiaohongshuAdapter(**CONFIG)
        assert adapter._tenant_id == CONFIG["tenant_id"]
        assert adapter._app_id == CONFIG["app_id"]
        assert adapter._app_secret == CONFIG["app_secret"]
        assert adapter._client is not None
        assert adapter._coupon is not None
        assert adapter._poi is not None
        assert adapter._review is not None

    def test_init_minimal(self):
        adapter = XiaohongshuAdapter()
        assert adapter._app_id == ""
        assert adapter._app_secret == ""


# ─────────────────────────────────────────────────────────────
# 2. verify_coupon
# ─────────────────────────────────────────────────────────────


class TestVerifyCoupon:
    @patch("shared.adapters.xiaohongshu.src.adapter.XiaohongshuAdapter._emit_sync_event")
    def test_success(self, mock_emit):
        adapter = XiaohongshuAdapter(**CONFIG)
        adapter._coupon.verify_and_record = AsyncMock(return_value=SAMPLE_VERIFY_RESULT)
        db = MagicMock()

        result = _run(
            adapter.verify_coupon(
                coupon_data={"coupon_code": "XHS123", "store_id": "store-001", "order_id": "order-001", "verified_by": "cashier-001"},
                tenant_id=CONFIG["tenant_id"],
                db=db,
            )
        )

        assert result["verified"] is True
        assert result["record_id"] == "rec-001"
        mock_emit.assert_awaited_once()

    @patch("shared.adapters.xiaohongshu.src.adapter.XiaohongshuAdapter._emit_sync_event")
    def test_idempotency(self, mock_emit):
        adapter = XiaohongshuAdapter(**CONFIG)
        adapter._coupon.verify_and_record = AsyncMock(return_value=SAMPLE_VERIFY_RESULT)
        db = MagicMock()

        coupon_data = {"coupon_code": "XHS123", "store_id": "store-001"}

        first = _run(adapter.verify_coupon(coupon_data, CONFIG["tenant_id"], db))
        assert first["verified"] is True
        assert "duplicate" not in first

        second = _run(adapter.verify_coupon(coupon_data, CONFIG["tenant_id"], db))
        assert second["duplicate"] is True

    @patch("shared.adapters.xiaohongshu.src.adapter.XiaohongshuAdapter._emit_sync_event")
    def test_api_error_raises(self, mock_emit):
        adapter = XiaohongshuAdapter(**CONFIG)
        adapter._coupon.verify_and_record = AsyncMock(
            side_effect=XiaohongshuAPIError("API timeout", code="E_COUPON_VERIFY_FAILED")
        )
        db = MagicMock()

        with pytest.raises(XiaohongshuAPIError, match="API timeout"):
            _run(adapter.verify_coupon({"coupon_code": "XHS123", "store_id": "store-001"}, CONFIG["tenant_id"], db))


# ─────────────────────────────────────────────────────────────
# 3. sync_poi
# ─────────────────────────────────────────────────────────────


class TestSyncPOI:
    @patch("shared.adapters.xiaohongshu.src.adapter.XiaohongshuAdapter._emit_sync_event")
    def test_bind_and_sync(self, mock_emit):
        adapter = XiaohongshuAdapter(**CONFIG)
        adapter._poi.bind_store = AsyncMock(return_value=SAMPLE_BIND_RESULT)
        adapter._poi.sync_store_info = AsyncMock(return_value=SAMPLE_SYNC_RESULT)
        db = MagicMock()

        result = _run(
            adapter.sync_poi(
                store_data={"store_id": "store-001", "xhs_poi_id": "poi-001", "name": "测试门店"},
                tenant_id=CONFIG["tenant_id"],
                db=db,
            )
        )

        assert "action" in result or "synced" in result
        mock_emit.assert_awaited_once()

    @patch("shared.adapters.xiaohongshu.src.adapter.XiaohongshuAdapter._emit_sync_event")
    def test_sync_only(self, mock_emit):
        adapter = XiaohongshuAdapter(**CONFIG)
        adapter._poi.sync_store_info = AsyncMock(return_value=SAMPLE_SYNC_RESULT)
        db = MagicMock()

        result = _run(
            adapter.sync_poi(
                store_data={"store_id": "store-001", "name": "测试门店"},
                tenant_id=CONFIG["tenant_id"],
                db=db,
            )
        )

        assert result.get("synced") is True
        mock_emit.assert_awaited_once()

    @patch("shared.adapters.xiaohongshu.src.adapter.XiaohongshuAdapter._emit_sync_event")
    def test_idempotency_bind(self, mock_emit):
        adapter = XiaohongshuAdapter(**CONFIG)
        adapter._poi.bind_store = AsyncMock(return_value=SAMPLE_BIND_RESULT)
        adapter._poi.sync_store_info = AsyncMock(return_value=SAMPLE_SYNC_RESULT)
        db = MagicMock()

        store_data = {"store_id": "store-001", "xhs_poi_id": "poi-001"}

        _run(adapter.sync_poi(store_data, CONFIG["tenant_id"], db))
        second = _run(adapter.sync_poi(store_data, CONFIG["tenant_id"], db))
        assert second["duplicate"] is True

    @patch("shared.adapters.xiaohongshu.src.adapter.XiaohongshuAdapter._emit_sync_event")
    def test_bind_error_raises(self, mock_emit):
        adapter = XiaohongshuAdapter(**CONFIG)
        adapter._poi.bind_store = AsyncMock(
            side_effect=XiaohongshuAPIError("bind failed", code="E_POI_BIND_FAILED")
        )
        db = MagicMock()

        with pytest.raises(XiaohongshuAPIError, match="bind failed"):
            _run(adapter.sync_poi({"store_id": "store-001", "xhs_poi_id": "poi-001"}, CONFIG["tenant_id"], db))

    @patch("shared.adapters.xiaohongshu.src.adapter.XiaohongshuAdapter._emit_sync_event")
    def test_sync_error_raises(self, mock_emit):
        adapter = XiaohongshuAdapter(**CONFIG)
        adapter._poi.sync_store_info = AsyncMock(
            side_effect=XiaohongshuAPIError("sync failed", code="E_POI_SYNC_FAILED")
        )
        db = MagicMock()

        with pytest.raises(XiaohongshuAPIError, match="sync failed"):
            _run(adapter.sync_poi({"store_id": "store-001", "name": "测试"}, CONFIG["tenant_id"], db))


# ─────────────────────────────────────────────────────────────
# 4. query_reviews
# ─────────────────────────────────────────────────────────────


class TestQueryReviews:
    @patch("shared.adapters.xiaohongshu.src.adapter.XiaohongshuAdapter._emit_sync_event")
    def test_success(self, mock_emit):
        adapter = XiaohongshuAdapter(**CONFIG)
        adapter._review.crawl_store_reviews = AsyncMock(return_value=SAMPLE_REVIEW_RESULT)
        db = MagicMock()

        result = _run(adapter.query_reviews("store-001", CONFIG["tenant_id"], db))

        assert result["notes_count"] == 2
        assert result["comments_count"] == 5
        assert len(result["reviews"]) == 1
        mock_emit.assert_awaited_once()

    @patch("shared.adapters.xiaohongshu.src.adapter.XiaohongshuAdapter._emit_sync_event")
    def test_idempotency(self, mock_emit):
        adapter = XiaohongshuAdapter(**CONFIG)
        adapter._review.crawl_store_reviews = AsyncMock(return_value=SAMPLE_REVIEW_RESULT)
        db = MagicMock()

        first = _run(adapter.query_reviews("store-001", CONFIG["tenant_id"], db))
        assert "duplicate" not in first

        second = _run(adapter.query_reviews("store-001", CONFIG["tenant_id"], db))
        assert second["duplicate"] is True

    @patch("shared.adapters.xiaohongshu.src.adapter.XiaohongshuAdapter._emit_sync_event")
    def test_api_error_raises(self, mock_emit):
        adapter = XiaohongshuAdapter(**CONFIG)
        adapter._review.crawl_store_reviews = AsyncMock(
            side_effect=XiaohongshuAPIError("crawl failed", code="E_REVIEW_CRAWL_FAILED")
        )
        db = MagicMock()

        with pytest.raises(XiaohongshuAPIError, match="crawl failed"):
            _run(adapter.query_reviews("store-001", CONFIG["tenant_id"], db))

    @patch("shared.adapters.xiaohongshu.src.adapter.XiaohongshuAdapter._emit_sync_event")
    def test_store_not_bound(self, mock_emit):
        adapter = XiaohongshuAdapter(**CONFIG)
        adapter._review.crawl_store_reviews = AsyncMock(
            return_value={"store_id": "store-001", "notes_count": 0, "comments_count": 0, "reviews": [], "error": "store_not_bound"}
        )
        db = MagicMock()

        result = _run(adapter.query_reviews("store-001", CONFIG["tenant_id"], db))
        assert result["notes_count"] == 0
        assert result.get("error") == "store_not_bound"


# ─────────────────────────────────────────────────────────────
# 5. 幂等性方法
# ─────────────────────────────────────────────────────────────


class TestIdempotency:
    def test_idempotency_key_stable(self):
        adapter = XiaohongshuAdapter(**CONFIG)
        key_a = adapter.idempotency_key("verify_coupon", {"coupon_code": "XHS123"})
        key_b = adapter.idempotency_key("verify_coupon", {"coupon_code": "XHS123"})
        assert key_a == key_b

    def test_idempotency_key_different(self):
        adapter = XiaohongshuAdapter(**CONFIG)
        key_a = adapter.idempotency_key("verify_coupon", {"coupon_code": "XHS123"})
        key_b = adapter.idempotency_key("sync_poi", {"store_id": "store-001"})
        assert key_a != key_b

    def test_mark_and_check(self):
        adapter = XiaohongshuAdapter(**CONFIG)
        key = "test_key_123"
        assert adapter.is_duplicate(key) is False
        adapter.mark_idempotent(key)
        assert adapter.is_duplicate(key) is True


# ─────────────────────────────────────────────────────────────
# 6. close
# ─────────────────────────────────────────────────────────────


class TestClose:
    def test_close_clears_nonce_store(self):
        adapter = XiaohongshuAdapter(**CONFIG)
        adapter.mark_idempotent("some_key")
        assert len(adapter._nonce_store) == 1
        _run(adapter.close())
        assert len(adapter._nonce_store) == 0
