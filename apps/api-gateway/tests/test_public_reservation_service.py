"""
R1: 客户自助预订服务 — 单元测试

测试内容：
- 可用时段计算逻辑
- 预订创建 + 渠道记录
- 预订查询（按手机号）
- 预订取消（状态校验）
- Token 管理（create/get）
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
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.public_reservation_service import (
    PublicReservationService,
    TOKEN_EXPIRE_SECONDS,
    _TOKEN_PREFIX,
)


class TestTokenManagement:

    @pytest.fixture
    def service(self):
        return PublicReservationService()

    @pytest.mark.asyncio
    async def test_create_phone_token(self, service):
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()
        service._redis = mock_redis

        token = await service.create_phone_token("13800138000")
        assert len(token) == 32  # hex(16) = 32 chars
        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        assert call_args[0][1] == "13800138000"
        assert call_args[1]["ex"] == TOKEN_EXPIRE_SECONDS

    @pytest.mark.asyncio
    async def test_get_phone_by_token_found(self, service):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="13800138000")
        service._redis = mock_redis

        phone = await service.get_phone_by_token("abc123")
        assert phone == "13800138000"
        mock_redis.get.assert_called_once_with(f"{_TOKEN_PREFIX}abc123")

    @pytest.mark.asyncio
    async def test_get_phone_by_token_not_found(self, service):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        service._redis = mock_redis

        phone = await service.get_phone_by_token("invalid_token")
        assert phone is None


class TestGetPublicStores:

    @pytest.fixture
    def service(self):
        return PublicReservationService()

    @pytest.mark.asyncio
    async def test_returns_active_stores(self, service):
        mock_store1 = MagicMock()
        mock_store1.id = "S001"
        mock_store1.name = "门店A"
        mock_store1.address = "长沙市"
        mock_store1.phone = "0731-111"
        mock_store2 = MagicMock()
        mock_store2.id = "S002"
        mock_store2.name = "门店B"
        mock_store2.address = "株洲市"
        mock_store2.phone = "0731-222"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_store1, mock_store2]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        stores = await service.get_public_stores(mock_db)
        assert len(stores) == 2
        assert stores[0]["id"] == "S001"
        assert stores[0]["name"] == "门店A"
        assert stores[1]["id"] == "S002"

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_stores(self, service):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        stores = await service.get_public_stores(mock_db)
        assert stores == []


class TestGetStoreAvailability:

    @pytest.fixture
    def service(self):
        return PublicReservationService()

    @pytest.mark.asyncio
    async def test_no_existing_reservations(self, service):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.get_store_availability(mock_db, "S001", date(2026, 3, 15))
        assert result["store_id"] == "S001"
        assert result["date"] == "2026-03-15"
        assert len(result["slots"]) > 0
        # All slots should have 20 available when no bookings
        for slot in result["slots"]:
            assert slot["available"] == 20
            assert slot["booked"] == 0

    @pytest.mark.asyncio
    async def test_with_existing_reservations(self, service):
        # Simulate 3 reservations at 18:00
        mock_res1 = MagicMock(reservation_time=time(18, 0))
        mock_res2 = MagicMock(reservation_time=time(18, 0))
        mock_res3 = MagicMock(reservation_time=time(18, 0))

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_res1, mock_res2, mock_res3]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.get_store_availability(mock_db, "S001", date(2026, 3, 15))
        # Find the 18:00 slot
        slot_1800 = next(s for s in result["slots"] if s["time"] == "18:00")
        assert slot_1800["booked"] == 3
        assert slot_1800["available"] == 17

    @pytest.mark.asyncio
    async def test_slots_cover_lunch_and_dinner(self, service):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.get_store_availability(mock_db, "S001", date(2026, 3, 15))
        meal_periods = {s["meal_period"] for s in result["slots"]}
        assert "午餐" in meal_periods
        assert "晚餐" in meal_periods

    @pytest.mark.asyncio
    async def test_table_types(self, service):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.get_store_availability(mock_db, "S001", date(2026, 3, 15))
        types = [t["type"] for t in result["table_types"]]
        assert "大厅" in types
        assert "包厢" in types


class TestCreatePublicReservation:

    @pytest.fixture
    def service(self):
        return PublicReservationService()

    @pytest.mark.asyncio
    async def test_creates_reservation_and_channel(self, service):
        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        added_objects = []
        mock_db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

        result = await service.create_public_reservation(
            session=mock_db,
            phone="13800138000",
            store_id="S001",
            customer_name="张三",
            party_size=4,
            reservation_date=date(2026, 3, 15),
            reservation_time=time(18, 0),
        )

        # Should add 2 objects: Reservation + ReservationChannel
        assert len(added_objects) == 2
        assert mock_db.commit.called
        assert mock_db.refresh.called

    @pytest.mark.asyncio
    async def test_reservation_id_format(self, service):
        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        mock_db.add = MagicMock()

        result = await service.create_public_reservation(
            session=mock_db,
            phone="13800138000",
            store_id="S001",
            customer_name="李四",
            party_size=2,
            reservation_date=date(2026, 3, 15),
            reservation_time=time(12, 0),
        )

        assert result.id.startswith("RES_20260315_")


class TestCancelReservation:

    @pytest.fixture
    def service(self):
        return PublicReservationService()

    @pytest.mark.asyncio
    async def test_cancel_pending(self, service):
        from src.models.reservation import ReservationStatus

        mock_reservation = MagicMock()
        mock_reservation.status = ReservationStatus.PENDING
        mock_reservation.customer_phone = "13800138000"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_reservation

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        result = await service.cancel_reservation(mock_db, "RES_001", "13800138000")
        assert result.status == ReservationStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_confirmed(self, service):
        from src.models.reservation import ReservationStatus

        mock_reservation = MagicMock()
        mock_reservation.status = ReservationStatus.CONFIRMED

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_reservation

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        result = await service.cancel_reservation(mock_db, "RES_001", "13800138000")
        assert result.status == ReservationStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_not_found_raises(self, service):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="预订不存在"):
            await service.cancel_reservation(mock_db, "RES_999", "13800138000")

    @pytest.mark.asyncio
    async def test_cancel_seated_raises(self, service):
        from src.models.reservation import ReservationStatus

        mock_reservation = MagicMock()
        mock_reservation.status = ReservationStatus.SEATED

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_reservation

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="不允许取消"):
            await service.cancel_reservation(mock_db, "RES_001", "13800138000")

    @pytest.mark.asyncio
    async def test_cancel_completed_raises(self, service):
        from src.models.reservation import ReservationStatus

        mock_reservation = MagicMock()
        mock_reservation.status = ReservationStatus.COMPLETED

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_reservation

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="不允许取消"):
            await service.cancel_reservation(mock_db, "RES_001", "13800138000")


class TestLookupReservations:

    @pytest.fixture
    def service(self):
        return PublicReservationService()

    @pytest.mark.asyncio
    async def test_lookup_returns_list(self, service):
        mock_res1 = MagicMock(id="RES_001")
        mock_res2 = MagicMock(id="RES_002")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_res1, mock_res2]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        results = await service.lookup_reservations(mock_db, "13800138000")
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_lookup_empty(self, service):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        results = await service.lookup_reservations(mock_db, "00000000000")
        assert results == []
