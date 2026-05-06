"""test_kitchen.py — 明厨亮灶路由测试

覆盖范围 (/api/v1/civic/kitchen):
  1. POST /devices         — 注册监控设备
  2. GET  /online-rate     — 设备在线率
  3. PUT  /alerts/{id}/resolve — 处理告警

依赖：
  - 通过 _DBOverride 注入 mock_db 避免真实 DB
"""
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api.kitchen_routes import router as kitchen_router

from conftest import (
    TENANT_ID,
    TENANT_HEADERS,
    _DBOverride,
    make_mock_db,
    make_mock_result,
)

# ─── 测试 app ─────────────────────────────────────────────────────────────────

_app = FastAPI(title="kitchen-test")
_app.include_router(kitchen_router)


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=_app), base_url="http://test"
    ) as ac:
        yield ac


# ─── 测试 ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_device(client: AsyncClient):
    """注册明厨亮灶设备 → 返回 ok=True 及 device id。"""
    mock_db = make_mock_db()
    mock_db.execute = AsyncMock()

    body = {
        "store_id": "store-001",
        "device_name": "后厨主摄像头",
        "device_type": "camera",
        "device_brand": "海康威视",
        "device_model": "DS-2CD2T47G2",
        "serial_no": "SN-2024-001",
        "ai_enabled": True,
        "ai_capabilities": ["smoke_detection", "hat_detection"],
        "location_desc": "热菜区",
    }

    with _DBOverride(_app, mock_db):
        resp = await client.post(
            "/api/v1/civic/kitchen/devices",
            json=body,
            headers=TENANT_HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "id" in data["data"]


@pytest.mark.asyncio
async def test_get_online_rate(client: AsyncClient):
    """设备在线率 → 返回 total_devices、online_devices、online_rate_pct。"""
    mock_db = make_mock_db()

    # 3 execute calls: _set_tenant + total count + online count
    mock_db.execute = AsyncMock(side_effect=[
        make_mock_result(),                # _set_tenant
        make_mock_result(scalar_value=10),  # total devices
        make_mock_result(scalar_value=7),   # online devices
    ])

    with _DBOverride(_app, mock_db):
        resp = await client.get(
            "/api/v1/civic/kitchen/online-rate?store_id=store-001",
            headers=TENANT_HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["total_devices"] == 10
    assert data["data"]["online_devices"] == 7
    assert data["data"]["online_rate_pct"] == 70.0  # 7/10 = 70%


@pytest.mark.asyncio
async def test_online_rate_zero_devices(client: AsyncClient):
    """门店无设备 → 在线率 0%。"""
    mock_db = make_mock_db()

    # 3 execute calls: _set_tenant + total count + online count
    mock_db.execute = AsyncMock(side_effect=[
        make_mock_result(),                # _set_tenant
        make_mock_result(scalar_value=0),   # total = 0
        make_mock_result(scalar_value=0),   # online = 0
    ])

    with _DBOverride(_app, mock_db):
        resp = await client.get(
            "/api/v1/civic/kitchen/online-rate?store_id=store-001",
            headers=TENANT_HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["data"]["online_rate_pct"] == 0.0
    assert data["data"]["total_devices"] == 0


@pytest.mark.asyncio
async def test_resolve_alert(client: AsyncClient):
    """处理告警 → 返回 resolved=True。"""
    mock_db = make_mock_db()

    # 2 execute calls: _set_tenant + UPDATE
    mock_db.execute = AsyncMock(side_effect=[
        make_mock_result(),                # _set_tenant
        make_mock_result(rowcount=1),       # UPDATE → 1 row affected
    ])

    body = {
        "resolved_by": "inspector-001",
        "resolution_notes": "已清理烟道",
        "false_positive": False,
    }

    with _DBOverride(_app, mock_db):
        resp = await client.put(
            "/api/v1/civic/kitchen/alerts/alert-001/resolve",
            json=body,
            headers=TENANT_HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["resolved"] is True


@pytest.mark.asyncio
async def test_resolve_alert_not_found(client: AsyncClient):
    """处理不存在的告警 → HTTP 404。"""
    mock_db = make_mock_db()

    # 2 execute calls: _set_tenant + UPDATE (0 rows affected)
    mock_db.execute = AsyncMock(side_effect=[
        make_mock_result(),
        make_mock_result(rowcount=0),  # no rows affected → 404
    ])

    body = {
        "resolved_by": "inspector-001",
        "false_positive": False,
    }

    with _DBOverride(_app, mock_db):
        resp = await client.put(
            "/api/v1/civic/kitchen/alerts/alert-nonexistent/resolve",
            json=body,
            headers=TENANT_HEADERS,
        )

    assert resp.status_code == 404
