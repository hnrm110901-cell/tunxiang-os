"""预订配置 API 路由测试 — reservation_config_routes.py

覆盖场景（共 16 个）：

包间配置:
1.  GET  /configs?store_id=            — 返回空配置
2.  POST /configs/rooms                — 创建包间成功
3.  POST /configs/rooms                — room_code 重复 → 400
4.  POST /configs/rooms                — max_guests < min_guests → 422
5.  PUT  /configs/rooms/{id}           — 更新包间名称成功
6.  PUT  /configs/rooms/{id}           — 不存在 → 404
7.  DELETE /configs/rooms/{id}         — 删除成功
8.  DELETE /configs/rooms/{id}         — 不存在 → 404

时段配置:
9.  GET  /configs/time-slots           — 返回空列表
10. POST /configs/time-slots           — 创建时段成功
11. POST /configs/time-slots           — end_time <= start_time → 400
12. PUT  /configs/time-slots/{id}      — 更新用餐时长成功
13. PUT  /configs/time-slots/{id}      — 不存在 → 404

顾客查询:
14. GET  /available                    — 无 DB 配置时 fallback 返回数据
15. GET  /available                    — 缺少必填参数 → 422
16. GET  /available                    — 缺少 tenant_id → 401
"""

import datetime
import os
import sys
import types
import uuid

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
_ensure_pkg("src.models", os.path.join(_SRC_DIR, "models"))
_ensure_pkg("src.repositories", os.path.join(_SRC_DIR, "repositories"))
_ensure_pkg("src.services", os.path.join(_SRC_DIR, "services"))

# ─── 导入 ─────────────────────────────────────────────────────────────────────

from unittest.mock import AsyncMock, patch  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from shared.ontology.src.database import get_db  # noqa: E402
from src.api.reservation_config_routes import router as config_router  # type: ignore[import]  # noqa: E402

# ─── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_ID = "11111111-1111-1111-1111-111111111111"
STORE_ID = "22222222-2222-2222-2222-222222222222"
ROOM_ID = "33333333-3333-3333-3333-333333333333"
SLOT_ID = "44444444-4444-4444-4444-444444444444"

HEADERS = {"X-Tenant-ID": TENANT_ID}

# ─── 工具函数 ──────────────────────────────────────────────────────────────────


def _make_mock_db() -> AsyncMock:
    """创建最小化的 mock AsyncSession。"""
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _make_app_with_db(db: AsyncMock) -> FastAPI:
    """创建绑定了 mock DB 的独立测试 app。"""
    app = FastAPI()
    app.include_router(config_router, prefix="/api/v1/reservation")

    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    return app


class _FakeRoom:
    """模拟 ReservationConfig ORM 对象"""

    def __init__(self, **kwargs):
        self.id = kwargs.get("id", uuid.UUID(ROOM_ID))
        self.tenant_id = kwargs.get("tenant_id", uuid.UUID(TENANT_ID))
        self.store_id = kwargs.get("store_id", uuid.UUID(STORE_ID))
        self.room_code = kwargs.get("room_code", "MH01")
        self.room_name = kwargs.get("room_name", "梅花厅")
        self.room_type = kwargs.get("room_type", "private")
        self.min_guests = kwargs.get("min_guests", 4)
        self.max_guests = kwargs.get("max_guests", 8)
        self.deposit_fen = kwargs.get("deposit_fen", 80000)
        self.is_active = kwargs.get("is_active", True)
        self.sort_order = kwargs.get("sort_order", 0)
        self.is_deleted = kwargs.get("is_deleted", False)
        self.created_at = kwargs.get("created_at", datetime.datetime(2026, 4, 25, 10, 0, 0))
        self.updated_at = kwargs.get("updated_at", datetime.datetime(2026, 4, 25, 10, 0, 0))

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "store_id": str(self.store_id),
            "room_code": self.room_code,
            "room_name": self.room_name,
            "room_type": self.room_type,
            "min_guests": self.min_guests,
            "max_guests": self.max_guests,
            "deposit_fen": self.deposit_fen,
            "is_active": self.is_active,
            "sort_order": self.sort_order,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class _FakeSlot:
    """模拟 ReservationTimeSlot ORM 对象"""

    def __init__(self, **kwargs):
        self.id = kwargs.get("id", uuid.UUID(SLOT_ID))
        self.tenant_id = kwargs.get("tenant_id", uuid.UUID(TENANT_ID))
        self.store_id = kwargs.get("store_id", uuid.UUID(STORE_ID))
        self.slot_name = kwargs.get("slot_name", "午餐")
        self.start_time = kwargs.get("start_time", datetime.time(11, 0))
        self.end_time = kwargs.get("end_time", datetime.time(14, 0))
        self.dining_duration_min = kwargs.get("dining_duration_min", 120)
        self.max_reservations = kwargs.get("max_reservations", 0)
        self.is_active = kwargs.get("is_active", True)
        self.sort_order = kwargs.get("sort_order", 0)
        self.is_deleted = kwargs.get("is_deleted", False)
        self.created_at = kwargs.get("created_at", datetime.datetime(2026, 4, 25, 10, 0, 0))
        self.updated_at = kwargs.get("updated_at", datetime.datetime(2026, 4, 25, 10, 0, 0))

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "store_id": str(self.store_id),
            "slot_name": self.slot_name,
            "start_time": self.start_time.strftime("%H:%M") if self.start_time else None,
            "end_time": self.end_time.strftime("%H:%M") if self.end_time else None,
            "dining_duration_min": self.dining_duration_min,
            "max_reservations": self.max_reservations,
            "is_active": self.is_active,
            "sort_order": self.sort_order,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 1: GET /configs — 返回空配置
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@patch("src.api.reservation_config_routes.ReservationConfigRepository", autospec=False)
def test_get_configs_empty(MockRepo):
    """门店无预订配置时应返回 rooms=[], time_slots=[]。"""
    db = _make_mock_db()
    mock_repo = AsyncMock()
    mock_repo.list_rooms = AsyncMock(return_value=[])
    mock_repo.list_time_slots = AsyncMock(return_value=[])
    MockRepo.return_value = mock_repo

    client = TestClient(_make_app_with_db(db))
    resp = client.get(
        "/api/v1/reservation/configs",
        params={"store_id": STORE_ID},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["rooms"] == []
    assert data["data"]["time_slots"] == []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 2: POST /configs/rooms — 创建包间成功
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@patch("src.api.reservation_config_routes.ReservationConfigRepository", autospec=False)
def test_create_room_success(MockRepo):
    """正常创建包间应返回 ok=True 及包间详情。"""
    db = _make_mock_db()
    fake_room = _FakeRoom()
    mock_repo = AsyncMock()
    mock_repo.get_room_by_code = AsyncMock(return_value=None)
    mock_repo.create_room = AsyncMock(return_value=fake_room)
    MockRepo.return_value = mock_repo

    client = TestClient(_make_app_with_db(db))
    resp = client.post(
        "/api/v1/reservation/configs/rooms",
        json={
            "store_id": STORE_ID,
            "room_code": "MH01",
            "room_name": "梅花厅",
            "room_type": "private",
            "min_guests": 4,
            "max_guests": 8,
            "deposit_fen": 80000,
        },
        headers=HEADERS,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["room_code"] == "MH01"
    assert data["data"]["room_name"] == "梅花厅"
    assert data["data"]["deposit_fen"] == 80000
    db.commit.assert_awaited_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 3: POST /configs/rooms — room_code 重复 → 400
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@patch("src.api.reservation_config_routes.ReservationConfigRepository", autospec=False)
def test_create_room_duplicate_code(MockRepo):
    """包间编码已存在时应返回 400。"""
    db = _make_mock_db()
    mock_repo = AsyncMock()
    mock_repo.get_room_by_code = AsyncMock(return_value=_FakeRoom())
    MockRepo.return_value = mock_repo

    client = TestClient(_make_app_with_db(db))
    resp = client.post(
        "/api/v1/reservation/configs/rooms",
        json={
            "store_id": STORE_ID,
            "room_code": "MH01",
            "room_name": "梅花厅",
        },
        headers=HEADERS,
    )

    assert resp.status_code == 400


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 4: POST /configs/rooms — max_guests < min_guests → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_create_room_invalid_capacity():
    """max_guests < min_guests 时 Pydantic 校验应失败，返回 422。"""
    db = _make_mock_db()
    client = TestClient(_make_app_with_db(db))
    resp = client.post(
        "/api/v1/reservation/configs/rooms",
        json={
            "store_id": STORE_ID,
            "room_code": "MH01",
            "room_name": "梅花厅",
            "min_guests": 10,
            "max_guests": 4,
        },
        headers=HEADERS,
    )

    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 5: PUT /configs/rooms/{id} — 更新包间名称成功
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@patch("src.api.reservation_config_routes.ReservationConfigRepository", autospec=False)
def test_update_room_success(MockRepo):
    """更新包间名称应返回更新后的配置。"""
    db = _make_mock_db()
    updated_room = _FakeRoom(room_name="梅花厅VIP")
    mock_repo = AsyncMock()
    mock_repo.update_room = AsyncMock(return_value=updated_room)
    MockRepo.return_value = mock_repo

    client = TestClient(_make_app_with_db(db))
    resp = client.put(
        f"/api/v1/reservation/configs/rooms/{ROOM_ID}",
        json={"room_name": "梅花厅VIP"},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["room_name"] == "梅花厅VIP"
    db.commit.assert_awaited_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 6: PUT /configs/rooms/{id} — 不存在 → 404
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@patch("src.api.reservation_config_routes.ReservationConfigRepository", autospec=False)
def test_update_room_not_found(MockRepo):
    """包间不存在时应返回 404。"""
    db = _make_mock_db()
    mock_repo = AsyncMock()
    mock_repo.update_room = AsyncMock(return_value=None)
    MockRepo.return_value = mock_repo

    client = TestClient(_make_app_with_db(db))
    resp = client.put(
        f"/api/v1/reservation/configs/rooms/{ROOM_ID}",
        json={"room_name": "不存在的包间"},
        headers=HEADERS,
    )

    assert resp.status_code == 404


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 7: DELETE /configs/rooms/{id} — 删除成功
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@patch("src.api.reservation_config_routes.ReservationConfigRepository", autospec=False)
def test_delete_room_success(MockRepo):
    """删除包间应返回 deleted=True。"""
    db = _make_mock_db()
    mock_repo = AsyncMock()
    mock_repo.soft_delete_room = AsyncMock(return_value=True)
    MockRepo.return_value = mock_repo

    client = TestClient(_make_app_with_db(db))
    resp = client.delete(
        f"/api/v1/reservation/configs/rooms/{ROOM_ID}",
        headers=HEADERS,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["deleted"] is True
    db.commit.assert_awaited_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 8: DELETE /configs/rooms/{id} — 不存在 → 404
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@patch("src.api.reservation_config_routes.ReservationConfigRepository", autospec=False)
def test_delete_room_not_found(MockRepo):
    """包间不存在时删除应返回 404。"""
    db = _make_mock_db()
    mock_repo = AsyncMock()
    mock_repo.soft_delete_room = AsyncMock(return_value=False)
    MockRepo.return_value = mock_repo

    client = TestClient(_make_app_with_db(db))
    resp = client.delete(
        f"/api/v1/reservation/configs/rooms/{ROOM_ID}",
        headers=HEADERS,
    )

    assert resp.status_code == 404


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 9: GET /configs/time-slots — 返回空列表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@patch("src.api.reservation_config_routes.ReservationConfigRepository", autospec=False)
def test_list_time_slots_empty(MockRepo):
    """无时段配置时应返回空列表。"""
    db = _make_mock_db()
    mock_repo = AsyncMock()
    mock_repo.list_time_slots = AsyncMock(return_value=[])
    MockRepo.return_value = mock_repo

    client = TestClient(_make_app_with_db(db))
    resp = client.get(
        "/api/v1/reservation/configs/time-slots",
        params={"store_id": STORE_ID},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["time_slots"] == []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 10: POST /configs/time-slots — 创建时段成功
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@patch("src.api.reservation_config_routes.ReservationConfigRepository", autospec=False)
def test_create_time_slot_success(MockRepo):
    """正常创建时段应返回 ok=True 及时段详情。"""
    db = _make_mock_db()
    fake_slot = _FakeSlot()
    mock_repo = AsyncMock()
    mock_repo.create_time_slot = AsyncMock(return_value=fake_slot)
    MockRepo.return_value = mock_repo

    client = TestClient(_make_app_with_db(db))
    resp = client.post(
        "/api/v1/reservation/configs/time-slots",
        json={
            "store_id": STORE_ID,
            "slot_name": "午餐",
            "start_time": "11:00",
            "end_time": "14:00",
            "dining_duration_min": 120,
            "max_reservations": 20,
        },
        headers=HEADERS,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["slot_name"] == "午餐"
    assert data["data"]["start_time"] == "11:00"
    assert data["data"]["end_time"] == "14:00"
    db.commit.assert_awaited_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 11: POST /configs/time-slots — end_time <= start_time → 400
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_create_time_slot_invalid_time_range():
    """end_time <= start_time 时应返回 400。"""
    db = _make_mock_db()
    client = TestClient(_make_app_with_db(db))
    resp = client.post(
        "/api/v1/reservation/configs/time-slots",
        json={
            "store_id": STORE_ID,
            "slot_name": "无效时段",
            "start_time": "14:00",
            "end_time": "11:00",
            "dining_duration_min": 120,
        },
        headers=HEADERS,
    )

    assert resp.status_code == 400


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 12: PUT /configs/time-slots/{id} — 更新用餐时长成功
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@patch("src.api.reservation_config_routes.ReservationConfigRepository", autospec=False)
def test_update_time_slot_success(MockRepo):
    """更新用餐时长应返回更新后的配置。"""
    db = _make_mock_db()
    updated_slot = _FakeSlot(dining_duration_min=90)
    mock_repo = AsyncMock()
    mock_repo.update_time_slot = AsyncMock(return_value=updated_slot)
    MockRepo.return_value = mock_repo

    client = TestClient(_make_app_with_db(db))
    resp = client.put(
        f"/api/v1/reservation/configs/time-slots/{SLOT_ID}",
        json={"dining_duration_min": 90},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["dining_duration_min"] == 90
    db.commit.assert_awaited_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 13: PUT /configs/time-slots/{id} — 不存在 → 404
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@patch("src.api.reservation_config_routes.ReservationConfigRepository", autospec=False)
def test_update_time_slot_not_found(MockRepo):
    """时段不存在时应返回 404。"""
    db = _make_mock_db()
    mock_repo = AsyncMock()
    mock_repo.update_time_slot = AsyncMock(return_value=None)
    MockRepo.return_value = mock_repo

    client = TestClient(_make_app_with_db(db))
    resp = client.put(
        f"/api/v1/reservation/configs/time-slots/{SLOT_ID}",
        json={"dining_duration_min": 90},
        headers=HEADERS,
    )

    assert resp.status_code == 404


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 14: GET /available — 无 DB 配置时 fallback 返回数据
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@patch("src.api.reservation_config_routes.ReservationService", autospec=False)
def test_get_available_fallback(MockService):
    """无数据库配置时应 fallback 到硬编码配置并返回数据。"""
    db = _make_mock_db()
    mock_svc = AsyncMock()
    mock_svc.get_available_rooms = AsyncMock(
        return_value=[
            {
                "room_code": "梅花厅",
                "room_name": "梅花厅",
                "room_type": "private",
                "min_guests": 4,
                "max_guests": 8,
                "deposit_fen": 80000,
                "available": True,
                "conflict_count": 0,
            }
        ]
    )
    mock_svc.get_available_time_slots = AsyncMock(
        return_value=[
            {
                "time": "11:00",
                "meal": "lunch",
                "label": "午餐 11:00",
                "available": True,
                "conflict_count": 0,
                "reason": "",
            }
        ]
    )
    MockService.return_value = mock_svc

    client = TestClient(_make_app_with_db(db))
    resp = client.get(
        "/api/v1/reservation/available",
        params={"store_id": STORE_ID, "date": "2026-05-01", "guest_count": 6},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert len(data["data"]["rooms"]) >= 1
    assert len(data["data"]["time_slots"]) >= 1
    assert data["data"]["date"] == "2026-05-01"
    assert data["data"]["guest_count"] == 6


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 15: GET /available — 缺少必填参数 → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_get_available_missing_params():
    """缺少 store_id 或 date 时应返回 422。"""
    db = _make_mock_db()
    client = TestClient(_make_app_with_db(db))

    # 缺少 store_id
    resp = client.get(
        "/api/v1/reservation/available",
        params={"date": "2026-05-01"},
        headers=HEADERS,
    )
    assert resp.status_code == 422

    # 缺少 date
    resp = client.get(
        "/api/v1/reservation/available",
        params={"store_id": STORE_ID},
        headers=HEADERS,
    )
    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 16: GET /available — 缺少 tenant_id → 401
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_get_available_missing_tenant_id():
    """缺少 X-Tenant-ID header 时应返回 401。"""
    db = _make_mock_db()
    client = TestClient(_make_app_with_db(db))
    resp = client.get(
        "/api/v1/reservation/available",
        params={"store_id": STORE_ID, "date": "2026-05-01"},
        # 不传 X-Tenant-ID
    )
    assert resp.status_code == 401
