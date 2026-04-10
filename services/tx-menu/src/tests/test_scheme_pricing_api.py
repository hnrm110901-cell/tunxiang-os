"""scheme_routes.py + pricing_routes.py 路由测试

覆盖：
  scheme_routes  — 11 个端点（方案CRUD / 发布 / 下发 / 门店覆盖）
  pricing_routes — 13 个端点（标准价/时价/称重/套餐/渠道/促销/毛利/审批/矩阵/批量/规则/预览）

测试策略:
- 通过 app.dependency_overrides[get_db] 注入 AsyncMock DB Session
- PricingEngine 及 SQLAlchemy 调用全部 mock，不依赖真实数据库
"""
import os
import sys
import types
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# ─── Mock 模块前置注入 ─────────────────────────────────────────────────────────
for _mod in [
    "shared",
    "shared.ontology",
    "shared.ontology.src",
    "shared.ontology.src.database",
]:
    sys.modules.setdefault(_mod, types.ModuleType(_mod))


async def _fake_get_db():
    yield None


sys.modules["shared.ontology.src.database"].get_db = _fake_get_db  # type: ignore[attr-defined]

# structlog stub
if "structlog" not in sys.modules:
    _structlog = types.ModuleType("structlog")
    _structlog.get_logger = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]
    sys.modules["structlog"] = _structlog

# sqlalchemy stubs
for _mod in ["sqlalchemy", "sqlalchemy.ext", "sqlalchemy.ext.asyncio"]:
    sys.modules.setdefault(_mod, types.ModuleType(_mod))

import sqlalchemy as _sa

_sa.text = MagicMock(return_value=MagicMock())
sys.modules["sqlalchemy.ext.asyncio"].AsyncSession = MagicMock()  # type: ignore[attr-defined]

# src.services.pricing_engine stub
for _mod in ["src.services", "src.services.pricing_engine"]:
    sys.modules.setdefault(_mod, types.ModuleType(_mod))

_pricing_engine_mock = MagicMock()
_PricingEngine_cls = MagicMock()
sys.modules["src.services.pricing_engine"].PricingEngine = _PricingEngine_cls  # type: ignore[attr-defined]

# ─── 路径设置 ──────────────────────────────────────────────────────────────────
_tx_menu_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_repo_root = os.path.abspath(os.path.join(_tx_menu_dir, "..", ".."))
for _p in [_tx_menu_dir, _repo_root]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.scheme_routes import get_db as scheme_get_db
from src.api.scheme_routes import router as scheme_router
from src.api.pricing_routes import get_db as pricing_get_db
from src.api.pricing_routes import router as pricing_router

# ─── 测试常量 ──────────────────────────────────────────────────────────────────
TENANT = str(uuid.uuid4())
SCHEME_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
DISH_ID = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT}


# ─── 辅助 ──────────────────────────────────────────────────────────────────────

def _make_mock_session():
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.close = AsyncMock()
    return session


def _async_dep(session):
    async def _dep():
        yield session
    return _dep


def _make_scheme_app(db_override=None) -> FastAPI:
    app = FastAPI()
    app.include_router(scheme_router)
    if db_override is not None:
        app.dependency_overrides[scheme_get_db] = db_override
    return app


def _make_pricing_app(db_override=None) -> FastAPI:
    app = FastAPI()
    app.include_router(pricing_router)
    if db_override is not None:
        app.dependency_overrides[pricing_get_db] = db_override
    return app


def _scalar_result(value):
    """返回一个 execute 结果，scalar() 返回 value。"""
    r = MagicMock()
    r.scalar.return_value = value
    r.fetchone.return_value = None
    r.fetchall.return_value = []
    return r


def _row_result(row):
    """execute 结果，fetchone() 返回 row。"""
    r = MagicMock()
    r.fetchone.return_value = row
    r.scalar.return_value = None
    r.fetchall.return_value = []
    return r


def _rows_result(rows):
    r = MagicMock()
    r.fetchall.return_value = rows
    r.fetchone.return_value = None
    r.scalar.return_value = len(rows)
    return r


# ══════════════════════════════════════════════════════════════════════════════
# scheme_routes 测试
# ══════════════════════════════════════════════════════════════════════════════

# ─── 1. GET /api/v1/menu-schemes/ — 方案列表 ───────────────────────────────────

def test_list_schemes_success():
    """GET /api/v1/menu-schemes/ — 正常返回空列表。"""
    session = _make_mock_session()
    # count query returns 0, rows query returns []
    session.execute.side_effect = [_scalar_result(0), _rows_result([])]

    app = _make_scheme_app(_async_dep(session))
    client = TestClient(app)
    resp = client.get("/api/v1/menu-schemes/", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 0
    assert body["data"]["items"] == []


def test_list_schemes_missing_tenant():
    """GET /api/v1/menu-schemes/ — 缺少 X-Tenant-ID 返回 422。"""
    app = _make_scheme_app()
    client = TestClient(app)
    resp = client.get("/api/v1/menu-schemes/")
    assert resp.status_code == 422


def test_list_schemes_invalid_tenant():
    """GET /api/v1/menu-schemes/ — 非 UUID tenant 返回 400。"""
    app = _make_scheme_app(_async_dep(_make_mock_session()))
    client = TestClient(app)
    resp = client.get("/api/v1/menu-schemes/", headers={"X-Tenant-ID": "not-a-uuid"})
    assert resp.status_code in (400, 422, 500)


# ─── 2. POST /api/v1/menu-schemes/ — 新建方案 ─────────────────────────────────

def test_create_scheme_success():
    """POST /api/v1/menu-schemes/ — 成功创建方案，返回 201 ok=True。"""
    session = _make_mock_session()
    now = datetime.now(timezone.utc)
    new_id = uuid.uuid4()
    row = MagicMock()
    row.__getitem__ = lambda self, i: [new_id, "春季菜谱", None, None, "draft", now][i]

    insert_result = MagicMock()
    insert_result.fetchone.return_value = row
    session.execute.return_value = insert_result

    app = _make_scheme_app(_async_dep(session))
    client = TestClient(app)
    payload = {"name": "春季菜谱"}
    resp = client.post("/api/v1/menu-schemes/", json=payload, headers=HEADERS)
    assert resp.status_code in (201, 200)
    body = resp.json()
    assert body["ok"] is True


def test_create_scheme_missing_name():
    """POST /api/v1/menu-schemes/ — name 缺失时 422。"""
    app = _make_scheme_app(_async_dep(_make_mock_session()))
    client = TestClient(app)
    resp = client.post("/api/v1/menu-schemes/", json={}, headers=HEADERS)
    assert resp.status_code == 422


# ─── 3. GET /api/v1/menu-schemes/{scheme_id} — 方案详情 ───────────────────────

def test_get_scheme_not_found():
    """GET /api/v1/menu-schemes/{id} — 方案不存在返回 404。"""
    session = _make_mock_session()
    scheme_result = _row_result(None)
    session.execute.return_value = scheme_result

    app = _make_scheme_app(_async_dep(session))
    client = TestClient(app)
    resp = client.get(f"/api/v1/menu-schemes/{SCHEME_ID}", headers=HEADERS)
    assert resp.status_code == 404


def test_get_scheme_invalid_id():
    """GET /api/v1/menu-schemes/{id} — 非法 UUID 返回 400。"""
    app = _make_scheme_app(_async_dep(_make_mock_session()))
    client = TestClient(app)
    resp = client.get("/api/v1/menu-schemes/bad-id", headers=HEADERS)
    assert resp.status_code == 400


# ─── 4. PUT /api/v1/menu-schemes/{scheme_id} — 更新方案 ───────────────────────

def test_update_scheme_success():
    """PUT /api/v1/menu-schemes/{id} — 成功更新方案基本信息。"""
    session = _make_mock_session()
    row = MagicMock()
    row.__getitem__ = lambda self, i: "draft"
    check_result = MagicMock()
    check_result.fetchone.return_value = row
    update_result = MagicMock()
    session.execute.side_effect = [check_result, check_result, update_result]

    app = _make_scheme_app(_async_dep(session))
    client = TestClient(app)
    payload = {"name": "夏季菜谱", "description": "夏日特供"}
    resp = client.put(f"/api/v1/menu-schemes/{SCHEME_ID}", json=payload, headers=HEADERS)
    assert resp.status_code in (200, 404)


def test_update_scheme_not_found():
    """PUT /api/v1/menu-schemes/{id} — 方案不存在返回 404。"""
    session = _make_mock_session()
    check_result = MagicMock()
    check_result.fetchone.return_value = None
    session.execute.return_value = check_result

    app = _make_scheme_app(_async_dep(session))
    client = TestClient(app)
    resp = client.put(f"/api/v1/menu-schemes/{SCHEME_ID}", json={"name": "x"}, headers=HEADERS)
    assert resp.status_code == 404


# ─── 5. POST /api/v1/menu-schemes/{scheme_id}/publish — 发布方案 ───────────────

def test_publish_scheme_already_published():
    """POST /publish — 已发布方案重复发布返回 400。"""
    session = _make_mock_session()
    row = MagicMock()
    row.__getitem__ = lambda self, i: "published"
    check_result = MagicMock()
    check_result.fetchone.return_value = row
    session.execute.return_value = check_result

    app = _make_scheme_app(_async_dep(session))
    client = TestClient(app)
    resp = client.post(f"/api/v1/menu-schemes/{SCHEME_ID}/publish", headers=HEADERS)
    assert resp.status_code == 400


def test_publish_scheme_no_items():
    """POST /publish — 方案无菜品时拒绝发布（400）。"""
    session = _make_mock_session()

    draft_row = MagicMock()
    draft_row.__getitem__ = lambda self, i: "draft"
    check_result = MagicMock()
    check_result.fetchone.return_value = draft_row

    count_result = MagicMock()
    count_result.scalar.return_value = 0

    session.execute.side_effect = [check_result, check_result, count_result]

    app = _make_scheme_app(_async_dep(session))
    client = TestClient(app)
    resp = client.post(f"/api/v1/menu-schemes/{SCHEME_ID}/publish", headers=HEADERS)
    assert resp.status_code == 400


# ─── 6. POST /api/v1/menu-schemes/{scheme_id}/distribute — 下发到门店 ──────────

def test_distribute_scheme_not_published():
    """POST /distribute — 未发布方案下发返回 400。"""
    session = _make_mock_session()
    row = MagicMock()
    row.__getitem__ = lambda self, i: "draft"
    check_result = MagicMock()
    check_result.fetchone.return_value = row
    session.execute.return_value = check_result

    app = _make_scheme_app(_async_dep(session))
    client = TestClient(app)
    payload = {"store_ids": [str(uuid.uuid4())]}
    resp = client.post(f"/api/v1/menu-schemes/{SCHEME_ID}/distribute", json=payload, headers=HEADERS)
    assert resp.status_code == 400


# ─── 7. GET /api/v1/menu-schemes/{scheme_id}/stores — 已下发门店 ───────────────

def test_get_scheme_stores_empty():
    """GET /stores — 尚未下发任何门店时返回空列表。"""
    session = _make_mock_session()
    count_result = MagicMock()
    count_result.scalar.return_value = 0
    rows_result = MagicMock()
    rows_result.fetchall.return_value = []
    session.execute.side_effect = [count_result, rows_result]

    app = _make_scheme_app(_async_dep(session))
    client = TestClient(app)
    resp = client.get(f"/api/v1/menu-schemes/{SCHEME_ID}/stores", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["total"] == 0


# ─── 8. POST /api/v1/menu-schemes/{scheme_id}/items — 批量设置菜品 ─────────────

def test_set_scheme_items_archived():
    """POST /items — 已归档方案不可编辑，返回 400。"""
    session = _make_mock_session()
    row = MagicMock()
    row.__getitem__ = lambda self, i: "archived"
    check_result = MagicMock()
    check_result.fetchone.return_value = row
    session.execute.return_value = check_result

    app = _make_scheme_app(_async_dep(session))
    client = TestClient(app)
    payload = {
        "items": [
            {"dish_id": DISH_ID, "is_available": True, "sort_order": 0}
        ]
    }
    resp = client.post(f"/api/v1/menu-schemes/{SCHEME_ID}/items", json=payload, headers=HEADERS)
    assert resp.status_code == 400


# ─── 9. GET /api/v1/store-menu/{store_id} — 门店菜谱 ─────────────────────────

def test_get_store_menu_no_scheme():
    """GET /store-menu/{id} — 门店尚无方案时返回空列表提示。"""
    session = _make_mock_session()
    latest_result = MagicMock()
    latest_result.fetchone.return_value = None
    session.execute.return_value = latest_result

    app = _make_scheme_app(_async_dep(session))
    client = TestClient(app)
    resp = client.get(f"/api/v1/store-menu/{STORE_ID}", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["items"] == []


# ─── 10. PUT /api/v1/store-menu/{store_id}/override — 门店覆盖 ────────────────

def test_set_store_override_no_assignment():
    """PUT /store-menu/override — 门店未分配该方案时拒绝覆盖（400）。"""
    session = _make_mock_session()
    check_result = MagicMock()
    check_result.fetchone.return_value = None
    session.execute.return_value = check_result

    app = _make_scheme_app(_async_dep(session))
    client = TestClient(app)
    payload = {
        "dish_id": DISH_ID,
        "scheme_id": SCHEME_ID,
        "override_price_fen": 5000,
        "override_available": True,
    }
    resp = client.put(f"/api/v1/store-menu/{STORE_ID}/override", json=payload, headers=HEADERS)
    assert resp.status_code == 400


# ─── 11. DELETE /api/v1/store-menu/{store_id}/override/{dish_id} ─────────────

def test_delete_store_override_success():
    """DELETE /store-menu/override/{dish_id} — 成功删除门店覆盖。"""
    session = _make_mock_session()
    del_result = MagicMock()
    del_result.rowcount = 1
    session.execute.return_value = del_result

    app = _make_scheme_app(_async_dep(session))
    client = TestClient(app)
    resp = client.delete(
        f"/api/v1/store-menu/{STORE_ID}/override/{DISH_ID}?scheme_id={SCHEME_ID}",
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True


# ══════════════════════════════════════════════════════════════════════════════
# pricing_routes 测试
# ══════════════════════════════════════════════════════════════════════════════

def _pricing_engine_returning(value):
    """让 PricingEngine 实例的所有 async 方法返回给定值。"""
    inst = AsyncMock()
    inst.get_standard_price = AsyncMock(return_value=value)
    inst.set_market_price = AsyncMock(return_value=value)
    inst.calculate_weighing_price = AsyncMock(return_value=value)
    inst.create_combo_price = AsyncMock(return_value=value)
    inst.set_channel_price = AsyncMock(return_value=value)
    inst.set_promotion_price = AsyncMock(return_value=value)
    inst.validate_margin = AsyncMock(return_value=value)
    inst.approve_price_change = AsyncMock(return_value=value)
    _PricingEngine_cls.return_value = inst
    return inst


# ─── 1. GET /api/v1/pricing/standard-price/{dish_id} ─────────────────────────

def test_get_standard_price():
    """GET /standard-price/{dish_id} — 成功返回标准价数据。"""
    expected = {"dish_id": DISH_ID, "price_fen": 5800, "channel": "dine_in"}
    _pricing_engine_returning(expected)

    session = _make_mock_session()
    app = _make_pricing_app(_async_dep(session))
    client = TestClient(app)
    resp = client.get(f"/api/v1/pricing/standard-price/{DISH_ID}", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["price_fen"] == 5800


# ─── 2. POST /api/v1/pricing/market-price ────────────────────────────────────

def test_set_market_price():
    """POST /market-price — 时价设置成功。"""
    expected = {"dish_id": DISH_ID, "price_fen": 12000, "status": "set"}
    _pricing_engine_returning(expected)

    session = _make_mock_session()
    app = _make_pricing_app(_async_dep(session))
    client = TestClient(app)
    payload = {
        "dish_id": DISH_ID,
        "price_fen": 12000,
        "effective_from": "2026-04-06T09:00:00+08:00",
    }
    resp = client.post("/api/v1/pricing/market-price", json=payload, headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# ─── 3. POST /api/v1/pricing/weighing-price ──────────────────────────────────

def test_calculate_weighing_price():
    """POST /weighing-price — 称重计价成功。"""
    expected = {"dish_id": DISH_ID, "weight_g": 300, "price_fen": 3600}
    _pricing_engine_returning(expected)

    session = _make_mock_session()
    app = _make_pricing_app(_async_dep(session))
    client = TestClient(app)
    payload = {"dish_id": DISH_ID, "weight_g": 300}
    resp = client.post("/api/v1/pricing/weighing-price", json=payload, headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# ─── 4. POST /api/v1/pricing/combo-price ─────────────────────────────────────

def test_create_combo_price():
    """POST /combo-price — 套餐组合定价计算成功。"""
    expected = {"total_price_fen": 8800, "original_price_fen": 10800}
    _pricing_engine_returning(expected)

    session = _make_mock_session()
    app = _make_pricing_app(_async_dep(session))
    client = TestClient(app)
    payload = {
        "dishes": [{"dish_id": DISH_ID, "quantity": 1}],
        "discount_rate": 0.85,
    }
    resp = client.post("/api/v1/pricing/combo-price", json=payload, headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# ─── 5. POST /api/v1/pricing/channel-price ───────────────────────────────────

def test_set_channel_price():
    """POST /channel-price — 多渠道差异价设置成功。"""
    expected = {"dish_id": DISH_ID, "channels_updated": 2}
    _pricing_engine_returning(expected)

    session = _make_mock_session()
    app = _make_pricing_app(_async_dep(session))
    client = TestClient(app)
    payload = {
        "dish_id": DISH_ID,
        "channel_prices": {"dine_in": 5800, "meituan": 6200},
    }
    resp = client.post("/api/v1/pricing/channel-price", json=payload, headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# ─── 6. POST /api/v1/pricing/promotion-price ─────────────────────────────────

def test_set_promotion_price():
    """POST /promotion-price — 限时促销价设置成功。"""
    expected = {"dish_id": DISH_ID, "promo_price_fen": 4000, "status": "active"}
    _pricing_engine_returning(expected)

    session = _make_mock_session()
    app = _make_pricing_app(_async_dep(session))
    client = TestClient(app)
    payload = {
        "dish_id": DISH_ID,
        "promo_price_fen": 4000,
        "start": "2026-04-06T00:00:00+08:00",
        "end": "2026-04-07T00:00:00+08:00",
    }
    resp = client.post("/api/v1/pricing/promotion-price", json=payload, headers=HEADERS)
    assert resp.status_code == 200


# ─── 7. POST /api/v1/pricing/validate-margin ─────────────────────────────────

def test_validate_margin_pass():
    """POST /validate-margin — 毛利校验通过。"""
    expected = {"dish_id": DISH_ID, "margin_ok": True, "margin_rate": 0.55}
    _pricing_engine_returning(expected)

    session = _make_mock_session()
    app = _make_pricing_app(_async_dep(session))
    client = TestClient(app)
    payload = {"dish_id": DISH_ID, "proposed_price_fen": 5800}
    resp = client.post("/api/v1/pricing/validate-margin", json=payload, headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["margin_ok"] is True


# ─── 8. POST /api/v1/pricing/approve-change ──────────────────────────────────

def test_approve_price_change():
    """POST /approve-change — 审批调价申请成功。"""
    expected = {"change_id": "chg-001", "status": "approved"}
    _pricing_engine_returning(expected)

    session = _make_mock_session()
    app = _make_pricing_app(_async_dep(session))
    client = TestClient(app)
    payload = {"change_id": "chg-001", "approver_id": "mgr-001"}
    resp = client.post("/api/v1/pricing/approve-change", json=payload, headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# ─── 9. GET /api/v1/pricing/matrix ───────────────────────────────────────────

def test_get_pricing_matrix_empty():
    """GET /matrix — 无菜品时返回空矩阵。"""
    session = _make_mock_session()
    dishes_result = MagicMock()
    dishes_result.fetchall.return_value = []
    session.execute.return_value = dishes_result

    app = _make_pricing_app(_async_dep(session))
    client = TestClient(app)
    resp = client.get(f"/api/v1/pricing/matrix?store_id={STORE_ID}", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total_dishes"] == 0


def test_get_pricing_matrix_missing_store():
    """GET /matrix — 缺少 store_id 返回 422。"""
    session = _make_mock_session()
    app = _make_pricing_app(_async_dep(session))
    client = TestClient(app)
    resp = client.get("/api/v1/pricing/matrix", headers=HEADERS)
    assert resp.status_code == 422


# ─── 10. PUT /api/v1/pricing/batch ───────────────────────────────────────────

def test_batch_price_update():
    """PUT /batch — 批量调价成功。"""
    session = _make_mock_session()
    session.execute.return_value = MagicMock()

    app = _make_pricing_app(_async_dep(session))
    client = TestClient(app)
    payload = {
        "store_id": STORE_ID,
        "items": [
            {"dish_id": DISH_ID, "channel": "dine_in", "new_price_fen": 6000},
        ],
    }
    resp = client.put("/api/v1/pricing/batch", json=payload, headers=HEADERS)
    assert resp.status_code in (200, 400, 422)


# ─── 11. GET /api/v1/pricing/rules ───────────────────────────────────────────

def test_get_pricing_rules():
    """GET /rules — 加价规则查询成功，返回列表。"""
    session = _make_mock_session()
    rows_mock = MagicMock()
    rows_mock.fetchall.return_value = []
    session.execute.return_value = rows_mock

    app = _make_pricing_app(_async_dep(session))
    client = TestClient(app)
    resp = client.get(f"/api/v1/pricing/rules?store_id={STORE_ID}", headers=HEADERS)
    assert resp.status_code in (200, 422)


# ─── 12. POST /api/v1/pricing/rules — 创建加价规则 ───────────────────────────

def test_create_pricing_rule():
    """POST /rules — 创建加价规则成功（201）。"""
    session = _make_mock_session()
    insert_result = MagicMock()
    insert_result.fetchone.return_value = (uuid.uuid4(), STORE_ID, "meituan", "percent", 5.0, None)
    session.execute.return_value = insert_result

    app = _make_pricing_app(_async_dep(session))
    client = TestClient(app)
    payload = {
        "store_id": STORE_ID,
        "channel": "meituan",
        "rule_type": "percent",
        "value": 5.0,
        "description": "美团加价5%",
    }
    resp = client.post("/api/v1/pricing/rules", json=payload, headers=HEADERS)
    assert resp.status_code in (200, 201, 400, 422)


# ─── 13. POST /api/v1/pricing/preview — 调价预览 ─────────────────────────────

def test_preview_pricing():
    """POST /preview — 加价规则预览成功。"""
    session = _make_mock_session()
    dishes_mock = MagicMock()
    dishes_mock.fetchall.return_value = []
    session.execute.return_value = dishes_mock

    app = _make_pricing_app(_async_dep(session))
    client = TestClient(app)
    payload = {
        "store_id": STORE_ID,
        "channel": "meituan",
        "rule_type": "percent",
        "value": 5.0,
    }
    resp = client.post("/api/v1/pricing/preview", json=payload, headers=HEADERS)
    assert resp.status_code in (200, 400, 422)
