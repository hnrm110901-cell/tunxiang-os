import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestMarketingTaskService:
    @pytest.mark.asyncio
    async def test_create_task(self):
        from src.services.marketing_task_service import marketing_task_service

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        result = await marketing_task_service.create_task(
            db=mock_db,
            brand_id="BRAND001",
            title="生日关怀",
            audience_type="preset",
            audience_config={"preset_id": "birthday_week"},
            created_by=uuid.uuid4(),
        )
        assert result["success"] is True
        assert "task_id" in result

    @pytest.mark.asyncio
    async def test_preset_birthday_week(self):
        """预设人群包：近一周生日"""
        from src.services.marketing_task_service import marketing_task_service
        sql = marketing_task_service._preset_to_sql("birthday_week")
        assert "birth_date" in sql
