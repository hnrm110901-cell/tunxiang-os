"""
BFF 端点测试
covers: _fetch_queue_status, _fetch_today_reservations, _fetch_inventory_alerts,
        _fetch_waste_top5, _fetch_all_stores_health (via mocks)
"""
import os

for _k, _v in {
    "DATABASE_URL":          "postgresql+asyncpg://test:test@localhost/test",
    "REDIS_URL":             "redis://localhost:6379/0",
    "CELERY_BROKER_URL":     "redis://localhost:6379/0",
    "CELERY_RESULT_BACKEND": "redis://localhost:6379/0",
    "SECRET_KEY":            "test-secret-key",
    "JWT_SECRET":            "test-jwt-secret",
}.items():
    os.environ.setdefault(_k, _v)

import pytest
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch


# ── DB mock helpers ───────────────────────────────────────────────────────────

def _make_db() -> AsyncMock:
    db = AsyncMock()
    return db


def _rows(*rows):
    res = MagicMock()
    res.fetchall.return_value = list(rows)
    res.fetchone.return_value = rows[0] if rows else None
    return res


def _one(row):
    res = MagicMock()
    res.fetchone.return_value = row
    return res


# ════════════════════════════════════════════════════════════════════════════════
# _fetch_queue_status
# ════════════════════════════════════════════════════════════════════════════════

class TestFetchQueueStatus:

    @pytest.mark.asyncio
    async def test_returns_correct_field_names(self):
        """waiting_count / avg_wait_min / served_today / queue_items 全部存在"""
        from src.api.bff import _fetch_queue_status

        db = _make_db()
        call_count = 0

        async def fake_execute(sql, params=None):
            nonlocal call_count
            call_count += 1
            sql_str = str(sql)
            if "waiting_count" in sql_str or "waiting" in sql_str.lower() and "count" in sql_str.lower():
                # first call: summary
                return _rows((5, 8.5))
            elif "served" in sql_str or "seated" in sql_str:
                return _one((12,))
            else:
                # queue items
                return _rows(
                    ("T001", 2, 10.0, "waiting"),
                    ("T002", 4, 5.0,  "called"),
                )

        db.execute = fake_execute

        result = await _fetch_queue_status("S001", db)

        assert result is not None
        assert "waiting_count"  in result
        assert "avg_wait_min"   in result
        assert "served_today"   in result
        assert "queue_items"    in result
        assert result["waiting_count"] == 5
        assert result["avg_wait_min"]  == 8.5

    @pytest.mark.asyncio
    async def test_returns_none_on_no_row(self):
        from src.api.bff import _fetch_queue_status

        db = _make_db()
        db.execute = AsyncMock(return_value=_one(None))

        result = await _fetch_queue_status("S001", db)
        assert result is None

    @pytest.mark.asyncio
    async def test_queue_items_format(self):
        """queue_items 每项包含 ticket_no / party_size / wait_min / status"""
        from src.api.bff import _fetch_queue_status

        db = _make_db()
        call_count = [0]

        async def fake_execute(sql, params=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return _one((3, 6.0))
            elif call_count[0] == 2:
                return _one((7,))
            else:
                return _rows(("T999", 3, 12.0, "waiting"))

        db.execute = fake_execute

        result = await _fetch_queue_status("S001", db)
        assert len(result["queue_items"]) == 1
        item = result["queue_items"][0]
        assert item["ticket_no"]  == "T999"
        assert item["party_size"] == 3
        assert item["status"]     == "waiting"


# ════════════════════════════════════════════════════════════════════════════════
# _fetch_today_reservations
# ════════════════════════════════════════════════════════════════════════════════

class TestFetchTodayReservations:

    @pytest.mark.asyncio
    async def test_returns_reserved_time_field(self):
        """字段名应为 reserved_time（不是 reservation_time）"""
        from src.api.bff import _fetch_today_reservations

        dt = datetime(2026, 3, 6, 18, 30, 0)
        db = _make_db()
        db.execute = AsyncMock(return_value=_rows(
            ("res-1", "张三", 4, dt, "T3", "confirmed")
        ))

        result = await _fetch_today_reservations("S001", None, db)

        assert len(result) == 1
        r = result[0]
        assert "reserved_time" in r
        assert "reservation_time" not in r
        assert r["guest_name"] == "张三"
        assert r["party_size"] == 4
        assert r["status"]     == "confirmed"

    @pytest.mark.asyncio
    async def test_empty_returns_empty_list(self):
        from src.api.bff import _fetch_today_reservations

        db = _make_db()
        db.execute = AsyncMock(return_value=_rows())

        result = await _fetch_today_reservations("S001", None, db)
        assert result == []

    @pytest.mark.asyncio
    async def test_notes_field_present(self):
        """notes 字段应存在（可为 None）"""
        from src.api.bff import _fetch_today_reservations

        dt = datetime(2026, 3, 6, 19, 0, 0)
        db = _make_db()
        db.execute = AsyncMock(return_value=_rows(
            ("res-2", "李四", 2, dt, None, "pending")
        ))

        result = await _fetch_today_reservations("S001", None, db)
        assert "notes" in result[0]


# ════════════════════════════════════════════════════════════════════════════════
# _fetch_inventory_alerts
# ════════════════════════════════════════════════════════════════════════════════

class TestFetchInventoryAlerts:

    @pytest.mark.asyncio
    async def test_contains_alert_type_and_severity(self):
        """alert_type 和 severity 字段必须存在"""
        from src.api.bff import _fetch_inventory_alerts

        db = _make_db()
        db.execute = AsyncMock(return_value=_rows(
            ("猪肉", 2.0, 10.0, "kg", "critical"),
            ("葱",   5.0, 8.0,  "kg", "warning"),
        ))

        result = await _fetch_inventory_alerts("S001", db)
        assert len(result) == 2
        for item in result:
            assert "alert_type"  in item
            assert "severity"    in item
            assert item["alert_type"] == "low"

    @pytest.mark.asyncio
    async def test_severity_values(self):
        """severity 只能是 warning 或 critical"""
        from src.api.bff import _fetch_inventory_alerts

        db = _make_db()
        db.execute = AsyncMock(return_value=_rows(
            ("鸡蛋", 0.0, 5.0, "kg", "critical"),
        ))

        result = await _fetch_inventory_alerts("S001", db)
        assert result[0]["severity"] == "critical"

    @pytest.mark.asyncio
    async def test_suggested_action_present(self):
        from src.api.bff import _fetch_inventory_alerts

        db = _make_db()
        db.execute = AsyncMock(return_value=_rows(
            ("大米", 3.0, 20.0, "kg", "warning"),
        ))

        result = await _fetch_inventory_alerts("S001", db)
        assert "suggested_action" in result[0]
        assert result[0]["suggested_action"]  # non-empty

    @pytest.mark.asyncio
    async def test_empty_returns_empty_list(self):
        from src.api.bff import _fetch_inventory_alerts

        db = _make_db()
        db.execute = AsyncMock(return_value=_rows())
        result = await _fetch_inventory_alerts("S001", db)
        assert result == []


# ════════════════════════════════════════════════════════════════════════════════
# _fetch_pending_count
# ════════════════════════════════════════════════════════════════════════════════

class TestFetchPendingCount:

    @pytest.mark.asyncio
    async def test_returns_int(self):
        from src.api.bff import _fetch_pending_count

        db = _make_db()
        db.scalar = AsyncMock(return_value=7)

        result = await _fetch_pending_count("S001", db)
        assert isinstance(result, int)
        assert result == 7

    @pytest.mark.asyncio
    async def test_returns_zero_when_none(self):
        from src.api.bff import _fetch_pending_count

        db = _make_db()
        db.scalar = AsyncMock(return_value=None)

        result = await _fetch_pending_count(None, db)
        assert result == 0


# ════════════════════════════════════════════════════════════════════════════════
# _safe helper
# ════════════════════════════════════════════════════════════════════════════════

class TestSafeHelper:

    @pytest.mark.asyncio
    async def test_returns_value_on_success(self):
        from src.api.bff import _safe

        async def ok():
            return 42

        result = await _safe(ok())
        assert result == 42

    @pytest.mark.asyncio
    async def test_returns_default_on_exception(self):
        from src.api.bff import _safe

        async def boom():
            raise ValueError("oops")

        result = await _safe(boom(), default=[])
        assert result == []

    @pytest.mark.asyncio
    async def test_default_is_none(self):
        from src.api.bff import _safe

        async def boom():
            raise RuntimeError("error")

        result = await _safe(boom())
        assert result is None


# ════════════════════════════════════════════════════════════════════════════════
# _fetch_waste_top5
# ════════════════════════════════════════════════════════════════════════════════

class TestFetchWasteTop5:

    @pytest.mark.asyncio
    async def test_returns_items_list(self):
        from src.api.bff import _fetch_waste_top5
        from unittest.mock import patch

        db = _make_db()
        mock_result = {"items": [{"rank": 1, "ingredient_name": "猪肉", "waste_cost_yuan": 200.0}]}

        with patch("src.services.waste_guard_service.WasteGuardService.get_top5_waste",
                   new=AsyncMock(return_value=mock_result)):
            result = await _fetch_waste_top5("S001", db)

        assert len(result) == 1
        assert result[0]["rank"] == 1

    @pytest.mark.asyncio
    async def test_returns_empty_on_non_dict(self):
        from src.api.bff import _fetch_waste_top5
        from unittest.mock import patch

        db = _make_db()
        with patch("src.services.waste_guard_service.WasteGuardService.get_top5_waste",
                   new=AsyncMock(return_value=None)):
            result = await _fetch_waste_top5("S001", db)

        assert result == []
