"""协议单位体系测试 (TC-P1-09)

测试：
  1. test_create_unit_with_credit_limit   — 新建协议单位，授信额度正确存储
  2. test_charge_within_credit_limit      — 挂账金额在授信内成功
  3. test_charge_exceeds_credit_limit     — 超授信额度挂账被拒绝（返回400）
  4. test_repay_updates_balance           — 还款后余额正确减少
  5. test_aging_report_categorization     — 账龄按天数分组正确

Mock 路径：shared.ontology.src.database.get_db_with_tenant
"""
import sys
import types
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─── Bootstrap: mock 所有外部依赖 ─────────────────────────────────────────────

# shared.ontology.src.database
_shared_pkg = types.ModuleType("shared")
_shared_onto = types.ModuleType("shared.ontology")
_shared_onto_src = types.ModuleType("shared.ontology.src")
_shared_onto_db = types.ModuleType("shared.ontology.src.database")

async def _fake_get_db_with_tenant(tenant_id: str):
    yield None

_shared_onto_db.get_db_with_tenant = _fake_get_db_with_tenant
sys.modules.setdefault("shared", _shared_pkg)
sys.modules.setdefault("shared.ontology", _shared_onto)
sys.modules.setdefault("shared.ontology.src", _shared_onto_src)
sys.modules.setdefault("shared.ontology.src.database", _shared_onto_db)

# structlog
_structlog = types.ModuleType("structlog")
class _FakeLogger:
    def info(self, *a, **kw): pass
    def error(self, *a, **kw): pass
    def warning(self, *a, **kw): pass
    def debug(self, *a, **kw): pass
_structlog.get_logger = lambda *a, **kw: _FakeLogger()
sys.modules.setdefault("structlog", _structlog)

# ─── 现在才能 import 被测模块 ──────────────────────────────────────────────────
from fastapi.testclient import TestClient
from fastapi import FastAPI

app = FastAPI()

# 延迟 import（依赖已 mock）
from api.agreement_unit_routes import router  # noqa: E402
app.include_router(router)

client = TestClient(app, raise_server_exceptions=False)

TENANT_ID = str(uuid.uuid4())
OPERATOR_ID = str(uuid.uuid4())
UNIT_ID = str(uuid.uuid4())
ACCOUNT_ID = str(uuid.uuid4())
TXN_ID = str(uuid.uuid4())

BASE_HEADERS = {
    "X-Tenant-ID": TENANT_ID,
    "X-Operator-ID": OPERATOR_ID,
}

NOW = datetime.now(timezone.utc)


# ─── 工具：构造 DB mock ───────────────────────────────────────────────────────

def _make_db_mock():
    """返回一个 AsyncMock，模拟 AsyncSession 的常见操作。"""
    db = AsyncMock()
    # 支持 async with db.begin() 上下文管理器
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=ctx)
    ctx.__aexit__ = AsyncMock(return_value=False)
    db.begin.return_value = ctx
    return db


def _make_mappings(rows: list[dict]):
    """将 dict 列表包装成 SQLAlchemy mappings 风格的 mock。"""
    result = MagicMock()
    result.mappings.return_value.all.return_value = [
        MagicMock(**{k: v for k, v in r.items()}, **{"__getitem__": lambda s, k: r[k]})
        for r in rows
    ]
    result.mappings.return_value.first.return_value = (
        MagicMock(**{k: v for k, v in rows[0].items()},
                  **{"__getitem__": lambda s, k: rows[0][k]})
        if rows else None
    )
    result.scalar.return_value = len(rows)
    return result


# ─── Test 1: 新建协议单位，授信额度正确存储 ───────────────────────────────────

def test_create_unit_with_credit_limit():
    """POST /api/v1/agreement-units — 创建协议单位，响应中包含正确 unit_id 和 status。"""
    created_unit_id = uuid.uuid4()
    created_at = NOW

    db = _make_db_mock()
    # 第一次 execute（INSERT unit）返回 id + created_at
    unit_row = MagicMock()
    unit_row.__getitem__ = lambda s, k: {
        "id": created_unit_id,
        "created_at": created_at,
    }[k]
    unit_result = MagicMock()
    unit_result.mappings.return_value.first.return_value = unit_row

    # 第二次 execute（INSERT account）无需返回值
    account_result = MagicMock()
    account_result.mappings.return_value.first.return_value = None

    db.execute = AsyncMock(side_effect=[unit_result, account_result])

    async def _fake_db_gen(_tid: str):
        yield db

    with patch("api.agreement_unit_routes.get_db_with_tenant", _fake_db_gen):
        resp = client.post(
            "/api/v1/agreement-units",
            json={
                "name": "测试企业A",
                "credit_limit_fen": 100_000_00,  # 10万元
                "settlement_cycle": "monthly",
                "settlement_day": 15,
            },
            headers=BASE_HEADERS,
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["name"] == "测试企业A"
    assert data["data"]["status"] == "active"
    # unit_id 应当是 UUID 字符串
    assert uuid.UUID(data["data"]["unit_id"])


# ─── Test 2: 挂账金额在授信内成功 ────────────────────────────────────────────

def test_charge_within_credit_limit():
    """POST /{unit_id}/charge — 挂账金额 ≤ 可用授信时返回 200 + txn_id。"""
    txn_at = NOW

    db = _make_db_mock()

    # 第一次 execute：查询单位 + 账户
    unit_fetch = MagicMock()
    unit_data = {
        "id": uuid.UUID(UNIT_ID),
        "name": "测试企业A",
        "credit_limit_fen": 100_000_00,
        "status": "active",
        "credit_used_fen": 20_000_00,
        "account_id": uuid.UUID(ACCOUNT_ID),
    }
    unit_row = MagicMock()
    unit_row.__getitem__ = lambda s, k: unit_data[k]
    unit_fetch.mappings.return_value.first.return_value = unit_row

    # 第二次 execute：INSERT transaction
    txn_result = MagicMock()
    txn_row = MagicMock()
    txn_row.__getitem__ = lambda s, k: {
        "id": uuid.UUID(TXN_ID),
        "created_at": txn_at,
    }[k]
    txn_result.mappings.return_value.first.return_value = txn_row

    # 第三次 execute：UPDATE agreement_accounts
    update_result = MagicMock()

    db.execute = AsyncMock(side_effect=[unit_fetch, txn_result, update_result])

    async def _fake_db_gen(_tid: str):
        yield db

    with patch("api.agreement_unit_routes.get_db_with_tenant", _fake_db_gen):
        resp = client.post(
            f"/api/v1/agreement-units/{UNIT_ID}/charge",
            json={
                "amount_fen": 5_000_00,   # 5千元，远小于可用额度 8万元
                "notes": "手动挂账测试",
                "print_voucher": False,
            },
            headers=BASE_HEADERS,
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["amount_fen"] == 5_000_00
    assert data["data"]["new_credit_used_fen"] == 25_000_00  # 20000 + 5000 分
    # available_credit_fen = 100000 - 25000 = 75000
    assert data["data"]["available_credit_fen"] == 75_000_00


# ─── Test 3: 超授信额度挂账被拒绝（返回400） ──────────────────────────────────

def test_charge_exceeds_credit_limit():
    """POST /{unit_id}/charge — 挂账金额 > 可用授信时返回 400。"""
    db = _make_db_mock()

    # 查询单位：已用 90_000_00，授信 100_000_00，可用仅 10_000_00
    unit_data = {
        "id": uuid.UUID(UNIT_ID),
        "name": "测试企业B",
        "credit_limit_fen": 100_000_00,
        "status": "active",
        "credit_used_fen": 90_000_00,
        "account_id": uuid.UUID(ACCOUNT_ID),
    }
    unit_fetch = MagicMock()
    unit_row = MagicMock()
    unit_row.__getitem__ = lambda s, k: unit_data[k]
    unit_fetch.mappings.return_value.first.return_value = unit_row

    db.execute = AsyncMock(return_value=unit_fetch)

    async def _fake_db_gen(_tid: str):
        yield db

    with patch("api.agreement_unit_routes.get_db_with_tenant", _fake_db_gen):
        resp = client.post(
            f"/api/v1/agreement-units/{UNIT_ID}/charge",
            json={
                "amount_fen": 20_000_00,   # 2万元，超出可用额度1万元
                "notes": "超限挂账测试",
            },
            headers=BASE_HEADERS,
        )

    assert resp.status_code == 400, f"期望400，实际: {resp.status_code}"
    detail = resp.json().get("detail", "")
    assert "超出授信额度" in detail or "credit" in detail.lower()


# ─── Test 4: 还款后余额正确减少 ──────────────────────────────────────────────

def test_repay_updates_balance():
    """POST /{unit_id}/repay — 普通还款后 new_credit_used_fen 减少正确金额。"""
    txn_at = NOW
    db = _make_db_mock()

    # 当前已用 30_000_00
    unit_data = {
        "id": uuid.UUID(UNIT_ID),
        "name": "测试企业A",
        "status": "active",
        "credit_used_fen": 30_000_00,
        "account_id": uuid.UUID(ACCOUNT_ID),
    }
    unit_fetch = MagicMock()
    unit_row = MagicMock()
    unit_row.__getitem__ = lambda s, k: unit_data[k]
    unit_fetch.mappings.return_value.first.return_value = unit_row

    # INSERT transaction
    txn_result = MagicMock()
    txn_row = MagicMock()
    txn_row.__getitem__ = lambda s, k: {
        "id": uuid.UUID(TXN_ID),
        "created_at": txn_at,
    }[k]
    txn_result.mappings.return_value.first.return_value = txn_row

    # UPDATE account
    update_result = MagicMock()

    db.execute = AsyncMock(side_effect=[unit_fetch, txn_result, update_result])

    async def _fake_db_gen(_tid: str):
        yield db

    with patch("api.agreement_unit_routes.get_db_with_tenant", _fake_db_gen):
        resp = client.post(
            f"/api/v1/agreement-units/{UNIT_ID}/repay",
            json={
                "repay_mode": "normal",
                "amount_fen": 10_000_00,    # 还1万
                "repay_method": "cash",
                "notes": "现金还款测试",
                "print_voucher": False,
            },
            headers=BASE_HEADERS,
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["pay_amount_fen"] == 10_000_00
    # 还款后已用 = 30000 - 10000 = 20000
    assert data["data"]["new_credit_used_fen"] == 20_000_00


# ─── Test 5: 账龄按天数分组正确 ──────────────────────────────────────────────

def test_aging_report_categorization():
    """GET /report/aging — 各区间金额分组正确，汇总和与各区间之和一致。"""
    now = datetime.now(timezone.utc)
    uid1 = str(uuid.uuid4())

    db = _make_db_mock()

    # 模拟账龄查询返回：一个单位有 4 个区间的欠款
    aging_row_data = {
        "unit_id": uuid.UUID(uid1),
        "unit_name": "测试企业A",
        "contact_name": "张经理",
        "total_owed_fen": 40_000_00,
        "aged_0_30_fen": 10_000_00,
        "aged_31_60_fen": 12_000_00,
        "aged_61_90_fen": 8_000_00,
        "aged_90plus_fen": 10_000_00,
    }
    aging_row = MagicMock()
    aging_row.__iter__ = lambda s: iter(aging_row_data.items())
    aging_row.items = lambda: aging_row_data.items()
    aging_row.keys = lambda: aging_row_data.keys()
    aging_row.values = lambda: aging_row_data.values()
    aging_row.__getitem__ = lambda s, k: aging_row_data[k]

    aging_result = MagicMock()
    aging_result.mappings.return_value.all.return_value = [aging_row]

    db.execute = AsyncMock(return_value=aging_result)

    async def _fake_db_gen(_tid: str):
        yield db

    with patch("api.agreement_unit_routes.get_db_with_tenant", _fake_db_gen):
        resp = client.get(
            "/api/v1/agreement-units/report/aging",
            headers=BASE_HEADERS,
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    items = data["data"]["items"]
    assert len(items) == 1

    item = items[0]
    # 验证各区间数据
    assert item["aged_0_30_fen"] == 10_000_00
    assert item["aged_31_60_fen"] == 12_000_00
    assert item["aged_61_90_fen"] == 8_000_00
    assert item["aged_90plus_fen"] == 10_000_00

    # 验证各区间之和 == total_owed_fen（本 mock 中完全一致）
    sum_parts = (
        item["aged_0_30_fen"]
        + item["aged_31_60_fen"]
        + item["aged_61_90_fen"]
        + item["aged_90plus_fen"]
    )
    assert sum_parts == item["total_owed_fen"], (
        f"各区间之和 {sum_parts} 不等于总欠款 {item['total_owed_fen']}"
    )
