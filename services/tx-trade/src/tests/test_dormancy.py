"""沉睡天数检测测试"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone

from services.dormancy_service import classify_dormancy, compute_dormancy_days, scan_dormant_items, suggest_cleanup


class TestDormancyDays:
    def test_recent(self):
        now = datetime(2026, 3, 23, tzinfo=timezone.utc)
        assert compute_dormancy_days("2026-03-22T00:00:00+00:00", now) == 1

    def test_old(self):
        now = datetime(2026, 3, 23, tzinfo=timezone.utc)
        assert compute_dormancy_days("2025-12-23T00:00:00+00:00", now) == 90

    def test_never_used(self):
        assert compute_dormancy_days(None) == 9999

    def test_invalid_date(self):
        assert compute_dormancy_days("not-a-date") == 9999


class TestClassify:
    def test_active(self):
        assert classify_dormancy(3) == "active"

    def test_idle(self):
        assert classify_dormancy(15) == "idle"

    def test_dormant(self):
        assert classify_dormancy(60) == "dormant"

    def test_dead(self):
        assert classify_dormancy(120) == "dead"

    def test_never(self):
        assert classify_dormancy(9999) == "never"


class TestScan:
    def test_mixed_items(self):
        items = [
            {"id": "1", "name": "微信支付", "last_used_at": "2026-03-22T00:00:00+00:00"},
            {"id": "2", "name": "旧银行卡", "last_used_at": "2025-06-01T00:00:00+00:00"},
            {"id": "3", "name": "从未用的券", "last_used_at": None},
        ]
        result = scan_dormant_items(items, threshold_days=30)
        assert result["dormant_count"] == 2  # 旧银行卡 + 从未用的券
        assert result["active"][0]["name"] == "微信支付"

    def test_all_active(self):
        items = [{"id": "1", "name": "现金", "last_used_at": datetime.now(timezone.utc).isoformat()}]
        result = scan_dormant_items(items)
        assert result["dormant_count"] == 0


class TestSuggest:
    def test_cleanup_suggestions(self):
        scan = {
            "dormant": [
                {"name": "旧券A", "dormancy_days": 120, "dormancy_status": "dead"},
                {"name": "从未用B", "dormancy_days": 9999, "dormancy_status": "never"},
            ]
        }
        suggestions = suggest_cleanup(scan)
        assert len(suggestions) == 2
        assert "停用" in suggestions[0]
        assert "删除" in suggestions[1]
