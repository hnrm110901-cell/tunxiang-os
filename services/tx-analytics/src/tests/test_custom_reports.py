"""自定义报表框架单元测试

覆盖文件：api/report_config_routes.py

测试用例：
  1. test_get_reports_list        — 获取报表列表，验证含标准报表≥5条
  2. test_create_and_get_custom_report — 创建自定义报表，验证字段完整保存
  3. test_execute_report_returns_data  — 执行报表，验证status/rows/execution_ms
  4. test_share_token_generation  — 生成分享链接，验证token格式和URL
  5. test_narrative_template_preview — 预览AI叙事，验证文本非空且含brand_focus关键词

技术说明：
  - 使用 TestClient（同步）直接测试 FastAPI router
  - 路由使用内存dict存储，无需DB依赖
  - 每个测试独立：利用新创建资源确保隔离
"""
from __future__ import annotations

import sys
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ─── 最小化 stub 注入，避免重依赖导入报错 ──────────────────────────────────────

def _inject_stubs() -> None:
    """注入 structlog stub，避免在测试环境中找不到依赖"""
    if "structlog" not in sys.modules:
        stub = types.ModuleType("structlog")
        _logger_stub = types.SimpleNamespace(
            info=lambda *a, **kw: None,
            warning=lambda *a, **kw: None,
            error=lambda *a, **kw: None,
            debug=lambda *a, **kw: None,
        )
        stub.get_logger = lambda: _logger_stub  # type: ignore[attr-defined]
        sys.modules["structlog"] = stub


_inject_stubs()

from services.tx_analytics.src.api.report_config_routes import (  # noqa: E402
    router,
    _custom_reports,
    _custom_templates,
)

# ─── TestClient 构建 ────────────────────────────────────────────────────────────

app = FastAPI()
app.include_router(router)
client = TestClient(app)

# ─── 测试辅助 ──────────────────────────────────────────────────────────────────

def _create_report(
    name: str = "测试报表",
    data_source: str = "orders",
    report_type: str = "custom",
) -> dict:
    """创建自定义报表并返回data字典"""
    payload = {
        "name": name,
        "report_type": report_type,
        "data_source": data_source,
        "chart_type": "table",
        "dimensions": [{"field": "store_id", "label": "门店", "type": "string"}],
        "metrics": [{"field": "revenue_fen", "label": "营业额", "agg": "sum"}],
        "filters": [{"field": "date", "op": "gte", "value": "today-7d"}],
        "sort_by": "revenue_fen",
        "sort_order": "desc",
    }
    resp = client.post("/api/v1/analytics/reports", json=payload)
    assert resp.status_code == 200, f"创建报表失败: {resp.text}"
    return resp.json()["data"]


# ─── 测试用例 ──────────────────────────────────────────────────────────────────

class TestGetReportsList:
    """TC-1: 获取报表列表，验证含标准报表≥5条"""

    def test_list_contains_standard_reports(self) -> None:
        resp = client.get("/api/v1/analytics/reports")
        assert resp.status_code == 200

        body = resp.json()
        assert body["ok"] is True

        data = body["data"]
        assert "items" in data
        assert "total" in data

        items = data["items"]
        assert len(items) >= 5, f"期望至少5条报表，实际 {len(items)} 条"

    def test_list_each_item_has_required_fields(self) -> None:
        resp = client.get("/api/v1/analytics/reports")
        assert resp.status_code == 200

        items = resp.json()["data"]["items"]
        for item in items:
            assert "name" in item, f"报表缺少 name 字段: {item}"
            assert "report_type" in item, f"报表缺少 report_type 字段: {item}"
            assert "data_source" in item, f"报表缺少 data_source 字段: {item}"

    def test_list_standard_reports_count(self) -> None:
        resp = client.get("/api/v1/analytics/reports?report_type=standard")
        assert resp.status_code == 200

        items = resp.json()["data"]["items"]
        standard_items = [i for i in items if i["report_type"] == "standard"]
        assert len(standard_items) >= 5, f"标准报表应≥5条，实际 {len(standard_items)} 条"

    def test_list_filter_by_favorite(self) -> None:
        resp = client.get("/api/v1/analytics/reports?is_favorite=true")
        assert resp.status_code == 200

        items = resp.json()["data"]["items"]
        # 所有返回项都应是收藏的
        for item in items:
            assert item.get("is_favorite") is True


class TestCreateAndGetCustomReport:
    """TC-2: 创建自定义报表，验证字段完整保存"""

    def test_create_report_returns_ok(self) -> None:
        report = _create_report(name="字段完整性测试报表")

        assert report["name"] == "字段完整性测试报表"
        assert report["report_type"] == "custom"
        assert report["data_source"] == "orders"
        assert report["chart_type"] == "table"
        assert isinstance(report["id"], str) and len(report["id"]) > 0

    def test_create_report_saves_dimensions(self) -> None:
        report = _create_report(name="维度保存测试")

        assert isinstance(report["dimensions"], list)
        assert len(report["dimensions"]) > 0
        assert report["dimensions"][0]["field"] == "store_id"
        assert report["dimensions"][0]["label"] == "门店"

    def test_create_report_saves_metrics(self) -> None:
        report = _create_report(name="指标保存测试")

        assert isinstance(report["metrics"], list)
        assert len(report["metrics"]) > 0
        assert report["metrics"][0]["field"] == "revenue_fen"
        assert report["metrics"][0]["agg"] == "sum"

    def test_create_report_saves_filters(self) -> None:
        report = _create_report(name="过滤条件保存测试")

        assert isinstance(report["filters"], list)
        assert len(report["filters"]) > 0
        assert report["filters"][0]["field"] == "date"
        assert report["filters"][0]["op"] == "gte"

    def test_get_report_by_id(self) -> None:
        created = _create_report(name="GET详情测试")
        report_id = created["id"]

        resp = client.get(f"/api/v1/analytics/reports/{report_id}")
        assert resp.status_code == 200

        fetched = resp.json()["data"]
        assert fetched["id"] == report_id
        assert fetched["name"] == "GET详情测试"
        assert fetched["dimensions"] == created["dimensions"]
        assert fetched["metrics"] == created["metrics"]
        assert fetched["filters"] == created["filters"]

    def test_get_nonexistent_report_returns_404(self) -> None:
        resp = client.get("/api/v1/analytics/reports/nonexistent-id-000")
        assert resp.status_code == 404


class TestExecuteReportReturnsData:
    """TC-3: 执行报表，验证status/rows/execution_ms"""

    def test_execute_standard_report(self) -> None:
        resp = client.post("/api/v1/analytics/reports/std-001/execute")
        assert resp.status_code == 200

        body = resp.json()
        assert body["ok"] is True

        data = body["data"]
        assert "execution" in data
        assert "rows" in data

    def test_execute_returns_completed_status(self) -> None:
        report = _create_report(name="执行状态测试", data_source="orders")
        resp = client.post(f"/api/v1/analytics/reports/{report['id']}/execute")
        assert resp.status_code == 200

        execution = resp.json()["data"]["execution"]
        assert execution["status"] == "completed"

    def test_execute_returns_non_empty_rows(self) -> None:
        report = _create_report(name="数据行测试", data_source="members")
        resp = client.post(f"/api/v1/analytics/reports/{report['id']}/execute")
        assert resp.status_code == 200

        data = resp.json()["data"]
        rows = data["rows"]
        assert isinstance(rows, list)
        assert len(rows) > 0, "执行报表应返回非空数据行"

    def test_execute_returns_positive_execution_ms(self) -> None:
        report = _create_report(name="执行耗时测试", data_source="inventory")
        resp = client.post(f"/api/v1/analytics/reports/{report['id']}/execute")
        assert resp.status_code == 200

        execution = resp.json()["data"]["execution"]
        assert "execution_ms" in execution
        assert execution["execution_ms"] >= 0, "execution_ms 应为非负整数"

    def test_execute_different_data_sources(self) -> None:
        for source in ("orders", "members", "inventory", "employees", "finance"):
            report = _create_report(name=f"{source}_执行测试", data_source=source)
            resp = client.post(f"/api/v1/analytics/reports/{report['id']}/execute")
            assert resp.status_code == 200, f"{source} 数据源执行失败"

            rows = resp.json()["data"]["rows"]
            assert len(rows) > 0, f"{source} 数据源应返回数据行"


class TestShareTokenGeneration:
    """TC-4: 生成分享链接，验证token格式和URL"""

    def test_share_returns_token(self) -> None:
        report = _create_report(name="分享token测试")
        resp = client.post(f"/api/v1/analytics/reports/{report['id']}/share")
        assert resp.status_code == 200

        data = resp.json()["data"]
        assert "share_token" in data
        assert "share_url" in data

    def test_share_token_is_64_char_hex(self) -> None:
        report = _create_report(name="token格式测试")
        resp = client.post(f"/api/v1/analytics/reports/{report['id']}/share")
        assert resp.status_code == 200

        share_token = resp.json()["data"]["share_token"]
        assert len(share_token) == 64, f"share_token 应为64字符，实际 {len(share_token)} 字符"
        # 验证是合法的十六进制字符串
        int(share_token, 16)  # 如果不是hex会抛出 ValueError

    def test_share_url_contains_token(self) -> None:
        report = _create_report(name="URL包含token测试")
        resp = client.post(f"/api/v1/analytics/reports/{report['id']}/share")
        assert resp.status_code == 200

        data = resp.json()["data"]
        share_token = data["share_token"]
        share_url = data["share_url"]

        assert share_token in share_url, f"share_url 应包含 share_token"

    def test_shared_report_accessible_by_token(self) -> None:
        report = _create_report(name="token访问测试")
        share_resp = client.post(f"/api/v1/analytics/reports/{report['id']}/share")
        assert share_resp.status_code == 200

        token = share_resp.json()["data"]["share_token"]

        # 通过token访问报表
        view_resp = client.get(f"/api/v1/analytics/reports/shared/{token}")
        assert view_resp.status_code == 200

        view_data = view_resp.json()["data"]
        assert "report" in view_data
        assert "rows" in view_data

    def test_invalid_share_token_returns_404(self) -> None:
        resp = client.get("/api/v1/analytics/reports/shared/invalid-token-that-does-not-exist")
        assert resp.status_code == 404


class TestNarrativeTemplatePreview:
    """TC-5: 预览AI叙事，验证文本非空且含brand_focus关键词"""

    def test_preview_builtin_template(self) -> None:
        resp = client.post("/api/v1/analytics/narrative-templates/tpl-001/preview")
        assert resp.status_code == 200

        body = resp.json()
        assert body["ok"] is True

    def test_preview_returns_non_empty_narrative(self) -> None:
        resp = client.post("/api/v1/analytics/narrative-templates/tpl-001/preview")
        assert resp.status_code == 200

        data = resp.json()["data"]
        assert "narrative" in data
        narrative = data["narrative"]
        assert isinstance(narrative, str)
        assert len(narrative) > 20, f"叙事文本应非空且有实质内容，实际：{narrative!r}"

    def test_preview_seafood_template_contains_brand_focus(self) -> None:
        """徐记海鲜模板的叙事文本应包含其brand_focus关键词"""
        resp = client.post("/api/v1/analytics/narrative-templates/tpl-002/preview")
        assert resp.status_code == 200

        data = resp.json()["data"]
        narrative = data["narrative"]
        brand_focus = data.get("brand_focus", "")

        # brand_focus 中的关键词（至少一个）应出现在叙事文本中
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
        """创建自定义模板并预览"""
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
        narrative = data["narrative"]
        assert len(narrative) > 20

    def test_preview_nonexistent_template_returns_404(self) -> None:
        resp = client.post("/api/v1/analytics/narrative-templates/nonexistent-999/preview")
        assert resp.status_code == 404

    def test_list_narrative_templates(self) -> None:
        resp = client.get("/api/v1/analytics/narrative-templates")
        assert resp.status_code == 200

        data = resp.json()["data"]
        assert "items" in data
        items = data["items"]
        assert len(items) >= 3, f"应至少有3个内置模板，实际 {len(items)}"
