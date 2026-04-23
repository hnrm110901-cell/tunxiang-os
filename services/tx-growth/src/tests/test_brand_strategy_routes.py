"""品牌策略中枢 API 路由测试 — api/brand_strategy_routes.py

覆盖端点（8个）：
1.  GET  /api/v1/brand/profile           — 返回激活档案
2.  GET  /api/v1/brand/profile           — 无档案返回 404
3.  POST /api/v1/brand/profile           — 创建成功返回 201
4.  POST /api/v1/brand/profile           — ValueError → 422
5.  PUT  /api/v1/brand/profile/{id}      — 更新成功
6.  PUT  /api/v1/brand/profile/{id}      — 档案不存在返回 404
7.  GET  /api/v1/brand/calendar          — 返回列表
8.  GET  /api/v1/brand/calendar          — 空列表
9.  POST /api/v1/brand/calendar          — 创建节点成功
10. POST /api/v1/brand/calendar          — ValueError → 422
11. GET  /api/v1/brand/constraints       — 返回约束列表
12. GET  /api/v1/brand/constraints       — 空列表
13. POST /api/v1/brand/constraints       — 创建成功
14. POST /api/v1/brand/constraints       — ValueError → 422
15. GET  /api/v1/brand/content-brief     — 生成简报成功
16. GET  /api/v1/brand/content-brief     — 缺少 header → 400
"""

import os
import sys
import types
import uuid
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ---------------------------------------------------------------------------
# 预注入 shared.ontology.src.database 伪模块（避免真实 DB import）
# ---------------------------------------------------------------------------

_shared_mod = types.ModuleType("shared")
_shared_ontology = types.ModuleType("shared.ontology")
_shared_ontology_src = types.ModuleType("shared.ontology.src")
_shared_ontology_src_db = types.ModuleType("shared.ontology.src.database")

TENANT_ID = str(uuid.uuid4())


async def _fake_get_db_with_tenant(tenant_id_str: str):
    yield AsyncMock()


_shared_ontology_src_db.get_db_with_tenant = _fake_get_db_with_tenant
_shared_ontology_src_db.get_db = AsyncMock()

sys.modules.setdefault("shared", _shared_mod)
sys.modules.setdefault("shared.ontology", _shared_ontology)
sys.modules.setdefault("shared.ontology.src", _shared_ontology_src)
sys.modules.setdefault("shared.ontology.src.database", _shared_ontology_src_db)

# Stub structlog
_structlog = types.ModuleType("structlog")
_structlog.get_logger = lambda *a, **kw: MagicMock()
sys.modules.setdefault("structlog", _structlog)

# Stub models.brand_strategy (minimal stubs)
_models_pkg = types.ModuleType("models")
_brand_strategy_models = types.ModuleType("models.brand_strategy")

from typing import Optional

from pydantic import BaseModel


class BrandProfileCreate(BaseModel):
    brand_name: str
    brand_slogan: Optional[str] = None
    price_tier: str = "mid"
    target_segments: list = []
    key_scenarios: list = []


class BrandProfileUpdate(BaseModel):
    brand_name: Optional[str] = None
    brand_slogan: Optional[str] = None


class BrandSeasonalCalendarCreate(BaseModel):
    event_name: str
    event_date: str


class BrandContentConstraintsCreate(BaseModel):
    constraint_type: str
    constraint_value: str


_brand_strategy_models.BrandProfileCreate = BrandProfileCreate
_brand_strategy_models.BrandProfileUpdate = BrandProfileUpdate
_brand_strategy_models.BrandSeasonalCalendarCreate = BrandSeasonalCalendarCreate
_brand_strategy_models.BrandContentConstraintsCreate = BrandContentConstraintsCreate

sys.modules.setdefault("models", _models_pkg)
sys.modules.setdefault("models.brand_strategy", _brand_strategy_models)

# Stub services.brand_strategy_db_service
_svc_pkg = types.ModuleType("services")
_svc_db = types.ModuleType("services.brand_strategy_db_service")


class _FakeBrandStrategyDbService:
    async def get_active_profile(self, *a, **kw):
        return None

    async def create_profile(self, *a, **kw):
        return {}

    async def update_profile(self, *a, **kw):
        return {}

    async def list_calendar(self, *a, **kw):
        return []

    async def create_calendar_entry(self, *a, **kw):
        return {}

    async def list_constraints(self, *a, **kw):
        return []

    async def create_constraint(self, *a, **kw):
        return {}

    async def build_content_brief(self, *a, **kw):
        m = MagicMock()
        m.model_dump = MagicMock(return_value={"system_prompt": "test"})
        return m


_svc_db.BrandStrategyDbService = _FakeBrandStrategyDbService
sys.modules.setdefault("services", _svc_pkg)
sys.modules.setdefault("services.brand_strategy_db_service", _svc_db)

# ---------------------------------------------------------------------------
# 导入路由
# ---------------------------------------------------------------------------

from api.brand_strategy_routes import _svc, router
from fastapi import FastAPI
from fastapi.testclient import TestClient

app = FastAPI()
app.include_router(router)
client = TestClient(app, raise_server_exceptions=False)

_HEADERS = {"X-Tenant-ID": TENANT_ID}
_PROFILE_ID = str(uuid.uuid4())

# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _fake_profile():
    return {
        "id": _PROFILE_ID,
        "brand_name": "测试品牌",
        "is_active": True,
    }


def _fake_calendar_entry():
    return {"id": str(uuid.uuid4()), "event_name": "春节", "event_date": "2026-02-01"}


def _fake_constraint():
    return {"id": str(uuid.uuid4()), "constraint_type": "forbidden_word", "constraint_value": "最便宜"}


# ---------------------------------------------------------------------------
# GET /api/v1/brand/profile
# ---------------------------------------------------------------------------


def test_get_active_profile_found(monkeypatch):
    monkeypatch.setattr(_svc, "get_active_profile", AsyncMock(return_value=_fake_profile()))
    resp = client.get("/api/v1/brand/profile", headers=_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["brand_name"] == "测试品牌"


def test_get_active_profile_not_found(monkeypatch):
    monkeypatch.setattr(_svc, "get_active_profile", AsyncMock(return_value=None))
    resp = client.get("/api/v1/brand/profile", headers=_HEADERS)
    assert resp.status_code == 404


def test_get_active_profile_missing_header():
    resp = client.get("/api/v1/brand/profile")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/v1/brand/profile
# ---------------------------------------------------------------------------


def test_create_profile_success(monkeypatch):
    monkeypatch.setattr(_svc, "create_profile", AsyncMock(return_value=_fake_profile()))
    body = {"brand_name": "测试品牌", "price_tier": "mid"}
    resp = client.post("/api/v1/brand/profile", json=body, headers=_HEADERS)
    assert resp.status_code == 201
    assert resp.json()["ok"] is True


def test_create_profile_value_error(monkeypatch):
    monkeypatch.setattr(_svc, "create_profile", AsyncMock(side_effect=ValueError("已存在激活档案")))
    body = {"brand_name": "测试品牌"}
    resp = client.post("/api/v1/brand/profile", json=body, headers=_HEADERS)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# PUT /api/v1/brand/profile/{id}
# ---------------------------------------------------------------------------


def test_update_profile_success(monkeypatch):
    monkeypatch.setattr(_svc, "update_profile", AsyncMock(return_value=_fake_profile()))
    body = {"brand_name": "新品牌名"}
    resp = client.put(f"/api/v1/brand/profile/{_PROFILE_ID}", json=body, headers=_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_update_profile_not_found(monkeypatch):
    monkeypatch.setattr(_svc, "update_profile", AsyncMock(return_value=None))
    body = {"brand_name": "新品牌名"}
    resp = client.put(f"/api/v1/brand/profile/{_PROFILE_ID}", json=body, headers=_HEADERS)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/brand/calendar
# ---------------------------------------------------------------------------


def test_list_calendar_with_items(monkeypatch):
    monkeypatch.setattr(_svc, "list_calendar", AsyncMock(return_value=[_fake_calendar_entry()]))
    resp = client.get("/api/v1/brand/calendar", headers=_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 1


def test_list_calendar_empty(monkeypatch):
    monkeypatch.setattr(_svc, "list_calendar", AsyncMock(return_value=[]))
    resp = client.get("/api/v1/brand/calendar", headers=_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 0


# ---------------------------------------------------------------------------
# POST /api/v1/brand/calendar
# ---------------------------------------------------------------------------


def test_add_calendar_entry_success(monkeypatch):
    monkeypatch.setattr(_svc, "create_calendar_entry", AsyncMock(return_value=_fake_calendar_entry()))
    body = {"event_name": "春节", "event_date": "2026-02-01"}
    resp = client.post("/api/v1/brand/calendar", json=body, headers=_HEADERS)
    assert resp.status_code == 201
    assert resp.json()["ok"] is True


def test_add_calendar_entry_value_error(monkeypatch):
    monkeypatch.setattr(_svc, "create_calendar_entry", AsyncMock(side_effect=ValueError("日期冲突")))
    body = {"event_name": "春节", "event_date": "2026-02-01"}
    resp = client.post("/api/v1/brand/calendar", json=body, headers=_HEADERS)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/brand/constraints
# ---------------------------------------------------------------------------


def test_list_constraints_with_items(monkeypatch):
    monkeypatch.setattr(_svc, "list_constraints", AsyncMock(return_value=[_fake_constraint()]))
    resp = client.get("/api/v1/brand/constraints", headers=_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 1


def test_list_constraints_empty(monkeypatch):
    monkeypatch.setattr(_svc, "list_constraints", AsyncMock(return_value=[]))
    resp = client.get("/api/v1/brand/constraints", headers=_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 0


# ---------------------------------------------------------------------------
# POST /api/v1/brand/constraints
# ---------------------------------------------------------------------------


def test_add_constraint_success(monkeypatch):
    monkeypatch.setattr(_svc, "create_constraint", AsyncMock(return_value=_fake_constraint()))
    body = {"constraint_type": "forbidden_word", "constraint_value": "最便宜"}
    resp = client.post("/api/v1/brand/constraints", json=body, headers=_HEADERS)
    assert resp.status_code == 201
    assert resp.json()["ok"] is True


def test_add_constraint_value_error(monkeypatch):
    monkeypatch.setattr(_svc, "create_constraint", AsyncMock(side_effect=ValueError("约束类型无效")))
    body = {"constraint_type": "forbidden_word", "constraint_value": "最便宜"}
    resp = client.post("/api/v1/brand/constraints", json=body, headers=_HEADERS)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/brand/content-brief
# ---------------------------------------------------------------------------


def test_get_content_brief_success(monkeypatch):
    fake_brief = MagicMock()
    fake_brief.model_dump = MagicMock(return_value={"system_prompt": "你是品牌营销专家"})
    monkeypatch.setattr(_svc, "build_content_brief", AsyncMock(return_value=fake_brief))
    resp = client.get(
        "/api/v1/brand/content-brief",
        params={"channel": "wechat", "segment": "高价值常客", "purpose": "复购召回"},
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "system_prompt" in body["data"]


def test_get_content_brief_missing_params():
    # channel/segment/purpose 均为必填 Query 参数
    resp = client.get("/api/v1/brand/content-brief", headers=_HEADERS)
    assert resp.status_code == 422
