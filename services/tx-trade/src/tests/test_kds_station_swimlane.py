"""KDS 档口毛利路由 + 泳道路由测试

覆盖场景（共 12 个）：

kds_station_profit_routes（依赖 src.services.kds_station_profit）：
1.  GET /api/v1/kds/station-profit?store_id=xxx&period=today   — 正常返回 depts 汇总
2.  GET /api/v1/kds/station-profit?period=week                 — week 周期正常计算
3.  GET /api/v1/kds/station-profit?period=month                — month 周期正常计算
4.  GET /api/v1/kds/station-profit?start_date=&end_date=       — 自定义日期区间优先
5.  GET /api/v1/kds/station-profit — 无档口数据时返回空 depts + 0 合计

kds_swimlane_routes（依赖 src.services.kds_swimlane 服务层）：
6.  GET  /api/v1/kds/swimlane/board?dept_id=xxx               — 正常返回 steps + lanes
7.  GET  /api/v1/kds/swimlane/board?dept_id=xxx               — 无工序时返回空看板
8.  GET  /api/v1/kds/swimlane/steps?dept_id=xxx               — 正常返回工序列表
9.  POST /api/v1/kds/swimlane/steps — 新建工序，返回 created=True
10. POST /api/v1/kds/swimlane/steps — 更新现有工序，返回 updated=True
11. POST /api/v1/kds/swimlane/tasks/{task_id}/advance — 推进工序成功，all_done=False
12. POST /api/v1/kds/swimlane/tasks/{task_id}/advance — 最后一道工序，all_done=True
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
_ensure_pkg("src.services", os.path.join(_SRC_DIR, "services"))
_ensure_pkg("src.models", os.path.join(_SRC_DIR, "models"))


# ─── stub helper ──────────────────────────────────────────────────────────────


def _stub_module(full_name: str, **attrs):
    if full_name in sys.modules:
        return sys.modules[full_name]
    mod = types.ModuleType(full_name)
    mod.__package__ = full_name.rsplit(".", 1)[0] if "." in full_name else full_name
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[full_name] = mod
    return mod


# ─── stub src.db（两个路由都 from ..db import get_db）────────────────────────
_db_mod = _stub_module("src.db", get_db=lambda: None)

# ─── stub 服务层 ───────────────────────────────────────────────────────────────
_stub_module(
    "src.services.kds_station_profit",
    get_station_profit_summary=None,
    get_station_profit_report=None,
)
_stub_module(
    "src.services.kds_swimlane",
    advance_step=None,
    get_steps_for_dept=None,
    get_swimlane_board=None,
    upsert_step=None,
)

# ─── stub models（服务层依赖，路由层不直接使用）────────────────────────────────
_stub_module("src.models.kds_task", KDSTask=None)
_stub_module("src.models.kds_task_step", KDSTaskStep=None)
_stub_module("src.models.production_step", ProductionStep=None)

# ─── 正式导入 ──────────────────────────────────────────────────────────────────
import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.kds_station_profit_routes import router as profit_router  # type: ignore[import]
from src.api.kds_swimlane_routes import router as swimlane_router  # type: ignore[import]
from src.db import get_db as src_get_db  # type: ignore[import]

# ─── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
STORE_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
DEPT_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
TASK_ID = "dddddddd-dddd-dddd-dddd-dddddddddddd"
STEP_ID = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
NEXT_STEP = "ffffffff-ffff-ffff-ffff-ffffffffffff"

HEADERS = {"X-Tenant-ID": TENANT_ID}


# ─── 工具函数 ──────────────────────────────────────────────────────────────────


def _make_mock_db() -> AsyncMock:
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())
    return db


def _make_profit_app(db: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.include_router(profit_router)

    async def _override():
        yield db

    app.dependency_overrides[src_get_db] = _override
    return app


def _make_swimlane_app(db: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.include_router(swimlane_router)

    async def _override():
        yield db

    app.dependency_overrides[src_get_db] = _override
    return app


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 1: GET /station-profit?period=today — 正常返回 depts 汇总
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_station_profit_today_success():
    """档口毛利报表：today 周期，2个档口，校验 total_revenue 及毛利颜色语义。"""
    db = _make_mock_db()

    fake_summary = {
        "total_revenue": 15000.0,
        "total_profit": 9500.0,
        "avg_margin_pct": 63.3,
        "depts": [
            {
                "dept_id": DEPT_ID,
                "dept_name": "热菜间",
                "dish_count": 80,
                "revenue": 10000.0,
                "cost": 3500.0,
                "profit": 6500.0,
                "profit_margin_pct": 65.0,
                "status": "healthy",
            },
            {
                "dept_id": str(uuid.uuid4()),
                "dept_name": "凉菜间",
                "dish_count": 40,
                "revenue": 5000.0,
                "cost": 2000.0,
                "profit": 3000.0,
                "profit_margin_pct": 60.0,
                "status": "healthy",
            },
        ],
    }

    with patch(
        "src.api.kds_station_profit_routes.get_station_profit_summary",
        new=AsyncMock(return_value=fake_summary),
    ):
        client = TestClient(_make_profit_app(db))
        resp = client.get(
            "/api/v1/kds/station-profit",
            params={"store_id": STORE_ID, "period": "today"},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["total_revenue"] == 15000.0
    assert data["avg_margin_pct"] == 63.3
    assert data["period"] == "today"
    assert len(data["depts"]) == 2
    assert data["depts"][0]["status"] == "healthy"
    assert data["depts"][0]["dept_name"] == "热菜间"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 2: GET /station-profit?period=week — week 周期计算正确
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_station_profit_week_period():
    """week 周期：start_date 应是本周一，end_date 是今天；验证服务层被调用的日期参数。"""
    db = _make_mock_db()
    captured: dict = {}

    async def _fake_summary(**kwargs):
        captured.update(kwargs)
        return {"total_revenue": 0, "total_profit": 0, "avg_margin_pct": 0, "depts": []}

    with patch(
        "src.api.kds_station_profit_routes.get_station_profit_summary",
        new=_fake_summary,
    ):
        client = TestClient(_make_profit_app(db))
        resp = client.get(
            "/api/v1/kds/station-profit",
            params={"store_id": STORE_ID, "period": "week"},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    assert resp.json()["data"]["period"] == "week"
    # 验证 start_date 是本周一（weekday() == 0）
    assert captured["start_date"].weekday() == 0
    assert captured["end_date"] == date.today()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 3: GET /station-profit?period=month — month 周期计算正确
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_station_profit_month_period():
    """month 周期：start_date 应是本月1日，end_date 是今天。"""
    db = _make_mock_db()
    captured: dict = {}

    async def _fake_summary(**kwargs):
        captured.update(kwargs)
        return {"total_revenue": 0, "total_profit": 0, "avg_margin_pct": 0, "depts": []}

    with patch(
        "src.api.kds_station_profit_routes.get_station_profit_summary",
        new=_fake_summary,
    ):
        client = TestClient(_make_profit_app(db))
        resp = client.get(
            "/api/v1/kds/station-profit",
            params={"store_id": STORE_ID, "period": "month"},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    assert captured["start_date"].day == 1
    assert captured["end_date"] == date.today()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 4: GET /station-profit?start_date=&end_date= — 自定义日期区间优先
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_station_profit_custom_date_range():
    """自定义 start_date/end_date 优先级高于 period 预设。"""
    db = _make_mock_db()
    captured: dict = {}

    async def _fake_summary(**kwargs):
        captured.update(kwargs)
        return {"total_revenue": 0, "total_profit": 0, "avg_margin_pct": 0, "depts": []}

    start = "2026-03-01"
    end = "2026-03-31"

    with patch(
        "src.api.kds_station_profit_routes.get_station_profit_summary",
        new=_fake_summary,
    ):
        client = TestClient(_make_profit_app(db))
        resp = client.get(
            "/api/v1/kds/station-profit",
            params={
                "store_id": STORE_ID,
                "period": "today",  # 被覆盖
                "start_date": start,
                "end_date": end,
            },
            headers=HEADERS,
        )

    assert resp.status_code == 200
    # start_date 应等于自定义值，而非今天
    assert captured["start_date"] == date(2026, 3, 1)
    assert captured["end_date"] == date(2026, 3, 31)
    # response 中也应含自定义日期
    data = resp.json()["data"]
    assert data["start_date"] == "2026-03-01"
    assert data["end_date"] == "2026-03-31"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 5: GET /station-profit — 无档口数据时返回空 depts + 0 合计
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_station_profit_empty_result():
    """没有完成任务时，服务层返回空汇总，响应也应是 0 / 空列表。"""
    db = _make_mock_db()

    empty_summary = {
        "total_revenue": 0,
        "total_profit": 0,
        "avg_margin_pct": 0,
        "depts": [],
    }

    with patch(
        "src.api.kds_station_profit_routes.get_station_profit_summary",
        new=AsyncMock(return_value=empty_summary),
    ):
        client = TestClient(_make_profit_app(db))
        resp = client.get(
            "/api/v1/kds/station-profit",
            params={"store_id": STORE_ID},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total_revenue"] == 0
    assert data["depts"] == []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 6: GET /swimlane/board?dept_id=xxx — 正常返回 steps + lanes
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_swimlane_board_success():
    """泳道看板：2道工序，热菜间有1个任务在工序1，返回结构正确。"""
    db = _make_mock_db()

    fake_board = {
        "steps": [
            {"step_id": STEP_ID, "step_name": "腌制", "step_order": 1, "color": "#FF6B6B"},
            {"step_id": NEXT_STEP, "step_name": "烤制", "step_order": 2, "color": "#4ECDC4"},
        ],
        "lanes": {
            STEP_ID: [
                {
                    "task_step_id": str(uuid.uuid4()),
                    "task_id": TASK_ID,
                    "status": "in_progress",
                    "operator_id": None,
                    "started_at": "2026-04-05T10:00:00+00:00",
                }
            ],
            NEXT_STEP: [],
        },
    }

    with patch(
        "src.api.kds_swimlane_routes.get_swimlane_board",
        new=AsyncMock(return_value=fake_board),
    ):
        client = TestClient(_make_swimlane_app(db))
        resp = client.get(
            "/api/v1/kds/swimlane/board",
            params={"dept_id": DEPT_ID},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert len(data["steps"]) == 2
    assert data["steps"][0]["step_name"] == "腌制"
    assert len(data["lanes"][STEP_ID]) == 1
    assert data["lanes"][STEP_ID][0]["task_id"] == TASK_ID
    assert len(data["lanes"][NEXT_STEP]) == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 7: GET /swimlane/board — 无工序时返回空看板
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_swimlane_board_empty():
    """档口未配置工序时，看板返回空 steps 和 lanes。"""
    db = _make_mock_db()

    with patch(
        "src.api.kds_swimlane_routes.get_swimlane_board",
        new=AsyncMock(return_value={"steps": [], "lanes": {}}),
    ):
        client = TestClient(_make_swimlane_app(db))
        resp = client.get(
            "/api/v1/kds/swimlane/board",
            params={"dept_id": DEPT_ID},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["steps"] == []
    assert data["lanes"] == {}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 8: GET /swimlane/steps?dept_id=xxx — 正常返回工序列表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_get_swimlane_steps_success():
    """工序定义列表：3道工序，按 step_order 返回。"""
    db = _make_mock_db()

    fake_steps = [
        {"step_id": STEP_ID, "step_name": "切配", "step_order": 1, "color": "#FF6B6B"},
        {"step_id": NEXT_STEP, "step_name": "烹饪", "step_order": 2, "color": "#4ECDC4"},
        {"step_id": str(uuid.uuid4()), "step_name": "装盘", "step_order": 3, "color": "#45B7D1"},
    ]

    with patch(
        "src.api.kds_swimlane_routes.get_steps_for_dept",
        new=AsyncMock(return_value=fake_steps),
    ):
        client = TestClient(_make_swimlane_app(db))
        resp = client.get(
            "/api/v1/kds/swimlane/steps",
            params={"dept_id": DEPT_ID},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    items = body["data"]["items"]
    assert len(items) == 3
    assert items[0]["step_name"] == "切配"
    assert items[1]["step_order"] == 2
    assert items[2]["step_name"] == "装盘"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 9: POST /swimlane/steps — 新建工序，返回 created=True
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_upsert_step_create():
    """新增工序（不传 step_id）：服务层返回 created=True。"""
    db = _make_mock_db()

    new_step_id = str(uuid.uuid4())
    fake_result = {"step_id": new_step_id, "created": True}

    with patch(
        "src.api.kds_swimlane_routes.upsert_step",
        new=AsyncMock(return_value=fake_result),
    ):
        client = TestClient(_make_swimlane_app(db))
        resp = client.post(
            "/api/v1/kds/swimlane/steps",
            json={
                "store_id": STORE_ID,
                "dept_id": DEPT_ID,
                "step_name": "传菜",
                "step_order": 4,
                "color": "#A29BFE",
            },
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["created"] is True
    assert body["data"]["step_id"] == new_step_id


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 10: POST /swimlane/steps — 更新现有工序，返回 updated=True
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_upsert_step_update():
    """更新工序（传入 step_id）：服务层返回 updated=True。"""
    db = _make_mock_db()

    fake_result = {"step_id": STEP_ID, "updated": True}

    with patch(
        "src.api.kds_swimlane_routes.upsert_step",
        new=AsyncMock(return_value=fake_result),
    ):
        client = TestClient(_make_swimlane_app(db))
        resp = client.post(
            "/api/v1/kds/swimlane/steps",
            json={
                "store_id": STORE_ID,
                "dept_id": DEPT_ID,
                "step_name": "切配（改名）",
                "step_order": 1,
                "color": "#FF6B6B",
                "step_id": STEP_ID,  # 传入则为更新
            },
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["updated"] is True
    assert body["data"]["step_id"] == STEP_ID


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 11: POST /swimlane/tasks/{task_id}/advance — 推进工序，all_done=False
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_advance_step_not_last():
    """推进非最后一道工序：服务层返回 all_done=False，next_step 有值。"""
    db = _make_mock_db()

    fake_result = {
        "task_id": TASK_ID,
        "completed_step": STEP_ID,
        "next_step": NEXT_STEP,
        "all_done": False,
    }

    with patch(
        "src.api.kds_swimlane_routes.advance_step",
        new=AsyncMock(return_value=fake_result),
    ):
        client = TestClient(_make_swimlane_app(db))
        resp = client.post(
            f"/api/v1/kds/swimlane/tasks/{TASK_ID}/advance",
            json={"step_id": STEP_ID, "operator_id": None},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["all_done"] is False
    assert data["next_step"] == NEXT_STEP
    assert data["completed_step"] == STEP_ID


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 12: POST /swimlane/tasks/{task_id}/advance — 最后一道工序，all_done=True
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_advance_step_last_step():
    """推进最后一道工序：服务层返回 all_done=True，next_step=None。"""
    db = _make_mock_db()

    fake_result = {
        "task_id": TASK_ID,
        "completed_step": NEXT_STEP,
        "next_step": None,
        "all_done": True,
    }

    with patch(
        "src.api.kds_swimlane_routes.advance_step",
        new=AsyncMock(return_value=fake_result),
    ):
        client = TestClient(_make_swimlane_app(db))
        resp = client.post(
            f"/api/v1/kds/swimlane/tasks/{TASK_ID}/advance",
            json={"step_id": NEXT_STEP},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["all_done"] is True
    assert data["next_step"] is None
