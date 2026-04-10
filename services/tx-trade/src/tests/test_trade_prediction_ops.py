"""tx-trade 补充测试 — prediction + printer_config + proactive_service + order_ops + supply_chain_mobile

覆盖场景（共 20 个）：

── prediction_routes.py (4 个) ──
1.  GET /api/v1/predict/dish-time/{dish_id}         — 菜品出餐时间预测成功
2.  GET /api/v1/predict/order/{order_id}/completion — 订单出餐完成时间预测成功
3.  GET /api/v1/predict/table/{table_no}/turn       — 翻台时机预测成功
4.  GET /api/v1/predict/busy-periods                — 高峰时段预测成功

── printer_config_routes.py (4 个) ──
5.  GET    /api/v1/printers                         — 获取打印机列表成功
6.  POST   /api/v1/printers                         — 注册打印机成功
7.  DELETE /api/v1/printers/{printer_id}            — 停用打印机 → 404 不存在
8.  GET    /api/v1/printers/resolve                 — 路由解析无匹配 → data=None

── proactive_service_routes.py (4 个) ──
9.  GET  /api/v1/service/suggestions/all            — 店长视角建议汇总
10. GET  /api/v1/service/suggestions/{order_id}     — 订单建议列表
11. POST /api/v1/service/suggestions/{order_id}/{suggestion_type}/dismiss — 忽略建议
12. GET  /api/v1/orders/{order_id}/constraint-status — 三约束状态查询

── order_ops_routes.py (4 个) ──
13. POST /api/v1/orders/{order_id}/gift             — 赠菜成功
14. POST /api/v1/orders/{order_id}/split            — 拆单成功
15. POST /api/v1/orders/merge                       — 并单 ValueError → 400
16. PUT  /api/v1/orders/changes/{change_id}/approve — 改单审批成功

── supply_chain_mobile_routes.py (4 个) ──
17. POST /api/v1/supply/receiving                   — 到货接收成功
18. GET  /api/v1/supply/receiving/history           — 到货历史查询成功
19. POST /api/v1/supply/stocktake/start             — 开始盘点成功
20. POST /api/v1/supply/purchase/{purchase_id}/approve — 采购审批 404 → 报错
"""
import os
import sys
import types
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ─── sys.path ──────────────────────────────────────────────────────────────────
_TESTS_DIR = os.path.dirname(__file__)
_SRC_DIR   = os.path.abspath(os.path.join(_TESTS_DIR, ".."))
_ROOT_DIR  = os.path.abspath(os.path.join(_TESTS_DIR, "..", "..", "..", ".."))

for _p in [_SRC_DIR, _ROOT_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ─── 包层级设置工具 ────────────────────────────────────────────────────────────

def _ensure_pkg(name: str, path: str | None = None) -> types.ModuleType:
    if name not in sys.modules:
        mod = types.ModuleType(name)
        if path:
            mod.__path__ = [path]
        mod.__package__ = name
        sys.modules[name] = mod
    return sys.modules[name]


def _stub_module(full_name: str, **attrs) -> types.ModuleType:
    if full_name in sys.modules:
        mod = sys.modules[full_name]
    else:
        mod = types.ModuleType(full_name)
        parent = full_name.rsplit(".", 1)[0] if "." in full_name else None
        if parent:
            mod.__package__ = parent
        sys.modules[full_name] = mod
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


# ─── 基础包结构 ────────────────────────────────────────────────────────────────

_ensure_pkg("src",          _SRC_DIR)
_ensure_pkg("src.api",      os.path.join(_SRC_DIR, "api"))
_ensure_pkg("src.services", os.path.join(_SRC_DIR, "services"))


# ─── structlog 存根 ────────────────────────────────────────────────────────────

if "structlog" not in sys.modules:
    _structlog = types.ModuleType("structlog")
    _structlog.get_logger = MagicMock(return_value=MagicMock())
    sys.modules["structlog"] = _structlog
else:
    sys.modules["structlog"].get_logger = MagicMock(return_value=MagicMock())


# ─── shared 存根 ───────────────────────────────────────────────────────────────

_ensure_pkg("shared")
_ensure_pkg("shared.ontology")
_ensure_pkg("shared.ontology.src")

_db_mod = types.ModuleType("shared.ontology.src.database")

async def _fake_get_db():
    yield AsyncMock()

async def _fake_get_db_with_tenant(tenant_id):  # noqa: ARG001
    yield AsyncMock()

_db_mod.get_db = _fake_get_db
_db_mod.get_db_with_tenant = _fake_get_db_with_tenant
_db_mod.async_session_factory = MagicMock()
sys.modules["shared.ontology.src.database"] = _db_mod


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION A: prediction_routes.py
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# prediction_service 存根
class _DishTimePrediction:
    def to_dict(self):
        return {"dish_id": "dish-001", "predicted_minutes": 8, "confidence": "high"}

class _OrderCompletionPrediction:
    def to_dict(self):
        return {"order_id": "order-001", "predicted_minutes": 15, "confidence": "medium"}

class _TableTurnPrediction:
    def to_dict(self):
        return {"table_no": "A01", "remaining_minutes": 20, "confidence": "medium"}

class _BusyPeriod:
    def __init__(self, label):
        self._label = label
    def to_dict(self):
        return {"label": self._label, "start": "11:30", "end": "13:30"}

_pred_svc = _stub_module(
    "src.services.prediction_service",
    predict_dish_time=AsyncMock(return_value=_DishTimePrediction()),
    predict_order_completion=AsyncMock(return_value=_OrderCompletionPrediction()),
    predict_table_turn=AsyncMock(return_value=_TableTurnPrediction()),
    get_busy_period_forecast=AsyncMock(return_value=[_BusyPeriod("午高峰"), _BusyPeriod("晚高峰")]),
)

# 让相对导入 ..services.prediction_service 也能找到同一模块
sys.modules["services"] = sys.modules.get("services") or types.ModuleType("services")
sys.modules["services.prediction_service"] = _pred_svc

# 导入路由
from src.api.prediction_routes import router as _pred_router  # noqa: E402

def _make_pred_app() -> FastAPI:
    app = FastAPI()
    app.include_router(_pred_router)
    return app

TENANT_ID  = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
STORE_ID   = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
ORDER_ID   = "cccccccc-cccc-cccc-cccc-cccccccccccc"
HEADERS    = {"X-Tenant-ID": TENANT_ID}


# ──── 场景 1: 菜品出餐时间预测 ─────────────────────────────────────────────────

def test_predict_dish_time_success():
    """菜品出餐时间预测成功：返回 predicted_minutes 字段。"""
    # prediction_routes 使用局部 import，需 patch service 模块的函数本身
    _pred_svc.predict_dish_time = AsyncMock(return_value=_DishTimePrediction())

    client = TestClient(_make_pred_app())
    resp = client.get(
        "/api/v1/predict/dish-time/dish-001",
        params={"store_id": STORE_ID, "dept_id": "dept-001"},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["predicted_minutes"] == 8
    assert body["data"]["confidence"] == "high"


# ──── 场景 2: 订单出餐完成时间预测 ────────────────────────────────────────────

def test_predict_order_completion_success():
    """订单整体出餐完成时间预测成功。"""
    _pred_svc.predict_order_completion = AsyncMock(return_value=_OrderCompletionPrediction())

    client = TestClient(_make_pred_app())
    resp = client.get(
        f"/api/v1/predict/order/{ORDER_ID}/completion",
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["predicted_minutes"] == 15


# ──── 场景 3: 翻台时机预测 ─────────────────────────────────────────────────────

def test_predict_table_turn_success():
    """翻台时机预测成功：返回 remaining_minutes。"""
    _pred_svc.predict_table_turn = AsyncMock(return_value=_TableTurnPrediction())

    client = TestClient(_make_pred_app())
    resp = client.get(
        "/api/v1/predict/table/A01/turn",
        params={"store_id": STORE_ID, "seats": 4, "elapsed_minutes": 30},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["remaining_minutes"] == 20


# ──── 场景 4: 高峰时段预测 ─────────────────────────────────────────────────────

def test_predict_busy_periods_success():
    """高峰时段预测成功：返回 date 和 periods 列表。"""
    _pred_svc.get_busy_period_forecast = AsyncMock(
        return_value=[_BusyPeriod("午高峰"), _BusyPeriod("晚高峰")]
    )

    client = TestClient(_make_pred_app())
    resp = client.get(
        "/api/v1/predict/busy-periods",
        params={"store_id": STORE_ID, "date": "2026-04-05"},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["date"] == "2026-04-05"
    assert len(body["data"]["periods"]) == 2
    assert body["data"]["periods"][0]["label"] == "午高峰"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION B: printer_config_routes.py
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# print_manager 存根（test_printer 端点需要）
_print_mgr = MagicMock()
_print_task = MagicMock()
_print_task.to_dict.return_value = {"status": "sent"}
_print_mgr.test_print = AsyncMock(return_value=_print_task)
_stub_module("src.services.print_manager", get_print_manager=MagicMock(return_value=_print_mgr))

from src.api.printer_config_routes import router as _printer_router  # noqa: E402
from shared.ontology.src.database import get_db as _get_db  # noqa: E402


def _make_printer_app(db_mock: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.include_router(_printer_router)

    async def _override():
        yield db_mock

    app.dependency_overrides[_get_db] = _override
    return app


PRINTER_ID = str(uuid.uuid4())
ROUTE_ID   = str(uuid.uuid4())


def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.commit   = AsyncMock()
    db.rollback = AsyncMock()
    _res = MagicMock()
    _res.fetchone.return_value = None
    _res.fetchall.return_value = []
    db.execute = AsyncMock(return_value=_res)
    return db


def _make_printer_row(pid: str = PRINTER_ID):
    """生成 row mock 用于 _row_to_printer 序列化。"""
    row = MagicMock()
    row.id              = uuid.UUID(pid)
    row.tenant_id       = uuid.UUID(TENANT_ID)
    row.store_id        = uuid.UUID(STORE_ID)
    row.name            = "前台打印机"
    row.type            = "receipt"
    row.connection_type = "network"
    row.address         = "192.168.1.100"
    row.is_active       = True
    row.paper_width     = 80
    row.created_at      = None
    row.updated_at      = None
    return row


# ──── 场景 5: GET /printers — 获取打印机列表 ──────────────────────────────────

def test_list_printers_success():
    """获取门店打印机列表：返回 ok=True 及打印机数组。"""
    db = _make_db()

    row = _make_printer_row()
    _res = MagicMock()
    _res.fetchall.return_value = [row]
    db.execute = AsyncMock(return_value=_res)

    app = _make_printer_app(db)
    client = TestClient(app)
    resp = client.get(
        "/api/v1/printers",
        params={"store_id": STORE_ID},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert len(body["data"]) == 1
    assert body["data"][0]["name"] == "前台打印机"
    assert body["data"][0]["type"] == "receipt"


# ──── 场景 6: POST /printers — 注册打印机成功 ─────────────────────────────────

def test_create_printer_success():
    """注册新打印机：INSERT RETURNING 返回打印机信息，响应 ok=True。"""
    db = _make_db()

    row = _make_printer_row()
    _res = MagicMock()
    _res.fetchone.return_value = row
    db.execute = AsyncMock(return_value=_res)

    app = _make_printer_app(db)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/printers",
        json={
            "store_id": STORE_ID,
            "name": "前台打印机",
            "type": "receipt",
            "connection_type": "network",
            "address": "192.168.1.100",
            "paper_width": 80,
        },
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["name"] == "前台打印机"
    assert body["data"]["connection_type"] == "network"


# ──── 场景 7: DELETE /printers/{printer_id} — 打印机不存在 → 404 ───────────────

def test_deactivate_printer_not_found():
    """停用打印机时找不到记录应返回 404。"""
    db = _make_db()

    # UPDATE RETURNING 没有行返回
    _res = MagicMock()
    _res.fetchone.return_value = None
    db.execute = AsyncMock(return_value=_res)

    app = _make_printer_app(db)
    client = TestClient(app)
    resp = client.delete(
        f"/api/v1/printers/{PRINTER_ID}",
        headers=HEADERS,
    )

    assert resp.status_code == 404
    assert "不存在" in resp.json()["detail"]


# ──── 场景 8: GET /printers/resolve — 无匹配规则 → data=None ──────────────────

def test_resolve_printer_no_match():
    """路由解析无任何匹配规则时返回 data=None。"""
    db = _make_db()

    # 所有 SELECT 均返回 None（无匹配）
    _res = MagicMock()
    _res.fetchone.return_value = None
    db.execute = AsyncMock(return_value=_res)

    app = _make_printer_app(db)
    client = TestClient(app)
    resp = client.get(
        "/api/v1/printers/resolve",
        params={"store_id": STORE_ID},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"] is None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION C: proactive_service_routes.py
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 先定义 dataclass 存根，再导入路由

class _MarginStatus:
    ok    = True
    pct   = 0.42
    level = "ok"

class _FoodSafetyStatus:
    ok     = True
    issues = []
    level  = "ok"

class _ServiceTimeStatus:
    ok          = True
    elapsed_min = 25
    limit_min   = 90
    level       = "ok"

class _ConstraintStatusStub:
    margin       = _MarginStatus()
    food_safety  = _FoodSafetyStatus()
    service_time = _ServiceTimeStatus()

class _SuggestionStub:
    type         = "upsell"
    message      = "推荐加单甜品"
    urgency      = "low"
    action_label = "查看推荐"
    action_data  = {}

_proactive_svc = _stub_module(
    "src.services.proactive_service_agent",
    ServiceSuggestion    = _SuggestionStub,
    ConstraintStatus     = _ConstraintStatusStub,
    get_service_suggestions = AsyncMock(return_value=[_SuggestionStub()]),
    get_table_suggestions   = AsyncMock(return_value={"A01": [_SuggestionStub()]}),
    dismiss_suggestion      = MagicMock(return_value=None),
    get_constraint_status   = AsyncMock(return_value=_ConstraintStatusStub()),
)

from src.api.proactive_service_routes import router as _proactive_router  # noqa: E402


def _make_proactive_app() -> FastAPI:
    app = FastAPI()
    app.include_router(_proactive_router)
    return app


# ──── 场景 9: GET /service/suggestions/all — 店长视角汇总 ──────────────────────

def test_list_all_suggestions_success():
    """店长视角建议汇总：返回 {table_no: [...suggestions]} 结构。"""
    with patch("src.api.proactive_service_routes.get_table_suggestions",
               new=AsyncMock(return_value={"A01": [_SuggestionStub()], "B02": []})):
        client = TestClient(_make_proactive_app())
        resp = client.get(
            "/api/v1/service/suggestions/all",
            params={"store_id": STORE_ID},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "A01" in body["data"]
    assert len(body["data"]["A01"]) == 1
    assert body["data"]["A01"][0]["type"] == "upsell"


# ──── 场景 10: GET /service/suggestions/{order_id} — 订单建议列表 ──────────────

def test_get_order_suggestions_success():
    """服务员视角：获取指定订单的建议列表，含 type/message 字段。"""
    with patch("src.api.proactive_service_routes.get_service_suggestions",
               new=AsyncMock(return_value=[_SuggestionStub()])):
        client = TestClient(_make_proactive_app())
        resp = client.get(
            f"/api/v1/service/suggestions/{ORDER_ID}",
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert len(body["data"]) == 1
    assert body["data"][0]["message"] == "推荐加单甜品"


# ──── 场景 11: POST /service/suggestions/{order_id}/{suggestion_type}/dismiss ──

def test_dismiss_suggestion_success():
    """忽略建议：返回 dismissed=suggestion_type。"""
    with patch("src.api.proactive_service_routes.dismiss_suggestion", return_value=None):
        client = TestClient(_make_proactive_app())
        resp = client.post(
            f"/api/v1/service/suggestions/{ORDER_ID}/upsell/dismiss",
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["dismissed"] == "upsell"


# ──── 场景 12: GET /orders/{order_id}/constraint-status — 三约束状态 ───────────

def test_get_constraint_status_success():
    """三约束状态查询：返回 margin/food_safety/service_time 三个子对象。"""
    with patch("src.api.proactive_service_routes.get_constraint_status",
               new=AsyncMock(return_value=_ConstraintStatusStub())):
        client = TestClient(_make_proactive_app())
        resp = client.get(
            f"/api/v1/orders/{ORDER_ID}/constraint-status",
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["margin"]["ok"] is True
    assert data["food_safety"]["ok"] is True
    assert data["service_time"]["elapsed_min"] == 25
    assert data["service_time"]["limit_min"] == 90


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION D: order_ops_routes.py
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# order_extensions 服务存根
_order_ext = _stub_module(
    "src.services.order_extensions",
    gift_dish            = AsyncMock(return_value={"gifted": True, "dish_id": "dish-001"}),
    split_order          = AsyncMock(return_value={"orders": ["order-A", "order-B"]}),
    merge_orders         = AsyncMock(return_value={"merged_order_id": "order-merged"}),
    request_order_change = AsyncMock(return_value={"change_id": "chg-001", "status": "pending"}),
    approve_order_change = AsyncMock(return_value={"change_id": "chg-001", "status": "approved"}),
)

# order_ops_routes 使用相对导入 `from ..services import order_extensions as ext`
# 注入到 src.services 命名空间
sys.modules["src.services.order_extensions"] = _order_ext

from src.api.order_ops_routes import router as _order_ops_router  # noqa: E402


def _make_order_ops_app(db_mock: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.include_router(_order_ops_router)

    from shared.ontology.src.database import get_db_with_tenant as _gwt

    async def _db_override():
        yield db_mock

    app.dependency_overrides[_gwt] = _db_override
    return app


# ──── 场景 13: POST /orders/{order_id}/gift — 赠菜成功 ────────────────────────

def test_gift_dish_success():
    """赠菜成功：ext.gift_dish 返回 gifted=True。"""
    db = _make_db()

    with patch("src.api.order_ops_routes.ext.gift_dish",
               new=AsyncMock(return_value={"gifted": True, "dish_id": "dish-001"})):
        app = _make_order_ops_app(db)
        client = TestClient(app)
        resp = client.post(
            f"/api/v1/orders/{ORDER_ID}/gift",
            json={
                "dish_id": "dish-001",
                "qty": 1,
                "reason": "顾客等待过久",
                "approver_id": "mgr-001",
            },
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["gifted"] is True


# ──── 场景 14: POST /orders/{order_id}/split — 拆单成功 ───────────────────────

def test_split_order_success():
    """拆单成功：返回拆分后的订单 ID 列表。"""
    db = _make_db()

    with patch("src.api.order_ops_routes.ext.split_order",
               new=AsyncMock(return_value={"orders": ["order-A", "order-B"]})):
        app = _make_order_ops_app(db)
        client = TestClient(app)
        resp = client.post(
            f"/api/v1/orders/{ORDER_ID}/split",
            json={"item_ids": [["item-001"], ["item-002", "item-003"]]},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert len(body["data"]["orders"]) == 2


# ──── 场景 15: POST /orders/merge — ValueError → 400 ──────────────────────────

def test_merge_orders_value_error():
    """并单时 ValueError（如两单不同桌）应返回 400。"""
    db = _make_db()

    with patch("src.api.order_ops_routes.ext.merge_orders",
               new=AsyncMock(side_effect=ValueError("订单不在同一桌台"))):
        app = _make_order_ops_app(db)
        client = TestClient(app)
        resp = client.post(
            "/api/v1/orders/merge",
            json={
                "source_order_id": str(uuid.uuid4()),
                "target_order_id": str(uuid.uuid4()),
            },
            headers=HEADERS,
        )

    assert resp.status_code == 400
    assert "订单不在同一桌台" in resp.json()["detail"]


# ──── 场景 16: PUT /orders/changes/{change_id}/approve — 审批成功 ──────────────

def test_approve_order_change_success():
    """改单审批通过：返回 status=approved。"""
    db = _make_db()
    change_id = str(uuid.uuid4())

    with patch("src.api.order_ops_routes.ext.approve_order_change",
               new=AsyncMock(return_value={"change_id": change_id, "status": "approved"})):
        app = _make_order_ops_app(db)
        client = TestClient(app)
        resp = client.put(
            f"/api/v1/orders/changes/{change_id}/approve",
            json={"approver_id": "mgr-001"},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "approved"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION E: supply_chain_mobile_routes.py
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 异常类
class _PurchaseOrderNotFoundError(Exception):
    pass

class _StocktakeAlreadyCompletedError(Exception):
    pass

class _StocktakeSessionNotFoundError(Exception):
    pass


# supply_chain_mobile_service 存根
_sc_svc = _stub_module(
    "src.services.supply_chain_mobile_service",
    PurchaseOrderNotFoundError    = _PurchaseOrderNotFoundError,
    StocktakeAlreadyCompletedError = _StocktakeAlreadyCompletedError,
    StocktakeSessionNotFoundError  = _StocktakeSessionNotFoundError,
    create_receiving_order  = AsyncMock(return_value={"order_id": "recv-001"}),
    confirm_receiving       = AsyncMock(return_value={"status": "confirmed", "order_id": "recv-001"}),
    get_receiving_history   = AsyncMock(return_value=[{"id": "recv-001", "supplier_name": "天府食材"}]),
    start_stocktake         = AsyncMock(return_value={"session_id": "stk-001", "status": "in_progress"}),
    record_count            = AsyncMock(return_value={"item_id": "item-001", "actual_qty": "10.5"}),
    complete_stocktake      = AsyncMock(return_value={"session_id": "stk-001", "status": "completed"}),
    get_stocktake_report    = AsyncMock(return_value={"session_id": "stk-001", "items": []}),
    get_pending_approvals   = AsyncMock(return_value=[{"id": "pur-001", "supplier": "天府食材"}]),
    approve_purchase        = AsyncMock(return_value={"purchase_id": "pur-001", "status": "approved"}),
)

from src.api.supply_chain_mobile_routes import router as _sc_router  # noqa: E402


def _make_sc_app(db_mock: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.include_router(_sc_router)

    async def _override():
        yield db_mock

    app.dependency_overrides[_get_db] = _override
    return app


# ──── 场景 17: POST /supply/receiving — 到货接收成功 ──────────────────────────

def test_create_receiving_success():
    """到货接收成功：create_receiving_order + confirm_receiving，返回 confirmed。"""
    db = _make_db()

    with patch("src.api.supply_chain_mobile_routes.create_receiving_order",
               new=AsyncMock(return_value={"order_id": "recv-001"})), \
         patch("src.api.supply_chain_mobile_routes.confirm_receiving",
               new=AsyncMock(return_value={"status": "confirmed", "order_id": "recv-001"})):
        app = _make_sc_app(db)
        client = TestClient(app)
        resp = client.post(
            "/api/v1/supply/receiving",
            json={
                "store_id": STORE_ID,
                "supplier_name": "天府食材",
                "items": [
                    {"ingredient_name": "猪肉", "received_qty": "5.0"}
                ],
            },
            headers={**HEADERS, "X-Tenant-ID": TENANT_ID},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "confirmed"


# ──── 场景 18: GET /supply/receiving/history — 到货历史查询 ───────────────────

def test_receiving_history_success():
    """到货历史查询成功：返回到货列表。"""
    db = _make_db()

    with patch("src.api.supply_chain_mobile_routes.get_receiving_history",
               new=AsyncMock(return_value=[{"id": "recv-001", "supplier_name": "天府食材"}])):
        app = _make_sc_app(db)
        client = TestClient(app)
        resp = client.get(
            "/api/v1/supply/receiving/history",
            params={"store_id": STORE_ID, "days": 7},
            headers={**HEADERS, "X-Tenant-ID": TENANT_ID},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert len(body["data"]) == 1
    assert body["data"][0]["supplier_name"] == "天府食材"


# ──── 场景 19: POST /supply/stocktake/start — 开始盘点 ────────────────────────

def test_start_stocktake_success():
    """开始盘点成功：返回 session_id 和 status=in_progress。"""
    db = _make_db()

    with patch("src.api.supply_chain_mobile_routes.start_stocktake",
               new=AsyncMock(return_value={"session_id": "stk-001", "status": "in_progress"})):
        app = _make_sc_app(db)
        client = TestClient(app)
        resp = client.post(
            "/api/v1/supply/stocktake/start",
            json={"store_id": STORE_ID, "category": "肉类", "initiated_by": "staff-001"},
            headers={**HEADERS, "X-Tenant-ID": TENANT_ID},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["session_id"] == "stk-001"
    assert body["data"]["status"] == "in_progress"


# ──── 场景 20: POST /supply/purchase/{purchase_id}/approve — PO 不存在 → 404 ──

def test_approve_purchase_not_found():
    """采购单不存在时 approve_purchase 抛 PurchaseOrderNotFoundError → 404。"""
    db = _make_db()

    with patch("src.api.supply_chain_mobile_routes.approve_purchase",
               new=AsyncMock(side_effect=_PurchaseOrderNotFoundError("采购单不存在"))), \
         patch("src.api.supply_chain_mobile_routes.PurchaseOrderNotFoundError",
               _PurchaseOrderNotFoundError):
        app = _make_sc_app(db)
        client = TestClient(app)
        resp = client.post(
            f"/api/v1/supply/purchase/pur-not-exist/approve",
            json={"approved": True},
            headers={**HEADERS, "X-Tenant-ID": TENANT_ID, "X-Staff-ID": "staff-001"},
        )

    assert resp.status_code == 404
    assert "采购单不存在" in resp.json()["detail"]
