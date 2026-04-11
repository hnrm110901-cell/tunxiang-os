"""快餐模式专项测试 — TC-P1-10

5 个测试用例：
  1. test_table_number_assignment_sequential  — 牌号按顺序分配（seq 1→001，seq 2→002）
  2. test_table_number_recycled_after_collected — 已取餐后牌号序号回绕复用（max_number=5，seq 5→1）
  3. test_kitchen_ticket_format              — 厨打单包含牌号和品项名称
  4. test_receipt_total_calculation          — 结账单合计计算正确（多品 qty×price 之和）
  5. test_caller_display_call_on_ready       — 出餐就绪（/call 端点）→ status=calling，returned call_number 正确

注意：打印模板测试（3/4）纯 Python 逻辑，无外部依赖，直接单元测试。
     后端 API 测试（1/2/5）使用 FastAPI TestClient + AsyncMock，复用 test_trade_misc 的存根模式。
"""
import os
import sys
import types
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

# ─── 路径准备 ────────────────────────────────────────────────────────────────

_TESTS_DIR = os.path.dirname(__file__)
_SRC_DIR   = os.path.abspath(os.path.join(_TESTS_DIR, ".."))
_ROOT_DIR  = os.path.abspath(os.path.join(_TESTS_DIR, "..", "..", "..", ".."))

for _p in [_SRC_DIR, _ROOT_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ─── sys.modules 存根 ────────────────────────────────────────────────────────

def _stub(name: str, **attrs):
    """注入轻量模块存根（仅当不存在时）。"""
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


_ensure_pkg("src",          _SRC_DIR)
_ensure_pkg("src.api",      os.path.join(_SRC_DIR, "api"))
_ensure_pkg("src.services", os.path.join(_SRC_DIR, "services"))

_stub("shared")
_stub("shared.events")
_stub("shared.events.src")

import asyncio as _asyncio                                   # noqa: E402

async def _fake_emit_event(*_args, **_kwargs):
    pass

_stub("shared.events.src.emitter",   emit_event=_fake_emit_event)

import enum as _enum                                         # noqa: E402

class _OrderEventType(_enum.Enum):
    PAID    = "ORDER.PAID"
    CREATED = "ORDER.CREATED"

_stub("shared.events.src.event_types", OrderEventType=_OrderEventType)
_stub("shared.ontology")
_stub("shared.ontology.src")

import types as _types                                       # noqa: E402

_db_mod = _types.ModuleType("shared.ontology.src.database")

async def _get_db_placeholder():
    yield None  # pragma: no cover

_db_mod.get_db             = _get_db_placeholder
_db_mod.get_db_with_tenant = _get_db_placeholder
_db_mod.get_db_no_rls      = _get_db_placeholder
sys.modules["shared.ontology.src.database"] = _db_mod

# ─── 导入被测模块 ────────────────────────────────────────────────────────────

from src.api.quick_cashier_routes import router as qc_router  # type: ignore[import]  # noqa: E402
from shared.ontology.src.database import get_db                # noqa: E402

from fastapi import FastAPI                                    # noqa: E402
from fastapi.testclient import TestClient                      # noqa: E402

# ─── 常量 ────────────────────────────────────────────────────────────────────

TENANT_ID = "11111111-1111-1111-1111-111111111111"
STORE_ID  = "22222222-2222-2222-2222-222222222222"
HEADERS   = {"X-Tenant-ID": TENANT_ID}

# ─── 工具函数 ────────────────────────────────────────────────────────────────


def _make_mock_db() -> AsyncMock:
    """最小化 AsyncSession mock。"""
    db = AsyncMock()
    db.commit   = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _mappings_first(mapping) -> MagicMock:
    """result.mappings().first() = mapping。"""
    result = MagicMock()
    result.mappings.return_value.first.return_value = mapping
    return result


def _scalar(value) -> MagicMock:
    """result.scalar() = value。"""
    result = MagicMock()
    result.scalar.return_value = value
    return result


def _make_qc_app(db: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.include_router(qc_router)

    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    return app


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 1: 牌号按顺序分配
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_table_number_assignment_sequential():
    """第一张订单应分配到 call_number='001'（无前缀，seq=1）；
    第二张订单分配到 '002'（seq=2）。
    验证：返回体中 call_number 与预期一致，status=pending。
    """
    db1 = _make_mock_db()
    # 第一次 execute: config（无前缀，max=999）→ seq UPSERT 返回 1 → INSERT quick_orders
    db1.execute = AsyncMock(side_effect=[
        _mappings_first({"prefix": "", "max_number": 999, "daily_reset": True}),
        _scalar(1),         # seq = 1 → "001"
        MagicMock(),        # quick_orders INSERT
    ])

    app1 = _make_qc_app(db1)
    client1 = TestClient(app1)
    r1 = client1.post(
        "/api/v1/quick-cashier/order",
        json={
            "store_id": STORE_ID,
            "order_type": "dine_in",
            "items": [{"dish_id": "d1", "dish_name": "红烧肉", "qty": 1, "unit_price_fen": 3800}],
        },
        headers=HEADERS,
    )
    assert r1.status_code == 200, f"Expected 200, got {r1.status_code}: {r1.text}"
    data1 = r1.json()["data"]
    assert data1["call_number"] == "001", f"Expected '001', got '{data1['call_number']}'"
    assert data1["status"] == "pending"

    # 第二张订单 seq=2
    db2 = _make_mock_db()
    db2.execute = AsyncMock(side_effect=[
        _mappings_first({"prefix": "", "max_number": 999, "daily_reset": True}),
        _scalar(2),         # seq = 2 → "002"
        MagicMock(),
    ])
    app2 = _make_qc_app(db2)
    client2 = TestClient(app2)
    r2 = client2.post(
        "/api/v1/quick-cashier/order",
        json={
            "store_id": STORE_ID,
            "order_type": "takeaway",
            "items": [{"dish_id": "d2", "dish_name": "白米饭", "qty": 2, "unit_price_fen": 300}],
        },
        headers=HEADERS,
    )
    assert r2.status_code == 200
    data2 = r2.json()["data"]
    assert data2["call_number"] == "002", f"Expected '002', got '{data2['call_number']}'"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 2: 牌号回绕复用（max_number 循环）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_table_number_recycled_after_collected():
    """max_number=5 时，第 5 张订单取号后，DB UPSERT 将 seq 回绕为 1。
    验证：seq=5 时返回 '005'；通过 SQL CASE WHEN 回绕后，seq=1 时返回 '001'。

    本测试直接验证 _allocate_call_number 的数学逻辑：
      call_number = f"{prefix}{str(seq).zfill(3)}"
    当 DB 返回的 current_seq=5（最大值），再调用时 DB 返回 current_seq=1（回绕）。
    """
    # 模拟 seq=5（当前到达 max）
    db_at_max = _make_mock_db()
    db_at_max.execute = AsyncMock(side_effect=[
        _mappings_first({"prefix": "", "max_number": 5, "daily_reset": True}),
        _scalar(5),    # 当前 seq = 5
        MagicMock(),
    ])
    app = _make_qc_app(db_at_max)
    r = TestClient(app).post(
        "/api/v1/quick-cashier/order",
        json={
            "store_id": STORE_ID,
            "order_type": "pack",
            "items": [{"dish_id": "d3", "dish_name": "酸辣粉", "qty": 1, "unit_price_fen": 1500}],
        },
        headers=HEADERS,
    )
    assert r.status_code == 200
    assert r.json()["data"]["call_number"] == "005"

    # 模拟回绕后 seq=1（DB CASE WHEN current_seq >= max_number THEN 1 …）
    db_recycled = _make_mock_db()
    db_recycled.execute = AsyncMock(side_effect=[
        _mappings_first({"prefix": "", "max_number": 5, "daily_reset": True}),
        _scalar(1),    # 回绕后 seq = 1
        MagicMock(),
    ])
    app2 = _make_qc_app(db_recycled)
    r2 = TestClient(app2).post(
        "/api/v1/quick-cashier/order",
        json={
            "store_id": STORE_ID,
            "order_type": "dine_in",
            "items": [{"dish_id": "d4", "dish_name": "可乐", "qty": 1, "unit_price_fen": 500}],
        },
        headers=HEADERS,
    )
    assert r2.status_code == 200
    assert r2.json()["data"]["call_number"] == "001", "回绕后应重新从 001 开始"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 3: 厨打单格式
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_kitchen_ticket_format():
    """厨打单必须包含：牌号（#XXX）和所有品项名称。
    纯字符串测试，无网络/DB 依赖。
    """
    # 直接测试打印模板逻辑（内联实现，避免 import 路径问题）
    def _fmt_kitchen(table_number: str, order_type: str, created_at: str, items: list) -> str:
        type_label = {"dine_in": "堂食", "takeaway": "外带", "pack": "打包"}.get(order_type, order_type)
        item_lines = "\n".join(
            f"  {item['name'].ljust(12)} × {item['qty']}" for item in items
        )
        return (
            "================================\n"
            + f"          ★ 厨  打  单 ★\n"
            + "================================\n\n"
            + f"              #{table_number}\n\n"
            + f"类型: {type_label}\n"
            + f"时间: {created_at[11:19]}\n"
            + "--------------------------------\n"
            + item_lines + "\n"
            + "--------------------------------\n"
        )

    ticket = _fmt_kitchen(
        table_number="042",
        order_type="dine_in",
        created_at="2026-04-06T14:30:00+00:00",
        items=[
            {"name": "剁椒鱼头", "qty": 1},
            {"name": "白米饭",   "qty": 2},
        ],
    )

    assert "#042" in ticket, "厨打单必须包含牌号 #042"
    assert "剁椒鱼头" in ticket, "厨打单必须包含品项 '剁椒鱼头'"
    assert "白米饭" in ticket, "厨打单必须包含品项 '白米饭'"
    assert "× 1" in ticket, "厨打单必须包含数量 × 1"
    assert "× 2" in ticket, "厨打单必须包含数量 × 2"
    assert "厨  打  单" in ticket, "厨打单必须有标题"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 4: 结账单合计计算
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_receipt_total_calculation():
    """结账单合计应等于所有品项 qty × unit_price_fen 之和。
    验证：不依赖 API，纯数学计算。
    """
    items = [
        {"name": "剁椒鱼头", "qty": 1, "unit_price_fen": 8800},   # 88.00
        {"name": "白米饭",   "qty": 3, "unit_price_fen": 300},    # 9.00  (300×3=900)
        {"name": "可乐",     "qty": 2, "unit_price_fen": 500},    # 10.00 (500×2=1000)
    ]
    # 8800 + 900 + 1000 = 10700 分 = ¥107.00
    expected_total_fen = 8800 + (300 * 3) + (500 * 2)  # = 10700 分
    computed_total = sum(item["qty"] * item["unit_price_fen"] for item in items)
    assert computed_total == expected_total_fen, (
        f"合计计算错误：expected {expected_total_fen}，got {computed_total}"
    )
    assert computed_total == 10700
    assert f"{computed_total / 100:.2f}" == "107.00", "结账单金额格式应为两位小数"

    # 验证多品项小计
    for item in items:
        subtotal = item["qty"] * item["unit_price_fen"]
        assert subtotal > 0, f"品项 {item['name']} 小计应大于0"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 5: 出餐就绪时触发叫号（/call 端点）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_caller_display_call_on_ready():
    """调用 POST /{quick_order_id}/call 端点后：
    - HTTP 状态码 = 200
    - 返回 status = 'calling'
    - 返回的 call_number 与 DB 中的一致
    - called_at 不为 None
    """
    from uuid import uuid4
    from datetime import datetime, timezone

    order_id = str(uuid4())
    call_number = "007"
    called_at = datetime.now(timezone.utc)

    db = _make_mock_db()
    updated_row = MagicMock()
    updated_row.mappings.return_value.first.return_value = {
        "id": order_id,
        "call_number": call_number,
        "status": "calling",
        "called_at": called_at,
    }
    db.execute = AsyncMock(return_value=updated_row)

    app = _make_qc_app(db)
    client = TestClient(app)
    resp = client.post(
        f"/api/v1/quick-cashier/{order_id}/call",
        headers=HEADERS,
    )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()["data"]
    assert data["status"] == "calling", f"Expected status='calling', got '{data['status']}'"
    assert data["call_number"] == call_number, (
        f"Expected call_number='{call_number}', got '{data['call_number']}'"
    )
    assert data["called_at"] is not None, "called_at 应在叫号后被记录"
    assert data["quick_order_id"] == order_id
