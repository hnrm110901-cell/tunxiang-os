"""裂变拉新 API 路由测试 — api/referral_routes.py

注意：referral_routes 通过 request.state.db 获取 DB（由中间件注入），
需要用 app.middleware 或 monkeypatch 注入 mock DB。

覆盖场景：
1.  POST /api/v1/growth/referrals/campaigns              — 正常创建裂变活动
2.  POST /api/v1/growth/referrals/campaigns              — 非法 reward_type → 422
3.  POST /api/v1/growth/referrals/campaigns              — 缺少必填字段 → 422
4.  POST /api/v1/growth/referrals/campaigns              — 奖励值为负数 → 422
5.  GET  /api/v1/growth/referrals/campaigns              — 正常返回活动列表
6.  GET  /api/v1/growth/referrals/campaigns/{id}/stats   — 正常返回活动统计
7.  GET  /api/v1/growth/referrals/campaigns/{id}/stats   — 活动不存在 → 404
8.  POST /api/v1/growth/referrals/invite/generate        — 正常生成邀请链接
9.  POST /api/v1/growth/referrals/invite/generate        — 活动不存在 → 404
10. POST /api/v1/growth/referrals/invite/register        — 正常注册绑定
11. POST /api/v1/growth/referrals/invite/register        — 欺诈拦截 → 403
12. POST /api/v1/growth/referrals/invite/register        — 邀请码不存在 → 404
13. POST /api/v1/growth/referrals/invite/first-order     — 正常触发首单奖励
14. POST /api/v1/growth/referrals/invite/first-order     — 订单金额为 0 → 422
15. GET  /api/v1/growth/referrals/my-invites             — 正常返回邀请记录
16. GET  /api/v1/growth/referrals/my-invites             — 活动不存在 → 404
"""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ---------------------------------------------------------------------------
# Stub heavy dependencies before importing route module
# ---------------------------------------------------------------------------
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

# Stub structlog
_structlog_mod = types.ModuleType("structlog")
_structlog_mod.get_logger = MagicMock(return_value=MagicMock())
sys.modules.setdefault("structlog", _structlog_mod)

# Stub services.referral_service
_ref_svc_mod = types.ModuleType("services.referral_service")


class _ReferralError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


_fake_ref_svc = MagicMock()
_ref_svc_mod.ReferralService = MagicMock(return_value=_fake_ref_svc)
_ref_svc_mod.ReferralError = _ReferralError
_svc_parent = types.ModuleType("services")
sys.modules.setdefault("services", _svc_parent)
sys.modules["services.referral_service"] = _ref_svc_mod

# Stub models.referral (used in create_campaign)
_models_mod = types.ModuleType("models")
_models_ref_mod = types.ModuleType("models.referral")


class _FakeReferralCampaign:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


_models_ref_mod.ReferralCampaign = _FakeReferralCampaign
sys.modules.setdefault("models", _models_mod)
sys.modules["models.referral"] = _models_ref_mod

# Stub sqlalchemy.ext.asyncio
_sqla_ext = types.ModuleType("sqlalchemy.ext.asyncio")
_sqla_ext.AsyncSession = MagicMock()
_sqla_parent = types.ModuleType("sqlalchemy")
_sqla_ext_parent = types.ModuleType("sqlalchemy.ext")
sys.modules.setdefault("sqlalchemy", _sqla_parent)
sys.modules.setdefault("sqlalchemy.ext", _sqla_ext_parent)
sys.modules.setdefault("sqlalchemy.ext.asyncio", _sqla_ext)

# Stub sqlalchemy.select
_sqla_parent.select = MagicMock(return_value=MagicMock(
    where=MagicMock(return_value=MagicMock(
        where=MagicMock(return_value=MagicMock(
            order_by=MagicMock(return_value=MagicMock())
        ))
    ))
))

from api.referral_routes import router  # noqa: E402

# ─── Build app with middleware that injects mock DB ────────────────────────

def _build_app(mock_db):
    _app = FastAPI()

    @_app.middleware("http")
    async def inject_db(request: Request, call_next):
        request.state.db = mock_db
        response = await call_next(request)
        return response

    _app.include_router(router)
    return _app


TENANT_ID = str(uuid.uuid4())
_HEADERS = {"X-Tenant-ID": TENANT_ID}
_CAMPAIGN_ID = str(uuid.uuid4())
_CUSTOMER_ID = str(uuid.uuid4())
_NOW = datetime(2026, 4, 6, 10, 0, tzinfo=timezone.utc)

_CREATE_CAMPAIGN_PAYLOAD = {
    "name": "春节老带新",
    "referrer_reward_type": "coupon",
    "referrer_reward_value": 1000,
    "referrer_reward_condition": "first_order",
    "invitee_reward_type": "coupon",
    "invitee_reward_value": 500,
    "valid_from": "2026-04-01T00:00:00",
}


def _make_mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock()
    return db


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 1-4: POST /campaigns
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_create_campaign_ok():
    """正常创建裂变活动，返回 campaign_id 和 status=draft"""
    mock_db = _make_mock_db()
    app = _build_app(mock_db)
    c = TestClient(app, raise_server_exceptions=False)

    resp = c.post(
        "/api/v1/growth/referrals/campaigns",
        headers=_HEADERS,
        json=_CREATE_CAMPAIGN_PAYLOAD,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "campaign_id" in body["data"]
    assert body["data"]["status"] == "draft"


def test_create_campaign_invalid_reward_type():
    """非法 referrer_reward_type → 422"""
    mock_db = _make_mock_db()
    app = _build_app(mock_db)
    c = TestClient(app, raise_server_exceptions=False)

    payload = dict(_CREATE_CAMPAIGN_PAYLOAD)
    payload["referrer_reward_type"] = "cash"  # not in allowed set
    resp = c.post(
        "/api/v1/growth/referrals/campaigns",
        headers=_HEADERS,
        json=payload,
    )
    assert resp.status_code == 422


def test_create_campaign_missing_required_field():
    """缺少必填字段 valid_from → 422"""
    mock_db = _make_mock_db()
    app = _build_app(mock_db)
    c = TestClient(app, raise_server_exceptions=False)

    payload = {k: v for k, v in _CREATE_CAMPAIGN_PAYLOAD.items() if k != "valid_from"}
    resp = c.post(
        "/api/v1/growth/referrals/campaigns",
        headers=_HEADERS,
        json=payload,
    )
    assert resp.status_code == 422


def test_create_campaign_negative_reward_value():
    """奖励值为负数 → 422"""
    mock_db = _make_mock_db()
    app = _build_app(mock_db)
    c = TestClient(app, raise_server_exceptions=False)

    payload = dict(_CREATE_CAMPAIGN_PAYLOAD)
    payload["referrer_reward_value"] = -100
    resp = c.post(
        "/api/v1/growth/referrals/campaigns",
        headers=_HEADERS,
        json=payload,
    )
    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 5: GET /campaigns
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_list_campaigns_ok():
    """正常返回活动列表"""
    campaign = _FakeReferralCampaign(
        id=uuid.uuid4(),
        name="春节老带新",
        status="active",
        valid_from=_NOW,
        valid_until=None,
        referrer_reward_type="coupon",
        invitee_reward_type="coupon",
    )
    mock_result = MagicMock()
    mock_result.scalars = MagicMock(return_value=MagicMock(
        all=MagicMock(return_value=[campaign])
    ))

    mock_db = _make_mock_db()
    mock_db.execute = AsyncMock(return_value=mock_result)

    app = _build_app(mock_db)
    c = TestClient(app, raise_server_exceptions=False)

    resp = c.get("/api/v1/growth/referrals/campaigns", headers=_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 1
    assert body["data"]["items"][0]["name"] == "春节老带新"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 6-7: GET /campaigns/{id}/stats
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_get_campaign_stats_ok():
    """正常返回活动统计数据"""
    _fake_ref_svc.get_referral_stats = AsyncMock(return_value={
        "total_invitees": 50,
        "total_conversions": 30,
        "referrer_rewards_issued": 25,
    })

    mock_db = _make_mock_db()
    app = _build_app(mock_db)
    c = TestClient(app, raise_server_exceptions=False)

    resp = c.get(
        f"/api/v1/growth/referrals/campaigns/{_CAMPAIGN_ID}/stats",
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total_invitees"] == 50


def test_get_campaign_stats_not_found():
    """活动不存在 → 404"""
    _fake_ref_svc.get_referral_stats = AsyncMock(
        side_effect=_ReferralError("CAMPAIGN_NOT_FOUND", "活动不存在")
    )

    mock_db = _make_mock_db()
    app = _build_app(mock_db)
    c = TestClient(app, raise_server_exceptions=False)

    resp = c.get(
        f"/api/v1/growth/referrals/campaigns/{_CAMPAIGN_ID}/stats",
        headers=_HEADERS,
    )
    assert resp.status_code == 404


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 8-9: POST /invite/generate
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_generate_invite_link_ok():
    """正常生成专属邀请链接"""
    _fake_ref_svc.generate_invite_link = AsyncMock(return_value={
        "invite_code": "INV_ABC123",
        "invite_url": "https://miniapp.tunxiang.com/invite?code=INV_ABC123",
        "expires_at": "2026-05-01T00:00:00",
    })

    mock_db = _make_mock_db()
    app = _build_app(mock_db)
    c = TestClient(app, raise_server_exceptions=False)

    resp = c.post(
        "/api/v1/growth/referrals/invite/generate",
        headers=_HEADERS,
        json={
            "campaign_id": _CAMPAIGN_ID,
            "referrer_customer_id": _CUSTOMER_ID,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "invite_code" in body["data"]


def test_generate_invite_link_campaign_not_found():
    """活动不存在 → 404"""
    _fake_ref_svc.generate_invite_link = AsyncMock(
        side_effect=_ReferralError("CAMPAIGN_NOT_FOUND", "活动不存在")
    )

    mock_db = _make_mock_db()
    app = _build_app(mock_db)
    c = TestClient(app, raise_server_exceptions=False)

    resp = c.post(
        "/api/v1/growth/referrals/invite/generate",
        headers=_HEADERS,
        json={
            "campaign_id": _CAMPAIGN_ID,
            "referrer_customer_id": _CUSTOMER_ID,
        },
    )
    assert resp.status_code == 404


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 10-12: POST /invite/register
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_register_via_invite_ok():
    """正常通过邀请码注册绑定"""
    _fake_ref_svc.register_via_invite = AsyncMock(return_value={
        "registered": True,
        "invite_code": "INV_ABC123",
        "invitee_reward_issued": True,
    })

    mock_db = _make_mock_db()
    app = _build_app(mock_db)
    c = TestClient(app, raise_server_exceptions=False)

    resp = c.post(
        "/api/v1/growth/referrals/invite/register",
        headers=_HEADERS,
        json={
            "invite_code": "INV_ABC123",
            "new_customer_id": str(uuid.uuid4()),
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["registered"] is True


def test_register_via_invite_fraud_blocked():
    """欺诈检测拦截（同设备）→ 403"""
    _fake_ref_svc.register_via_invite = AsyncMock(
        side_effect=_ReferralError("FRAUD_SAME_DEVICE", "设备已被使用")
    )

    mock_db = _make_mock_db()
    app = _build_app(mock_db)
    c = TestClient(app, raise_server_exceptions=False)

    resp = c.post(
        "/api/v1/growth/referrals/invite/register",
        headers=_HEADERS,
        json={
            "invite_code": "INV_ABC123",
            "new_customer_id": str(uuid.uuid4()),
            "device_id": "same_device_123",
        },
    )
    assert resp.status_code == 403


def test_register_via_invite_code_not_found():
    """邀请码不存在 → 404"""
    _fake_ref_svc.register_via_invite = AsyncMock(
        side_effect=_ReferralError("INVITE_CODE_NOT_FOUND", "邀请码不存在")
    )

    mock_db = _make_mock_db()
    app = _build_app(mock_db)
    c = TestClient(app, raise_server_exceptions=False)

    resp = c.post(
        "/api/v1/growth/referrals/invite/register",
        headers=_HEADERS,
        json={
            "invite_code": "INVALID_CODE",
            "new_customer_id": str(uuid.uuid4()),
        },
    )
    assert resp.status_code == 404


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 13-14: POST /invite/first-order
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_first_order_trigger_ok():
    """正常触发首单奖励"""
    _fake_ref_svc.process_first_order = AsyncMock(return_value={
        "reward_issued": True,
        "referrer_rewarded": True,
    })

    mock_db = _make_mock_db()
    app = _build_app(mock_db)
    c = TestClient(app, raise_server_exceptions=False)

    resp = c.post(
        "/api/v1/growth/referrals/invite/first-order",
        headers=_HEADERS,
        json={
            "order_id": str(uuid.uuid4()),
            "customer_id": _CUSTOMER_ID,
            "order_amount_fen": 8800,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["reward_issued"] is True


def test_first_order_trigger_zero_amount():
    """订单金额为 0 → 422（order_amount_fen 必须 > 0）"""
    mock_db = _make_mock_db()
    app = _build_app(mock_db)
    c = TestClient(app, raise_server_exceptions=False)

    resp = c.post(
        "/api/v1/growth/referrals/invite/first-order",
        headers=_HEADERS,
        json={
            "order_id": str(uuid.uuid4()),
            "customer_id": _CUSTOMER_ID,
            "order_amount_fen": 0,
        },
    )
    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 15-16: GET /my-invites
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_get_my_invites_ok():
    """正常返回我的邀请记录列表"""
    _fake_ref_svc.get_my_referrals = AsyncMock(return_value={
        "items": [
            {"invitee_name": "张三", "status": "rewarded", "created_at": _NOW.isoformat()},
        ],
        "total": 1,
    })

    mock_db = _make_mock_db()
    app = _build_app(mock_db)
    c = TestClient(app, raise_server_exceptions=False)

    resp = c.get(
        "/api/v1/growth/referrals/my-invites",
        headers=_HEADERS,
        params={"campaign_id": _CAMPAIGN_ID, "customer_id": _CUSTOMER_ID},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 1


def test_get_my_invites_campaign_not_found():
    """活动不存在 → 404"""
    _fake_ref_svc.get_my_referrals = AsyncMock(
        side_effect=_ReferralError("CAMPAIGN_NOT_FOUND", "活动不存在")
    )

    mock_db = _make_mock_db()
    app = _build_app(mock_db)
    c = TestClient(app, raise_server_exceptions=False)

    resp = c.get(
        "/api/v1/growth/referrals/my-invites",
        headers=_HEADERS,
        params={"campaign_id": _CAMPAIGN_ID, "customer_id": _CUSTOMER_ID},
    )
    assert resp.status_code == 404
