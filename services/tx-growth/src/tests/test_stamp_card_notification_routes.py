"""集章卡 & 通知任务 API 路由测试

覆盖路由文件：
  - api/stamp_card_routes.py     (4 个端点)
  - api/notification_routes.py   (2 个端点)

测试场景：
1.  GET  /api/v1/growth/stamp-card/my              — 正常返回集章卡信息
2.  GET  /api/v1/growth/stamp-card/my              — 无集章卡时返回 card=None
3.  GET  /api/v1/growth/stamp-card/my              — DB 表不存在时返回 TABLE_NOT_READY
4.  POST /api/v1/growth/stamp-card/stamp           — 正常盖章返回 stamp_count
5.  POST /api/v1/growth/stamp-card/stamp           — 无进行中集章卡返回 NO_ACTIVE_CARD
6.  POST /api/v1/growth/stamp-card/stamp           — 消费不足返回 BELOW_MINIMUM
7.  GET  /api/v1/growth/stamp-card/prizes          — 正常返回奖品列表
8.  GET  /api/v1/growth/stamp-card/prizes          — DB 表不存在时 fallback 空列表
9.  POST /api/v1/growth/stamp-card/exchange        — 正常兑换返回 redeem_code
10. POST /api/v1/growth/stamp-card/exchange        — 集章卡未集满返回 NOT_COMPLETED
11. POST /api/v1/growth/stamp-card/exchange        — 奖品已兑换返回 ALREADY_EXCHANGED
12. POST /api/v1/growth/notifications/send-campaign — 正常创建发送任务返回 task_id
13. POST /api/v1/growth/notifications/send-campaign — 非法 channel 返回 INVALID_CHANNEL
14. POST /api/v1/growth/notifications/send-campaign — 空目标客户列表返回 EMPTY_TARGETS
15. POST /api/v1/growth/notifications/send-campaign — 空模板返回 EMPTY_TEMPLATE
16. GET  /api/v1/growth/notifications/tasks         — 正常列出任务
17. GET  /api/v1/growth/notifications/tasks         — DB 表不存在时返回空列表
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import types
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

# ---------------------------------------------------------------------------
# Mock shared.ontology.src.database.get_db (used by stamp_card + notification)
# ---------------------------------------------------------------------------

_fake_shared = sys.modules.get("shared") or types.ModuleType("shared")
_fake_ontology = sys.modules.get("shared.ontology") or types.ModuleType("shared.ontology")
_fake_src = sys.modules.get("shared.ontology.src") or types.ModuleType("shared.ontology.src")
_fake_database = sys.modules.get("shared.ontology.src.database") or types.ModuleType("shared.ontology.src.database")


# get_db is used as a FastAPI dependency (overridden per-test)
async def _fake_get_db():
    yield None


_fake_database.get_db = _fake_get_db

sys.modules["shared"] = _fake_shared
sys.modules["shared.ontology"] = _fake_ontology
sys.modules["shared.ontology.src"] = _fake_src
sys.modules["shared.ontology.src.database"] = _fake_database

# structlog
_fake_structlog = sys.modules.get("structlog") or types.ModuleType("structlog")
_fake_structlog.get_logger = MagicMock(return_value=MagicMock(info=MagicMock(), warning=MagicMock(), error=MagicMock()))
sys.modules["structlog"] = _fake_structlog

# ---------------------------------------------------------------------------
# Load routes
# ---------------------------------------------------------------------------

from api.notification_routes import get_db as notif_get_db
from api.notification_routes import router as notif_router
from api.stamp_card_routes import get_db as stamp_get_db
from api.stamp_card_routes import router as stamp_router

stamp_app = FastAPI()
stamp_app.include_router(stamp_router)

notif_app = FastAPI()
notif_app.include_router(notif_router)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TENANT_ID = str(uuid.uuid4())
_HEADERS = {"X-Tenant-ID": TENANT_ID}
_CUSTOMER_ID = str(uuid.uuid4())
_CAMPAIGN_ID = str(uuid.uuid4())
_CARD_ID = str(uuid.uuid4())
_ORDER_ID = str(uuid.uuid4())
_TEMPLATE_ID = str(uuid.uuid4())


class _FakeRow:
    """Simulate SQLAlchemy named-column row."""

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

    def __getattr__(self, name):
        raise AttributeError(name)


def _make_db(*execute_results):
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=list(execute_results))
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _exec_ok(*rows):
    """Return a mock execute result with fetchone/fetchall returning given rows."""
    result = MagicMock()
    result.fetchone = MagicMock(return_value=rows[0] if rows else None)
    result.fetchall = MagicMock(return_value=list(rows))
    result.scalar = MagicMock(return_value=len(rows))
    return result


def _override(db):
    def _dep():
        return db

    return _dep


# ===========================================================================
# STAMP CARD ROUTES
# ===========================================================================

# ── Test 1: 正常返回集章卡信息 ───────────────────────────────────────────────


def test_get_my_stamp_card_found():
    card_row = _FakeRow(
        id=uuid.UUID(_CARD_ID),
        template_id=uuid.UUID(_TEMPLATE_ID),
        stamp_count=3,
        target_stamps=8,
        status="active",
        expired_at=datetime.now(timezone.utc) + timedelta(days=30),
        completed_at=None,
        reward_issued=False,
        name="集章有礼",
        description="集满8章送饮品",
        reward_type="dish",
        reward_config={"dish_id": "xxx"},
        min_order_fen=3000,
    )
    stamp_row = _FakeRow(
        stamp_no=1,
        order_id=uuid.uuid4(),
        store_id=uuid.uuid4(),
        stamped_at=datetime.now(timezone.utc),
    )
    cfg_result = _exec_ok()
    card_result = _exec_ok(card_row)
    stamps_result = _exec_ok(stamp_row)

    db = _make_db(cfg_result, card_result, stamps_result)
    stamp_app.dependency_overrides[stamp_get_db] = _override(db)

    client = TestClient(stamp_app)
    resp = client.get(
        f"/api/v1/growth/stamp-card/my?customer_id={_CUSTOMER_ID}",
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["current_stamps"] == 3
    assert data["data"]["total_slots"] == 8


# ── Test 2: 无集章卡时返回 card=None ─────────────────────────────────────────


def test_get_my_stamp_card_none():
    cfg_result = _exec_ok()
    no_result = MagicMock()
    no_result.fetchone = MagicMock(return_value=None)

    db = _make_db(cfg_result, no_result)
    stamp_app.dependency_overrides[stamp_get_db] = _override(db)

    client = TestClient(stamp_app)
    resp = client.get(
        f"/api/v1/growth/stamp-card/my?customer_id={_CUSTOMER_ID}",
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["card"] is None


# ── Test 3: DB 表不存在时返回 TABLE_NOT_READY ────────────────────────────────


def test_get_my_stamp_card_table_missing():
    cfg_result = _exec_ok()
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            cfg_result,
            OperationalError("relation stamp_card_instances does not exist", None, None),
        ]
    )
    stamp_app.dependency_overrides[stamp_get_db] = _override(db)

    client = TestClient(stamp_app)
    resp = client.get(
        f"/api/v1/growth/stamp-card/my?customer_id={_CUSTOMER_ID}",
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["_note"] == "TABLE_NOT_READY"


# ── Test 4: 正常盖章返回 stamp_count ─────────────────────────────────────────


def test_stamp_success():
    instance_row = _FakeRow(
        id=uuid.UUID(_CARD_ID),
        stamp_count=2,
        target_stamps=8,
        min_order_fen=2000,
        name="集章有礼",
    )
    instance_result = MagicMock()
    instance_result.fetchone = MagicMock(return_value=instance_row)

    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            MagicMock(),  # set_config
            instance_result,
            MagicMock(),  # INSERT stamp_card_stamps
            MagicMock(),  # UPDATE stamp_card_instances
        ]
    )
    stamp_app.dependency_overrides[stamp_get_db] = _override(db)

    client = TestClient(stamp_app)
    resp = client.post(
        "/api/v1/growth/stamp-card/stamp",
        json={
            "order_id": _ORDER_ID,
            "customer_id": _CUSTOMER_ID,
            "amount_fen": 5000,
        },
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["stamp_count"] == 1
    assert data["data"]["current_stamps"] == 3


# ── Test 5: 无进行中集章卡返回 NO_ACTIVE_CARD ────────────────────────────────


def test_stamp_no_active_card():
    no_instance = MagicMock()
    no_instance.fetchone = MagicMock(return_value=None)

    db = _make_db(MagicMock(), no_instance)
    stamp_app.dependency_overrides[stamp_get_db] = _override(db)

    client = TestClient(stamp_app)
    resp = client.post(
        "/api/v1/growth/stamp-card/stamp",
        json={
            "order_id": _ORDER_ID,
            "customer_id": _CUSTOMER_ID,
            "amount_fen": 5000,
        },
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["error"]["code"] == "NO_ACTIVE_CARD"


# ── Test 6: 消费金额不足 ──────────────────────────────────────────────────────


def test_stamp_below_minimum():
    instance_row = _FakeRow(
        id=uuid.UUID(_CARD_ID),
        stamp_count=1,
        target_stamps=8,
        min_order_fen=5000,
        name="集章有礼",
    )
    instance_result = MagicMock()
    instance_result.fetchone = MagicMock(return_value=instance_row)

    db = _make_db(MagicMock(), instance_result)
    stamp_app.dependency_overrides[stamp_get_db] = _override(db)

    client = TestClient(stamp_app)
    resp = client.post(
        "/api/v1/growth/stamp-card/stamp",
        json={
            "order_id": _ORDER_ID,
            "customer_id": _CUSTOMER_ID,
            "amount_fen": 1000,
        },
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["error"]["code"] == "BELOW_MINIMUM"


# ── Test 7: 奖品列表 ──────────────────────────────────────────────────────────


def test_get_prizes():
    prize_row = _FakeRow(
        id=uuid.UUID(_TEMPLATE_ID),
        name="集章有礼",
        description="集满8章",
        target_stamps=8,
        reward_type="dish",
        reward_config={"dish_id": "xxx"},
        min_order_fen=2000,
    )
    prize_result = MagicMock()
    prize_result.fetchall = MagicMock(return_value=[prize_row])

    db = _make_db(MagicMock(), prize_result)
    stamp_app.dependency_overrides[stamp_get_db] = _override(db)

    client = TestClient(stamp_app)
    resp = client.get("/api/v1/growth/stamp-card/prizes", headers=_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["total"] == 1


# ── Test 8: DB 表不存在时奖品列表返回空 ──────────────────────────────────────


def test_get_prizes_table_missing():
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            MagicMock(),
            OperationalError("relation stamp_card_templates does not exist", None, None),
        ]
    )
    stamp_app.dependency_overrides[stamp_get_db] = _override(db)

    client = TestClient(stamp_app)
    resp = client.get("/api/v1/growth/stamp-card/prizes", headers=_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["total"] == 0


# ── Test 9: 正常兑换返回 redeem_code ─────────────────────────────────────────


def test_exchange_prize_success():
    card_row = _FakeRow(
        id=uuid.UUID(_CARD_ID),
        status="completed",
        reward_issued=False,
        customer_id=uuid.UUID(_CUSTOMER_ID),
        name="集章有礼",
        reward_type="dish",
        reward_config={"dish_id": "xxx"},
    )
    card_result = MagicMock()
    card_result.fetchone = MagicMock(return_value=card_row)

    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            MagicMock(),  # set_config
            card_result,  # SELECT instances
            MagicMock(),  # UPDATE reward_issued
            MagicMock(),  # UPDATE completed_count
        ]
    )
    stamp_app.dependency_overrides[stamp_get_db] = _override(db)

    client = TestClient(stamp_app)
    resp = client.post(
        "/api/v1/growth/stamp-card/exchange",
        json={"card_id": _CARD_ID, "customer_id": _CUSTOMER_ID},
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "redeem_code" in data["data"]


# ── Test 10: 集章卡未集满返回 NOT_COMPLETED ──────────────────────────────────


def test_exchange_not_completed():
    card_row = _FakeRow(
        id=uuid.UUID(_CARD_ID),
        status="active",
        reward_issued=False,
        customer_id=uuid.UUID(_CUSTOMER_ID),
        name="集章有礼",
        reward_type="dish",
        reward_config={},
    )
    card_result = MagicMock()
    card_result.fetchone = MagicMock(return_value=card_row)

    db = _make_db(MagicMock(), card_result)
    stamp_app.dependency_overrides[stamp_get_db] = _override(db)

    client = TestClient(stamp_app)
    resp = client.post(
        "/api/v1/growth/stamp-card/exchange",
        json={"card_id": _CARD_ID, "customer_id": _CUSTOMER_ID},
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["error"]["code"] == "NOT_COMPLETED"


# ── Test 11: 奖品已兑换 ──────────────────────────────────────────────────────


def test_exchange_already_exchanged():
    card_row = _FakeRow(
        id=uuid.UUID(_CARD_ID),
        status="completed",
        reward_issued=True,
        customer_id=uuid.UUID(_CUSTOMER_ID),
        name="集章有礼",
        reward_type="dish",
        reward_config={},
    )
    card_result = MagicMock()
    card_result.fetchone = MagicMock(return_value=card_row)

    db = _make_db(MagicMock(), card_result)
    stamp_app.dependency_overrides[stamp_get_db] = _override(db)

    client = TestClient(stamp_app)
    resp = client.post(
        "/api/v1/growth/stamp-card/exchange",
        json={"card_id": _CARD_ID, "customer_id": _CUSTOMER_ID},
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["error"]["code"] == "ALREADY_EXCHANGED"


# ===========================================================================
# NOTIFICATION ROUTES
# ===========================================================================

# ── Test 12: 正常创建发送任务 ─────────────────────────────────────────────────


def test_send_campaign_notification_success():
    campaign_row = _FakeRow(
        id=uuid.UUID(_CAMPAIGN_ID),
        name="夏日大促",
        status="active",
    )
    campaign_result = MagicMock()
    campaign_result.fetchone = MagicMock(return_value=campaign_row)

    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            MagicMock(),  # set_config
            campaign_result,  # SELECT campaigns
            MagicMock(),  # INSERT notification_tasks
        ]
    )
    notif_app.dependency_overrides[notif_get_db] = _override(db)

    client = TestClient(notif_app)
    resp = client.post(
        "/api/v1/growth/notifications/send-campaign",
        json={
            "campaign_id": _CAMPAIGN_ID,
            "channel": "sms",
            "message_template": "您有一张优惠券等您领取！",
            "target_customer_ids": [_CUSTOMER_ID],
        },
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "task_id" in data["data"]
    assert data["data"]["channel"] == "sms"


# ── Test 13: 非法 channel ────────────────────────────────────────────────────


def test_send_campaign_invalid_channel():
    db = _make_db()
    notif_app.dependency_overrides[notif_get_db] = _override(db)

    client = TestClient(notif_app)
    resp = client.post(
        "/api/v1/growth/notifications/send-campaign",
        json={
            "campaign_id": _CAMPAIGN_ID,
            "channel": "email",
            "message_template": "test",
            "target_customer_ids": [_CUSTOMER_ID],
        },
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["error"]["code"] == "INVALID_CHANNEL"


# ── Test 14: 空目标客户列表 ───────────────────────────────────────────────────


def test_send_campaign_empty_targets():
    db = _make_db()
    notif_app.dependency_overrides[notif_get_db] = _override(db)

    client = TestClient(notif_app)
    resp = client.post(
        "/api/v1/growth/notifications/send-campaign",
        json={
            "campaign_id": _CAMPAIGN_ID,
            "channel": "sms",
            "message_template": "test",
            "target_customer_ids": [],
        },
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["error"]["code"] == "EMPTY_TARGETS"


# ── Test 15: 空消息模板 ───────────────────────────────────────────────────────


def test_send_campaign_empty_template():
    db = _make_db()
    notif_app.dependency_overrides[notif_get_db] = _override(db)

    client = TestClient(notif_app)
    resp = client.post(
        "/api/v1/growth/notifications/send-campaign",
        json={
            "campaign_id": _CAMPAIGN_ID,
            "channel": "sms",
            "message_template": "   ",
            "target_customer_ids": [_CUSTOMER_ID],
        },
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["error"]["code"] == "EMPTY_TEMPLATE"


# ── Test 16: 正常列出任务 ─────────────────────────────────────────────────────


def test_list_notification_tasks():
    now = datetime.now(timezone.utc)
    task_row = _FakeRow(
        id=uuid.uuid4(),
        campaign_id=uuid.UUID(_CAMPAIGN_ID),
        channel="sms",
        status="pending",
        total_count=100,
        sent_count=0,
        failed_count=0,
        message_template="您有优惠券",
        created_at=now,
        updated_at=now,
    )

    count_result = MagicMock()
    count_result.scalar = MagicMock(return_value=1)

    rows_result = MagicMock()
    rows_result.fetchall = MagicMock(return_value=[task_row])

    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            MagicMock(),  # set_config
            count_result,
            rows_result,
        ]
    )
    notif_app.dependency_overrides[notif_get_db] = _override(db)

    client = TestClient(notif_app)
    resp = client.get("/api/v1/growth/notifications/tasks", headers=_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["total"] == 1
    assert data["data"]["items"][0]["channel"] == "sms"


# ── Test 17: DB 表不存在时列出任务返回空 ──────────────────────────────────────


def test_list_notification_tasks_table_missing():
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            MagicMock(),
            OperationalError("relation notification_tasks does not exist", None, None),
        ]
    )
    notif_app.dependency_overrides[notif_get_db] = _override(db)

    client = TestClient(notif_app)
    resp = client.get("/api/v1/growth/notifications/tasks", headers=_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["total"] == 0
    assert data["data"]["_note"] == "TABLE_NOT_READY"
