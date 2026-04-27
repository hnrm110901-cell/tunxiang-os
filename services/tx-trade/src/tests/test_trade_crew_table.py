"""交接班与桌台布局路由测试

覆盖场景（共 12 个）：

crew_handover_router.py（4个）：
1.  GET  /api/v1/crew/shift-summary          — 正常获取班次摘要，返回 crew_id+revenue 等字段
2.  POST /api/v1/crew/handover               — 正常提交交班记录，返回 handover_id
3.  POST /api/v1/crew/handover               — crew_id 为空 → 400
4.  POST /api/v1/crew/handover               — DB commit 异常 → 500

table_layout_routes.py（8个）：
5.  GET  /api/v1/tables/layout/{store_id}/floors            — 正常返回楼层列表
6.  GET  /api/v1/tables/layout/{store_id}/floor/{floor_no}  — 正常返回楼层布局
7.  GET  /api/v1/tables/layout/{store_id}/floor/{floor_no}  — 布局不存在 → 404
8.  PUT  /api/v1/tables/layout/{store_id}/floor/{floor_no}  — 正常保存布局，返回新版本
9.  PUT  /api/v1/tables/layout/{store_id}/floor/{floor_no}  — 缺少 X-Tenant-ID → 400
10. GET  /api/v1/tables/status/{store_id}                   — 正常返回桌台实时状态
11. POST /api/v1/tables/{table_id}/transfer                 — 正常换台，返回 success=True
12. POST /api/v1/tables/{table_id}/transfer                 — 服务层抛 ValueError → 400
"""

import os
import sys
import types
import uuid

# ─── 路径准备 ─────────────────────────────────────────────────────────────────
_TESTS_DIR = os.path.dirname(__file__)
_SRC_DIR = os.path.abspath(os.path.join(_TESTS_DIR, ".."))
_ROOT_DIR = os.path.abspath(os.path.join(_TESTS_DIR, "..", "..", "..", ".."))

for _p in [_SRC_DIR, _ROOT_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ─── 包层级建立 ───────────────────────────────────────────────────────────────


def _ensure_pkg(name: str, path: str) -> None:
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = [path]
        mod.__package__ = name
        sys.modules[name] = mod


_ensure_pkg("src", _SRC_DIR)
_ensure_pkg("src.api", os.path.join(_SRC_DIR, "api"))
_ensure_pkg("src.routers", os.path.join(_SRC_DIR, "routers"))
_ensure_pkg("src.services", os.path.join(_SRC_DIR, "services"))


def _stub_module(full_name: str, **attrs):
    if full_name in sys.modules:
        return sys.modules[full_name]
    mod = types.ModuleType(full_name)
    mod.__package__ = full_name.rsplit(".", 1)[0] if "." in full_name else full_name
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[full_name] = mod
    return mod


# ─── 为 table_layout_routes 构建服务存根 ──────────────────────────────────────
# TableLayoutService 方法在路由测试中通过 patch 覆盖，
# 但需要先让 import 能成功，因此注入存根。


class _FakeTableLayoutService:
    def __init__(self, db):
        pass


_tls_mod = _stub_module(
    "src.services.table_layout_service",
    TableLayoutService=_FakeTableLayoutService,
    layout_connections={},
)

# ─── 正式导入 ──────────────────────────────────────────────────────────────────
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.ontology.src.database import get_db  # type: ignore
from src.api.crew_handover_router import router as crew_handover_router  # type: ignore
from src.api.table_layout_routes import router as table_layout_router  # type: ignore

# ─── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
STORE_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
TABLE_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
OPERATOR_ID = "op-001"
HEADERS = {"X-Tenant-ID": TENANT_ID}


# ─── 工具函数 ──────────────────────────────────────────────────────────────────


def _make_mock_db() -> AsyncMock:
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())
    return db


def _make_app_crew(db: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.include_router(crew_handover_router)

    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    return app


def _make_app_table(db: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.include_router(table_layout_router)

    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    return app


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 1: GET /api/v1/crew/shift-summary — 正常获取班次摘要
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_get_shift_summary_success():
    """GET /crew/shift-summary：返回当前服务员本班摘要，含 crew_id、revenue 等字段。"""
    db = _make_mock_db()
    client = TestClient(_make_app_crew(db))
    resp = client.get(
        "/api/v1/crew/shift-summary",
        params={"store_id": STORE_ID},
        headers={**HEADERS, "X-Operator-ID": OPERATOR_ID},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert "crew_id" in data
    assert "table_count" in data
    assert "revenue" in data
    assert "generated_at" in data


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 2: POST /api/v1/crew/handover — 正常提交交班记录
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_submit_handover_success():
    """POST /crew/handover：正常提交，返回 handover_id + message='交班完成'。"""
    db = _make_mock_db()
    client = TestClient(_make_app_crew(db))
    payload = {
        "crew_id": "crew-001",
        "notes": "今日无特殊事项",
        "shift_summary_data": {
            "table_count": 12,
            "order_count": 25,
            "revenue": 456700,
            "bell_responses": 8,
            "complaints": 0,
            "good_reviews": 3,
        },
    }
    resp = client.post(
        "/api/v1/crew/handover",
        json=payload,
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert "handover_id" in data
    assert data["crew_id"] == "crew-001"
    assert data["message"] == "交班完成"
    # 确认 DB commit 被调用
    db.commit.assert_awaited_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 3: POST /api/v1/crew/handover — crew_id 为空 → 400
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_submit_handover_empty_crew_id():
    """crew_id 为空字符串时，路由层应返回 400 Bad Request。"""
    db = _make_mock_db()
    client = TestClient(_make_app_crew(db))
    payload = {
        "crew_id": "",
        "notes": "",
        "shift_summary_data": {
            "table_count": 0,
            "order_count": 0,
            "revenue": 0,
            "bell_responses": 0,
            "complaints": 0,
            "good_reviews": 0,
        },
    }
    resp = client.post(
        "/api/v1/crew/handover",
        json=payload,
        headers=HEADERS,
    )
    assert resp.status_code == 400
    assert "crew_id" in resp.json()["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 4: POST /api/v1/crew/handover — DB commit 异常 → 500
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_submit_handover_db_error():
    """DB commit 时抛出异常，路由应返回 500。"""
    db = _make_mock_db()
    db.commit = AsyncMock(side_effect=RuntimeError("DB unavailable"))
    client = TestClient(_make_app_crew(db), raise_server_exceptions=False)
    payload = {
        "crew_id": "crew-002",
        "notes": "",
        "shift_summary_data": {
            "table_count": 5,
            "order_count": 10,
            "revenue": 120000,
            "bell_responses": 3,
            "complaints": 0,
            "good_reviews": 1,
        },
    }
    resp = client.post(
        "/api/v1/crew/handover",
        json=payload,
        headers=HEADERS,
    )
    assert resp.status_code == 500
    assert "服务器内部错误" in resp.json()["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 桌台布局 mock 辅助
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _make_fake_floor_summary():
    """构造一个 TableLayoutSummary mock 对象。"""
    m = MagicMock()
    m.model_dump.return_value = {
        "floor_no": 1,
        "floor_name": "一楼大厅",
        "table_count": 10,
        "version": 3,
    }
    return m


def _make_fake_layout():
    """构造一个 TableLayout mock 对象。"""
    m = MagicMock()
    m.model_dump.return_value = {
        "id": str(uuid.uuid4()),
        "store_id": STORE_ID,
        "floor_no": 1,
        "floor_name": "一楼大厅",
        "canvas_width": 1200,
        "canvas_height": 800,
        "layout_json": {"tables": [], "walls": [], "areas": []},
        "version": 3,
        "published_at": None,
    }
    return m


def _make_fake_table_status():
    m = MagicMock()
    m.model_dump.return_value = {
        "table_db_id": str(uuid.uuid4()),
        "table_number": "A01",
        "status": "occupied",
        "order_id": str(uuid.uuid4()),
        "order_no": "TX20260405001",
        "seated_at": None,
        "seated_duration_min": 30,
        "guest_count": 4,
        "current_amount_fen": 18800,
    }
    return m


def _make_fake_transfer_result():
    m = MagicMock()
    m.model_dump.return_value = {
        "order_id": str(uuid.uuid4()),
        "from_table_id": TABLE_ID,
        "to_table_id": str(uuid.uuid4()),
        "success": True,
    }
    return m


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 5: GET /api/v1/tables/layout/{store_id}/floors — 正常返回楼层列表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_get_floors_success():
    """GET /tables/layout/{store_id}/floors：返回门店楼层摘要列表。"""
    db = _make_mock_db()
    fake_floor = _make_fake_floor_summary()

    with patch("src.api.table_layout_routes.TableLayoutService") as MockSvc:
        instance = MockSvc.return_value
        instance.get_all_floors = AsyncMock(return_value=[fake_floor])

        client = TestClient(_make_app_table(db))
        resp = client.get(
            f"/api/v1/tables/layout/{STORE_ID}/floors",
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    floors = body["data"]
    assert len(floors) == 1
    assert floors[0]["floor_name"] == "一楼大厅"
    assert floors[0]["version"] == 3


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 6: GET /api/v1/tables/layout/{store_id}/floor/{floor_no} — 正常返回布局
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_get_floor_layout_success():
    """GET /tables/layout/{store_id}/floor/1：返回指定楼层完整布局。"""
    db = _make_mock_db()
    fake_layout = _make_fake_layout()

    with patch("src.api.table_layout_routes.TableLayoutService") as MockSvc:
        instance = MockSvc.return_value
        instance.get_layout = AsyncMock(return_value=fake_layout)

        client = TestClient(_make_app_table(db))
        resp = client.get(
            f"/api/v1/tables/layout/{STORE_ID}/floor/1",
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["floor_no"] == 1
    assert data["canvas_width"] == 1200


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 7: GET /floor/{floor_no} — 布局不存在 → 404
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_get_floor_layout_not_found():
    """服务层返回 None 时，路由应返回 404（布局不存在）。"""
    db = _make_mock_db()

    with patch("src.api.table_layout_routes.TableLayoutService") as MockSvc:
        instance = MockSvc.return_value
        instance.get_layout = AsyncMock(return_value=None)

        client = TestClient(_make_app_table(db))
        resp = client.get(
            f"/api/v1/tables/layout/{STORE_ID}/floor/99",
            headers=HEADERS,
        )

    assert resp.status_code == 404


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 8: PUT /api/v1/tables/layout/{store_id}/floor/{floor_no} — 保存成功
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_upsert_floor_layout_success():
    """PUT /tables/layout/{store_id}/floor/1：保存布局，版本号自动递增。"""
    db = _make_mock_db()
    fake_layout = _make_fake_layout()

    with patch("src.api.table_layout_routes.TableLayoutService") as MockSvc:
        instance = MockSvc.return_value
        instance.upsert_layout = AsyncMock(return_value=fake_layout)

        client = TestClient(_make_app_table(db))
        resp = client.put(
            f"/api/v1/tables/layout/{STORE_ID}/floor/1",
            json={
                "floor_name": "一楼大厅",
                "layout_json": {"tables": [], "walls": [], "areas": []},
                "published_by": str(uuid.uuid4()),
            },
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["floor_no"] == 1


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 9: PUT /tables/layout — 缺少 X-Tenant-ID → 400
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_upsert_floor_layout_missing_tenant_id():
    """缺少 X-Tenant-ID header 时应返回 400。"""
    db = _make_mock_db()
    client = TestClient(_make_app_table(db))
    resp = client.put(
        f"/api/v1/tables/layout/{STORE_ID}/floor/1",
        json={
            "floor_name": "一楼大厅",
            "layout_json": {"tables": [], "walls": [], "areas": []},
            "published_by": str(uuid.uuid4()),
        },
        # 不传 headers=HEADERS
    )
    assert resp.status_code == 400


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 10: GET /api/v1/tables/status/{store_id} — 返回桌台实时状态
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_get_realtime_status_success():
    """GET /tables/status/{store_id}：返回全店桌台实时状态列表。"""
    db = _make_mock_db()
    fake_status = _make_fake_table_status()

    with patch("src.api.table_layout_routes.TableLayoutService") as MockSvc:
        instance = MockSvc.return_value
        instance.get_realtime_status = AsyncMock(return_value=[fake_status])

        client = TestClient(_make_app_table(db))
        resp = client.get(
            f"/api/v1/tables/status/{STORE_ID}",
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    statuses = body["data"]
    assert len(statuses) == 1
    assert statuses[0]["table_number"] == "A01"
    assert statuses[0]["status"] == "occupied"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 11: POST /api/v1/tables/{table_id}/transfer — 正常换台
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_transfer_table_success():
    """POST /tables/{table_id}/transfer：将订单换到另一桌，返回 success=True。"""
    db = _make_mock_db()
    fake_result = _make_fake_transfer_result()

    with patch("src.api.table_layout_routes.TableLayoutService") as MockSvc:
        instance = MockSvc.return_value
        instance.transfer_table = AsyncMock(return_value=fake_result)

        client = TestClient(_make_app_table(db))
        resp = client.post(
            f"/api/v1/tables/{TABLE_ID}/transfer",
            json={
                "to_table_id": str(uuid.uuid4()),
                "order_id": str(uuid.uuid4()),
                "operator_id": str(uuid.uuid4()),
            },
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["success"] is True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 12: POST /tables/{table_id}/transfer — 服务层抛 ValueError → 400
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_transfer_table_value_error():
    """服务层抛 ValueError 时（如目标桌已有订单），路由应返回 400。"""
    db = _make_mock_db()

    with patch("src.api.table_layout_routes.TableLayoutService") as MockSvc:
        instance = MockSvc.return_value
        instance.transfer_table = AsyncMock(side_effect=ValueError("目标桌台已有进行中的订单"))

        client = TestClient(_make_app_table(db))
        resp = client.post(
            f"/api/v1/tables/{TABLE_ID}/transfer",
            json={
                "to_table_id": str(uuid.uuid4()),
                "order_id": str(uuid.uuid4()),
                "operator_id": str(uuid.uuid4()),
            },
            headers=HEADERS,
        )

    assert resp.status_code == 400
