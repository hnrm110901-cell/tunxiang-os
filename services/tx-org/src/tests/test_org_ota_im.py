"""ota_routes + im_sync_routes 测试

覆盖端点：
  ota_routes.py (5 端点):
    [1]  POST  /api/v1/org/ota/versions                   — 正常发布新版本
    [2]  POST  /api/v1/org/ota/versions                   — 无效 target_type → 400
    [3]  POST  /api/v1/org/ota/versions                   — IntegrityError → 409
    [4]  POST  /api/v1/org/ota/versions                   — 缺少 X-Tenant-ID → 401
    [5]  GET   /api/v1/org/ota/versions                   — 正常版本列表
    [6]  GET   /api/v1/org/ota/versions/latest            — 有更新版本时返回 has_update=True
    [7]  GET   /api/v1/org/ota/versions/latest            — 已是最新版本时返回 has_update=False
    [8]  PATCH /api/v1/org/ota/versions/{id}/deactivate   — 正常撤回版本
    [9]  PATCH /api/v1/org/ota/versions/{id}/deactivate   — version_id 非 UUID → 400
    [10] GET   /api/v1/org/ota/stats                      — 正常升级进度统计

  im_sync_routes.py (4 端点，全为 Mock 实现，无 DB 依赖):
    [11] GET  /api/v1/org/im-sync/status        — 获取 IM 绑定状态概览
    [12] POST /api/v1/org/im-sync/preview       — IM 同步预览差异
    [13] POST /api/v1/org/im-sync/apply         — 应用 IM 同步结果
    [14] POST /api/v1/org/im-sync/send-message  — 向用户发送 IM 消息
    [15] POST /api/v1/org/im-sync/send-message  — user_ids 为空列表时发送数量为 0
"""

from __future__ import annotations

import os
import sys
import types
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

# ──────────────────────────────────────────────────────────────────────────────
# 路径注入
# ──────────────────────────────────────────────────────────────────────────────
_SRC = os.path.join(os.path.dirname(__file__), "..")
_ROOT = os.path.join(_SRC, "..", "..", "..", "..")
sys.path.insert(0, _SRC)
sys.path.insert(0, _ROOT)

# ──────────────────────────────────────────────────────────────────────────────
# structlog 存根
# ──────────────────────────────────────────────────────────────────────────────
if "structlog" not in sys.modules:
    _slog = types.ModuleType("structlog")
    _slog.get_logger = lambda *a, **k: MagicMock()
    _slog.stdlib = types.SimpleNamespace(BoundLogger=object)
    sys.modules["structlog"] = _slog

# ──────────────────────────────────────────────────────────────────────────────
# sqlalchemy 存根（ota_routes 直接引用）
# ──────────────────────────────────────────────────────────────────────────────
if "sqlalchemy" not in sys.modules:
    _sa = types.ModuleType("sqlalchemy")

    def _text(sql):
        return sql

    _sa.text = _text
    _sa_exc = types.ModuleType("sqlalchemy.exc")

    class _IntegrityError(Exception):
        pass

    class _SQLAlchemyError(Exception):
        pass

    _sa_exc.IntegrityError = _IntegrityError
    _sa_exc.SQLAlchemyError = _SQLAlchemyError
    _sa_ext = types.ModuleType("sqlalchemy.ext")
    _sa_ext_async = types.ModuleType("sqlalchemy.ext.asyncio")
    _sa_ext_async.AsyncSession = object
    sys.modules["sqlalchemy"] = _sa
    sys.modules["sqlalchemy.exc"] = _sa_exc
    sys.modules["sqlalchemy.ext"] = _sa_ext
    sys.modules["sqlalchemy.ext.asyncio"] = _sa_ext_async
else:
    from sqlalchemy.exc import IntegrityError as _IntegrityError
    from sqlalchemy.exc import SQLAlchemyError as _SQLAlchemyError

# ──────────────────────────────────────────────────────────────────────────────
# shared.ontology.src.database 存根
# ──────────────────────────────────────────────────────────────────────────────
_shared_pkg = types.ModuleType("shared")
_onto_pkg = types.ModuleType("shared.ontology")
_onto_src_pkg = types.ModuleType("shared.ontology.src")
_db_mod = types.ModuleType("shared.ontology.src.database")


async def _stub_get_db():
    yield MagicMock()


_db_mod.get_db = _stub_get_db
_db_mod.async_session_factory = MagicMock()
sys.modules.setdefault("shared", _shared_pkg)
sys.modules.setdefault("shared.ontology", _onto_pkg)
sys.modules.setdefault("shared.ontology.src", _onto_src_pkg)
sys.modules["shared.ontology.src.database"] = _db_mod

# ──────────────────────────────────────────────────────────────────────────────
# 导入被测路由
# ──────────────────────────────────────────────────────────────────────────────
import pytest
from api.im_sync_routes import router as im_router
from api.ota_routes import router as ota_router
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from shared.ontology.src.database import get_db

# ──────────────────────────────────────────────────────────────────────────────
# FastAPI 应用
# ──────────────────────────────────────────────────────────────────────────────
app_ota = FastAPI()
app_ota.include_router(ota_router)

app_im = FastAPI()
app_im.include_router(im_router)

TENANT_ID = str(uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}


def _override_db(mock_session):
    async def _inner():
        yield mock_session

    return _inner


def _make_mappings(*rows: dict):
    """构造模拟 db.execute() 返回的 result，支持 .mappings().first() 和 .mappings() 迭代。"""
    result = MagicMock()
    mapping_list = list(rows)

    mappings_obj = MagicMock()
    mappings_obj.first.return_value = mapping_list[0] if mapping_list else None
    mappings_obj.__iter__ = MagicMock(return_value=iter(mapping_list))
    result.mappings.return_value = mappings_obj
    result.rowcount = len(mapping_list)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# Part 1 — ota_routes.py
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.anyio
async def test_ota_create_version_ok():
    """[1] POST /versions — 正常发布新版本 → ok=True，返回 version_id。"""
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock())
    mock_db.commit = AsyncMock()
    app_ota.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_ota), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/org/ota/versions",
                headers=HEADERS,
                json={
                    "target_type": "android_pos",
                    "version_name": "3.2.0",
                    "version_code": 32000,
                    "download_url": "https://cdn.example.com/app-3.2.0.apk",
                    "is_forced": False,
                    "rollout_pct": 100,
                },
            )
    finally:
        app_ota.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "version_id" in body["data"]
    assert body["data"]["version_name"] == "3.2.0"


@pytest.mark.anyio
async def test_ota_create_version_invalid_target_type():
    """[2] POST /versions — target_type 非法 → 400。"""
    mock_db = AsyncMock()
    app_ota.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_ota), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/org/ota/versions",
                headers=HEADERS,
                json={
                    "target_type": "windows_pc",  # 非法类型
                    "version_name": "1.0.0",
                    "version_code": 10000,
                    "download_url": "https://cdn.example.com/app.exe",
                },
            )
    finally:
        app_ota.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 400


@pytest.mark.anyio
async def test_ota_create_version_integrity_error():
    """[3] POST /versions — 版本号重复（IntegrityError）→ 409。"""
    from sqlalchemy.exc import IntegrityError

    mock_db = AsyncMock()
    # IntegrityError 需要 orig 参数
    mock_db.execute = AsyncMock(side_effect=IntegrityError("duplicate", {}, Exception("unique")))
    mock_db.rollback = AsyncMock()
    app_ota.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_ota), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/org/ota/versions",
                headers=HEADERS,
                json={
                    "target_type": "mac_mini",
                    "version_name": "2.0.0",
                    "version_code": 20000,
                    "download_url": "https://cdn.example.com/mac-app.dmg",
                },
            )
    finally:
        app_ota.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 409


@pytest.mark.anyio
async def test_ota_create_version_missing_tenant():
    """[4] POST /versions — 缺少 X-Tenant-ID → 401。"""
    mock_db = AsyncMock()
    app_ota.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_ota), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/org/ota/versions",
                json={
                    "target_type": "android_pos",
                    "version_name": "1.0.0",
                    "version_code": 10000,
                    "download_url": "https://cdn.example.com/app.apk",
                },
            )
    finally:
        app_ota.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 401


@pytest.mark.anyio
async def test_ota_list_versions_ok():
    """[5] GET /versions — 正常版本列表（含分页）。"""
    now_str = datetime.utcnow().isoformat()
    version_row = {
        "id": uuid4(),
        "target_type": "android_pos",
        "version_name": "3.1.0",
        "version_code": 31000,
        "min_version_code": 0,
        "is_forced": False,
        "is_active": True,
        "rollout_pct": 100,
        "release_notes": "修复若干问题",
        "created_at": MagicMock(isoformat=lambda: now_str),
    }

    mock_db = AsyncMock()

    items_result = _make_mappings(version_row)
    mock_db.execute = AsyncMock(return_value=items_result)

    app_ota.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_ota), base_url="http://test") as ac:
            resp = await ac.get(
                "/api/v1/org/ota/versions",
                headers=HEADERS,
                params={"target_type": "android_pos", "active_only": True, "page": 1, "size": 10},
            )
    finally:
        app_ota.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "items" in body["data"]
    assert body["data"]["page"] == 1


@pytest.mark.anyio
async def test_ota_get_latest_version_has_update():
    """[6] GET /versions/latest — 服务器有更新版本 → has_update=True。"""
    latest_row = {
        "id": uuid4(),
        "version_name": "3.2.0",
        "version_code": 32000,
        "min_version_code": 30000,
        "download_url": "https://cdn.example.com/app-3.2.0.apk",
        "file_sha256": "abc123",
        "file_size_bytes": 5242880,
        "release_notes": "新功能",
        "is_forced": False,
        "rollout_pct": 100,
    }

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=_make_mappings(latest_row))

    app_ota.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_ota), base_url="http://test") as ac:
            resp = await ac.get(
                "/api/v1/org/ota/versions/latest",
                headers=HEADERS,
                params={"device_type": "android_pos", "current_version_code": 31000},
            )
    finally:
        app_ota.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["has_update"] is True
    assert body["data"]["version_name"] == "3.2.0"


@pytest.mark.anyio
async def test_ota_get_latest_version_no_update():
    """[7] GET /versions/latest — 设备已是最新 → has_update=False。"""
    mock_db = AsyncMock()
    # 返回空结果（没有更高版本）
    mock_db.execute = AsyncMock(return_value=_make_mappings())

    app_ota.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_ota), base_url="http://test") as ac:
            resp = await ac.get(
                "/api/v1/org/ota/versions/latest",
                headers=HEADERS,
                params={"device_type": "android_pos", "current_version_code": 99999},
            )
    finally:
        app_ota.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["has_update"] is False


@pytest.mark.anyio
async def test_ota_deactivate_version_ok():
    """[8] PATCH /versions/{id}/deactivate — 正常撤回版本。"""
    version_id = str(uuid4())
    mock_db = AsyncMock()

    deactivate_result = MagicMock()
    deactivate_result.rowcount = 1
    mock_db.execute = AsyncMock(return_value=deactivate_result)
    mock_db.commit = AsyncMock()

    app_ota.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_ota), base_url="http://test") as ac:
            resp = await ac.patch(
                f"/api/v1/org/ota/versions/{version_id}/deactivate",
                headers=HEADERS,
            )
    finally:
        app_ota.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["is_active"] is False
    assert body["data"]["version_id"] == version_id


@pytest.mark.anyio
async def test_ota_deactivate_version_invalid_uuid():
    """[9] PATCH /versions/{id}/deactivate — version_id 非 UUID → 400。"""
    mock_db = AsyncMock()
    app_ota.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_ota), base_url="http://test") as ac:
            resp = await ac.patch(
                "/api/v1/org/ota/versions/not-a-uuid/deactivate",
                headers=HEADERS,
            )
    finally:
        app_ota.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 400


@pytest.mark.anyio
async def test_ota_stats_ok():
    """[10] GET /stats — 正常升级进度统计（空设备池）。"""
    mock_db = AsyncMock()

    latest_result = _make_mappings()  # 无最新版本
    device_result = _make_mappings()  # 无设备

    mock_db.execute = AsyncMock(side_effect=[latest_result, device_result])

    app_ota.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_ota), base_url="http://test") as ac:
            resp = await ac.get(
                "/api/v1/org/ota/stats",
                headers=HEADERS,
            )
    finally:
        app_ota.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "stats" in body["data"]
    assert isinstance(body["data"]["stats"], list)


# ══════════════════════════════════════════════════════════════════════════════
# Part 2 — im_sync_routes.py（全为 Mock 实现，无 DB 依赖）
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.anyio
async def test_im_sync_status():
    """[11] GET /status — IM 绑定状态概览，返回固定 Mock 数据。"""
    async with AsyncClient(transport=ASGITransport(app=app_im), base_url="http://test") as ac:
        resp = await ac.get("/api/v1/org/im-sync/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert "total_employees" in data
    assert "wecom_bound" in data
    assert "dingtalk_bound" in data
    assert "unbound" in data
    # 固定 Mock 值校验
    assert data["total_employees"] == 45
    assert data["wecom_bound"] == 30


@pytest.mark.anyio
async def test_im_sync_preview():
    """[12] POST /preview — IM 同步差异预览，返回 to_bind / to_create / to_deactivate。"""
    async with AsyncClient(transport=ASGITransport(app=app_im), base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/org/im-sync/preview",
            json={
                "provider": "wecom",
                "corp_id": "ww-corp-001",
                "corp_secret": "secret-abc",
                "agent_id": "1000001",
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert isinstance(data["to_bind"], list)
    assert isinstance(data["to_create"], list)
    assert isinstance(data["to_deactivate"], list)
    assert "unchanged" in data
    # 固定 Mock 值
    assert len(data["to_bind"]) == 3
    assert len(data["to_create"]) == 2
    assert len(data["to_deactivate"]) == 1


@pytest.mark.anyio
async def test_im_sync_apply():
    """[13] POST /apply — 应用 IM 同步结果，返回执行统计。"""
    async with AsyncClient(transport=ASGITransport(app=app_im), base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/org/im-sync/apply",
            json={
                "provider": "wecom",
                "auto_create": False,
                "diff_id": "diff-" + str(uuid4()),
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert "bound" in data
    assert "created" in data
    assert "deactivated" in data
    assert "errors" in data
    assert isinstance(data["errors"], list)
    assert data["bound"] == 3


@pytest.mark.anyio
async def test_im_sync_send_message_ok():
    """[14] POST /send-message — 向多个用户发送 IM 消息，返回发送数量。"""
    user_ids = ["uid-001", "uid-002", "uid-003"]
    async with AsyncClient(transport=ASGITransport(app=app_im), base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/org/im-sync/send-message",
            json={
                "provider": "wecom",
                "user_ids": user_ids,
                "message": {"msgtype": "text", "text": {"content": "巡检提醒：请及时整改"}},
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["sent"] == len(user_ids)
    assert data["failed"] == 0


@pytest.mark.anyio
async def test_im_sync_send_message_empty_user_ids():
    """[15] POST /send-message — user_ids 为空列表 → sent=0, failed=0。"""
    async with AsyncClient(transport=ASGITransport(app=app_im), base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/org/im-sync/send-message",
            json={
                "provider": "dingtalk",
                "user_ids": [],
                "message": {"msgtype": "text", "text": {"content": "测试"}},
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["sent"] == 0
    assert body["data"]["failed"] == 0
