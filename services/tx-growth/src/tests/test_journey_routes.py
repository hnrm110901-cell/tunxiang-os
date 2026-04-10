"""旅程引擎 API 路由测试 — api/journey_routes.py

覆盖场景：
1.  GET  /api/v1/journey/definitions           — 正常路径返回 items/total
2.  GET  /api/v1/journey/definitions           — X-Tenant-ID 格式错误 → 400
3.  POST /api/v1/journey/definitions           — 正常创建，返回 id 和 is_active=False
4.  POST /api/v1/journey/definitions           — 缺少 name → 422
5.  POST /api/v1/journey/definitions           — steps 为空 → 422
6.  GET  /api/v1/journey/definitions/{id}      — 存在时返回完整详情
7.  GET  /api/v1/journey/definitions/{id}      — 不存在时返回 404
8.  DELETE /api/v1/journey/definitions/{id}    — 正常软删除，返回 deleted=True
9.  GET  /api/v1/journey/enrollments           — 正常路径返回 items/total
10. POST /api/v1/journey/definitions/import_template — 不存在的模板名 → 404
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

TENANT_ID = str(uuid.uuid4())
_HEADERS = {"X-Tenant-ID": TENANT_ID, "Authorization": "Bearer test"}
_BAD_TENANT = "not-a-uuid"
_BAD_HEADERS = {"X-Tenant-ID": _BAD_TENANT}

_JOURNEY_ID = str(uuid.uuid4())
_STEP = {
    "step_id": "s1",
    "action_type": "send_sms",
    "action_config": {"template": "welcome"},
    "wait_hours": 0,
    "next_steps": [],
}


# ── DB mock 工厂 ────────────────────────────────────────────────────────────

class _FakeRow:
    """模拟 SQLAlchemy fetchone/fetchall row"""
    def __init__(self, values: list):
        self._values = values

    def __getitem__(self, idx):
        return self._values[idx]


def _make_list_result(rows: list):
    """模拟 count + rows 两次 execute 的结果序列"""
    count_result = AsyncMock()
    count_result.scalar = MagicMock(return_value=len(rows))
    rows_result = AsyncMock()
    rows_result.fetchall = MagicMock(return_value=rows)
    return count_result, rows_result


def _make_db(*execute_side_effects):
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=list(execute_side_effects))
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


# ── 加载路由（patch async_session_factory + JourneyEngine） ─────────────────

_fake_engine = MagicMock()
_fake_engine.handle_event = AsyncMock(return_value={"enrollments_created": 0})

# patch templates 模块
import types as _types
_fake_templates_mod = _types.ModuleType("templates.journey_templates")
_fake_templates_mod.TEMPLATES = {
    "first_visit_welcome": {
        "name": "首次到访欢迎旅程",
        "description": "新客首次到店自动触发欢迎短信",
        "trigger_event": "first_visit",
        "trigger_conditions": [],
        "steps": [_STEP],
        "target_segment": "new_customer",
    }
}
sys.modules["templates"] = _types.ModuleType("templates")
sys.modules["templates.journey_templates"] = _fake_templates_mod

with patch("engine.journey_engine.JourneyEngine", return_value=_fake_engine):
    # engine 模块
    engine_mod = _types.ModuleType("engine")
    engine_mod.journey_engine = _types.ModuleType("engine.journey_engine")
    engine_mod.journey_engine.JourneyEngine = MagicMock(return_value=_fake_engine)
    sys.modules["engine"] = engine_mod
    sys.modules["engine.journey_engine"] = engine_mod.journey_engine

    from api.journey_routes import router

app = FastAPI()
app.include_router(router)
client = TestClient(app, raise_server_exceptions=False)

_NOW = datetime(2026, 4, 4, 10, 0, tzinfo=timezone.utc)


def _journey_row():
    return _FakeRow([
        uuid.UUID(_JOURNEY_ID),         # id
        "测试旅程",                      # name
        "旅程描述",                      # description
        "first_visit",                  # trigger_event
        [],                             # trigger_conditions
        [_STEP],                        # steps
        "new_customer",                 # target_segment
        False,                          # is_active
        1,                              # version
        _NOW,                           # created_at
        _NOW,                           # updated_at
    ])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 1: GET /definitions — 正常路径
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_list_journey_definitions_ok():
    """返回 items 列表和 total 字段"""
    set_local = AsyncMock()
    count_result, rows_result = _make_list_result([_journey_row()])

    with patch("api.journey_routes.async_session_factory") as mock_factory:
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock(side_effect=[set_local, count_result, rows_result])
        mock_factory.return_value = mock_db

        resp = client.get("/api/v1/journey/definitions", headers=_HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "items" in body["data"]
    assert "total" in body["data"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 2: GET /definitions — 非法 Tenant-ID → 400
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_list_definitions_bad_tenant():
    """X-Tenant-ID 非 UUID 格式时返回 400"""
    resp = client.get("/api/v1/journey/definitions", headers=_BAD_HEADERS)
    assert resp.status_code == 400


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 3: POST /definitions — 正常创建
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_create_journey_definition_ok():
    """正常创建旅程，返回 id 和 is_active=False"""
    with patch("api.journey_routes.async_session_factory") as mock_factory:
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock(return_value=AsyncMock())
        mock_db.commit = AsyncMock()
        mock_factory.return_value = mock_db

        resp = client.post(
            "/api/v1/journey/definitions",
            json={
                "name": "欢迎旅程",
                "trigger_event": "first_visit",
                "steps": [_STEP],
            },
            headers=_HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "id" in body["data"]
    assert body["data"]["is_active"] is False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 4: POST /definitions — 缺少 name → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_create_definition_missing_name():
    """name 为必填，缺少时应返回 422"""
    resp = client.post(
        "/api/v1/journey/definitions",
        json={"trigger_event": "first_visit", "steps": [_STEP]},
        headers=_HEADERS,
    )
    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 5: POST /definitions — steps 为空 → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_create_definition_empty_steps():
    """steps 为空时，业务层校验应返回 422"""
    with patch("api.journey_routes.async_session_factory"):
        resp = client.post(
            "/api/v1/journey/definitions",
            json={"name": "空步骤旅程", "trigger_event": "first_visit", "steps": []},
            headers=_HEADERS,
        )
    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 6: GET /definitions/{id} — 存在时返回详情
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_get_journey_definition_ok():
    """旅程存在时返回完整字段"""
    with patch("api.journey_routes.async_session_factory") as mock_factory:
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        row_result = AsyncMock()
        row_result.fetchone = MagicMock(return_value=_journey_row())
        mock_db.execute = AsyncMock(side_effect=[AsyncMock(), row_result])
        mock_factory.return_value = mock_db

        resp = client.get(
            f"/api/v1/journey/definitions/{_JOURNEY_ID}",
            headers=_HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["name"] == "测试旅程"
    assert data["trigger_event"] == "first_visit"
    assert data["is_active"] is False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 7: GET /definitions/{id} — 不存在时返回 404
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_get_journey_definition_not_found():
    """旅程不存在时返回 404"""
    with patch("api.journey_routes.async_session_factory") as mock_factory:
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        empty_result = AsyncMock()
        empty_result.fetchone = MagicMock(return_value=None)
        mock_db.execute = AsyncMock(side_effect=[AsyncMock(), empty_result])
        mock_factory.return_value = mock_db

        resp = client.get(
            f"/api/v1/journey/definitions/{uuid.uuid4()}",
            headers=_HEADERS,
        )

    assert resp.status_code == 404


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 8: DELETE /definitions/{id} — 软删除成功
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_delete_journey_definition_ok():
    """软删除成功，返回 deleted=True"""
    with patch("api.journey_routes.async_session_factory") as mock_factory:
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()

        del_result = AsyncMock()
        del_result.fetchone = MagicMock(return_value=_FakeRow([uuid.UUID(_JOURNEY_ID)]))
        mock_db.execute = AsyncMock(side_effect=[AsyncMock(), del_result])
        mock_factory.return_value = mock_db

        resp = client.delete(
            f"/api/v1/journey/definitions/{_JOURNEY_ID}",
            headers=_HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["deleted"] is True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 9: GET /enrollments — 正常路径
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_list_enrollments_ok():
    """返回 items/total 分页结构"""
    count_result = AsyncMock()
    count_result.scalar = MagicMock(return_value=0)
    rows_result = AsyncMock()
    rows_result.fetchall = MagicMock(return_value=[])

    with patch("api.journey_routes.async_session_factory") as mock_factory:
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock(side_effect=[AsyncMock(), count_result, rows_result])
        mock_factory.return_value = mock_db

        resp = client.get("/api/v1/journey/enrollments", headers=_HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert "items" in data
    assert data["total"] == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 10: POST /definitions/import_template — 模板不存在 → 404
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_import_template_not_found():
    """导入不存在的模板名称，应返回 404"""
    with patch("api.journey_routes.async_session_factory"):
        resp = client.post(
            "/api/v1/journey/definitions/import_template",
            json={"template_name": "nonexistent_template_xyz"},
            headers=_HEADERS,
        )
    assert resp.status_code == 404
