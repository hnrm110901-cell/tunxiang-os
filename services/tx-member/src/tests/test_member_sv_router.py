"""储值卡新版路由测试 — stored_value_router.py（member 维度）

覆盖场景（共 10 个）：

1.  POST /api/v1/members/{member_id}/sv/charge          — 充值成功（含赠送规则匹配）
2.  POST /api/v1/members/{member_id}/sv/charge          — 卡未激活 → 400
3.  POST /api/v1/members/{member_id}/sv/consume         — 消费成功
4.  POST /api/v1/members/{member_id}/sv/consume         — 余额不足 → 400
5.  POST /api/v1/sv/transactions/{tx_id}/refund         — 退款成功
6.  POST /api/v1/sv/transactions/{tx_id}/refund         — 流水不存在 → 404
7.  GET  /api/v1/members/{member_id}/sv/balance         — 余额查询成功
8.  GET  /api/v1/members/{member_id}/sv/transactions    — 流水分页查询成功
9.  GET  /api/v1/sv/charge-rules                        — 充值赠送规则列表查询
10. POST /api/v1/sv/charge-rules                        — 创建充值赠送规则（bonus=0 → 400）
"""

import os
import sys
import types
import uuid
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

# ─── sys.path ──────────────────────────────────────────────────────────────────
_TESTS_DIR = os.path.dirname(__file__)
_SRC_DIR = os.path.abspath(os.path.join(_TESTS_DIR, ".."))
_ROOT_DIR = os.path.abspath(os.path.join(_TESTS_DIR, "..", "..", "..", ".."))

for _p in [_SRC_DIR, _ROOT_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ─── 包层级设置 ────────────────────────────────────────────────────────────────


def _ensure_pkg(name: str, path: str | None = None) -> types.ModuleType:
    if name not in sys.modules:
        mod = types.ModuleType(name)
        if path:
            mod.__path__ = [path]
        mod.__package__ = name
        sys.modules[name] = mod
    return sys.modules[name]


_ensure_pkg("src", _SRC_DIR)
_ensure_pkg("src.api", os.path.join(_SRC_DIR, "api"))


# ─── 真实 SQLAlchemy 模型存根（路由文件内部执行 select(StoredValueCard)） ────────

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import DeclarativeBase, mapped_column


class _TestBase(DeclarativeBase):
    pass


class _FakeStoredValueCard(_TestBase):
    """最小化 StoredValueCard 存根，让 select(StoredValueCard) 能构造 SQL。"""

    __tablename__ = "stored_value_cards"
    id = mapped_column(Integer, primary_key=True)
    tenant_id = mapped_column(Integer)
    customer_id = mapped_column(Integer)
    status = mapped_column(String)
    is_deleted = mapped_column(Boolean)
    created_at = mapped_column(Integer)


class _FakeStoredValueTransaction(_TestBase):
    """最小化 StoredValueTransaction 存根。"""

    __tablename__ = "stored_value_transactions"
    id = mapped_column(Integer, primary_key=True)
    tenant_id = mapped_column(Integer)
    txn_type = mapped_column(String)
    amount_fen = mapped_column(Integer)
    is_deleted = mapped_column(Boolean)


# 注入 models.stored_value
_sv_models_mod = types.ModuleType("models.stored_value")
_sv_models_mod.StoredValueCard = _FakeStoredValueCard
_sv_models_mod.StoredValueTransaction = _FakeStoredValueTransaction
_ensure_pkg("models")
sys.modules["models.stored_value"] = _sv_models_mod


# ─── 异常类定义（与 StoredValueService 使用的同名异常） ──────────────────────────


class CardNotActiveError(Exception):
    pass


class CardNotFoundError(Exception):
    pass


class InsufficientBalanceError(Exception):
    pass


# ─── StoredValueService 存根工厂 ───────────────────────────────────────────────


def _make_sv_svc_stub() -> MagicMock:
    svc = MagicMock()
    for method in (
        "create_card",
        "recharge_direct",
        "consume_by_id",
        "refund_by_transaction",
        "get_balance",
        "get_transactions_by_id",
        "exchange_points_for_balance",
    ):
        setattr(svc, method, AsyncMock(return_value={}))
    return svc


# ─── services.stored_value_service 存根注入 ────────────────────────────────────

_svc_mod = types.ModuleType("services.stored_value_service")
_svc_mod.StoredValueService = MagicMock(return_value=_make_sv_svc_stub())
_svc_mod.CardNotActiveError = CardNotActiveError
_svc_mod.CardNotFoundError = CardNotFoundError
_svc_mod.InsufficientBalanceError = InsufficientBalanceError
_ensure_pkg("services")
sys.modules["services.stored_value_service"] = _svc_mod


# ─── structlog 存根 ────────────────────────────────────────────────────────────

if "structlog" not in sys.modules:
    _structlog = types.ModuleType("structlog")
    _structlog.get_logger = MagicMock(return_value=MagicMock())
    sys.modules["structlog"] = _structlog


# ─── shared 存根注入 ───────────────────────────────────────────────────────────

_ensure_pkg("shared")
_ensure_pkg("shared.ontology")
_ensure_pkg("shared.ontology.src")

_db_mod = types.ModuleType("shared.ontology.src.database")


async def _fake_get_db_with_tenant(tenant_id):  # noqa: ARG001
    yield AsyncMock()


_db_mod.get_db_with_tenant = _fake_get_db_with_tenant
_db_mod.get_db = MagicMock()
sys.modules["shared.ontology.src.database"] = _db_mod


# ─── 导入被测路由模块 ───────────────────────────────────────────────────────────

import importlib  # noqa: E402

_router_mod = importlib.import_module("api.stored_value_router")
_svc_singleton: MagicMock = _router_mod._svc  # 路由文件模块级 _svc 单例


# ─── FastAPI 测试 app 构建 ─────────────────────────────────────────────────────


def _make_app(db_mock: AsyncMock) -> FastAPI:
    """构建含路由的 FastAPI app，并用 db_mock 覆盖 _get_tenant_db 依赖。"""
    app = FastAPI()
    app.include_router(_router_mod.router)

    async def _override():
        yield db_mock

    app.dependency_overrides[_router_mod._get_tenant_db] = _override
    return app


# ─── 常量 ──────────────────────────────────────────────────────────────────────

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
MEMBER_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
CARD_ID = uuid.uuid4()
TX_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
HEADERS = {"X-Tenant-ID": TENANT_ID}


def _uid() -> str:
    return str(uuid.uuid4())


def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    # 默认 execute 返回一个带 scalar_one_or_none() -> None 的 mock
    _result = MagicMock()
    _result.scalar_one_or_none.return_value = None
    _result.fetchone.return_value = None
    _result.fetchall.return_value = []
    db.execute = AsyncMock(return_value=_result)
    return db


# ──────────────────────────────────────────────────────────────────────────────
# 场景 1: POST /members/{member_id}/sv/charge — 充值成功（含 bonus）
# ──────────────────────────────────────────────────────────────────────────────


def test_charge_success_with_bonus():
    """充值成功：_svc.recharge_direct 返回余额，路由附加 bonus_fen 字段。"""
    db = _make_db()

    # 模拟找到已存在储值卡
    fake_card = MagicMock()
    fake_card.id = CARD_ID
    _card_result = MagicMock()
    _card_result.scalar_one_or_none.return_value = fake_card
    # 第一次 execute → 找卡；第二次 execute → 匹配赠送规则（返回 bonus_amount=200）
    _rule_result = MagicMock()
    _rule_result.fetchone.return_value = (200,)
    db.execute = AsyncMock(side_effect=[_card_result, _rule_result])

    recharge_data = {
        "balance_fen": 10200,
        "gift_balance_fen": 200,
        "card_id": str(CARD_ID),
    }
    _svc_singleton.recharge_direct = AsyncMock(return_value=recharge_data)

    app = _make_app(db)
    client = TestClient(app)
    resp = client.post(
        f"/api/v1/members/{MEMBER_ID}/sv/charge",
        json={"amount_fen": 10000},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["balance_fen"] == 10200
    assert body["data"]["bonus_fen"] == 200


# ──────────────────────────────────────────────────────────────────────────────
# 场景 2: POST /members/{member_id}/sv/charge — 卡未激活 → 400
# ──────────────────────────────────────────────────────────────────────────────


def test_charge_card_not_active():
    """recharge_direct 抛 CardNotActiveError 时路由返回 400。"""
    db = _make_db()

    fake_card = MagicMock()
    fake_card.id = CARD_ID
    _card_result = MagicMock()
    _card_result.scalar_one_or_none.return_value = fake_card
    _rule_result = MagicMock()
    _rule_result.fetchone.return_value = None  # 无赠送规则
    db.execute = AsyncMock(side_effect=[_card_result, _rule_result])

    _svc_singleton.recharge_direct = AsyncMock(side_effect=CardNotActiveError("储值卡已停用"))

    app = _make_app(db)
    client = TestClient(app)
    resp = client.post(
        f"/api/v1/members/{MEMBER_ID}/sv/charge",
        json={"amount_fen": 5000},
        headers=HEADERS,
    )

    assert resp.status_code == 400
    assert "储值卡已停用" in resp.json()["detail"]


# ──────────────────────────────────────────────────────────────────────────────
# 场景 3: POST /members/{member_id}/sv/consume — 消费成功
# ──────────────────────────────────────────────────────────────────────────────


def test_consume_success():
    """消费核销成功：返回 ok=True 及消费后余额。"""
    db = _make_db()
    consume_data = {
        "balance_fen": 7000,
        "deducted_fen": 3000,
        "card_id": str(CARD_ID),
    }
    _svc_singleton.consume_by_id = AsyncMock(return_value=consume_data)

    app = _make_app(db)
    client = TestClient(app)
    resp = client.post(
        f"/api/v1/members/{MEMBER_ID}/sv/consume",
        json={"card_id": str(CARD_ID), "amount_fen": 3000},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["deducted_fen"] == 3000
    assert body["data"]["balance_fen"] == 7000


# ──────────────────────────────────────────────────────────────────────────────
# 场景 4: POST /members/{member_id}/sv/consume — 余额不足 → 400
# ──────────────────────────────────────────────────────────────────────────────


def test_consume_insufficient_balance():
    """consume_by_id 抛 InsufficientBalanceError 时路由返回 400。"""
    db = _make_db()
    _svc_singleton.consume_by_id = AsyncMock(side_effect=InsufficientBalanceError("余额不足"))

    app = _make_app(db)
    client = TestClient(app)
    resp = client.post(
        f"/api/v1/members/{MEMBER_ID}/sv/consume",
        json={"card_id": str(CARD_ID), "amount_fen": 999999},
        headers=HEADERS,
    )

    assert resp.status_code == 400
    assert "余额不足" in resp.json()["detail"]


# ──────────────────────────────────────────────────────────────────────────────
# 场景 5: POST /sv/transactions/{tx_id}/refund — 退款成功
# ──────────────────────────────────────────────────────────────────────────────


def test_refund_success():
    """按消费流水退款成功，返回 ok=True。"""
    db = _make_db()

    # 模拟找到 consume 类型的流水
    fake_txn = MagicMock()
    fake_txn.txn_type = "consume"
    fake_txn.amount_fen = -5000  # 消费记为负数

    _txn_result = MagicMock()
    _txn_result.scalar_one_or_none.return_value = fake_txn
    db.execute = AsyncMock(return_value=_txn_result)

    refund_data = {"balance_fen": 15000, "refund_fen": 5000}
    _svc_singleton.refund_by_transaction = AsyncMock(return_value=refund_data)

    app = _make_app(db)
    client = TestClient(app)
    resp = client.post(
        f"/api/v1/sv/transactions/{TX_ID}/refund",
        json={},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["refund_fen"] == 5000


# ──────────────────────────────────────────────────────────────────────────────
# 场景 6: POST /sv/transactions/{tx_id}/refund — 流水不存在 → 404
# ──────────────────────────────────────────────────────────────────────────────


def test_refund_txn_not_found():
    """流水不存在时路由返回 404。"""
    db = _make_db()

    _txn_result = MagicMock()
    _txn_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=_txn_result)

    app = _make_app(db)
    client = TestClient(app)
    resp = client.post(
        f"/api/v1/sv/transactions/{TX_ID}/refund",
        json={},
        headers=HEADERS,
    )

    assert resp.status_code == 404
    assert "不存在" in resp.json()["detail"]


# ──────────────────────────────────────────────────────────────────────────────
# 场景 7: GET /members/{member_id}/sv/balance — 余额查询成功
# ──────────────────────────────────────────────────────────────────────────────


def test_get_balance_success():
    """余额查询成功：找到储值卡，返回 balance_fen 等字段。"""
    db = _make_db()

    fake_card = MagicMock()
    fake_card.id = CARD_ID
    _card_result = MagicMock()
    _card_result.scalar_one_or_none.return_value = fake_card
    db.execute = AsyncMock(return_value=_card_result)

    balance_data = {
        "balance_fen": 20000,
        "gift_balance_fen": 500,
        "card_id": str(CARD_ID),
        "status": "active",
    }
    _svc_singleton.get_balance = AsyncMock(return_value=balance_data)

    app = _make_app(db)
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/members/{MEMBER_ID}/sv/balance",
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["balance_fen"] == 20000
    assert body["data"]["gift_balance_fen"] == 500


# ──────────────────────────────────────────────────────────────────────────────
# 场景 8: GET /members/{member_id}/sv/transactions — 流水分页查询
# ──────────────────────────────────────────────────────────────────────────────


def test_get_transactions_success():
    """流水分页查询成功：返回 items 和 total 字段。"""
    db = _make_db()

    fake_card = MagicMock()
    fake_card.id = CARD_ID
    _card_result = MagicMock()
    _card_result.scalar_one_or_none.return_value = fake_card
    db.execute = AsyncMock(return_value=_card_result)

    txn_data = {
        "items": [
            {"id": _uid(), "txn_type": "charge", "amount_fen": 10000},
            {"id": _uid(), "txn_type": "consume", "amount_fen": -3000},
        ],
        "total": 2,
        "page": 1,
        "size": 20,
    }
    _svc_singleton.get_transactions_by_id = AsyncMock(return_value=txn_data)

    app = _make_app(db)
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/members/{MEMBER_ID}/sv/transactions",
        params={"page": 1, "size": 20},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 2
    assert len(body["data"]["items"]) == 2
    assert body["data"]["items"][0]["txn_type"] == "charge"


# ──────────────────────────────────────────────────────────────────────────────
# 场景 9: GET /sv/charge-rules — 充值赠送规则列表
# ──────────────────────────────────────────────────────────────────────────────


def test_list_charge_rules_success():
    """充值赠送规则列表查询：返回 ok=True 及规则数组。"""
    db = _make_db()

    # 模拟两条规则行
    _row1 = MagicMock()
    _row1._mapping = {
        "id": uuid.uuid4(),
        "store_id": None,
        "charge_amount": 10000,
        "bonus_amount": 500,
        "description": "满100送5",
        "is_active": True,
        "valid_from": None,
        "valid_to": None,
        "created_at": None,
    }
    _rows_result = MagicMock()
    _rows_result.fetchall.return_value = [_row1]
    db.execute = AsyncMock(return_value=_rows_result)

    app = _make_app(db)
    client = TestClient(app)
    resp = client.get(
        "/api/v1/sv/charge-rules",
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert isinstance(body["data"], list)
    assert len(body["data"]) == 1
    assert body["data"][0]["charge_amount"] == 10000


# ──────────────────────────────────────────────────────────────────────────────
# 场景 10: POST /sv/charge-rules — bonus_amount=0 → 400
# ──────────────────────────────────────────────────────────────────────────────


def test_create_charge_rule_bonus_zero():
    """bonus_amount=0 时路由应返回 400（赠送金额必须大于0）。"""
    db = _make_db()

    app = _make_app(db)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/sv/charge-rules",
        json={
            "charge_amount": 10000,
            "bonus_amount": 0,  # 违反业务规则
        },
        headers=HEADERS,
    )

    assert resp.status_code == 400
    assert "赠送金额" in resp.json()["detail"]
