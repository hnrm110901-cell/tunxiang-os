"""加盟管理 V4 API 测试 — franchise_v4_routes.py（Round 73 Mock→DB 改造）

覆盖端点：
  GET  /api/v1/franchise/v4/franchisees         - 加盟商列表
  GET  /api/v1/franchise/v4/franchisees/{id}    - 加盟商详情
  POST /api/v1/franchise/v4/franchisees         - 新增加盟商
  PATCH /api/v1/franchise/v4/franchisees/{id}   - 更新加盟商
  GET  /api/v1/franchise/v4/contracts           - 合同列表
  POST /api/v1/franchise/v4/contracts           - 签署合同
  GET  /api/v1/franchise/v4/fees                - 费用列表
  GET  /api/v1/franchise/v4/fees/overdue        - 逾期费用
  GET  /api/v1/franchise/v4/stats               - 聚合统计
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))

import pytest
from contextlib import asynccontextmanager
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from api.franchise_v4_routes import router as franchise_v4_router
from shared.ontology.src.database import get_db

app = FastAPI()
app.include_router(franchise_v4_router)

TENANT_ID = str(uuid4())
STORE_ID = str(uuid4())


@pytest.fixture
def headers():
    return {
        "X-Tenant-ID": TENANT_ID,
        "Authorization": "Bearer test-token",
    }


def _make_mock_session() -> MagicMock:
    """返回一个 AsyncMock SQLAlchemy session。"""
    return AsyncMock()


def _override_db(mock_session):
    """返回一个可以替换 get_db 的 async generator。"""
    async def _mock_get_db():
        yield mock_session
    return _mock_get_db


def _make_row(data: dict):
    row = MagicMock()
    row._mapping = data
    return row


# ─── GET /franchisees ─────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_list_franchisees_ok(headers):
    """正常路径：返回加盟商列表。"""
    mock_session = _make_mock_session()

    fake_row = _make_row({"id": "f001", "name": "张三加盟商", "status": "active"})
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [fake_row]
    mock_session.execute = AsyncMock(return_value=mock_result)

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/v1/franchise/v4/franchisees", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 1
    assert body["data"]["items"][0]["name"] == "张三加盟商"


@pytest.mark.anyio
async def test_list_franchisees_db_error_fallback(headers):
    """DB 异常时 fallback 返回空列表，ok=True。"""
    from sqlalchemy.exc import SQLAlchemyError

    mock_session = _make_mock_session()
    mock_session.execute = AsyncMock(side_effect=SQLAlchemyError("db down"))

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(
                "/api/v1/franchise/v4/franchisees",
                headers=headers,
                params={"status": "active"},
            )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["items"] == []
    assert body["data"]["total"] == 0


# ─── GET /franchisees/{id} ─────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_get_franchisee_detail_ok(headers):
    """正常路径：返回加盟商详情（含合同和费用）。"""
    mock_session = _make_mock_session()
    fid = "f001"

    main_row = _make_row({"id": fid, "name": "张三加盟商", "status": "active"})
    main_result = MagicMock()
    main_result.fetchone.return_value = main_row

    contract_row = _make_row({"id": "c001", "franchisee_id": fid})
    contract_result = MagicMock()
    contract_result.fetchall.return_value = [contract_row]

    fee_row = _make_row({"id": "fee001", "franchisee_id": fid, "amount_fen": 50000})
    fee_result = MagicMock()
    fee_result.fetchall.return_value = [fee_row]

    # execute 依次：RLS set_config → 主查询 → 合同查询 → 费用查询
    mock_session.execute = AsyncMock(
        side_effect=[MagicMock(), main_result, contract_result, fee_result]
    )

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(f"/api/v1/franchise/v4/franchisees/{fid}", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["id"] == fid
    assert len(body["data"]["contracts"]) == 1
    assert len(body["data"]["fees"]) == 1


@pytest.mark.anyio
async def test_get_franchisee_not_found(headers):
    """加盟商不存在时返回 404。"""
    mock_session = _make_mock_session()
    empty_result = MagicMock()
    empty_result.fetchone.return_value = None
    mock_session.execute = AsyncMock(side_effect=[MagicMock(), empty_result])

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(
                "/api/v1/franchise/v4/franchisees/nonexistent", headers=headers
            )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 404


# ─── POST /franchisees ─────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_create_franchisee_ok(headers):
    """正常创建加盟商，返回 id 和 status=active。"""
    mock_session = _make_mock_session()

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/api/v1/franchise/v4/franchisees",
                headers=headers,
                json={
                    "name": "李四",
                    "contact_phone": "13800138000",
                    "region": "湖南省长沙市",
                    "store_name": "尝在一起（河西店）",
                    "store_address": "长沙市岳麓区河西大道100号",
                    "franchise_type": "standard",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "id" in body["data"]
    assert body["data"]["status"] == "active"
    assert body["data"]["name"] == "李四"


@pytest.mark.anyio
async def test_create_franchisee_missing_required_fields(headers):
    """缺少必填字段 → 422。"""
    mock_session = _make_mock_session()

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/api/v1/franchise/v4/franchisees",
                headers=headers,
                json={"name": "李四"},  # 缺 contact_phone / region / store_name / store_address
            )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 422


# ─── GET /contracts ─────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_list_contracts_ok(headers):
    """正常路径：返回合同列表。"""
    mock_session = _make_mock_session()

    row = _make_row({"id": "c001", "contract_no": "C2024001", "franchisee_id": "f001"})
    result = MagicMock()
    result.fetchall.return_value = [row]
    mock_session.execute = AsyncMock(return_value=result)

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/v1/franchise/v4/contracts", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 1


@pytest.mark.anyio
async def test_list_contracts_db_error_fallback(headers):
    """DB 异常时 fallback 返回空列表。"""
    from sqlalchemy.exc import SQLAlchemyError

    mock_session = _make_mock_session()
    mock_session.execute = AsyncMock(side_effect=SQLAlchemyError("timeout"))

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(
                "/api/v1/franchise/v4/contracts",
                headers=headers,
                params={"franchisee_id": "f001"},
            )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    assert r.json()["data"]["items"] == []


# ─── POST /contracts ─────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_create_contract_missing_fields(headers):
    """缺少必填字段 → 422。"""
    mock_session = _make_mock_session()

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/api/v1/franchise/v4/contracts",
                headers=headers,
                json={"franchisee_id": "f001"},  # 缺 contract_no/sign_date 等
            )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 422


# ─── GET /fees ─────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_list_fees_with_stats_ok(headers):
    """正常路径：返回费用列表及汇总统计。"""
    mock_session = _make_mock_session()

    fee_row = _make_row({"id": "fee001", "franchisee_id": "f001", "amount_fen": 10000, "status": "pending"})
    fees_result = MagicMock()
    fees_result.fetchall.return_value = [fee_row]

    stats_row = _make_row({"status": "pending", "cnt": 1, "total_fen": 10000})
    stats_result = MagicMock()
    stats_result.fetchall.return_value = [stats_row]

    # execute: RLS set_config → 费用列表 → 汇总统计
    mock_session.execute = AsyncMock(side_effect=[MagicMock(), fees_result, stats_result])

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/v1/franchise/v4/fees", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 1
    assert "pending_amount_fen" in body["data"]
    assert "overdue_count" in body["data"]


@pytest.mark.anyio
async def test_list_fees_db_error_fallback(headers):
    """DB 异常时返回带零统计的 fallback 响应。"""
    from sqlalchemy.exc import SQLAlchemyError

    mock_session = _make_mock_session()
    mock_session.execute = AsyncMock(side_effect=SQLAlchemyError("connection lost"))

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/v1/franchise/v4/fees", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["overdue_count"] == 0
    assert body["data"]["pending_amount_fen"] == 0


# ─── GET /stats ─────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_franchise_stats_ok(headers):
    """正常路径：返回加盟体系聚合统计。"""
    mock_session = _make_mock_session()

    f_row = _make_row({"total": 10, "active_count": 8, "suspended_count": 1, "terminated_count": 1})
    f_result = MagicMock()
    f_result.fetchone.return_value = f_row

    fee_row = _make_row({"overdue_fee_count": 2, "overdue_fee_amount_fen": 50000})
    fee_result = MagicMock()
    fee_result.fetchone.return_value = fee_row

    mock_session.execute = AsyncMock(side_effect=[MagicMock(), f_result, fee_result])

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/v1/franchise/v4/stats", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["total_franchisees"] == 10
    assert body["data"]["active_count"] == 8
    assert body["data"]["overdue_fee_count"] == 2


@pytest.mark.anyio
async def test_franchise_stats_db_error_fallback(headers):
    """DB 异常时 fallback 返回全零统计。"""
    from sqlalchemy.exc import SQLAlchemyError

    mock_session = _make_mock_session()
    mock_session.execute = AsyncMock(side_effect=SQLAlchemyError("timeout"))

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/v1/franchise/v4/stats", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["total_franchisees"] == 0
    assert body["data"]["overdue_fee_count"] == 0
