"""加盟路由裁决 — 端到端契约验证（2026-05-04 路由冲突清理）

本文件验证：4 处历史撞车的端点在裁决后均由唯一文件提供，
且响应字段与前端 FranchiseManagePage.tsx 期望的 v5 契约一致。

裁决结果：
  GET    /api/v1/franchise/franchisees                → franchise_v5_routes.py
  POST   /api/v1/franchise/franchisees                → franchise_v5_routes.py
  PUT    /api/v1/franchise/franchisees/{id}           → franchise_v5_routes.py
  GET    /api/v1/franchise/franchisees/{id}/dashboard → franchise_router.py (V2)

测试策略：
  1. 端点存在性 + 单一所有者：用 main.app 的 routes 表统计每条路径的 endpoint 数。
  2. v5 契约校验：mock get_db，验证 GET/POST/PUT 返回字段含 v5 字段名（name/region 等），
     而不是 v1 的 franchisee_name。
  3. dashboard 仍由 V2 router 提供 → 调用走 FranchiseService。

cURL 示例（部署后人工冒烟）：
  # 列表（v5 契约 — 返回项含 name/region/store_name）
  curl -H 'X-Tenant-ID: <uuid>' http://localhost:8012/api/v1/franchise/franchisees

  # 创建（v5 契约 — 提交 name 字段，不是 franchisee_name）
  curl -X POST -H 'X-Tenant-ID: <uuid>' -H 'Content-Type: application/json' \\
    -d '{"name":"加盟商A","contact_phone":"13800000000","region":"湖南省长沙市", \\
         "store_name":"望城店","store_address":"望城区雷锋大道","franchise_type":"standard"}' \\
    http://localhost:8012/api/v1/franchise/franchisees

  # 更新（v5 契约）
  curl -X PUT -H 'X-Tenant-ID: <uuid>' -H 'Content-Type: application/json' \\
    -d '{"status":"suspended","notes":"暂停审计中"}' \\
    http://localhost:8012/api/v1/franchise/franchisees/<id>

  # 仪表盘（V2 router）
  curl -H 'X-Tenant-ID: <uuid>' \\
    http://localhost:8012/api/v1/franchise/franchisees/<id>/dashboard
"""

from __future__ import annotations

import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

# ── 路径注入（与 test_franchise_v4 / test_org_core 一致）──────────────────────
_SRC = os.path.join(os.path.dirname(__file__), "..")
_ROOT = os.path.join(_SRC, "..", "..", "..", "..")
sys.path.insert(0, _SRC)
sys.path.insert(0, _ROOT)

# ── shared.ontology.src.database 存根 ─────────────────────────────────────────
if "shared" not in sys.modules:
    sys.modules["shared"] = types.ModuleType("shared")
if "shared.ontology" not in sys.modules:
    sys.modules["shared.ontology"] = types.ModuleType("shared.ontology")
if "shared.ontology.src" not in sys.modules:
    sys.modules["shared.ontology.src"] = types.ModuleType("shared.ontology.src")

if "shared.ontology.src.database" not in sys.modules:
    _db = types.ModuleType("shared.ontology.src.database")

    async def _stub_get_db():
        yield MagicMock()

    _db.get_db = _stub_get_db
    _db.async_session_factory = MagicMock()
    sys.modules["shared.ontology.src.database"] = _db

# structlog 兜底
if "structlog" not in sys.modules:
    _slog = types.ModuleType("structlog")
    _slog.get_logger = lambda *a, **k: MagicMock()
    _slog.stdlib = types.SimpleNamespace(BoundLogger=object)
    sys.modules["structlog"] = _slog

# FranchiseService 存根（让 V2 router 的 dashboard 端点不真连 DB）
# 路由文件用 `from ..services.franchise_service import FranchiseService` —
# 当被 import 为 services.tx_org.src.api.franchise_router 时，相对路径解析到
# services.tx_org.src.services.franchise_service。
if "services" not in sys.modules:
    sys.modules["services"] = types.ModuleType("services")
_fs_stub = types.ModuleType("franchise_service_stub")


class _StubFranchiseService:
    @staticmethod
    async def get_franchisee_dashboard(**_kw):
        return {
            "franchisee_id": "demo-id",
            "month_revenue_fen": 12345600,
            "month_royalty_fen": 617280,
            "outstanding_fen": 0,
        }


_fs_stub.FranchiseService = _StubFranchiseService
# 多路径兼容：覆盖 conftest 已注册的命名空间包，让真实模块文件不被加载。
for path in (
    "services.tx_org.src.services.franchise_service",
    "services.franchise_service",
):
    sys.modules[path] = _fs_stub

# RoyaltyCalculator 也兜底（franchise_routes.py 顶部 import 它）
_rc_stub = types.ModuleType("royalty_calculator_stub")


class _StubRoyaltyCalculator:
    @staticmethod
    async def generate_monthly_bills(**_kw):
        return []


_rc_stub.RoyaltyCalculator = _StubRoyaltyCalculator
for path in (
    "services.tx_org.src.services.royalty_calculator",
    "services.royalty_calculator",
):
    sys.modules[path] = _rc_stub

# ── 现在 import 三个真实路由 + main.app 的注册聚合 ────────────────────────────
from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

# 使用完整包路径导入，让 routes 内部的相对导入 (..services.*) 能解析；
# 这依赖 conftest.py 把 services.tx_org.src.* 的命名空间包注册好。
from services.tx_org.src.api.franchise_router import router as v2_router  # noqa: E402
from services.tx_org.src.api.franchise_routes import router as v1_router  # noqa: E402
from services.tx_org.src.api.franchise_v5_routes import router as v5_router  # noqa: E402
from shared.ontology.src.database import get_db  # noqa: E402

# 模拟 main.py 的注册顺序（v5 先于 v1/v2 — 防御性兜底）
app = FastAPI()
app.include_router(v5_router)
app.include_router(v2_router)
app.include_router(v1_router)


TENANT_ID = str(uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}


def _override_db(mock_session: AsyncMock):
    async def _inner():
        yield mock_session

    return _inner


def _make_row(data: dict) -> MagicMock:
    row = MagicMock()
    row._mapping = data
    for k, v in data.items():
        setattr(row, k, v)
    return row


# ══════════════════════════════════════════════════════════════════════════════
# Part A — 路由聚合：4 处冲突路径必须由单一文件提供
# ══════════════════════════════════════════════════════════════════════════════


def _routes_for(method: str, path: str) -> list:
    """返回 app 中匹配 (method, path) 的路由列表。"""
    matches = []
    for r in app.routes:
        if not hasattr(r, "methods") or not hasattr(r, "path"):
            continue
        if r.path == path and method in r.methods:
            matches.append(r)
    return matches


CONFLICT_PATHS = [
    ("GET", "/api/v1/franchise/franchisees"),
    ("POST", "/api/v1/franchise/franchisees"),
    ("PUT", "/api/v1/franchise/franchisees/{franchisee_id}"),
    ("GET", "/api/v1/franchise/franchisees/{franchisee_id}/dashboard"),
]


@pytest.mark.parametrize("method,path", CONFLICT_PATHS)
def test_each_conflict_path_has_exactly_one_owner(method, path):
    """4 个历史冲突端点：每条路径在 app 中只能注册一次。"""
    routes = _routes_for(method, path)
    assert len(routes) == 1, (
        f"{method} {path} expected exactly 1 owner, got {len(routes)}: "
        f"{[getattr(r.endpoint, '__module__', '?') for r in routes]}"
    )


def _module_basename(route) -> str:
    """提取 endpoint 的模块短名（兼容 api.X 与 services.tx_org.src.api.X 两种导入路径）。"""
    full = getattr(route.endpoint, "__module__", "?")
    return full.rsplit(".", 1)[-1]


def test_franchisees_crud_owner_is_v5():
    """GET/POST /franchisees + PUT /franchisees/{id} 必须由 franchise_v5_routes 提供。"""
    for method, path in [
        ("GET", "/api/v1/franchise/franchisees"),
        ("POST", "/api/v1/franchise/franchisees"),
        ("PUT", "/api/v1/franchise/franchisees/{franchisee_id}"),
    ]:
        routes = _routes_for(method, path)
        assert len(routes) == 1
        owner = _module_basename(routes[0])
        assert owner == "franchise_v5_routes", (
            f"{method} {path} should be owned by franchise_v5_routes, got {owner}"
        )


def test_dashboard_owner_is_v2_router():
    """GET /franchisees/{id}/dashboard 必须由 franchise_router (V2) 提供（v5 没有此端点）。"""
    routes = _routes_for("GET", "/api/v1/franchise/franchisees/{franchisee_id}/dashboard")
    assert len(routes) == 1
    owner = _module_basename(routes[0])
    assert owner == "franchise_router", (
        f"dashboard should be owned by franchise_router, got {owner}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# Part B — v5 契约端到端：返回字段必须是 v5 命名
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.anyio
async def test_get_franchisees_returns_v5_contract():
    """GET /franchisees → 列表项含 v5 字段 name/region/store_name（而非 v1 的 franchisee_name）。"""
    mock_db = AsyncMock()
    fake_row = _make_row(
        {
            "id": "f-001",
            "tenant_id": TENANT_ID,
            "name": "湖南张三连锁",  # ← v5 契约关键字段
            "company_name": "张三餐饮有限公司",
            "contact_phone": "13800138000",
            "region": "湖南省长沙市",  # ← v5 契约关键字段
            "store_name": "徐家湾店",  # ← v5 契约关键字段
            "store_address": "雨花区韶山南路123号",
            "franchise_type": "standard",
            "status": "active",
        }
    )
    list_result = MagicMock()
    list_result.fetchall.return_value = [fake_row]
    count_result = MagicMock()
    count_result.scalar.return_value = 1
    # _set_rls + count + list = 3 calls
    mock_db.execute = AsyncMock(side_effect=[MagicMock(), count_result, list_result])

    app.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/v1/franchise/franchisees", headers=HEADERS)
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    items = body["data"]["items"]
    assert len(items) == 1
    item = items[0]
    # v5 契约：必须有这些字段
    for key in ("name", "region", "store_name", "store_address", "franchise_type"):
        assert key in item, f"v5 contract field {key!r} missing in {item}"
    # v1 契约：不得有这些字段（裁决保证）
    assert "franchisee_name" not in item, "v1 contract leak: franchisee_name should not appear"


@pytest.mark.anyio
async def test_post_franchisee_accepts_v5_payload():
    """POST /franchisees 接受 v5 字段（name/region/store_name 等），返回包含同名字段。"""
    mock_db = AsyncMock()
    # _set_rls + INSERT
    mock_db.execute = AsyncMock(return_value=MagicMock())
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    payload_v5 = {
        "name": "新加盟商A",
        "company_name": "A 公司",
        "contact_phone": "13900139000",
        "region": "广东省深圳市",
        "store_name": "深南大道店",
        "store_address": "福田区深南大道999号",
        "franchise_type": "premium",
    }

    app.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/franchise/franchisees", headers=HEADERS, json=payload_v5
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    # v5 契约回显
    assert data["name"] == "新加盟商A"
    assert data["region"] == "广东省深圳市"
    assert data["store_name"] == "深南大道店"
    assert data["franchise_type"] == "premium"
    assert data["status"] == "active"


@pytest.mark.anyio
async def test_put_franchisee_uses_v5_field_names():
    """PUT /franchisees/{id} 接受 v5 字段名（status/contact_phone/notes…）。"""
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock())
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    fid = str(uuid4())
    update_v5 = {"status": "suspended", "notes": "暂停经营审计中"}

    app.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.put(
                f"/api/v1/franchise/franchisees/{fid}", headers=HEADERS, json=update_v5
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "suspended"
    assert body["data"]["notes"] == "暂停经营审计中"


@pytest.mark.anyio
async def test_dashboard_returns_v2_router_payload():
    """GET /franchisees/{id}/dashboard → 走 V2 router → FranchiseService（v5 无此端点）。"""
    fid = str(uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get(
            f"/api/v1/franchise/franchisees/{fid}/dashboard", headers=HEADERS
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    # V2 router 透传 service 返回，存根返回 month_revenue_fen 字段
    data = body["data"]
    assert "month_revenue_fen" in data
    assert data["month_revenue_fen"] == 12345600


# ══════════════════════════════════════════════════════════════════════════════
# Part C — 反向回归：被删除的 v1/v2 端点不应再可达（路径仍在但 owner 是 v5）
# ══════════════════════════════════════════════════════════════════════════════


def test_v1_routes_no_longer_owns_franchisees_crud():
    """franchise_routes (v1 PB.1) 不应再注册 GET/POST /franchisees。"""
    v1_paths = {(m, r.path) for r in v1_router.routes if hasattr(r, "methods") for m in r.methods}
    assert ("GET", "/api/v1/franchise/franchisees") not in v1_paths
    assert ("POST", "/api/v1/franchise/franchisees") not in v1_paths
    assert ("GET", "/api/v1/franchise/franchisees/{franchisee_id}/dashboard") not in v1_paths
    # 但保留独有端点
    assert ("POST", "/api/v1/franchise/franchisees/{franchisee_id}/assign-store") in v1_paths
    assert ("GET", "/api/v1/franchise/overdue-alerts") in v1_paths


def test_v2_router_no_longer_owns_franchisees_crud():
    """franchise_router (V2) 不应再注册 GET/POST /franchisees, PUT /franchisees/{id}。"""
    v2_paths = {(m, r.path) for r in v2_router.routes if hasattr(r, "methods") for m in r.methods}
    assert ("GET", "/api/v1/franchise/franchisees") not in v2_paths
    assert ("POST", "/api/v1/franchise/franchisees") not in v2_paths
    assert ("PUT", "/api/v1/franchise/franchisees/{franchisee_id}") not in v2_paths
    # 但保留独有端点
    assert ("GET", "/api/v1/franchise/franchisees/{franchisee_id}") in v2_paths
    assert ("GET", "/api/v1/franchise/franchisees/{franchisee_id}/dashboard") in v2_paths
    assert ("POST", "/api/v1/franchise/royalty/generate-batch") in v2_paths
    assert ("POST", "/api/v1/franchise/audits") in v2_paths
