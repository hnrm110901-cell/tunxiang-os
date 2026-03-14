"""
R2: 美团预订同步服务 — 单元测试

测试内容：
- 入站 Webhook 处理（创建/更新/取消）
- 幂等去重（按 external_order_id）
- 渠道类型判断（美团/大众点评）
- 出站同步到美团
- 门店ID映射
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
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date

from src.services.meituan_reservation_service import (
    MeituanReservationService,
    _STORE_MAP,
)


class TestResolveStoreId:

    def test_mapped_store(self):
        service = MeituanReservationService()
        _STORE_MAP["MT_001"] = "LOCAL_001"
        try:
            assert service._resolve_store_id("MT_001") == "LOCAL_001"
        finally:
            _STORE_MAP.pop("MT_001", None)

    def test_unmapped_store_passthrough(self):
        service = MeituanReservationService()
        assert service._resolve_store_id("UNKNOWN_STORE") == "UNKNOWN_STORE"


class TestHandleWebhook:

    @pytest.fixture
    def service(self):
        return MeituanReservationService()

    @pytest.mark.asyncio
    async def test_missing_reservation_id_raises(self, service):
        with pytest.raises(ValueError, match="缺少 reservation_id"):
            await service.handle_webhook("reservation.created", {})

    @pytest.mark.asyncio
    async def test_cancel_event_routes_to_handle_cancel(self, service):
        with patch.object(service, "_handle_cancel", new_callable=AsyncMock) as mock_cancel:
            mock_cancel.return_value = {"action": "cancelled"}
            result = await service.handle_webhook(
                "reservation.cancelled",
                {"reservation_id": "EXT_001"},
            )
            mock_cancel.assert_called_once()
            assert result["action"] == "cancelled"

    @pytest.mark.asyncio
    async def test_created_event_routes_to_create_or_update(self, service):
        with patch.object(service, "_handle_create_or_update", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = {"action": "created"}
            result = await service.handle_webhook(
                "reservation.created",
                {"reservation_id": "EXT_002"},
            )
            mock_create.assert_called_once()
            assert result["action"] == "created"


class TestHandleCreateOrUpdate:

    @pytest.fixture
    def service(self):
        return MeituanReservationService()

    @pytest.mark.asyncio
    async def test_create_new_reservation(self, service):
        """新预订：external_id 不存在时创建新记录"""
        # Mock: channel lookup returns None (no existing)
        mock_channel_result = MagicMock()
        mock_channel_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_channel_result)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        with patch("src.services.meituan_reservation_service.get_db_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await service._handle_create_or_update({
                "reservation_id": "MT_RES_001",
                "store_id": "S001",
                "customer_name": "王五",
                "customer_phone": "13800138000",
                "party_size": 4,
                "reservation_date": "2026-03-15",
                "reservation_time": "18:00",
            })

            assert result["action"] == "created"
            # Should add Reservation + ReservationChannel + ReservationSync = 3 objects
            assert mock_session.add.call_count == 3

    @pytest.mark.asyncio
    async def test_update_existing_reservation(self, service):
        """幂等：external_id 已存在时更新"""
        mock_channel = MagicMock(reservation_id="RES_EXISTING")
        mock_channel_result = MagicMock()
        mock_channel_result.scalar_one_or_none.return_value = mock_channel

        mock_reservation = MagicMock(id="RES_EXISTING")
        mock_res_result = MagicMock()
        mock_res_result.scalar_one_or_none.return_value = mock_reservation

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=[mock_channel_result, mock_res_result])
        mock_session.commit = AsyncMock()

        with patch("src.services.meituan_reservation_service.get_db_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await service._handle_create_or_update({
                "reservation_id": "MT_RES_001",
                "customer_name": "王五（改）",
                "party_size": 6,
            })

            assert result["action"] == "updated"
            assert mock_reservation.customer_name == "王五（改）"
            assert mock_reservation.party_size == 6

    @pytest.mark.asyncio
    async def test_dianping_source_channel(self, service):
        """大众点评渠道识别"""
        mock_channel_result = MagicMock()
        mock_channel_result.scalar_one_or_none.return_value = None

        added_objects = []
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_channel_result)
        mock_session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
        mock_session.commit = AsyncMock()

        with patch("src.services.meituan_reservation_service.get_db_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            await service._handle_create_or_update({
                "reservation_id": "DP_RES_001",
                "store_id": "S001",
                "source": "dianping",
                "reservation_date": "2026-03-15",
                "reservation_time": "19:00",
            })

            # Find ReservationChannel in added objects
            from src.models.reservation_channel import ReservationChannel, ChannelType
            channels = [o for o in added_objects if isinstance(o, ReservationChannel)]
            assert len(channels) == 1
            assert channels[0].channel == ChannelType.DIANPING


class TestHandleCancel:

    @pytest.fixture
    def service(self):
        return MeituanReservationService()

    @pytest.mark.asyncio
    async def test_cancel_not_found(self, service):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("src.services.meituan_reservation_service.get_db_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await service._handle_cancel({"reservation_id": "NONEXIST"})
            assert result["action"] == "skipped"
            assert result["reason"] == "not_found"

    @pytest.mark.asyncio
    async def test_cancel_already_cancelled(self, service):
        from src.models.reservation import ReservationStatus

        mock_channel = MagicMock(reservation_id="RES_001")
        mock_channel_result = MagicMock()
        mock_channel_result.scalar_one_or_none.return_value = mock_channel

        mock_reservation = MagicMock(status=ReservationStatus.CANCELLED)
        mock_res_result = MagicMock()
        mock_res_result.scalar_one_or_none.return_value = mock_reservation

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=[mock_channel_result, mock_res_result])

        with patch("src.services.meituan_reservation_service.get_db_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await service._handle_cancel({"reservation_id": "EXT_001"})
            assert result["action"] == "skipped"
            assert result["reason"] == "already_terminal"

    @pytest.mark.asyncio
    async def test_cancel_confirmed_success(self, service):
        from src.models.reservation import ReservationStatus

        mock_channel = MagicMock(reservation_id="RES_001")
        mock_channel_result = MagicMock()
        mock_channel_result.scalar_one_or_none.return_value = mock_channel

        mock_reservation = MagicMock(id="RES_001", status=ReservationStatus.CONFIRMED)
        mock_res_result = MagicMock()
        mock_res_result.scalar_one_or_none.return_value = mock_reservation

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=[mock_channel_result, mock_res_result])
        mock_session.commit = AsyncMock()

        with patch("src.services.meituan_reservation_service.get_db_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await service._handle_cancel({"reservation_id": "EXT_001"})
            assert result["action"] == "cancelled"
            assert mock_reservation.status == ReservationStatus.CANCELLED


class TestSyncToMeituan:

    @pytest.fixture
    def service(self):
        return MeituanReservationService()

    @pytest.mark.asyncio
    async def test_no_sync_record_raises(self, service):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="非美团渠道"):
            await service.sync_to_meituan(mock_db, "RES_LOCAL", "confirm")

    @pytest.mark.asyncio
    async def test_adapter_not_configured(self, service):
        mock_sync = MagicMock(external_reservation_id="EXT_001")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_sync

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch.object(service, "_get_adapter", return_value=None):
            result = await service.sync_to_meituan(mock_db, "RES_001", "confirm")
            assert result["synced"] is False
            assert result["reason"] == "adapter_not_configured"

    @pytest.mark.asyncio
    async def test_sync_confirm_success(self, service):
        from src.models.integration import SyncStatus

        mock_sync = MagicMock(external_reservation_id="EXT_001")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_sync

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        mock_adapter = AsyncMock()
        mock_adapter.confirm_reservation = AsyncMock()

        with patch.object(service, "_get_adapter", return_value=mock_adapter):
            result = await service.sync_to_meituan(mock_db, "RES_001", "confirm")
            assert result["synced"] is True
            assert result["action"] == "confirm"
            mock_adapter.confirm_reservation.assert_called_once_with("EXT_001")
            assert mock_sync.sync_status == SyncStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_sync_cancel_success(self, service):
        mock_sync = MagicMock(external_reservation_id="EXT_002")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_sync

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        mock_adapter = AsyncMock()
        mock_adapter.cancel_reservation = AsyncMock()

        with patch.object(service, "_get_adapter", return_value=mock_adapter):
            result = await service.sync_to_meituan(mock_db, "RES_002", "cancel")
            assert result["synced"] is True
            mock_adapter.cancel_reservation.assert_called_once_with("EXT_002")

    @pytest.mark.asyncio
    async def test_sync_unsupported_action_raises(self, service):
        mock_sync = MagicMock(external_reservation_id="EXT_003")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_sync

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_adapter = AsyncMock()

        with patch.object(service, "_get_adapter", return_value=mock_adapter):
            # "invalid_action" should raise inside sync_to_meituan
            # But the error is caught by the try/except and returned as synced=False
            result = await service.sync_to_meituan(mock_db, "RES_003", "invalid_action")
            assert result["synced"] is False

    @pytest.mark.asyncio
    async def test_sync_adapter_failure(self, service):
        from src.models.integration import SyncStatus

        mock_sync = MagicMock(external_reservation_id="EXT_004")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_sync

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        mock_adapter = AsyncMock()
        mock_adapter.confirm_reservation = AsyncMock(side_effect=Exception("网络错误"))

        with patch.object(service, "_get_adapter", return_value=mock_adapter):
            result = await service.sync_to_meituan(mock_db, "RES_004", "confirm")
            assert result["synced"] is False
            assert "网络错误" in result["error"]
            assert mock_sync.sync_status == SyncStatus.FAILED
