"""
R4: AI邀请函服务 — 单元测试

测试内容：
- 邀请函CRUD（创建/列表/按ID/按token）
- AI文案生成（正常 + 降级）
- 发布（share_url生成）
- RSVP回执（记录 + 统计）
- 浏览量计数
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
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.invitation_service import InvitationService
from src.models.invitation import InvitationTemplate, RSVPStatus


class TestCreateInvitation:

    @pytest.fixture
    def service(self):
        return InvitationService()

    @pytest.mark.asyncio
    async def test_create_basic(self, service):
        added_objects = []
        mock_db = AsyncMock()
        mock_db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        result = await service.create_invitation(
            session=mock_db,
            store_id="S001",
            host_name="张总",
            host_phone="13800138000",
            event_type="商务宴请",
            event_title="新品发布庆功宴",
            event_date=datetime(2026, 4, 1, 18, 0),
            venue_name="长沙宴会厅",
        )

        assert len(added_objects) == 1
        inv = added_objects[0]
        assert inv.store_id == "S001"
        assert inv.host_name == "张总"
        assert inv.event_type == "商务宴请"
        assert inv.template == InvitationTemplate.CORPORATE_BLUE  # default
        assert len(inv.share_token) == 32  # hex(16)
        assert mock_db.commit.called

    @pytest.mark.asyncio
    async def test_create_with_wedding_template(self, service):
        added_objects = []
        mock_db = AsyncMock()
        mock_db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        await service.create_invitation(
            session=mock_db,
            store_id="S001",
            host_name="李先生",
            host_phone="13900139000",
            event_type="婚宴",
            event_title="李王婚礼",
            event_date=datetime(2026, 5, 1),
            venue_name="红色宴会厅",
            template="wedding_red",
        )

        inv = added_objects[0]
        assert inv.template == InvitationTemplate.WEDDING_RED

    @pytest.mark.asyncio
    async def test_create_with_coordinates(self, service):
        added_objects = []
        mock_db = AsyncMock()
        mock_db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        await service.create_invitation(
            session=mock_db,
            store_id="S001",
            host_name="王总",
            host_phone="13700137000",
            event_type="生日宴",
            event_title="六十大寿",
            event_date=datetime(2026, 6, 15),
            venue_name="金色宴会厅",
            venue_lat=28.228,
            venue_lng=112.939,
        )

        inv = added_objects[0]
        assert inv.venue_lat == 28.228
        assert inv.venue_lng == 112.939


class TestListInvitations:

    @pytest.fixture
    def service(self):
        return InvitationService()

    @pytest.mark.asyncio
    async def test_list_returns_items(self, service):
        mock_inv1 = MagicMock(id="INV_001")
        mock_inv2 = MagicMock(id="INV_002")
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_inv1, mock_inv2]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        results = await service.list_invitations(mock_db, "S001")
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_list_empty(self, service):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        results = await service.list_invitations(mock_db, "S001")
        assert results == []


class TestGetById:

    @pytest.fixture
    def service(self):
        return InvitationService()

    @pytest.mark.asyncio
    async def test_found(self, service):
        mock_inv = MagicMock(id="INV_001")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_inv

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.get_by_id(mock_db, "INV_001")
        assert result.id == "INV_001"

    @pytest.mark.asyncio
    async def test_not_found(self, service):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.get_by_id(mock_db, "NONEXIST")
        assert result is None


class TestGetByShareToken:

    @pytest.fixture
    def service(self):
        return InvitationService()

    @pytest.mark.asyncio
    async def test_found_published(self, service):
        mock_inv = MagicMock(share_token="abc123", is_published=True)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_inv

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.get_by_share_token(mock_db, "abc123")
        assert result is not None

    @pytest.mark.asyncio
    async def test_not_found_unpublished(self, service):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.get_by_share_token(mock_db, "unpublished_token")
        assert result is None


class TestGenerateInvitationText:

    @pytest.fixture
    def service(self):
        return InvitationService()

    @pytest.mark.asyncio
    async def test_ai_generation_success(self, service):
        mock_inv = MagicMock(
            event_type="商务宴请",
            event_title="新品发布",
            host_name="张总",
            event_date=datetime(2026, 4, 1),
            venue_name="宴会厅",
            custom_message="",
        )

        with patch.object(service, "get_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_inv
            mock_db = AsyncMock()
            mock_db.commit = AsyncMock()

            # Mock the lazy import: from ..agents.llm_agent import LLMAgent
            mock_agent = MagicMock()
            mock_agent.generate_text = AsyncMock(return_value="尊敬的贵宾，诚邀参加...")
            mock_llm_class = MagicMock(return_value=mock_agent)

            import src.agents.llm_agent as llm_module
            with patch.object(llm_module, "LLMAgent", mock_llm_class, create=True):
                result = await service.generate_invitation_text(mock_db, "INV_001")
                assert result == "尊敬的贵宾，诚邀参加..."
                assert mock_inv.ai_generated_message == "尊敬的贵宾，诚邀参加..."

    @pytest.mark.asyncio
    async def test_ai_generation_fallback(self, service):
        """当 LLMAgent 不可用时，降级为模板文案"""
        mock_inv = MagicMock(
            event_type="婚宴",
            event_title="李王婚礼",
            host_name="李先生",
            event_date=datetime(2026, 5, 1),
            venue_name="红色宴会厅",
            custom_message="",
        )

        with patch.object(service, "get_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_inv
            mock_db = AsyncMock()
            mock_db.commit = AsyncMock()

            # LLMAgent import will fail (class doesn't exist in module) → triggers fallback
            result = await service.generate_invitation_text(mock_db, "INV_001")
            # Should use fallback template
            assert "李先生" in result
            assert "李王婚礼" in result
            assert "红色宴会厅" in result

    @pytest.mark.asyncio
    async def test_invitation_not_found_raises(self, service):
        with patch.object(service, "get_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None
            mock_db = AsyncMock()

            with pytest.raises(ValueError, match="邀请函不存在"):
                await service.generate_invitation_text(mock_db, "NONEXIST")

    @pytest.mark.asyncio
    async def test_ai_params_saved(self, service):
        mock_inv = MagicMock(
            event_type="生日宴",
            event_title="六十大寿",
            host_name="王总",
            event_date=datetime(2026, 6, 15),
            venue_name="金色宴会厅",
            custom_message="",
        )

        with patch.object(service, "get_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_inv
            mock_db = AsyncMock()
            mock_db.commit = AsyncMock()

            mock_agent = MagicMock()
            mock_agent.generate_text = AsyncMock(return_value="祝寿文案...")
            mock_llm_class = MagicMock(return_value=mock_agent)

            import src.agents.llm_agent as llm_module
            with patch.object(llm_module, "LLMAgent", mock_llm_class, create=True):
                await service.generate_invitation_text(
                    mock_db, "INV_001",
                    genre="古典诗词", mood="庄重", emotion="敬意",
                )

                assert mock_inv.ai_params["genre"] == "古典诗词"
                assert mock_inv.ai_params["mood"] == "庄重"
                assert mock_inv.ai_params["emotion"] == "敬意"


class TestPublish:

    @pytest.fixture
    def service(self):
        return InvitationService()

    @pytest.mark.asyncio
    async def test_publish_success(self, service):
        mock_inv = MagicMock(share_token="abc123def456")

        with patch.object(service, "get_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_inv
            mock_db = AsyncMock()
            mock_db.commit = AsyncMock()

            result = await service.publish(mock_db, "INV_001")
            assert mock_inv.is_published is True
            assert "abc123def456" in result["share_url"]
            assert result["share_token"] == "abc123def456"

    @pytest.mark.asyncio
    async def test_publish_not_found_raises(self, service):
        with patch.object(service, "get_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None
            mock_db = AsyncMock()

            with pytest.raises(ValueError, match="邀请函不存在"):
                await service.publish(mock_db, "NONEXIST")


class TestRecordRSVP:

    @pytest.fixture
    def service(self):
        return InvitationService()

    @pytest.mark.asyncio
    async def test_record_attending(self, service):
        mock_inv = MagicMock(rsvp_count=0)

        added_objects = []
        mock_db = AsyncMock()
        mock_db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        with patch.object(service, "get_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_inv

            result = await service.record_rsvp(
                session=mock_db,
                invitation_id="INV_001",
                guest_name="赵先生",
                guest_phone="13500135000",
                party_size=3,
                status="attending",
            )

            assert len(added_objects) == 1
            rsvp = added_objects[0]
            assert rsvp.guest_name == "赵先生"
            assert rsvp.party_size == 3
            assert rsvp.status == RSVPStatus.ATTENDING
            assert mock_inv.rsvp_count == 1

    @pytest.mark.asyncio
    async def test_record_declined(self, service):
        mock_inv = MagicMock(rsvp_count=5)

        added_objects = []
        mock_db = AsyncMock()
        mock_db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        with patch.object(service, "get_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_inv

            await service.record_rsvp(
                session=mock_db,
                invitation_id="INV_001",
                guest_name="钱女士",
                status="declined",
            )

            rsvp = added_objects[0]
            assert rsvp.status == RSVPStatus.DECLINED
            assert mock_inv.rsvp_count == 6


class TestGetRSVPStats:

    @pytest.fixture
    def service(self):
        return InvitationService()

    @pytest.mark.asyncio
    async def test_stats_with_data(self, service):
        rsvp1 = MagicMock(
            status=RSVPStatus.ATTENDING, party_size=3,
            guest_name="A", message="祝福", dietary_restrictions="无", created_at=datetime.now(),
        )
        rsvp2 = MagicMock(
            status=RSVPStatus.ATTENDING, party_size=2,
            guest_name="B", message="恭喜", dietary_restrictions="素食", created_at=datetime.now(),
        )
        rsvp3 = MagicMock(
            status=RSVPStatus.DECLINED, party_size=1,
            guest_name="C", message="抱歉", dietary_restrictions="", created_at=datetime.now(),
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [rsvp1, rsvp2, rsvp3]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        stats = await service.get_rsvp_stats(mock_db, "INV_001")
        assert stats["total"] == 3
        assert stats["attending"] == 2
        assert stats["attending_guests"] == 5  # 3 + 2
        assert stats["declined"] == 1
        assert len(stats["rsvps"]) == 3

    @pytest.mark.asyncio
    async def test_stats_empty(self, service):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        stats = await service.get_rsvp_stats(mock_db, "INV_001")
        assert stats["total"] == 0
        assert stats["attending"] == 0
        assert stats["attending_guests"] == 0
        assert stats["declined"] == 0


class TestIncrementView:

    @pytest.fixture
    def service(self):
        return InvitationService()

    @pytest.mark.asyncio
    async def test_increment_from_zero(self, service):
        mock_inv = MagicMock(view_count=0)
        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()

        await service.increment_view(mock_db, mock_inv)
        assert mock_inv.view_count == 1

    @pytest.mark.asyncio
    async def test_increment_from_existing(self, service):
        mock_inv = MagicMock(view_count=42)
        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()

        await service.increment_view(mock_db, mock_inv)
        assert mock_inv.view_count == 43

    @pytest.mark.asyncio
    async def test_increment_from_none(self, service):
        mock_inv = MagicMock(view_count=None)
        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()

        await service.increment_view(mock_db, mock_inv)
        assert mock_inv.view_count == 1


class TestEnumValues:
    """确保模型枚举值正确"""

    def test_invitation_templates(self):
        assert InvitationTemplate.WEDDING_RED.value == "wedding_red"
        assert InvitationTemplate.BIRTHDAY_GOLD.value == "birthday_gold"
        assert InvitationTemplate.CORPORATE_BLUE.value == "corporate_blue"
        assert InvitationTemplate.FULL_MOON_PINK.value == "full_moon_pink"
        assert InvitationTemplate.GRADUATION_GREEN.value == "graduation_green"

    def test_rsvp_statuses(self):
        assert RSVPStatus.ATTENDING.value == "attending"
        assert RSVPStatus.DECLINED.value == "declined"
        assert RSVPStatus.PENDING.value == "pending"
