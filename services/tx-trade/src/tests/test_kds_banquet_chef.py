"""KDS 宴席路由 + 厨师绩效路由测试

覆盖场景（共 12 个）：

kds_banquet_routes（使用 shared.ontology.src.database.get_db，直接 SQL）：
1.  GET  /api/v1/kds/banquet-sessions/{store_id}    — 正常返回 sessions 列表
2.  GET  /api/v1/kds/banquet-sessions/{store_id}    — 缺少 X-Tenant-ID → 400
3.  POST /api/v1/kds/banquet-sessions/open           — 开席成功，返回 tasks_created
4.  POST /api/v1/kds/banquet-sessions/open           — 场次不存在 → 404
5.  POST /api/v1/kds/banquet-sessions/open           — 场次状态为 serving → 400
6.  POST /api/v1/kds/banquet-sessions/push-section   — 推进节成功，返回 section_name
7.  POST /api/v1/kds/banquet-sessions/push-section   — 该节无菜品 → 404
8.  GET  /api/v1/kds/banquet-sessions/{session_id}/progress — 正常返回进度条

kds_chef_stats_routes（依赖 src.services.kds_chef_stats 服务层）：
9.  GET  /api/v1/kds/chef-stats/leaderboard          — 正常返回排行榜
10. GET  /api/v1/kds/chef-stats/leaderboard?period=week&dept_id=xxx — 带 dept_id 过滤
11. GET  /api/v1/kds/chef-stats/{operator_id}        — 正常返回厨师每日明细
12. GET  /api/v1/kds/chef-stats/{operator_id}?days=7  — days 参数生效
"""
import os
import sys
import types

# ─── 路径准备 ─────────────────────────────────────────────────────────────────
_TESTS_DIR = os.path.dirname(__file__)
_SRC_DIR   = os.path.abspath(os.path.join(_TESTS_DIR, ".."))
_ROOT_DIR  = os.path.abspath(os.path.join(_TESTS_DIR, "..", "..", "..", ".."))

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


_ensure_pkg("src",          _SRC_DIR)
_ensure_pkg("src.api",      os.path.join(_SRC_DIR, "api"))
_ensure_pkg("src.services", os.path.join(_SRC_DIR, "services"))
_ensure_pkg("src.models",   os.path.join(_SRC_DIR, "models"))


# ─── stub helper ──────────────────────────────────────────────────────────────

def _stub_module(full_name: str, **attrs):
    """注入一个最小存根模块，避免真实导入失败。"""
    if full_name in sys.modules:
        return sys.modules[full_name]
    mod = types.ModuleType(full_name)
    mod.__package__ = full_name.rsplit(".", 1)[0] if "." in full_name else full_name
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[full_name] = mod
    return mod


# ─── stub src.db（kds_chef_stats_routes 通过 from ..db import get_db）──────────
_db_mod = _stub_module("src.db", get_db=lambda: None)

# ─── stub kds_chef_stats 服务层 ────────────────────────────────────────────────
_stub_module(
    "src.services.kds_chef_stats",
    get_leaderboard=None,
    get_chef_daily_detail=None,
)

# ─── stub models（kds_swimlane/kds_chef_stats 服务层依赖，但路由层不直接用）────
_stub_module("src.models.chef_performance_daily", ChefPerformanceDaily=None)
_stub_module("src.models.kds_task",               KDSTask=None)
_stub_module("src.models.kds_task_step",          KDSTaskStep=None)
_stub_module("src.models.production_step",        ProductionStep=None)

# ─── 正式导入 ──────────────────────────────────────────────────────────────────
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# kds_banquet_routes 使用 shared.ontology.src.database.get_db
from src.api.kds_banquet_routes import router as banquet_router  # type: ignore[import]
from shared.ontology.src.database import get_db as shared_get_db  # noqa: E402

# kds_chef_stats_routes 使用 src.db.get_db
from src.api.kds_chef_stats_routes import router as chef_router  # type: ignore[import]
from src.db import get_db as src_get_db  # type: ignore[import]


# ─── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_ID   = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
STORE_ID    = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
DEPT_ID     = "cccccccc-cccc-cccc-cccc-cccccccccccc"
SESSION_ID  = "dddddddd-dddd-dddd-dddd-dddddddddddd"
SECTION_ID  = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
OPERATOR_ID = "ffffffff-ffff-ffff-ffff-ffffffffffff"
MENU_ID     = "11111111-1111-1111-1111-111111111111"
DISH_ID     = "22222222-2222-2222-2222-222222222222"

HEADERS = {"X-Tenant-ID": TENANT_ID}


# ─── 工具函数 ──────────────────────────────────────────────────────────────────

def _make_mock_db() -> AsyncMock:
    db = AsyncMock()
    db.commit   = AsyncMock()
    db.rollback = AsyncMock()
    db.execute  = AsyncMock(return_value=MagicMock())
    return db


def _make_banquet_app(db: AsyncMock) -> FastAPI:
    """宴席路由用 shared get_db。"""
    app = FastAPI()
    app.include_router(banquet_router)

    async def _override():
        yield db

    app.dependency_overrides[shared_get_db] = _override
    return app


def _make_chef_app(db: AsyncMock) -> FastAPI:
    """厨师绩效路由用 src get_db。"""
    app = FastAPI()
    app.include_router(chef_router)

    async def _override():
        yield db

    app.dependency_overrides[src_get_db] = _override
    return app


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 1: GET /banquet-sessions/{store_id} — 正常返回 sessions 列表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_list_today_banquet_sessions_success():
    """KDS大屏拉取今日宴席场次，有场次时正常返回 sessions + total。"""
    db = _make_mock_db()

    # _rls 调用（set_config）
    rls_result = MagicMock()

    # fetchall 返回一条宴席记录：按 list_today_banquet_sessions 中 row 下标排列
    # r[0]=id, r[1]=session_name, r[2]=scheduled_at, r[3]=actual_open_at,
    # r[4]=status, r[5]=guest_count, r[6]=table_count,
    # r[7]=current_section_id, r[8]=next_section_at,
    # r[9]=menu_name, r[10]=per_person_fen,
    # r[11]=current_section_name, r[12]=current_serve_sequence
    from datetime import datetime, timedelta
    scheduled = datetime.utcnow() + timedelta(hours=1)

    fake_row = MagicMock()
    fake_row.__getitem__ = lambda self, idx: [
        uuid.UUID(SESSION_ID),  # [0] id
        "VIP宴席001",            # [1] session_name
        scheduled,               # [2] scheduled_at
        None,                    # [3] actual_open_at
        "scheduled",             # [4] status
        60,                      # [5] guest_count
        6,                       # [6] table_count
        None,                    # [7] current_section_id
        None,                    # [8] next_section_at
        "徐记豪华宴席套餐",       # [9] menu_name
        29800,                   # [10] per_person_fen
        None,                    # [11] current_section_name
        None,                    # [12] current_serve_sequence
    ][idx]

    session_result = MagicMock()
    session_result.fetchall.return_value = [fake_row]

    db.execute = AsyncMock(side_effect=[rls_result, session_result])

    client = TestClient(_make_banquet_app(db))
    resp = client.get(
        f"/api/v1/kds/banquet-sessions/{STORE_ID}",
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["total"] == 1
    assert len(data["sessions"]) == 1
    assert data["sessions"][0]["session_name"] == "VIP宴席001"
    assert data["sessions"][0]["status"] == "scheduled"
    assert data["sessions"][0]["guest_count"] == 60


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 2: GET /banquet-sessions/{store_id} — 缺少 X-Tenant-ID → 400
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_list_banquet_sessions_missing_tenant_id():
    """不传 X-Tenant-ID 时，_tenant() 抛 HTTP 400。"""
    db = _make_mock_db()
    client = TestClient(_make_banquet_app(db))

    resp = client.get(f"/api/v1/kds/banquet-sessions/{STORE_ID}")

    assert resp.status_code == 400
    assert "X-Tenant-ID" in resp.json()["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 3: POST /banquet-sessions/open — 开席成功，返回 tasks_created
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_banquet_open_success():
    """开席成功：场次 scheduled，有1个菜品，1张桌，创建1个KDS任务。"""
    db = _make_mock_db()

    # 按调用顺序排列 side_effect
    # [0] _rls set_config
    rls_r = MagicMock()

    # [1] 查场次 session_result.fetchone()
    session_row = MagicMock()
    session_row.__getitem__ = lambda self, idx: [
        uuid.UUID(SESSION_ID),  # [0] id
        "scheduled",            # [1] status
        [],                     # [2] table_ids
        [],                     # [3] order_ids
        uuid.UUID(MENU_ID),     # [4] banquet_menu_id
        1,                      # [5] table_count
        10,                     # [6] guest_count
    ][idx]
    session_r = MagicMock()
    session_r.fetchone.return_value = session_row

    # [2] 查第一节菜品 first_section_result.fetchall()
    # 路由代码做 tuple unpack：section_id, section_name, _, dish_id, dish_name, qty, note = item
    # 必须使用可迭代的 tuple，不能用 MagicMock
    section_row = (
        uuid.UUID(SECTION_ID),  # [0] section_id
        "凉菜上桌",              # [1] section_name
        0,                       # [2] serve_delay_minutes
        uuid.UUID(DISH_ID),     # [3] dish_id
        "夫妻肺片",              # [4] dish_name
        1,                       # [5] quantity_per_table
        "",                      # [6] note
    )
    first_section_r = MagicMock()
    first_section_r.fetchall.return_value = [section_row]

    # [3] 查档口映射 dept_result.fetchone()
    dept_row = MagicMock()
    dept_row.__getitem__ = lambda self, idx: [uuid.UUID(DEPT_ID)][idx]
    dept_r = MagicMock()
    dept_r.fetchone.return_value = dept_row

    # [4] INSERT kds_tasks（无需返回值）
    insert_r = MagicMock()

    # [5] UPDATE banquet_sessions
    update_r = MagicMock()

    db.execute = AsyncMock(side_effect=[
        rls_r,
        session_r,
        first_section_r,
        dept_r,
        insert_r,
        update_r,
    ])

    client = TestClient(_make_banquet_app(db))
    resp = client.post(
        "/api/v1/kds/banquet-sessions/open",
        json={
            "session_id": SESSION_ID,
            "operator_id": OPERATOR_ID,
            "first_section_delay_minutes": 0,
        },
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["session_id"] == SESSION_ID
    assert data["status"] == "serving"
    assert data["tasks_created"] == 1
    assert data["table_count"] == 1
    assert "凉菜上桌" in data["first_section_name"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 4: POST /banquet-sessions/open — 场次不存在 → 404
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_banquet_open_session_not_found():
    """开席失败：session 不存在，返回 404。"""
    db = _make_mock_db()

    rls_r = MagicMock()
    session_r = MagicMock()
    session_r.fetchone.return_value = None  # 查不到场次

    db.execute = AsyncMock(side_effect=[rls_r, session_r])

    client = TestClient(_make_banquet_app(db))
    resp = client.post(
        "/api/v1/kds/banquet-sessions/open",
        json={"session_id": SESSION_ID},
        headers=HEADERS,
    )

    assert resp.status_code == 404
    assert "不存在" in resp.json()["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 5: POST /banquet-sessions/open — 场次状态为 serving → 400
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_banquet_open_wrong_status():
    """开席失败：场次已在 serving 状态，返回 400。"""
    db = _make_mock_db()

    rls_r = MagicMock()
    session_row = MagicMock()
    session_row.__getitem__ = lambda self, idx: [
        uuid.UUID(SESSION_ID),
        "serving",  # 已开席
        [],
        [],
        uuid.UUID(MENU_ID),
        1,
        10,
    ][idx]
    session_r = MagicMock()
    session_r.fetchone.return_value = session_row

    db.execute = AsyncMock(side_effect=[rls_r, session_r])

    client = TestClient(_make_banquet_app(db))
    resp = client.post(
        "/api/v1/kds/banquet-sessions/open",
        json={"session_id": SESSION_ID},
        headers=HEADERS,
    )

    assert resp.status_code == 400
    assert "serving" in resp.json()["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 6: POST /banquet-sessions/push-section — 推进节成功，返回 section_name
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_push_next_section_success():
    """推进下一节成功：1道菜，1张桌，创建1个任务。"""
    db = _make_mock_db()

    rls_r = MagicMock()

    # 查该节菜品
    item_row = MagicMock()
    item_row.__getitem__ = lambda self, idx: [
        uuid.UUID(DISH_ID),  # [0] dish_id
        "红烧肉",             # [1] dish_name
        2,                    # [2] quantity_per_table
        "",                   # [3] note
        "热菜上桌",           # [4] section_name
        2,                    # [5] serve_sequence
    ][idx]
    items_r = MagicMock()
    items_r.fetchall.return_value = [item_row]

    # 查场次
    session_row = MagicMock()
    session_row.__getitem__ = lambda self, idx: [1, []  ][idx]
    session_r = MagicMock()
    session_r.fetchone.return_value = session_row

    # 查档口映射
    dept_row = MagicMock()
    dept_row.__getitem__ = lambda self, idx: [uuid.UUID(DEPT_ID)][idx]
    dept_r = MagicMock()
    dept_r.fetchone.return_value = dept_row

    # INSERT
    insert_r = MagicMock()
    # UPDATE 场次当前节
    update_r = MagicMock()

    db.execute = AsyncMock(side_effect=[
        rls_r,
        items_r,
        session_r,
        dept_r,
        insert_r,
        update_r,
    ])

    client = TestClient(_make_banquet_app(db))
    resp = client.post(
        "/api/v1/kds/banquet-sessions/push-section",
        json={
            "session_id": SESSION_ID,
            "section_id": SECTION_ID,
            "operator_id": OPERATOR_ID,
        },
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["section_name"] == "热菜上桌"
    assert data["tasks_created"] == 1


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 7: POST /banquet-sessions/push-section — 该节无菜品 → 404
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_push_next_section_no_items():
    """推进失败：section 未配置菜品，返回 404。"""
    db = _make_mock_db()

    rls_r = MagicMock()
    items_r = MagicMock()
    items_r.fetchall.return_value = []  # 无菜品

    db.execute = AsyncMock(side_effect=[rls_r, items_r])

    client = TestClient(_make_banquet_app(db))
    resp = client.post(
        "/api/v1/kds/banquet-sessions/push-section",
        json={"session_id": SESSION_ID, "section_id": SECTION_ID},
        headers=HEADERS,
    )

    assert resp.status_code == 404
    assert "无菜品" in resp.json()["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 8: GET /banquet-sessions/{session_id}/progress — 正常返回进度条
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_get_banquet_progress_success():
    """宴席进度总览：2节，第1节已完成，第2节进行中。"""
    db = _make_mock_db()

    rls_r = MagicMock()

    # 模拟2行进度数据
    # r[0]=section_name, r[1]=serve_sequence, r[2]=total, r[3]=done, r[4]=cooking, r[5]=pending
    rows = []
    for section_name, seq, total, done, cooking, pending in [
        ("凉菜", 1, 6, 6, 0, 0),
        ("热菜", 2, 6, 2, 3, 1),
    ]:
        row = MagicMock()
        row.__getitem__ = lambda self, idx, _d=[section_name, seq, total, done, cooking, pending]: _d[idx]
        rows.append(row)

    progress_r = MagicMock()
    progress_r.fetchall.return_value = rows

    db.execute = AsyncMock(side_effect=[rls_r, progress_r])

    client = TestClient(_make_banquet_app(db))
    resp = client.get(
        f"/api/v1/kds/banquet-sessions/{SESSION_ID}/progress",
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["session_id"] == SESSION_ID
    assert len(data["sections"]) == 2

    section1 = data["sections"][0]
    assert section1["section_name"] == "凉菜"
    assert section1["completion_pct"] == 100
    assert section1["status"] == "completed"

    section2 = data["sections"][1]
    assert section2["section_name"] == "热菜"
    assert section2["status"] == "in_progress"

    assert data["overall_total"] == 12
    assert data["overall_done"] == 8


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 9: GET /chef-stats/leaderboard — 正常返回排行榜
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_chef_leaderboard_success():
    """厨师绩效排行榜：today 周期，返回1名厨师的数据。"""
    db = _make_mock_db()

    fake_leaderboard = [
        {
            "operator_id": OPERATOR_ID,
            "total_dishes": 42,
            "total_amount": 1680.0,
            "avg_cook_sec": 300,
            "rush_handled": 3,
            "remake_count": 0,
        }
    ]

    with patch(
        "src.api.kds_chef_stats_routes.get_leaderboard",
        new=AsyncMock(return_value=fake_leaderboard),
    ):
        client = TestClient(_make_chef_app(db))
        resp = client.get(
            "/api/v1/kds/chef-stats/leaderboard",
            params={"store_id": STORE_ID, "period": "today"},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["period"] == "today"
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["operator_id"] == OPERATOR_ID
    assert item["total_dishes"] == 42
    assert item["remake_count"] == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 10: GET /chef-stats/leaderboard?period=week&dept_id=xxx — 带 dept_id 过滤
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_chef_leaderboard_week_with_dept_filter():
    """排行榜：week 周期 + dept_id 过滤，服务层接收正确参数，返回空列表也合法。"""
    db = _make_mock_db()

    captured: dict = {}

    async def _fake_leaderboard(**kwargs):
        captured.update(kwargs)
        return []

    with patch(
        "src.api.kds_chef_stats_routes.get_leaderboard",
        new=_fake_leaderboard,
    ):
        client = TestClient(_make_chef_app(db))
        resp = client.get(
            "/api/v1/kds/chef-stats/leaderboard",
            params={
                "store_id": STORE_ID,
                "period": "week",
                "dept_id": DEPT_ID,
            },
            headers=HEADERS,
        )

    assert resp.status_code == 200
    assert resp.json()["data"]["period"] == "week"
    assert resp.json()["data"]["items"] == []
    assert captured["period"] == "week"
    assert captured["dept_id"] == DEPT_ID


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 11: GET /chef-stats/{operator_id} — 正常返回厨师每日明细
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_chef_detail_success():
    """厨师每日明细：默认 days=30，返回3条记录。"""
    db = _make_mock_db()

    fake_detail = [
        {"date": "2026-04-05", "dept_id": DEPT_ID, "dish_count": 15, "dish_amount": 600.0,
         "avg_cook_sec": 320, "rush_handled": 1, "remake_count": 0},
        {"date": "2026-04-04", "dept_id": DEPT_ID, "dish_count": 18, "dish_amount": 720.0,
         "avg_cook_sec": 290, "rush_handled": 2, "remake_count": 1},
        {"date": "2026-04-03", "dept_id": DEPT_ID, "dish_count": 12, "dish_amount": 480.0,
         "avg_cook_sec": 310, "rush_handled": 0, "remake_count": 0},
    ]

    with patch(
        "src.api.kds_chef_stats_routes.get_chef_daily_detail",
        new=AsyncMock(return_value=fake_detail),
    ):
        client = TestClient(_make_chef_app(db))
        resp = client.get(
            f"/api/v1/kds/chef-stats/{OPERATOR_ID}",
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["operator_id"] == OPERATOR_ID
    assert len(data["items"]) == 3
    assert data["items"][0]["dish_count"] == 15
    assert data["items"][1]["remake_count"] == 1


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 12: GET /chef-stats/{operator_id}?days=7 — days 参数生效
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_chef_detail_days_param():
    """days=7 时，start_date 应是 end_date 往前推 6 天（7天区间）。"""
    from datetime import date, timedelta

    db = _make_mock_db()
    captured: dict = {}

    async def _fake_detail(**kwargs):
        captured.update(kwargs)
        return []

    with patch(
        "src.api.kds_chef_stats_routes.get_chef_daily_detail",
        new=_fake_detail,
    ):
        client = TestClient(_make_chef_app(db))
        resp = client.get(
            f"/api/v1/kds/chef-stats/{OPERATOR_ID}",
            params={"days": 7},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    # 验证 start_date 和 end_date 的间隔为 6 天（days-1）
    delta = (captured["end_date"] - captured["start_date"]).days
    assert delta == 6
    assert captured["operator_id"] == OPERATOR_ID
