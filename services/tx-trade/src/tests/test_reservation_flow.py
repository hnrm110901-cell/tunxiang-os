"""预订→排队→入座 全链路测试"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.reservation_flow import (
    call_next,
    can_reservation_transition,
    compute_queue_stats,
    generate_queue_number,
    queue_to_table,
)


class TestReservationStateMachine:
    def test_pending_to_confirmed(self):
        assert can_reservation_transition("pending", "confirmed")

    def test_confirmed_to_arrived(self):
        assert can_reservation_transition("confirmed", "arrived")

    def test_cannot_skip(self):
        assert not can_reservation_transition("pending", "seated")

    def test_no_show(self):
        assert can_reservation_transition("confirmed", "no_show")


class TestQueueManagement:
    def test_generate_number_small(self):
        result = generate_queue_number("s1", 3, [])
        assert result["prefix"] == "A"
        assert result["number"] == 1
        assert result["status"] == "waiting"

    def test_generate_number_large(self):
        result = generate_queue_number("s1", 10, [])
        assert result["prefix"] == "C"

    def test_call_next(self):
        queue = [
            {"prefix": "A", "status": "waiting", "taken_at": "2026-03-23T10:00:00"},
            {"prefix": "A", "status": "waiting", "taken_at": "2026-03-23T10:05:00"},
        ]
        called = call_next(queue)
        assert called is not None
        assert called["status"] == "called"
        assert called["taken_at"] == "2026-03-23T10:00:00"

    def test_call_next_empty(self):
        assert call_next([]) is None


class TestTableAllocation:
    def test_allocate_best_fit(self):
        tables = [
            {"table_no": "A01", "seats": 4, "status": "free", "area": "大厅"},
            {"table_no": "B01", "seats": 8, "status": "free", "area": "包间"},
        ]
        result = queue_to_table({"guest_count": 3, "queue_no": "A001"}, tables)
        assert result["table_no"] == "A01"  # 4座最接近3人

    def test_no_available(self):
        tables = [{"table_no": "A01", "seats": 4, "status": "occupied"}]
        assert queue_to_table({"guest_count": 2}, tables) is None


class TestQueueStats:
    def test_stats(self):
        queue = [
            {"prefix": "A", "status": "waiting"},
            {"prefix": "A", "status": "seated"},
            {"prefix": "B", "status": "cancelled"},
        ]
        stats = compute_queue_stats(queue)
        assert stats["total_today"] == 3
        assert stats["waiting"] == 1
        assert stats["abandon_rate_pct"] > 0
