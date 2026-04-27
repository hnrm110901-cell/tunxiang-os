"""营销活动 & 拼团详情 API 路由测试

覆盖 campaign_routes.py（8 端点）:
1.  POST /api/v1/campaigns              — 创建活动成功
2.  POST /api/v1/campaigns              — engine 返回 error
3.  POST /api/v1/campaigns/{id}/start   — 启动成功
4.  POST /api/v1/campaigns/{id}/start   — 启动失败 error
5.  POST /api/v1/campaigns/{id}/pause   — 暂停成功
6.  POST /api/v1/campaigns/{id}/end     — 结束成功
7.  GET  /api/v1/campaigns/{id}         — 获取详情存在
8.  GET  /api/v1/campaigns/{id}         — 详情不存在
9.  GET  /api/v1/campaigns              — 列表返回
10. POST /api/v1/campaigns/{id}/check   — 资格检查成功
11. GET  /api/v1/campaigns/{id}/analytics — 分析成功
12. GET  /api/v1/campaigns/{id}/analytics — 分析 error

覆盖 group_buy_detail_routes.py（3 端点）:
13. GET  /api/v1/group-buy/campaigns/{id}  — 拼团详情成功
14. GET  /api/v1/group-buy/campaigns/{id}  — 活动不存在 NOT_FOUND
15. GET  /api/v1/group-buy/campaigns/{id}  — DB 表不存在 TABLE_NOT_READY
16. POST /api/v1/group-buy/join            — 开新团成功
17. POST /api/v1/group-buy/join            — 加入已有团成功
18. POST /api/v1/group-buy/join            — 活动不存在
19. GET  /api/v1/group-buy/my-orders       — 我的团购列表
20. GET  /api/v1/group-buy/my-orders       — DB 表不存在 fallback 空列表
"""

import os
import sys
import types
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ---------------------------------------------------------------------------
# 伪模块注入
# ---------------------------------------------------------------------------

_shared_mod = sys.modules.get("shared") or types.ModuleType("shared")
_shared_ontology = sys.modules.get("shared.ontology") or types.ModuleType("shared.ontology")
_shared_ontology_src = sys.modules.get("shared.ontology.src") or types.ModuleType("shared.ontology.src")
_shared_ontology_src_db = sys.modules.get("shared.ontology.src.database") or types.ModuleType(
    "shared.ontology.src.database"
)

TENANT_ID = str(uuid.uuid4())
CAMPAIGN_ID = str(uuid.uuid4())
CUSTOMER_ID = str(uuid.uuid4())
ACTIVITY_ID = str(uuid.uuid4())
TEAM_ID = str(uuid.uuid4())


async def _fake_get_db():
    yield AsyncMock()


_shared_ontology_src_db.get_db = _fake_get_db
_shared_ontology_src_db.get_db_with_tenant = AsyncMock()

sys.modules["shared"] = _shared_mod
sys.modules["shared.ontology"] = _shared_ontology
sys.modules["shared.ontology.src"] = _shared_ontology_src
sys.modules["shared.ontology.src.database"] = _shared_ontology_src_db

# Stub structlog
_structlog = sys.modules.get("structlog") or types.ModuleType("structlog")
_structlog.get_logger = lambda *a, **kw: MagicMock()
sys.modules["structlog"] = _structlog

# ---------------------------------------------------------------------------
# campaign_routes 依赖: CampaignEngine + CampaignRepository
# These are relative imports (..services.*), injected via sys.modules
# ---------------------------------------------------------------------------

# We patch at module level since relative imports use package resolution.
# Build the package hierarchy src.services.* so the relative imports resolve.

_src_pkg = sys.modules.get("src") or types.ModuleType("src")
_src_services = sys.modules.get("src.services") or types.ModuleType("src.services")
_src_api = sys.modules.get("src.api") or types.ModuleType("src.api")

sys.modules["src"] = _src_pkg
sys.modules["src.services"] = _src_services
sys.modules["src.api"] = _src_api

# Stub CampaignEngine
_engine_mod = types.ModuleType("src.services.campaign_engine")


class _MockCampaignEngine:
    async def create_campaign(self, *a, **kw):
        return {"id": CAMPAIGN_ID, "status": "draft"}

    async def start_campaign(self, *a, **kw):
        return {"id": CAMPAIGN_ID, "status": "active"}

    async def pause_campaign(self, *a, **kw):
        return {"id": CAMPAIGN_ID, "status": "paused"}

    async def end_campaign(self, *a, **kw):
        return {"id": CAMPAIGN_ID, "status": "ended"}

    async def check_eligibility(self, *a, **kw):
        return {"eligible": True, "reason": "ok"}

    async def get_campaign_analytics(self, *a, **kw):
        return {"total_participants": 10, "conversion_rate": 0.3}


_engine_mod.CampaignEngine = _MockCampaignEngine
sys.modules["src.services.campaign_engine"] = _engine_mod

# Stub CampaignRepository
_repo_mod = types.ModuleType("src.services.campaign_repository")


class _MockCampaignRepository:
    def __init__(self, db, tenant_id):
        self.db = db
        self.tenant_id = tenant_id

    async def get_campaign(self, campaign_id):
        return {"id": campaign_id, "status": "active"}

    async def list_campaigns(self, status=None):
        return [{"id": CAMPAIGN_ID, "status": status or "active"}]


_repo_mod.CampaignRepository = _MockCampaignRepository
sys.modules["src.services.campaign_repository"] = _repo_mod

# ---------------------------------------------------------------------------
# Import route modules with patched engine
# ---------------------------------------------------------------------------

from fastapi import FastAPI
from fastapi.testclient import TestClient

# -- campaign_routes --
# Patch relative imports by temporarily setting __package__ trick via sys.modules
# We import directly after stubbing the dependency modules

# The relative imports in campaign_routes use '..services.*', which resolves to
# src.services.* when the package is src.api. We set that up above.
# Direct import (not as package) requires us to mock those at the top-level name.

# Re-stub without package prefix for direct import context
_campaign_engine_top = types.ModuleType("campaign_engine")
_campaign_engine_top.CampaignEngine = _MockCampaignEngine
sys.modules.setdefault("campaign_engine", _campaign_engine_top)

_campaign_repo_top = types.ModuleType("campaign_repository")
_campaign_repo_top.CampaignRepository = _MockCampaignRepository
sys.modules.setdefault("campaign_repository", _campaign_repo_top)

# We patch the relative-import resolution by loading via importlib after package setup
import importlib
import importlib.util


def _load_route_module(filepath, modname):
    spec = importlib.util.spec_from_file_location(modname, filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


_base = os.path.join(os.path.dirname(__file__), "..", "api")

# Patch the relative imports for campaign_routes by pre-populating
# the names they will look for under the loader's package namespace.
# Since we load as top-level, the relative imports '..services.*' will fail.
# We use monkeypatching at the sys.modules level to intercept.

# The campaign_routes does:
#   from ..services.campaign_engine import CampaignEngine
#   from ..services.campaign_repository import CampaignRepository
# When loaded as "api.campaign_routes" in package "api", parent is "" -> fails.
# So we stub them in a dummy parent package.

_api_pkg = types.ModuleType("api")
_api_services_pkg = (
    types.ModuleType("api.services") if "api.services" not in sys.modules else sys.modules["api.services"]
)
_api_campaign_engine = types.ModuleType("api.services.campaign_engine")
_api_campaign_engine.CampaignEngine = _MockCampaignEngine
_api_campaign_repo = types.ModuleType("api.services.campaign_repository")
_api_campaign_repo.CampaignRepository = _MockCampaignRepository

sys.modules["api"] = _api_pkg
sys.modules["api.services"] = _api_services_pkg
sys.modules["api.services.campaign_engine"] = _api_campaign_engine
sys.modules["api.services.campaign_repository"] = _api_campaign_repo

# Also need models + services stubs if not already set
if "models" not in sys.modules:
    sys.modules["models"] = types.ModuleType("models")
if "services" not in sys.modules:
    sys.modules["services"] = types.ModuleType("services")

# Load campaign_routes as "api.campaign_routes"
_campaign_mod = _load_route_module(
    os.path.join(_base, "campaign_routes.py"),
    "api.campaign_routes",
)
_campaign_engine_instance = _campaign_mod.engine

# Load group_buy_detail_routes as "api.group_buy_detail_routes"
_gb_mod = _load_route_module(
    os.path.join(_base, "group_buy_detail_routes.py"),
    "api.group_buy_detail_routes",
)

# ---------------------------------------------------------------------------
# Build apps
# ---------------------------------------------------------------------------

campaign_app = FastAPI()
campaign_app.include_router(_campaign_mod.router)
campaign_client = TestClient(campaign_app, raise_server_exceptions=False)

gb_app = FastAPI()
gb_app.include_router(_gb_mod.router)
gb_client = TestClient(gb_app, raise_server_exceptions=False)

_H = {"X-Tenant-ID": TENANT_ID}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeRow:
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


def _exec_returning(row):
    """Return a mock execute result whose .fetchone() returns `row`."""
    res = MagicMock()
    res.fetchone = MagicMock(return_value=row)
    res.fetchall = MagicMock(return_value=[])
    res.scalar = MagicMock(return_value=None)
    return AsyncMock(return_value=res)


def _exec_returning_all(rows):
    res = MagicMock()
    res.fetchone = MagicMock(return_value=rows[0] if rows else None)
    res.fetchall = MagicMock(return_value=rows)
    res.scalar = MagicMock(return_value=len(rows))
    return AsyncMock(return_value=res)


# ===========================================================================
# campaign_routes tests
# ===========================================================================


def test_create_campaign_success(monkeypatch):
    monkeypatch.setattr(
        _campaign_engine_instance,
        "create_campaign",
        AsyncMock(return_value={"id": CAMPAIGN_ID, "status": "draft"}),
    )
    resp = campaign_client.post(
        "/api/v1/campaigns",
        json={"campaign_type": "discount", "config": {}},
        headers=_H,
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_create_campaign_engine_error(monkeypatch):
    monkeypatch.setattr(
        _campaign_engine_instance,
        "create_campaign",
        AsyncMock(return_value={"error": "类型不支持"}),
    )
    resp = campaign_client.post(
        "/api/v1/campaigns",
        json={"campaign_type": "unknown", "config": {}},
        headers=_H,
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is False


def test_start_campaign_success(monkeypatch):
    monkeypatch.setattr(
        _campaign_engine_instance,
        "start_campaign",
        AsyncMock(return_value={"id": CAMPAIGN_ID, "status": "active"}),
    )
    resp = campaign_client.post(f"/api/v1/campaigns/{CAMPAIGN_ID}/start", headers=_H)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_start_campaign_error(monkeypatch):
    monkeypatch.setattr(
        _campaign_engine_instance,
        "start_campaign",
        AsyncMock(return_value={"error": "状态非法"}),
    )
    resp = campaign_client.post(f"/api/v1/campaigns/{CAMPAIGN_ID}/start", headers=_H)
    assert resp.json()["ok"] is False


def test_pause_campaign_success(monkeypatch):
    monkeypatch.setattr(
        _campaign_engine_instance,
        "pause_campaign",
        AsyncMock(return_value={"id": CAMPAIGN_ID, "status": "paused"}),
    )
    resp = campaign_client.post(f"/api/v1/campaigns/{CAMPAIGN_ID}/pause", headers=_H)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_end_campaign_success(monkeypatch):
    monkeypatch.setattr(
        _campaign_engine_instance,
        "end_campaign",
        AsyncMock(return_value={"id": CAMPAIGN_ID, "status": "ended"}),
    )
    resp = campaign_client.post(f"/api/v1/campaigns/{CAMPAIGN_ID}/end", headers=_H)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_get_campaign_detail_found(monkeypatch):
    # CampaignRepository is instantiated per-request, patch the class
    mock_repo = MagicMock()
    mock_repo.get_campaign = AsyncMock(return_value={"id": CAMPAIGN_ID, "status": "active"})
    monkeypatch.setattr(_campaign_mod, "CampaignRepository", lambda db, tid: mock_repo)
    resp = campaign_client.get(f"/api/v1/campaigns/{CAMPAIGN_ID}", headers=_H)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_get_campaign_detail_not_found(monkeypatch):
    mock_repo = MagicMock()
    mock_repo.get_campaign = AsyncMock(return_value=None)
    monkeypatch.setattr(_campaign_mod, "CampaignRepository", lambda db, tid: mock_repo)
    resp = campaign_client.get(f"/api/v1/campaigns/{CAMPAIGN_ID}", headers=_H)
    assert resp.json()["ok"] is False


def test_list_campaigns(monkeypatch):
    mock_repo = MagicMock()
    mock_repo.list_campaigns = AsyncMock(return_value=[{"id": CAMPAIGN_ID}])
    monkeypatch.setattr(_campaign_mod, "CampaignRepository", lambda db, tid: mock_repo)
    resp = campaign_client.get("/api/v1/campaigns", headers=_H)
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 1


def test_check_eligibility(monkeypatch):
    monkeypatch.setattr(
        _campaign_engine_instance,
        "check_eligibility",
        AsyncMock(return_value={"eligible": True}),
    )
    resp = campaign_client.post(
        f"/api/v1/campaigns/{CAMPAIGN_ID}/check",
        json={"customer_id": CUSTOMER_ID},
        headers=_H,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["eligible"] is True


def test_get_campaign_analytics_success(monkeypatch):
    monkeypatch.setattr(
        _campaign_engine_instance,
        "get_campaign_analytics",
        AsyncMock(return_value={"total_participants": 50}),
    )
    resp = campaign_client.get(f"/api/v1/campaigns/{CAMPAIGN_ID}/analytics", headers=_H)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_get_campaign_analytics_error(monkeypatch):
    monkeypatch.setattr(
        _campaign_engine_instance,
        "get_campaign_analytics",
        AsyncMock(return_value={"error": "活动不存在"}),
    )
    resp = campaign_client.get(f"/api/v1/campaigns/{CAMPAIGN_ID}/analytics", headers=_H)
    assert resp.json()["ok"] is False


# ===========================================================================
# group_buy_detail_routes tests
# ===========================================================================

_NOW = datetime.now(timezone.utc)
_FUTURE = _NOW + timedelta(hours=2)


def _act_row(**overrides):
    defaults = dict(
        id=uuid.UUID(ACTIVITY_ID),
        name="春节拼团",
        product_id=uuid.uuid4(),
        product_name="烤鸭",
        original_price_fen=8800,
        group_price_fen=5800,
        group_size=3,
        max_teams=100,
        team_count=5,
        time_limit_minutes=60,
        status="active",
        start_time=_NOW - timedelta(hours=1),
        end_time=_NOW + timedelta(hours=24),
        success_count=2,
    )
    defaults.update(overrides)
    return _FakeRow(**defaults)


def _make_gb_db(*execute_side_effects):
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=list(execute_side_effects))
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _res(row=None, rows=None, scalar_val=None):
    m = MagicMock()
    m.fetchone = MagicMock(return_value=row)
    m.fetchall = MagicMock(return_value=rows or [])
    m.scalar = MagicMock(return_value=scalar_val)
    return AsyncMock(return_value=m)


def test_get_group_buy_campaign_detail_success():
    """拼团详情 — 活动存在，无进行中的团"""
    db = AsyncMock()
    # set_config call
    set_cfg = _res()
    # activity query
    act_res = _res(row=_act_row())
    # teams query (empty)
    teams_res = _res(rows=[])
    db.execute = AsyncMock(side_effect=[set_cfg, act_res, teams_res])

    gb_app.dependency_overrides[_gb_mod.get_db] = lambda: db
    try:
        resp = gb_client.get(f"/api/v1/group-buy/campaigns/{ACTIVITY_ID}", headers=_H)
    finally:
        gb_app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["name"] == "春节拼团"
    assert body["data"]["forming_teams"] == []


def test_get_group_buy_campaign_detail_not_found():
    """拼团详情 — 活动不存在"""
    db = AsyncMock()
    set_cfg = _res()
    act_res = _res(row=None)
    db.execute = AsyncMock(side_effect=[set_cfg, act_res])

    gb_app.dependency_overrides[_gb_mod.get_db] = lambda: db
    try:
        resp = gb_client.get(f"/api/v1/group-buy/campaigns/{ACTIVITY_ID}", headers=_H)
    finally:
        gb_app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "NOT_FOUND"


def test_get_group_buy_campaign_table_not_ready():
    """拼团详情 — DB 表不存在"""
    from sqlalchemy.exc import OperationalError

    db = AsyncMock()
    set_cfg = _res()
    db.execute = AsyncMock(side_effect=[set_cfg, OperationalError("relation does not exist", None, None)])

    gb_app.dependency_overrides[_gb_mod.get_db] = lambda: db
    try:
        resp = gb_client.get(f"/api/v1/group-buy/campaigns/{ACTIVITY_ID}", headers=_H)
    finally:
        gb_app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "TABLE_NOT_READY"


def test_join_group_buy_new_team():
    """参团 — 开新团成功"""
    db = AsyncMock()
    set_cfg = _res()
    act_res = _res(row=_act_row())
    # insert new team
    insert_team = _res()
    # update activity team_count
    update_act = _res()
    # insert member
    insert_member = _res()
    db.execute = AsyncMock(side_effect=[set_cfg, act_res, insert_team, update_act, insert_member])
    db.commit = AsyncMock()

    gb_app.dependency_overrides[_gb_mod.get_db] = lambda: db
    try:
        resp = gb_client.post(
            "/api/v1/group-buy/join",
            json={"campaign_id": ACTIVITY_ID, "customer_id": CUSTOMER_ID, "quantity": 1},
            headers=_H,
        )
    finally:
        gb_app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "team_id" in body["data"]


def test_join_group_buy_existing_team():
    """参团 — 加入已有团（非满团）"""
    db = AsyncMock()
    set_cfg = _res()
    act_res = _res(row=_act_row())
    team_row = _FakeRow(
        id=uuid.UUID(TEAM_ID),
        current_size=1,
        target_size=3,
        status="forming",
        expired_at=_FUTURE,
    )
    team_res = _res(row=team_row)
    # dup check
    dup_res = _res(row=None)
    # insert member
    insert_member = _res()
    # update current_size
    update_team = _res()
    db.execute = AsyncMock(side_effect=[set_cfg, act_res, team_res, dup_res, insert_member, update_team])
    db.commit = AsyncMock()

    gb_app.dependency_overrides[_gb_mod.get_db] = lambda: db
    try:
        resp = gb_client.post(
            "/api/v1/group-buy/join",
            json={"campaign_id": ACTIVITY_ID, "team_id": TEAM_ID, "customer_id": CUSTOMER_ID},
            headers=_H,
        )
    finally:
        gb_app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "forming"


def test_join_group_buy_activity_not_found():
    """参团 — 活动不存在"""
    db = AsyncMock()
    set_cfg = _res()
    act_res = _res(row=None)
    db.execute = AsyncMock(side_effect=[set_cfg, act_res])

    gb_app.dependency_overrides[_gb_mod.get_db] = lambda: db
    try:
        resp = gb_client.post(
            "/api/v1/group-buy/join",
            json={"campaign_id": ACTIVITY_ID, "customer_id": CUSTOMER_ID},
            headers=_H,
        )
    finally:
        gb_app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_get_my_orders_success():
    """我的团购 — 正常返回列表"""
    db = AsyncMock()
    set_cfg = _res()
    count_res = MagicMock()
    count_res.scalar = MagicMock(return_value=1)
    count_async = AsyncMock(return_value=count_res)

    row = _FakeRow(
        team_id=uuid.UUID(TEAM_ID),
        activity_id=uuid.UUID(ACTIVITY_ID),
        target_size=3,
        current_size=2,
        team_status="forming",
        expired_at=_FUTURE,
        succeeded_at=None,
        activity_name="春节拼团",
        group_price_fen=5800,
        original_price_fen=8800,
        product_name="烤鸭",
        joined_at=_NOW,
    )
    rows_res = _res(rows=[row])

    db.execute = AsyncMock(side_effect=[set_cfg, count_async, rows_res])

    gb_app.dependency_overrides[_gb_mod.get_db] = lambda: db
    try:
        resp = gb_client.get(
            "/api/v1/group-buy/my-orders",
            params={"customer_id": CUSTOMER_ID, "status": "forming"},
            headers=_H,
        )
    finally:
        gb_app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 1


def test_get_my_orders_table_not_ready():
    """我的团购 — DB 表不存在 fallback 空列表"""
    from sqlalchemy.exc import OperationalError

    db = AsyncMock()
    set_cfg = _res()
    db.execute = AsyncMock(side_effect=[set_cfg, OperationalError("relation does not exist", None, None)])

    gb_app.dependency_overrides[_gb_mod.get_db] = lambda: db
    try:
        resp = gb_client.get(
            "/api/v1/group-buy/my-orders",
            params={"customer_id": CUSTOMER_ID},
            headers=_H,
        )
    finally:
        gb_app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["items"] == []
    assert "_note" in body["data"]
