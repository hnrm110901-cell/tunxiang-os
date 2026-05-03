"""test_channel_adapter — VC-1.1 ChannelsECAdapter 全方法覆盖

Tier 2 覆盖：
  1. parse_order — 视频号小店原始 JSON → 解析后字典
  2. to_internal_order — 解析后字典 → 内部持久化订单
  3. map_status — 6 种视频号状态码 → 内部状态
  4. mock_order — 模拟订单字段完整性
"""

from __future__ import annotations

import os
import sys
import types
import uuid

_TESTS_DIR = os.path.dirname(__file__)
_SRC_DIR = os.path.abspath(os.path.join(_TESTS_DIR, ".."))
_ROOT_DIR = os.path.abspath(os.path.join(_TESTS_DIR, "..", "..", "..", ".."))

for _p in [_SRC_DIR, _ROOT_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _ensure_pkg(name: str, path: str) -> None:
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = [path]
        mod.__package__ = name
        sys.modules[name] = mod


_ensure_pkg("src", _SRC_DIR)
_ensure_pkg("src.services", os.path.join(_SRC_DIR, "services"))
_ensure_pkg("src.schemas", os.path.join(_SRC_DIR, "schemas"))
_ensure_pkg("src.api", os.path.join(_SRC_DIR, "api"))

import pytest  # noqa: E402
from src.services.channel_adapter import ChannelsECAdapter  # noqa: E402


# ─── 测试数据 ──────────────────────────────────────────────────────────────────

TENANT_ID = "00000000-0000-0000-0000-000000000001"
STORE_ID = "store_001"

RAW_ORDER_PAID = {
    "order_id": "ec_202605010001",
    "product_infos": [
        {
            "product_id": "prod_001",
            "product_name": "招牌水煮鱼",
            "count": 1,
            "price": 6800,
            "img": "https://mmbiz.qpic.cn/example/fish.jpg",
        },
        {
            "product_id": "prod_002",
            "product_name": "酸菜鱼套餐",
            "count": 2,
            "price": 9800,
            "img": "https://example.com/sour_fish.jpg",
        },
    ],
    "total_price": 26400,
    "pay_amount": 26400,
    "freight": 0,
    "discounted_price": 0,
    "status": "2",
    "openid": "mock_openid_001",
    "unionid": "mock_unionid_001",
    "receiver_info": {
        "receiver_name": "张先生",
        "receiver_phone": "138****8888",
        "address_detail": "湖南省长沙市岳麓区梅溪湖街道100号",
    },
    "remark": "请尽快发货",
    "create_time": "2026-05-01T12:00:00+00:00",
    "update_time": "2026-05-01T12:05:00+00:00",
}

RAW_ORDER_PENDING = {
    "order_id": "ec_202605010002",
    "product_infos": [
        {
            "product_id": "prod_003",
            "product_name": "凉拌黄瓜",
            "count": 1,
            "price": 1800,
            "img": "",
        },
    ],
    "total_price": 1800,
    "pay_amount": 0,
    "freight": 500,
    "discounted_price": 0,
    "status": "1",
    "openid": "mock_openid_002",
    "unionid": "",
    "receiver_info": {},
    "remark": "",
    "create_time": "2026-05-01T13:00:00+00:00",
    "update_time": "2026-05-01T13:00:00+00:00",
}

RAW_ORDER_REFUNDED = {
    "order_id": "ec_202604300001",
    "product_infos": [
        {
            "product_id": "prod_001",
            "product_name": "招牌水煮鱼",
            "count": 1,
            "price": 6800,
            "img": "",
        },
    ],
    "total_price": 6800,
    "pay_amount": 6800,
    "freight": 0,
    "discounted_price": 0,
    "status": "200",
    "openid": "mock_openid_001",
    "unionid": "",
    "receiver_info": {
        "receiver_name": "张先生",
        "receiver_phone": "138****8888",
        "address_detail": "湖南省长沙市",
    },
    "remark": "质量问题退款",
    "create_time": "2026-04-30T10:00:00+00:00",
    "update_time": "2026-04-30T11:00:00+00:00",
}

RAW_ORDER_EMPTY_ITEMS = {
    "order_id": "ec_202604300002",
    "product_infos": [],
    "total_price": 0,
    "pay_amount": 0,
    "freight": 0,
    "discounted_price": 0,
    "status": "5",
    "openid": "",
    "unionid": "",
    "receiver_info": {},
    "remark": "",
    "create_time": "2026-04-30T09:00:00+00:00",
    "update_time": "2026-04-30T09:00:00+00:00",
}


class TestMapStatus:
    """状态码映射 6 种用例"""

    def test_pending_payment(self):
        assert ChannelsECAdapter.map_status("1") == "pending_payment"

    def test_paid(self):
        assert ChannelsECAdapter.map_status("2") == "paid"

    def test_preparing(self):
        assert ChannelsECAdapter.map_status("3") == "preparing"

    def test_completed(self):
        assert ChannelsECAdapter.map_status("4") == "completed"

    def test_cancelled(self):
        assert ChannelsECAdapter.map_status("5") == "cancelled"

    def test_refunded(self):
        assert ChannelsECAdapter.map_status("200") == "refunded"

    def test_unknown_status_defaults_to_pending_payment(self):
        assert ChannelsECAdapter.map_status("999") == "pending_payment"
        assert ChannelsECAdapter.map_status("") == "pending_payment"


class TestParseOrder:
    """parse_order 从原始 JSON → 解析字典"""

    def test_parse_paid_order(self):
        parsed = ChannelsECAdapter.parse_order(RAW_ORDER_PAID)
        assert parsed["channel_order_id"] == "ec_202605010001"
        assert parsed["channel"] == "channels_ec"
        assert parsed["status"] == "paid"
        assert parsed["total_fen"] == 26400
        assert parsed["pay_amount_fen"] == 26400
        assert parsed["freight_fen"] == 0
        assert parsed["openid"] == "mock_openid_001"
        assert parsed["unionid"] == "mock_unionid_001"
        assert len(parsed["items"]) == 2

        item = parsed["items"][0]
        assert item["sku_id"] == "prod_001"
        assert item["name"] == "招牌水煮鱼"
        assert item["quantity"] == 1
        assert item["price_fen"] == 6800

        item2 = parsed["items"][1]
        assert item2["sku_id"] == "prod_002"
        assert item2["name"] == "酸菜鱼套餐"
        assert item2["quantity"] == 2
        assert item2["price_fen"] == 9800

    def test_parse_pending_order_with_freight(self):
        parsed = ChannelsECAdapter.parse_order(RAW_ORDER_PENDING)
        assert parsed["status"] == "pending_payment"
        assert parsed["freight_fen"] == 500
        assert parsed["total_fen"] == 1800
        assert parsed["pay_amount_fen"] == 0
        assert len(parsed["items"]) == 1

    def test_parse_refunded_order(self):
        parsed = ChannelsECAdapter.parse_order(RAW_ORDER_REFUNDED)
        assert parsed["status"] == "refunded"
        assert parsed["remark"] == "质量问题退款"

    def test_parse_empty_items(self):
        parsed = ChannelsECAdapter.parse_order(RAW_ORDER_EMPTY_ITEMS)
        assert parsed["status"] == "cancelled"
        assert parsed["items"] == []
        assert parsed["openid"] == ""

    def test_parse_receiver_info_when_empty(self):
        parsed = ChannelsECAdapter.parse_order(RAW_ORDER_PENDING)
        assert parsed["receiver"]["name"] == ""
        assert parsed["receiver"]["phone"] == ""
        assert parsed["receiver"]["address"] == ""

    def test_parse_alternative_field_names(self):
        """兼容 product_id/real_price/thumb_img 等备选字段名"""
        raw = {
            "order_id": "ec_alt_001",
            "items": [
                {
                    "product_id": "p1",
                    "name": "测试商品",
                    "quantity": 2,
                    "real_price": 5000,
                    "thumb_img": "https://example.com/thumb.jpg",
                },
            ],
            "total_price": 10000,
            "pay_amount": 10000,
            "freight": 0,
            "discounted_price": 0,
            "status": "2",
            "openid": "",
            "unionid": "",
            "receiver_info": {},
            "remark": "",
            "create_time": "",
            "update_time": "",
        }
        parsed = ChannelsECAdapter.parse_order(raw)
        assert len(parsed["items"]) == 1
        assert parsed["items"][0]["sku_id"] == "p1"
        assert parsed["items"][0]["name"] == "测试商品"
        assert parsed["items"][0]["quantity"] == 2
        assert parsed["items"][0]["price_fen"] == 5000
        assert parsed["items"][0]["img_url"] == "https://example.com/thumb.jpg"


class TestToInternalOrder:
    """to_internal_order 从解析字典 → 内部持久化订单"""

    def test_to_internal_order_generates_ids(self):
        parsed = ChannelsECAdapter.parse_order(RAW_ORDER_PAID)
        internal = ChannelsECAdapter.to_internal_order(parsed, TENANT_ID, STORE_ID)

        assert internal["internal_order_id"] is not None
        assert uuid.UUID(internal["internal_order_id"], version=4)  # 合法的 UUID4

        assert internal["internal_order_no"].startswith("EC")
        assert internal["internal_order_no"].endswith("0001".upper())  # channel_order_id 后 6 位

        assert internal["tenant_id"] == TENANT_ID
        assert internal["store_id"] == STORE_ID
        assert internal["channel"] == "channels_ec"
        assert internal["channel_order_id"] == "ec_202605010001"
        assert internal["total_fen"] == 26400
        assert internal["pay_amount_fen"] == 26400

    def test_to_internal_order_preserves_items_and_receiver(self):
        parsed = ChannelsECAdapter.parse_order(RAW_ORDER_PAID)
        internal = ChannelsECAdapter.to_internal_order(parsed, TENANT_ID, STORE_ID)

        assert len(internal["items"]) == 2
        assert internal["receiver"]["name"] == "张先生"
        assert internal["receiver"]["address"] == "湖南省长沙市岳麓区梅溪湖街道100号"

    def test_to_internal_order_with_empty_data(self):
        parsed = ChannelsECAdapter.parse_order(RAW_ORDER_EMPTY_ITEMS)
        internal = ChannelsECAdapter.to_internal_order(parsed, TENANT_ID, STORE_ID)

        assert internal["items"] == []
        assert internal["receiver"]["name"] == ""
        assert internal["receiver"]["phone"] == ""


class TestMockOrder:
    """mock_order 字段完整性"""

    def test_mock_order_has_all_required_fields(self):
        order = ChannelsECAdapter.mock_order()
        assert order["order_id"].startswith("ec_mock_")
        assert len(order["product_infos"]) == 2
        assert order["total_price"] > 0
        assert order["pay_amount"] > 0
        assert order["status"] == "2"
        assert order["openid"] != ""
        assert order["receiver_info"]["receiver_name"] != ""

    def test_mock_order_roundtrip(self):
        """mock_order 生成的数据可以通过 parse_order 正确解析"""
        order = ChannelsECAdapter.mock_order("store_002")
        parsed = ChannelsECAdapter.parse_order(order)
        internal = ChannelsECAdapter.to_internal_order(parsed, TENANT_ID, "store_002")

        assert internal["store_id"] == "store_002"
        assert internal["channel"] == "channels_ec"
        assert len(internal["items"]) == 2
        assert internal["total_fen"] > 0
        assert internal["pay_amount_fen"] > 0


class TestEdgeCases:
    """边界与异常输入"""

    def test_missing_fields_default_to_zero_and_empty(self):
        raw = {
            "order_id": "ec_minimal_001",
            "status": "2",
        }
        parsed = ChannelsECAdapter.parse_order(raw)
        assert parsed["channel_order_id"] == "ec_minimal_001"
        assert parsed["total_fen"] == 0
        assert parsed["items"] == []
        assert parsed["freight_fen"] == 0
        assert parsed["openid"] == ""

    def test_string_amount_coerced_to_int(self):
        raw = {
            "order_id": "ec_str_amount",
            "product_infos": [
                {"product_id": "p1", "product_name": "测试", "count": "1", "price": "5000", "img": ""},
            ],
            "total_price": "5000",
            "pay_amount": "5000",
            "freight": "0",
            "discounted_price": "0",
            "status": "2",
            "openid": "",
            "unionid": "",
            "receiver_info": {},
            "remark": "",
            "create_time": "",
            "update_time": "",
        }
        parsed = ChannelsECAdapter.parse_order(raw)
        assert parsed["total_fen"] == 5000
        assert parsed["items"][0]["price_fen"] == 5000
        assert parsed["items"][0]["quantity"] == 1

    def test_different_tenant_and_store(self):
        parsed = ChannelsECAdapter.parse_order(RAW_ORDER_PAID)
        internal = ChannelsECAdapter.to_internal_order(parsed, TENANT_ID, "store_099")
        assert internal["tenant_id"] == TENANT_ID
        assert internal["store_id"] == "store_099"

    def test_internal_order_no_format(self):
        parsed = ChannelsECAdapter.parse_order({"order_id": "abc123xyz789", "status": "1"})
        internal = ChannelsECAdapter.to_internal_order(parsed, TENANT_ID, STORE_ID)
        # 内部单号以 EC 开头，以 channel_order_id 后 6 位大写结尾
        assert internal["internal_order_no"].startswith("EC")
        assert internal["internal_order_no"].endswith("Z789")  # "xyz789" 后6位大写
