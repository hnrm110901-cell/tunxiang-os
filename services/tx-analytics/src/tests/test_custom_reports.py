"""自定义报表框架单元测试（DB版）

覆盖文件：api/report_config_routes.py

测试用例：
  1. test_get_reports_list           — 获取报表列表
  2. test_create_and_get_custom_report — 创建自定义报表，验证字段完整保存
  3. test_execute_report_returns_data  — 执行报表，验证status/rows/execution_ms
  4. test_share_token_generation      — 生成分享链接，验证token格式和URL
  5. test_narrative_template_preview  — 预览AI叙事，验证文本非空且含brand_focus关键词

技术说明：
  - 使用 TestClient（同步）直接测试 FastAPI router
  - DB 操作通过 _FakeSession 模拟
  - 叙事模板部分保留内存实现，直接测试
"""
from __future__ import annotations

import sys
import types
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ─── 最小化 stub 注入 ──────────────────────────────────────────────────────

def _inject_stubs() -> None:
    """注入 structlog + shared 存根"""
    if "structlog" not in sys.modules:
        stub = types.ModuleType("structlog")
        _logger_stub = types.SimpleNamespace(
            info=lambda *a, **kw: None,
            warning=lambda *a, **kw: None,
            error=lambda *a, **kw: None,
            debug=lambda *a, **kw: None,
        )
        stub.get_logger = lambda *a, **kw: _logger_stub  # type: ignore[attr-defined]
        sys.modules["structlog"] = stub

    for path in [
        "shared", "shared.ontology", "shared.ontology.src",
        "shared.events", "shared.events.src",
    ]:
        if path not in sys.modules:
            sys.modules[path] = types.ModuleType(path)

    if "shared.ontology.src.database" not in sys.modules:
        db_mod = types.ModuleType("shared.ontology.src.database")
        db_mod.get_db_with_tenant = AsyncMock()  # type: ignore[attr-defined]
        db_mod.get_db_no_rls = AsyncMock()  # type: ignore[attr-defined]
        sys.modules["shared.ontology.src.database"] = db_mod

    if "shared.events.src.emitter" not in sys.modules:
        em_mod = types.ModuleType("shared.events.src.emitter")
        em_mod.emit_event = AsyncMock()  # type: ignore[attr-defined]
        sys.modules["shared.events.src.emitter"] = em_mod


_inject_stubs()


# ── 伪造 DB Session ──
class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows
        self.rowcount = len(rows)

    def mappings(self) -> "_FakeResult":
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows

    def first(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def scalar_one(self) -> int:
        return len(self._rows)


class _FakeSession:
    def __init__(self) -> None:
        self._reports: dict[str, dict[str, Any]] = {}

    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> _FakeResult:
        sql_str = str(stmt.text) if hasattr(stmt, "text") else str(stmt)
        params = params or {}

        if "INSERT INTO report_configs" in sql_str:
            rid = params.get("id", "test-id")
            self._reports[rid] = {**params}
            return _FakeResult([{"rowcount": 1}])

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
                return _FakeResult([{
                    "id": rid,
                    "name": rpt.get("name", "Test"),
                    "description": rpt.get("description", ""),
                    "category": rpt.get("category", "operation"),
                    "sql_template": rpt.get("sql_template", "SELECT 1 AS val"),
                    "default_params": {},
                    "dimensions": [],
                    "metrics": [],
                    "filters": [],
                    "is_system": rpt.get("is_system", False),
                    "is_active": True,
                    "created_at": "2026-04-09T00:00:00Z",
                    "updated_at": "2026-04-09T00:00:00Z",
                }])
            return _FakeResult([])

        if "COUNT(*) FROM report_configs" in sql_str:
            active = [r for r in self._reports.values() if not r.get("is_deleted")]
            return _FakeResult([{}] * len(active))

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

        if "SELECT * FROM (" in sql_str:
            return _FakeResult([{"val": 1}])

        return _FakeResult([])


_fake_session = _FakeSession()


async def _override_get_db() -> AsyncGenerator[Any, None]:
    yield _fake_session


from ..api.report_config_routes import (  # noqa: E402
    router,
    _get_db,
    _custom_templates,
)

# ─── TestClient 构建 ────────────────────────────────────────────────────────

app = FastAPI()
app.include_router(router)
app.dependency_overrides[_get_db] = _override_get_db
client = TestClient(app)

HEADERS = {"X-Tenant-ID": "test-tenant"}


# ─── 测试辅助 ──────────────────────────────────────────────────────────────────

def _create_report(name: str = "测试报表", category: str = "operation") -> dict:
    """创建报表并返回data字典"""
    payload = {
        "name": name,
        "category": category,
        "sql_template": "SELECT 1 AS val",
        "dimensions": [{"name": "store_id", "label": "门店"}],
        "metrics": [{"name": "revenue_fen", "label": "营业额"}],
    }
    resp = client.post("/api/v1/analytics/reports", json=payload, headers=HEADERS)
    assert resp.status_code == 200, f"创建报表失败: {resp.text}"
    return resp.json()["data"]


# ─── 测试用例 ──────────────────────────────────────────────────────────────────

class TestGetReportsList:
    """TC-1: 获取报表列表"""

    def test_list_returns_ok(self) -> None:
        _create_report(name="列表测试报表")
        resp = client.get("/api/v1/analytics/reports", headers=HEADERS)
        assert resp.status_code == 200

        body = resp.json()
        assert body["ok"] is True
        assert "items" in body["data"]
        assert "total" in body["data"]


class TestCreateAndGetCustomReport:
    """TC-2: 创建自定义报表，验证字段完整保存"""

    def test_create_report_returns_ok(self) -> None:
        report = _create_report(name="字段完整性测试报表")
        assert report["name"] == "字段完整性测试报表"
        assert isinstance(report["id"], str) and len(report["id"]) > 0

    def test_get_report_by_id(self) -> None:
        created = _create_report(name="GET详情测试")
        report_id = created["id"]

        resp = client.get(f"/api/v1/analytics/reports/{report_id}", headers=HEADERS)
        assert resp.status_code == 200

        fetched = resp.json()["data"]
        assert fetched["id"] == report_id
        assert fetched["name"] == "GET详情测试"

    def test_get_nonexistent_report_returns_404(self) -> None:
        resp = client.get("/api/v1/analytics/reports/nonexistent-id-000", headers=HEADERS)
        assert resp.status_code == 404


class TestExecuteReportReturnsData:
    """TC-3: 执行报表，验证status/rows/execution_ms"""

    def test_execute_report(self) -> None:
        report = _create_report(name="执行测试")
        resp = client.post(
            f"/api/v1/analytics/reports/{report['id']}/execute",
            json={"params": {}, "row_limit": 5},
            headers=HEADERS,
        )
        assert resp.status_code == 200

        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert "execution" in data
        assert "rows" in data

    def test_execute_returns_completed_status(self) -> None:
        report = _create_report(name="执行状态测试")
        resp = client.post(
            f"/api/v1/analytics/reports/{report['id']}/execute",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        execution = resp.json()["data"]["execution"]
        assert execution["status"] == "completed"

    def test_execute_returns_execution_ms(self) -> None:
        report = _create_report(name="执行耗时测试")
        resp = client.post(
            f"/api/v1/analytics/reports/{report['id']}/execute",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        execution = resp.json()["data"]["execution"]
        assert "execution_ms" in execution
        assert execution["execution_ms"] >= 0


class TestShareTokenGeneration:
    """TC-4: 生成分享链接，验证token格式和URL"""

    def test_share_returns_token(self) -> None:
        report = _create_report(name="分享token测试")
        resp = client.post(
            f"/api/v1/analytics/reports/{report['id']}/share",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "share_token" in data
        assert "share_url" in data

    def test_share_token_is_64_char_hex(self) -> None:
        report = _create_report(name="token格式测试")
        resp = client.post(
            f"/api/v1/analytics/reports/{report['id']}/share",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        share_token = resp.json()["data"]["share_token"]
        assert len(share_token) == 64
        int(share_token, 16)  # 验证合法hex

    def test_share_url_contains_token(self) -> None:
        report = _create_report(name="URL包含token测试")
        resp = client.post(
            f"/api/v1/analytics/reports/{report['id']}/share",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["share_token"] in data["share_url"]


class TestNarrativeTemplatePreview:
    """TC-5: 预览AI叙事，验证文本非空且含brand_focus关键词"""

    def test_preview_builtin_template(self) -> None:
        resp = client.post("/api/v1/analytics/narrative-templates/tpl-001/preview")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_preview_returns_non_empty_narrative(self) -> None:
        resp = client.post("/api/v1/analytics/narrative-templates/tpl-001/preview")
        assert resp.status_code == 200

        data = resp.json()["data"]
        assert "narrative" in data
        narrative = data["narrative"]
        assert isinstance(narrative, str)
        assert len(narrative) > 20

    def test_preview_seafood_template_contains_brand_focus(self) -> None:
        resp = client.post("/api/v1/analytics/narrative-templates/tpl-002/preview")
        assert resp.status_code == 200

        data = resp.json()["data"]
        narrative = data["narrative"]
        brand_focus = data.get("brand_focus", "")

        keywords = [kw.strip() for kw in brand_focus.split("/") if kw.strip()]
        assert any(kw in narrative for kw in keywords), (
            f"叙事文本应包含品牌侧重关键词 {keywords} 之一\n实际叙事：{narrative}"
        )

    def test_preview_returns_template_metadata(self) -> None:
        resp = client.post("/api/v1/analytics/narrative-templates/tpl-003/preview")
        assert resp.status_code == 200

        data = resp.json()["data"]
        assert data["template_id"] == "tpl-003"
        assert "template_name" in data
        assert "tone" in data
        assert "generated_at" in data

    def test_preview_custom_template(self) -> None:
        create_resp = client.post(
            "/api/v1/analytics/narrative-templates",
            json={
                "name": "快餐翻台专报",
                "brand_focus": "翻台率/人效",
                "tone": "casual",
                "is_default": False,
            },
        )
        assert create_resp.status_code == 200
        template_id = create_resp.json()["data"]["id"]

        preview_resp = client.post(f"/api/v1/analytics/narrative-templates/{template_id}/preview")
        assert preview_resp.status_code == 200

        data = preview_resp.json()["data"]
        assert len(data["narrative"]) > 20

    def test_preview_nonexistent_template_returns_404(self) -> None:
        resp = client.post("/api/v1/analytics/narrative-templates/nonexistent-999/preview")
        assert resp.status_code == 404

    def test_list_narrative_templates(self) -> None:
        resp = client.get("/api/v1/analytics/narrative-templates")
        assert resp.status_code == 200

        data = resp.json()["data"]
        assert "items" in data
        items = data["items"]
        assert len(items) >= 3
