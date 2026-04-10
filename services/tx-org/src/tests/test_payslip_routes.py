"""工资条 API 测试 — payslip.py（prefix /api/v1/org）

覆盖端点：
  POST   /api/v1/org/payslips/generate       - 批量生成工资条
  GET    /api/v1/org/payslips                - 工资条列表（分页）
  GET    /api/v1/org/payslips/{pid}          - 查询单条工资条
  PATCH  /api/v1/org/payslips/{pid}/status   - 更新工资条状态
"""
import os
import sys
import types

# ── 路径注入 ──
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))

# ── 桩模块：payroll_engine（避免导入依赖缺失） ──
_pe_stub = types.ModuleType("services.payroll_engine")
_pe_stub.count_work_days = lambda year, mon: 22
_pe_stub.compute_base_salary = lambda base, att, wd: base * att // wd
_pe_stub.derive_hourly_rate = lambda base, wd: base // (wd * 8)
_pe_stub.compute_overtime_pay = lambda hr, hours, ot_type: hr * hours
_pe_stub.compute_absence_deduction = lambda base, absence, wd: base * absence // wd
_pe_stub.compute_late_deduction = lambda count, per: count * per
_pe_stub.compute_performance_bonus = lambda base, coeff: int(base * (coeff - 1))
_pe_stub.compute_seniority_subsidy = lambda months: min(months * 100, 5000)
_pe_stub.compute_full_attendance_bonus = lambda absence, late, early, bonus: (
    bonus if absence == 0 and late == 0 and early == 0 else 0
)
_pe_stub.compute_monthly_tax = lambda **kw: 0.0
_pe_stub.summarize_payroll = lambda **kw: {
    "gross_pay_fen": sum(v for k, v in kw.items() if "fen" in k and "deduction" not in k and "insurance" not in k and "fund" not in k and "tax" not in k),
    "deductions_fen": sum(v for k, v in kw.items() if "deduction" in k or "insurance" in k or "fund" in k or "tax" in k),
    "net_pay_fen": 300000,
}
sys.modules.setdefault("services.payroll_engine", _pe_stub)
# 也注册非包形式
sys.modules.setdefault("payroll_engine", _pe_stub)

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from api.payslip import router as payslip_router
from shared.ontology.src.database import get_db

# ── App fixture ──
app = FastAPI()
app.include_router(payslip_router)

TENANT_ID = str(uuid4())
STORE_ID = "store-001"
PAYSLIP_ID = str(uuid4())
MONTH = "2026-03"

HEADERS = {"X-Tenant-ID": TENANT_ID}


def _make_db_mock():
    """返回一个可在 with/async with 语句中使用的 DB mock。"""
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _make_result_mock(rows=None, scalar_value=None):
    """构造 execute 的返回值 mock。"""
    result = MagicMock()
    if scalar_value is not None:
        result.scalar_one = MagicMock(return_value=scalar_value)
    if rows is not None:
        result.mappings.return_value.first = MagicMock(
            return_value=rows[0] if rows else None
        )
        # 用于 list_payslips 的 for row in rows 遍历
        _mappings = MagicMock()
        _mappings.__iter__ = MagicMock(return_value=iter(rows))
        result.mappings.return_value = _mappings
        result.mappings.return_value.first = MagicMock(
            return_value=rows[0] if rows else None
        )
    return result


# ─────────────────────────────────────────────
# 辅助：构建员工数据
# ─────────────────────────────────────────────
def _emp(employee_id="emp-001"):
    return {
        "employee_id": employee_id,
        "name": "张三",
        "role": "cashier",
        "base_salary_fen": 500000,
        "attendance_days": 22,
        "absence_days": 0,
        "late_count": 0,
        "early_leave_count": 0,
        "overtime_hours": 2,
        "overtime_type": "weekday",
        "performance_coefficient": 1.0,
        "seniority_months": 12,
        "sales_amount_fen": 0,
        "commission_rate": 0,
        "position_allowance_fen": 20000,
        "meal_allowance_fen": 10000,
        "transport_allowance_fen": 5000,
    }


# ─────────────────────────────────────────────
# 测试 1：批量生成工资条 — 成功
# ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_generate_payslips_success():
    """POST /api/v1/org/payslips/generate，mock INSERT ON CONFLICT DO NOTHING → 200，generated≥0。"""
    db = _make_db_mock()
    # execute 每次返回一个带 RETURNING 结果的 mock（可以为空，表示冲突跳过）
    db.execute = AsyncMock(return_value=MagicMock())

    app.dependency_overrides[get_db] = lambda: db

    payload = {
        "store_id": STORE_ID,
        "month": MONTH,
        "employees": [_emp("emp-001"), _emp("emp-002")],
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/org/payslips/generate", json=payload, headers=HEADERS
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["generated"] >= 0
    assert body["data"]["store_id"] == STORE_ID

    app.dependency_overrides.clear()


# ─────────────────────────────────────────────
# 测试 2：批量生成工资条 — 空列表 → 400
# ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_generate_payslips_empty():
    """POST /api/v1/org/payslips/generate，employees=[] → 400（接口拒绝空列表）。"""
    db = _make_db_mock()
    app.dependency_overrides[get_db] = lambda: db

    payload = {"store_id": STORE_ID, "month": MONTH, "employees": []}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/org/payslips/generate", json=payload, headers=HEADERS
        )

    # payslip.py 明确校验空列表，返回 400
    assert resp.status_code == 400
    body = resp.json()
    assert "employees" in body["detail"].lower() or "empty" in body["detail"].lower()

    app.dependency_overrides.clear()


# ─────────────────────────────────────────────
# 测试 3：工资条列表 — 有数据
# ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_list_payslips_success():
    """GET /api/v1/org/payslips，mock COUNT+SELECT → 200，data.items 长度>0。"""
    db = _make_db_mock()

    fake_row = MagicMock()
    fake_row._mapping = {
        "id": PAYSLIP_ID,
        "store_id": STORE_ID,
        "employee_id": "emp-001",
        "pay_period": MONTH,
        "gross_pay_fen": 600000,
        "deductions_fen": 80000,
        "net_pay_fen": 520000,
        "breakdown": "{}",
        "meta": "{}",
        "status": "draft",
        "issued_at": None,
        "acknowledged_at": None,
        "created_at": "2026-03-31T10:00:00",
        "updated_at": "2026-03-31T10:00:00",
    }

    count_result = MagicMock()
    count_result.scalar_one = MagicMock(return_value=1)

    rows_result = MagicMock()
    rows_result.__iter__ = MagicMock(return_value=iter([fake_row]))

    call_count = 0

    async def _execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # set_config
            return MagicMock()
        elif call_count == 2:
            # COUNT
            return count_result
        else:
            # SELECT rows
            return rows_result

    db.execute = _execute

    app.dependency_overrides[get_db] = lambda: db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            f"/api/v1/org/payslips",
            params={"store_id": STORE_ID, "month": MONTH},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert len(body["data"]["items"]) > 0
    assert body["data"]["total"] == 1

    app.dependency_overrides.clear()


# ─────────────────────────────────────────────
# 测试 4：工资条列表 — 空结果
# ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_list_payslips_empty():
    """GET /api/v1/org/payslips，mock COUNT=0 → 200，data.items=[]。"""
    db = _make_db_mock()

    count_result = MagicMock()
    count_result.scalar_one = MagicMock(return_value=0)

    rows_result = MagicMock()
    rows_result.__iter__ = MagicMock(return_value=iter([]))

    call_count = 0

    async def _execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return MagicMock()  # set_config
        elif call_count == 2:
            return count_result  # COUNT
        else:
            return rows_result  # SELECT

    db.execute = _execute

    app.dependency_overrides[get_db] = lambda: db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/api/v1/org/payslips",
            params={"store_id": STORE_ID, "month": MONTH},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["items"] == []
    assert body["data"]["total"] == 0

    app.dependency_overrides.clear()


# ─────────────────────────────────────────────
# 测试 5：查询单条工资条 — 成功
# ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_get_payslip_success():
    """GET /api/v1/org/payslips/{pid}，mock SELECT 返回1条 → 200，data 含 employee_id。"""
    db = _make_db_mock()

    fake_record = {
        "id": PAYSLIP_ID,
        "store_id": STORE_ID,
        "employee_id": "emp-001",
        "pay_period": MONTH,
        "gross_pay_fen": 600000,
        "deductions_fen": 80000,
        "net_pay_fen": 520000,
        "breakdown": "{}",
        "meta": "{}",
        "status": "draft",
        "issued_at": None,
        "acknowledged_at": None,
        "created_at": "2026-03-31T10:00:00",
        "updated_at": "2026-03-31T10:00:00",
    }

    call_count = 0

    async def _execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count >= 2:
            mappings = MagicMock()
            mappings.first = MagicMock(return_value=fake_record)
            result.mappings = MagicMock(return_value=mappings)
        return result

    db.execute = _execute

    app.dependency_overrides[get_db] = lambda: db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            f"/api/v1/org/payslips/{PAYSLIP_ID}", headers=HEADERS
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "employee_id" in body["data"]
    assert body["data"]["employee_id"] == "emp-001"

    app.dependency_overrides.clear()


# ─────────────────────────────────────────────
# 测试 6：查询单条工资条 — 不存在 → 404
# ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_get_payslip_not_found():
    """GET /api/v1/org/payslips/{pid}，mock SELECT 返回 None → 404。"""
    db = _make_db_mock()

    call_count = 0

    async def _execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count >= 2:
            mappings = MagicMock()
            mappings.first = MagicMock(return_value=None)
            result.mappings = MagicMock(return_value=mappings)
        return result

    db.execute = _execute

    app.dependency_overrides[get_db] = lambda: db

    nonexistent_id = str(uuid4())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            f"/api/v1/org/payslips/{nonexistent_id}", headers=HEADERS
        )

    assert resp.status_code == 404
    body = resp.json()
    assert "not found" in body["detail"].lower()

    app.dependency_overrides.clear()


# ─────────────────────────────────────────────
# 测试 7：更新工资条状态 — 成功
# ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_update_payslip_status_success():
    """PATCH /api/v1/org/payslips/{pid}/status，mock UPDATE RETURNING → 200，data.status 已更新。"""
    db = _make_db_mock()

    updated_record = {
        "id": PAYSLIP_ID,
        "status": "issued",
        "updated_at": "2026-04-01T09:00:00",
    }

    call_count = 0

    async def _execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count >= 2:
            mappings = MagicMock()
            mappings.first = MagicMock(return_value=updated_record)
            result.mappings = MagicMock(return_value=mappings)
        return result

    db.execute = _execute

    app.dependency_overrides[get_db] = lambda: db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.patch(
            f"/api/v1/org/payslips/{PAYSLIP_ID}/status",
            json={"status": "issued"},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "issued"

    app.dependency_overrides.clear()
