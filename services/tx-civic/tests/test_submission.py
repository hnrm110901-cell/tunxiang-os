"""test_submission.py — 政府监管上报路由测试

覆盖范围 (/api/v1/civic/submissions):
  1. POST /batch              — 批量上报
  2. POST /{id}/retry         — 重试失败的上报
  3. GET  /stats              — 上报统计

依赖：
  - 通过 _DBOverride 注入 mock_db 避免真实 DB
"""
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api.submission_routes import router as submission_router

from conftest import (
    TENANT_ID,
    TENANT_HEADERS,
    _DBOverride,
    make_mock_db,
    make_mock_result,
)

# ─── 测试 app ─────────────────────────────────────────────────────────────────

_app = FastAPI(title="submission-test")
_app.include_router(submission_router)


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=_app), base_url="http://test"
    ) as ac:
        yield ac


# ─── 测试 ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_batch_submit(client: AsyncClient):
    """批量上报 3 条记录 → 返回 submission_ids 列表，count=3。"""
    mock_db = make_mock_db()
    mock_db.execute = AsyncMock()  # multiple INSERTs, no special return needed

    body = {
        "store_id": "store-001",
        "domain": "traceability",
        "record_ids": ["rec-001", "rec-002", "rec-003"],
    }

    with _DBOverride(_app, mock_db):
        resp = await client.post(
            "/api/v1/civic/submissions/batch",
            json=body,
            headers=TENANT_HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert len(data["data"]["submission_ids"]) == 3
    assert data["data"]["count"] == 3
    assert data["data"]["status"] == "pending"


@pytest.mark.asyncio
async def test_retry_failed(client: AsyncClient):
    """重试失败的上报 → status 变为 pending，retry_count 递增。"""
    mock_db = make_mock_db()
    submission_id = "sub-failed-001"

    # 3 execute calls: _set_tenant + SELECT check + UPDATE
    mock_db.execute = AsyncMock(side_effect=[
        make_mock_result(),               # _set_tenant
        make_mock_result(rows=[{
            "id": submission_id,
            "status": "failed",
            "retry_count": 2,
        }]),
        make_mock_result(rowcount=1),     # UPDATE result
    ])

    with _DBOverride(_app, mock_db):
        resp = await client.post(
            f"/api/v1/civic/submissions/{submission_id}/retry",
            headers=TENANT_HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["status"] == "pending"
    assert data["data"]["retry_count"] == 3  # 2 + 1 = 3


@pytest.mark.asyncio
async def test_retry_success_state_rejected(client: AsyncClient):
    """重试成功状态的上报 → HTTP 400。"""
    mock_db = make_mock_db()
    submission_id = "sub-success-001"

    # 2 execute calls: _set_tenant + SELECT check
    mock_db.execute = AsyncMock(side_effect=[
        make_mock_result(),               # _set_tenant
        make_mock_result(rows=[{
            "id": submission_id,
            "status": "success",
            "retry_count": 0,
        }]),
    ])

    with _DBOverride(_app, mock_db):
        resp = await client.post(
            f"/api/v1/civic/submissions/{submission_id}/retry",
            headers=TENANT_HEADERS,
        )

    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_retry_not_found(client: AsyncClient):
    """重试不存在的上报 → HTTP 404。"""
    mock_db = make_mock_db()

    # 2 execute calls: _set_tenant + SELECT (no rows)
    mock_db.execute = AsyncMock(side_effect=[
        make_mock_result(),
        make_mock_result(rows=[]),  # no rows found
    ])

    with _DBOverride(_app, mock_db):
        resp = await client.post(
            "/api/v1/civic/submissions/nonexistent/retry",
            headers=TENANT_HEADERS,
        )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_submission_stats(client: AsyncClient):
    """上报统计 → 返回 total、by_domain、recent_24h 指标。"""
    mock_db = make_mock_db()

    # First query: GROUP BY domain, status
    stats_rows = [
        {"domain": "traceability", "status": "success", "count": 50},
        {"domain": "traceability", "status": "failed", "count": 5},
        {"domain": "kitchen", "status": "success", "count": 30},
        {"domain": "kitchen", "status": "failed", "count": 2},
    ]
    # Second query: recent 24h
    recent_rows = [{"total": 20, "success": 18}]

    # 3 execute calls: _set_tenant + GROUP BY + recent 24h
    mock_db.execute = AsyncMock(side_effect=[
        make_mock_result(),                  # _set_tenant
        make_mock_result(rows=stats_rows),   # GROUP BY query
        make_mock_result(rows=recent_rows),  # recent 24h query
    ])

    with _DBOverride(_app, mock_db):
        resp = await client.get(
            "/api/v1/civic/submissions/stats",
            headers=TENANT_HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["total"] == 87  # 50+5+30+2
    assert "traceability" in data["data"]["by_domain"]
    assert "kitchen" in data["data"]["by_domain"]
    assert data["data"]["by_domain"]["traceability"]["success"] == 50
    assert data["data"]["recent_24h"]["total"] == 20
    assert data["data"]["recent_24h"]["success"] == 18
