"""薪资记录 API 测试 — payroll_routes.py（Round 61 薪资记录，prefix /api/v1/payroll）

覆盖端点：
  GET    /api/v1/payroll/configs              - 薪资配置列表
  POST   /api/v1/payroll/configs              - 创建薪资配置
  PUT    /api/v1/payroll/configs/{id}         - 更新薪资配置
  DELETE /api/v1/payroll/configs/{id}         - 软删除薪资配置
  GET    /api/v1/payroll/records              - 薪资单列表
  POST   /api/v1/payroll/records              - 创建薪资单（draft）
  POST   /api/v1/payroll/records/{id}/approve - 审批薪资单（先查状态再更新）
  POST   /api/v1/payroll/records/{id}/void    - 作废薪资单（先查状态再更新）
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from api.payroll_routes import router as payroll_router
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from shared.ontology.src.database import get_db

app = FastAPI()
app.include_router(payroll_router)

TENANT_ID = str(uuid4())
STORE_ID = str(uuid4())
EMP_ID = str(uuid4())
CONFIG_ID = str(uuid4())
RECORD_ID = str(uuid4())


@pytest.fixture
def headers():
    return {
        "X-Tenant-ID": TENANT_ID,
        "Authorization": "Bearer test-token",
    }


def _make_mock_session():
    return AsyncMock()


def _override_db(mock_session):
    async def _mock_get_db():
        yield mock_session

    return _mock_get_db


def _make_mappings_result(rows: list[dict]):
    """模拟 .mappings().all() 返回。"""
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows
    return result


def _make_scalar_result(value):
    result = MagicMock()
    result.scalar.return_value = value
    return result


# ─── GET /configs ──────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_list_payroll_configs_ok(headers):
    """正常路径：返回薪资配置列表（两条记录）。"""
    mock_session = _make_mock_session()

    rows = [
        {"id": CONFIG_ID, "employee_role": "cashier", "salary_type": "monthly", "base_salary_fen": 400000},
        {"id": str(uuid4()), "employee_role": "chef", "salary_type": "monthly", "base_salary_fen": 500000},
    ]
    mock_session.execute = AsyncMock(side_effect=[MagicMock(), _make_mappings_result(rows)])

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/v1/payroll/configs", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert len(body["data"]) == 2
    assert body["data"][0]["employee_role"] == "cashier"


@pytest.mark.anyio
async def test_list_payroll_configs_filter_by_role(headers):
    """按 employee_role 过滤薪资配置。"""
    mock_session = _make_mock_session()

    rows = [{"id": CONFIG_ID, "employee_role": "waiter", "salary_type": "hourly"}]
    mock_session.execute = AsyncMock(side_effect=[MagicMock(), _make_mappings_result(rows)])

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(
                "/api/v1/payroll/configs",
                headers=headers,
                params={"employee_role": "waiter"},
            )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    assert r.json()["data"][0]["employee_role"] == "waiter"


# ─── POST /configs ─────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_create_payroll_config_ok(headers):
    """正常创建薪资配置，返回 config_id 和 created=True。"""
    mock_session = _make_mock_session()

    new_id = str(uuid4())
    insert_result = MagicMock()
    insert_result.fetchone.return_value = (new_id,)

    mock_session.execute = AsyncMock(side_effect=[MagicMock(), insert_result])
    mock_session.commit = AsyncMock()

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/api/v1/payroll/configs",
                headers=headers,
                json={
                    "employee_role": "cashier",
                    "salary_type": "monthly",
                    "base_salary_fen": 400000,
                    "commission_type": "none",
                    "kpi_bonus_max_fen": 20000,
                    "effective_from": "2026-01-01",
                    "is_active": True,
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["config_id"] == new_id
    assert body["data"]["created"] is True


@pytest.mark.anyio
async def test_create_payroll_config_missing_required(headers):
    """缺少必填字段（employee_role / effective_from）→ 422。"""
    mock_session = _make_mock_session()

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/api/v1/payroll/configs",
                headers=headers,
                json={"salary_type": "monthly"},
            )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 422


# ─── PUT /configs/{id} ─────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_update_payroll_config_ok(headers):
    """正常更新薪资配置，返回 updated=True。"""
    mock_session = _make_mock_session()

    update_result = MagicMock()
    update_result.fetchone.return_value = (CONFIG_ID,)
    mock_session.execute = AsyncMock(side_effect=[MagicMock(), update_result])
    mock_session.commit = AsyncMock()

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.put(
                f"/api/v1/payroll/configs/{CONFIG_ID}",
                headers=headers,
                json={"base_salary_fen": 450000},
            )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["updated"] is True


@pytest.mark.anyio
async def test_update_payroll_config_not_found(headers):
    """配置不存在时返回 404。"""
    mock_session = _make_mock_session()

    update_result = MagicMock()
    update_result.fetchone.return_value = None
    mock_session.execute = AsyncMock(side_effect=[MagicMock(), update_result])
    mock_session.commit = AsyncMock()

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.put(
                f"/api/v1/payroll/configs/{CONFIG_ID}",
                headers=headers,
                json={"base_salary_fen": 450000},
            )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 404


# ─── GET /records ──────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_list_payroll_records_ok(headers):
    """正常路径：返回薪资单列表，包含分页信息。"""
    mock_session = _make_mock_session()

    count_result = _make_scalar_result(1)
    rows = [
        {
            "id": RECORD_ID,
            "store_id": STORE_ID,
            "employee_id": EMP_ID,
            "gross_pay_fen": 450000,
            "net_pay_fen": 440000,
            "status": "draft",
        }
    ]
    list_result = _make_mappings_result(rows)

    mock_session.execute = AsyncMock(side_effect=[MagicMock(), count_result, list_result])

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/v1/payroll/records", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 1
    assert body["data"]["page"] == 1
    assert len(body["data"]["items"]) == 1


# ─── POST /records ─────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_create_payroll_record_ok(headers):
    """正常创建薪资单（draft 状态），验证净薪计算。
    gross = 400000+20000+0+0+10000-5000 = 425000 < 500000起征 → tax=0 → net=425000
    """
    mock_session = _make_mock_session()

    new_id = str(uuid4())
    insert_result = MagicMock()
    insert_result.fetchone.return_value = (new_id,)
    mock_session.execute = AsyncMock(side_effect=[MagicMock(), insert_result])
    mock_session.commit = AsyncMock()

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/api/v1/payroll/records",
                headers=headers,
                json={
                    "store_id": STORE_ID,
                    "employee_id": EMP_ID,
                    "pay_period_start": "2026-04-01",
                    "pay_period_end": "2026-04-30",
                    "base_pay_fen": 400000,
                    "overtime_pay_fen": 20000,
                    "commission_fen": 0,
                    "piecework_pay_fen": 0,
                    "kpi_bonus_fen": 10000,
                    "deduction_fen": 5000,
                    "payment_method": "bank",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["record_id"] == new_id
    assert body["data"]["status"] == "draft"
    assert body["data"]["net_pay_fen"] == 425000
    assert body["data"]["tax_fen"] == 0


@pytest.mark.anyio
async def test_create_payroll_record_missing_required(headers):
    """缺少必填字段 → 422。"""
    mock_session = _make_mock_session()

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/api/v1/payroll/records",
                headers=headers,
                json={"base_pay_fen": 400000},
            )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 422


# ─── POST /records/{id}/approve ────────────────────────────────────────────────


@pytest.mark.anyio
async def test_approve_payroll_record_ok(headers):
    """正常审批薪资单：先查 status=draft，再更新 → approved。"""
    mock_session = _make_mock_session()

    # 1. RLS；2. SELECT 查状态；3. UPDATE RETURNING
    select_result = MagicMock()
    select_result.mappings.return_value.first.return_value = {"id": RECORD_ID, "status": "draft"}
    update_result = MagicMock()
    update_result.mappings.return_value.first.return_value = {
        "id": RECORD_ID,
        "status": "approved",
        "approved_by": "hr-manager-001",
        "approved_at": "2026-04-04T10:00:00Z",
    }
    mock_session.execute = AsyncMock(side_effect=[MagicMock(), select_result, update_result])
    mock_session.commit = AsyncMock()

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                f"/api/v1/payroll/records/{RECORD_ID}/approve",
                headers=headers,
                json={"approved_by": "hr-manager-001"},
            )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "approved"
    assert body["data"]["approved_by"] == "hr-manager-001"


@pytest.mark.anyio
async def test_approve_payroll_record_not_found(headers):
    """审批不存在的薪资单返回 404。"""
    mock_session = _make_mock_session()

    select_result = MagicMock()
    select_result.mappings.return_value.first.return_value = None

    mock_session.execute = AsyncMock(side_effect=[MagicMock(), select_result])
    mock_session.commit = AsyncMock()

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                f"/api/v1/payroll/records/{RECORD_ID}/approve",
                headers=headers,
                json={"approved_by": "hr-manager-001"},
            )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 404


# ─── POST /records/{id}/void ───────────────────────────────────────────────────


@pytest.mark.anyio
async def test_void_payroll_record_ok(headers):
    """正常作废薪资单：先查状态，再更新 → voided。"""
    mock_session = _make_mock_session()

    select_result = MagicMock()
    select_result.mappings.return_value.first.return_value = {"id": RECORD_ID, "status": "approved"}
    update_result = MagicMock()
    update_result.mappings.return_value.first.return_value = {"id": RECORD_ID, "status": "voided"}
    mock_session.execute = AsyncMock(side_effect=[MagicMock(), select_result, update_result])
    mock_session.commit = AsyncMock()

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                f"/api/v1/payroll/records/{RECORD_ID}/void",
                headers=headers,
            )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "voided"


@pytest.mark.anyio
async def test_void_payroll_record_not_found(headers):
    """作废不存在的薪资单返回 404。"""
    mock_session = _make_mock_session()

    select_result = MagicMock()
    select_result.mappings.return_value.first.return_value = None

    mock_session.execute = AsyncMock(side_effect=[MagicMock(), select_result])
    mock_session.commit = AsyncMock()

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                f"/api/v1/payroll/records/{RECORD_ID}/void",
                headers=headers,
            )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 404
