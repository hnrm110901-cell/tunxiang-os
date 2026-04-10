"""营销活动管理 API 路由测试 — api/growth_campaign_routes.py

覆盖场景（14个）：
1.  GET  /api/v1/growth/campaigns          — 正常列表（空过滤）返回 items/total
2.  GET  /api/v1/growth/campaigns          — status 过滤无效值返回 INVALID_STATUS
3.  GET  /api/v1/growth/campaigns          — type 过滤无效值返回 INVALID_TYPE
4.  GET  /api/v1/growth/campaigns          — DB 表不存在时降级返回 TABLE_NOT_READY note
5.  POST /api/v1/growth/campaigns          — 正常创建 draft 活动返回 campaign_id
6.  POST /api/v1/growth/campaigns          — 无效 type 返回 INVALID_TYPE
7.  PUT  /api/v1/growth/campaigns/{id}     — draft 活动正常更新返回 updated 结果
8.  PUT  /api/v1/growth/campaigns/{id}     — 活动不存在返回 NOT_FOUND
9.  PUT  /api/v1/growth/campaigns/{id}     — 非 draft 状态返回 NOT_DRAFT
10. POST /api/v1/growth/campaigns/{id}/activate  — 正常激活返回 ok
11. POST /api/v1/growth/campaigns/{id}/end       — 正常结束返回 ok
12. GET  /api/v1/growth/campaigns/{id}/stats     — 正常返回统计数据
13. POST /api/v1/growth/campaigns/{id}/deactivate — 正常停用返回 cancelled
14. POST /api/v1/growth/campaigns/apply-to-order  — 有可用券时返回 eligible_coupons
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import types
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

# ── 注入假依赖模块 ────────────────────────────────────────────────────────────

# shared.ontology.src.database — 提供 get_db
_fake_db_mod = types.ModuleType("shared.ontology.src.database")

async def _fake_get_db():
    yield None

_fake_db_mod.get_db = _fake_get_db
sys.modules.setdefault("shared", types.ModuleType("shared"))
sys.modules.setdefault("shared.ontology", types.ModuleType("shared.ontology"))
sys.modules.setdefault("shared.ontology.src", types.ModuleType("shared.ontology.src"))
sys.modules["shared.ontology.src.database"] = _fake_db_mod

# shared.events.src.emitter
_fake_emitter = types.ModuleType("shared.events.src.emitter")
_fake_emitter.emit_event = AsyncMock()
sys.modules.setdefault("shared.events", types.ModuleType("shared.events"))
sys.modules.setdefault("shared.events.src", types.ModuleType("shared.events.src"))
sys.modules["shared.events.src.emitter"] = _fake_emitter

# services.campaign_engine + services.campaign_repository（相对导入 ..services.*）
_fake_campaign_engine_inst = MagicMock()
_fake_campaign_engine_inst.create_campaign = AsyncMock(return_value={"campaign_id": str(uuid.uuid4()), "status": "draft"})
_fake_campaign_engine_inst.start_campaign = AsyncMock(return_value={"campaign_id": str(uuid.uuid4()), "status": "active"})
_fake_campaign_engine_inst.end_campaign = AsyncMock(return_value={"campaign_id": str(uuid.uuid4()), "status": "ended"})

_fake_engine_mod = types.ModuleType("src.services.campaign_engine")
_fake_engine_mod.CampaignEngine = MagicMock(return_value=_fake_campaign_engine_inst)

_fake_repo_inst = MagicMock()
_fake_repo_inst.get_campaign = AsyncMock(return_value=None)
_fake_repo_inst.get_analytics = AsyncMock(return_value=None)

_fake_repo_mod = types.ModuleType("src.services.campaign_repository")
_fake_repo_mod.CampaignRepository = MagicMock(return_value=_fake_repo_inst)

sys.modules.setdefault("src", types.ModuleType("src"))
sys.modules.setdefault("src.services", types.ModuleType("src.services"))
sys.modules["src.services.campaign_engine"] = _fake_engine_mod
sys.modules["src.services.campaign_repository"] = _fake_repo_mod

# 让相对导入 ..services.* 指向同一模块
_services_mod = sys.modules["src.services"]
_services_mod.campaign_engine = _fake_engine_mod
_services_mod.campaign_repository = _fake_repo_mod

# ── 加载路由 ──────────────────────────────────────────────────────────────────

with patch.dict("sys.modules", {
    "src.services.campaign_engine": _fake_engine_mod,
    "src.services.campaign_repository": _fake_repo_mod,
}):
    with patch("src.services.campaign_engine.CampaignEngine", _fake_engine_mod.CampaignEngine):
        from api.growth_campaign_routes import router, get_db

app = FastAPI()
app.include_router(router)
client = TestClient(app, raise_server_exceptions=False)

# ── 常量 ──────────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
CAMPAIGN_ID = str(uuid.uuid4())
_HEADERS = {"X-Tenant-ID": TENANT_ID}
_NOW = datetime(2026, 4, 4, 10, 0, tzinfo=timezone.utc)


# ── 辅助工具 ──────────────────────────────────────────────────────────────────

class _FakeRow:
    """模拟 SQLAlchemy named-column row"""
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

    def __getattr__(self, name):
        return None


def _make_db(*execute_side_effects):
    """构建 AsyncMock DB session，按顺序返回 execute 结果"""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=list(execute_side_effects))
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _campaign_row():
    return _FakeRow(
        id=uuid.UUID(CAMPAIGN_ID),
        campaign_type="coupon_giveaway",
        name="春节大促",
        description="春节期间满减活动",
        status="draft",
        config={"rules": {}},
        start_time=_NOW,
        end_time=_NOW,
        budget_fen=100000,
        spent_fen=0,
        target_segments=["all"],
        participant_count=0,
        reward_count=0,
        total_cost_fen=0,
        conversion_count=0,
        created_at=_NOW,
        updated_at=_NOW,
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 1: GET /campaigns — 正常路径返回 items/total
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_list_campaigns_ok():
    """正常列表请求返回 items/total 字段"""
    set_cfg = MagicMock()
    count_result = MagicMock()
    count_result.scalar = MagicMock(return_value=1)
    rows_result = MagicMock()
    rows_result.fetchall = MagicMock(return_value=[_campaign_row()])

    mock_db = _make_db(set_cfg, count_result, rows_result)

    app.dependency_overrides[get_db] = lambda: mock_db
    resp = client.get("/api/v1/growth/campaigns", headers=_HEADERS)
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "items" in body["data"]
    assert "total" in body["data"]
    assert body["data"]["total"] == 1


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 2: GET /campaigns — 无效 status 参数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_list_campaigns_invalid_status():
    """status 参数无效时返回 INVALID_STATUS 错误"""
    mock_db = _make_db()
    app.dependency_overrides[get_db] = lambda: mock_db
    resp = client.get("/api/v1/growth/campaigns?status=INVALID", headers=_HEADERS)
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "INVALID_STATUS"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 3: GET /campaigns — 无效 type 参数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_list_campaigns_invalid_type():
    """type 参数无效时返回 INVALID_TYPE 错误"""
    mock_db = _make_db()
    app.dependency_overrides[get_db] = lambda: mock_db
    resp = client.get("/api/v1/growth/campaigns?type=BOGUS", headers=_HEADERS)
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "INVALID_TYPE"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 4: GET /campaigns — DB 表不存在时降级
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_list_campaigns_table_not_ready():
    """DB 表不存在时返回空列表并包含 TABLE_NOT_READY note"""
    exc = OperationalError("relation campaigns does not exist", None, None)
    set_cfg = MagicMock()
    mock_db = _make_db(set_cfg, exc)

    app.dependency_overrides[get_db] = lambda: mock_db
    resp = client.get("/api/v1/growth/campaigns", headers=_HEADERS)
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["items"] == []
    assert "_note" in body["data"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 5: POST /campaigns — 正常创建
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_create_campaign_ok():
    """正常创建营销活动返回 campaign_id"""
    new_campaign_id = str(uuid.uuid4())
    _fake_campaign_engine_inst.create_campaign = AsyncMock(
        return_value={"campaign_id": new_campaign_id, "status": "draft"}
    )

    mock_db = _make_db()
    mock_db.commit = AsyncMock()

    app.dependency_overrides[get_db] = lambda: mock_db
    resp = client.post(
        "/api/v1/growth/campaigns",
        json={
            "name": "春节大促",
            "type": "coupon_giveaway",
            "description": "春节满减活动",
            "budget_fen": 100000,
        },
        headers=_HEADERS,
    )
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "campaign_id" in body["data"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 6: POST /campaigns — 无效 type
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_create_campaign_invalid_type():
    """无效 campaign type 返回 INVALID_TYPE"""
    mock_db = _make_db()
    app.dependency_overrides[get_db] = lambda: mock_db
    resp = client.post(
        "/api/v1/growth/campaigns",
        json={"name": "测试", "type": "INVALID_TYPE"},
        headers=_HEADERS,
    )
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "INVALID_TYPE"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 7: PUT /campaigns/{id} — draft 活动正常更新
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_update_campaign_ok():
    """draft 活动正常更新，返回更新后的结果"""
    campaign_data = {
        "id": CAMPAIGN_ID,
        "status": "draft",
        "config": {"rules": {}},
        "name": "更新后名称",
        "description": "新描述",
        "campaign_type": "coupon_giveaway",
        "start_time": None,
        "end_time": None,
        "budget_fen": 50000,
        "spent_fen": 0,
        "target_segments": ["all"],
        "participant_count": 0,
        "reward_count": 0,
        "total_cost_fen": 0,
        "conversion_count": 0,
        "created_at": _NOW.isoformat(),
        "updated_at": _NOW.isoformat(),
    }
    _fake_repo_inst.get_campaign = AsyncMock(return_value=campaign_data)

    set_cfg = MagicMock()
    update_result = MagicMock()
    mock_db = _make_db(set_cfg, update_result)
    mock_db.commit = AsyncMock()

    app.dependency_overrides[get_db] = lambda: mock_db
    resp = client.put(
        f"/api/v1/growth/campaigns/{CAMPAIGN_ID}",
        json={"name": "更新后名称", "description": "新描述"},
        headers=_HEADERS,
    )
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 8: PUT /campaigns/{id} — 活动不存在
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_update_campaign_not_found():
    """活动不存在时返回 NOT_FOUND"""
    _fake_repo_inst.get_campaign = AsyncMock(return_value=None)

    set_cfg = MagicMock()
    mock_db = _make_db(set_cfg)
    mock_db.commit = AsyncMock()

    app.dependency_overrides[get_db] = lambda: mock_db
    resp = client.put(
        f"/api/v1/growth/campaigns/{CAMPAIGN_ID}",
        json={"name": "新名称"},
        headers=_HEADERS,
    )
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "NOT_FOUND"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 9: PUT /campaigns/{id} — 非 draft 状态
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_update_campaign_not_draft():
    """active 状态活动不可修改，返回 NOT_DRAFT"""
    _fake_repo_inst.get_campaign = AsyncMock(return_value={
        "id": CAMPAIGN_ID,
        "status": "active",
        "config": {},
    })

    set_cfg = MagicMock()
    mock_db = _make_db(set_cfg)

    app.dependency_overrides[get_db] = lambda: mock_db
    resp = client.put(
        f"/api/v1/growth/campaigns/{CAMPAIGN_ID}",
        json={"name": "尝试修改"},
        headers=_HEADERS,
    )
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "NOT_DRAFT"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 10: POST /campaigns/{id}/activate — 正常激活
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_activate_campaign_ok():
    """正常激活活动，返回 ok=True"""
    _fake_campaign_engine_inst.start_campaign = AsyncMock(
        return_value={"campaign_id": CAMPAIGN_ID, "status": "active"}
    )

    mock_db = _make_db()
    mock_db.commit = AsyncMock()

    app.dependency_overrides[get_db] = lambda: mock_db
    resp = client.post(
        f"/api/v1/growth/campaigns/{CAMPAIGN_ID}/activate",
        headers=_HEADERS,
    )
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "active"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 11: POST /campaigns/{id}/end — 正常结束
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_end_campaign_ok():
    """正常结束活动，返回 ok=True"""
    _fake_campaign_engine_inst.end_campaign = AsyncMock(
        return_value={"campaign_id": CAMPAIGN_ID, "status": "ended"}
    )

    mock_db = _make_db()
    mock_db.commit = AsyncMock()

    app.dependency_overrides[get_db] = lambda: mock_db
    resp = client.post(
        f"/api/v1/growth/campaigns/{CAMPAIGN_ID}/end",
        headers=_HEADERS,
    )
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "ended"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 12: GET /campaigns/{id}/stats — 正常统计
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_get_campaign_stats_ok():
    """正常返回活动效果统计数据"""
    _fake_repo_inst.get_analytics = AsyncMock(return_value={
        "campaign_name": "春节大促",
        "status": "active",
        "participant_count": 100,
        "total_cost_fen": 50000,
        "reward_breakdown": {},
        "budget_usage": 0.5,
    })

    set_cfg = MagicMock()
    distinct_result = MagicMock()
    distinct_row = MagicMock()
    distinct_row.distinct_customers = 80
    distinct_result.fetchone = MagicMock(return_value=distinct_row)
    used_result = MagicMock()
    used_result.scalar = MagicMock(return_value=20)

    mock_db = _make_db(set_cfg, distinct_result, used_result)

    app.dependency_overrides[get_db] = lambda: mock_db
    resp = client.get(
        f"/api/v1/growth/campaigns/{CAMPAIGN_ID}/stats",
        headers=_HEADERS,
    )
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "claimed_count" in body["data"]
    assert "participating_customers" in body["data"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 13: POST /campaigns/{id}/deactivate — 正常停用
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_deactivate_campaign_ok():
    """active 活动正常停用，返回 cancelled 状态"""
    set_cfg = MagicMock()
    status_row = MagicMock()
    status_row.fetchone = MagicMock(return_value=_FakeRow(status="active"))
    update_result = MagicMock()

    mock_db = _make_db(set_cfg, status_row, update_result)
    mock_db.commit = AsyncMock()

    app.dependency_overrides[get_db] = lambda: mock_db
    resp = client.post(
        f"/api/v1/growth/campaigns/{CAMPAIGN_ID}/deactivate",
        headers=_HEADERS,
    )
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "cancelled"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 14: POST /campaigns/apply-to-order — 无可用券
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_apply_to_order_no_eligible_coupons():
    """结账检查无可用券时返回空 eligible_coupons"""
    set_cfg = MagicMock()
    coupon_result = MagicMock()
    coupon_result.fetchall = MagicMock(return_value=[])
    campaign_result = MagicMock()
    campaign_result.fetchall = MagicMock(return_value=[])

    mock_db = _make_db(set_cfg, coupon_result, campaign_result)

    app.dependency_overrides[get_db] = lambda: mock_db
    resp = client.post(
        "/api/v1/growth/campaigns/apply-to-order",
        json={
            "order_id": str(uuid.uuid4()),
            "store_id": str(uuid.uuid4()),
            "customer_id": str(uuid.uuid4()),
            "order_amount_fen": 8800,
            "tenant_id": TENANT_ID,
        },
        headers=_HEADERS,
    )
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["eligible_coupons"] == []
    assert body["data"]["auto_applicable"] is False
