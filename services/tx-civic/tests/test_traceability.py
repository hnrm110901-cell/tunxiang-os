"""test_traceability.py — 食品安全追溯路由测试

覆盖范围 (/api/v1/civic/trace):
  1. POST /inbound          — 录入进货台账
  2. GET  /batch/{batch_no} — 批次追溯完整链路
  3. POST /suppliers        — 供应商资质登记
  4. POST /coldchain        — 冷链温控记录
  5. GET  /completeness     — 追溯完整性检查

依赖：
  - 通过 _DBOverride 注入 mock_db 避免真实 DB
  - 所有 DB execute 返回 mock result
"""
import sys
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.traceability_routes import router as trace_router

from conftest import (
    TENANT_ID,
    TENANT_HEADERS,
    _DBOverride,
    make_mock_db,
    make_mock_result,
)

# ─── 测试 app ─────────────────────────────────────────────────────────────────

_app = FastAPI(title="trace-test")
_app.include_router(trace_router)


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=_app), base_url="http://test"
    ) as ac:
        yield ac


# ─── 测试 ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_inbound(client: AsyncClient):
    """录入进货台账 → 返回 ok=True、包含 id 和 batch_no。"""
    mock_db = make_mock_db()
    mock_db.execute = AsyncMock()  # DB INSERT 不需要特殊返回值

    body = {
        "store_id": "store-001",
        "supplier_name": "鲜丰农产品",
        "product_name": "番茄",
        "product_category": "蔬菜",
        "quantity": 100.0,
        "unit": "kg",
        "inspection_result": True,
    }

    with _DBOverride(_app, mock_db):
        resp = await client.post(
            "/api/v1/civic/trace/inbound",
            json=body,
            headers=TENANT_HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "id" in data["data"]
    assert "batch_no" in data["data"]


@pytest.mark.asyncio
async def test_get_batch_trace(client: AsyncClient):
    """批次追溯 → 返回进货台账 + 冷链记录的完整链路。"""
    mock_db = make_mock_db()
    batch_no = "B-20260501-abc12345"

    # First query: inbound records (one record found)
    # Second query: coldchain records (two records)
    inbound_rows = [{
        "id": str(uuid4()),
        "batch_no": batch_no,
        "product_name": "鲈鱼",
        "quantity": 50.0,
        "supplier_name": "海产供应商",
    }]
    coldchain_rows = [
        {
            "id": str(uuid4()),
            "batch_id": batch_no,
            "checkpoint": "出库",
            "temperature_c": 2.5,
        },
        {
            "id": str(uuid4()),
            "batch_id": batch_no,
            "checkpoint": "到店",
            "temperature_c": 3.0,
        },
    ]

    # 3 execute calls: _set_tenant + inbound query + coldchain query
    mock_db.execute = AsyncMock(side_effect=[
        make_mock_result(),                     # _set_tenant
        make_mock_result(rows=inbound_rows),    # inbound query
        make_mock_result(rows=coldchain_rows),  # coldchain query
    ])

    with _DBOverride(_app, mock_db):
        resp = await client.get(
            f"/api/v1/civic/trace/batch/{batch_no}",
            headers=TENANT_HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["batch_no"] == batch_no
    assert len(data["data"]["inbound_records"]) == 1
    assert len(data["data"]["coldchain_records"]) == 2


@pytest.mark.asyncio
async def test_get_batch_trace_not_found(client: AsyncClient):
    """批次不存在 → HTTP 404。"""
    mock_db = make_mock_db()
    # 3 execute calls: _set_tenant + inbound query (empty) + coldchain query
    mock_db.execute = AsyncMock(side_effect=[
        make_mock_result(),              # _set_tenant
        make_mock_result(rows=[]),        # no inbound records → triggers 404
        make_mock_result(rows=[]),        # no coldchain records
    ])

    with _DBOverride(_app, mock_db):
        resp = await client.get(
            "/api/v1/civic/trace/batch/nonexistent-batch",
            headers=TENANT_HEADERS,
        )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_register_supplier(client: AsyncClient):
    """供应商资质登记 → 返回 ok=True 及 id。"""
    mock_db = make_mock_db()
    mock_db.execute = AsyncMock()

    body = {
        "supplier_name": "鲜丰农产品",
        "license_no": "SP2024-001",
        "contact_name": "张三",
        "contact_phone": "13800138000",
    }

    with _DBOverride(_app, mock_db):
        resp = await client.post(
            "/api/v1/civic/trace/suppliers",
            json=body,
            headers=TENANT_HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "id" in data["data"]


@pytest.mark.asyncio
async def test_coldchain_record(client: AsyncClient):
    """冷链温控记录 → 返回 ok=True 及 id。"""
    mock_db = make_mock_db()
    mock_db.execute = AsyncMock()

    body = {
        "store_id": "store-001",
        "checkpoint": "出库",
        "temperature_c": 2.5,
        "humidity_pct": 85.0,
    }

    with _DBOverride(_app, mock_db):
        resp = await client.post(
            "/api/v1/civic/trace/coldchain",
            json=body,
            headers=TENANT_HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "id" in data["data"]


@pytest.mark.asyncio
async def test_trace_completeness(client: AsyncClient):
    """追溯完整性检查 → 返回 trace_completeness_pct 等指标。"""
    mock_db = make_mock_db()

    # 4 execute calls: _set_tenant + total_inbound + traced_count + inspected_count
    mock_db.execute = AsyncMock(side_effect=[
        make_mock_result(),                  # _set_tenant
        make_mock_result(scalar_value=20),    # total_inbound
        make_mock_result(scalar_value=15),    # traced_count
        make_mock_result(scalar_value=18),    # inspected_count
    ])

    with _DBOverride(_app, mock_db):
        resp = await client.get(
            "/api/v1/civic/trace/completeness?store_id=store-001&date=2026-05-01",
            headers=TENANT_HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["store_id"] == "store-001"
    assert data["data"]["total_inbound"] == 20
    assert data["data"]["traced_count"] == 15
    assert data["data"]["inspected_count"] == 18
    # trace_completeness = 15/20 = 75%
    assert data["data"]["trace_completeness_pct"] == 75.0
