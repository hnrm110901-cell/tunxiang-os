"""
FCT Public API: voucher endpoint error mapping tests
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

from src.api.fct_public import create_manual_voucher, red_flush_voucher, update_voucher_status  # noqa: E402


@pytest.mark.asyncio
async def test_create_manual_voucher_maps_closed_period_error_to_400():
    session = MagicMock()
    body = {
        "tenant_id": "T1",
        "entity_id": "S001",
        "biz_date": "2026-03-01",
        "lines": [
            {"account_code": "1001", "debit": 100, "credit": None},
            {"account_code": "6001", "debit": None, "credit": 100},
        ],
    }
    with patch(
        "src.api.fct_public.fct_service.create_manual_voucher",
        new=AsyncMock(side_effect=ValueError("会计期间 2026-03 已结账，禁止新增或过账凭证")),
    ):
        with pytest.raises(HTTPException) as exc:
            await create_manual_voucher(body=body, session=session, _=None)
    assert exc.value.status_code == 400
    assert "已结账" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_update_voucher_status_maps_closed_period_error_to_400():
    session = MagicMock()
    with patch(
        "src.api.fct_public.fct_service.update_voucher_status",
        new=AsyncMock(side_effect=ValueError("会计期间 2026-03 已结账，禁止新增或过账凭证")),
    ):
        with pytest.raises(HTTPException) as exc:
            await update_voucher_status(
                voucher_id="vid-1",
                body={"status": "posted"},
                session=session,
                _=None,
            )
    assert exc.value.status_code == 400
    assert "已结账" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_red_flush_maps_closed_period_error_to_400():
    session = MagicMock()
    with patch(
        "src.api.fct_public.fct_service.red_flush_voucher",
        new=AsyncMock(side_effect=ValueError("会计期间 2026-03 已结账，禁止新增或过账凭证")),
    ):
        with pytest.raises(HTTPException) as exc:
            await red_flush_voucher(voucher_id="vid-2", biz_date=None, session=session, _=None)
    assert exc.value.status_code == 400
    assert "已结账" in str(exc.value.detail)
