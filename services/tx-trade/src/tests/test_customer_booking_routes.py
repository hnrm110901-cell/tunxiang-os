"""Customer-facing booking & queue API 测试 — customer_booking_routes.py

覆盖场景（共 10 个）：
1.  test_create_booking_success        — mock INSERT RETURNING 成功 → 200，data 含 id
2.  test_create_booking_db_error       — mock SQLAlchemyError → 200，ok=False
3.  test_list_bookings_success         — mock SELECT 返回 2 条 → 200，data.items 长度=2
4.  test_list_bookings_empty           — mock SELECT 返回空 → 200，data.items=[]
5.  test_cancel_booking_success        — mock UPDATE RETURNING 1 行 → 200，ok=True
6.  test_cancel_booking_not_found      — mock UPDATE RETURNING 空 → 200，ok=False
7.  test_queue_take_success            — mock COUNT=2 → ticket_no="A003"，200，ok=True
8.  test_queue_my_ticket_success       — mock SELECT 1 条 ticket → 200，含 ticketNo
9.  test_queue_my_ticket_not_found     — mock SELECT 空，ticket_id 传空 → 200，data=None
10. test_queue_cancel_success          — mock UPDATE RETURNING 1 行 → 200，ok=True
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from api.customer_booking_routes import router
from shared.ontology.src.database import get_db

# ─── 常量 ────────────────────────────────────────────────────────────────────

TENANT = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())

_HEADERS = {
    "X-Tenant-ID": TENANT,
}

_NOW = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)


# ─── 辅助工厂 ────────────────────────────────────────────────────────────────

def mock_db() -> AsyncMock:
    """返回一个最小可用的 AsyncSession mock。"""
    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


_SENTINEL = object()  # 区分"未传"与"显式传 None"


def _make_result(
    *,
    one=_SENTINEL,
    first=_SENTINEL,
    all_rows=_SENTINEL,
    scalar_val=None,
) -> MagicMock:
    """构造 db.execute() 返回值，支持 .mappings().one/first/all 以及 .scalar()。

    使用 _SENTINEL 哨兵区分"调用者未指定"与"显式传 None"，确保
    _make_result(first=None) 能正确令 mappings().first() 返回 None。
    """
    result = MagicMock()

    # scalar() —— 用于 COUNT 查询
    result.scalar = MagicMock(return_value=scalar_val)

    # mappings() 链式调用
    mappings_obj = MagicMock()

    if one is not _SENTINEL:
        mappings_obj.one = MagicMock(return_value=one)
    if first is not _SENTINEL:
        mappings_obj.first = MagicMock(return_value=first)
    if all_rows is not _SENTINEL:
        # mappings() 直接可迭代
        mappings_obj.__iter__ = MagicMock(return_value=iter(all_rows))
        mappings_obj.all = MagicMock(return_value=all_rows)

    result.mappings = MagicMock(return_value=mappings_obj)
    return result


def _make_app(db: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    return app


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. test_create_booking_success
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_create_booking_success():
    """INSERT RETURNING 成功 → HTTP 200，ok=True，data 含 id 字段。"""
    booking_id = str(uuid.uuid4())

    # create_booking 执行 2 次 db.execute：
    #   [0] _set_tenant → set_config（返回值不关心）
    #   [1] INSERT RETURNING → rec = row.mappings().one()
    set_cfg_result = MagicMock()

    rec_row = {
        "id": uuid.UUID(booking_id),
        "status": "pending",
        "created_at": _NOW,
    }
    insert_result = _make_result(one=rec_row)

    db = mock_db()
    db.execute = AsyncMock(side_effect=[set_cfg_result, insert_result])

    app = _make_app(db)
    client = TestClient(app)

    payload = {
        "store_id": STORE_ID,
        "customer_name": "张三",
        "customer_phone": "13800138000",
        "party_size": 3,
        "booking_date": "2026-07-10",
        "booking_time": "18:00",
    }
    resp = client.post("/api/v1/booking/create", json=payload, headers=_HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["id"] == booking_id
    assert body["data"]["status"] == "pending"
    assert "customer_name" in body["data"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. test_create_booking_db_error
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_create_booking_db_error():
    """SQLAlchemyError → HTTP 200，ok=False，error 非空。

    路由捕获 SQLAlchemyError 后返回 _err_resp() 而非抛出 HTTP 5xx，
    因此 status_code 仍为 200。
    """
    db = mock_db()
    db.execute = AsyncMock(side_effect=SQLAlchemyError("connection refused"))

    app = _make_app(db)
    client = TestClient(app)

    payload = {
        "store_id": STORE_ID,
        "customer_name": "李四",
        "customer_phone": "13900139000",
        "party_size": 2,
        "booking_date": "2026-07-11",
        "booking_time": "19:00",
    }
    resp = client.post("/api/v1/booking/create", json=payload, headers=_HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"] is not None
    assert body["error"]["message"]  # 非空字符串


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. test_list_bookings_success
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_list_bookings_success():
    """SELECT 返回 2 条记录 → HTTP 200，ok=True，data.items 长度=2。"""
    store_uuid = uuid.UUID(STORE_ID)

    def _make_row(idx: int) -> dict:
        return {
            "id": uuid.uuid4(),
            "store_id": store_uuid,
            "customer_name": f"顾客{idx}",
            "customer_phone": f"1380013800{idx}",
            "party_size": 2,
            "booking_date": "2026-07-10",
            "booking_time": "18:00",
            "table_type": None,
            "special_request": None,
            "status": "pending",
            "source": "miniapp",
            "cancelled_at": None,
            "cancel_reason": None,
            "created_at": _NOW,
            "updated_at": _NOW,
        }

    rows = [_make_row(1), _make_row(2)]

    # list_bookings 执行 2 次 db.execute：
    #   [0] _set_tenant
    #   [1] SELECT → rows.mappings() 可迭代
    set_cfg_result = MagicMock()
    select_result = _make_result(all_rows=rows)

    db = mock_db()
    db.execute = AsyncMock(side_effect=[set_cfg_result, select_result])

    app = _make_app(db)
    client = TestClient(app)

    resp = client.get(
        f"/api/v1/booking/list?store_id={STORE_ID}",
        headers=_HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert len(body["data"]["items"]) == 2
    assert body["data"]["total"] == 2


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. test_list_bookings_empty
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_list_bookings_empty():
    """SELECT 返回空 → HTTP 200，ok=True，data.items=[]。"""
    set_cfg_result = MagicMock()
    select_result = _make_result(all_rows=[])

    db = mock_db()
    db.execute = AsyncMock(side_effect=[set_cfg_result, select_result])

    app = _make_app(db)
    client = TestClient(app)

    resp = client.get(
        f"/api/v1/booking/list?store_id={STORE_ID}",
        headers=_HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["items"] == []
    assert body["data"]["total"] == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. test_cancel_booking_success
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_cancel_booking_success():
    """UPDATE RETURNING 1 行 → HTTP 200，ok=True，data.status='cancelled'。"""
    booking_id = str(uuid.uuid4())

    set_cfg_result = MagicMock()
    update_result = _make_result(first={"id": uuid.UUID(booking_id)})

    db = mock_db()
    db.execute = AsyncMock(side_effect=[set_cfg_result, update_result])

    app = _make_app(db)
    client = TestClient(app)

    resp = client.post(
        f"/api/v1/booking/{booking_id}/cancel",
        headers=_HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["id"] == booking_id
    assert body["data"]["status"] == "cancelled"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 6. test_cancel_booking_not_found
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_cancel_booking_not_found():
    """UPDATE RETURNING 空（rec=None） → HTTP 200，ok=False（路由返回 _err_resp）。

    注意：路由未使用 HTTPException，不存在时仍返回 HTTP 200 + ok=False。
    """
    set_cfg_result = MagicMock()
    update_result = _make_result(first=None)

    db = mock_db()
    db.execute = AsyncMock(side_effect=[set_cfg_result, update_result])

    app = _make_app(db)
    client = TestClient(app)

    resp = client.post(
        f"/api/v1/booking/{uuid.uuid4()}/cancel",
        headers=_HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"] is not None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 7. test_queue_take_success
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_queue_take_success():
    """当日已有 2 条记录 → ticket_no='A003'，HTTP 200，ok=True。

    take_queue 执行 3 次 db.execute：
      [0] _set_tenant
      [1] COUNT 当日记录 → scalar=2
      [2] INSERT RETURNING → rec = row.mappings().one()
      [3] COUNT waiting → scalar=1（ahead = max(0, 1-1) = 0）
    """
    ticket_uuid = uuid.uuid4()

    set_cfg_result = MagicMock()
    count_today_result = _make_result(scalar_val=2)          # 已有 2 条，下一个 = A003
    insert_result = _make_result(one={
        "id": ticket_uuid,
        "status": "waiting",
        "created_at": _NOW,
    })
    count_waiting_result = _make_result(scalar_val=1)        # waiting=1，ahead=0

    db = mock_db()
    db.execute = AsyncMock(side_effect=[
        set_cfg_result,
        count_today_result,
        insert_result,
        count_waiting_result,
    ])

    app = _make_app(db)
    client = TestClient(app)

    payload = {
        "store_id": STORE_ID,
        "customer_name": "王五",
        "customer_phone": "13700137000",
        "party_size": 2,
        "queue_type": "normal",
    }
    resp = client.post("/api/v1/queue/take", json=payload, headers=_HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["ticketNo"] == "A003"
    assert body["data"]["status"] == "waiting"
    assert body["data"]["ahead"] == 0
    assert body["data"]["id"] == str(ticket_uuid)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 8. test_queue_my_ticket_success
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_queue_my_ticket_success():
    """SELECT 1 条 ticket → HTTP 200，ok=True，data 含 ticketNo 字段。

    my_ticket 执行 3 次 db.execute（当 ticket 存在时）：
      [0] _set_tenant
      [1] SELECT ticket → rec = row.mappings().first()
      [2] COUNT ahead → scalar=0
    """
    ticket_id = str(uuid.uuid4())
    store_uuid = uuid.UUID(STORE_ID)

    set_cfg_result = MagicMock()
    ticket_rec = {
        "id": uuid.UUID(ticket_id),
        "store_id": store_uuid,
        "ticket_no": "A001",
        "customer_name": "赵六",
        "customer_phone": "13600136000",
        "party_size": 2,
        "queue_type": "normal",
        "status": "waiting",
        "called_at": None,
        "seated_at": None,
        "cancelled_at": None,
        "wait_minutes": None,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    select_result = _make_result(first=ticket_rec)
    count_ahead_result = _make_result(scalar_val=0)

    db = mock_db()
    db.execute = AsyncMock(side_effect=[
        set_cfg_result,
        select_result,
        count_ahead_result,
    ])

    app = _make_app(db)
    client = TestClient(app)

    resp = client.get(
        f"/api/v1/queue/my-ticket?store_id={STORE_ID}&ticket_id={ticket_id}",
        headers=_HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["ticketNo"] == "A001"
    assert body["data"]["id"] == ticket_id
    assert body["data"]["status"] == "waiting"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 9. test_queue_my_ticket_not_found
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_queue_my_ticket_not_found():
    """ticket_id 未传（空字符串）→ 路由提前返回 ok=True，data=None（不查 DB）。

    路由逻辑：
        if not ticket_id:
            return _ok(None)
    因此 data=None，无 DB 调用。
    """
    db = mock_db()
    app = _make_app(db)
    client = TestClient(app)

    resp = client.get(
        f"/api/v1/queue/my-ticket?store_id={STORE_ID}",
        headers=_HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"] is None
    # 确认 DB 未被调用
    db.execute.assert_not_called()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 10. test_queue_cancel_success
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_queue_cancel_success():
    """UPDATE RETURNING 1 行 → HTTP 200，ok=True，data.status='cancelled'。"""
    ticket_id = str(uuid.uuid4())

    set_cfg_result = MagicMock()
    update_result = _make_result(first={
        "id": uuid.UUID(ticket_id),
        "ticket_no": "A001",
    })

    db = mock_db()
    db.execute = AsyncMock(side_effect=[set_cfg_result, update_result])

    app = _make_app(db)
    client = TestClient(app)

    resp = client.post(
        f"/api/v1/queue/{ticket_id}/cancel",
        headers=_HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["id"] == ticket_id
    assert body["data"]["status"] == "cancelled"
