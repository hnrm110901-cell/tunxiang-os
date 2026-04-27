"""储值卡小程序端 API 测试 — stored_value_miniapp_routes.py

覆盖场景：
1.  GET  /stored-value/balance/{member_id} — 正常路径：账户存在
2.  GET  /stored-value/balance/{member_id} — 账户不存在，返回全零
3.  GET  /stored-value/balance/{member_id} — DB 异常 fallback 返回全零
4.  GET  /stored-value/balance/{member_id} — 缺少 X-Tenant-ID → 422
5.  GET  /stored-value/plans               — DB 有方案时返回真实列表
6.  GET  /stored-value/plans               — DB 无方案时返回 mock 兜底数据
7.  GET  /stored-value/plans               — DB 异常时返回 mock 兜底数据
8.  POST /stored-value/recharge            — 正常路径：返回 order_id
9.  POST /stored-value/recharge            — amount_fen=0（非正数）返回 422
10. GET  /stored-value/transactions/{mid}  — 正常路径：有流水记录
11. GET  /stored-value/transactions/{mid}  — 账户不存在返回空列表
12. GET  /stored-value/transactions/{mid}  — DB 异常 fallback 返回空列表
13. POST /gift-card/purchase               — 正常路径：返回 order_id 和 card_id
14. GET  /gift-card/list                   — received 方向正常路径
15. GET  /gift-card/list                   — DB 异常 fallback 返回空列表
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

# ─── 工具类 ────────────────────────────────────────────────


def _uid() -> str:
    return str(uuid.uuid4())


TENANT_ID = _uid()
MEMBER_ID = _uid()

_HEADERS = {"X-Tenant-ID": TENANT_ID}


class FakeMappingsResult:
    """模拟 result.mappings().first() 和 .all()"""

    def __init__(self, rows=None):
        self._rows = rows or []

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows

    def __iter__(self):
        return iter(self._rows)


class FakeExecuteResult:
    def __init__(self, mapping_rows=None, scalar_value=None):
        self._mapping_rows = mapping_rows or []
        self._scalar_value = scalar_value

    def mappings(self):
        return FakeMappingsResult(self._mapping_rows)

    def scalar(self):
        return self._scalar_value


def _seq_db(*results):
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=list(results))
    return db


# ─── 加载路由 ──────────────────────────────────────────────

from api.stored_value_miniapp_routes import _MOCK_PLANS, router

from shared.ontology.src.database import get_db

app = FastAPI()
app.include_router(router)


def _override(db):
    def _dep():
        return db

    return _dep


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 1: GET balance — 账户存在，返回真实余额
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_get_balance_account_exists():
    """账户存在时返回余额字段"""
    card_id = _uid()
    row = {
        "balance_fen": 50000,
        "gift_balance_fen": 1000,
        "bonus_balance_fen": 500,
        "card_id": card_id,
        "status": "active",
    }

    set_cfg = AsyncMock()
    balance_result = FakeExecuteResult(mapping_rows=[row])

    db = _seq_db(set_cfg, balance_result)
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.get(
        f"/api/v1/member/miniapp/stored-value/balance/{MEMBER_ID}",
        headers=_HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["balance_fen"] == 50000
    assert data["gift_balance_fen"] == 1000
    assert data["bonus_balance_fen"] == 500
    assert data["card_id"] == card_id
    assert data["status"] == "active"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 2: GET balance — 账户不存在，返回全零
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_get_balance_account_not_found():
    """账户不存在时余额全零，ok=True"""
    set_cfg = AsyncMock()
    empty_result = FakeExecuteResult(mapping_rows=[])  # first() → None

    db = _seq_db(set_cfg, empty_result)
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.get(
        f"/api/v1/member/miniapp/stored-value/balance/{MEMBER_ID}",
        headers=_HEADERS,
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["balance_fen"] == 0
    assert data["card_id"] is None
    assert data["status"] == "none"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 3: GET balance — DB 异常 fallback
# 注：_set_rls（第 1 次 execute）需正常；第 2 次查询才抛异常
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_get_balance_db_error_fallback():
    """DB 查询异常时 graceful 返回全零，HTTP 200"""
    db = _seq_db(
        AsyncMock(),  # _set_rls 正常
        OperationalError("stmt", {}, Exception("conn refused")),  # 查询抛异常
    )
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.get(
        f"/api/v1/member/miniapp/stored-value/balance/{MEMBER_ID}",
        headers=_HEADERS,
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["balance_fen"] == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 4: GET balance — 缺少 X-Tenant-ID → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_get_balance_missing_tenant_header():
    db = AsyncMock()
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/member/miniapp/stored-value/balance/{MEMBER_ID}"
        # 不带 X-Tenant-ID
    )
    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 5: GET plans — DB 有方案，返回真实列表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_get_plans_from_db():
    """DB 返回真实方案时不使用 mock 兜底数据"""
    db_plans = [
        {"id": "plan-a", "name": "充200送20", "amount_fen": 20000, "bonus_fen": 2000, "sort_order": 1},
        {"id": "plan-b", "name": "充500送80", "amount_fen": 50000, "bonus_fen": 8000, "sort_order": 2},
    ]

    set_cfg = AsyncMock()
    plans_result = FakeExecuteResult(mapping_rows=db_plans)

    db = _seq_db(set_cfg, plans_result)
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.get("/api/v1/member/miniapp/stored-value/plans", headers=_HEADERS)

    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert len(items) == 2
    assert items[0]["id"] == "plan-a"
    assert items[1]["amount_fen"] == 50000


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 6: GET plans — DB 返回空列表时使用 mock 兜底
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_get_plans_empty_db_uses_mock():
    """DB 无方案时 fallback 到 _MOCK_PLANS"""
    set_cfg = AsyncMock()
    empty_result = FakeExecuteResult(mapping_rows=[])

    db = _seq_db(set_cfg, empty_result)
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.get("/api/v1/member/miniapp/stored-value/plans", headers=_HEADERS)

    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert items == _MOCK_PLANS
    assert len(items) == 5  # _MOCK_PLANS 有 5 条预置方案


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 7: GET plans — DB 异常 fallback 到 mock
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_get_plans_db_error_fallback_to_mock():
    """DB 查询异常时 fallback 到 _MOCK_PLANS，ok=True"""
    db = _seq_db(
        AsyncMock(),  # _set_rls 正常
        OperationalError("stmt", {}, Exception("timeout")),  # 查询抛异常
    )
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.get("/api/v1/member/miniapp/stored-value/plans", headers=_HEADERS)

    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert items == _MOCK_PLANS


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 8: POST /recharge — 正常路径
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_recharge_returns_order_id():
    """充值请求返回 order_id，amount_fen 匹配"""
    db = AsyncMock()
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/member/miniapp/stored-value/recharge",
        json={"member_id": MEMBER_ID, "amount_fen": 20000},
        headers=_HEADERS,
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "order_id" in data
    assert data["amount_fen"] == 20000
    # 微信支付参数暂为 None（TODO 阶段）
    assert data["timeStamp"] is None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 9: POST /recharge — amount_fen=0 → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_recharge_invalid_amount_fen():
    """amount_fen 必须 > 0，传 0 应返回 422"""
    db = AsyncMock()
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/member/miniapp/stored-value/recharge",
        json={"member_id": MEMBER_ID, "amount_fen": 0},
        headers=_HEADERS,
    )
    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 10: GET /transactions/{mid} — 有流水记录
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_get_transactions_with_records():
    """账户存在且有流水时返回正确分页数据"""
    account_id = uuid.uuid4()
    txn_row = {
        "id": str(uuid.uuid4()),
        "type": "recharge",
        "description": "充值200元",
        "amount_fen": 20000,
        "created_at": datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc),
    }

    set_cfg = AsyncMock()
    acct_result = FakeExecuteResult(mapping_rows=[{"id": account_id}])
    count_result = AsyncMock()
    count_result.scalar = lambda: 1
    rows_result = FakeExecuteResult(mapping_rows=[txn_row])

    db = _seq_db(set_cfg, acct_result, count_result, rows_result)
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.get(
        f"/api/v1/member/miniapp/stored-value/transactions/{MEMBER_ID}",
        headers=_HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["total"] == 1
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["type"] == "recharge"
    assert item["amount_fen"] == 20000
    # created_at 已序列化为 ISO 字符串
    assert "2026-03-15" in item["created_at"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 11: GET /transactions/{mid} — 账户不存在
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_get_transactions_no_account():
    """账户不存在时直接返回空列表，total=0"""
    set_cfg = AsyncMock()
    acct_result = FakeExecuteResult(mapping_rows=[])  # first() → None

    db = _seq_db(set_cfg, acct_result)
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.get(
        f"/api/v1/member/miniapp/stored-value/transactions/{MEMBER_ID}",
        headers=_HEADERS,
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["items"] == []
    assert data["total"] == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 12: GET /transactions/{mid} — DB 异常 fallback
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_get_transactions_db_error_fallback():
    """DB 查询异常时返回空列表，ok=True"""
    db = _seq_db(
        AsyncMock(),  # _set_rls 正常
        OperationalError("stmt", {}, Exception("conn error")),  # account 查询抛异常
    )
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.get(
        f"/api/v1/member/miniapp/stored-value/transactions/{MEMBER_ID}",
        headers=_HEADERS,
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["items"] == []
    assert data["total"] == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 13: POST /gift-card/purchase — 正常路径
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_gift_card_purchase_returns_ids():
    """购买礼品卡返回 order_id 和 card_id"""
    db = AsyncMock()
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/member/miniapp/gift-card/purchase",
        json={
            "member_id": MEMBER_ID,
            "amount_fen": 50000,
            "theme": "birthday",
            "bless_msg": "生日快乐",
            "recipient_phone": "13800138000",
        },
        headers=_HEADERS,
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "order_id" in data
    assert "card_id" in data
    assert data["amount_fen"] == 50000
    # 两个 ID 应为有效 UUID 格式
    uuid.UUID(data["order_id"])
    uuid.UUID(data["card_id"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 14: GET /gift-card/list — received 方向正常
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_list_gift_cards_received():
    """direction=received 返回收到的礼品卡"""
    card_row = {
        "id": str(uuid.uuid4()),
        "amount_fen": 30000,
        "theme": "birthday",
        "bless_msg": "生日快乐",
        "status": "unused",
        "sender_phone": "13900139001",
        "sender_name": "张三",
        "created_at": datetime(2026, 3, 1, tzinfo=timezone.utc),
    }

    set_cfg = AsyncMock()
    cards_result = FakeExecuteResult(mapping_rows=[card_row])

    db = _seq_db(set_cfg, cards_result)
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.get(
        f"/api/v1/member/miniapp/gift-card/list?member_id={MEMBER_ID}&direction=received",
        headers=_HEADERS,
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 1
    card = data["items"][0]
    assert card["amount_fen"] == 30000
    assert card["status"] == "unused"
    assert "2026-03-01" in card["created_at"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 15: GET /gift-card/list — DB 异常 fallback
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_list_gift_cards_db_error_fallback():
    """DB 查询异常时返回空列表，ok=True"""
    db = _seq_db(
        AsyncMock(),  # _set_rls 正常
        OperationalError("stmt", {}, Exception("timeout")),  # 查询抛异常
    )
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.get(
        f"/api/v1/member/miniapp/gift-card/list?member_id={MEMBER_ID}",
        headers=_HEADERS,
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["items"] == []
    assert data["total"] == 0
