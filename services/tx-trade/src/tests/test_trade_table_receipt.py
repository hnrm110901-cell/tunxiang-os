"""叫号屏 + 打印模板路由测试

覆盖文件：
  api/calling_screen_routes.py  — 3 个 REST 端点（5 个测试）
  api/print_template_routes.py  — 7 个端点（5 个测试）

场景清单：
calling_screen_routes
  1. GET /current — 正常路径，DB 返回叫号中订单
  2. GET /current — DB 无数据时返回 data=None
  3. GET /current — 缺少 X-Tenant-ID → 400
  4. GET /recent  — 正常路径，返回 items 列表
  5. GET /recent  — DB 抛 OperationalError → 500

print_template_routes
  6.  POST /weigh-ticket         — 正常生成 ESC/POS base64
  7.  POST /weigh-ticket         — service 抛 ValueError → 422
  8.  POST /banquet-notice       — 正常生成 ESC/POS base64
  9.  POST /live-seafood-receipt — 正常生成语义标记文本
  10. GET  /live-seafood-receipt/preview — 无需 tenant，返回 mock 内容
"""
import os
import sys
import types
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

# ─── 路径准备 ──────────────────────────────────────────────────────────────────

_TESTS_DIR = os.path.dirname(__file__)
_SRC_DIR   = os.path.join(_TESTS_DIR, "..")
_ROOT_DIR  = os.path.abspath(os.path.join(_TESTS_DIR, "..", "..", "..", ".."))

for _p in [_SRC_DIR, _ROOT_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ─── 建立 src 包层级（让相对导入能正确解析） ──────────────────────────────────────

def _ensure_pkg(name: str, path: str) -> None:
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = [path]
        mod.__package__ = name
        sys.modules[name] = mod


_ensure_pkg("src",           _SRC_DIR)
_ensure_pkg("src.api",       os.path.join(_SRC_DIR, "api"))
_ensure_pkg("src.services",  os.path.join(_SRC_DIR, "services"))
_ensure_pkg("src.utils",     os.path.join(_SRC_DIR, "utils"))

# ─── 注入 src.services.print_template_service 存根 ────────────────────────────

_pts_mod = types.ModuleType("src.services.print_template_service")
_pts_mod.generate_weigh_ticket         = MagicMock(return_value="MOCK_BASE64_WEIGH==")
_pts_mod.generate_banquet_notice       = MagicMock(return_value="MOCK_BASE64_BANQUET==")
_pts_mod.generate_credit_account_ticket = MagicMock(return_value="MOCK_BASE64_CREDIT==")
sys.modules["src.services.print_template_service"] = _pts_mod

# ─── 注入 src.utils.print_templates 存根 ──────────────────────────────────────

_put_mod = types.ModuleType("src.utils.print_templates")
_put_mod._mock_live_seafood_receipt = MagicMock(return_value={
    "store_name": "Mock门店", "table_no": "A8", "printed_at": "",
    "operator": "", "items": [], "total_fen": 0,
})
_put_mod._mock_banquet_notice = MagicMock(return_value={
    "store_name": "Mock宴席馆", "banquet_name": "婚宴", "session_no": 1,
    "table_count": 10, "party_size": 100, "arrive_time": "", "start_time": "",
    "printed_at": "", "contact_name": "", "contact_phone": "",
    "package_name": "", "sections": [], "special_notes": "", "dept": "热菜档口",
})
_put_mod.render_live_seafood_receipt = MagicMock(return_value="MOCK_SEAFOOD_CONTENT")
_put_mod.render_banquet_notice       = MagicMock(return_value="MOCK_BANQUET_CONTENT")
sys.modules["src.utils.print_templates"] = _put_mod

# ─── 加载路由 ─────────────────────────────────────────────────────────────────

from src.api.calling_screen_routes import router as cs_router  # type: ignore[import]  # noqa: E402
from src.api.print_template_routes  import router as pt_router  # type: ignore[import]  # noqa: E402
from shared.ontology.src.database   import get_db               # noqa: E402

# ─── 两个独立 FastAPI 应用 ──────────────────────────────────────────────────────

cs_app = FastAPI()
cs_app.include_router(cs_router)

pt_app = FastAPI()
pt_app.include_router(pt_router)

# ─── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID  = str(uuid.uuid4())
HEADERS   = {"X-Tenant-ID": TENANT_ID}

# ─── DB Mock 工具 ──────────────────────────────────────────────────────────────


class _FakeMappingResult:
    """模拟 db.execute() 返回对象，支持 .mappings().first() / __iter__"""

    def __init__(self, rows=None):
        self._rows = rows or []

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows

    def __iter__(self):
        return iter(self._rows)


def _make_db(*results):
    """db.execute 按顺序返回 results 中的各值。"""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=list(results))
    return db


def _override(db):
    """生成依赖覆盖函数。"""
    def _dep():
        return db
    return _dep


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ██ calling_screen_routes 测试（场景 1–5）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_calling_current_returns_calling_order():
    """场景1: GET /current — DB 有 calling 订单时正常返回"""
    mock_row = {
        "id": str(uuid.uuid4()),
        "call_number": "A023",
        "order_type": "quick",
        "status": "calling",
        "called_at": "2026-04-04T18:00:00+00:00",
        "created_at": "2026-04-04T17:55:00+00:00",
    }
    db = _make_db(_FakeMappingResult(rows=[mock_row]))

    cs_app.dependency_overrides[get_db] = _override(db)
    client = TestClient(cs_app)
    resp = client.get(
        f"/api/v1/calling-screen/{STORE_ID}/current",
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["call_number"] == "A023"
    assert body["data"]["status"] == "calling"


@pytest.mark.asyncio
async def test_calling_current_no_data_returns_none():
    """场景2: GET /current — DB 无 calling 订单时 data=None"""
    db = _make_db(_FakeMappingResult(rows=[]))

    cs_app.dependency_overrides[get_db] = _override(db)
    client = TestClient(cs_app)
    resp = client.get(
        f"/api/v1/calling-screen/{STORE_ID}/current",
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"] is None


def test_calling_current_missing_tenant_returns_400():
    """场景3: GET /current — 缺少 X-Tenant-ID header → 400"""
    db = AsyncMock()
    cs_app.dependency_overrides[get_db] = _override(db)
    client = TestClient(cs_app)
    resp = client.get(
        f"/api/v1/calling-screen/{STORE_ID}/current",
        # 故意不传 X-Tenant-ID
    )
    assert resp.status_code == 400
    assert "X-Tenant-ID" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_calling_recent_returns_items_list():
    """场景4: GET /recent — 正常路径返回 items 列表，total 与条数一致"""
    rows = [
        {
            "id": str(uuid.uuid4()),
            "call_number": f"A0{i:02d}",
            "order_type": "quick",
            "status": "completed" if i % 2 == 0 else "calling",
            "called_at": f"2026-04-04T18:0{i}:00+00:00",
            "completed_at": None,
            "created_at": f"2026-04-04T17:5{i}:00+00:00",
        }
        for i in range(3)
    ]
    db = _make_db(_FakeMappingResult(rows=rows))

    cs_app.dependency_overrides[get_db] = _override(db)
    client = TestClient(cs_app)
    resp = client.get(
        f"/api/v1/calling-screen/{STORE_ID}/recent?n=5",
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 3
    assert len(body["data"]["items"]) == 3
    assert body["data"]["items"][0]["call_number"] == "A000"


@pytest.mark.asyncio
async def test_calling_recent_db_error_raises_500():
    """场景5: GET /recent — DB 抛 OperationalError，路由无 fallback → 500"""
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=OperationalError("stmt", {}, Exception("connection refused"))
    )

    cs_app.dependency_overrides[get_db] = _override(db)
    client = TestClient(cs_app, raise_server_exceptions=False)
    resp = client.get(
        f"/api/v1/calling-screen/{STORE_ID}/recent",
        headers=HEADERS,
    )

    assert resp.status_code == 500


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ██ print_template_routes 测试（场景 6–10）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_WEIGH_BODY = {
    "store_name": "测试门店",
    "table_no": "A01",
    "waiter_name": "张三",
    "dish_name": "清蒸鲈鱼",
    "weight_gram": 650.0,
    "unit_price_fen": 5800,
    "price_unit": "500g",
    "amount_fen": 7540,
}

_BANQUET_BODY = {
    "session": {
        "store_name": "测试宴席馆",
        "contract_no": "HW20260404001",
        "customer_name": "李总",
        "customer_phone": "138****8888",
        "start_time": "2026-04-04T18:30:00",
        "table_count": 20,
        "pax_per_table": 10,
        "banquet_type": "婚宴",
    },
    "menu_sections": [],
}

_SEAFOOD_BODY = {
    "store_name": "鲜活海鲜馆",
    "table_no": "B12",
    "printed_at": "2026-04-04 18:35",
    "operator": "李四",
    "items": [
        {
            "dish_name": "活跳虾",
            "tank_zone": "A1鱼缸",
            "weight_kg": 0.8,
            "weight_jin": 1.6,
            "price_per_jin_fen": 8800,
            "total_fen": 14080,
            "note": "客户已验鱼",
        }
    ],
    "total_fen": 14080,
}


def test_weigh_ticket_normal_returns_base64():
    """场景6: POST /weigh-ticket — 正常路径返回 ESC/POS base64"""
    _pts_mod.generate_weigh_ticket.reset_mock()
    _pts_mod.generate_weigh_ticket.side_effect = None
    _pts_mod.generate_weigh_ticket.return_value = "MOCK_BASE64_WEIGH=="

    client = TestClient(pt_app)
    resp = client.post(
        "/api/v1/print/weigh-ticket",
        json=_WEIGH_BODY,
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["base64"] == "MOCK_BASE64_WEIGH=="
    assert body["data"]["content_type"] == "application/escpos"
    assert "清蒸鲈鱼" in body["data"]["description"]


def test_weigh_ticket_service_error_returns_422():
    """场景7: POST /weigh-ticket — service 抛 ValueError → 422"""
    _pts_mod.generate_weigh_ticket.side_effect = ValueError("称重数据异常：克数为负")

    client = TestClient(pt_app)
    resp = client.post(
        "/api/v1/print/weigh-ticket",
        json=_WEIGH_BODY,
        headers=HEADERS,
    )

    # 恢复正常返回值，避免污染后续测试
    _pts_mod.generate_weigh_ticket.side_effect = None
    _pts_mod.generate_weigh_ticket.return_value = "MOCK_BASE64_WEIGH=="

    assert resp.status_code == 422
    assert "称重单" in resp.json()["detail"]


def test_banquet_notice_normal_returns_base64():
    """场景8: POST /banquet-notice — 正常生成宴席通知单 ESC/POS base64"""
    _pts_mod.generate_banquet_notice.reset_mock()
    _pts_mod.generate_banquet_notice.side_effect = None
    _pts_mod.generate_banquet_notice.return_value = "MOCK_BASE64_BANQUET=="

    client = TestClient(pt_app)
    resp = client.post(
        "/api/v1/print/banquet-notice",
        json=_BANQUET_BODY,
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["base64"] == "MOCK_BASE64_BANQUET=="
    assert body["data"]["content_type"] == "application/escpos"


def test_live_seafood_receipt_normal_returns_content():
    """场景9: POST /live-seafood-receipt — 正常生成活鲜称重单语义标记文本"""
    _put_mod.render_live_seafood_receipt.reset_mock()
    _put_mod.render_live_seafood_receipt.side_effect = None
    _put_mod.render_live_seafood_receipt.return_value = "MOCK_SEAFOOD_CONTENT"

    client = TestClient(pt_app)
    resp = client.post(
        "/api/v1/print/live-seafood-receipt",
        json=_SEAFOOD_BODY,
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["content"] == "MOCK_SEAFOOD_CONTENT"
    assert body["data"]["printer_hint"] == "receipt"
    assert "B12" in body["data"]["description"]


def test_live_seafood_receipt_preview_no_tenant_required():
    """场景10: GET /live-seafood-receipt/preview — 无需 X-Tenant-ID，返回 mock 内容"""
    _put_mod.render_live_seafood_receipt.reset_mock()
    _put_mod.render_live_seafood_receipt.side_effect = None
    _put_mod.render_live_seafood_receipt.return_value = "MOCK_SEAFOOD_PREVIEW"
    _put_mod._mock_live_seafood_receipt.return_value = {
        "store_name": "Mock门店", "table_no": "T99", "printed_at": "",
        "operator": "", "items": [], "total_fen": 0,
    }

    client = TestClient(pt_app)
    resp = client.get(
        "/api/v1/print/live-seafood-receipt/preview?table_no=T99",
        # 故意不传 X-Tenant-ID — preview 端点无需认证
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["mock"] is True
    assert body["data"]["printer_hint"] == "receipt"
    assert "T99" in body["data"]["description"]
