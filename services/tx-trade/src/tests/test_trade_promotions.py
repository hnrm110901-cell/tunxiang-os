"""促销与储值路由测试 — discount_engine_routes + stored_value_routes

覆盖场景（共 10 个）：

discount_engine_routes.py（5个）
1. GET  /api/v1/discount/rules       — 正常返回规则列表
2. GET  /api/v1/discount/rules       — 缺少 X-Tenant-ID → 400
3. POST /api/v1/discount/calculate   — 单折扣（会员85折）正常叠加
4. POST /api/v1/discount/calculate   — 无效 discount type → 400
5. POST /api/v1/discount/rules       — 创建折扣规则成功

stored_value_routes.py（5个）
6. GET  /api/v1/members/{id}/stored-value     — 返回余额与流水
7. POST /api/v1/members/{id}/stored-value/recharge  — 充值：100000分 → 赠15000分
8. POST /api/v1/members/{id}/stored-value/recharge  — 金额<100分 → 422
9. POST /api/v1/members/{id}/stored-value/consume   — 余额充足，扣款成功
10. POST /api/v1/members/{id}/stored-value/consume  — 余额不足，返回 success=False
"""
from __future__ import annotations

import os
import sys
import types
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ─── sys.path 设置 ─────────────────────────────────────────────────────────────

_TESTS_DIR = os.path.dirname(__file__)
_SRC_DIR   = os.path.abspath(os.path.join(_TESTS_DIR, ".."))
_ROOT_DIR  = os.path.abspath(os.path.join(_TESTS_DIR, "..", "..", "..", ".."))

for _p in [_SRC_DIR, _ROOT_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ─── 注入 shared.ontology.src.database 存根（如尚未真实导入）────────────────────

def _ensure_stub(mod_name: str) -> None:
    if mod_name not in sys.modules:
        stub = types.ModuleType(mod_name)
        sys.modules[mod_name] = stub


_ensure_stub("shared")
_ensure_stub("shared.ontology")
_ensure_stub("shared.ontology.src")
_ensure_stub("shared.ontology.src.database")

# get_db 占位符（真实对象由 dependency_overrides 替换）
_db_stub = sys.modules["shared.ontology.src.database"]
if not hasattr(_db_stub, "get_db"):
    async def _get_db_stub():  # pragma: no cover
        yield None
    _db_stub.get_db = _get_db_stub

from shared.ontology.src.database import get_db  # noqa: E402

# ─── 导入被测路由（保证 shared 存根已注册）──────────────────────────────────────

from api.discount_engine_routes import router as discount_router  # type: ignore[import]
from api.stored_value_routes import router as stored_value_router  # type: ignore[import]

# ─── 常量 ──────────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
MEMBER_ID = str(uuid.uuid4())
STORE_ID  = str(uuid.uuid4())
HEADERS   = {"X-Tenant-ID": TENANT_ID}


# ─── DB Mock 工厂 ───────────────────────────────────────────────────────────────

class _FakeMappingsResult:
    """模拟 result.mappings().all() / .first() / 直接迭代 的返回"""

    def __init__(self, rows: list[dict] | None = None):
        self._rows = rows or []

    def mappings(self) -> "_FakeMappingsResult":
        return self

    def all(self) -> list[dict]:
        return self._rows

    def first(self) -> dict | None:
        return self._rows[0] if self._rows else None

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


def _make_db(execute_side_effect=None) -> AsyncMock:
    """返回一个可配置 execute side_effect 的 DB AsyncMock"""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=execute_side_effect)
    db.commit  = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _make_app_discount(db_mock) -> TestClient:
    app = FastAPI()
    app.include_router(discount_router)
    app.dependency_overrides[get_db] = lambda: db_mock
    return TestClient(app)


def _make_app_stored_value(db_mock) -> TestClient:
    app = FastAPI()
    app.include_router(stored_value_router)
    app.dependency_overrides[get_db] = lambda: db_mock
    return TestClient(app)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# discount_engine_routes — 5 个测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 场景 1: GET /api/v1/discount/rules — 正常返回规则列表 ─────────────────────────

def test_get_discount_rules_ok():
    """查询激活规则：返回 ok=True，data.rules 为列表"""
    rule_row = {
        "id": uuid.uuid4(),
        "store_id": None,
        "name": "会员折扣规则",
        "priority": 10,
        "type": "member_discount",
        "can_stack_with": ["full_reduction"],
        "apply_order": 1,
        "is_active": True,
        "description": "会员85折",
    }
    # _fetch_active_rules 调用两次 execute：SET CONFIG + SELECT
    execute_results = [
        _FakeMappingsResult(),         # SET CONFIG 无需返回行
        _FakeMappingsResult([rule_row]),
    ]
    call_idx = {"i": 0}

    async def _side(stmt, params=None):
        res = execute_results[call_idx["i"]]
        call_idx["i"] += 1
        return res

    db = _make_db(execute_side_effect=_side)
    client = _make_app_discount(db)

    resp = client.get("/api/v1/discount/rules", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "rules" in body["data"]
    assert body["data"]["total"] == 1
    assert body["data"]["rules"][0]["name"] == "会员折扣规则"


# 场景 2: GET /api/v1/discount/rules — 缺少 X-Tenant-ID → 400 ──────────────────

def test_get_discount_rules_missing_tenant():
    """不提供 X-Tenant-ID 时返回 400"""
    db = _make_db()
    client = _make_app_discount(db)

    resp = client.get("/api/v1/discount/rules")
    assert resp.status_code == 400


# 场景 3: POST /api/v1/discount/calculate — 单折扣（会员85折）正常计算 ──────────

def test_calculate_member_discount_ok():
    """会员85折：10000分 × 0.85 = 8500分，节省1500分"""
    # _fetch_active_rules: SET CONFIG + SELECT（返回会员规则）
    rule_row = {
        "id": uuid.uuid4(),
        "store_id": None,
        "name": "会员折扣",
        "priority": 10,
        "type": "member_discount",
        "can_stack_with": [],
        "apply_order": 1,
        "is_active": True,
        "description": "会员85折",
    }
    # INSERT discount_log + commit
    log_insert_result = _FakeMappingsResult()

    call_results = [
        _FakeMappingsResult(),          # SET CONFIG (fetch_active_rules)
        _FakeMappingsResult([rule_row]),# SELECT discount_rules
        _FakeMappingsResult(),          # SET CONFIG (insert_log 内部的 set_config — 此处路由不调用)
        log_insert_result,              # INSERT checkout_discount_log
    ]
    call_idx = {"i": 0}

    async def _side(stmt, params=None):
        idx = min(call_idx["i"], len(call_results) - 1)
        res = call_results[idx]
        call_idx["i"] += 1
        return res

    db = _make_db(execute_side_effect=_side)
    client = _make_app_discount(db)

    resp = client.post(
        "/api/v1/discount/calculate",
        json={
            "order_id": str(uuid.uuid4()),
            "base_amount_fen": 10000,
            "discounts": [
                {"type": "member_discount", "member_id": "mem-001", "rate": 0.85},
            ],
            "store_id": STORE_ID,
        },
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["base_amount_fen"] == 10000
    assert data["final_amount_fen"] == 8500
    assert data["total_saved_fen"] == 1500
    assert len(data["applied_steps"]) == 1


# 场景 4: POST /api/v1/discount/calculate — 无效 discount type → 400 ─────────────

def test_calculate_invalid_discount_type():
    """传入不合法的 discount type 时应立即返回 400"""
    db = _make_db()
    client = _make_app_discount(db)

    resp = client.post(
        "/api/v1/discount/calculate",
        json={
            "order_id": str(uuid.uuid4()),
            "base_amount_fen": 5000,
            "discounts": [{"type": "fake_discount_xyz", "deduct_fen": 100}],
        },
        headers=HEADERS,
    )
    assert resp.status_code == 400


# 场景 5: POST /api/v1/discount/rules — 创建折扣规则成功 ─────────────────────────

def test_create_discount_rule_ok():
    """新建折扣规则，DB INSERT 成功后返回 rule_id"""
    # execute 顺序: SET CONFIG → INSERT
    call_idx = {"i": 0}
    results = [_FakeMappingsResult(), _FakeMappingsResult()]

    async def _side(stmt, params=None):
        idx = min(call_idx["i"], len(results) - 1)
        res = results[idx]
        call_idx["i"] += 1
        return res

    db = _make_db(execute_side_effect=_side)
    client = _make_app_discount(db)

    resp = client.post(
        "/api/v1/discount/rules",
        json={
            "name": "满100减20",
            "priority": 50,
            "type": "full_reduction",
            "can_stack_with": ["member_discount"],
            "apply_order": 2,
            "description": "满100元减20元",
        },
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "rule_id" in body["data"]
    assert body["data"]["message"] == "规则创建成功"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# stored_value_routes — 5 个测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 场景 6: GET /api/v1/members/{id}/stored-value — 返回余额与流水 ────────────────

def test_get_stored_value_ok():
    """返回账户余额 + 最近20条流水"""
    account_id = str(uuid.uuid4())
    account_row = {
        "id": account_id,
        "balance_fen": 50000,
        "frozen_fen": 0,
        "total_recharged_fen": 50000,
        "total_consumed_fen": 0,
    }
    txn_rows: list[dict] = []

    call_idx = {"i": 0}
    # execute: SET LOCAL → SELECT account → (commit) → SELECT transactions
    results_seq = [
        _FakeMappingsResult(),                # SET LOCAL
        _FakeMappingsResult([account_row]),   # SELECT stored_value_accounts
        _FakeMappingsResult(txn_rows),        # SELECT stored_value_transactions
    ]

    async def _side(stmt, params=None):
        idx = min(call_idx["i"], len(results_seq) - 1)
        res = results_seq[idx]
        call_idx["i"] += 1
        return res

    db = _make_db(execute_side_effect=_side)
    client = _make_app_stored_value(db)

    resp = client.get(
        f"/api/v1/members/{MEMBER_ID}/stored-value",
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["balance_fen"] == 50000
    assert data["member_id"] == MEMBER_ID
    assert isinstance(data["transactions"], list)


# 场景 7: POST recharge — 充100000分，档位赠15000分 ─────────────────────────────

def test_recharge_with_bonus():
    """充100000分（≥100000分档），应赠15000分，total_credited=115000"""
    account_id = str(uuid.uuid4())
    account_row = {
        "id": account_id,
        "balance_fen": 0,
        "frozen_fen": 0,
        "total_recharged_fen": 0,
        "total_consumed_fen": 0,
    }

    call_idx = {"i": 0}
    results_seq = [
        _FakeMappingsResult(),              # SET LOCAL
        _FakeMappingsResult([account_row]), # SELECT account
        _FakeMappingsResult(),              # UPDATE balance
        _FakeMappingsResult(),              # INSERT transaction
    ]

    async def _side(stmt, params=None):
        idx = min(call_idx["i"], len(results_seq) - 1)
        res = results_seq[idx]
        call_idx["i"] += 1
        return res

    db = _make_db(execute_side_effect=_side)
    client = _make_app_stored_value(db)

    resp = client.post(
        f"/api/v1/members/{MEMBER_ID}/stored-value/recharge",
        json={
            "amount_fen": 100_000,
            "payment_method": "wechat",
            "operator_id": "op-001",
        },
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["amount_fen"] == 100_000
    assert data["bonus_fen"] == 15_000
    assert data["total_credited_fen"] == 115_000
    assert data["balance_after_fen"] == 115_000


# 场景 8: POST recharge — 金额 < 100分 → 422 ────────────────────────────────────

def test_recharge_amount_too_small():
    """充值金额低于100分应被 Pydantic validator 拒绝，返回 422"""
    db = _make_db()
    client = _make_app_stored_value(db)

    resp = client.post(
        f"/api/v1/members/{MEMBER_ID}/stored-value/recharge",
        json={
            "amount_fen": 50,
            "payment_method": "cash",
            "operator_id": "op-001",
        },
        headers=HEADERS,
    )
    assert resp.status_code == 422


# 场景 9: POST consume — 余额充足，扣款成功 ──────────────────────────────────────

def test_consume_sufficient_balance():
    """账户余额20000分，消费8800分，应成功并返回 balance_after=11200"""
    account_id = str(uuid.uuid4())
    account_row = {
        "id": account_id,
        "balance_fen": 20_000,
        "frozen_fen": 0,
        "total_recharged_fen": 20_000,
        "total_consumed_fen": 0,
    }

    call_idx = {"i": 0}
    results_seq = [
        _FakeMappingsResult(),              # SET LOCAL
        _FakeMappingsResult([account_row]), # SELECT account
        _FakeMappingsResult(),              # UPDATE balance
        _FakeMappingsResult(),              # INSERT transaction
    ]

    async def _side(stmt, params=None):
        idx = min(call_idx["i"], len(results_seq) - 1)
        res = results_seq[idx]
        call_idx["i"] += 1
        return res

    db = _make_db(execute_side_effect=_side)
    client = _make_app_stored_value(db)

    resp = client.post(
        f"/api/v1/members/{MEMBER_ID}/stored-value/consume",
        json={
            "amount_fen": 8_800,
            "order_id": str(uuid.uuid4()),
            "operator_id": "op-002",
        },
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["success"] is True
    assert data["balance_after_fen"] == 11_200
    assert data["insufficient_fen"] == 0


# 场景 10: POST consume — 余额不足，返回 success=False ───────────────────────────

def test_consume_insufficient_balance():
    """账户余额1000分，尝试消费5000分，返回 success=False 和 insufficient_fen=4000"""
    account_id = str(uuid.uuid4())
    account_row = {
        "id": account_id,
        "balance_fen": 1_000,
        "frozen_fen": 0,
        "total_recharged_fen": 1_000,
        "total_consumed_fen": 0,
    }

    call_idx = {"i": 0}
    results_seq = [
        _FakeMappingsResult(),              # SET LOCAL
        _FakeMappingsResult([account_row]), # SELECT account
    ]

    async def _side(stmt, params=None):
        idx = min(call_idx["i"], len(results_seq) - 1)
        res = results_seq[idx]
        call_idx["i"] += 1
        return res

    db = _make_db(execute_side_effect=_side)
    client = _make_app_stored_value(db)

    resp = client.post(
        f"/api/v1/members/{MEMBER_ID}/stored-value/consume",
        json={
            "amount_fen": 5_000,
            "order_id": str(uuid.uuid4()),
            "operator_id": "op-003",
        },
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["success"] is False
    assert data["insufficient_fen"] == 4_000
    assert data["balance_after_fen"] == 1_000
