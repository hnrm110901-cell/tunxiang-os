"""客户预订 & 排队 API 测试 — customer_booking_routes.py

覆盖场景（共 8 个）：
1. GET  /available-slots — 返回 slots 数组，不含 11:00-21:00 以外时段
2. POST /booking/create — 正常路径：DB 成功查到门店名
3. POST /booking/create — DB 异常 fallback：store_name 默认"门店"，仍创建成功
4. GET  /booking/list — 返回该租户的预订列表（按 store_id 过滤）
5. POST /booking/{id}/cancel — 取消已存在预订
6. POST /booking/{id}/cancel — 预订不存在时返回 ok=False
7. POST /queue/take — 成功取号，ticket_no 前缀正确
8. POST /queue/take — 重复取号时返回 ok=False
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

import api.customer_booking_routes as cbr_mod
from api.customer_booking_routes import router
from shared.ontology.src.database import get_db


# ─── 工具 ──────────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID  = str(uuid.uuid4())

_BASE_HEADERS = {
    "X-Tenant-ID": TENANT_ID,
    "X-Store-ID":  STORE_ID,
}


def _make_db():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=AsyncMock(scalar=MagicMock(return_value=None)))
    db.commit  = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _override_db(db):
    def _dep():
        return db
    return _dep


def _make_app(db):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = _override_db(db)
    return app


@pytest.fixture(autouse=True)
def clear_memory_state():
    """每个测试前清空内存存储，避免测试间互相干扰"""
    cbr_mod._bookings.clear()
    cbr_mod._queue_tickets.clear()
    yield
    cbr_mod._bookings.clear()
    cbr_mod._queue_tickets.clear()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 1: GET /api/v1/trade/booking/available-slots — 返回 slots
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_available_slots_returns_correct_structure():
    """available-slots 应返回 11:00-20:30 的时段数组（20 个），ok=True"""
    db = _make_db()
    app = _make_app(db)
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/trade/booking/available-slots?store_id={STORE_ID}&date=2099-12-31",
        headers=_BASE_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    slots = body["data"]["slots"]
    assert len(slots) == 20                       # 11:00-20:30，每30分钟，共20个
    times = [s["time"] for s in slots]
    assert "11:00" in times
    assert "20:30" in times
    assert all(s["status"] in ("available", "full", "unavailable") for s in slots)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 2: POST /booking/create — DB 成功查到门店名
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_create_booking_with_store_name_from_db():
    """DB 能查到门店名时，booking.store_name 应为真实门店名"""
    db = _make_db()
    # set_config 调用 → scalar_one_or_none, 门店查询 → scalar 返回门店名
    set_cfg_result = MagicMock()
    store_result   = MagicMock()
    store_result.scalar = MagicMock(return_value="徐记海鲜万宝店")
    db.execute = AsyncMock(side_effect=[set_cfg_result, store_result])

    app = _make_app(db)
    client = TestClient(app)
    payload = {
        "store_id":        STORE_ID,
        "customer_id":     str(uuid.uuid4()),
        "date":            "2026-07-01",
        "time_slot":       "18:00",
        "guests":          4,
        "room_preference": "hall",
        "remark":          "不要辣",
    }
    resp = client.post(
        "/api/v1/booking/create",
        json=payload,
        headers=_BASE_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["store_name"] == "徐记海鲜万宝店"
    assert body["data"]["status"] == "pending"
    assert "id" in body["data"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 3: POST /booking/create — DB 异常 fallback，store_name 默认"门店"
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_create_booking_db_error_fallback_store_name():
    """DB 查询门店名出错时应 fallback 使用'门店'，预订仍成功创建"""
    import api.customer_booking_routes as cbr_api  # noqa: PLC0415

    db = _make_db()
    db.execute = AsyncMock(
        side_effect=SQLAlchemyError("connection refused")
    )

    app = _make_app(db)
    # patch 掉 logger.warning 避免标准库不支持 extra kwargs 报 TypeError
    with patch.object(cbr_api.logger, "warning"):
        client = TestClient(app)
        payload = {
            "store_id":  STORE_ID,
            "date":      "2026-07-02",
            "time_slot": "19:00",
            "guests":    2,
        }
        resp = client.post(
            "/api/v1/booking/create",
            json=payload,
            headers=_BASE_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["store_name"] == "门店"    # fallback 值


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 4: GET /booking/list — 按 store_id 过滤列表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_list_bookings_filtered_by_store_id():
    """list 接口按 store_id 过滤后，只返回该门店的预订"""
    db = _make_db()
    db.execute = AsyncMock(
        side_effect=SQLAlchemyError("no db needed for list")
    )

    # 预先往内存存储放两条数据（不同 store_id）
    store_a = STORE_ID
    store_b = str(uuid.uuid4())
    cbr_mod._bookings[TENANT_ID] = [
        {"id": "b1", "store_id": store_a, "customer_id": "", "date": "2026-07-01",
         "time_slot": "18:00", "status": "pending", "created_at": "2026-07-01T10:00:00"},
        {"id": "b2", "store_id": store_b, "customer_id": "", "date": "2026-07-01",
         "time_slot": "19:00", "status": "pending", "created_at": "2026-07-01T10:01:00"},
    ]

    app = _make_app(db)
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/booking/list?store_id={store_a}",
        headers=_BASE_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 1
    assert body["data"]["items"][0]["id"] == "b1"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 5: POST /booking/{id}/cancel — 成功取消
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_cancel_booking_ok():
    """存在的预订取消后 status 应变为 cancelled，ok=True"""
    booking_id = str(uuid.uuid4())
    cbr_mod._bookings[TENANT_ID] = [
        {"id": booking_id, "store_id": STORE_ID, "customer_id": "",
         "status": "pending", "created_at": "2026-07-01T10:00:00"},
    ]

    db = _make_db()
    app = _make_app(db)
    client = TestClient(app)
    resp = client.post(
        f"/api/v1/booking/{booking_id}/cancel",
        headers=_BASE_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "cancelled"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 6: POST /booking/{id}/cancel — 预订不存在返回 ok=False
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_cancel_booking_not_found():
    """不存在的 booking_id 应返回 ok=False，error 非空"""
    db = _make_db()
    app = _make_app(db)
    client = TestClient(app)
    resp = client.post(
        f"/api/v1/booking/{uuid.uuid4()}/cancel",
        headers=_BASE_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"] is not None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 7: POST /queue/take — 成功取号，ticket_no 前缀正确
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_take_queue_success():
    """1-2人范围对应 small 桌，ticket_no 前缀应为 S"""
    db = _make_db()
    app = _make_app(db)
    client = TestClient(app)
    payload = {
        "store_id":    STORE_ID,
        "customer_id": str(uuid.uuid4()),
        "guest_range": "1-2",
    }
    resp = client.post(
        "/api/v1/queue/take",
        json=payload,
        headers=_BASE_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["ticketNo"].startswith("S")
    assert body["data"]["status"] == "waiting"
    assert body["data"]["table_type"] == "small"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 8: POST /queue/take — 重复取号返回 ok=False
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_take_queue_duplicate():
    """同一客户已在排队时再次取号应返回 ok=False"""
    customer_id = str(uuid.uuid4())
    # 预先放一条 waiting 状态的票
    cbr_mod._queue_tickets[STORE_ID] = [
        {
            "id": str(uuid.uuid4()),
            "customer_id": customer_id,
            "status": "waiting",
            "table_type": "medium",
            "created_at": "2026-07-01T10:00:00",
        }
    ]

    db = _make_db()
    app = _make_app(db)
    client = TestClient(app)
    payload = {
        "store_id":    STORE_ID,
        "customer_id": customer_id,
        "guest_range": "3-4",
    }
    resp = client.post(
        "/api/v1/queue/take",
        json=payload,
        headers=_BASE_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "排队" in body["error"]["message"]
