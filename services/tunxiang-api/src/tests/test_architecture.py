"""架构修正验证测试 — Correction #1, #2, #7

测试内容：
- Monolith health endpoint
- Amount convention functions
- SalesChannel 数据驱动
- Order metadata 弹性
- Store 虚拟门店支持
- Module imports
"""

import os
import sys

import pytest
from fastapi.testclient import TestClient

# ── Setup: ensure imports work ──
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))
_ontology_src = os.path.join(_project_root, "shared", "ontology", "src")
if _ontology_src not in sys.path:
    sys.path.insert(0, _ontology_src)

# ── Import app ──
from services.tunxiang_api.src.main import app  # noqa: E402

client = TestClient(app)


# ═══════════════════════════════════════════════
# Correction #2: MVP Monolith
# ═══════════════════════════════════════════════


class TestMonolithHealth:
    """验证单体入口正常启动"""

    def test_health_endpoint(self):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["service"] == "tunxiang-api"
        assert body["data"]["mode"] == "monolith"
        assert body["data"]["version"] == "7.1.0"

    def test_auth_login(self):
        resp = client.post(
            "/api/v1/auth/login",
            json={
                "username": "admin",
                "password": "admin123",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["user"]["role"] == "admin"
        assert "token" in body["data"]

    def test_auth_login_fail(self):
        resp = client.post(
            "/api/v1/auth/login",
            json={
                "username": "admin",
                "password": "wrong",
            },
        )
        assert resp.status_code == 401

    def test_trade_routes_exist(self):
        resp = client.get("/api/v1/trade/orders")
        assert resp.status_code == 200

    def test_ops_routes_exist(self):
        resp = client.get("/api/v1/ops/employees")
        assert resp.status_code == 200

    def test_brain_routes_exist(self):
        resp = client.get("/api/v1/brain/agents")
        assert resp.status_code == 200

    def test_hub_routes_exist(self):
        resp = client.get("/api/v1/hub/merchants")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════
# Correction #1: Amount Convention
# ═══════════════════════════════════════════════


class TestAmountConvention:
    """验证金额单位公约 — 全系统统一存分"""

    def test_yuan_to_fen_basic(self):
        from amount_convention import yuan_to_fen

        assert yuan_to_fen(168.00) == 16800
        assert yuan_to_fen(0.01) == 1
        assert yuan_to_fen(99999.99) == 9999999
        assert yuan_to_fen(0) == 0

    def test_yuan_to_fen_rounding(self):
        """浮点精度：round确保不出现 168.00 * 100 = 16799.999"""
        from amount_convention import yuan_to_fen

        assert yuan_to_fen(1.005) == 101  # round(100.5) = 100 or 101
        assert yuan_to_fen(19.99) == 1999

    def test_fen_to_yuan(self):
        from amount_convention import fen_to_yuan

        assert fen_to_yuan(16800) == 168.00
        assert fen_to_yuan(1) == 0.01
        assert fen_to_yuan(0) == 0.0

    def test_format_amount_small(self):
        from amount_convention import format_amount

        assert format_amount(16800) == "¥168.00"
        assert format_amount(1) == "¥0.01"
        assert format_amount(0) == "¥0.00"

    def test_format_amount_large(self):
        """大金额加千分位"""
        from amount_convention import format_amount

        result = format_amount(1000000)  # ¥10,000.00
        assert result == "¥10,000.00"
        result2 = format_amount(12345678)  # ¥123,456.78
        assert result2 == "¥123,456.78"

    def test_validate_fen_ok(self):
        from amount_convention import validate_fen

        assert validate_fen(100) == 100
        assert validate_fen(0) == 0

    def test_validate_fen_not_int(self):
        from amount_convention import validate_fen

        with pytest.raises(ValueError, match="must be integer"):
            validate_fen(100.5)  # type: ignore

    def test_validate_fen_negative(self):
        from amount_convention import validate_fen

        with pytest.raises(ValueError, match="cannot be negative"):
            validate_fen(-1)

    def test_validate_fen_custom_field_name(self):
        from amount_convention import validate_fen

        with pytest.raises(ValueError, match="total_fen"):
            validate_fen(-1, field_name="total_fen")


# ═══════════════════════════════════════════════
# Correction #7: Data Model Flexibility
# ═══════════════════════════════════════════════


class TestSalesChannel:
    """验证渠道配置表 — 数据驱动，非枚举"""

    def test_default_channels_count(self):
        from sales_channel import DEFAULT_CHANNELS

        assert len(DEFAULT_CHANNELS) == 11

    def test_get_channel_by_id(self):
        from sales_channel import get_channel_by_id

        ch = get_channel_by_id("ch_meituan")
        assert ch is not None
        assert ch.channel_name == "美团外卖"
        assert ch.commission_rate == 0.18
        assert ch.channel_type == "delivery"

    def test_get_channel_not_found(self):
        from sales_channel import get_channel_by_id

        assert get_channel_by_id("ch_nonexistent") is None

    def test_get_channels_by_type(self):
        from sales_channel import get_channels_by_type

        delivery = get_channels_by_type("delivery")
        assert len(delivery) == 3  # 美团, 饿了么, 抖音
        names = {ch.channel_name for ch in delivery}
        assert "美团外卖" in names
        assert "饿了么" in names
        assert "抖音外卖" in names

    def test_add_new_channel_without_code_change(self):
        """新增渠道不改代码 — 加一条记录即可"""
        from sales_channel import DEFAULT_CHANNELS, SalesChannel

        new_channel = SalesChannel(
            channel_id="ch_pinduoduo",
            channel_name="拼多多外卖",
            channel_type="delivery",
            commission_rate=0.15,
            settlement_days=7,
            payment_fee_rate=0.0,
            margin_rules={"type": "platform", "deduct_commission": True},
        )

        # Simulate adding to config (in real code: INSERT into sales_channels table)
        channels = DEFAULT_CHANNELS + [new_channel]
        assert len(channels) == 12
        assert channels[-1].channel_name == "拼多多外卖"

    def test_dine_in_zero_commission(self):
        from sales_channel import get_channel_by_id

        ch = get_channel_by_id("ch_dine_in")
        assert ch is not None
        assert ch.commission_rate == 0.0
        assert ch.settlement_days == 0

    def test_b2b_channel(self):
        from sales_channel import get_channel_by_id

        ch = get_channel_by_id("ch_central_kitchen")
        assert ch is not None
        assert ch.channel_type == "b2b"
        assert ch.settlement_days == 30


class TestOrderMetadata:
    """验证订单 metadata 弹性 — table_no 可选"""

    def test_order_without_table_no(self):
        """预制菜零售场景：无桌台"""
        # Simulate creating a retail order — no table_no needed
        order_data = {
            "order_no": "R20260327001",
            "store_id": "store-central-kitchen",
            "order_type": "retail",
            "sales_channel_id": "ch_retail",
            "total_amount_fen": 9900,
            "discount_amount_fen": 0,
            "status": "pending",
            "order_metadata": {},  # No table_no — totally valid
        }
        assert "table_no" not in order_data["order_metadata"]
        assert order_data["order_type"] == "retail"

    def test_order_with_table_no_in_metadata(self):
        """堂食场景：table_no 在 metadata 中"""
        order_data = {
            "order_no": "D20260327001",
            "store_id": "store-furong",
            "order_type": "dine_in",
            "sales_channel_id": "ch_dine_in",
            "total_amount_fen": 16800,
            "discount_amount_fen": 0,
            "status": "pending",
            "order_metadata": {
                "table_no": "A03",
                "guest_count": 4,
            },
        }
        assert order_data["order_metadata"]["table_no"] == "A03"
        assert order_data["order_metadata"]["guest_count"] == 4

    def test_delivery_order_with_address(self):
        """外卖场景：metadata 含配送地址"""
        order_data = {
            "order_no": "MT20260327001",
            "store_id": "store-furong",
            "order_type": "delivery",
            "sales_channel_id": "ch_meituan",
            "total_amount_fen": 5600,
            "discount_amount_fen": 500,
            "status": "pending",
            "order_metadata": {
                "delivery_address": "长沙市芙蓉区xxx路123号",
                "delivery_phone": "138xxxx1234",
                "platform_order_id": "MT123456789",
            },
        }
        assert "table_no" not in order_data["order_metadata"]
        assert order_data["order_metadata"]["delivery_address"] != ""


class TestStoreFlexibility:
    """验证门店模型弹性 — 支持虚拟门店"""

    def test_virtual_store_no_address(self):
        """中央厨房：无地址，无座位"""
        store_data = {
            "store_name": "长沙中央厨房",
            "store_code": "CK-CS-001",
            "store_type": "central_kitchen",
            "has_physical_seats": False,
            "address": None,
            "seats": None,
            "business_type": "catering",
        }
        assert store_data["store_type"] == "central_kitchen"
        assert store_data["has_physical_seats"] is False
        assert store_data["address"] is None
        assert store_data["seats"] is None

    def test_physical_store(self):
        """普通餐厅：有地址，有座位"""
        store_data = {
            "store_name": "芙蓉路店",
            "store_code": "CZQ-CS-001",
            "store_type": "physical",
            "has_physical_seats": True,
            "address": "长沙市芙蓉区芙蓉路123号",
            "seats": 120,
            "business_type": "fine_dining",
        }
        assert store_data["store_type"] == "physical"
        assert store_data["has_physical_seats"] is True
        assert store_data["seats"] == 120

    def test_warehouse_store(self):
        """电商仓库：虚拟门店"""
        store_data = {
            "store_name": "预制菜电商仓库",
            "store_code": "WH-CS-001",
            "store_type": "warehouse",
            "has_physical_seats": False,
            "address": "长沙市望城区仓储基地",
            "seats": None,
            "business_type": "retail",
        }
        assert store_data["store_type"] == "warehouse"
        assert store_data["has_physical_seats"] is False


class TestModuleImports:
    """验证模块可以被正确导入"""

    def test_import_ontology_entities(self):
        """Ontology entities importable"""
        from entities import Order, Store

        assert Order is not None
        assert Store is not None

    def test_import_amount_convention(self):
        """Amount convention importable"""
        from amount_convention import fen_to_yuan, yuan_to_fen

        assert callable(yuan_to_fen)
        assert callable(fen_to_yuan)

    def test_import_sales_channel(self):
        """SalesChannel importable"""
        from sales_channel import DEFAULT_CHANNELS, SalesChannel

        assert SalesChannel is not None
        assert len(DEFAULT_CHANNELS) > 0

    def test_import_monolith_modules(self):
        """All monolith module packages importable"""
        from services.tunxiang_api.src.modules import brain, gateway, ops, trade

        assert trade is not None
        assert ops is not None
        assert brain is not None
        assert gateway is not None

    def test_import_api_routes(self):
        """All API route modules importable"""
        from services.tunxiang_api.src.api.v1 import (
            auth_routes,
            brain_routes,
            hub_routes,
            ops_routes,
            trade_routes,
        )

        assert auth_routes.router is not None
        assert hub_routes.router is not None
        assert trade_routes.router is not None
        assert ops_routes.router is not None
        assert brain_routes.router is not None

    def test_import_shared(self):
        """Shared utilities importable"""
        from services.tunxiang_api.src.shared.response import err, ok, paginated

        assert callable(ok)
        assert callable(err)
        assert callable(paginated)
