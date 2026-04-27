"""报表配置引擎测试（DB版）

覆盖：
  1. test_report_list_from_db        — GET /reports 从DB返回报表列表
  2. test_report_detail_from_db      — GET /reports/{id} 返回报表详情
  3. test_create_report_to_db        — POST /reports 创建报表写入DB
  4. test_execute_report_runs_sql    — POST /reports/{id}/execute 执行SQL模板
  5. test_narrative_templates        — GET /narrative-templates 返回叙事模板
  6. test_delete_blocks_system       — DELETE /reports/{id} 系统报表不可删
  7. test_p0_seed_data_count         — 种子数据包含20张报表
"""

from __future__ import annotations

import sys
import types
import uuid
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient


# ── 存根注入 ──
def _ensure_stub(path: str, attrs: dict | None = None) -> types.ModuleType:
    if path not in sys.modules:
        mod = types.ModuleType(path)
        if attrs:
            for k, v in attrs.items():
                setattr(mod, k, v)
        sys.modules[path] = mod
    return sys.modules[path]


_ensure_stub("shared")
_ensure_stub("shared.ontology")
_ensure_stub("shared.ontology.src")
_ensure_stub(
    "shared.ontology.src.database",
    {
        "get_db": AsyncMock(),
        "get_db_with_tenant": AsyncMock(),
        "get_db_no_rls": AsyncMock(),
    },
)
_ensure_stub("shared.events")
_ensure_stub("shared.events.src")
_ensure_stub("shared.events.src.emitter", {"emit_event": AsyncMock()})

if "structlog" not in sys.modules:
    _sl = types.ModuleType("structlog")
    _sl.get_logger = MagicMock(return_value=MagicMock())
    sys.modules["structlog"] = _sl


# ── 伪造 DB Session ──
class _FakeResult:
    """模拟 SQLAlchemy 查询结果"""

    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows

    def mappings(self) -> "_FakeResult":
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows

    def first(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def scalar_one(self) -> int:
        return len(self._rows)


class _FakeSession:
    """模拟 AsyncSession"""

    def __init__(self) -> None:
        self._reports: dict[str, dict[str, Any]] = {}

    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> _FakeResult:
        sql_str = str(stmt.text) if hasattr(stmt, "text") else str(stmt)
        params = params or {}

        if "INSERT INTO report_configs" in sql_str:
            rid = params.get("id", "test-id")
            self._reports[rid] = params
            return _FakeResult([{"rowcount": 1}])

        if "UPDATE report_configs SET is_deleted" in sql_str:
            rid = params.get("id")
            if rid in self._reports:
                self._reports[rid]["is_deleted"] = True
            return _FakeResult([])

        if "SELECT is_system FROM report_configs" in sql_str:
            rid = params.get("id")
            rpt = self._reports.get(rid)
            if rpt:
                return _FakeResult([{"is_system": rpt.get("is_system", False)}])
            return _FakeResult([])

        if "FROM report_configs WHERE id" in sql_str:
            rid = params.get("id")
            rpt = self._reports.get(rid)
            if rpt:
                return _FakeResult(
                    [
                        {
                            "id": rid,
                            "name": rpt.get("name", "Test"),
                            "description": rpt.get("description", ""),
                            "category": rpt.get("category", "operation"),
                            "sql_template": rpt.get("sql_template", "SELECT 1 AS val"),
                            "default_params": rpt.get("default_params", {}),
                            "dimensions": rpt.get("dimensions", []),
                            "metrics": rpt.get("metrics", []),
                            "filters": rpt.get("filters", []),
                            "is_system": rpt.get("is_system", False),
                            "is_active": True,
                            "created_at": "2026-04-09T00:00:00Z",
                            "updated_at": "2026-04-09T00:00:00Z",
                        }
                    ]
                )
            return _FakeResult([])

        if "COUNT(*) FROM report_configs" in sql_str:
            return _FakeResult([{}])

        if "FROM report_configs WHERE" in sql_str and "LIMIT" in sql_str:
            items = [
                {
                    "id": rid,
                    "name": rpt.get("name", "Test"),
                    "description": "",
                    "category": rpt.get("category", "operation"),
                    "dimensions": [],
                    "metrics": [],
                    "filters": [],
                    "is_system": rpt.get("is_system", False),
                    "is_active": True,
                    "created_at": "2026-04-09T00:00:00Z",
                    "updated_at": "2026-04-09T00:00:00Z",
                }
                for rid, rpt in self._reports.items()
                if not rpt.get("is_deleted")
            ]
            return _FakeResult(items)

        # execute 端点：子查询包装
        if "SELECT * FROM (" in sql_str:
            return _FakeResult([{"val": 1}])

        return _FakeResult([])


_fake_session = _FakeSession()


async def _override_get_db() -> AsyncGenerator[Any, None]:
    yield _fake_session


# ── 导入路由 ──
from ..api.report_config_routes import _get_db, router  # noqa: E402

app = FastAPI()
app.include_router(router)
app.dependency_overrides[_get_db] = _override_get_db

TENANT_ID = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}


class TestReportList:
    """1. GET /reports 从 DB 返回报表列表。"""

    def test_returns_list(self):
        # 先创建一条
        with TestClient(app) as client:
            client.post(
                "/api/v1/analytics/reports",
                json={"name": "Test Report", "category": "finance"},
                headers=HEADERS,
            )
            resp = client.get("/api/v1/analytics/reports", headers=HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "items" in body["data"]


class TestReportDetail:
    """2. GET /reports/{id} 返回报表详情。"""

    def test_get_existing(self):
        with TestClient(app) as client:
            create_resp = client.post(
                "/api/v1/analytics/reports",
                json={"name": "Detail Test", "category": "operation"},
                headers=HEADERS,
            )
            report_id = create_resp.json()["data"]["id"]

            resp = client.get(f"/api/v1/analytics/reports/{report_id}", headers=HEADERS)

        assert resp.status_code == 200
        assert resp.json()["data"]["name"] == "Detail Test"

    def test_get_nonexistent(self):
        with TestClient(app) as client:
            resp = client.get("/api/v1/analytics/reports/nonexistent", headers=HEADERS)
        assert resp.status_code == 404


class TestCreateReport:
    """3. POST /reports 创建报表写入DB。"""

    def test_create_report(self):
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/analytics/reports",
                json={
                    "name": "自定义报表",
                    "description": "test",
                    "category": "member",
                    "sql_template": "SELECT 1",
                    "dimensions": [{"name": "x", "label": "X"}],
                    "metrics": [{"name": "y", "label": "Y"}],
                },
                headers=HEADERS,
            )

        assert resp.status_code in (200, 201)
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["name"] == "自定义报表"


class TestExecuteReport:
    """4. POST /reports/{id}/execute 执行SQL模板。"""

    def test_execute_report(self):
        with TestClient(app) as client:
            create_resp = client.post(
                "/api/v1/analytics/reports",
                json={
                    "name": "Execute Test",
                    "category": "finance",
                    "sql_template": "SELECT 1 AS val",
                },
                headers=HEADERS,
            )
            report_id = create_resp.json()["data"]["id"]

            resp = client.post(
                f"/api/v1/analytics/reports/{report_id}/execute",
                json={"params": {}, "row_limit": 5},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "rows" in body["data"]


class TestNarrativeTemplates:
    """5. GET /narrative-templates 返回叙事模板。"""

    def test_list_templates(self):
        with TestClient(app) as client:
            resp = client.get("/api/v1/analytics/narrative-templates", headers=HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        items = body["data"]["items"]
        assert isinstance(items, list)
        assert len(items) >= 3


class TestDeleteSystemReport:
    """6. DELETE /reports/{id} 系统报表不可删除。"""

    def test_cannot_delete_system(self):
        with TestClient(app) as client:
            create_resp = client.post(
                "/api/v1/analytics/reports",
                json={"name": "System One", "category": "finance", "is_system": True},
                headers=HEADERS,
            )
            report_id = create_resp.json()["data"]["id"]

            resp = client.delete(f"/api/v1/analytics/reports/{report_id}", headers=HEADERS)

        assert resp.status_code == 400


class TestP0SeedCount:
    """7. 种子数据包含20张报表。"""

    def test_seed_count(self):
        from ..seed_p0_reports import P0_REPORTS

        assert len(P0_REPORTS) == 20

    def test_all_have_required_fields(self):
        from ..seed_p0_reports import P0_REPORTS

        required_keys = {
            "id",
            "name",
            "description",
            "category",
            "sql_template",
            "default_params",
            "dimensions",
            "metrics",
            "filters",
        }
        for rpt in P0_REPORTS:
            missing = required_keys - set(rpt.keys())
            assert not missing, f"报表 {rpt['id']} 缺少字段: {missing}"

    def test_categories_coverage(self):
        from ..seed_p0_reports import P0_REPORTS

        cats = {r["category"] for r in P0_REPORTS}
        assert cats == {"finance", "operation", "member", "hr"}

    def test_category_counts(self):
        from collections import Counter

        from ..seed_p0_reports import P0_REPORTS

        counts = Counter(r["category"] for r in P0_REPORTS)
        assert counts["finance"] == 7
        assert counts["operation"] == 6
        assert counts["member"] == 4
        assert counts["hr"] == 3

    def test_ids_unique(self):
        from ..seed_p0_reports import P0_REPORTS

        ids = [r["id"] for r in P0_REPORTS]
        assert len(ids) == len(set(ids))

    def test_all_ids_prefixed_p0(self):
        from ..seed_p0_reports import P0_REPORTS

        for rpt in P0_REPORTS:
            assert rpt["id"].startswith("p0_"), f"报表ID {rpt['id']} 缺少 p0_ 前缀"
