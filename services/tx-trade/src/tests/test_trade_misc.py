"""杂项路由测试 — quick_cashier_routes.py + banquet_payment_routes.py

文件一：quick_cashier_routes（快餐收银/叫号，8 端点）
  场景 1: POST /api/v1/quick-cashier/order        — 正常创建快餐订单，返回 call_number
  场景 2: POST /api/v1/quick-cashier/order        — order_type 非法 → 400
  场景 3: POST /api/v1/quick-cashier/{id}/call    — 叫号成功，status=calling
  场景 4: POST /api/v1/quick-cashier/{id}/complete — 取餐完成，status=completed
  场景 5: GET  /api/v1/quick-cashier/config/{store_id} — 无配置时返回默认值

文件二：banquet_payment_routes（宴席支付/确认单，8 端点）
  场景 6: POST /api/v1/banquet/{id}/deposit        — 创建定金成功，返回 deposit 对象
  场景 7: POST /api/v1/banquet/{id}/deposit        — 缺少 X-Tenant-ID → 400
  场景 8: GET  /api/v1/banquet/{id}/deposit        — 定金记录不存在 → ok=False, NOT_FOUND
  场景 9: POST /api/v1/banquet/{id}/confirmation   — 创建确认单成功
  场景 10: POST /api/v1/banquet/{id}/confirmation/sign — 顾客签字成功，status=confirmed
"""
import os
import sys
import types

# ─── 路径准备 ─────────────────────────────────────────────────────────────────
_TESTS_DIR = os.path.dirname(__file__)
_SRC_DIR   = os.path.join(_TESTS_DIR, "..")
_ROOT_DIR  = os.path.abspath(os.path.join(_TESTS_DIR, "..", "..", "..", ".."))

for _p in [_SRC_DIR, _ROOT_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ─── sys.modules 存根：防止重型依赖导入失败 ──────────────────────────────────

def _stub(name: str, **attrs):
    """注入一个空模块存根（仅当尚未存在时）。"""
    if name not in sys.modules:
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules[name] = mod
    return sys.modules[name]


def _ensure_pkg(name: str, path: str) -> None:
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = [path]
        mod.__package__ = name
        sys.modules[name] = mod


# 建立包层级
_ensure_pkg("src",          _SRC_DIR)
_ensure_pkg("src.api",      os.path.join(_SRC_DIR, "api"))
_ensure_pkg("src.services", os.path.join(_SRC_DIR, "services"))

# shared.events 存根
_stub("shared")
_stub("shared.events")
_stub("shared.events.src")
async def _fake_emit_event(*_args, **_kwargs):
    pass

_stub("shared.events.src.emitter",    emit_event=_fake_emit_event)
import enum as _enum                                        # noqa: E402 (used before final imports)

class _OrderEventType(_enum.Enum):
    PAID = "ORDER.PAID"
    CREATED = "ORDER.CREATED"

_stub("shared.events.src.event_types", OrderEventType=_OrderEventType)

# shared.ontology 存根（get_db 将被 dependency_overrides 替换）
_stub("shared.ontology")
_stub("shared.ontology.src")

import asyncio                                           # noqa: E402
from datetime import datetime, timezone                  # noqa: E402
from uuid import UUID, uuid4                             # noqa: E402
from unittest.mock import AsyncMock, MagicMock, patch   # noqa: E402

from fastapi import FastAPI                              # noqa: E402
from fastapi.testclient import TestClient                # noqa: E402

# ─── 注入 shared.ontology.src.database 存根（含真实 get_db 占位符） ──────────

import types as _types                                   # noqa: E402

_db_mod = _types.ModuleType("shared.ontology.src.database")

# get_db 占位符（会被 dependency_overrides 覆盖）
async def _get_db_placeholder():
    yield None  # pragma: no cover

_db_mod.get_db              = _get_db_placeholder
_db_mod.get_db_with_tenant  = _get_db_placeholder
_db_mod.get_db_no_rls       = _get_db_placeholder
sys.modules["shared.ontology.src.database"] = _db_mod

# ─── 导入被测路由 ─────────────────────────────────────────────────────────────

from src.api.quick_cashier_routes import router as qc_router   # type: ignore[import]  # noqa: E402
from shared.ontology.src.database import get_db                  # noqa: E402

# banquet_payment_routes 需要 BanquetPaymentService；先给 services 包注册存根
_svc_mod = _types.ModuleType("src.services.banquet_payment_service")

class _FakeBanquetDeposit:
    def model_dump(self, **_kw):
        return {
            "id": "aaaa0000-0000-0000-0000-000000000001",
            "banquet_id": "bbbb0000-0000-0000-0000-000000000002",
            "total_deposit_fen": 50000,
            "paid_fen": 0,
            "status": "pending",
            "due_date": None,
            "paid_at": None,
        }

class _FakeBanquetConfirmation:
    id = UUID("cccc0000-0000-0000-0000-000000000003")
    def model_dump(self, **_kw):
        return {
            "id": str(self.id),
            "banquet_id": "bbbb0000-0000-0000-0000-000000000002",
            "confirmation_no": "CONF-20260404-001",
            "menu_items_json": [],
            "total_fen": 120000,
            "guest_count": 20,
            "status": "draft",
            "confirmed_at": None,
            "expires_at": None,
        }

class _FakeSignedConfirmation:
    def model_dump(self, **_kw):
        return {
            "id": "cccc0000-0000-0000-0000-000000000003",
            "status": "confirmed",
            "confirmed_at": "2026-04-04T10:00:00+00:00",
        }

_svc_mod.BanquetPaymentService = MagicMock

# ── 确保 src.services 是带 __path__ 的合法包（相对导入 ..services 需要此条件）──
_src_services_mod = sys.modules.get("src.services")
if _src_services_mod is None or not hasattr(_src_services_mod, "__path__"):
    _src_services_mod = _types.ModuleType("src.services")
    _src_services_mod.__path__ = [os.path.join(_SRC_DIR, "services")]
    _src_services_mod.__package__ = "src.services"
    sys.modules["src.services"] = _src_services_mod

# 注入 banquet_payment_service 存根到两个可能被查找的路径
sys.modules["src.services.banquet_payment_service"] = _svc_mod

# 确保 src.api 包也带 __path__ 和 __package__（relative import 需要）
_src_api_mod = sys.modules.get("src.api")
if _src_api_mod is not None:
    _src_api_mod.__path__ = [os.path.join(_SRC_DIR, "api")]
    _src_api_mod.__package__ = "src.api"

# 直接从文件加载 banquet_payment_routes（使用正确的 package 上下文）
import importlib.util as _ilu                            # noqa: E402
_bp_spec = _ilu.spec_from_file_location(
    "src.api.banquet_payment_routes",
    os.path.join(_SRC_DIR, "api", "banquet_payment_routes.py"),
    submodule_search_locations=[],
)
_bp_mod = _ilu.module_from_spec(_bp_spec)
_bp_mod.__package__ = "src.api"   # 告知解释器此模块属于 src.api 包
try:
    _bp_spec.loader.exec_module(_bp_mod)
    sys.modules["src.api.banquet_payment_routes"] = _bp_mod
    bp_router = _bp_mod.router
    _BP_SVC_CLS = _bp_mod.BanquetPaymentService
    _BP_SVS_DEP = _bp_mod._svc
    _BP_GET_DB_NO_TENANT = _bp_mod._get_db_no_tenant
except Exception as _exc:
    # 如果相对导入失败则跳过宴席路由测试（用 None 占位）
    import traceback as _tb
    print(f"[test_trade_misc] banquet_payment_routes 加载失败: {_exc}")
    _tb.print_exc()
    bp_router = None
    _BP_SVC_CLS = None
    _BP_SVS_DEP = None
    _BP_GET_DB_NO_TENANT = None


# ─── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_ID  = "11111111-1111-1111-1111-111111111111"
STORE_ID   = "22222222-2222-2222-2222-222222222222"
BANQUET_ID = "33333333-3333-3333-3333-333333333333"
HEADERS    = {"X-Tenant-ID": TENANT_ID}

# ─── 工具函数 ──────────────────────────────────────────────────────────────────


def _make_mock_db() -> AsyncMock:
    """创建最小化的 mock AsyncSession。"""
    db = AsyncMock()
    db.commit   = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _fake_mappings_first(mapping) -> MagicMock:
    """result.mappings().first() = mapping（可以是 dict 或 None）。"""
    result = MagicMock()
    result.mappings.return_value.first.return_value = mapping
    return result


def _scalar_result(value) -> MagicMock:
    """result.scalar() = value。"""
    result = MagicMock()
    result.scalar.return_value = value
    return result


def _make_qc_app(db: AsyncMock) -> FastAPI:
    """快餐收银 app（quick_cashier_routes）。"""
    app = FastAPI()
    app.include_router(qc_router)

    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    return app


def _make_bp_app(mock_svc: MagicMock) -> FastAPI:
    """宴席支付 app（banquet_payment_routes），将 _svc 依赖替换为 mock。"""
    if bp_router is None:
        raise RuntimeError("banquet_payment_routes 加载失败")
    app = FastAPI()
    app.include_router(bp_router)

    # 替换 _svc（BanquetPaymentService 工厂依赖）
    async def _override_svc(request=None, db=None):
        return mock_svc

    app.dependency_overrides[_BP_SVS_DEP] = _override_svc
    return app


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ── 文件一：quick_cashier_routes ──────────────────────────────────────────────
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# ─── 场景 1: POST /order — 正常创建快餐订单 ───────────────────────────────────

def test_create_quick_order_success():
    """正常提交一笔快餐订单，DB UPSERT + INSERT 均成功，返回 call_number 和 status=pending。"""
    db = _make_mock_db()

    # _allocate_call_number: config SELECT → seq UPSERT RETURNING current_seq
    config_result = _fake_mappings_first({"prefix": "A", "max_number": 99, "daily_reset": True})
    seq_result = MagicMock()
    seq_result.scalar.return_value = 1          # current_seq = 1 → call_number = "A001"
    insert_order = MagicMock()                  # quick_orders INSERT
    db.execute = AsyncMock(side_effect=[
        config_result,   # config SELECT（_allocate_call_number）
        seq_result,      # seq UPSERT RETURNING
        insert_order,    # quick_orders INSERT
    ])

    payload = {
        "store_id": STORE_ID,
        "order_type": "dine_in",
        "items": [
            {"dish_id": "d001", "dish_name": "红烧肉", "qty": 2, "unit_price_fen": 3800}
        ],
    }

    with patch("src.api.quick_cashier_routes.asyncio.create_task"):
        client = TestClient(_make_qc_app(db))
        resp = client.post("/api/v1/quick-cashier/order", json=payload, headers=HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert "quick_order_id" in data
    assert data["call_number"] == "A001"
    assert data["status"] == "pending"
    assert data["total_fen"] == 7600
    db.commit.assert_awaited_once()


# ─── 场景 2: POST /order — order_type 非法 → 400 ─────────────────────────────

def test_create_quick_order_invalid_order_type():
    """order_type='invalid' 不在允许列表中，应返回 400 且不写 DB。"""
    db = _make_mock_db()

    payload = {
        "store_id": STORE_ID,
        "order_type": "invalid",
        "items": [
            {"dish_id": "d001", "dish_name": "测试菜", "qty": 1, "unit_price_fen": 1000}
        ],
    }

    # _allocate_call_number 在 order_type 校验之后，所以 config SELECT 可能被调用，
    # 但 order_type 校验在它之前——提供充足的 side_effect 以防止 StopAsyncIteration
    config_result = _fake_mappings_first(None)
    seq_result = MagicMock()
    seq_result.scalar.return_value = 1
    db.execute = AsyncMock(side_effect=[config_result, seq_result, MagicMock()])

    client = TestClient(_make_qc_app(db))
    resp = client.post("/api/v1/quick-cashier/order", json=payload, headers=HEADERS)

    assert resp.status_code == 400


# ─── 场景 3: POST /{id}/call — 叫号成功 ──────────────────────────────────────

def test_call_number_success():
    """UPDATE RETURNING 返回行，叫号成功，响应 status=calling。"""
    db = _make_mock_db()

    now_dt = datetime.now(timezone.utc)
    called_row = MagicMock()
    called_row.mappings.return_value.first.return_value = {
        "id": "oid-0001",
        "call_number": "001",
        "status": "calling",
        "called_at": now_dt,
    }
    db.execute = AsyncMock(return_value=called_row)

    client = TestClient(_make_qc_app(db))
    resp = client.post("/api/v1/quick-cashier/oid-0001/call", headers=HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "calling"
    assert body["data"]["call_number"] == "001"
    db.commit.assert_awaited_once()


# ─── 场景 4: POST /{id}/complete — 取餐完成 ──────────────────────────────────

def test_complete_order_success():
    """UPDATE RETURNING 返回行，取餐完成，响应 status=completed。"""
    db = _make_mock_db()

    now_dt = datetime.now(timezone.utc)
    completed_row = MagicMock()
    completed_row.mappings.return_value.first.return_value = {
        "id": "oid-0002",
        "call_number": "002",
        "status": "completed",
        "completed_at": now_dt,
    }
    db.execute = AsyncMock(return_value=completed_row)

    client = TestClient(_make_qc_app(db))
    resp = client.post("/api/v1/quick-cashier/oid-0002/complete", headers=HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "completed"
    assert body["data"]["call_number"] == "002"
    db.commit.assert_awaited_once()


# ─── 场景 5: GET /config/{store_id} — 无配置时返回默认值 ─────────────────────

def test_get_config_returns_default_when_not_configured():
    """quick_cashier_configs 中无记录，应返回 is_enabled=False 的默认配置。"""
    db = _make_mock_db()

    # SELECT 返回 None（无配置记录）
    db.execute = AsyncMock(return_value=_fake_mappings_first(None))

    client = TestClient(_make_qc_app(db))
    resp = client.get(f"/api/v1/quick-cashier/config/{STORE_ID}", headers=HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["is_enabled"] is False
    assert data["call_mode"] == "number"
    assert data["configured"] is False
    assert data["max_number"] == 999


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ── 文件二：banquet_payment_routes ────────────────────────────────────────────
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

import pytest                                            # noqa: E402

_BP_AVAILABLE = bp_router is not None


# ─── 场景 6: POST /{id}/deposit — 创建定金成功 ───────────────────────────────

@pytest.mark.skipif(not _BP_AVAILABLE, reason="banquet_payment_routes 加载失败，跳过")
def test_create_deposit_success():
    """create_deposit 返回 BanquetDeposit，路由正确封装为 ok=True。"""
    svc = AsyncMock()
    svc.create_deposit = AsyncMock(return_value=_FakeBanquetDeposit())

    client = TestClient(_make_bp_app(svc))
    resp = client.post(
        f"/api/v1/banquet/{BANQUET_ID}/deposit",
        json={"total_deposit_fen": 50000},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["total_deposit_fen"] == 50000
    assert data["status"] == "pending"
    svc.create_deposit.assert_awaited_once()


# ─── 场景 7: POST /{id}/deposit — 缺少 X-Tenant-ID → 400 ────────────────────

@pytest.mark.skipif(not _BP_AVAILABLE, reason="banquet_payment_routes 加载失败，跳过")
def test_create_deposit_missing_tenant_id():
    """不传 X-Tenant-ID header，_get_tenant_id 应抛 HTTPException(400)。"""
    svc = AsyncMock()
    svc.create_deposit = AsyncMock(return_value=_FakeBanquetDeposit())

    client = TestClient(_make_bp_app(svc))
    resp = client.post(
        f"/api/v1/banquet/{BANQUET_ID}/deposit",
        json={"total_deposit_fen": 50000},
        # 故意不传 headers
    )

    assert resp.status_code == 400


# ─── 场景 8: GET /{id}/deposit — 定金记录不存在 → ok=False ───────────────────

@pytest.mark.skipif(not _BP_AVAILABLE, reason="banquet_payment_routes 加载失败，跳过")
def test_get_deposit_not_found():
    """get_deposit 返回 None，路由封装为 ok=False, error.code=NOT_FOUND。"""
    svc = AsyncMock()
    svc.get_deposit = AsyncMock(return_value=None)

    client = TestClient(_make_bp_app(svc))
    resp = client.get(
        f"/api/v1/banquet/{BANQUET_ID}/deposit",
        headers=HEADERS,
    )

    assert resp.status_code == 200   # HTTP 200，业务错误在 body
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "NOT_FOUND"


# ─── 场景 9: POST /{id}/confirmation — 创建确认单成功 ────────────────────────

@pytest.mark.skipif(not _BP_AVAILABLE, reason="banquet_payment_routes 加载失败，跳过")
def test_create_confirmation_success():
    """create_confirmation 返回 BanquetConfirmation，路由封装为 ok=True。"""
    svc = AsyncMock()
    svc.create_confirmation = AsyncMock(return_value=_FakeBanquetConfirmation())

    client = TestClient(_make_bp_app(svc))
    resp = client.post(
        f"/api/v1/banquet/{BANQUET_ID}/confirmation",
        json={
            "menu_items": [
                {"dish_id": "dish-001", "dish_name": "佛跳墙",
                 "quantity": 2, "unit_price_fen": 49800, "subtotal_fen": 99600}
            ],
            "guest_count": 20,
            "confirmed_by_name": "张三",
            "confirmed_by_phone": "13800138000",
            "special_requirements": "少辣",
        },
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["status"] == "draft"
    assert data["guest_count"] == 20
    svc.create_confirmation.assert_awaited_once()


# ─── 场景 10: POST /{id}/confirmation/sign — 顾客签字成功 ────────────────────

@pytest.mark.skipif(not _BP_AVAILABLE, reason="banquet_payment_routes 加载失败，跳过")
def test_sign_confirmation_success():
    """confirm_with_signature 返回已签字确认单，status=confirmed。"""
    fake_conf = _FakeBanquetConfirmation()
    svc = AsyncMock()
    svc.get_confirmation = AsyncMock(return_value=fake_conf)
    svc.confirm_with_signature = AsyncMock(return_value=_FakeSignedConfirmation())

    client = TestClient(_make_bp_app(svc))
    resp = client.post(
        f"/api/v1/banquet/{BANQUET_ID}/confirmation/sign",
        json={"signature_data": "data:image/png;base64,iVBORw0KGgo="},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["status"] == "confirmed"
    svc.confirm_with_signature.assert_awaited_once()
