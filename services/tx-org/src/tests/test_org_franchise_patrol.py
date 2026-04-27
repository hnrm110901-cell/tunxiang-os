"""franchise_settlement_routes + patrol_routes 测试

覆盖端点：
  franchise_settlement_routes.py (6 端点):
    [1]  POST /api/v1/franchise/settlements/generate     — 正常生成结算单
    [2]  POST /api/v1/franchise/settlements/generate     — 缺少 X-Tenant-ID → 400
    [3]  POST /api/v1/franchise/settlements/generate     — LookupError → 404
    [4]  POST /api/v1/franchise/settlements/{id}/send    — 正常发送
    [5]  POST /api/v1/franchise/settlements/{id}/send    — InvalidStatusTransitionError → 409
    [6]  PUT  /api/v1/franchise/settlements/{id}/confirm — 正常确认
    [7]  PUT  /api/v1/franchise/settlements/{id}/pay     — 正常付款
    [8]  GET  /api/v1/franchise/settlements/overdue      — 正常逾期列表
    [9]  GET  /api/v1/franchise/{id}/statement           — franchisee_id 非 UUID → 400
    [10] GET  /api/v1/franchise/{id}/statement           — 正常对账单

  patrol_routes.py (8 端点):
    [11] POST /patrol/templates              — 正常创建模板
    [12] GET  /patrol/templates              — 正常列表
    [13] POST /patrol/records               — 正常开始巡检
    [14] PUT  /patrol/records/{id}/submit   — 正常提交
    [15] GET  /patrol/rankings              — 正常排名
    [16] GET  /patrol/issues                — 正常整改列表
    [17] POST /patrol/issues                — 正常创建整改任务
    [18] PUT  /patrol/issues/{id}           — 正常更新整改状态
    [19] POST /patrol/templates             — ValueError → 400
    [20] GET  /patrol/templates             — 缺少 X-Tenant-ID → 400
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

# ──────────────────────────────────────────────────────────────────────────────
# 路径注入
# ──────────────────────────────────────────────────────────────────────────────
_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_ROOT = os.path.abspath(os.path.join(_SRC, "..", "..", "..", ".."))
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
# shared.ontology.src.database 存根
# ──────────────────────────────────────────────────────────────────────────────
for _name in ("shared", "shared.ontology", "shared.ontology.src"):
    sys.modules.setdefault(_name, types.ModuleType(_name))

_db_mod = types.ModuleType("shared.ontology.src.database")


async def _stub_get_db():
    yield MagicMock()


_db_mod.get_db = _stub_get_db
_db_mod.async_session_factory = MagicMock()
sys.modules["shared.ontology.src.database"] = _db_mod

# ──────────────────────────────────────────────────────────────────────────────
# 注册 src 包层次，以支持路由文件中的相对导入（from ..services.xxx import）
# ──────────────────────────────────────────────────────────────────────────────
_src_pkg = types.ModuleType("src")
_src_pkg.__path__ = [_SRC]
_src_pkg.__package__ = "src"
sys.modules.setdefault("src", _src_pkg)

_api_pkg = types.ModuleType("src.api")
_api_pkg.__path__ = [os.path.join(_SRC, "api")]
_api_pkg.__package__ = "src.api"
sys.modules.setdefault("src.api", _api_pkg)

_svc_pkg = types.ModuleType("src.services")
_svc_pkg.__path__ = [os.path.join(_SRC, "services")]
_svc_pkg.__package__ = "src.services"
sys.modules.setdefault("src.services", _svc_pkg)

_models_pkg = types.ModuleType("src.models")
_models_pkg.__path__ = [os.path.join(_SRC, "models")]
sys.modules.setdefault("src.models", _models_pkg)


# ──────────────────────────────────────────────────────────────────────────────
# 服务存根异常类
# ──────────────────────────────────────────────────────────────────────────────
class _SettlementNotFoundError(Exception):
    pass


class _InvalidStatusTransitionError(Exception):
    pass


# ──────────────────────────────────────────────────────────────────────────────
# franchise_settlement_service 存根
# ──────────────────────────────────────────────────────────────────────────────
class _FakeSettlement:
    def __init__(self, **kwargs):
        self._data = kwargs

    def model_dump(self, mode="json"):
        return self._data


class _FakeStatement:
    def __init__(self, **kwargs):
        self._data = kwargs

    def model_dump(self, mode="json"):
        return self._data


class _FakeSettlementService:
    async def generate_monthly_settlement(self, **kwargs):
        return _FakeSettlement(id="s-001", status="draft", franchisee_id=kwargs.get("franchisee_id"))

    async def send_settlement_to_franchisee(self, **kwargs):
        pass

    async def confirm_settlement(self, **kwargs):
        pass

    async def mark_as_paid(self, **kwargs):
        pass

    async def get_overdue_settlements(self, **kwargs):
        return []

    async def get_franchisee_statement(self, **kwargs):
        return _FakeStatement(franchisee_id=kwargs.get("franchisee_id"), months=[])


_fss_stub = types.ModuleType("src.services.franchise_settlement_service")
_fss_stub.FranchiseSettlement = _FakeSettlement
_fss_stub.FranchiseeStatement = _FakeStatement
_fss_stub.FranchiseSettlementService = _FakeSettlementService
_fss_stub.SettlementNotFoundError = _SettlementNotFoundError
_fss_stub.InvalidStatusTransitionError = _InvalidStatusTransitionError
sys.modules["src.services.franchise_settlement_service"] = _fss_stub

# ──────────────────────────────────────────────────────────────────────────────
# franchise_settlement_routes 依赖的其他存根
# ──────────────────────────────────────────────────────────────────────────────
_franchise_model_stub = types.ModuleType("src.models.franchise")
_franchise_model_stub.Franchisee = MagicMock()
_franchise_model_stub.RoyaltyTier = MagicMock()
sys.modules["src.models.franchise"] = _franchise_model_stub

_royalty_calc_stub = types.ModuleType("src.services.royalty_calculator")
_royalty_calc_stub.RoyaltyCalculator = MagicMock()
sys.modules["src.services.royalty_calculator"] = _royalty_calc_stub

# httpx — 确保使用真实版本（路由 service 依赖它）
import httpx as _real_httpx  # noqa: E402

sys.modules["httpx"] = _real_httpx


# ──────────────────────────────────────────────────────────────────────────────
# patrol_service 存根
# ──────────────────────────────────────────────────────────────────────────────
class _FakePatrolService:
    @staticmethod
    async def create_template(**kwargs):
        return {"template_id": "tmpl-001", "name": kwargs.get("name")}

    @staticmethod
    async def list_templates(**kwargs):
        return {"items": [], "total": 0}

    @staticmethod
    async def start_patrol(**kwargs):
        return {"record_id": "rec-001", "status": "in_progress"}

    @staticmethod
    async def submit_patrol(**kwargs):
        return {"record_id": kwargs.get("record_id"), "status": "submitted", "total_score": 90.0}

    @staticmethod
    async def get_store_patrol_ranking(**kwargs):
        return [{"store_id": "s1", "avg_score": 95.0}]

    @staticmethod
    async def list_issues(**kwargs):
        return {"items": [], "total": 0}

    @staticmethod
    async def create_issue(**kwargs):
        return {"issue_id": "iss-001", "status": "open"}

    @staticmethod
    async def update_issue_status(**kwargs):
        return {"issue_id": kwargs.get("issue_id"), "status": kwargs.get("new_status")}


_patrol_svc_stub = types.ModuleType("src.services.patrol_service")
_patrol_svc_stub.PatrolService = _FakePatrolService
sys.modules["src.services.patrol_service"] = _patrol_svc_stub


# ──────────────────────────────────────────────────────────────────────────────
# 用 importlib 加载路由模块（设置正确的 __package__ 使相对导入生效）
# ──────────────────────────────────────────────────────────────────────────────
def _load_route_module(filename: str, module_name: str) -> types.ModuleType:
    """从文件加载路由模块，并正确设置包信息以支持 from ..xxx import 相对导入。"""
    filepath = os.path.join(_SRC, "api", filename)
    spec = importlib.util.spec_from_file_location(
        module_name,
        filepath,
        submodule_search_locations=[],
    )
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "src.api"
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


_settlement_mod = _load_route_module(
    "franchise_settlement_routes.py",
    "src.api.franchise_settlement_routes",
)
_patrol_mod = _load_route_module(
    "patrol_routes.py",
    "src.api.patrol_routes",
)

# ──────────────────────────────────────────────────────────────────────────────
# 构建 FastAPI 测试应用
# ──────────────────────────────────────────────────────────────────────────────
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from shared.ontology.src.database import get_db

settlement_router = _settlement_mod.router
patrol_router = _patrol_mod.router
_settlement_service_instance = _settlement_mod._service

app_settlement = FastAPI()
app_settlement.include_router(settlement_router)

app_patrol = FastAPI()
app_patrol.include_router(patrol_router)

TENANT_ID = str(uuid4())
FRANCHISEE_ID = str(uuid4())
SETTLEMENT_ID = str(uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}


def _override_db(mock_session):
    async def _inner():
        yield mock_session

    return _inner


# ══════════════════════════════════════════════════════════════════════════════
# Part 1 — franchise_settlement_routes.py
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.anyio
async def test_generate_settlement_ok():
    """[1] POST /settlements/generate — 正常生成结算单 → ok=True, status=draft。"""
    mock_db = AsyncMock()
    app_settlement.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_settlement), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/franchise/settlements/generate",
                headers=HEADERS,
                json={"franchisee_id": FRANCHISEE_ID, "year": 2026, "month": 3},
            )
    finally:
        app_settlement.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "draft"


@pytest.mark.anyio
async def test_generate_settlement_missing_tenant():
    """[2] POST /settlements/generate — 缺少 X-Tenant-ID → 400。"""
    async with AsyncClient(transport=ASGITransport(app=app_settlement), base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/franchise/settlements/generate",
            json={"franchisee_id": FRANCHISEE_ID, "year": 2026, "month": 3},
        )

    assert resp.status_code == 400
    assert "X-Tenant-ID" in resp.json()["detail"]


@pytest.mark.anyio
async def test_generate_settlement_lookup_error():
    """[3] POST /settlements/generate — service LookupError → 404。"""
    with patch.object(
        _settlement_service_instance,
        "generate_monthly_settlement",
        new=AsyncMock(side_effect=LookupError("加盟商不存在")),
    ):
        async with AsyncClient(transport=ASGITransport(app=app_settlement), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/franchise/settlements/generate",
                headers=HEADERS,
                json={"franchisee_id": FRANCHISEE_ID, "year": 2026, "month": 3},
            )

    assert resp.status_code == 404
    assert "加盟商不存在" in resp.json()["detail"]


@pytest.mark.anyio
async def test_send_settlement_ok():
    """[4] POST /settlements/{id}/send — 正常发送 → ok=True, status=sent。"""
    with patch.object(
        _settlement_service_instance,
        "send_settlement_to_franchisee",
        new=AsyncMock(return_value=None),
    ):
        async with AsyncClient(transport=ASGITransport(app=app_settlement), base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/v1/franchise/settlements/{SETTLEMENT_ID}/send",
                headers=HEADERS,
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "sent"


@pytest.mark.anyio
async def test_send_settlement_invalid_status_transition():
    """[5] POST /settlements/{id}/send — InvalidStatusTransitionError → 409。"""
    with patch.object(
        _settlement_service_instance,
        "send_settlement_to_franchisee",
        new=AsyncMock(side_effect=_InvalidStatusTransitionError("只有 draft 才能发送")),
    ):
        async with AsyncClient(transport=ASGITransport(app=app_settlement), base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/v1/franchise/settlements/{SETTLEMENT_ID}/send",
                headers=HEADERS,
            )

    assert resp.status_code == 409
    assert "draft" in resp.json()["detail"]


@pytest.mark.anyio
async def test_confirm_settlement_ok():
    """[6] PUT /settlements/{id}/confirm — 正常确认 → ok=True, status=confirmed。"""
    with patch.object(
        _settlement_service_instance,
        "confirm_settlement",
        new=AsyncMock(return_value=None),
    ):
        async with AsyncClient(transport=ASGITransport(app=app_settlement), base_url="http://test") as ac:
            resp = await ac.put(
                f"/api/v1/franchise/settlements/{SETTLEMENT_ID}/confirm",
                headers=HEADERS,
                params={"franchisee_id": FRANCHISEE_ID},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "confirmed"


@pytest.mark.anyio
async def test_mark_as_paid_ok():
    """[7] PUT /settlements/{id}/pay — 正常标记付款 → ok=True, status=paid。"""
    with patch.object(
        _settlement_service_instance,
        "mark_as_paid",
        new=AsyncMock(return_value=None),
    ):
        async with AsyncClient(transport=ASGITransport(app=app_settlement), base_url="http://test") as ac:
            resp = await ac.put(
                f"/api/v1/franchise/settlements/{SETTLEMENT_ID}/pay",
                headers=HEADERS,
                json={"payment_ref": "BANK-TXN-20260401-001"},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "paid"


@pytest.mark.anyio
async def test_get_overdue_settlements_ok():
    """[8] GET /settlements/overdue — 正常逾期列表（含自定义 overdue_days）。"""
    fake_settlement = _FakeSettlement(id="s-overdue", status="confirmed", franchisee_id=FRANCHISEE_ID)
    with patch.object(
        _settlement_service_instance,
        "get_overdue_settlements",
        new=AsyncMock(return_value=[fake_settlement]),
    ):
        async with AsyncClient(transport=ASGITransport(app=app_settlement), base_url="http://test") as ac:
            resp = await ac.get(
                "/api/v1/franchise/settlements/overdue",
                headers=HEADERS,
                params={"overdue_days": 30},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["overdue_days"] == 30
    assert body["data"]["count"] == 1


@pytest.mark.anyio
async def test_get_franchisee_statement_invalid_uuid():
    """[9] GET /{franchisee_id}/statement — franchisee_id 非 UUID → 400。"""
    async with AsyncClient(transport=ASGITransport(app=app_settlement), base_url="http://test") as ac:
        resp = await ac.get(
            "/api/v1/franchise/not-a-uuid/statement",
            headers=HEADERS,
        )

    assert resp.status_code == 400
    assert "franchisee_id" in resp.json()["detail"]


@pytest.mark.anyio
async def test_get_franchisee_statement_ok():
    """[10] GET /{franchisee_id}/statement — 正常对账单返回。"""
    fake_stmt = _FakeStatement(franchisee_id=FRANCHISEE_ID, months=[], total_outstanding=0)
    with patch.object(
        _settlement_service_instance,
        "get_franchisee_statement",
        new=AsyncMock(return_value=fake_stmt),
    ):
        async with AsyncClient(transport=ASGITransport(app=app_settlement), base_url="http://test") as ac:
            resp = await ac.get(
                f"/api/v1/franchise/{FRANCHISEE_ID}/statement",
                headers=HEADERS,
                params={"months": 6},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["franchisee_id"] == FRANCHISEE_ID


# ══════════════════════════════════════════════════════════════════════════════
# Part 2 — patrol_routes.py（PatrolService + get_db 依赖）
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.anyio
async def test_patrol_create_template_ok():
    """[11] POST /patrol/templates — 正常创建模板。"""
    mock_db = AsyncMock()
    app_patrol.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        with patch.object(
            _FakePatrolService,
            "create_template",
            new=AsyncMock(return_value={"template_id": "tmpl-001", "name": "食品安全检查"}),
        ):
            async with AsyncClient(transport=ASGITransport(app=app_patrol), base_url="http://test") as ac:
                resp = await ac.post(
                    "/patrol/templates",
                    headers=HEADERS,
                    json={
                        "name": "食品安全检查",
                        "category": "safety",
                        "items": [{"item_name": "灶台清洁", "item_type": "score", "max_score": 10.0}],
                    },
                )
    finally:
        app_patrol.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["template_id"] == "tmpl-001"


@pytest.mark.anyio
async def test_patrol_list_templates_ok():
    """[12] GET /patrol/templates — 正常模板列表。"""
    mock_db = AsyncMock()
    app_patrol.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        with patch.object(
            _FakePatrolService,
            "list_templates",
            new=AsyncMock(return_value={"items": [{"template_id": "t1"}], "total": 1}),
        ):
            async with AsyncClient(transport=ASGITransport(app=app_patrol), base_url="http://test") as ac:
                resp = await ac.get(
                    "/patrol/templates",
                    headers=HEADERS,
                    params={"category": "hygiene", "page": 1, "size": 10},
                )
    finally:
        app_patrol.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 1


@pytest.mark.anyio
async def test_patrol_start_patrol_ok():
    """[13] POST /patrol/records — 正常开始巡检。"""
    mock_db = AsyncMock()
    app_patrol.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        with patch.object(
            _FakePatrolService,
            "start_patrol",
            new=AsyncMock(return_value={"record_id": "rec-999", "status": "in_progress"}),
        ):
            async with AsyncClient(transport=ASGITransport(app=app_patrol), base_url="http://test") as ac:
                resp = await ac.post(
                    "/patrol/records",
                    headers=HEADERS,
                    json={
                        "store_id": str(uuid4()),
                        "template_id": str(uuid4()),
                        "patroller_id": str(uuid4()),
                    },
                )
    finally:
        app_patrol.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["record_id"] == "rec-999"


@pytest.mark.anyio
async def test_patrol_submit_patrol_ok():
    """[14] PUT /patrol/records/{id}/submit — 正常提交巡检结果。"""
    record_id = str(uuid4())
    mock_db = AsyncMock()
    app_patrol.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        with patch.object(
            _FakePatrolService,
            "submit_patrol",
            new=AsyncMock(return_value={"record_id": record_id, "status": "submitted", "total_score": 88.5}),
        ):
            async with AsyncClient(transport=ASGITransport(app=app_patrol), base_url="http://test") as ac:
                resp = await ac.put(
                    f"/patrol/records/{record_id}/submit",
                    headers=HEADERS,
                    json={
                        "items": [
                            {
                                "template_item_id": str(uuid4()),
                                "actual_score": 8.5,
                                "photo_urls": [],
                                "notes": "良好",
                            }
                        ]
                    },
                )
    finally:
        app_patrol.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "submitted"
    assert body["data"]["total_score"] == 88.5


@pytest.mark.anyio
async def test_patrol_get_rankings_ok():
    """[15] GET /patrol/rankings — 正常门店排名列表。"""
    mock_db = AsyncMock()
    app_patrol.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        with patch.object(
            _FakePatrolService,
            "get_store_patrol_ranking",
            new=AsyncMock(
                return_value=[
                    {"store_id": "store-A", "avg_score": 98.0},
                    {"store_id": "store-B", "avg_score": 85.0},
                ]
            ),
        ):
            async with AsyncClient(transport=ASGITransport(app=app_patrol), base_url="http://test") as ac:
                resp = await ac.get(
                    "/patrol/rankings",
                    headers=HEADERS,
                    params={"days": 7},
                )
    finally:
        app_patrol.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 2
    assert len(body["data"]["items"]) == 2


@pytest.mark.anyio
async def test_patrol_list_issues_ok():
    """[16] GET /patrol/issues — 正常整改任务列表（含过滤条件）。"""
    mock_db = AsyncMock()
    app_patrol.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        with patch.object(
            _FakePatrolService,
            "list_issues",
            new=AsyncMock(return_value={"items": [{"issue_id": "iss-1"}], "total": 1}),
        ):
            async with AsyncClient(transport=ASGITransport(app=app_patrol), base_url="http://test") as ac:
                resp = await ac.get(
                    "/patrol/issues",
                    headers=HEADERS,
                    params={"status": "open", "severity": "critical"},
                )
    finally:
        app_patrol.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 1


@pytest.mark.anyio
async def test_patrol_create_issue_ok():
    """[17] POST /patrol/issues — 正常手动创建整改任务。"""
    mock_db = AsyncMock()
    app_patrol.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        with patch.object(
            _FakePatrolService,
            "create_issue",
            new=AsyncMock(return_value={"issue_id": "iss-new", "status": "open"}),
        ):
            async with AsyncClient(transport=ASGITransport(app=app_patrol), base_url="http://test") as ac:
                resp = await ac.post(
                    "/patrol/issues",
                    headers=HEADERS,
                    json={
                        "store_id": str(uuid4()),
                        "item_name": "灶台油污",
                        "severity": "major",
                        "description": "灶台积油严重",
                    },
                )
    finally:
        app_patrol.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["issue_id"] == "iss-new"


@pytest.mark.anyio
async def test_patrol_update_issue_ok():
    """[18] PUT /patrol/issues/{id} — 正常更新整改任务状态。"""
    issue_id = str(uuid4())
    mock_db = AsyncMock()
    app_patrol.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        with patch.object(
            _FakePatrolService,
            "update_issue_status",
            new=AsyncMock(return_value={"issue_id": issue_id, "status": "resolved"}),
        ):
            async with AsyncClient(transport=ASGITransport(app=app_patrol), base_url="http://test") as ac:
                resp = await ac.put(
                    f"/patrol/issues/{issue_id}",
                    headers=HEADERS,
                    json={"status": "resolved", "resolution_notes": "已清洁灶台"},
                )
    finally:
        app_patrol.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "resolved"


@pytest.mark.anyio
async def test_patrol_create_template_value_error():
    """[19] POST /patrol/templates — service ValueError → 400。"""
    mock_db = AsyncMock()
    app_patrol.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        with patch.object(
            _FakePatrolService,
            "create_template",
            new=AsyncMock(side_effect=ValueError("category 非法")),
        ):
            async with AsyncClient(transport=ASGITransport(app=app_patrol), base_url="http://test") as ac:
                resp = await ac.post(
                    "/patrol/templates",
                    headers=HEADERS,
                    json={"name": "测试", "category": "invalid_cat", "items": []},
                )
    finally:
        app_patrol.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 400
    assert "category" in resp.json()["detail"]


@pytest.mark.anyio
async def test_patrol_list_templates_missing_tenant():
    """[20] GET /patrol/templates — 缺少 X-Tenant-ID → 400。"""
    mock_db = AsyncMock()
    app_patrol.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_patrol), base_url="http://test") as ac:
            resp = await ac.get("/patrol/templates")  # 故意不带 header
    finally:
        app_patrol.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 400
    assert "X-Tenant-ID" in resp.json()["detail"]
