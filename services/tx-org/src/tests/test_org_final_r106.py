"""Round 106 — tx-org 最终扫尾测试
涵盖端点：
  - org_structure_routes.py  (8 endpoints: tree/create/get/update/delete/employees/move/statistics)
  - labor_margin_routes.py   (5 endpoints: realtime/hourly/monthly/comparison/loss-hours)
测试数量：≥ 8
"""

import sys
import types
import unittest.mock as _mock

# ── Mock structlog ────────────────────────────────────────────────────
_structlog = types.ModuleType("structlog")
_structlog.get_logger = lambda *a, **kw: _mock.MagicMock()
sys.modules.setdefault("structlog", _structlog)


# ── Mock shared.ontology.src.database ────────────────────────────────
async def _fake_get_db():
    yield None


_shared = types.ModuleType("shared")
_shared_onto = types.ModuleType("shared.ontology")
_shared_onto_src = types.ModuleType("shared.ontology.src")
_shared_onto_src_db = types.ModuleType("shared.ontology.src.database")
_shared_onto_src_db.get_db = _fake_get_db
sys.modules.setdefault("shared", _shared)
sys.modules.setdefault("shared.ontology", _shared_onto)
sys.modules.setdefault("shared.ontology.src", _shared_onto_src)
sys.modules.setdefault("shared.ontology.src.database", _shared_onto_src_db)

# ── Mock labor_margin_service ─────────────────────────────────────────
_src_pkg = types.ModuleType("src")
_src_svc_pkg = types.ModuleType("src.services")
_labor_svc_mod = types.ModuleType("src.services.labor_margin_service")


class _FakeLaborMarginService:
    async def get_realtime_margin(self, db, tenant_id, store_id, target_date):
        return {
            "store_id": store_id,
            "date": str(target_date),
            "revenue_fen": 100000,
            "labor_cost_fen": 25000,
            "net_margin_fen": 35000,
            "net_margin_rate": 0.35,
        }

    async def get_hourly_breakdown(self, db, tenant_id, store_id, target_date):
        return {
            "store_id": store_id,
            "date": str(target_date),
            "hours": [{"hour": h, "revenue_fen": 8000, "labor_cost_fen": 2000} for h in range(9, 22)],
        }

    async def get_monthly_trend(self, db, tenant_id, store_id, month):
        return {
            "store_id": store_id,
            "month": month,
            "days": [{"date": f"{month}-01", "net_margin_rate": 0.38}],
        }

    async def get_store_comparison(self, db, tenant_id, store_ids, month):
        return {
            "month": month,
            "stores": [{"store_id": sid, "net_margin_rate": 0.40} for sid in store_ids],
        }

    async def identify_loss_hours(self, db, tenant_id, store_id, target_date):
        return {
            "store_id": store_id,
            "date": str(target_date),
            "loss_hours": [],
        }


_labor_svc_mod.LaborMarginService = _FakeLaborMarginService
sys.modules.setdefault("src", _src_pkg)
sys.modules.setdefault("src.services", _src_svc_pkg)
sys.modules.setdefault("src.services.labor_margin_service", _labor_svc_mod)

import importlib.util
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ORG_SRC = pathlib.Path(__file__).parent.parent

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
STORE_ID = "store-001"
DEPT_ID = "dept-001"


def _load_module(rel_path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, str(ORG_SRC / rel_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ════════════════════════════════════════════════════════════════════
# PART A — org_structure_routes.py  (8 endpoints)
# ════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def org_struct_client():
    mod = _load_module("api/org_structure_routes.py", "org_structure_routes")
    app = FastAPI()
    app.include_router(mod.router)
    return TestClient(app, raise_server_exceptions=False)


def _make_mock_db(fetchone_return=None, fetchall_return=None, scalar_return=0):
    """Helper to create a mock AsyncSession"""
    mock_db = AsyncMock()

    async def _execute(sql, params=None):
        result = MagicMock()
        result.fetchone = MagicMock(return_value=fetchone_return)
        result.fetchall = MagicMock(return_value=fetchall_return or [])
        result.scalar = MagicMock(return_value=scalar_return)
        result._mapping = {}
        return result

    mock_db.execute = _execute
    mock_db.commit = AsyncMock()
    return mock_db


class TestOrgStructureRoutes:
    """org_structure_routes.py — 主要端点覆盖"""

    def test_get_org_tree_missing_tenant(self, org_struct_client):
        """缺少 X-Tenant-ID → 400"""
        r = org_struct_client.get("/api/v1/org-structure/tree")
        assert r.status_code == 400

    def test_get_org_tree_success(self, org_struct_client):
        """正常获取组织架构树"""
        mock_db = AsyncMock()

        async def _execute(sql, params=None):
            result = MagicMock()
            result.fetchall = MagicMock(return_value=[])
            return result

        mock_db.execute = _execute

        async def fake_get_db():
            yield mock_db

        with patch.object(sys.modules["shared.ontology.src.database"], "get_db", fake_get_db):
            r = org_struct_client.get(
                "/api/v1/org-structure/tree",
                headers={"X-Tenant-ID": TENANT_ID},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert "tree" in body["data"]
        assert body["data"]["total_departments"] == 0

    def test_create_department_missing_tenant(self, org_struct_client):
        """缺少 X-Tenant-ID → 400"""
        r = org_struct_client.post(
            "/api/v1/org-structure/departments",
            json={"name": "技术部"},
        )
        assert r.status_code == 400

    def test_create_department_no_parent(self, org_struct_client):
        """创建顶级部门（无上级）"""
        mock_db = AsyncMock()
        dept_row = MagicMock()
        dept_row._mapping = {"department_id": "new-dept-001"}

        async def _execute(sql, params=None):
            result = MagicMock()
            result.fetchone = MagicMock(return_value=dept_row)
            result._mapping = {"department_id": "new-dept-001"}
            return result

        mock_db.execute = _execute
        mock_db.commit = AsyncMock()

        async def fake_get_db():
            yield mock_db

        with patch.object(sys.modules["shared.ontology.src.database"], "get_db", fake_get_db):
            r = org_struct_client.post(
                "/api/v1/org-structure/departments",
                json={"name": "总部运营部", "dept_type": "department"},
                headers={"X-Tenant-ID": TENANT_ID},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["data"]["level"] == 1

    def test_get_department_detail_not_found(self, org_struct_client):
        """部门不存在 → 404"""
        mock_db = AsyncMock()

        async def _execute(sql, params=None):
            result = MagicMock()
            result.fetchone = MagicMock(return_value=None)
            return result

        mock_db.execute = _execute

        async def fake_get_db():
            yield mock_db

        with patch.object(sys.modules["shared.ontology.src.database"], "get_db", fake_get_db):
            r = org_struct_client.get(
                f"/api/v1/org-structure/departments/{DEPT_ID}",
                headers={"X-Tenant-ID": TENANT_ID},
            )
        assert r.status_code == 404

    def test_update_department_no_fields(self, org_struct_client):
        """没有传任何更新字段 → 400"""
        mock_db = AsyncMock()
        exist_row = MagicMock()
        exist_row._mapping = {"id": DEPT_ID}

        async def _execute(sql, params=None):
            result = MagicMock()
            result.fetchone = MagicMock(return_value=exist_row)
            return result

        mock_db.execute = _execute
        mock_db.commit = AsyncMock()

        async def fake_get_db():
            yield mock_db

        with patch.object(sys.modules["shared.ontology.src.database"], "get_db", fake_get_db):
            r = org_struct_client.put(
                f"/api/v1/org-structure/departments/{DEPT_ID}",
                json={},  # no fields
                headers={"X-Tenant-ID": TENANT_ID},
            )
        assert r.status_code == 400

    def test_get_org_statistics_success(self, org_struct_client):
        """统计接口正常返回汇总数据"""
        mock_db = AsyncMock()

        async def _execute(sql, params=None):
            result = MagicMock()
            result.fetchall = MagicMock(return_value=[])
            return result

        mock_db.execute = _execute

        async def fake_get_db():
            yield mock_db

        with patch.object(sys.modules["shared.ontology.src.database"], "get_db", fake_get_db):
            r = org_struct_client.get(
                "/api/v1/org-structure/statistics",
                headers={"X-Tenant-ID": TENANT_ID},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert "summary" in body["data"]
        assert body["data"]["summary"]["total_departments"] == 0


# ════════════════════════════════════════════════════════════════════
# PART B — labor_margin_routes.py  (5 endpoints)
# ════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def labor_margin_client():
    mod = _load_module("api/labor_margin_routes.py", "labor_margin_routes")
    app = FastAPI()
    app.include_router(mod.router)
    return TestClient(app, raise_server_exceptions=False)


class TestLaborMarginRoutes:
    """labor_margin_routes.py — 5 端点全覆盖"""

    def test_realtime_margin_missing_tenant(self, labor_margin_client):
        """缺少 X-Tenant-ID → 400"""
        r = labor_margin_client.get(
            "/api/v1/labor-margin/realtime",
            params={"store_id": STORE_ID},
        )
        assert r.status_code == 400

    def test_realtime_margin_success(self, labor_margin_client):
        """实时毛利正常返回"""
        mock_db = AsyncMock()

        async def fake_get_db():
            yield mock_db

        with patch.object(sys.modules["shared.ontology.src.database"], "get_db", fake_get_db):
            r = labor_margin_client.get(
                "/api/v1/labor-margin/realtime",
                params={"store_id": STORE_ID},
                headers={"X-Tenant-ID": TENANT_ID},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["data"]["store_id"] == STORE_ID
        assert "net_margin_rate" in body["data"]

    def test_hourly_breakdown_success(self, labor_margin_client):
        """按小时分解正常返回"""
        mock_db = AsyncMock()

        async def fake_get_db():
            yield mock_db

        with patch.object(sys.modules["shared.ontology.src.database"], "get_db", fake_get_db):
            r = labor_margin_client.get(
                "/api/v1/labor-margin/hourly",
                params={"store_id": STORE_ID},
                headers={"X-Tenant-ID": TENANT_ID},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert "hours" in body["data"]

    def test_monthly_trend_success(self, labor_margin_client):
        """月度趋势正常返回"""
        mock_db = AsyncMock()

        async def fake_get_db():
            yield mock_db

        with patch.object(sys.modules["shared.ontology.src.database"], "get_db", fake_get_db):
            r = labor_margin_client.get(
                "/api/v1/labor-margin/monthly",
                params={"store_id": STORE_ID, "month": "2026-04"},
                headers={"X-Tenant-ID": TENANT_ID},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["data"]["month"] == "2026-04"

    def test_store_comparison_success(self, labor_margin_client):
        """多店对比正常返回"""
        mock_db = AsyncMock()

        async def fake_get_db():
            yield mock_db

        with patch.object(sys.modules["shared.ontology.src.database"], "get_db", fake_get_db):
            r = labor_margin_client.get(
                "/api/v1/labor-margin/comparison",
                params={"store_ids": "store-001,store-002", "month": "2026-04"},
                headers={"X-Tenant-ID": TENANT_ID},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert "stores" in body["data"]
        assert len(body["data"]["stores"]) == 2

    def test_store_comparison_empty_store_ids(self, labor_margin_client):
        """store_ids 为空 → ok=False"""
        mock_db = AsyncMock()

        async def fake_get_db():
            yield mock_db

        with patch.object(sys.modules["shared.ontology.src.database"], "get_db", fake_get_db):
            r = labor_margin_client.get(
                "/api/v1/labor-margin/comparison",
                params={"store_ids": "   ", "month": "2026-04"},
                headers={"X-Tenant-ID": TENANT_ID},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert "store_ids" in body["error"]["message"]

    def test_loss_hours_success(self, labor_margin_client):
        """亏损时段识别正常返回"""
        mock_db = AsyncMock()

        async def fake_get_db():
            yield mock_db

        with patch.object(sys.modules["shared.ontology.src.database"], "get_db", fake_get_db):
            r = labor_margin_client.get(
                "/api/v1/labor-margin/loss-hours",
                params={"store_id": STORE_ID},
                headers={"X-Tenant-ID": TENANT_ID},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert "loss_hours" in body["data"]
