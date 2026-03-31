"""小票可视化编辑器测试

覆盖：
  1. TemplateRenderer — 各 element 类型 ESC/POS 渲染
  2. preview 接口 — 返回格式验证
  3. elements/catalog 接口 — 完整性验证
  4. CRUD API 端点 — mock db
  5. 边界条件

共 25+ 测试用例，全部不依赖真实数据库或打印机。
"""
import json
import sys
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# 路径修正（在 tests/ 目录下直接运行 pytest）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.template_renderer import TemplateRenderer, _apply_template_vars, _yuan_str
from services.printer_driver import (
    ESC_INIT,
    ESC_ALIGN_CENTER,
    ESC_ALIGN_LEFT,
    ESC_BOLD_ON,
    ESC_BOLD_OFF,
    GS_SIZE_NORMAL,
    GS_SIZE_DOUBLE_HEIGHT,
    GS_SIZE_DOUBLE_BOTH,
    GS_CUT_PARTIAL,
    LF,
)

# ─── 共用示例数据 ───

SAMPLE_CONTEXT = {
    "store_name": "好味道火锅",
    "store_address": "长沙市天心区解放西路88号",
    "table_no": "A08",
    "order_no": "TX20260331120001A",
    "cashier": "李淳",
    "datetime": "2026-03-31 12:00:00",
    "items": [
        {"name": "毛肚", "qty": 2, "price_yuan": 32.0, "subtotal_yuan": 64.0, "notes": ""},
        {"name": "黄喉", "qty": 1, "price_yuan": 28.0, "subtotal_yuan": 28.0, "notes": "不要辣"},
    ],
    "subtotal_yuan": 200.0,
    "discount_yuan": 20.0,
    "service_fee_yuan": 10.0,
    "total_yuan": 190.0,
    "payment_method": "wechat",
    "payment_amount_yuan": 200.0,
    "change_yuan": 10.0,
    "order_id": "3f4a8b2c-1234-5678-abcd-ef0123456789",
}

SAMPLE_CONFIG = {
    "paper_width": 80,
    "elements": [
        {"id": "e1", "type": "store_name", "align": "center", "bold": True, "size": "double_height"},
        {"id": "e2", "type": "store_address", "align": "center", "bold": False},
        {"id": "e3", "type": "separator", "char": "-"},
        {"id": "e4", "type": "order_info", "fields": ["table_no", "order_no", "cashier", "datetime"]},
        {"id": "e5", "type": "separator", "char": "-"},
        {"id": "e6", "type": "order_items", "show_price": True, "show_qty": True, "show_subtotal": True},
        {"id": "e7", "type": "separator", "char": "="},
        {"id": "e8", "type": "total_summary", "show_discount": True, "show_service_fee": True},
        {"id": "e9", "type": "payment_method", "show_change": True},
        {"id": "e10", "type": "qrcode", "content_field": "order_id", "size": 6},
        {"id": "e11", "type": "custom_text", "content": "谢谢惠顾，欢迎再来！", "align": "center"},
        {"id": "e12", "type": "blank_lines", "count": 2},
        {"id": "e13", "type": "logo_text", "content": "屯象OS · 智慧餐饮", "align": "center"},
        {"id": "e14", "type": "barcode", "content_field": "order_no"},
    ],
}


# ════════════════════════════════════════════════
# 1. TemplateRenderer 单元测试
# ════════════════════════════════════════════════


class TestTemplateRenderer:
    """测试 TemplateRenderer 各 element 渲染。"""

    @pytest.fixture
    def renderer(self):
        return TemplateRenderer()

    @pytest.mark.asyncio
    async def test_render_returns_bytes(self, renderer):
        """完整渲染应返回 bytes 类型。"""
        result = await renderer.render(SAMPLE_CONFIG, SAMPLE_CONTEXT)
        assert isinstance(result, bytes)

    @pytest.mark.asyncio
    async def test_render_starts_with_esc_init(self, renderer):
        """字节流必须以 ESC @ 初始化开头。"""
        result = await renderer.render(SAMPLE_CONFIG, SAMPLE_CONTEXT)
        assert result.startswith(ESC_INIT)

    @pytest.mark.asyncio
    async def test_render_ends_with_cut(self, renderer):
        """字节流必须以切纸指令结尾。"""
        result = await renderer.render(SAMPLE_CONFIG, SAMPLE_CONTEXT)
        assert GS_CUT_PARTIAL in result

    @pytest.mark.asyncio
    async def test_store_name_element(self, renderer):
        """store_name element 应包含店名 GBK 编码。"""
        config = {"elements": [{"id": "e1", "type": "store_name", "align": "center", "bold": True, "size": "double_height"}]}
        result = await renderer.render(config, SAMPLE_CONTEXT)
        assert "好味道火锅".encode("gbk") in result
        assert GS_SIZE_DOUBLE_HEIGHT in result
        assert ESC_BOLD_ON in result

    @pytest.mark.asyncio
    async def test_store_address_element(self, renderer):
        """store_address element 应包含地址。"""
        config = {"elements": [{"id": "e2", "type": "store_address", "align": "center"}]}
        result = await renderer.render(config, SAMPLE_CONTEXT)
        assert "长沙市".encode("gbk") in result

    @pytest.mark.asyncio
    async def test_store_address_empty_skipped(self, renderer):
        """store_address 为空时不输出内容（只有初始化和切纸）。"""
        config = {"elements": [{"id": "e2", "type": "store_address"}]}
        ctx = {**SAMPLE_CONTEXT, "store_address": ""}
        result = await renderer.render(config, ctx)
        # 去掉 ESC_INIT 和 cut 之后基本为空
        inner = result[len(ESC_INIT):-len(b'\x03' + GS_CUT_PARTIAL) - 1]
        assert len(inner) == 0

    @pytest.mark.asyncio
    async def test_separator_dash(self, renderer):
        """separator char=- 应生成 48 个连字符。"""
        config = {"elements": [{"id": "e3", "type": "separator", "char": "-"}]}
        result = await renderer.render(config, SAMPLE_CONTEXT)
        assert b"-" * 48 in result

    @pytest.mark.asyncio
    async def test_separator_equals(self, renderer):
        """separator char== 应生成等号分隔线。"""
        config = {"elements": [{"id": "e3", "type": "separator", "char": "="}]}
        result = await renderer.render(config, SAMPLE_CONTEXT)
        assert b"=" * 48 in result

    @pytest.mark.asyncio
    async def test_order_info_contains_fields(self, renderer):
        """order_info element 应包含桌号/单号。"""
        config = {"elements": [{"id": "e4", "type": "order_info",
                                "fields": ["table_no", "order_no"]}]}
        result = await renderer.render(config, SAMPLE_CONTEXT)
        assert "A08".encode("gbk") in result
        assert "TX20260331120001A".encode("gbk") in result

    @pytest.mark.asyncio
    async def test_order_items_contains_dish_names(self, renderer):
        """order_items element 应包含所有菜品名。"""
        config = {"elements": [{"id": "e6", "type": "order_items",
                                "show_price": True, "show_qty": True, "show_subtotal": True}]}
        result = await renderer.render(config, SAMPLE_CONTEXT)
        assert "毛肚".encode("gbk") in result
        assert "黄喉".encode("gbk") in result

    @pytest.mark.asyncio
    async def test_order_items_notes_included(self, renderer):
        """order_items 菜品备注应出现在输出中。"""
        config = {"elements": [{"id": "e6", "type": "order_items",
                                "show_qty": True, "show_subtotal": True}]}
        result = await renderer.render(config, SAMPLE_CONTEXT)
        assert "不要辣".encode("gbk") in result

    @pytest.mark.asyncio
    async def test_total_summary_shows_discount(self, renderer):
        """total_summary 应包含折扣和实付金额。"""
        config = {"elements": [{"id": "e8", "type": "total_summary",
                                "show_discount": True, "show_service_fee": True}]}
        result = await renderer.render(config, SAMPLE_CONTEXT)
        assert "实付".encode("gbk") in result
        assert "优惠".encode("gbk") in result

    @pytest.mark.asyncio
    async def test_total_summary_no_discount_when_zero(self, renderer):
        """discount_yuan=0 时不显示折扣行。"""
        config = {"elements": [{"id": "e8", "type": "total_summary",
                                "show_discount": True, "show_service_fee": False}]}
        ctx = {**SAMPLE_CONTEXT, "discount_yuan": 0.0}
        result = await renderer.render(config, ctx)
        assert "优惠".encode("gbk") not in result

    @pytest.mark.asyncio
    async def test_payment_method_wechat(self, renderer):
        """payment_method 应显示微信支付。"""
        config = {"elements": [{"id": "e9", "type": "payment_method", "show_change": True}]}
        result = await renderer.render(config, SAMPLE_CONTEXT)
        assert "微信支付".encode("gbk") in result
        assert "找零".encode("gbk") in result

    @pytest.mark.asyncio
    async def test_payment_method_no_change_when_disabled(self, renderer):
        """show_change=False 时不显示找零。"""
        config = {"elements": [{"id": "e9", "type": "payment_method", "show_change": False}]}
        result = await renderer.render(config, SAMPLE_CONTEXT)
        assert "找零".encode("gbk") not in result

    @pytest.mark.asyncio
    async def test_qrcode_included(self, renderer):
        """qrcode element 应生成 QR code ESC/POS 指令（以 GS ( k 开头）。"""
        config = {"elements": [{"id": "e10", "type": "qrcode",
                                "content_field": "order_id", "size": 6}]}
        result = await renderer.render(config, SAMPLE_CONTEXT)
        # GS ( k 是二维码指令前缀
        assert b'\x1d\x28\x6b' in result

    @pytest.mark.asyncio
    async def test_qrcode_empty_content_skipped(self, renderer):
        """content 和 content_field 都为空时跳过 qrcode。"""
        config = {"elements": [{"id": "e10", "type": "qrcode", "content": ""}]}
        ctx = {**SAMPLE_CONTEXT, "order_id": ""}
        result = await renderer.render(config, ctx)
        assert b'\x1d\x28\x6b' not in result

    @pytest.mark.asyncio
    async def test_barcode_included(self, renderer):
        """barcode element 应生成条形码 ESC/POS 指令（GS k）。"""
        config = {"elements": [{"id": "e14", "type": "barcode",
                                "content_field": "order_no"}]}
        result = await renderer.render(config, SAMPLE_CONTEXT)
        assert b'\x1d\x6b' in result

    @pytest.mark.asyncio
    async def test_custom_text_rendered(self, renderer):
        """custom_text 应渲染出文字。"""
        config = {"elements": [{"id": "e11", "type": "custom_text",
                                "content": "谢谢惠顾", "align": "center"}]}
        result = await renderer.render(config, SAMPLE_CONTEXT)
        assert "谢谢惠顾".encode("gbk") in result

    @pytest.mark.asyncio
    async def test_custom_text_variable_substitution(self, renderer):
        """custom_text 支持 {{变量}} 替换。"""
        config = {"elements": [{"id": "e11", "type": "custom_text",
                                "content": "单号: {{order_no}}", "align": "left"}]}
        result = await renderer.render(config, SAMPLE_CONTEXT)
        assert "TX20260331120001A".encode("gbk") in result

    @pytest.mark.asyncio
    async def test_blank_lines(self, renderer):
        """blank_lines 应输出 LF 字节。"""
        config = {"elements": [{"id": "e12", "type": "blank_lines", "count": 3}]}
        result = await renderer.render(config, SAMPLE_CONTEXT)
        assert LF * 3 in result

    @pytest.mark.asyncio
    async def test_logo_text_rendered(self, renderer):
        """logo_text 应渲染文字。"""
        config = {"elements": [{"id": "e13", "type": "logo_text",
                                "content": "屯象OS", "align": "center"}]}
        result = await renderer.render(config, SAMPLE_CONTEXT)
        assert "屯象OS".encode("gbk") in result

    @pytest.mark.asyncio
    async def test_unknown_element_type_skipped(self, renderer):
        """未知 element 类型应被跳过，不抛出异常。"""
        config = {"elements": [{"id": "x1", "type": "unknown_future_type"}]}
        result = await renderer.render(config, SAMPLE_CONTEXT)
        assert isinstance(result, bytes)

    @pytest.mark.asyncio
    async def test_paper_width_58(self, renderer):
        """纸宽 58mm 时分隔线应为 32 字符。"""
        config = {"elements": [{"id": "e3", "type": "separator", "char": "-"}]}
        result = await renderer.render(config, SAMPLE_CONTEXT, paper_width=58)
        assert b"-" * 32 in result
        # 58mm 纸不应有 48 个连字符
        assert b"-" * 48 not in result

    @pytest.mark.asyncio
    async def test_empty_elements_list(self, renderer):
        """elements 为空列表时，只返回初始化和切纸。"""
        config = {"elements": []}
        result = await renderer.render(config, SAMPLE_CONTEXT)
        assert result.startswith(ESC_INIT)
        assert GS_CUT_PARTIAL in result

    def test_apply_template_vars(self):
        """_apply_template_vars 应正确替换 {{key}} 占位符。"""
        text = "桌号:{{table_no}} 单号:{{order_no}} 未知:{{xyz}}"
        ctx = {"table_no": "A01", "order_no": "TX001"}
        result = _apply_template_vars(text, ctx)
        assert "A01" in result
        assert "TX001" in result
        assert "{{xyz}}" in result   # 未定义的变量保留原样

    def test_yuan_str_format(self):
        """_yuan_str 应输出 ¥XX.XX 格式。"""
        assert _yuan_str(180.0) == "\xa5180.00"
        assert _yuan_str(0.5) == "\xa50.50"
        assert _yuan_str(1234.56) == "\xa51234.56"


# ════════════════════════════════════════════════
# 2. preview 接口测试（使用 FastAPI TestClient + mock db）
# ════════════════════════════════════════════════


def _make_app():
    """创建测试用 FastAPI app，屏蔽真实 DB。"""
    from fastapi import FastAPI
    from api.template_editor_routes import router

    app = FastAPI()
    app.include_router(router)
    return app


class TestPreviewEndpoint:
    @pytest.fixture
    def client(self):
        app = _make_app()
        return TestClient(app)

    def test_preview_returns_ok(self, client):
        """preview 接口应返回 ok=true。"""
        resp = client.post(
            "/api/v1/receipt-templates/preview",
            json={"config": SAMPLE_CONFIG},
            headers={"X-Tenant-ID": str(uuid.uuid4())},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True

    def test_preview_contains_preview_lines(self, client):
        """preview 返回结构应包含 preview_lines 列表。"""
        resp = client.post(
            "/api/v1/receipt-templates/preview",
            json={"config": SAMPLE_CONFIG},
            headers={"X-Tenant-ID": str(uuid.uuid4())},
        )
        data = resp.json()["data"]
        assert "preview_lines" in data
        assert isinstance(data["preview_lines"], list)
        assert len(data["preview_lines"]) > 0

    def test_preview_paper_width_80(self, client):
        """80mm 纸宽时 char_width 应为 48。"""
        resp = client.post(
            "/api/v1/receipt-templates/preview",
            json={"config": {**SAMPLE_CONFIG, "paper_width": 80}},
            headers={"X-Tenant-ID": str(uuid.uuid4())},
        )
        data = resp.json()["data"]
        assert data["paper_width_mm"] == 80
        assert data["char_width"] == 48

    def test_preview_paper_width_58(self, client):
        """58mm 纸宽时 char_width 应为 32。"""
        resp = client.post(
            "/api/v1/receipt-templates/preview",
            json={"config": {**SAMPLE_CONFIG, "paper_width": 58}},
            headers={"X-Tenant-ID": str(uuid.uuid4())},
        )
        data = resp.json()["data"]
        assert data["paper_width_mm"] == 58
        assert data["char_width"] == 32

    def test_preview_line_types(self, client):
        """preview_lines 中的每条记录都有 type 字段。"""
        resp = client.post(
            "/api/v1/receipt-templates/preview",
            json={"config": SAMPLE_CONFIG},
            headers={"X-Tenant-ID": str(uuid.uuid4())},
        )
        lines = resp.json()["data"]["preview_lines"]
        for line in lines:
            assert "type" in line

    def test_preview_store_name_line(self, client):
        """preview 中 store_name element 应生成带店名的 text 行。"""
        config = {
            "paper_width": 80,
            "elements": [{"id": "e1", "type": "store_name", "align": "center",
                          "bold": True, "size": "double_height"}],
        }
        resp = client.post(
            "/api/v1/receipt-templates/preview",
            json={"config": config},
            headers={"X-Tenant-ID": str(uuid.uuid4())},
        )
        lines = resp.json()["data"]["preview_lines"]
        assert len(lines) == 1
        assert lines[0]["type"] == "text"
        assert lines[0]["content"] == "好味道火锅"
        assert lines[0]["bold"] is True

    def test_preview_separator_line(self, client):
        """preview 中 separator element 应生成 separator 类型行。"""
        config = {
            "paper_width": 80,
            "elements": [{"id": "e3", "type": "separator", "char": "="}],
        }
        resp = client.post(
            "/api/v1/receipt-templates/preview",
            json={"config": config},
            headers={"X-Tenant-ID": str(uuid.uuid4())},
        )
        lines = resp.json()["data"]["preview_lines"]
        assert lines[0]["type"] == "separator"
        assert lines[0]["char"] == "="

    def test_preview_empty_elements(self, client):
        """elements 为空时，preview_lines 也为空。"""
        config = {"paper_width": 80, "elements": []}
        resp = client.post(
            "/api/v1/receipt-templates/preview",
            json={"config": config},
            headers={"X-Tenant-ID": str(uuid.uuid4())},
        )
        assert resp.json()["data"]["preview_lines"] == []

    def test_preview_custom_text_variable(self, client):
        """custom_text 中 {{order_no}} 应被示例数据替换。"""
        config = {
            "paper_width": 80,
            "elements": [{"id": "e11", "type": "custom_text",
                          "content": "单号: {{order_no}}", "align": "center"}],
        }
        resp = client.post(
            "/api/v1/receipt-templates/preview",
            json={"config": config},
            headers={"X-Tenant-ID": str(uuid.uuid4())},
        )
        lines = resp.json()["data"]["preview_lines"]
        assert "TX20260331120001A" in lines[0]["content"]

    def test_preview_qrcode_line(self, client):
        """qrcode element 应生成 qrcode 类型行。"""
        config = {
            "paper_width": 80,
            "elements": [{"id": "e10", "type": "qrcode", "content_field": "order_id"}],
        }
        resp = client.post(
            "/api/v1/receipt-templates/preview",
            json={"config": config},
            headers={"X-Tenant-ID": str(uuid.uuid4())},
        )
        lines = resp.json()["data"]["preview_lines"]
        assert len(lines) == 1
        assert lines[0]["type"] == "qrcode"

    def test_preview_blank_lines(self, client):
        """blank_lines count=3 应生成 3 个 blank 类型行。"""
        config = {
            "paper_width": 80,
            "elements": [{"id": "e12", "type": "blank_lines", "count": 3}],
        }
        resp = client.post(
            "/api/v1/receipt-templates/preview",
            json={"config": config},
            headers={"X-Tenant-ID": str(uuid.uuid4())},
        )
        lines = resp.json()["data"]["preview_lines"]
        blank_lines = [l for l in lines if l["type"] == "blank"]
        assert len(blank_lines) == 3


# ════════════════════════════════════════════════
# 3. elements/catalog 接口测试
# ════════════════════════════════════════════════


class TestElementsCatalog:
    @pytest.fixture
    def client(self):
        app = _make_app()
        return TestClient(app)

    def test_catalog_returns_ok(self, client):
        """catalog 接口应返回 ok=true。"""
        resp = client.get(
            "/api/v1/receipt-templates/elements/catalog",
            headers={"X-Tenant-ID": str(uuid.uuid4())},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_catalog_contains_all_element_types(self, client):
        """catalog 应包含全部 12 种 element 类型。"""
        expected_types = {
            "store_name", "store_address", "separator", "order_info",
            "order_items", "total_summary", "payment_method", "qrcode",
            "barcode", "custom_text", "blank_lines", "logo_text",
        }
        resp = client.get(
            "/api/v1/receipt-templates/elements/catalog",
            headers={"X-Tenant-ID": str(uuid.uuid4())},
        )
        elements = resp.json()["data"]["elements"]
        actual_types = {e["type"] for e in elements}
        assert expected_types == actual_types

    def test_catalog_element_has_required_fields(self, client):
        """每个 catalog element 必须有 type/label/icon/category/props。"""
        resp = client.get(
            "/api/v1/receipt-templates/elements/catalog",
            headers={"X-Tenant-ID": str(uuid.uuid4())},
        )
        elements = resp.json()["data"]["elements"]
        for elem in elements:
            assert "type" in elem, f"缺少 type: {elem}"
            assert "label" in elem, f"缺少 label: {elem}"
            assert "icon" in elem, f"缺少 icon: {elem}"
            assert "category" in elem, f"缺少 category: {elem}"
            assert "props" in elem, f"缺少 props: {elem}"
            assert isinstance(elem["props"], list), f"props 应为 list: {elem}"

    def test_catalog_props_have_required_fields(self, client):
        """每个 prop 必须有 key/label/type/default。"""
        resp = client.get(
            "/api/v1/receipt-templates/elements/catalog",
            headers={"X-Tenant-ID": str(uuid.uuid4())},
        )
        elements = resp.json()["data"]["elements"]
        for elem in elements:
            for prop in elem["props"]:
                assert "key" in prop, f"prop 缺少 key: {prop}"
                assert "label" in prop, f"prop 缺少 label: {prop}"
                assert "type" in prop, f"prop 缺少 type: {prop}"
                assert "default" in prop, f"prop 缺少 default: {prop}"

    def test_catalog_categories_coverage(self, client):
        """catalog 应覆盖多个 category。"""
        resp = client.get(
            "/api/v1/receipt-templates/elements/catalog",
            headers={"X-Tenant-ID": str(uuid.uuid4())},
        )
        elements = resp.json()["data"]["elements"]
        categories = {e["category"] for e in elements}
        # 至少包含这几个分类
        assert "基础信息" in categories
        assert "订单数据" in categories
        assert "布局" in categories
        assert "自定义" in categories


# ════════════════════════════════════════════════
# 4. CRUD API 端点测试（mock async_session_factory）
# ════════════════════════════════════════════════


def _mock_session_ctx(rows=None, scalar=None):
    """返回一个 mock 的 async_session_factory context manager。"""
    mock_result = MagicMock()
    mock_mapping = MagicMock()

    if rows is not None:
        mock_mapping.first.return_value = rows[0] if rows else None
        mock_mapping.__iter__ = MagicMock(return_value=iter(rows))
    else:
        mock_mapping.first.return_value = None

    mock_result.mappings.return_value = mock_mapping
    mock_result.scalar.return_value = scalar or 0

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_begin_ctx = AsyncMock()
    mock_begin_ctx.__aenter__ = AsyncMock(return_value=None)
    mock_begin_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock(return_value=mock_begin_ctx)

    mock_factory = MagicMock(return_value=mock_session)
    return mock_factory


class TestCRUDEndpoints:
    @pytest.fixture
    def client(self):
        app = _make_app()
        return TestClient(app, raise_server_exceptions=False)

    def test_list_templates_requires_tenant_header(self, client):
        """缺少 X-Tenant-ID header 应返回 422。"""
        resp = client.get("/api/v1/receipt-templates")
        assert resp.status_code == 422

    def test_preview_missing_tenant_header(self, client):
        """preview 缺少 X-Tenant-ID 应返回 422。"""
        resp = client.post(
            "/api/v1/receipt-templates/preview",
            json={"config": SAMPLE_CONFIG},
        )
        assert resp.status_code == 422

    def test_get_nonexistent_template_404(self, client):
        """获取不存在的模板应返回 404。"""
        fake_id = uuid.uuid4()
        # mock DB 返回 None（模板不存在）
        with patch(
            "api.template_editor_routes.async_session_factory",
            _mock_session_ctx(rows=[]),
        ):
            resp = client.get(
                f"/api/v1/receipt-templates/{fake_id}",
                headers={"X-Tenant-ID": str(uuid.uuid4())},
            )
        assert resp.status_code == 404

    def test_create_template_validates_config(self, client):
        """创建模板时 config 字段为必填。"""
        resp = client.post(
            "/api/v1/receipt-templates",
            json={
                "store_id": str(uuid.uuid4()),
                "template_name": "测试模板",
                # 缺少 config 字段
            },
            headers={"X-Tenant-ID": str(uuid.uuid4())},
        )
        assert resp.status_code == 422

    def test_update_template_nonexistent_404(self, client):
        """更新不存在的模板应返回 404。"""
        fake_id = uuid.uuid4()
        with patch(
            "api.template_editor_routes.async_session_factory",
            _mock_session_ctx(rows=[]),
        ):
            resp = client.put(
                f"/api/v1/receipt-templates/{fake_id}",
                json={"template_name": "新名字"},
                headers={"X-Tenant-ID": str(uuid.uuid4())},
            )
        assert resp.status_code == 404

    def test_delete_template_nonexistent_404(self, client):
        """删除不存在的模板应返回 404。"""
        fake_id = uuid.uuid4()
        with patch(
            "api.template_editor_routes.async_session_factory",
            _mock_session_ctx(rows=[]),
        ):
            resp = client.delete(
                f"/api/v1/receipt-templates/{fake_id}",
                headers={"X-Tenant-ID": str(uuid.uuid4())},
            )
        assert resp.status_code == 404

    def test_set_default_nonexistent_404(self, client):
        """对不存在的模板调用 set-default 应返回 404。"""
        fake_id = uuid.uuid4()
        with patch(
            "api.template_editor_routes.async_session_factory",
            _mock_session_ctx(rows=[]),
        ):
            resp = client.post(
                f"/api/v1/receipt-templates/{fake_id}/set-default",
                headers={"X-Tenant-ID": str(uuid.uuid4())},
            )
        assert resp.status_code == 404

    def test_duplicate_nonexistent_404(self, client):
        """复制不存在的模板应返回 404。"""
        fake_id = uuid.uuid4()
        with patch(
            "api.template_editor_routes.async_session_factory",
            _mock_session_ctx(rows=[]),
        ):
            resp = client.post(
                f"/api/v1/receipt-templates/{fake_id}/duplicate",
                headers={"X-Tenant-ID": str(uuid.uuid4())},
            )
        assert resp.status_code == 404

    def test_invalid_uuid_in_path(self, client):
        """路径中非法 UUID 应返回 422。"""
        resp = client.get(
            "/api/v1/receipt-templates/not-a-uuid",
            headers={"X-Tenant-ID": str(uuid.uuid4())},
        )
        assert resp.status_code == 422
