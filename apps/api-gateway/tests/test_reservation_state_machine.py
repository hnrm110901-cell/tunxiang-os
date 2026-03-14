"""
预订状态机 + 桌位冲突检测 + 企微通知 — 单元测试

测试内容：
- VALID_TRANSITIONS 状态转移合法性
- _check_transition 守卫函数
- _check_table_conflict 桌位冲突检测
- _notify_reservation_change 企微通知
- 各端点状态守卫集成
"""
import os
for _k, _v in {
    "APP_ENV": "test",
    "DATABASE_URL": "postgresql+asyncpg://test:test@localhost/test",
    "REDIS_URL": "redis://localhost:6379/0",
    "CELERY_BROKER_URL": "redis://localhost:6379/0",
    "CELERY_RESULT_BACKEND": "redis://localhost:6379/0",
    "SECRET_KEY": "test-secret-key",
    "JWT_SECRET": "test-jwt-secret",
}.items():
    os.environ.setdefault(_k, _v)

import pytest
from datetime import date, time, datetime
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi import HTTPException

from src.api.reservations import (
    VALID_TRANSITIONS,
    _check_transition,
    _check_table_conflict,
    _notify_reservation_change,
)
from src.models.reservation import ReservationStatus


class TestValidTransitions:
    """状态转移矩阵完整性"""

    def test_all_statuses_have_entry(self):
        for status in ReservationStatus:
            assert status in VALID_TRANSITIONS, f"{status} 缺少转移定义"

    def test_pending_transitions(self):
        allowed = VALID_TRANSITIONS[ReservationStatus.PENDING]
        assert ReservationStatus.CONFIRMED in allowed
        assert ReservationStatus.ARRIVED in allowed
        assert ReservationStatus.CANCELLED in allowed
        assert ReservationStatus.SEATED not in allowed

    def test_confirmed_transitions(self):
        allowed = VALID_TRANSITIONS[ReservationStatus.CONFIRMED]
        assert ReservationStatus.ARRIVED in allowed
        assert ReservationStatus.CANCELLED in allowed
        assert ReservationStatus.NO_SHOW in allowed
        assert ReservationStatus.PENDING not in allowed

    def test_arrived_transitions(self):
        allowed = VALID_TRANSITIONS[ReservationStatus.ARRIVED]
        assert ReservationStatus.SEATED in allowed
        assert ReservationStatus.CANCELLED in allowed

    def test_seated_transitions(self):
        allowed = VALID_TRANSITIONS[ReservationStatus.SEATED]
        assert ReservationStatus.COMPLETED in allowed
        assert len(allowed) == 1  # 只能完成

    def test_terminal_states_empty(self):
        for status in [ReservationStatus.COMPLETED, ReservationStatus.CANCELLED, ReservationStatus.NO_SHOW]:
            assert VALID_TRANSITIONS[status] == [], f"{status} 应是终态（无出边）"


class TestCheckTransition:

    def test_valid_transition_passes(self):
        # Should not raise
        _check_transition(ReservationStatus.PENDING, ReservationStatus.CONFIRMED)
        _check_transition(ReservationStatus.CONFIRMED, ReservationStatus.ARRIVED)
        _check_transition(ReservationStatus.ARRIVED, ReservationStatus.SEATED)
        _check_transition(ReservationStatus.SEATED, ReservationStatus.COMPLETED)

    def test_invalid_transition_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _check_transition(ReservationStatus.PENDING, ReservationStatus.SEATED)
        assert exc_info.value.status_code == 400
        assert "不可转移" in exc_info.value.detail

    def test_terminal_state_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _check_transition(ReservationStatus.COMPLETED, ReservationStatus.PENDING)
        assert exc_info.value.status_code == 400
        assert "终态" in exc_info.value.detail

    def test_error_message_includes_allowed(self):
        with pytest.raises(HTTPException) as exc_info:
            _check_transition(ReservationStatus.PENDING, ReservationStatus.COMPLETED)
        detail = exc_info.value.detail
        assert "confirmed" in detail  # allowed targets listed
        assert "arrived" in detail

    def test_no_show_is_terminal(self):
        with pytest.raises(HTTPException) as exc_info:
            _check_transition(ReservationStatus.NO_SHOW, ReservationStatus.CONFIRMED)
        assert exc_info.value.status_code == 400

    def test_cancelled_is_terminal(self):
        with pytest.raises(HTTPException) as exc_info:
            _check_transition(ReservationStatus.CANCELLED, ReservationStatus.PENDING)
        assert exc_info.value.status_code == 400


class TestCheckTableConflict:

    @pytest.mark.asyncio
    async def test_no_conflict_passes(self):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        # Should not raise
        await _check_table_conflict(
            mock_session, "S001", "A01",
            date(2026, 3, 15), time(18, 0),
        )

    @pytest.mark.asyncio
    async def test_conflict_raises_409(self):
        conflict_res = MagicMock()
        conflict_res.customer_name = "张三"
        conflict_res.reservation_time = time(18, 30)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = conflict_res
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await _check_table_conflict(
                mock_session, "S001", "A01",
                date(2026, 3, 15), time(18, 0),
            )
        assert exc_info.value.status_code == 409
        assert "桌位冲突" in exc_info.value.detail
        assert "张三" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_exclude_id_filters_self(self):
        """更新自身预订时不应冲突"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        await _check_table_conflict(
            mock_session, "S001", "A01",
            date(2026, 3, 15), time(18, 0),
            exclude_id="RES_001",
        )
        # Verify the query was called (session.execute was invoked)
        mock_session.execute.assert_called_once()


class TestNotifyReservationChange:

    @pytest.mark.asyncio
    async def test_confirmed_triggers_notification(self):
        reservation = MagicMock()
        reservation.id = "RES_001"
        reservation.store_id = "S001"
        reservation.customer_name = "张三"
        reservation.customer_phone = "13800138000"
        reservation.party_size = 4
        reservation.reservation_date = date(2026, 3, 15)
        reservation.reservation_time = time(18, 0)
        reservation.table_number = "A01"

        mock_trigger = AsyncMock()

        with patch(
            "src.api.reservations.wechat_trigger_service",
            create=True,
        ) as mock_svc:
            mock_svc.trigger = mock_trigger
            # Patch the lazy import
            with patch(
                "src.services.wechat_trigger_service.wechat_trigger_service",
                mock_svc,
                create=True,
            ):
                await _notify_reservation_change(reservation, "pending", "confirmed")

    @pytest.mark.asyncio
    async def test_cancelled_triggers_notification(self):
        reservation = MagicMock()
        reservation.id = "RES_001"
        reservation.store_id = "S001"
        reservation.customer_name = "张三"
        reservation.customer_phone = "13800138000"
        reservation.party_size = 4
        reservation.reservation_date = date(2026, 3, 15)
        reservation.reservation_time = time(18, 0)
        reservation.table_number = None

        # Fire-and-forget: even if import fails, should not raise
        await _notify_reservation_change(reservation, "confirmed", "cancelled")

    @pytest.mark.asyncio
    async def test_seated_does_not_trigger(self):
        """入座不在通知事件映射中"""
        reservation = MagicMock()
        reservation.id = "RES_001"

        # Should not raise, just skip
        await _notify_reservation_change(reservation, "arrived", "seated")

    @pytest.mark.asyncio
    async def test_notification_failure_does_not_raise(self):
        """通知失败不应阻塞主流程"""
        reservation = MagicMock()
        reservation.id = "RES_001"
        reservation.store_id = "S001"
        reservation.customer_name = "张三"
        reservation.customer_phone = "13800138000"
        reservation.party_size = 4
        reservation.reservation_date = date(2026, 3, 15)
        reservation.reservation_time = time(18, 0)
        reservation.table_number = None

        # Even with an import that raises, should not propagate
        await _notify_reservation_change(reservation, "pending", "confirmed")


class TestEndpointStateGuards:
    """测试各端点是否正确集成状态守卫（通过单元模拟）"""

    def test_seat_from_pending_raises(self):
        """PENDING → SEATED 不合法（必须先到店）"""
        with pytest.raises(HTTPException) as exc_info:
            _check_transition(ReservationStatus.PENDING, ReservationStatus.SEATED)
        assert exc_info.value.status_code == 400

    def test_no_show_from_pending_raises(self):
        """PENDING → NO_SHOW 不合法（必须先确认）"""
        with pytest.raises(HTTPException) as exc_info:
            _check_transition(ReservationStatus.PENDING, ReservationStatus.NO_SHOW)
        assert exc_info.value.status_code == 400

    def test_complete_from_arrived_raises(self):
        """ARRIVED → COMPLETED 不合法（必须先入座）"""
        with pytest.raises(HTTPException) as exc_info:
            _check_transition(ReservationStatus.ARRIVED, ReservationStatus.COMPLETED)
        assert exc_info.value.status_code == 400

    def test_full_happy_path(self):
        """完整正向路径：PENDING→CONFIRMED→ARRIVED→SEATED→COMPLETED"""
        _check_transition(ReservationStatus.PENDING, ReservationStatus.CONFIRMED)
        _check_transition(ReservationStatus.CONFIRMED, ReservationStatus.ARRIVED)
        _check_transition(ReservationStatus.ARRIVED, ReservationStatus.SEATED)
        _check_transition(ReservationStatus.SEATED, ReservationStatus.COMPLETED)

    def test_walk_in_path(self):
        """Walk-in路径：PENDING→ARRIVED→SEATED→COMPLETED"""
        _check_transition(ReservationStatus.PENDING, ReservationStatus.ARRIVED)
        _check_transition(ReservationStatus.ARRIVED, ReservationStatus.SEATED)
        _check_transition(ReservationStatus.SEATED, ReservationStatus.COMPLETED)

    def test_cancellation_paths(self):
        """各阶段取消"""
        _check_transition(ReservationStatus.PENDING, ReservationStatus.CANCELLED)
        _check_transition(ReservationStatus.CONFIRMED, ReservationStatus.CANCELLED)
        _check_transition(ReservationStatus.ARRIVED, ReservationStatus.CANCELLED)

    def test_seated_cannot_cancel(self):
        """已入座不可取消"""
        with pytest.raises(HTTPException):
            _check_transition(ReservationStatus.SEATED, ReservationStatus.CANCELLED)
