"""门店经理 App 路由测试 — manager_app_routes.py DB版

覆盖场景（共 10 个）：
1.  GET  /api/v1/manager/realtime-kpi           — 正常聚合，返回 revenue_fen
2.  GET  /api/v1/manager/realtime-kpi?period=year — 非法 period → 422
3.  GET  /api/v1/manager/realtime-kpi           — SQLAlchemyError → graceful 零值
4.  GET  /api/v1/manager/alerts                 — 返回 ok=True + data=[]
5.  POST /api/v1/manager/alerts/{id}/read       — 返回 is_read=True + alert_id
6.  POST /api/v1/manager/discount/approve       — UPDATE RETURNING 成功，approved=True
7.  POST /api/v1/manager/discount/approve       — UPDATE RETURNING None → 404
8.  GET  /api/v1/manager/staff-online           — 返回 2 条员工，含 name 字段
9.  GET  /api/v1/manager/discount-requests      — 返回 1 条申请，含 status 字段
10. POST /api/v1/manager/broadcast-message      — 无 DB，返回 msg_id + sent_at
"""

import os
import sys
import types

# ─── 路径准备 ─────────────────────────────────────────────────────────────────
_TESTS_DIR = os.path.dirname(__file__)
_SRC_DIR = os.path.join(_TESTS_DIR, "..")
_ROOT_DIR = os.path.abspath(os.path.join(_TESTS_DIR, "..", "..", "..", ".."))

for _p in [_SRC_DIR, _ROOT_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ─── 建立 src 包层级 ──────────────────────────────────────────────────────────


def _ensure_pkg(name: str, path: str) -> None:
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = [path]
        mod.__package__ = name
        sys.modules[name] = mod


_ensure_pkg("src", _SRC_DIR)
_ensure_pkg("src.api", os.path.join(_SRC_DIR, "api"))

# ─── 导入 ─────────────────────────────────────────────────────────────────────

import datetime  # noqa: E402
from unittest.mock import AsyncMock, MagicMock  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from shared.ontology.src.database import get_db  # noqa: E402
from src.api.manager_app_routes import router  # type: ignore[import]  # noqa: E402

# ─── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_ID = "11111111-1111-1111-1111-111111111111"
STORE_ID = "22222222-2222-2222-2222-222222222222"
REQUEST_ID = "33333333-3333-3333-3333-333333333333"

HEADERS = {"X-Tenant-ID": TENANT_ID}

# ─── 工具函数 ──────────────────────────────────────────────────────────────────


def _make_mock_db() -> AsyncMock:
    """创建最小化的 mock AsyncSession。"""
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _fake_row(mapping: dict) -> MagicMock:
    """创建带 _mapping 属性的假行对象，支持键式访问。"""
    row = MagicMock()
    row._mapping = mapping
    row.__getitem__ = lambda self, key: self._mapping[key]
    return row


def _mappings_one_or_none(row) -> MagicMock:
    """辅助：result.mappings().one_or_none() = row。"""
    result = MagicMock()
    result.mappings.return_value.one_or_none.return_value = row
    return result


def _mappings_all(rows: list) -> MagicMock:
    """辅助：result.mappings().all() = rows。"""
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows
    return result


def _make_app_with_db(db: AsyncMock) -> FastAPI:
    """创建绑定了 mock DB 的独立测试 app。"""
    app = FastAPI()
    app.include_router(router)

    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    return app


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 1: GET /realtime-kpi — 正常聚合，返回 revenue_fen
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_realtime_kpi_today_success():
    """正常聚合：DB 返回营收行，响应含 revenue_fen 字段。"""
    db = _make_mock_db()

    set_cfg_result = MagicMock()
    agg_row = _fake_row(
        {
            "revenue_fen": 88000,
            "order_count": 12,
            "avg_check_fen": 7333,
        }
    )
    agg_result = _mappings_one_or_none(agg_row)

    db.execute = AsyncMock(side_effect=[set_cfg_result, agg_result])

    client = TestClient(_make_app_with_db(db))
    resp = client.get(
        "/api/v1/manager/realtime-kpi",
        params={"period": "today"},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "revenue_fen" in body["data"]
    assert body["data"]["revenue_fen"] == 88000
    assert body["data"]["order_count"] == 12
    assert body["data"]["period"] == "today"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 2: GET /realtime-kpi?period=year — 非法 period → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_realtime_kpi_invalid_period():
    """period=year 不在正则允许范围（today|week|month），FastAPI 返回 422。"""
    db = _make_mock_db()
    client = TestClient(_make_app_with_db(db))
    resp = client.get(
        "/api/v1/manager/realtime-kpi",
        params={"period": "year"},
        headers=HEADERS,
    )
    assert resp.status_code == 422
    # DB 不应被调用
    db.execute.assert_not_called()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 3: GET /realtime-kpi — SQLAlchemyError → graceful 零值降级
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_realtime_kpi_db_error():
    """DB 抛 SQLAlchemyError 时，端点不应崩溃，返回 ok=True + 零值数据。"""
    db = _make_mock_db()
    db.execute = AsyncMock(side_effect=SQLAlchemyError("db down"))

    client = TestClient(_make_app_with_db(db))
    resp = client.get(
        "/api/v1/manager/realtime-kpi",
        params={"period": "today"},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["revenue_fen"] == 0
    assert body["data"]["order_count"] == 0
    assert body["data"]["avg_check_fen"] == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 4: GET /alerts — 返回 ok=True + data=[]
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_get_alerts_returns_empty_list():
    """alerts 端点无 DB 调用，直接返回空列表。"""
    # 无 DB 依赖，直接构建 app（不注入 db override 也可）
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    resp = client.get("/api/v1/manager/alerts", headers=HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"] == []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 5: POST /alerts/{id}/read — 返回 is_read=True + alert_id
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_mark_alert_read():
    """标记预警已读（幂等，无 DB），返回 alert_id 和 is_read=True。"""
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    alert_id = "alert-abc-123"
    resp = client.post(f"/api/v1/manager/alerts/{alert_id}/read", headers=HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["alert_id"] == alert_id
    assert body["data"]["is_read"] is True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 6: POST /discount/approve — UPDATE RETURNING 成功，approved=True
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_discount_approve_success():
    """折扣审批成功：DB 先 set_config，再 UPDATE RETURNING 返回行。"""
    db = _make_mock_db()

    set_cfg_result = MagicMock()
    update_row = _fake_row({"id": REQUEST_ID, "status": "approved"})
    update_result = _mappings_one_or_none(update_row)

    # execute 会被调用两次：set_config + UPDATE RETURNING
    db.execute = AsyncMock(side_effect=[set_cfg_result, update_result])

    client = TestClient(_make_app_with_db(db))
    resp = client.post(
        "/api/v1/manager/discount/approve",
        json={
            "request_id": REQUEST_ID,
            "approved": True,
            "reason": "合规",
        },
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["approved"] is True
    assert body["data"]["status"] == "approved"
    db.commit.assert_awaited_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 7: POST /discount/approve — UPDATE RETURNING None → 404
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_discount_approve_not_found():
    """UPDATE RETURNING 返回 None（申请不存在）→ 404。"""
    db = _make_mock_db()

    set_cfg_result = MagicMock()
    update_result = _mappings_one_or_none(None)

    db.execute = AsyncMock(side_effect=[set_cfg_result, update_result])

    client = TestClient(_make_app_with_db(db))
    resp = client.post(
        "/api/v1/manager/discount/approve",
        json={
            "request_id": "99999999-9999-9999-9999-999999999999",
            "approved": False,
        },
        headers=HEADERS,
    )

    assert resp.status_code == 404


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 8: GET /staff-online — 返回 2 条员工，含 name 字段
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_staff_online_success():
    """在岗员工列表：DB 返回 2 条记录，验证 count 和 name 字段存在。"""
    db = _make_mock_db()

    set_cfg_result = MagicMock()
    emp1 = _fake_row({"id": "aaaa", "emp_name": "张三", "role": "cashier"})
    emp2 = _fake_row({"id": "bbbb", "emp_name": "李四", "role": "waiter"})
    select_result = _mappings_all([emp1, emp2])

    db.execute = AsyncMock(side_effect=[set_cfg_result, select_result])

    client = TestClient(_make_app_with_db(db))
    resp = client.get("/api/v1/manager/staff-online", headers=HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    staff = body["data"]
    assert len(staff) == 2
    # 验证字段结构
    assert "name" in staff[0]
    assert "role" in staff[0]
    assert staff[0]["name"] == "张三"
    assert staff[1]["name"] == "李四"
    assert staff[0]["status"] == "on_duty"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 9: GET /discount-requests — 返回 1 条申请，含 status 字段
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_get_discount_requests_success():
    """折扣申请列表：DB 返回 1 条记录，验证 status 字段存在。"""
    db = _make_mock_db()

    set_cfg_result = MagicMock()
    req_row = _fake_row(
        {
            "id": REQUEST_ID,
            "applicant": "王五",
            "applicant_role": "waiter",
            "table_label": "A03",
            "discount_type": "percent",
            "discount_amount": 10,
            "reason": "顾客投诉",
            "status": "pending",
            "manager_reason": None,
            "created_at": datetime.datetime(2026, 4, 4, 10, 0, 0),
        }
    )
    select_result = _mappings_all([req_row])

    db.execute = AsyncMock(side_effect=[set_cfg_result, select_result])

    client = TestClient(_make_app_with_db(db))
    resp = client.get("/api/v1/manager/discount-requests", headers=HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    items = body["data"]
    assert len(items) == 1
    assert "status" in items[0]
    assert items[0]["status"] == "pending"
    assert items[0]["applicant"] == "王五"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 10: POST /broadcast-message — 无 DB，返回 msg_id + sent_at
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_broadcast_message_success():
    """广播消息（无 DB），响应含 msg_id 和 sent_at 字段。"""
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/manager/broadcast-message",
        json={
            "store_id": STORE_ID,
            "message": "今日特价：红烧肉半价！",
            "target": "all",
        },
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert "msg_id" in data
    assert "sent_at" in data
    assert data["store_id"] == STORE_ID
    assert data["target"] == "all"
    assert data["message"] == "今日特价：红烧肉半价！"
