"""
Tests for Phase 4 Month 10 — Webhook 订阅与分发系统
Run: python3 -m pytest tests/test_webhooks.py -v
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

with patch("src.core.config", create=True):
    from src.api.webhooks import (
        SUPPORTED_EVENTS,
        MAX_SUBS_PER_DEV,
        MAX_DELIVERY_RETRIES,
        _hash_secret,
        _sign_payload,
        _validate_events,
        _format_sub,
    )


# ── TestConstants ─────────────────────────────────────────────────────────────

class TestConstants(unittest.TestCase):

    def test_supported_events_count(self):
        self.assertEqual(len(SUPPORTED_EVENTS), 7)

    def test_plugin_events_exist(self):
        self.assertIn("plugin.installed", SUPPORTED_EVENTS)
        self.assertIn("plugin.uninstalled", SUPPORTED_EVENTS)
        self.assertIn("plugin.reviewed", SUPPORTED_EVENTS)

    def test_settlement_events_exist(self):
        self.assertIn("settlement.approved", SUPPORTED_EVENTS)
        self.assertIn("settlement.paid", SUPPORTED_EVENTS)

    def test_rating_event_exists(self):
        self.assertIn("rating.created", SUPPORTED_EVENTS)

    def test_developer_event_exists(self):
        self.assertIn("developer.tier_changed", SUPPORTED_EVENTS)

    def test_max_subs_per_dev(self):
        self.assertEqual(MAX_SUBS_PER_DEV, 10)

    def test_max_delivery_retries(self):
        self.assertEqual(MAX_DELIVERY_RETRIES, 5)


# ── TestHelpers ───────────────────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):

    def test_hash_secret_is_sha256(self):
        h = _hash_secret("mysecret")
        self.assertEqual(len(h), 64)   # sha256 hex = 64 chars
        self.assertIsInstance(h, str)

    def test_hash_secret_deterministic(self):
        self.assertEqual(_hash_secret("abc"), _hash_secret("abc"))

    def test_hash_secret_different_inputs_different_hashes(self):
        self.assertNotEqual(_hash_secret("a"), _hash_secret("b"))

    def test_sign_payload_prefix(self):
        sig = _sign_payload("somehash", '{"event":"ping"}')
        self.assertTrue(sig.startswith("sha256="))

    def test_sign_payload_deterministic(self):
        p = '{"event":"test"}'
        self.assertEqual(_sign_payload("hash", p), _sign_payload("hash", p))


# ── TestValidateEvents ────────────────────────────────────────────────────────

class TestValidateEvents(unittest.TestCase):

    def test_valid_single_event(self):
        _validate_events(["plugin.installed"])  # should not raise

    def test_valid_multiple_events(self):
        _validate_events(["plugin.installed", "settlement.paid"])

    def test_empty_list_valid(self):
        _validate_events([])

    def test_unknown_event_raises_400(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            _validate_events(["unknown.event"])
        self.assertEqual(ctx.exception.status_code, 400)

    def test_mixed_valid_invalid_raises_400(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            _validate_events(["plugin.installed", "bogus.event"])


# ── TestFormatSub ─────────────────────────────────────────────────────────────

class TestFormatSub(unittest.TestCase):

    def _make_sub(self, events_val):
        return {
            "id": "sub-1",
            "developer_id": "dev-1",
            "endpoint_url": "https://example.com/hook",
            "secret_hash": "a" * 64,
            "events": events_val,
            "status": "active",
            "description": "test",
            "failure_count": 0,
            "last_triggered_at": None,
            "created_at": None,
            "updated_at": None,
        }

    def test_events_json_string_deserialized(self):
        sub = self._make_sub('["plugin.installed"]')
        result = _format_sub(sub)
        self.assertIsInstance(result["events"], list)
        self.assertEqual(result["events"], ["plugin.installed"])

    def test_events_already_list(self):
        sub = self._make_sub(["plugin.installed"])
        result = _format_sub(sub)
        self.assertIsInstance(result["events"], list)

    def test_events_invalid_json_returns_empty(self):
        sub = self._make_sub("not-json")
        result = _format_sub(sub)
        self.assertEqual(result["events"], [])

    def test_secret_hash_masked(self):
        sub = self._make_sub("[]")
        result = _format_sub(sub)
        self.assertIn("…", result["secret_hash"])
        # Only first 8 chars + ellipsis
        self.assertEqual(len(result["secret_hash"]), 9)  # 8 + "…" (single char)


# ── TestCreateSubscription ────────────────────────────────────────────────────

class TestCreateSubscription(unittest.IsolatedAsyncioTestCase):

    def _make_db(self, *, dev_exists=True, count=0, dup_url=False):
        db = AsyncMock()

        async def execute_side(stmt, params=None):
            stmt_str = str(stmt)
            mock_row = MagicMock()
            result = MagicMock()

            if "isv_developers" in stmt_str:
                result.fetchone.return_value = MagicMock() if dev_exists else None

            elif "COUNT(*)" in stmt_str:
                mock_row.cnt = count
                result.fetchone.return_value = mock_row

            elif "endpoint_url" in stmt_str and "SELECT id" in stmt_str:
                result.fetchone.return_value = MagicMock() if dup_url else None

            elif "INSERT INTO webhook_subscriptions" in stmt_str:
                result.fetchone.return_value = None

            elif "SELECT * FROM webhook_subscriptions" in stmt_str:
                mock_row._mapping = {
                    "id": "sub-new",
                    "developer_id": "dev-1",
                    "endpoint_url": "https://example.com/hook",
                    "secret_hash": "a" * 64,
                    "events": '["plugin.installed"]',
                    "status": "active",
                    "description": None,
                    "failure_count": 0,
                    "last_triggered_at": None,
                    "created_at": None,
                    "updated_at": None,
                }
                result.fetchone.return_value = mock_row

            return result

        db.execute = execute_side
        db.commit = AsyncMock()
        return db

    async def test_create_success(self):
        from src.api.webhooks import create_subscription, CreateSubscriptionRequest
        db = self._make_db()
        req = CreateSubscriptionRequest(
            developer_id="dev-1",
            endpoint_url="https://example.com/hook",
            secret="mysecret",
            events=["plugin.installed"],
        )
        result = await create_subscription(req, db)
        self.assertIn("id", result)

    async def test_nonexistent_developer_raises_404(self):
        from fastapi import HTTPException
        from src.api.webhooks import create_subscription, CreateSubscriptionRequest
        db = self._make_db(dev_exists=False)
        req = CreateSubscriptionRequest(
            developer_id="no-dev",
            endpoint_url="https://example.com/hook",
            secret="sec",
            events=["plugin.installed"],
        )
        with self.assertRaises(HTTPException) as ctx:
            await create_subscription(req, db)
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_http_url_raises_400(self):
        from fastapi import HTTPException
        from src.api.webhooks import create_subscription, CreateSubscriptionRequest
        db = self._make_db()
        req = CreateSubscriptionRequest(
            developer_id="dev-1",
            endpoint_url="http://insecure.com/hook",
            secret="sec",
            events=["plugin.installed"],
        )
        with self.assertRaises(HTTPException) as ctx:
            await create_subscription(req, db)
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_over_limit_raises_409(self):
        from fastapi import HTTPException
        from src.api.webhooks import create_subscription, CreateSubscriptionRequest
        db = self._make_db(count=MAX_SUBS_PER_DEV)
        req = CreateSubscriptionRequest(
            developer_id="dev-1",
            endpoint_url="https://example.com/hook",
            secret="sec",
            events=["plugin.installed"],
        )
        with self.assertRaises(HTTPException) as ctx:
            await create_subscription(req, db)
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_duplicate_url_raises_409(self):
        from fastapi import HTTPException
        from src.api.webhooks import create_subscription, CreateSubscriptionRequest
        db = self._make_db(dup_url=True)
        req = CreateSubscriptionRequest(
            developer_id="dev-1",
            endpoint_url="https://example.com/hook",
            secret="sec",
            events=["plugin.installed"],
        )
        with self.assertRaises(HTTPException) as ctx:
            await create_subscription(req, db)
        self.assertEqual(ctx.exception.status_code, 409)


# ── TestUpdateSubscription ────────────────────────────────────────────────────

class TestUpdateSubscription(unittest.IsolatedAsyncioTestCase):

    def _make_db(self, *, sub_exists=True):
        db = AsyncMock()

        async def execute_side(stmt, params=None):
            stmt_str = str(stmt)
            result = MagicMock()

            if "SELECT * FROM webhook_subscriptions WHERE id" in stmt_str:
                if sub_exists:
                    mock_row = MagicMock()
                    mock_row._mapping = {
                        "id": params.get("id", "sub-1"),
                        "developer_id": params.get("did", "dev-1"),
                        "endpoint_url": "https://old.com/hook",
                        "secret_hash": "a" * 64,
                        "events": '["plugin.installed"]',
                        "status": "active",
                        "description": None,
                        "failure_count": 0,
                        "last_triggered_at": None,
                        "created_at": None,
                        "updated_at": None,
                    }
                    result.fetchone.return_value = mock_row
                else:
                    result.fetchone.return_value = None

            return result

        db.execute = execute_side
        db.commit = AsyncMock()
        return db

    async def test_update_status_to_paused(self):
        from src.api.webhooks import update_subscription, UpdateSubscriptionRequest
        db = self._make_db()
        req = UpdateSubscriptionRequest(status="paused")
        result = await update_subscription("sub-1", req, "dev-1", db)
        self.assertIn("id", result)

    async def test_nonexistent_raises_404(self):
        from fastapi import HTTPException
        from src.api.webhooks import update_subscription, UpdateSubscriptionRequest
        db = self._make_db(sub_exists=False)
        req = UpdateSubscriptionRequest(status="paused")
        with self.assertRaises(HTTPException) as ctx:
            await update_subscription("no-sub", req, "dev-1", db)
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_invalid_status_raises_400(self):
        from fastapi import HTTPException
        from src.api.webhooks import update_subscription, UpdateSubscriptionRequest
        db = self._make_db()
        req = UpdateSubscriptionRequest(status="deleted")
        with self.assertRaises(HTTPException) as ctx:
            await update_subscription("sub-1", req, "dev-1", db)
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_http_url_update_raises_400(self):
        from fastapi import HTTPException
        from src.api.webhooks import update_subscription, UpdateSubscriptionRequest
        db = self._make_db()
        req = UpdateSubscriptionRequest(endpoint_url="http://insecure.com/hook")
        with self.assertRaises(HTTPException) as ctx:
            await update_subscription("sub-1", req, "dev-1", db)
        self.assertEqual(ctx.exception.status_code, 400)


# ── TestDispatchEvent ─────────────────────────────────────────────────────────

class TestDispatchEvent(unittest.IsolatedAsyncioTestCase):

    def _make_db(self, *, subs=None):
        """subs: list of event-lists per subscription."""
        db = AsyncMock()

        async def execute_side(stmt, params=None):
            stmt_str = str(stmt)
            result = MagicMock()

            if "SELECT * FROM webhook_subscriptions" in stmt_str:
                rows = []
                for i, events in enumerate(subs or []):
                    mock_row = MagicMock()
                    mock_row._mapping = {
                        "id": f"sub-{i}",
                        "developer_id": "dev-1",
                        "endpoint_url": "https://example.com/hook",
                        "secret_hash": "a" * 64,
                        "events": json.dumps(events),
                        "status": "active",
                    }
                    rows.append(mock_row)
                result.fetchall.return_value = rows

            return result

        db.execute = execute_side
        db.commit = AsyncMock()
        return db

    async def test_dispatch_queues_matching_subs(self):
        from src.api.webhooks import dispatch_event, DispatchEventRequest
        db = self._make_db(subs=[["plugin.installed"], ["settlement.paid"]])
        req = DispatchEventRequest(
            developer_id="dev-1",
            event_type="plugin.installed",
            payload={"plugin_id": "p1", "store_id": "S001"},
        )
        result = await dispatch_event(req, db)
        self.assertEqual(result["queued"], 1)
        self.assertEqual(result["event_type"], "plugin.installed")

    async def test_dispatch_no_matching_subs(self):
        from src.api.webhooks import dispatch_event, DispatchEventRequest
        db = self._make_db(subs=[["settlement.paid"]])  # not subscribed to plugin.installed
        req = DispatchEventRequest(
            developer_id="dev-1",
            event_type="plugin.installed",
            payload={},
        )
        result = await dispatch_event(req, db)
        self.assertEqual(result["queued"], 0)

    async def test_dispatch_multiple_subs(self):
        from src.api.webhooks import dispatch_event, DispatchEventRequest
        db = self._make_db(subs=[
            ["plugin.installed", "settlement.paid"],
            ["plugin.installed"],
        ])
        req = DispatchEventRequest(
            developer_id="dev-1",
            event_type="plugin.installed",
            payload={},
        )
        result = await dispatch_event(req, db)
        self.assertEqual(result["queued"], 2)

    async def test_dispatch_unknown_event_raises_400(self):
        from fastapi import HTTPException
        from src.api.webhooks import dispatch_event, DispatchEventRequest
        db = self._make_db()
        req = DispatchEventRequest(
            developer_id="dev-1",
            event_type="bogus.event",
            payload={},
        )
        with self.assertRaises(HTTPException) as ctx:
            await dispatch_event(req, db)
        self.assertEqual(ctx.exception.status_code, 400)


# ── TestListSupportedEvents ───────────────────────────────────────────────────

class TestListSupportedEvents(unittest.IsolatedAsyncioTestCase):

    async def test_returns_all_events(self):
        from src.api.webhooks import list_supported_events
        result = await list_supported_events()
        self.assertIn("events", result)
        self.assertEqual(len(result["events"]), len(SUPPORTED_EVENTS))

    async def test_each_event_has_description(self):
        from src.api.webhooks import list_supported_events
        result = await list_supported_events()
        for ev in result["events"]:
            self.assertIn("type", ev)
            self.assertIn("description", ev)
            self.assertTrue(ev["description"])


if __name__ == "__main__":
    unittest.main()
