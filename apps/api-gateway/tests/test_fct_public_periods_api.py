"""
FCT Public API: periods endpoints tests
"""
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

for _k, _v in {
    "DATABASE_URL": "postgresql+asyncpg://test:test@localhost/test",
    "REDIS_URL": "redis://localhost:6379/0",
    "CELERY_BROKER_URL": "redis://localhost:6379/0",
    "CELERY_RESULT_BACKEND": "redis://localhost:6379/0",
    "SECRET_KEY": "test-secret-key",
    "JWT_SECRET": "test-jwt-secret",
}.items():
    os.environ.setdefault(_k, _v)

from src.api.fct_public import close_period, list_periods, reopen_period  # noqa: E402


@pytest.mark.asyncio
async def test_list_periods_success():
    session = MagicMock()
    expected = {
        "items": [
            {"period_key": "2026-03", "status": "open"},
            {"period_key": "2026-02", "status": "closed"},
        ],
        "total": 2,
    }
    with patch("src.api.fct_public.fct_service.list_periods", new=AsyncMock(return_value=expected)):
        result = await list_periods(tenant_id="S001", start_key=None, end_key=None, session=session, _=None)
    assert result == expected


@pytest.mark.asyncio
async def test_close_period_maps_value_error_to_400():
    session = MagicMock()
    with patch("src.api.fct_public.fct_service.close_period", new=AsyncMock(side_effect=ValueError("period_key 格式应为 YYYY-MM"))):
        with pytest.raises(HTTPException) as exc:
            await close_period(period_key="202603", tenant_id="S001", session=session, _=None)
    assert exc.value.status_code == 400
    assert "YYYY-MM" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_reopen_period_success():
    session = MagicMock()
    expected = {"tenant_id": "S001", "period_key": "2026-02", "status": "open"}
    with patch("src.api.fct_public.fct_service.reopen_period", new=AsyncMock(return_value=expected)):
        result = await reopen_period(period_key="2026-02", tenant_id="S001", session=session, _=None)
    assert result["status"] == "open"
    assert result == expected
