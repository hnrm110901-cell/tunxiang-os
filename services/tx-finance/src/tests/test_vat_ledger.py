"""增值税台账 API 测试 — Y-F9

8 个测试用例，覆盖销项/进项台账、月度汇总、抵扣状态、科目映射、诺诺 POC。
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from api.vat_ledger_routes import router
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# ── 测试 App ──────────────────────────────────────────────────────────────────

app = FastAPI()
app.include_router(router)

TENANT_ID = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}


def _make_mock_db():
    """返回 mock AsyncSession，execute 返回可配置结果。"""
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _mock_scalar(value):
    result = MagicMock()
    result.scalar_one.return_value = value
    return result


def _mock_rows(rows: list[dict]):
    result = MagicMock()
    mock_rows = []
    for row in rows:
        r = MagicMock()
        r._mapping = row
        mock_rows.append(r)
    result.fetchone.return_value = mock_rows[0] if mock_rows else None
    result.fetchall.return_value = mock_rows

    # 让 result 可迭代（供 [dict(r._mapping) for r in result] 使用）
    result.__iter__ = MagicMock(return_value=iter(mock_rows))
    return result


# ── 1. test_create_output_record ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_output_record():
    """POST /output 新增销项税记录应返回 201 和新记录 id。"""
    mock_db = _make_mock_db()
    mock_db.execute = AsyncMock(return_value=MagicMock())

    with patch("api.vat_ledger_routes.get_db_with_tenant", return_value=_async_gen(mock_db)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/finance/vat/output",
                json={
                    "period_month": "2026-04",
                    "tax_code": "3010101",
                    "tax_rate": "0.06",
                    "amount_excl_tax_fen": 10000,
                    "tax_amount_fen": 600,
                    "amount_incl_tax_fen": 10600,
                    "invoice_date": "2026-04-01",
                    "buyer_name": "测试买方",
                },
                headers=HEADERS,
            )

    assert resp.status_code == 201
    data = resp.json()
    assert data["ok"] is True
    assert "id" in data["data"]
    assert data["data"]["period_month"] == "2026-04"


# ── 2. test_create_input_record ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_input_record():
    """POST /input 新增进项税记录应返回 201 和新记录 id。"""
    mock_db = _make_mock_db()
    mock_db.execute = AsyncMock(return_value=MagicMock())

    with patch("api.vat_ledger_routes.get_db_with_tenant", return_value=_async_gen(mock_db)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/finance/vat/input",
                json={
                    "period_month": "2026-04",
                    "tax_code": "3010101",
                    "tax_rate": "0.09",
                    "amount_excl_tax_fen": 5000,
                    "tax_amount_fen": 450,
                    "amount_incl_tax_fen": 5450,
                    "invoice_date": "2026-04-05",
                    "seller_name": "供应商甲",
                    "pl_account_code": "6001",
                },
                headers=HEADERS,
            )

    assert resp.status_code == 201
    data = resp.json()
    assert data["ok"] is True
    assert "id" in data["data"]


# ── 3. test_monthly_summary_calculation ──────────────────────────────────────


@pytest.mark.asyncio
async def test_monthly_summary_calculation():
    """GET /summary/{period_month} 应返回 net_payable = output - input。"""
    mock_db = _make_mock_db()

    output_row = MagicMock()
    output_row.output_tax_fen = 12000
    output_row.output_count = 150

    input_row = MagicMock()
    input_row.input_tax_fen = 8000
    input_row.input_count = 80

    pl_mock = MagicMock()
    pl_mock.__iter__ = MagicMock(return_value=iter([]))

    call_count = 0

    async def _execute_side_effect(stmt, params=None):
        nonlocal call_count
        call_count += 1
        mock_result = MagicMock()
        if call_count == 1:
            mock_result.fetchone.return_value = output_row
        elif call_count == 2:
            mock_result.fetchone.return_value = input_row
        else:
            mock_result.__iter__ = MagicMock(return_value=iter([]))
        return mock_result

    mock_db.execute = _execute_side_effect

    with patch("api.vat_ledger_routes.get_db_with_tenant", return_value=_async_gen(mock_db)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/finance/vat/summary/2026-04",
                headers=HEADERS,
            )

    assert resp.status_code == 200
    d = resp.json()["data"]
    assert d["output_tax_fen"] == 12000
    assert d["input_tax_fen"] == 8000
    assert d["net_payable_fen"] == 4000  # 12000 - 8000 = 4000
    assert d["period_month"] == "2026-04"


# ── 4. test_monthly_summary_all_integers ──────────────────────────────────────


@pytest.mark.asyncio
async def test_monthly_summary_all_integers():
    """所有金额字段必须是整数（无浮点）。"""
    mock_db = _make_mock_db()

    output_row = MagicMock()
    output_row.output_tax_fen = 99999
    output_row.output_count = 1

    input_row = MagicMock()
    input_row.input_tax_fen = 33333
    input_row.input_count = 1

    call_count = 0

    async def _execute_side_effect(stmt, params=None):
        nonlocal call_count
        call_count += 1
        mock_result = MagicMock()
        if call_count == 1:
            mock_result.fetchone.return_value = output_row
        elif call_count == 2:
            mock_result.fetchone.return_value = input_row
        else:
            mock_result.__iter__ = MagicMock(return_value=iter([]))
        return mock_result

    mock_db.execute = _execute_side_effect

    with patch("api.vat_ledger_routes.get_db_with_tenant", return_value=_async_gen(mock_db)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/finance/vat/summary/2026-04",
                headers=HEADERS,
            )

    assert resp.status_code == 200
    d = resp.json()["data"]
    for field in ("output_tax_fen", "input_tax_fen", "net_payable_fen", "output_count", "input_count"):
        assert isinstance(d[field], int), f"{field} 不是整数: {type(d[field])}"


# ── 5. test_deduct_input_record ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_deduct_input_record():
    """PUT /input/{id}/deduct 标记抵扣，应返回 deduction_status=deducted。"""
    mock_db = _make_mock_db()
    record_id = uuid.uuid4()

    updated_row = MagicMock()
    updated_row.id = str(record_id)

    mock_result = MagicMock()
    mock_result.fetchone.return_value = updated_row
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch("api.vat_ledger_routes.get_db_with_tenant", return_value=_async_gen(mock_db)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                f"/api/v1/finance/vat/input/{record_id}/deduct",
                headers=HEADERS,
            )

    assert resp.status_code == 200
    d = resp.json()["data"]
    assert d["deduction_status"] == "deducted"
    assert d["id"] == str(record_id)


# ── 6. test_pl_account_update ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pl_account_update():
    """PUT /pl-accounts/{tax_code} 更新科目映射，应返回 tax_code 和 pl_account_code。"""
    mock_db = _make_mock_db()
    mock_db.execute = AsyncMock(return_value=MagicMock())

    with patch("api.vat_ledger_routes.get_db_with_tenant", return_value=_async_gen(mock_db)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                "/api/v1/finance/vat/pl-accounts/3010101",
                json={
                    "pl_account_code": "6001",
                    "pl_account_name": "主营业务收入",
                    "account_type": "revenue",
                    "is_active": True,
                },
                headers=HEADERS,
            )

    assert resp.status_code == 200
    d = resp.json()["data"]
    assert d["tax_code"] == "3010101"
    assert d["pl_account_code"] == "6001"


# ── 7. test_nuonuo_poc_returns_mock_id ────────────────────────────────────────


@pytest.mark.asyncio
async def test_nuonuo_poc_returns_mock_id():
    """POST /nuonuo/sync-poc 应返回 MOCK_ 前缀的流水号和 mock=True 标记。"""
    invoice_id = uuid.uuid4()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/finance/vat/nuonuo/sync-poc",
            json={
                "invoice_id": str(invoice_id),
                "buyer_name": "测试买方",
                "total_amount_fen": 10600,
            },
            headers=HEADERS,
        )

    assert resp.status_code == 202
    d = resp.json()["data"]
    assert d["nuonuo_order_id"].startswith("MOCK_")
    assert d["status"] == "submitted"
    assert d["mock"] is True
    assert d["invoice_id"] == str(invoice_id)


# ── 8. test_output_list_by_period ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_output_list_by_period():
    """GET /output?period_month=2026-04 应返回分页结果。"""
    mock_db = _make_mock_db()

    call_count = 0
    sample_row = {
        "id": str(uuid.uuid4()),
        "period_month": "2026-04",
        "tax_amount_fen": 600,
        "status": "normal",
    }

    async def _execute_side_effect(stmt, params=None):
        nonlocal call_count
        call_count += 1
        mock_result = MagicMock()
        if call_count == 1:
            mock_result.scalar_one.return_value = 1
        else:
            r = MagicMock()
            r._mapping = sample_row
            mock_result.__iter__ = MagicMock(return_value=iter([r]))
        return mock_result

    mock_db.execute = _execute_side_effect

    with patch("api.vat_ledger_routes.get_db_with_tenant", return_value=_async_gen(mock_db)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/finance/vat/output?period_month=2026-04",
                headers=HEADERS,
            )

    assert resp.status_code == 200
    d = resp.json()["data"]
    assert d["total"] == 1
    assert len(d["items"]) == 1
    assert d["items"][0]["period_month"] == "2026-04"


# ── 辅助函数 ──────────────────────────────────────────────────────────────────


async def _async_gen(value):
    """将普通值包装为异步生成器，用于 mock get_db_with_tenant。"""
    yield value
