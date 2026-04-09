"""报表配置引擎测试

覆盖：
  1. test_report_catalog_returns_list   — GET /reports 返回报表列表
  2. test_report_execute                — POST /reports/{id}/execute 执行报表
  3. test_create_custom_report          — POST /reports 创建自定义报表
  4. test_narrative_templates           — GET /narrative-templates 返回叙事模板
"""
from __future__ import annotations

import sys
import types
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
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
_ensure_stub("shared.ontology.src.database", {
    "get_db": AsyncMock(),
    "get_db_with_tenant": AsyncMock(),
})
_ensure_stub("shared.events")
_ensure_stub("shared.events.src")
_ensure_stub("shared.events.src.emitter", {"emit_event": AsyncMock()})

if "structlog" not in sys.modules:
    _sl = types.ModuleType("structlog")
    _sl.get_logger = MagicMock(return_value=MagicMock())
    sys.modules["structlog"] = _sl

# ── 导入路由 ──
from ..api.report_config_routes import router  # noqa: E402

app = FastAPI()
app.include_router(router)

TENANT_ID = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}


class TestReportCatalog:
    """1. GET /reports 返回报表列表。"""

    def test_catalog_returns_list(self):
        with TestClient(app) as client:
            resp = client.get("/api/v1/analytics/reports", headers=HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "data" in body
        items = body["data"].get("items", body["data"])
        assert isinstance(items, list)
        assert len(items) > 0
        # 每个报表至少有 id 和 name
        for item in items:
            assert "id" in item
            assert "name" in item


class TestReportExecute:
    """2. POST /reports/{id}/execute 执行报表。"""

    def test_execute_standard_report(self):
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/analytics/reports/std-001/execute",
                json={"params": {}, "row_limit": 5},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert "rows" in data or "items" in data or "result" in data


class TestCreateCustomReport:
    """3. POST /reports 创建自定义报表。"""

    def test_create_report(self):
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/analytics/reports",
                json={
                    "name": "测试自定义报表",
                    "description": "测试用",
                    "data_source": "orders",
                    "chart_type": "bar",
                    "dimensions": [{"field": "store_id", "label": "门店", "type": "dimension"}],
                    "metrics": [{"field": "revenue_fen", "label": "营收", "agg": "sum"}],
                },
                headers=HEADERS,
            )

        assert resp.status_code in (200, 201)
        body = resp.json()
        assert body["ok"] is True
        assert "data" in body


class TestNarrativeTemplates:
    """4. GET /narrative-templates 返回叙事模板。"""

    def test_list_templates(self):
        with TestClient(app) as client:
            resp = client.get("/api/v1/analytics/narrative-templates", headers=HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        items = data.get("items", data) if isinstance(data, dict) else data
        assert isinstance(items, list)
