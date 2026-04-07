"""等位调度 API 路由测试 — waitlist_routes.py DB版

覆盖场景（共 10 个）：
1. GET  /api/v1/waitlist               — list_waitlist 正常返回空列表
2. GET  /api/v1/waitlist               — 缺少 store_id → 422
3. POST /api/v1/waitlist               — create_waitlist_entry 正常
4. POST /api/v1/waitlist               — party_size=0 → 422
5. POST /api/v1/waitlist/{id}/call     — call_entry 正常（waiting → called）
6. POST /api/v1/waitlist/{id}/call     — entry 不存在 → 404
7. POST /api/v1/waitlist/{id}/seat     — seat_entry 正常（called → seated）
8. POST /api/v1/waitlist/{id}/cancel   — cancel_entry 正常（waiting → cancelled）
9. POST /api/v1/waitlist/expire-overdue— 正常过期 1 条
10. GET  /api/v1/waitlist/stats        — 返回今日统计数据
"""
import datetime
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


# ─── 建立 src 包层级 ──────────────────────────────────────────────────────────

def _ensure_pkg(name: str, path: str) -> None:
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = [path]
        mod.__package__ = name
        sys.modules[name] = mod


_ensure_pkg("src",      _SRC_DIR)
_ensure_pkg("src.api",  os.path.join(_SRC_DIR, "api"))

# ─── 导入 ─────────────────────────────────────────────────────────────────────

import pytest  # noqa: E402
from unittest.mock import AsyncMock, MagicMock  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api.waitlist_routes import router as waitlist_router  # type: ignore[import]  # noqa: E402
from shared.ontology.src.database import get_db  # noqa: E402

# ─── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_ID = "11111111-1111-1111-1111-111111111111"
STORE_ID  = "22222222-2222-2222-2222-222222222222"
ENTRY_ID  = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"

HEADERS = {"X-Tenant-ID": TENANT_ID}

# ─── 工具函数 ──────────────────────────────────────────────────────────────────


def _make_mock_db() -> AsyncMock:
    """创建最小化的 mock AsyncSession。"""
    db = AsyncMock()
    db.commit   = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _mappings_all(rows: list) -> MagicMock:
    """辅助：生成 result.mappings().all() = rows 的 mock 链。"""
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows
    return result


def _mappings_one_or_none(row) -> MagicMock:
    """辅助：生成 result.mappings().one_or_none() = row 的 mock 链。"""
    result = MagicMock()
    result.mappings.return_value.one_or_none.return_value = row
    return result


def _mappings_one(row) -> MagicMock:
    """辅助：生成 result.mappings().one() = row 的 mock 链。"""
    result = MagicMock()
    result.mappings.return_value.one.return_value = row
    return result


def _scalar(value) -> MagicMock:
    """辅助：生成 result.scalar() = value 的 mock 链。"""
    result = MagicMock()
    result.scalar.return_value = value
    return result


def _fake_row(mapping: dict) -> MagicMock:
    """辅助：创建带 _mapping 属性的假行对象。"""
    row = MagicMock()
    row._mapping = mapping
    row.__getitem__ = lambda self, key: self._mapping[key]
    return row


def _make_app_with_db(db: AsyncMock) -> FastAPI:
    """创建绑定了 mock DB 的独立测试 app。"""
    app = FastAPI()
    # waitlist_routes.py 的路由注册时无前缀，由 main.py prefix=/api/v1/waitlist 注入
    app.include_router(waitlist_router, prefix="/api/v1/waitlist")

    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    return app


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 1: GET /api/v1/waitlist — list_waitlist 正常返回空列表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_list_waitlist_empty():
    """门店无等位记录时应返回 items=[], waiting_count=0。"""
    db = _make_mock_db()
    # execute 调用链: 1=set_config, 2=SELECT list
    set_cfg = MagicMock()
    list_result = _mappings_all([])
    db.execute = AsyncMock(side_effect=[set_cfg, list_result])

    client = TestClient(_make_app_with_db(db))
    resp = client.get("/api/v1/waitlist", params={"store_id": STORE_ID}, headers=HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["items"] == []
    assert data["data"]["waiting_count"] == 0
    assert data["data"]["total"] == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 2: GET /api/v1/waitlist — 缺少 store_id → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_list_waitlist_missing_store_id():
    """缺少必填查询参数 store_id 时 FastAPI 应返回 422 Unprocessable Entity。"""
    db = _make_mock_db()
    client = TestClient(_make_app_with_db(db))
    resp = client.get("/api/v1/waitlist", headers=HEADERS)
    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 3: POST /api/v1/waitlist — create_waitlist_entry 正常
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_create_waitlist_entry_success():
    """正常提交等位应返回 queue_no、status=waiting 及 entry_id。"""
    db = _make_mock_db()

    set_cfg      = MagicMock()
    queue_row    = _fake_row({"next_no": 101})
    queue_result = _mappings_one_or_none(queue_row)
    count_result = _scalar(3)
    insert_row   = _fake_row({
        "id":                "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "queue_no":          101,
        "estimated_wait_min": 18,
        "created_at":        datetime.datetime(2026, 4, 4, 10, 0, 0),
    })
    insert_result = _mappings_one(insert_row)

    db.execute = AsyncMock(side_effect=[set_cfg, queue_result, count_result, insert_result])

    client = TestClient(_make_app_with_db(db))
    resp = client.post(
        "/api/v1/waitlist",
        json={"store_id": STORE_ID, "name": "张三", "party_size": 4},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["queue_no"] == 101
    assert data["data"]["status"] == "waiting"
    assert "entry_id" in data["data"]
    db.commit.assert_awaited_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 4: POST /api/v1/waitlist — party_size=0 → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_create_waitlist_entry_invalid_party_size():
    """party_size 必须 > 0，传 0 时 Pydantic 校验失败应返回 422。"""
    db = _make_mock_db()
    client = TestClient(_make_app_with_db(db))
    resp = client.post(
        "/api/v1/waitlist",
        json={"store_id": STORE_ID, "name": "张三", "party_size": 0},
        headers=HEADERS,
    )
    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 5: POST /api/v1/waitlist/{id}/call — call_entry 正常
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_call_entry_success():
    """waiting 状态的记录叫号后应返回 status=called 及 call_count+1。"""
    db = _make_mock_db()

    set_cfg     = MagicMock()
    entry_row   = _fake_row({"id": ENTRY_ID, "status": "waiting", "call_count": 0})
    find_result = _mappings_one_or_none(entry_row)
    update_res  = MagicMock()
    log_res     = MagicMock()

    db.execute = AsyncMock(side_effect=[set_cfg, find_result, update_res, log_res])

    client = TestClient(_make_app_with_db(db))
    resp = client.post(
        f"/api/v1/waitlist/{ENTRY_ID}/call",
        json={"channel": "screen"},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["status"] == "called"
    assert data["data"]["call_count"] == 1
    db.commit.assert_awaited_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 6: POST /api/v1/waitlist/{id}/call — entry 不存在 → 404
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_call_entry_not_found():
    """等位记录不存在时应返回 404。"""
    db = _make_mock_db()

    set_cfg     = MagicMock()
    find_result = _mappings_one_or_none(None)

    db.execute = AsyncMock(side_effect=[set_cfg, find_result])

    client = TestClient(_make_app_with_db(db))
    resp = client.post(
        "/api/v1/waitlist/nonexistent-0000-0000-0000-000000000000/call",
        json={"channel": "screen"},
        headers=HEADERS,
    )

    assert resp.status_code == 404


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 7: POST /api/v1/waitlist/{id}/seat — seat_entry 正常
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_seat_entry_success():
    """called 状态的记录入座确认后应返回 status=seated。"""
    db = _make_mock_db()

    set_cfg     = MagicMock()
    entry_row   = _fake_row({"id": ENTRY_ID, "status": "called", "pre_order_items": None, "pre_order_total_fen": 0})
    find_result = _mappings_one_or_none(entry_row)
    update_res  = MagicMock()

    db.execute = AsyncMock(side_effect=[set_cfg, find_result, update_res])

    client = TestClient(_make_app_with_db(db))
    resp = client.post(
        f"/api/v1/waitlist/{ENTRY_ID}/seat",
        json={},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["status"] == "seated"
    assert "seated_at" in data["data"]
    db.commit.assert_awaited_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 8: POST /api/v1/waitlist/{id}/cancel — cancel_entry 正常
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_cancel_entry_success():
    """waiting 状态的记录取消后应返回 status=cancelled。"""
    db = _make_mock_db()

    set_cfg     = MagicMock()
    entry_row   = _fake_row({"id": ENTRY_ID, "status": "waiting"})
    find_result = _mappings_one_or_none(entry_row)
    update_res  = MagicMock()

    db.execute = AsyncMock(side_effect=[set_cfg, find_result, update_res])

    client = TestClient(_make_app_with_db(db))
    resp = client.post(
        f"/api/v1/waitlist/{ENTRY_ID}/cancel",
        json={"reason": "顾客主动取消"},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["status"] == "cancelled"
    db.commit.assert_awaited_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 9: POST /api/v1/waitlist/expire-overdue — 正常过期 1 条
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_expire_overdue_success():
    """批量过期应返回 expired_count=1 及对应 expired_ids 列表。"""
    db = _make_mock_db()

    set_cfg       = MagicMock()
    expired_row   = _fake_row({"id": "ffffffff-ffff-ffff-ffff-ffffffffffff"})
    update_result = _mappings_all([expired_row])

    db.execute = AsyncMock(side_effect=[set_cfg, update_result])

    client = TestClient(_make_app_with_db(db))
    resp = client.post(
        "/api/v1/waitlist/expire-overdue",
        params={"store_id": STORE_ID},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["expired_count"] == 1
    assert len(data["data"]["expired_ids"]) == 1
    db.commit.assert_awaited_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 10: GET /api/v1/waitlist/stats — 返回今日统计数据
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_get_stats_success():
    """统计端点应聚合今日各状态数量并返回 estimated_wait_min。"""
    db = _make_mock_db()

    set_cfg    = MagicMock()
    stats_row  = _fake_row({
        "waiting_count":   5,
        "called_count":    2,
        "seated_count":    10,
        "cancelled_count": 1,
        "expired_count":   0,
        "total_today":     18,
    })
    stats_result = _mappings_one_or_none(stats_row)

    db.execute = AsyncMock(side_effect=[set_cfg, stats_result])

    client = TestClient(_make_app_with_db(db))
    resp = client.get(
        "/api/v1/waitlist/stats",
        params={"store_id": STORE_ID},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["waiting_count"] == 5
    assert data["data"]["total_today"] == 18
    assert "estimated_wait_min" in data["data"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 排队预点菜功能测试（9 个场景）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# ── 场景 11: POST /{entry_id}/pre-order — 正常添加预点菜 ──

def test_add_pre_order_ok():
    """正常添加预点菜，返回 ok=True 及合并后的 items。"""
    db = _make_mock_db()

    set_cfg     = MagicMock()
    entry_row   = _fake_row({"id": ENTRY_ID, "status": "waiting", "pre_order_items": None})
    find_result = _mappings_one_or_none(entry_row)
    update_res  = MagicMock()

    db.execute = AsyncMock(side_effect=[set_cfg, find_result, update_res])

    client = TestClient(_make_app_with_db(db))
    resp = client.post(
        f"/api/v1/waitlist/{ENTRY_ID}/pre-order",
        json={
            "items": [
                {"dish_id": "d1", "dish_name": "烤鸭", "quantity": 1, "unit_price_fen": 16800},
                {"dish_id": "d2", "dish_name": "啤酒", "quantity": 2, "unit_price_fen": 1500},
            ]
        },
        headers=HEADERS,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["items_count"] == 2
    assert data["data"]["pre_order_total_fen"] == 16800 + 1500 * 2
    db.commit.assert_awaited_once()


# ── 场景 12: POST /{entry_id}/pre-order — 排队条目不存在 → 404 ──

def test_add_pre_order_entry_not_found():
    """排队条目不存在时应返回 404。"""
    db = _make_mock_db()

    set_cfg     = MagicMock()
    find_result = _mappings_one_or_none(None)

    db.execute = AsyncMock(side_effect=[set_cfg, find_result])

    client = TestClient(_make_app_with_db(db))
    resp = client.post(
        f"/api/v1/waitlist/{ENTRY_ID}/pre-order",
        json={"items": [{"dish_id": "d1", "dish_name": "菜", "quantity": 1, "unit_price_fen": 1000}]},
        headers=HEADERS,
    )

    assert resp.status_code == 404


# ── 场景 13: POST /{entry_id}/pre-order — 非 waiting/called 状态 → 400 ──

def test_add_pre_order_wrong_status():
    """非 waiting/called 状态不允许预点菜，应返回 400。"""
    db = _make_mock_db()

    set_cfg     = MagicMock()
    entry_row   = _fake_row({"id": ENTRY_ID, "status": "seated", "pre_order_items": None})
    find_result = _mappings_one_or_none(entry_row)

    db.execute = AsyncMock(side_effect=[set_cfg, find_result])

    client = TestClient(_make_app_with_db(db))
    resp = client.post(
        f"/api/v1/waitlist/{ENTRY_ID}/pre-order",
        json={"items": [{"dish_id": "d1", "dish_name": "菜", "quantity": 1, "unit_price_fen": 1000}]},
        headers=HEADERS,
    )

    assert resp.status_code == 400


# ── 场景 14: GET /{entry_id}/pre-order — 查看预点菜列表 ──

def test_get_pre_order_ok():
    """查看预点菜列表应返回 items 及 total_fen。"""
    db = _make_mock_db()

    set_cfg     = MagicMock()
    items_data  = [{"dish_id": "d1", "dish_name": "烤鸭", "quantity": 1, "unit_price_fen": 16800, "modifiers": [], "notes": ""}]
    entry_row   = _fake_row({
        "id": ENTRY_ID, "status": "waiting",
        "pre_order_items": items_data,
        "pre_order_total_fen": 16800,
    })
    find_result = _mappings_one_or_none(entry_row)

    db.execute = AsyncMock(side_effect=[set_cfg, find_result])

    client = TestClient(_make_app_with_db(db))
    resp = client.get(
        f"/api/v1/waitlist/{ENTRY_ID}/pre-order",
        headers=HEADERS,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["items_count"] == 1
    assert data["data"]["pre_order_total_fen"] == 16800
    assert data["data"]["pre_order_items"][0]["dish_id"] == "d1"


# ── 场景 15: GET /{entry_id}/pre-order — 无预点菜返回空列表 ──

def test_get_pre_order_empty():
    """无预点菜时应返回空列表及 total_fen=0。"""
    db = _make_mock_db()

    set_cfg     = MagicMock()
    entry_row   = _fake_row({
        "id": ENTRY_ID, "status": "waiting",
        "pre_order_items": None,
        "pre_order_total_fen": 0,
    })
    find_result = _mappings_one_or_none(entry_row)

    db.execute = AsyncMock(side_effect=[set_cfg, find_result])

    client = TestClient(_make_app_with_db(db))
    resp = client.get(
        f"/api/v1/waitlist/{ENTRY_ID}/pre-order",
        headers=HEADERS,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["pre_order_items"] == []
    assert data["data"]["pre_order_total_fen"] == 0
    assert data["data"]["items_count"] == 0


# ── 场景 16: DELETE /{entry_id}/pre-order/{dish_id} — 删除预点的某道菜 ──

def test_remove_pre_order_item():
    """删除预点的某道菜，菜品应从列表中移除，total_fen 重算。"""
    db = _make_mock_db()

    set_cfg     = MagicMock()
    items_data  = [
        {"dish_id": "d1", "dish_name": "烤鸭", "quantity": 1, "unit_price_fen": 16800, "modifiers": [], "notes": ""},
        {"dish_id": "d2", "dish_name": "啤酒", "quantity": 2, "unit_price_fen": 1500, "modifiers": [], "notes": ""},
    ]
    entry_row   = _fake_row({"id": ENTRY_ID, "status": "waiting", "pre_order_items": items_data})
    find_result = _mappings_one_or_none(entry_row)
    update_res  = MagicMock()

    db.execute = AsyncMock(side_effect=[set_cfg, find_result, update_res])

    client = TestClient(_make_app_with_db(db))
    resp = client.delete(
        f"/api/v1/waitlist/{ENTRY_ID}/pre-order/d1",
        headers=HEADERS,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["removed_dish_id"] == "d1"
    assert data["data"]["removed_count"] == 1
    assert data["data"]["items_count"] == 1
    assert data["data"]["pre_order_total_fen"] == 1500 * 2
    db.commit.assert_awaited_once()


# ── 场景 17: 预点菜总价计算（含做法加价）──

def test_pre_order_total_calculation():
    """预点菜总价应包含做法加价。"""
    db = _make_mock_db()

    set_cfg     = MagicMock()
    entry_row   = _fake_row({"id": ENTRY_ID, "status": "waiting", "pre_order_items": None})
    find_result = _mappings_one_or_none(entry_row)
    update_res  = MagicMock()

    db.execute = AsyncMock(side_effect=[set_cfg, find_result, update_res])

    client = TestClient(_make_app_with_db(db))
    resp = client.post(
        f"/api/v1/waitlist/{ENTRY_ID}/pre-order",
        json={
            "items": [
                {
                    "dish_id": "d1",
                    "dish_name": "烤鸭",
                    "quantity": 1,
                    "unit_price_fen": 16800,
                    "modifiers": [{"name": "加葱", "extra_fen": 300}],
                },
            ]
        },
        headers=HEADERS,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    # 总价 = (16800 + 300) * 1 = 17100
    assert data["data"]["pre_order_total_fen"] == 17100


# ── 场景 18: 入座时自动合并预点菜 ──

def test_seat_merges_pre_order():
    """入座时应自动合并预点菜，返回 pre_order_merged=True。"""
    db = _make_mock_db()

    set_cfg     = MagicMock()
    items_data  = [{"dish_id": "d1", "dish_name": "烤鸭", "quantity": 1, "unit_price_fen": 16800, "modifiers": [], "notes": ""}]
    entry_row   = _fake_row({
        "id": ENTRY_ID, "status": "called",
        "pre_order_items": items_data,
        "pre_order_total_fen": 16800,
    })
    find_result = _mappings_one_or_none(entry_row)
    update_res  = MagicMock()

    db.execute = AsyncMock(side_effect=[set_cfg, find_result, update_res])

    client = TestClient(_make_app_with_db(db))
    resp = client.post(
        f"/api/v1/waitlist/{ENTRY_ID}/seat",
        json={},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["status"] == "seated"
    assert data["data"]["pre_order_merged"] is True
    assert data["data"]["pre_order_items_count"] == 1
    db.commit.assert_awaited_once()


# ── 场景 19: 重复菜品智能合并数量 ──

def test_pre_order_duplicate_merge():
    """已有预点菜的条目再次添加相同菜品时，数量应合并而非重复。"""
    db = _make_mock_db()

    existing = [{"dish_id": "d1", "dish_name": "烤鸭", "quantity": 1, "unit_price_fen": 16800, "modifiers": [], "notes": ""}]

    set_cfg     = MagicMock()
    entry_row   = _fake_row({"id": ENTRY_ID, "status": "waiting", "pre_order_items": existing})
    find_result = _mappings_one_or_none(entry_row)
    update_res  = MagicMock()

    db.execute = AsyncMock(side_effect=[set_cfg, find_result, update_res])

    client = TestClient(_make_app_with_db(db))
    resp = client.post(
        f"/api/v1/waitlist/{ENTRY_ID}/pre-order",
        json={
            "items": [
                {"dish_id": "d1", "dish_name": "烤鸭", "quantity": 2, "unit_price_fen": 16800},
            ]
        },
        headers=HEADERS,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    # 原有 1 只 + 新增 2 只 = 3 只，应合并为同一条
    assert data["data"]["items_count"] == 1
    assert data["data"]["pre_order_items"][0]["quantity"] == 3
    assert data["data"]["pre_order_total_fen"] == 16800 * 3
    db.commit.assert_awaited_once()
