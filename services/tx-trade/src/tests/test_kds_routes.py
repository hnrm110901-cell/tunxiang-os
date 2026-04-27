"""KDS 出餐屏路由测试 — kds_routes.py

覆盖场景（共 10 个）：
GET  端点（2个）：
1.  GET  /api/v1/kds/tasks?dept_id=xxx       — 正常查询，返回 items+total+page+size
2.  GET  /api/v1/kds/overview/{store_id}    — 全店概览正常返回 depts 列表
3.  GET  /api/v1/kds/task/{task_id}/rush/status — 正常催菜SLA状态查询

POST/写入 端点（4个）：
4.  POST /api/v1/kds/dispatch/{order_id}    — 分单成功，返回 dept_tasks
5.  POST /api/v1/kds/task/{task_id}/start   — 开始制作成功
6.  POST /api/v1/kds/task/{task_id}/finish  — 完成出品成功
7.  POST /api/v1/kds/task/{task_id}/rush    — 催菜成功

404/DB错误 端点（3个）：
8.  GET  /api/v1/kds/tasks                  — 缺少 X-Tenant-ID → 400
9.  GET  /api/v1/kds/task/{task_id}/rush/status — task_id非法UUID → 400
10. POST /api/v1/kds/task/{task_id}/finish  — 服务层抛 HTTPException(404)
"""

import os
import sys
import types

# ─── 路径准备 ─────────────────────────────────────────────────────────────────
_TESTS_DIR = os.path.dirname(__file__)
_SRC_DIR = os.path.abspath(os.path.join(_TESTS_DIR, ".."))
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


# ─── stub services (kds_routes 依赖的服务模块) ─────────────────────────────────
# 以避免真实 import 链触发数据库/外部依赖


def _stub_module(full_name: str, **attrs):
    """注入一个最小存根模块到 sys.modules，避免真实导入失败。"""
    if full_name in sys.modules:
        return sys.modules[full_name]
    mod = types.ModuleType(full_name)
    mod.__package__ = full_name.rsplit(".", 1)[0] if "." in full_name else full_name
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[full_name] = mod
    return mod


# cooking_scheduler
_stub_module(
    "src.services.cooking_scheduler",
    calculate_cooking_order=None,
    get_dept_load=None,
)

# cooking_timeout
_stub_module(
    "src.services.cooking_timeout",
    check_timeouts=None,
    get_timeout_config=None,
)

# kds_actions
_stub_module(
    "src.services.kds_actions",
    check_rush_overdue=None,
    confirm_rush=None,
    finish_cooking=None,
    get_task_timeline=None,
    report_shortage=None,
    request_remake=None,
    request_rush=None,
    start_cooking=None,
)

# kds_dispatch
_stub_module(
    "src.services.kds_dispatch",
    dispatch_order_to_kds=None,
    get_dept_queue=None,
    get_kds_tasks_by_dept=None,
    get_store_kds_overview=None,
    resolve_dept_for_dish=None,
)

# models/kds_task（被 rush/status 端点内部 import）
# 必须是真实 SQLAlchemy 声明式模型，因为端点内部执行 select(KDSTask)
from sqlalchemy import Integer, String
from sqlalchemy.orm import DeclarativeBase, mapped_column


class _TestBase(DeclarativeBase):
    pass


class _FakeKDSTask(_TestBase):
    """最小化 KDSTask 存根，让 select(KDSTask) 能正常构造 SQL 语句。"""

    __tablename__ = "kds_tasks"
    id = mapped_column(Integer, primary_key=True)
    tenant_id = mapped_column(Integer)
    is_deleted = mapped_column(Integer)
    status = mapped_column(String)
    rush_count = mapped_column(Integer)
    last_rush_at = mapped_column(Integer)
    promised_at = mapped_column(Integer)


_kds_task_mod = _stub_module("src.models.kds_task")
_kds_task_mod.KDSTask = _FakeKDSTask  # type: ignore[attr-defined]

# ─── 正式导入 ──────────────────────────────────────────────────────────────────
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from shared.ontology.src.database import get_db  # noqa: E402
from src.api.kds_routes import router  # type: ignore[import]

# ─── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
STORE_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
DEPT_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
ORDER_ID = "dddddddd-dddd-dddd-dddd-dddddddddddd"
TASK_ID = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
DISH_ID = "ffffffff-ffff-ffff-ffff-ffffffffffff"

HEADERS = {"X-Tenant-ID": TENANT_ID}


# ─── 工具函数 ──────────────────────────────────────────────────────────────────


def _make_mock_db() -> AsyncMock:
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())
    return db


def _make_app_with_db(db: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.include_router(router)

    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    return app


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 1: GET /tasks?dept_id=xxx — 正常查询返回 items+total+page+size
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_get_kds_tasks_success():
    """KDS任务查询：按档口返回 pending+cooking 任务列表，含分页信息。"""
    db = _make_mock_db()

    fake_task = {
        "id": TASK_ID,
        "status": "pending",
        "dish_name": "宫保鸡丁",
        "quantity": 2,
        "priority": "normal",
    }

    with patch(
        "src.api.kds_routes.get_kds_tasks_by_dept",
        new=AsyncMock(return_value=([fake_task], 1)),
    ):
        client = TestClient(_make_app_with_db(db))
        resp = client.get(
            "/api/v1/kds/tasks",
            params={"dept_id": DEPT_ID, "status": "pending", "page": 1, "size": 20},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["total"] == 1
    assert data["page"] == 1
    assert data["size"] == 20
    assert len(data["items"]) == 1
    assert data["items"][0]["dish_name"] == "宫保鸡丁"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 2: GET /overview/{store_id} — 全店概览正常返回 depts 列表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_get_store_overview_success():
    """全店概览：返回所有档口实时负载，含 depts 数组和 total。"""
    db = _make_mock_db()

    fake_overview = [
        {"dept_id": DEPT_ID, "dept_name": "热菜间", "pending": 3, "cooking": 1},
        {"dept_id": str(uuid.uuid4()), "dept_name": "凉菜间", "pending": 0, "cooking": 0},
    ]

    with patch(
        "src.api.kds_routes.get_store_kds_overview",
        new=AsyncMock(return_value=fake_overview),
    ):
        client = TestClient(_make_app_with_db(db))
        resp = client.get(
            f"/api/v1/kds/overview/{STORE_ID}",
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["total"] == 2
    assert len(data["depts"]) == 2
    assert data["depts"][0]["dept_name"] == "热菜间"
    assert data["depts"][0]["pending"] == 3


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 3: GET /task/{task_id}/rush/status — 正常催菜SLA状态查询
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_rush_status_success():
    """催菜SLA状态：任务存在，返回 rush_count、is_overdue 等字段。"""
    db = _make_mock_db()

    now = datetime.now(timezone.utc)

    fake_task = MagicMock()
    fake_task.status = "cooking"
    fake_task.rush_count = 1
    fake_task.last_rush_at = now - timedelta(minutes=5)
    fake_task.promised_at = now + timedelta(minutes=10)  # 未超时

    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = fake_task

    # execute 被调用一次（SELECT KDSTask）
    db.execute = AsyncMock(return_value=scalar_result)

    client = TestClient(_make_app_with_db(db))
    resp = client.get(
        f"/api/v1/kds/task/{TASK_ID}/rush/status",
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["task_id"] == TASK_ID
    assert data["status"] == "cooking"
    assert data["rush_count"] == 1
    assert data["is_overdue"] is False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 4: POST /dispatch/{order_id} — 分单成功，返回 dept_tasks
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_dispatch_order_success():
    """分单：将订单菜品分配到档口，返回 dept_tasks（已排序）。"""
    db = _make_mock_db()

    fake_dept_tasks = [
        {
            "dept_id": DEPT_ID,
            "dept_name": "热菜间",
            "items": [{"dish_id": DISH_ID, "item_name": "红烧肉", "quantity": 1}],
        }
    ]
    fake_dispatch_result = {"dept_tasks": fake_dept_tasks}
    fake_sorted_tasks = fake_dept_tasks  # 排序后相同

    with (
        patch(
            "src.api.kds_routes.dispatch_order_to_kds",
            new=AsyncMock(return_value=fake_dispatch_result),
        ),
        patch(
            "src.api.kds_routes.calculate_cooking_order",
            new=AsyncMock(return_value=fake_sorted_tasks),
        ),
    ):
        client = TestClient(_make_app_with_db(db))
        resp = client.post(
            f"/api/v1/kds/dispatch/{ORDER_ID}",
            json={
                "items": [
                    {
                        "dish_id": DISH_ID,
                        "item_name": "红烧肉",
                        "quantity": 1,
                        "order_item_id": str(uuid.uuid4()),
                        "notes": None,
                    }
                ],
                "table_number": "A08",
                "order_no": "T20260404001",
            },
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    dept_tasks = body["data"]["dept_tasks"]
    assert len(dept_tasks) == 1
    assert dept_tasks[0]["dept_name"] == "热菜间"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 5: POST /task/{task_id}/start — 开始制作成功
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_start_cooking_success():
    """开始制作：厨师点击开始，任务状态变为 cooking，返回服务层结果。"""
    db = _make_mock_db()

    fake_result = {
        "ok": True,
        "data": {
            "task_id": TASK_ID,
            "status": "cooking",
            "started_at": datetime.now(timezone.utc).isoformat(),
        },
    }

    with patch(
        "src.api.kds_routes.start_cooking",
        new=AsyncMock(return_value=fake_result),
    ):
        client = TestClient(_make_app_with_db(db))
        resp = client.post(
            f"/api/v1/kds/task/{TASK_ID}/start",
            headers={**HEADERS, "X-Operator-ID": "chef_001"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "cooking"
    assert body["data"]["task_id"] == TASK_ID


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 6: POST /task/{task_id}/finish — 完成出品成功
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_finish_cooking_success():
    """完成出品：KDS 确认菜品已端出，任务状态变为 done。"""
    db = _make_mock_db()

    fake_result = {
        "ok": True,
        "data": {
            "task_id": TASK_ID,
            "status": "done",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "duration_sec": 420,
        },
    }

    with patch(
        "src.api.kds_routes.finish_cooking",
        new=AsyncMock(return_value=fake_result),
    ):
        client = TestClient(_make_app_with_db(db))
        resp = client.post(
            f"/api/v1/kds/task/{TASK_ID}/finish",
            headers={**HEADERS, "X-Operator-ID": "chef_002"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "done"
    assert body["data"]["duration_sec"] == 420


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 7: POST /task/{task_id}/rush — 催菜成功
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_request_rush_success():
    """催菜：服务员发起催单，推送到 KDS 和打印机，返回 ok=True。"""
    db = _make_mock_db()

    fake_result = {
        "ok": True,
        "data": {
            "task_id": TASK_ID,
            "dish_id": DISH_ID,
            "rush_count": 1,
            "pushed": True,
        },
    }

    with patch(
        "src.api.kds_routes.request_rush",
        new=AsyncMock(return_value=fake_result),
    ):
        client = TestClient(_make_app_with_db(db))
        resp = client.post(
            f"/api/v1/kds/task/{TASK_ID}/rush",
            json={"dish_id": DISH_ID},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["rush_count"] == 1
    assert body["data"]["pushed"] is True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 8: GET /tasks — 缺少 X-Tenant-ID → 400
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_get_kds_tasks_missing_tenant_id():
    """缺少 X-Tenant-ID header 时，_get_tenant_id 抛 400 BadRequest。"""
    db = _make_mock_db()
    client = TestClient(_make_app_with_db(db))

    # 不传 X-Tenant-ID
    resp = client.get(
        "/api/v1/kds/tasks",
        params={"dept_id": DEPT_ID},
        # 故意不传 headers=HEADERS
    )

    assert resp.status_code == 400
    body = resp.json()
    assert "X-Tenant-ID" in body["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 9: GET /task/{task_id}/rush/status — task_id 非法 UUID → 400
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_rush_status_invalid_task_id():
    """task_id 不是合法 UUID 时，端点返回 400（无效 task_id）。"""
    db = _make_mock_db()
    client = TestClient(_make_app_with_db(db))

    resp = client.get(
        "/api/v1/kds/task/not-a-valid-uuid/rush/status",
        headers=HEADERS,
    )

    assert resp.status_code == 400
    body = resp.json()
    # 返回的 detail 中应含"无效"关键字
    assert "无效" in body["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 10: POST /task/{task_id}/finish — 服务层抛 HTTPException(404)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_finish_cooking_task_not_found():
    """完成出品：服务层找不到任务时抛 HTTPException(404)，端点透传 404。"""
    db = _make_mock_db()

    async def _raise_404(task_id, operator_id, db):
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")

    with patch(
        "src.api.kds_routes.finish_cooking",
        new=_raise_404,
    ):
        client = TestClient(_make_app_with_db(db))
        resp = client.post(
            f"/api/v1/kds/task/{TASK_ID}/finish",
            headers=HEADERS,
            # raise_server_exceptions=False 让 TestClient 返回 HTTP 响应而非重新抛异常
        )

    assert resp.status_code == 404
    body = resp.json()
    assert "不存在" in body["detail"]
