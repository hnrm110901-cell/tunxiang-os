"""储值核心路由测试 — stored_value_routes.py + stored_value_card_routes.py

覆盖场景（共10个）：

stored_value_routes.py (22 端点，选5个代表性场景):
1.  GET  /api/v1/member/stored-value/accounts/{card_id}/balance  — 正常查询余额
2.  GET  /api/v1/member/stored-value/accounts/{card_id}/balance  — 卡不存在 → 404
3.  POST /api/v1/member/stored-value/accounts/{card_id}/recharge — 正常充值
4.  POST /api/v1/member/stored-value/accounts/{card_id}/recharge — DB 错误 → 500
5.  POST /api/v1/member/stored-value/cards                       — 缺少必填字段 → 422

stored_value_card_routes.py (9 端点，选5个代表性场景):
6.  POST /stored-value-cards                                     — 正常开卡（无初始充值）
7.  GET  /stored-value-cards/{card_id}                           — 正常卡详情
8.  GET  /stored-value-cards/{card_id}                           — 卡不存在 → 404
9.  POST /stored-value-cards/{card_id}/consume                   — 余额不足 → 400
10. POST /stored-value-cards/{card_id}/recharge                  — 缺少 X-Tenant-ID → 422
"""
import os
import sys
import types
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

# ─── sys.path ───────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ─── 共享存根：在导入路由前注入 ──────────────────────────────────────────────

def _inject_stubs():
    """向 sys.modules 注入所有相对导入所需的存根模块。"""

    # shared.events.src.emitter
    emitter_mod = types.ModuleType("shared.events.src.emitter")
    emitter_mod.emit_event = AsyncMock(return_value=None)
    sys.modules.setdefault("shared", types.ModuleType("shared"))
    sys.modules.setdefault("shared.events", types.ModuleType("shared.events"))
    sys.modules.setdefault("shared.events.src", types.ModuleType("shared.events.src"))
    sys.modules["shared.events.src.emitter"] = emitter_mod

    # shared.events.src.event_types
    event_types_mod = types.ModuleType("shared.events.src.event_types")
    for name in ("MemberEventType", "SettlementEventType", "OrderEventType"):
        cls = MagicMock()
        cls.RECHARGED = "MEMBER.RECHARGED"
        cls.CONSUMED = "MEMBER.CONSUMED"
        cls.STORED_VALUE_DEFERRED = "SETTLEMENT.STORED_VALUE_DEFERRED"
        cls.ADVANCE_CONSUMED = "SETTLEMENT.ADVANCE_CONSUMED"
        setattr(event_types_mod, name, cls)
    sys.modules["shared.events.src.event_types"] = event_types_mod

    # shared.ontology.src.database — get_db_with_tenant + get_db
    db_mod = types.ModuleType("shared.ontology.src.database")

    async def _fake_get_db_with_tenant(tenant_id):  # noqa: ARG001
        yield AsyncMock()

    db_mod.get_db_with_tenant = _fake_get_db_with_tenant
    db_mod.get_db = MagicMock()
    sys.modules.setdefault("shared.ontology", types.ModuleType("shared.ontology"))
    sys.modules.setdefault("shared.ontology.src", types.ModuleType("shared.ontology.src"))
    sys.modules["shared.ontology.src.database"] = db_mod

    # structlog（card_routes 用到）
    structlog_mod = types.ModuleType("structlog")
    structlog_mod.get_logger = MagicMock(return_value=MagicMock())
    sys.modules.setdefault("structlog", structlog_mod)


_inject_stubs()


# ─── 存根 StoredValueService（两个路由文件共用同一服务类） ───────────────────

_MOCK_SVC = MagicMock()


def _make_sv_svc_stub():
    svc = MagicMock()
    # 默认所有异步方法返回空 dict
    for method in (
        "get_balance", "recharge_direct", "consume_by_id", "refund_direct",
        "transfer", "get_transactions_by_id", "process_expiry_batch",
        "create_card", "get_card_by_id", "recharge_by_plan",
        "refund_by_transaction", "get_card", "recharge", "consume",
        "refund", "freeze", "unfreeze", "freeze_by_id", "unfreeze_by_id",
        "list_cards_by_customer", "list_recharge_plans", "create_recharge_plan",
    ):
        setattr(svc, method, AsyncMock(return_value={}))
    return svc


# ─── 注入 services.stored_value_service 存根 ────────────────────────────────
#    stored_value_card_routes 用裸的 `services.stored_value_service`（非相对导入）

class CardNotActiveError(Exception):
    pass

class InsufficientBalanceError(Exception):
    pass

class PlanNotFoundError(Exception):
    pass

class TransferNotAllowedError(Exception):
    pass


_svc_module = types.ModuleType("services.stored_value_service")
_svc_module.StoredValueService = MagicMock(return_value=_make_sv_svc_stub())
_svc_module.CardNotActiveError = CardNotActiveError
_svc_module.InsufficientBalanceError = InsufficientBalanceError
_svc_module.PlanNotFoundError = PlanNotFoundError
_svc_module.TransferNotAllowedError = TransferNotAllowedError

sys.modules.setdefault("services", types.ModuleType("services"))
sys.modules["services.stored_value_service"] = _svc_module

# ─── 注入 ..services.stored_value_service（相对导入路径，for stored_value_routes） ─

_rel_svc_module = types.ModuleType("api.services.stored_value_service")
_rel_svc_module.StoredValueService = MagicMock(return_value=_make_sv_svc_stub())
_rel_svc_module.CardNotActiveError = CardNotActiveError
_rel_svc_module.InsufficientBalanceError = InsufficientBalanceError
_rel_svc_module.PlanNotFoundError = PlanNotFoundError
_rel_svc_module.TransferNotAllowedError = TransferNotAllowedError
sys.modules["api.services"] = types.ModuleType("api.services")
sys.modules["api.services.stored_value_service"] = _rel_svc_module

# 让 ..services.stored_value_service 也能以 src.services 前缀找到
sys.modules.setdefault("src", types.ModuleType("src"))
sys.modules.setdefault("src.services", types.ModuleType("src.services"))
_src_svc = types.ModuleType("src.services.stored_value_service")
_src_svc.StoredValueService = MagicMock(return_value=_make_sv_svc_stub())
_src_svc.CardNotActiveError = CardNotActiveError
_src_svc.InsufficientBalanceError = InsufficientBalanceError
_src_svc.PlanNotFoundError = PlanNotFoundError
_src_svc.TransferNotAllowedError = TransferNotAllowedError
sys.modules["src.services.stored_value_service"] = _src_svc


# ─── 辅助 ───────────────────────────────────────────────────────────────────

def _uid() -> str:
    return str(uuid.uuid4())


TENANT_ID = _uid()
CARD_ID = uuid.uuid4()
HEADERS = {"X-Tenant-ID": TENANT_ID}


# ─── 加载被测路由 ─────────────────────────────────────────────────────────────
#   两个路由分别挂到独立 app，避免前缀冲突。

import importlib  # noqa: E402

# --- stored_value_routes ---
sv_routes_mod = importlib.import_module("api.stored_value_routes")
sv_svc: MagicMock = sv_routes_mod.svc          # 路由文件中模块级单例

sv_app = FastAPI()
sv_app.include_router(sv_routes_mod.router)


def _sv_db_override(db_mock):
    """替换 _get_tenant_db 依赖。"""
    async def _dep():
        return db_mock
    sv_app.dependency_overrides[sv_routes_mod._get_tenant_db] = _dep


# --- stored_value_card_routes ---
svc_routes_mod = importlib.import_module("api.stored_value_card_routes")
svc_svc: MagicMock = svc_routes_mod._svc       # 路由文件中模块级单例

svc_app = FastAPI()
svc_app.include_router(svc_routes_mod.router)


def _svc_db_override(db_mock):
    async def _dep():
        return db_mock
    svc_app.dependency_overrides[svc_routes_mod._get_tenant_db] = _dep


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ★ stored_value_routes.py — 5个测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# ── 场景 1: GET /accounts/{card_id}/balance — 正常查询 ─────────────────────

def test_sv_account_balance_ok():
    """账户余额查询成功，返回 ok=True 及余额字段。"""
    db = AsyncMock()
    balance_data = {
        "balance_fen": 80000,
        "gift_balance_fen": 2000,
        "card_id": str(CARD_ID),
        "status": "active",
    }
    sv_svc.get_balance = AsyncMock(return_value=balance_data)
    _sv_db_override(db)

    client = TestClient(sv_app)
    resp = client.get(
        f"/api/v1/member/stored-value/accounts/{CARD_ID}/balance",
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["balance_fen"] == 80000
    assert body["data"]["gift_balance_fen"] == 2000


# ── 场景 2: GET /accounts/{card_id}/balance — 卡不存在 → 404 ───────────────

def test_sv_account_balance_not_found():
    """get_balance 抛 ValueError（卡不存在）时应返回 404。"""
    db = AsyncMock()
    sv_svc.get_balance = AsyncMock(side_effect=ValueError("储值卡不存在"))
    _sv_db_override(db)

    client = TestClient(sv_app)
    resp = client.get(
        f"/api/v1/member/stored-value/accounts/{CARD_ID}/balance",
        headers=HEADERS,
    )

    assert resp.status_code == 404
    assert "储值卡不存在" in resp.json()["detail"]


# ── 场景 3: POST /accounts/{card_id}/recharge — 正常充值 ───────────────────

def test_sv_account_recharge_ok(monkeypatch):
    """充值成功时返回 ok=True 及新余额。"""
    db = AsyncMock()
    recharge_result = {
        "balance_fen": 150000,
        "gift_balance_fen": 5000,
        "customer_id": _uid(),
    }
    sv_svc.recharge_direct = AsyncMock(return_value=recharge_result)

    # asyncio.create_task 在 TestClient（同步）环境下不能真正调度，patch 掉
    monkeypatch.setattr("api.stored_value_routes.asyncio.create_task", lambda coro: None)
    _sv_db_override(db)

    client = TestClient(sv_app)
    resp = client.post(
        f"/api/v1/member/stored-value/accounts/{CARD_ID}/recharge",
        json={"amount_fen": 50000, "gift_amount_fen": 5000},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["balance_fen"] == 150000


# ── 场景 4: POST /accounts/{card_id}/recharge — DB 错误 → 500 ──────────────

def test_sv_account_recharge_db_error(monkeypatch):
    """数据库 OperationalError 未被业务层捕获时，FastAPI 应返回 500。"""
    db = AsyncMock()
    sv_svc.recharge_direct = AsyncMock(
        side_effect=OperationalError("connection lost", None, None)
    )
    monkeypatch.setattr("api.stored_value_routes.asyncio.create_task", lambda coro: None)
    _sv_db_override(db)

    client = TestClient(sv_app, raise_server_exceptions=False)
    resp = client.post(
        f"/api/v1/member/stored-value/accounts/{CARD_ID}/recharge",
        json={"amount_fen": 10000},
        headers=HEADERS,
    )

    assert resp.status_code == 500


# ── 场景 5: POST /cards — 缺少必填字段 → 422 ──────────────────────────────

def test_sv_create_card_missing_field():
    """POST /cards 缺少 customer_id（必填）时，Pydantic 校验失败返回 422。"""
    client = TestClient(sv_app)
    resp = client.post(
        "/api/v1/member/stored-value/cards",
        json={"scope_type": "brand"},   # 缺少 customer_id
        headers=HEADERS,
    )

    assert resp.status_code == 422
    errors = resp.json()["detail"]
    fields = [e["loc"][-1] for e in errors]
    assert "customer_id" in fields


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ★ stored_value_card_routes.py — 5个测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# ── 场景 6: POST /stored-value-cards — 正常开卡（无初始充值） ─────────────────

def test_svc_create_card_ok():
    """正常开卡（initial_amount_fen=0）返回 ok=True 和卡 ID。"""
    db = AsyncMock()
    card_id = _uid()
    card_data = {"id": card_id, "status": "active", "balance_fen": 0}
    svc_svc.create_card = AsyncMock(return_value=card_data)
    _svc_db_override(db)

    client = TestClient(svc_app)
    resp = client.post(
        "/stored-value-cards",
        json={"customer_id": _uid()},
        headers=HEADERS,
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["id"] == card_id


# ── 场景 7: GET /stored-value-cards/{card_id} — 正常卡详情 ──────────────────

def test_svc_get_card_ok():
    """按 card_id 查询储值卡详情，返回 ok=True 及余额。"""
    db = AsyncMock()
    card_data = {
        "id": str(CARD_ID),
        "status": "active",
        "balance_fen": 30000,
        "gift_balance_fen": 0,
    }
    svc_svc.get_card_by_id = AsyncMock(return_value=card_data)
    _svc_db_override(db)

    client = TestClient(svc_app)
    resp = client.get(
        f"/stored-value-cards/{CARD_ID}",
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["balance_fen"] == 30000


# ── 场景 8: GET /stored-value-cards/{card_id} — 卡不存在 → 404 ─────────────

def test_svc_get_card_not_found():
    """get_card_by_id 返回 None 时路由应返回 404。"""
    db = AsyncMock()
    svc_svc.get_card_by_id = AsyncMock(return_value=None)
    _svc_db_override(db)

    client = TestClient(svc_app)
    missing_id = uuid.uuid4()
    resp = client.get(
        f"/stored-value-cards/{missing_id}",
        headers=HEADERS,
    )

    assert resp.status_code == 404
    assert "储值卡不存在" in resp.json()["detail"]


# ── 场景 9: POST /{card_id}/consume — 余额不足 → 400 ──────────────────────

def test_svc_consume_insufficient_balance():
    """consume_by_id 抛 InsufficientBalanceError 时路由应返回 400。"""
    db = AsyncMock()
    svc_svc.consume_by_id = AsyncMock(
        side_effect=svc_routes_mod.InsufficientBalanceError("余额不足")
    )
    _svc_db_override(db)

    client = TestClient(svc_app)
    resp = client.post(
        f"/stored-value-cards/{CARD_ID}/consume",
        json={"amount_fen": 999999},
        headers=HEADERS,
    )

    assert resp.status_code == 400
    assert "余额不足" in resp.json()["detail"]


# ── 场景 10: POST /{card_id}/recharge — 缺少 X-Tenant-ID → 422 ─────────────

def test_svc_recharge_missing_tenant_header():
    """POST recharge 未传 X-Tenant-ID 时，FastAPI 依赖校验返回 422。"""
    # 不传 X-Tenant-ID
    client = TestClient(svc_app)
    resp = client.post(
        f"/stored-value-cards/{CARD_ID}/recharge",
        json={"amount_fen": 10000},
        # headers 故意不传
    )

    assert resp.status_code == 422
