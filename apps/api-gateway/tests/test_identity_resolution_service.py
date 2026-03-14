"""
IdentityResolutionService 单元测试 — Sprint 1 CDP 地基层

测试 resolve/merge/backfill/stats/fill_rate 核心功能
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
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, date

from src.models.consumer_identity import ConsumerIdentity
from src.models.consumer_id_mapping import ConsumerIdMapping, IdType
from src.services.identity_resolution_service import IdentityResolutionService


@pytest.fixture
def service():
    return IdentityResolutionService()


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    db.scalar = AsyncMock(return_value=None)
    db.scalar_one_or_none = AsyncMock(return_value=None)
    db.get = AsyncMock(return_value=None)
    db.add = MagicMock()
    return db


# ── resolve() ────────────────────────────────────────────────────────

class TestResolve:
    """resolve() 测试：查找或创建统一消费者身份"""

    @pytest.mark.asyncio
    async def test_resolve_new_consumer(self, service, mock_db):
        """新手机号 → 创建 ConsumerIdentity + phone mapping"""
        # _find_by_phone 返回 None（新消费者）
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute = AsyncMock(return_value=mock_result)

        consumer_id = await service.resolve(
            mock_db, "13800138000",
            store_id="S001", source="pos", display_name="张三",
        )

        # 验证 db.add 被调用（创建 ConsumerIdentity）
        assert mock_db.add.called
        added_obj = mock_db.add.call_args[0][0]
        assert isinstance(added_obj, ConsumerIdentity)
        assert added_obj.primary_phone == "13800138000"
        assert added_obj.display_name == "张三"
        assert added_obj.source == "pos"

    @pytest.mark.asyncio
    async def test_resolve_existing_consumer(self, service, mock_db):
        """已有手机号 → 返回已有 consumer_id"""
        existing = ConsumerIdentity(
            id=uuid.uuid4(),
            primary_phone="13800138000",
            display_name="张三",
            is_merged=False,
        )
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=existing)
        mock_db.execute = AsyncMock(return_value=mock_result)

        consumer_id = await service.resolve(
            mock_db, "13800138000",
            source="pos",
        )
        assert consumer_id == existing.id
        # 不应 add 新对象
        assert not mock_db.add.called

    @pytest.mark.asyncio
    async def test_resolve_updates_wechat(self, service, mock_db):
        """已有消费者 + 新 wechat_openid → 补充信息"""
        existing = ConsumerIdentity(
            id=uuid.uuid4(),
            primary_phone="13800138000",
            wechat_openid=None,
            display_name="张三",
            is_merged=False,
        )
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=existing)
        mock_db.execute = AsyncMock(return_value=mock_result)

        await service.resolve(
            mock_db, "13800138000",
            wechat_openid="oXYZ123",
        )
        assert existing.wechat_openid == "oXYZ123"

    @pytest.mark.asyncio
    async def test_resolve_empty_phone_raises(self, service, mock_db):
        """空手机号 → ValueError"""
        with pytest.raises(ValueError, match="phone is required"):
            await service.resolve(mock_db, "")

    @pytest.mark.asyncio
    async def test_resolve_strips_phone(self, service, mock_db):
        """手机号前后空格自动去除"""
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute = AsyncMock(return_value=mock_result)

        await service.resolve(mock_db, "  13800138000  ", source="test")
        added_obj = mock_db.add.call_args[0][0]
        assert added_obj.primary_phone == "13800138000"


# ── merge() ──────────────────────────────────────────────────────────

class TestMerge:
    """merge() 测试：合并两个消费者身份"""

    @pytest.mark.asyncio
    async def test_merge_same_id(self, service, mock_db):
        """相同ID → 直接返回"""
        cid = uuid.uuid4()
        result = await service.merge(mock_db, cid, cid)
        assert result == cid

    @pytest.mark.asyncio
    async def test_merge_winner_not_found(self, service, mock_db):
        """winner 不存在 → ValueError"""
        mock_db.get = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match="winner"):
            await service.merge(mock_db, uuid.uuid4(), uuid.uuid4())

    @pytest.mark.asyncio
    async def test_merge_loser_already_merged(self, service, mock_db):
        """loser 已合并 → ValueError"""
        winner = ConsumerIdentity(id=uuid.uuid4(), primary_phone="A", is_merged=False)
        loser = ConsumerIdentity(id=uuid.uuid4(), primary_phone="B", is_merged=True)

        async def get_side_effect(model, pk):
            if pk == winner.id:
                return winner
            return loser

        mock_db.get = AsyncMock(side_effect=get_side_effect)

        with pytest.raises(ValueError, match="already merged"):
            await service.merge(mock_db, winner.id, loser.id)

    @pytest.mark.asyncio
    async def test_merge_aggregates_stats(self, service, mock_db):
        """合并时聚合统计累加"""
        winner = ConsumerIdentity(
            id=uuid.uuid4(), primary_phone="A", is_merged=False,
            total_order_count=5, total_order_amount_fen=10000,
            total_reservation_count=2,
            first_order_at=datetime(2025, 6, 1),
            last_order_at=datetime(2025, 12, 1),
            first_store_id="S001",
        )
        loser = ConsumerIdentity(
            id=uuid.uuid4(), primary_phone="B", is_merged=False,
            total_order_count=3, total_order_amount_fen=5000,
            total_reservation_count=1,
            first_order_at=datetime(2025, 3, 1),
            last_order_at=datetime(2026, 1, 1),
            first_store_id="S002",
        )

        async def get_side_effect(model, pk):
            if pk == winner.id:
                return winner
            return loser

        mock_db.get = AsyncMock(side_effect=get_side_effect)

        await service.merge(mock_db, winner.id, loser.id)

        assert loser.is_merged is True
        assert loser.merged_into == winner.id
        assert winner.total_order_count == 8
        assert winner.total_order_amount_fen == 15000
        assert winner.total_reservation_count == 3
        # first_order_at 取更早的
        assert winner.first_order_at == datetime(2025, 3, 1)
        assert winner.first_store_id == "S002"
        # last_order_at 取更晚的
        assert winner.last_order_at == datetime(2026, 1, 1)


# ── resolve_by_external_id() ────────────────────────────────────────

class TestResolveByExternalId:

    @pytest.mark.asyncio
    async def test_found(self, service, mock_db):
        """按外部ID找到 consumer_id"""
        cid = uuid.uuid4()
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=cid)
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.resolve_by_external_id(
            mock_db, "wechat_openid", "oXYZ123",
        )
        assert result == cid

    @pytest.mark.asyncio
    async def test_not_found(self, service, mock_db):
        """外部ID不存在 → None"""
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.resolve_by_external_id(
            mock_db, "meituan_uid", "MT999",
        )
        assert result is None


# ── get_stats() ──────────────────────────────────────────────────────

class TestGetStats:

    @pytest.mark.asyncio
    async def test_stats_structure(self, service, mock_db):
        """stats 返回正确结构"""
        mock_db.scalar = AsyncMock(side_effect=[100, 5, 200])

        result = await service.get_stats(mock_db)
        assert result == {
            "total_consumers": 100,
            "merged_count": 5,
            "active_mappings": 200,
        }

    @pytest.mark.asyncio
    async def test_stats_empty(self, service, mock_db):
        """空库返回零"""
        mock_db.scalar = AsyncMock(return_value=None)

        result = await service.get_stats(mock_db)
        assert result["total_consumers"] == 0
        assert result["merged_count"] == 0
        assert result["active_mappings"] == 0


# ── ConsumerIdentity model ──────────────────────────────────────────

class TestConsumerIdentityModel:

    def test_default_values(self):
        ci = ConsumerIdentity(primary_phone="13800138000")
        assert ci.is_merged is False or ci.is_merged is None  # default via server_default
        assert ci.total_order_count == 0 or ci.total_order_count is None
        assert ci.tags == [] or ci.tags is None

    def test_repr(self):
        ci = ConsumerIdentity(id=uuid.uuid4(), primary_phone="13800138000")
        assert "13800138000" in repr(ci)


# ── ConsumerIdMapping model ──────────────────────────────────────────

class TestConsumerIdMappingModel:

    def test_id_type_enum(self):
        """11种ID类型"""
        assert len(IdType) == 11
        assert IdType.PHONE.value == "phone"
        assert IdType.WECHAT_OPENID.value == "wechat_openid"
        assert IdType.MEITUAN_UID.value == "meituan_uid"
        assert IdType.CUSTOM.value == "custom"

    def test_repr(self):
        cim = ConsumerIdMapping(
            consumer_id=uuid.uuid4(),
            id_type="phone",
            external_id="13800138000",
        )
        assert "phone" in repr(cim)
        assert "13800138000" in repr(cim)


# ── CDPSyncService ──────────────────────────────────────────────────

class TestCDPSyncService:

    def test_import(self):
        from src.services.cdp_sync_service import cdp_sync_service
        assert cdp_sync_service is not None

    def test_service_singleton(self):
        from src.services.cdp_sync_service import CDPSyncService
        s = CDPSyncService()
        assert hasattr(s, "sync_store_orders")
        assert hasattr(s, "get_fill_rate")
