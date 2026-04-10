"""营销方案路由测试 — api/marketing.py

覆盖场景：
1.  GET  /api/v1/member/marketing-schemes          — mock SELECT 返回2条方案 → 200，data.items 长度=2
2.  GET  /api/v1/member/marketing-schemes          — mock SELECT 返回空 → 200，data.items=[]
3.  POST /api/v1/member/marketing-schemes          — mock INSERT RETURNING 成功 → 200，data 含 id
4.  POST /api/v1/member/marketing-schemes          — mock SQLAlchemyError → ok=False
5.  POST /api/v1/member/marketing-schemes/calculate — DB 返回1条 order_discount 方案(rate=90)，total_fen=10000 → final=9000
6.  POST /api/v1/member/marketing-schemes/calculate — DB 返回空方案列表 → 200，返回原价
7.  POST /api/v1/member/marketing-schemes/calculate — mock SQLAlchemyError → ok=False
8.  POST /api/v1/member/marketing-schemes/calculate — 请求体中直接传 schemes → 200，应用请求中折扣规则
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from shared.ontology.src.database import get_db

TENANT = str(uuid.uuid4())
_HEADERS = {"X-Tenant-ID": TENANT}


# ---------------------------------------------------------------------------
# Mock DB 工厂
# ---------------------------------------------------------------------------

def make_mock_db():
    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


def _make_row(mapping: dict):
    """构造一个带 _mapping 属性的假行对象，模拟 SQLAlchemy Row"""
    row = MagicMock()
    row._mapping = mapping
    return row


# ---------------------------------------------------------------------------
# 应用 & 路由
# ---------------------------------------------------------------------------

from api.marketing import router

app = FastAPI()
app.include_router(router)


def _override_db(session):
    async def _dep():
        yield session
    return _dep


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 1: GET / — mock SELECT 返回2条方案
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_list_schemes_success():
    """mock SELECT 返回2条方案 → 200，data.items 长度=2"""
    db = make_mock_db()

    row1 = _make_row({
        "id": str(uuid.uuid4()),
        "name": "周末88折",
        "scheme_type": "order_discount",
        "rules": {"discount_rate": 88},
        "is_active": True,
        "valid_from": None,
        "valid_until": None,
        "priority": 10,
    })
    row2 = _make_row({
        "id": str(uuid.uuid4()),
        "name": "满100减10",
        "scheme_type": "threshold",
        "rules": {"tiers": [{"threshold_fen": 10000, "reduce_fen": 1000}]},
        "is_active": True,
        "valid_from": None,
        "valid_until": None,
        "priority": 5,
    })

    # 第一次 execute 是 set_config，第二次是 SELECT
    db.execute = AsyncMock(side_effect=[
        AsyncMock(),           # set_config
        iter([row1, row2]),    # SELECT 结果
    ])

    app.dependency_overrides[get_db] = _override_db(db)
    client = TestClient(app)

    resp = client.get("/api/v1/member/marketing-schemes", headers=_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert len(body["data"]["items"]) == 2


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 2: GET / — mock SELECT 返回空
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_list_schemes_empty():
    """mock SELECT 返回空列表 → 200，data.items=[]"""
    db = make_mock_db()
    db.execute = AsyncMock(side_effect=[
        AsyncMock(),   # set_config
        iter([]),      # SELECT 空结果
    ])

    app.dependency_overrides[get_db] = _override_db(db)
    client = TestClient(app)

    resp = client.get("/api/v1/member/marketing-schemes", headers=_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["items"] == []
    assert body["data"]["total"] == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 3: POST / — INSERT RETURNING 成功
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_create_scheme_success():
    """mock INSERT RETURNING 成功 → 200，data 含 id"""
    db = make_mock_db()
    new_id = str(uuid.uuid4())

    # scalar_one() 返回新 id
    insert_result = MagicMock()
    insert_result.scalar_one = MagicMock(return_value=new_id)

    db.execute = AsyncMock(side_effect=[
        AsyncMock(),      # set_config
        insert_result,    # INSERT RETURNING
    ])

    app.dependency_overrides[get_db] = _override_db(db)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/member/marketing-schemes",
        json={
            "scheme_type": "order_discount",
            "name": "全场9折",
            "priority": 10,
            "rules": {"discount_rate": 90},
        },
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["id"] == new_id


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 4: POST / — SQLAlchemyError → ok=False
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_create_scheme_db_error():
    """mock SQLAlchemyError → 返回 ok=False，error.code=DB_ERROR"""
    db = make_mock_db()
    db.execute = AsyncMock(side_effect=[
        AsyncMock(),                            # set_config
        SQLAlchemyError("connection refused"),  # INSERT 失败
    ])

    app.dependency_overrides[get_db] = _override_db(db)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/member/marketing-schemes",
        json={
            "scheme_type": "order_discount",
            "name": "全场9折",
            "rules": {"discount_rate": 90},
        },
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "DB_ERROR"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 5: POST /calculate — DB 返回1条 order_discount(rate=90)，total=10000 → final=9000
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_calculate_discount_with_db_schemes():
    """DB 返回 order_discount(rate=90)，total_fen=10000 → final_total_fen=9000"""
    db = make_mock_db()

    scheme_row = _make_row({
        "scheme_type": "order_discount",
        "rules": {"discount_rate": 90},
        "priority": 10,
        "exclusion_rules": [],
    })

    db.execute = AsyncMock(side_effect=[
        AsyncMock(),          # set_config
        iter([scheme_row]),   # SELECT marketing_schemes
    ])

    app.dependency_overrides[get_db] = _override_db(db)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/member/marketing-schemes/calculate",
        json={
            "items": [{"dish_id": "d1", "name": "红烧肉", "price_fen": 5000, "quantity": 2}],
            "order_total_fen": 10000,
            "schemes": [],
        },
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["final_total_fen"] == 9000
    assert body["data"]["total_discount_fen"] == 1000


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 6: POST /calculate — DB 返回空方案列表 → 返回原价
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_calculate_discount_no_schemes():
    """DB 返回空方案，请求也不含 schemes → final_total_fen 等于原价"""
    db = make_mock_db()
    db.execute = AsyncMock(side_effect=[
        AsyncMock(),   # set_config
        iter([]),      # SELECT 空
    ])

    app.dependency_overrides[get_db] = _override_db(db)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/member/marketing-schemes/calculate",
        json={
            "items": [{"dish_id": "d1", "name": "清蒸鱼", "price_fen": 8800, "quantity": 1}],
            "order_total_fen": 8800,
            "schemes": [],
        },
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["final_total_fen"] == 8800
    assert body["data"]["total_discount_fen"] == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 7: POST /calculate — SQLAlchemyError → ok=False
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_calculate_discount_db_error():
    """DB 查询方案时抛 SQLAlchemyError → ok=False，error.code=DB_ERROR"""
    db = make_mock_db()
    db.execute = AsyncMock(side_effect=[
        AsyncMock(),                            # set_config
        SQLAlchemyError("timeout"),             # SELECT 失败
    ])

    app.dependency_overrides[get_db] = _override_db(db)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/member/marketing-schemes/calculate",
        json={
            "items": [{"dish_id": "d1", "name": "红烧肉", "price_fen": 5000, "quantity": 1}],
            "order_total_fen": 5000,
            "schemes": [],
        },
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "DB_ERROR"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 8: POST /calculate — 请求体中直接传 schemes，不依赖DB
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_calculate_discount_request_schemes():
    """DB 无方案（空），请求体中传入 threshold 方案：满10000减1000 → final=9000"""
    db = make_mock_db()
    db.execute = AsyncMock(side_effect=[
        AsyncMock(),   # set_config
        iter([]),      # SELECT 空（无 DB 方案）
    ])

    app.dependency_overrides[get_db] = _override_db(db)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/member/marketing-schemes/calculate",
        json={
            "items": [{"dish_id": "d1", "name": "招牌菜", "price_fen": 10000, "quantity": 1}],
            "order_total_fen": 10000,
            "schemes": [
                {
                    "scheme_type": "threshold",
                    "priority": 10,
                    "rules": {
                        "tiers": [{"threshold_fen": 10000, "reduce_fen": 1000}]
                    },
                    "exclusion_rules": [],
                }
            ],
        },
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total_discount_fen"] == 1000
    assert body["data"]["final_total_fen"] == 9000
    assert "threshold" in body["data"]["applied_schemes"]
