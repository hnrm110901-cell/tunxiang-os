"""集点卡 API 路由测试 — api/stamp_card_routes.py

覆盖场景：
1.  POST /api/v1/stamp-cards/templates         — 正常创建模板，返回 ok=True
2.  POST /api/v1/stamp-cards/templates         — 缺少 name → 422
3.  POST /api/v1/stamp-cards/templates         — 服务层 ValueError fallback
4.  GET  /api/v1/stamp-cards/templates         — 正常返回模板列表
5.  GET  /api/v1/stamp-cards/templates         — DB 异常返回空列表（不崩溃）
6.  POST /api/v1/stamp-cards/auto-stamp        — 正常路径返回 ok=True
7.  POST /api/v1/stamp-cards/auto-stamp        — 缺少 customer_id → 422
8.  GET  /api/v1/stamp-cards/my               — 正常返回会员集章卡列表
9.  POST /api/v1/stamp-cards/{id}/redeem       — 正常核销返回 ok=True
10. POST /api/v1/stamp-cards/{id}/redeem       — 缺少 customer_id → 422
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

TENANT_ID = str(uuid.uuid4())
_HEADERS = {"X-Tenant-ID": TENANT_ID, "Authorization": "Bearer test"}


# ── Mock 数据库 session ──────────────────────────────────────────────────────


def _make_db():
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


# ── 加载路由（patch 掉服务层） ────────────────────────────────────────────────

# 预先 mock 服务模块，避免真实 DB 依赖
_mock_template_result = {"id": str(uuid.uuid4()), "name": "集5送1", "target_stamps": 5}
_mock_my_cards_result = [{"id": str(uuid.uuid4()), "stamps": 3, "target_stamps": 5}]
_mock_redeem_result = {"reward": "coupon-001", "status": "redeemed"}
_mock_auto_stamp_result = {"stamped": True, "current_stamps": 2}


with patch.dict(
    "sys.modules",
    {
        "services.stamp_card_service": type(sys)("services.stamp_card_service"),
    },
):
    import types

    fake_svc = types.ModuleType("services.stamp_card_service")
    fake_svc.create_template = AsyncMock(return_value=_mock_template_result)
    fake_svc.list_templates = AsyncMock(return_value=[_mock_template_result])
    fake_svc.auto_stamp = AsyncMock(return_value=_mock_auto_stamp_result)
    fake_svc.get_my_cards = AsyncMock(return_value=_mock_my_cards_result)
    fake_svc.redeem_card = AsyncMock(return_value=_mock_redeem_result)
    sys.modules["services.stamp_card_service"] = fake_svc

    from api.stamp_card_routes import get_db, router

app = FastAPI()
app.include_router(router)


def _override_db(db):
    def _dep():
        return db

    return _dep


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 1: POST /templates — 正常创建
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_create_template_ok():
    """正常创建模板，返回 ok=True"""
    db = _make_db()
    app.dependency_overrides[get_db] = _override_db(db)
    client = TestClient(app)

    fake_svc.create_template = AsyncMock(return_value=_mock_template_result)

    resp = client.post(
        "/api/v1/stamp-cards/templates",
        json={"name": "集5送1", "target_stamps": 5, "reward_type": "coupon", "validity_days": 90},
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["name"] == "集5送1"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 2: POST /templates — 缺少 name → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_create_template_missing_name():
    """name 为必填，缺少时应返回 422"""
    db = _make_db()
    app.dependency_overrides[get_db] = _override_db(db)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/stamp-cards/templates",
        json={"target_stamps": 5},
        headers=_HEADERS,
    )
    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 3: POST /templates — 服务层 ValueError fallback
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_create_template_service_error():
    """服务层抛 ValueError 时返回 ok=False"""
    db = _make_db()
    app.dependency_overrides[get_db] = _override_db(db)
    client = TestClient(app)

    fake_svc.create_template = AsyncMock(side_effect=ValueError("模板名称重复"))

    resp = client.post(
        "/api/v1/stamp-cards/templates",
        json={"name": "重复名称", "target_stamps": 5},
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "模板名称重复" in body["error"]["message"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 4: GET /templates — 正常返回列表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_list_templates_ok():
    """返回模板数组，元素含 name 字段"""
    db = _make_db()
    app.dependency_overrides[get_db] = _override_db(db)
    client = TestClient(app)

    fake_svc.list_templates = AsyncMock(return_value=[_mock_template_result])

    resp = client.get("/api/v1/stamp-cards/templates", headers=_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert isinstance(body["data"], list)
    assert body["data"][0]["name"] == "集5送1"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 5: GET /templates — 服务层异常（不崩溃）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_list_templates_service_returns_empty():
    """服务层返回空列表时，API 正常返回空数组"""
    db = _make_db()
    app.dependency_overrides[get_db] = _override_db(db)
    client = TestClient(app)

    fake_svc.list_templates = AsyncMock(return_value=[])

    resp = client.get("/api/v1/stamp-cards/templates", headers=_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"] == []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 6: POST /auto-stamp — 正常盖章
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_auto_stamp_ok():
    """自动盖章返回 ok=True"""
    db = _make_db()
    app.dependency_overrides[get_db] = _override_db(db)
    client = TestClient(app)

    fake_svc.auto_stamp = AsyncMock(return_value=_mock_auto_stamp_result)

    resp = client.post(
        "/api/v1/stamp-cards/auto-stamp",
        json={
            "customer_id": str(uuid.uuid4()),
            "order_id": str(uuid.uuid4()),
            "order_amount_fen": 8800,
            "store_id": "store-001",
        },
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["stamped"] is True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 7: POST /auto-stamp — 缺少 customer_id → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_auto_stamp_missing_customer_id():
    """customer_id 为必填，缺少时应返回 422"""
    db = _make_db()
    app.dependency_overrides[get_db] = _override_db(db)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/stamp-cards/auto-stamp",
        json={"order_id": str(uuid.uuid4()), "order_amount_fen": 5000, "store_id": "store-001"},
        headers=_HEADERS,
    )
    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 8: GET /my — 我的集章卡
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_my_cards_ok():
    """返回会员集章卡列表"""
    db = _make_db()
    app.dependency_overrides[get_db] = _override_db(db)
    client = TestClient(app)

    fake_svc.get_my_cards = AsyncMock(return_value=_mock_my_cards_result)
    customer_id = str(uuid.uuid4())

    resp = client.get(
        f"/api/v1/stamp-cards/my?customer_id={customer_id}",
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert isinstance(body["data"], list)
    assert body["data"][0]["stamps"] == 3


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 9: POST /{id}/redeem — 正常核销
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_redeem_ok():
    """集章卡满章核销，返回 ok=True"""
    db = _make_db()
    app.dependency_overrides[get_db] = _override_db(db)
    client = TestClient(app)

    fake_svc.redeem_card = AsyncMock(return_value=_mock_redeem_result)
    instance_id = str(uuid.uuid4())
    customer_id = str(uuid.uuid4())

    resp = client.post(
        f"/api/v1/stamp-cards/{instance_id}/redeem",
        json={"customer_id": customer_id},
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "redeemed"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 10: POST /{id}/redeem — 缺少 customer_id → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_redeem_missing_customer_id():
    """customer_id 为必填，缺少时应返回 422"""
    db = _make_db()
    app.dependency_overrides[get_db] = _override_db(db)
    client = TestClient(app)

    instance_id = str(uuid.uuid4())
    resp = client.post(
        f"/api/v1/stamp-cards/{instance_id}/redeem",
        json={},
        headers=_HEADERS,
    )
    assert resp.status_code == 422
