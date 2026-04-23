"""优惠策略 API 路由测试 — api/offer_routes.py

覆盖场景：
1.  POST /api/v1/offers                         — 正常创建，返回 offer_id 和 goal
2.  POST /api/v1/offers                         — 缺少 name → 422
3.  POST /api/v1/offers                         — 非法 offer_type → 422
4.  GET  /api/v1/offers                         — 正常返回 items/total
5.  GET  /api/v1/offers                         — DB 表不存在时 fallback 空列表
6.  GET  /api/v1/offers/recommend/{segment}     — DB 无数据时返回内置模板（source=template）
7.  GET  /api/v1/offers/recommend/{segment}     — DB 有数据时返回 source=db
8.  GET  /api/v1/offers/recommend/{segment}     — 未知 segment 返回通用模板（ok=True）
9.  POST /api/v1/offers                         — DB 表不存在时返回 TABLE_NOT_READY
10. POST /api/v1/offers                         — margin_floor 超出 [0,1] → 422
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

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


def _make_db(*execute_results):
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=list(execute_results))
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


# ── 加载路由 ────────────────────────────────────────────────────────────────

from api.offer_routes import get_db, router

app = FastAPI()
app.include_router(router)


def _override(db):
    def _dep():
        return db

    return _dep


_NOW = datetime(2026, 4, 4, 10, 0, tzinfo=timezone.utc)


def _offer_row():
    return _FakeRow(
        id=uuid.uuid4(),
        name="新客首单立减20",
        offer_type="new_customer_trial",
        description="新客首单体验优惠",
        goal="acquisition",
        discount_rules=json.dumps({"type": "fixed_amount", "amount_fen": 2000}),
        validity_days=30,
        target_segments=json.dumps(["new_customer"]),
        applicable_stores=json.dumps([]),
        time_slots=json.dumps([]),
        margin_floor=0.45,
        max_per_user=1,
        status="active",
        issued_count=100,
        redeemed_count=60,
        total_discount_fen=120000,
        created_at=_NOW,
        updated_at=_NOW,
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 1: POST /offers — 正常创建
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_create_offer_ok():
    """正常创建优惠，返回 offer_id 和 goal"""
    set_cfg = AsyncMock()
    insert_result = AsyncMock()

    db = _make_db(set_cfg, insert_result)
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/offers",
        json={
            "name": "新客首单立减20",
            "offer_type": "new_customer_trial",
            "discount_rules": {"type": "fixed_amount", "amount_fen": 2000},
            "validity_days": 30,
        },
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert "offer_id" in data
    assert data["offer_type"] == "new_customer_trial"
    assert data["goal"] == "acquisition"
    assert data["status"] == "active"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 2: POST /offers — 缺少 name → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_create_offer_missing_name():
    """name 为必填，缺少时应返回 422"""
    db = AsyncMock()
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/offers",
        json={"offer_type": "new_customer_trial", "discount_rules": {}},
        headers=_HEADERS,
    )
    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 3: POST /offers — 非法 offer_type → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_create_offer_invalid_type():
    """offer_type 不在允许列表时应返回 422"""
    db = AsyncMock()
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/offers",
        json={
            "name": "测试优惠",
            "offer_type": "invalid_offer_type_xyz",
            "discount_rules": {"type": "fixed_amount", "amount_fen": 1000},
        },
        headers=_HEADERS,
    )
    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 4: GET /offers — 正常返回列表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_list_offers_ok():
    """返回 items/total 分页结构"""
    set_cfg = AsyncMock()

    count_result = AsyncMock()
    count_result.scalar = MagicMock(return_value=1)

    rows_result = AsyncMock()
    rows_result.fetchall = MagicMock(return_value=[_offer_row()])

    db = _make_db(set_cfg, count_result, rows_result)
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.get("/api/v1/offers", headers=_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["name"] == "新客首单立减20"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 5: GET /offers — DB 表不存在时 fallback 空列表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_list_offers_table_not_ready():
    """表不存在时 graceful 返回空列表，ok=True"""
    db = _make_db(
        AsyncMock(),  # set_config
        OperationalError("stmt", {}, Exception("relation offers does not exist")),
    )
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.get("/api/v1/offers", headers=_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 0
    assert body["data"]["items"] == []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 6: GET /recommend/{segment} — DB 无数据返回模板
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_recommend_offer_fallback_to_template():
    """DB 无匹配优惠时返回内置模板，source=template"""
    set_cfg = AsyncMock()
    rows_result = AsyncMock()
    rows_result.fetchall = MagicMock(return_value=[])  # 无 DB 数据

    db = _make_db(set_cfg, rows_result)
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.get("/api/v1/offers/recommend/new_customer", headers=_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["source"] == "template"
    assert data["segment_id"] == "new_customer"
    assert len(data["recommendations"]) > 0
    assert data["recommendations"][0].get("source") == "template"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 7: GET /recommend/{segment} — DB 有数据返回 source=db
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_recommend_offer_from_db():
    """DB 有匹配优惠时返回 source=db"""
    set_cfg = AsyncMock()

    db_row = _FakeRow(
        id=uuid.uuid4(),
        offer_type="new_customer_trial",
        name="新客专属优惠",
        description="新客首单体验优惠",
        goal="acquisition",
        discount_rules=json.dumps({"type": "fixed_amount", "amount_fen": 2000}),
        validity_days=30,
        margin_floor=0.45,
        issued_count=50,
        redeemed_count=30,
        total_discount_fen=60000,
    )

    rows_result = AsyncMock()
    rows_result.fetchall = MagicMock(return_value=[db_row])

    db = _make_db(set_cfg, rows_result)
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.get("/api/v1/offers/recommend/new_customer", headers=_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["source"] == "db"
    assert data["recommendations"][0]["source"] == "db"
    assert data["recommendations"][0]["name"] == "新客专属优惠"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 8: GET /recommend/{segment} — 未知 segment 返回通用模板
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_recommend_offer_unknown_segment():
    """未知 segment 不报错，返回通用兜底模板，ok=True"""
    set_cfg = AsyncMock()
    rows_result = AsyncMock()
    rows_result.fetchall = MagicMock(return_value=[])

    db = _make_db(set_cfg, rows_result)
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.get("/api/v1/offers/recommend/unknown_segment_xyz", headers=_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert len(body["data"]["recommendations"]) > 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 9: POST /offers — DB 表不存在返回 TABLE_NOT_READY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_create_offer_table_not_ready():
    """DB 表不存在时返回 TABLE_NOT_READY 错误码"""
    db = _make_db(
        AsyncMock(),  # set_config
        OperationalError("stmt", {}, Exception("relation offers does not exist")),
    )
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/offers",
        json={
            "name": "新品尝鲜",
            "offer_type": "new_dish_trial",
            "discount_rules": {"type": "fixed_amount", "amount_fen": 1500},
        },
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "TABLE_NOT_READY"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 10: POST /offers — margin_floor 超出范围 → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_create_offer_invalid_margin_floor():
    """margin_floor 超出 [0,1] 时应返回 422"""
    db = AsyncMock()
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/offers",
        json={
            "name": "超高折扣",
            "offer_type": "second_visit",
            "discount_rules": {"type": "percentage", "pct": 50},
            "margin_floor": 1.5,  # 超出 [0,1]
        },
        headers=_HEADERS,
    )
    assert resp.status_code == 422
