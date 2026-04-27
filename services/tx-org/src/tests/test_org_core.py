"""组织核心路由测试 — test_org_core.py

覆盖两个端点最多且无测试的路由文件：
  1. franchise_router.py     (13 端点) — FranchiseService 封装层
  2. franchise_mgmt_routes.py (15 端点) — 直接 SQL + get_db 依赖

测试矩阵（每文件 5 个，共 10 个）：
  franchise_router：
    [1] GET  /franchisees              — 正常列表查询
    [2] POST /franchisees              — 正常创建
    [3] GET  /franchisees/{id}         — 404 场景
    [4] POST /royalty/generate-batch   — service 抛 ValueError → 400
    [5] GET  /franchisees              — 缺少 X-Tenant-ID → 400

  franchise_mgmt_routes：
    [6]  GET  /franchisees              — 正常列表（含分页）
    [7]  POST /franchisees              — 重复编号 → 409
    [8]  GET  /franchisees/{id}         — 404 场景
    [9]  PATCH /franchisees/{id}/status — 非法状态转换 → 422
    [10] POST /franchisees              — DB 异常 → 500
"""

from __future__ import annotations

import os
import sys
import types

# ──────────────────────────────────────────────────────────────────────────────
# 路径注入（让裸模块名 `api.*` 和 `shared.*` 可以 import）
# ──────────────────────────────────────────────────────────────────────────────
_SRC = os.path.join(os.path.dirname(__file__), "..")
_ROOT = os.path.join(_SRC, "..", "..", "..", "..")
sys.path.insert(0, _SRC)
sys.path.insert(0, _ROOT)

# ──────────────────────────────────────────────────────────────────────────────
# 存根注入：franchise_router.py 依赖 ..services.franchise_service
# ──────────────────────────────────────────────────────────────────────────────
from unittest.mock import AsyncMock, MagicMock, patch

# 先构造 services 包存根，确保相对导入不报错
_services_pkg = types.ModuleType("services")
sys.modules.setdefault("services", _services_pkg)

_fs_stub = types.ModuleType("services.franchise_service")


class _FakeService:
    """FranchiseService 全静态方法存根，测试用例按需 patch 各方法。"""

    @staticmethod
    async def list_franchisees(**kwargs):
        return {"items": [], "total": 0}

    @staticmethod
    async def create_franchisee(**kwargs):
        obj = MagicMock()
        obj.to_dict.return_value = {"id": "abc", "franchisee_name": "测试加盟商"}
        return obj

    @staticmethod
    async def get_franchisee(*args, **kwargs):
        return None

    @staticmethod
    async def create_royalty_bill_batch(**kwargs):
        return {"created": 0}

    @staticmethod
    async def list_bills(**kwargs):
        return {"items": [], "total": 0}

    @staticmethod
    async def mark_bill_paid(**kwargs):
        obj = MagicMock()
        obj.to_dict.return_value = {"id": "bill-1", "status": "paid"}
        return obj

    @staticmethod
    async def get_royalty_report(**kwargs):
        obj = MagicMock()
        obj.to_dict.return_value = {"total": 0}
        return obj

    @staticmethod
    async def check_overdue_bills(**kwargs):
        return 0

    @staticmethod
    async def list_audits(**kwargs):
        return {"items": [], "total": 0}

    @staticmethod
    async def create_audit(**kwargs):
        return {"id": "audit-1"}

    @staticmethod
    async def list_franchisee_stores(**kwargs):
        return []

    @staticmethod
    async def get_franchisee_dashboard(**kwargs):
        return {"revenue": 0}

    @staticmethod
    async def update_franchisee(**kwargs):
        obj = MagicMock()
        obj.to_dict.return_value = {}
        return obj

    @staticmethod
    async def update_franchisee_status(**kwargs):
        obj = MagicMock()
        obj.to_dict.return_value = {}
        return obj


_fs_stub.FranchiseService = _FakeService
sys.modules["services.franchise_service"] = _fs_stub

# 同时注册包装好的相对路径形式（api 模块会用 from ..services.franchise_service 导入）
_api_svc_key = "api.services.franchise_service"
sys.modules.setdefault(_api_svc_key, _fs_stub)

# franchise_clone_service 存根（franchise_mgmt_routes 依赖）
_fcs_stub = types.ModuleType("services.franchise_clone_service")
_fcs_stub._update_clone_status = AsyncMock()
_fcs_stub.clone_store = AsyncMock(return_value={"status": "completed"})
sys.modules["services.franchise_clone_service"] = _fcs_stub

# shared.ontology.src.database 存根
_shared_pkg = types.ModuleType("shared")
_onto_pkg = types.ModuleType("shared.ontology")
_onto_src_pkg = types.ModuleType("shared.ontology.src")
_db_mod = types.ModuleType("shared.ontology.src.database")


async def _stub_get_db():
    """占位 get_db；真实值由 dependency_overrides 注入。"""
    yield MagicMock()


_db_mod.get_db = _stub_get_db
_db_mod.async_session_factory = MagicMock()
sys.modules.setdefault("shared", _shared_pkg)
sys.modules.setdefault("shared.ontology", _onto_pkg)
sys.modules.setdefault("shared.ontology.src", _onto_src_pkg)
sys.modules["shared.ontology.src.database"] = _db_mod

# structlog 存根（若环境未安装）
if "structlog" not in sys.modules:
    _slog = types.ModuleType("structlog")
    _slog.get_logger = lambda *a, **k: MagicMock()
    _slog.stdlib = types.SimpleNamespace(BoundLogger=object)
    sys.modules["structlog"] = _slog

# ──────────────────────────────────────────────────────────────────────────────
# 现在才 import 被测路由
# ──────────────────────────────────────────────────────────────────────────────
from uuid import uuid4

import pytest
from api.franchise_mgmt_routes import router as mgmt_router
from api.franchise_router import router as franchise_router
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from shared.ontology.src.database import get_db

# ──────────────────────────────────────────────────────────────────────────────
# 两个独立 FastAPI 应用（避免 prefix 冲突）
# ──────────────────────────────────────────────────────────────────────────────
app_router = FastAPI()
app_router.include_router(franchise_router)

app_mgmt = FastAPI()
app_mgmt.include_router(mgmt_router)

TENANT_ID = str(uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}


# ──────────────────────────────────────────────────────────────────────────────
# 辅助：构造 SQLAlchemy Row-like mock
# ──────────────────────────────────────────────────────────────────────────────


def _make_row(data: dict) -> MagicMock:
    row = MagicMock()
    row._mapping = data
    for k, v in data.items():
        setattr(row, k, v)
    return row


def _mock_db_session() -> AsyncMock:
    return AsyncMock()


def _override_db(mock_session: AsyncMock):
    """返回可用于 dependency_overrides 的异步生成器覆盖函数。"""

    async def _inner():
        yield mock_session

    return _inner


# ══════════════════════════════════════════════════════════════════════════════
# Part 1 — franchise_router.py（FranchiseService 封装层）
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.anyio
async def test_franchise_router_list_franchisees_ok():
    """[1] GET /api/v1/franchise/franchisees — 正常列表返回 ok=True。"""
    fake_result = {"items": [{"id": "f1", "franchisee_name": "加盟商A"}], "total": 1}

    with patch.object(_FakeService, "list_franchisees", new=AsyncMock(return_value=fake_result)):
        async with AsyncClient(transport=ASGITransport(app=app_router), base_url="http://test") as ac:
            resp = await ac.get(
                "/api/v1/franchise/franchisees",
                headers=HEADERS,
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 1


@pytest.mark.anyio
async def test_franchise_router_create_franchisee_ok():
    """[2] POST /api/v1/franchise/franchisees — 正常创建返回 201。"""
    fake_obj = MagicMock()
    fake_obj.to_dict.return_value = {"id": "new-f1", "franchisee_name": "新加盟商"}

    with patch.object(_FakeService, "create_franchisee", new=AsyncMock(return_value=fake_obj)):
        async with AsyncClient(transport=ASGITransport(app=app_router), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/franchise/franchisees",
                headers=HEADERS,
                json={
                    "franchisee_name": "新加盟商",
                    "royalty_rate": 0.05,
                },
            )

    assert resp.status_code == 201
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["id"] == "new-f1"


@pytest.mark.anyio
async def test_franchise_router_get_franchisee_not_found():
    """[3] GET /api/v1/franchise/franchisees/{id} — service 返回 None → 404。"""
    with patch.object(_FakeService, "get_franchisee", new=AsyncMock(return_value=None)):
        async with AsyncClient(transport=ASGITransport(app=app_router), base_url="http://test") as ac:
            fid = str(uuid4())
            resp = await ac.get(
                f"/api/v1/franchise/franchisees/{fid}",
                headers=HEADERS,
            )

    assert resp.status_code == 404
    assert "不存在" in resp.json()["detail"]


@pytest.mark.anyio
async def test_franchise_router_generate_batch_value_error():
    """[4] POST /api/v1/franchise/royalty/generate-batch — ValueError → 400。"""
    with patch.object(
        _FakeService,
        "create_royalty_bill_batch",
        new=AsyncMock(side_effect=ValueError("当月账单已生成")),
    ):
        async with AsyncClient(transport=ASGITransport(app=app_router), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/franchise/royalty/generate-batch",
                headers=HEADERS,
                json={"year": 2026, "month": 4},
            )

    assert resp.status_code == 400
    assert "当月账单已生成" in resp.json()["detail"]


@pytest.mark.anyio
async def test_franchise_router_missing_tenant_header():
    """[5] GET /api/v1/franchise/franchisees — 缺少 X-Tenant-ID → 400。"""
    async with AsyncClient(transport=ASGITransport(app=app_router), base_url="http://test") as ac:
        resp = await ac.get("/api/v1/franchise/franchisees")  # 故意不带 header

    assert resp.status_code == 400
    assert "X-Tenant-ID" in resp.json()["detail"]


# ══════════════════════════════════════════════════════════════════════════════
# Part 2 — franchise_mgmt_routes.py（直接 SQL + get_db 依赖）
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.anyio
async def test_mgmt_list_franchisees_ok():
    """[6] GET /api/v1/org/franchise/franchisees — 正常分页列表。"""
    mock_db = _mock_db_session()

    # total 查询返回 1，rows 查询返回一行
    total_result = MagicMock()
    total_result.scalar_one.return_value = 1

    row_data = {
        "id": "f-001",
        "franchisee_no": "F001",
        "legal_name": "测试加盟商有限公司",
        "status": "operating",
        "tier": "standard",
    }
    item_row = _make_row(row_data)
    rows_result = MagicMock()
    rows_result.__iter__ = MagicMock(return_value=iter([item_row]))

    mock_db.execute = AsyncMock(side_effect=[total_result, rows_result])

    app_mgmt.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_mgmt), base_url="http://test") as ac:
            resp = await ac.get(
                "/api/v1/org/franchise/franchisees",
                headers=HEADERS,
                params={"page": 1, "size": 10},
            )
    finally:
        app_mgmt.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 1
    assert len(body["data"]["items"]) == 1


@pytest.mark.anyio
async def test_mgmt_create_franchisee_duplicate_no():
    """[7] POST /api/v1/org/franchise/franchisees — 编号重复 → 409。"""
    mock_db = _mock_db_session()

    # set_config 调用
    set_cfg_result = MagicMock()
    # 重复检查返回已有记录
    dup_result = MagicMock()
    dup_row = _make_row({"id": "existing-f"})
    dup_result.first.return_value = dup_row

    mock_db.execute = AsyncMock(side_effect=[set_cfg_result, dup_result])

    app_mgmt.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_mgmt), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/org/franchise/franchisees",
                headers=HEADERS,
                json={
                    "franchisee_no": "F001",
                    "legal_name": "重复加盟商",
                    "tier": "standard",
                    "royalty_rate": "0.05",
                },
            )
    finally:
        app_mgmt.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 409
    assert "已存在" in resp.json()["detail"]


@pytest.mark.anyio
async def test_mgmt_get_franchisee_not_found():
    """[8] GET /api/v1/org/franchise/franchisees/{id} — 查不到 → 404。"""
    mock_db = _mock_db_session()

    set_cfg_result = MagicMock()
    not_found_result = MagicMock()
    not_found_result.first.return_value = None  # 未找到记录

    mock_db.execute = AsyncMock(side_effect=[set_cfg_result, not_found_result])

    app_mgmt.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_mgmt), base_url="http://test") as ac:
            resp = await ac.get(
                f"/api/v1/org/franchise/franchisees/{uuid4()}",
                headers=HEADERS,
            )
    finally:
        app_mgmt.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 404
    assert "不存在" in resp.json()["detail"]


@pytest.mark.anyio
async def test_mgmt_patch_status_invalid_transition():
    """[9] PATCH /api/v1/org/franchise/franchisees/{id}/status
    — 状态 terminated → operating 不允许 → 422。"""
    mock_db = _mock_db_session()

    set_cfg_result = MagicMock()
    # 返回当前 status=terminated 的记录
    status_row = _make_row({"id": "f-001", "status": "terminated"})
    found_result = MagicMock()
    found_result.first.return_value = status_row

    mock_db.execute = AsyncMock(side_effect=[set_cfg_result, found_result])

    app_mgmt.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_mgmt), base_url="http://test") as ac:
            resp = await ac.patch(
                "/api/v1/org/franchise/franchisees/f-001/status",
                headers=HEADERS,
                json={"status": "operating"},
            )
    finally:
        app_mgmt.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "terminated" in detail or "不允许" in detail


@pytest.mark.anyio
async def test_mgmt_create_franchisee_db_error():
    """[10] POST /api/v1/org/franchise/franchisees — DB 异常 → 500。"""
    mock_db = _mock_db_session()

    set_cfg_result = MagicMock()
    # 重复检查通过（无重复）
    dup_result = MagicMock()
    dup_result.first.return_value = None
    # INSERT 执行时抛 OSError 模拟 DB 连接断开
    mock_db.execute = AsyncMock(side_effect=[set_cfg_result, dup_result, OSError("DB connection lost")])

    app_mgmt.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_mgmt), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/org/franchise/franchisees",
                headers=HEADERS,
                json={
                    "franchisee_no": "F999",
                    "legal_name": "崩溃测试加盟商",
                    "tier": "standard",
                    "royalty_rate": "0.06",
                },
            )
    finally:
        app_mgmt.dependency_overrides.pop(get_db, None)

    # DB 层崩溃未被路由捕获 → FastAPI 返回 500
    assert resp.status_code == 500
