"""优惠券 API 路由测试 — api/coupon_routes.py

覆盖场景：
1.  GET  /api/v1/growth/coupons/available     — 正常路径返回优惠券列表
2.  GET  /api/v1/growth/coupons/available     — DB 表不存在时 fallback 返回空列表
3.  POST /api/v1/growth/coupons/claim         — 正常领取返回 customer_coupon_id
4.  POST /api/v1/growth/coupons/claim         — 缺少 coupon_id → 422
5.  POST /api/v1/growth/coupons/claim         — DB 表不存在时返回 TABLE_NOT_READY
6.  POST /api/v1/growth/coupons/verify        — 正常核销返回 status=used
7.  POST /api/v1/growth/coupons/verify        — 缺少 customer_coupon_id → 422
8.  GET  /api/v1/growth/coupons/my            — 重定向提示返回 redirect 字段
9.  POST /api/v1/growth/coupons/{id}/apply    — 订单金额不足返回 ORDER_AMOUNT_TOO_LOW
10. POST /api/v1/growth/coupons/{id}/apply    — 缺少 order_id → 422
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from datetime import date, datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

TENANT_ID = str(uuid.uuid4())
_HEADERS = {"X-Tenant-ID": TENANT_ID, "Authorization": "Bearer test"}


# ── 工具 ────────────────────────────────────────────────────────────────────

class _FakeRow:
    """模拟 SQLAlchemy named-column row"""
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

    def __getattr__(self, name):
        raise AttributeError(name)


def _execute_seq(*results):
    return AsyncMock(side_effect=list(results))


def _make_db(*execute_results):
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=list(execute_results))
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


# ── 加载路由（patch emit_event + get_db） ────────────────────────────────────

with patch("shared.events.src.emitter.emit_event", new=AsyncMock()):
    from api.coupon_routes import router, get_db

app = FastAPI()
app.include_router(router)


def _override(db):
    def _dep():
        return db
    return _dep


# ── 复用 mock 行 ─────────────────────────────────────────────────────────────

def _coupon_row():
    return _FakeRow(
        id=uuid.uuid4(),
        name="新客首单立减20",
        coupon_type="cash",
        discount_rate=None,
        cash_amount_fen=2000,
        min_order_fen=5000,
        max_claim_per_user=1,
        total_quantity=100,
        claimed_count=10,
        expiry_days=30,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        is_active=True,
    )


def _customer_coupon_row():
    return _FakeRow(
        id=uuid.uuid4(),
        coupon_id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
        status="unused",
        expire_at=datetime.now(timezone.utc) + timedelta(days=30),
        coupon_name="新客首单立减20",
        cash_amount_fen=2000,
        discount_rate=None,
        coupon_type="cash",
    )


def _apply_row():
    return _FakeRow(
        cc_id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
        status="unused",
        expire_at=datetime.now(timezone.utc) + timedelta(days=30),
        coupon_name="新客立减20",
        cash_amount_fen=2000,
        discount_rate=None,
        coupon_type="cash",
        minimum_amount_fen=5000,
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 1: GET /available — 正常路径
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_list_available_coupons_ok():
    """返回可领取优惠券列表"""
    set_cfg = AsyncMock()
    rows_result = AsyncMock()
    rows_result.fetchall = MagicMock(return_value=[_coupon_row()])

    db = _make_db(set_cfg, rows_result)
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.get("/api/v1/growth/coupons/available", headers=_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 1
    assert body["data"]["items"][0]["name"] == "新客首单立减20"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 2: GET /available — DB 表不存在 fallback
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_list_available_coupons_table_not_ready():
    """表不存在时 graceful 返回空列表，ok=True"""
    db = _make_db(
        AsyncMock(),  # set_config 正常
        OperationalError("stmt", {}, Exception("relation coupons does not exist")),
    )
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.get("/api/v1/growth/coupons/available", headers=_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 0
    assert body["data"]["items"] == []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 3: POST /claim — 正常领取
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_claim_coupon_ok():
    """正常领取返回 customer_coupon_id"""
    coupon_id = str(uuid.uuid4())
    customer_id = str(uuid.uuid4())

    # execute 调用顺序：set_config → dup_check → coupon_info → insert → update
    set_cfg = AsyncMock()

    dup_result = AsyncMock()
    dup_result.fetchone = MagicMock(return_value=None)  # 未领取

    coupon_result = AsyncMock()
    coupon_result.fetchone = MagicMock(return_value=_coupon_row())

    insert_result = AsyncMock()
    update_result = AsyncMock()

    db = _make_db(set_cfg, dup_result, coupon_result, insert_result, update_result)
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/growth/coupons/claim",
        json={"coupon_id": coupon_id, "customer_id": customer_id},
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "customer_coupon_id" in body["data"]
    assert body["data"]["status"] == "unused"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 4: POST /claim — 缺少 coupon_id → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_claim_missing_coupon_id():
    """coupon_id 为必填，缺少时应返回 422"""
    db = AsyncMock()
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/growth/coupons/claim",
        json={"customer_id": str(uuid.uuid4())},
        headers=_HEADERS,
    )
    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 5: POST /claim — DB 表不存在时 TABLE_NOT_READY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_claim_table_not_ready():
    """表不存在时返回 TABLE_NOT_READY 错误码"""
    coupon_id = str(uuid.uuid4())
    customer_id = str(uuid.uuid4())

    db = _make_db(
        AsyncMock(),  # set_config
        OperationalError("stmt", {}, Exception("relation customer_coupons does not exist")),
    )
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/growth/coupons/claim",
        json={"coupon_id": coupon_id, "customer_id": customer_id},
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "TABLE_NOT_READY"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 6: POST /verify — 正常核销
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_verify_coupon_ok():
    """核销成功，返回 status=used"""
    cc_id = str(uuid.uuid4())
    customer_id = str(uuid.uuid4())

    row = _customer_coupon_row()
    row.customer_id = uuid.UUID(customer_id)  # 确保归属校验通过

    set_cfg = AsyncMock()
    query_result = AsyncMock()
    query_result.fetchone = MagicMock(return_value=row)
    update_result = AsyncMock()

    db = _make_db(set_cfg, query_result, update_result)
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/growth/coupons/verify",
        json={"customer_coupon_id": cc_id, "customer_id": customer_id},
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "used"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 7: POST /verify — 缺少 customer_coupon_id → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_verify_missing_customer_coupon_id():
    """customer_coupon_id 为必填，缺少时应返回 422"""
    db = AsyncMock()
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/growth/coupons/verify",
        json={"customer_id": str(uuid.uuid4())},
        headers=_HEADERS,
    )
    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 8: GET /my — 重定向提示
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_my_coupons_redirect():
    """返回 redirect 字段，指向 tx-member"""
    db = AsyncMock()
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.get("/api/v1/growth/coupons/my", headers=_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "redirect" in body["data"]
    assert "/api/v1/member/coupons" in body["data"]["redirect"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 9: POST /{id}/apply — 订单金额不足
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_apply_coupon_order_amount_too_low():
    """订单金额未达到门槛时返回 ORDER_AMOUNT_TOO_LOW"""
    coupon_id = str(uuid.uuid4())
    row = _apply_row()
    row.minimum_amount_fen = 10000  # 门槛 100 元

    set_cfg = AsyncMock()
    query_result = AsyncMock()
    query_result.fetchone = MagicMock(return_value=row)

    db = _make_db(set_cfg, query_result)
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.post(
        f"/api/v1/growth/coupons/{coupon_id}/apply",
        json={
            "order_id": str(uuid.uuid4()),
            "store_id": str(uuid.uuid4()),
            "order_amount_fen": 5000,  # 只有 50 元，不足门槛
            "operator_id": "op-001",
        },
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "ORDER_AMOUNT_TOO_LOW"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 10: POST /{id}/apply — 缺少 order_id → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_apply_coupon_missing_order_id():
    """order_id 为必填，缺少时应返回 422"""
    coupon_id = str(uuid.uuid4())
    db = AsyncMock()
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.post(
        f"/api/v1/growth/coupons/{coupon_id}/apply",
        json={"store_id": str(uuid.uuid4()), "order_amount_fen": 8000, "operator_id": "op-001"},
        headers=_HEADERS,
    )
    assert resp.status_code == 422
