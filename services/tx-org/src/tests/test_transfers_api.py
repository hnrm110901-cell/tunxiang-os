"""门店借调 API 测试 — transfers.py（Round 61 调岗4端点）

覆盖端点：
  POST /api/v1/org/transfers                      - 创建借调单
  GET  /api/v1/org/transfers                      - 列表查询
  POST /api/v1/org/transfers/{id}/approve         - 审批借调单
  POST /api/v1/org/cost-split                     - 成本分摊
  POST /api/v1/org/cost-split/report              - 三表报告

注意：transfers.py 使用内存存储（_transfer_store），无需 mock DB。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from uuid import uuid4

import api.transfers as transfers_module
from api.transfers import router as transfer_router

app = FastAPI()
app.include_router(transfer_router)

TENANT_ID = str(uuid4())
STORE_A = "store-a-001"
STORE_B = "store-b-002"
EMP_ID = "emp-001"


@pytest.fixture(autouse=True)
def clear_transfer_store():
    """每个测试前后清空内存存储，保证隔离。"""
    transfers_module._transfer_store.clear()
    yield
    transfers_module._transfer_store.clear()


@pytest.fixture
def headers():
    return {
        "X-Tenant-ID": TENANT_ID,
        "Authorization": "Bearer test-token",
    }


def _create_transfer_payload(**overrides):
    base = {
        "employee_id": EMP_ID,
        "employee_name": "张三",
        "from_store_id": STORE_A,
        "from_store_name": "长沙一店",
        "to_store_id": STORE_B,
        "to_store_name": "长沙二店",
        "start_date": "2026-04-10",
        "end_date": "2026-04-20",
        "reason": "人手不足支援",
    }
    base.update(overrides)
    return base


# ─── POST /transfers ──────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_create_transfer_ok(headers):
    """正常创建借调单，返回 id 和订单信息，状态为 pending。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/org/transfers",
            headers=headers,
            json=_create_transfer_payload(),
        )

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    data = body["data"]
    assert "id" in data
    assert data["employee_id"] == EMP_ID
    assert data["from_store_id"] == STORE_A
    assert data["to_store_id"] == STORE_B
    assert data["status"] == "pending"


@pytest.mark.anyio
async def test_create_transfer_missing_required_fields(headers):
    """缺少必填字段 → 422。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/org/transfers",
            headers=headers,
            json={"employee_id": EMP_ID},  # 缺 employee_name / from_store_id 等
        )

    assert r.status_code == 422


@pytest.mark.anyio
async def test_create_transfer_invalid_dates(headers):
    """结束日期早于开始日期时服务层应拒绝（400）。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/org/transfers",
            headers=headers,
            json=_create_transfer_payload(start_date="2026-04-20", end_date="2026-04-10"),
        )

    # store_transfer_service 会抛 ValueError → 400
    assert r.status_code == 400


# ─── GET /transfers ───────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_list_transfers_empty(headers):
    """无借调单时返回空列表。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/v1/org/transfers", headers=headers)

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 0
    assert body["data"]["items"] == []


@pytest.mark.anyio
async def test_list_transfers_with_data(headers):
    """创建若干借调单后列表查询应返回正确数量。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/api/v1/org/transfers", headers=headers, json=_create_transfer_payload())
        await client.post(
            "/api/v1/org/transfers",
            headers=headers,
            json=_create_transfer_payload(employee_id="emp-002", employee_name="李四"),
        )
        r = await client.get("/api/v1/org/transfers", headers=headers)

    assert r.status_code == 200
    assert r.json()["data"]["total"] == 2


@pytest.mark.anyio
async def test_list_transfers_filter_by_store(headers):
    """按 store_id 过滤借调单，只返回相关门店的。"""
    store_c = "store-c-003"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/api/v1/org/transfers", headers=headers, json=_create_transfer_payload())
        await client.post(
            "/api/v1/org/transfers",
            headers=headers,
            json=_create_transfer_payload(
                from_store_id=store_c, from_store_name="长沙三店",
                to_store_id="store-d-004", to_store_name="长沙四店",
            ),
        )
        r = await client.get(
            "/api/v1/org/transfers",
            headers=headers,
            params={"store_id": store_c},
        )

    assert r.status_code == 200
    assert r.json()["data"]["total"] == 1


# ─── POST /transfers/{id}/approve ─────────────────────────────────────────────

@pytest.mark.anyio
async def test_approve_transfer_ok(headers):
    """审批借调单，状态变为 approved，带 approver_id。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_r = await client.post(
            "/api/v1/org/transfers", headers=headers, json=_create_transfer_payload()
        )
        transfer_id = create_r.json()["data"]["id"]

        r = await client.post(
            f"/api/v1/org/transfers/{transfer_id}/approve",
            headers=headers,
            json={"approver_id": "mgr-001"},
        )

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "approved"
    assert body["data"]["approved_by"] == "mgr-001"  # approve_transfer_order 返回 approved_by


@pytest.mark.anyio
async def test_approve_transfer_not_found(headers):
    """审批不存在的借调单返回 404。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/org/transfers/nonexistent-id/approve",
            headers=headers,
            json={"approver_id": "mgr-001"},
        )

    assert r.status_code == 404


# ─── POST /cost-split ─────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_cost_split_ok(headers):
    """成本分摊：正常路径返回 time_split 和 cost_split。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_r = await client.post(
            "/api/v1/org/transfers", headers=headers, json=_create_transfer_payload()
        )
        transfer_id = create_r.json()["data"]["id"]

        r = await client.post(
            "/api/v1/org/cost-split",
            headers=headers,
            json={
                "transfers": [{
                    "id": transfer_id,
                    "employee_id": EMP_ID,
                    "from_store_id": STORE_A,
                    "to_store_id": STORE_B,
                    "start_date": "2026-04-10",
                    "end_date": "2026-04-20",
                }],
                "attendance_records": [
                    {
                        "employee_id": EMP_ID,
                        "date": "2026-04-11",
                        "hours": 8.0,
                        "store_id": STORE_B,
                    }
                ],
                "salary_data": {
                    "base_fen": 500000,
                    "overtime_fen": 0,
                    "social_fen": 50000,
                    "bonus_fen": 0,
                },
            },
        )

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "time_split" in body["data"]
    assert "cost_split" in body["data"]


@pytest.mark.anyio
async def test_cost_split_missing_required_fields(headers):
    """缺少必填字段 → 422。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/org/cost-split",
            headers=headers,
            json={"transfers": []},  # 缺 attendance_records / salary_data
        )

    assert r.status_code == 422


# ─── POST /cost-split/report ─────────────────────────────────────────────────

@pytest.mark.anyio
async def test_cost_report_summary_ok(headers):
    """summary 报告正常路径。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_r = await client.post(
            "/api/v1/org/transfers", headers=headers, json=_create_transfer_payload()
        )
        transfer_id = create_r.json()["data"]["id"]

        r = await client.post(
            "/api/v1/org/cost-split/report",
            headers=headers,
            json={
                "report_type": "summary",
                "transfers": [{
                    "id": transfer_id,
                    "employee_id": EMP_ID,
                    "from_store_id": STORE_A,
                    "to_store_id": STORE_B,
                    "start_date": "2026-04-10",
                    "end_date": "2026-04-20",
                }],
                "attendance_records": [
                    {
                        "employee_id": EMP_ID,
                        "date": "2026-04-11",
                        "hours": 8.0,
                        "store_id": STORE_B,
                    }
                ],
                "salary_data": {
                    "base_fen": 500000,
                    "overtime_fen": 0,
                    "social_fen": 50000,
                    "bonus_fen": 0,
                },
            },
        )

    assert r.status_code == 200
    assert r.json()["ok"] is True


@pytest.mark.anyio
async def test_cost_report_unknown_type(headers):
    """未知 report_type → 400。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/v1/org/cost-split/report",
            headers=headers,
            json={
                "report_type": "unknown",
                "transfers": [],
                "attendance_records": [],
                "salary_data": {"base_fen": 0, "overtime_fen": 0, "social_fen": 0, "bonus_fen": 0},
            },
        )

    assert r.status_code == 400
