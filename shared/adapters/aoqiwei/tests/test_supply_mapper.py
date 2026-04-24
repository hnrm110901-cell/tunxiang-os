"""
奥琦玮供应链映射层单元测试

覆盖：
  - aoqiwei_supplier_to_unified
  - aoqiwei_purchase_order_to_unified
  - aoqiwei_dispatch_to_receiving

测试策略：
  - 字段映射正确性（happy path）
  - 边界值（空字段、None值、零金额）
  - 状态映射（0/1/2 → ordered/received/stocked）
  - 缺失必填字段时抛出 ValueError
  - 金额单位转换（分 → 元）
"""

from __future__ import annotations

import os
import sys

# 确保可以导入 supply_mapper（不依赖已安装包）
_tests_dir = os.path.dirname(__file__)
_src_dir = os.path.abspath(os.path.join(_tests_dir, "../src"))
_base_types_dir = os.path.abspath(os.path.join(_tests_dir, "../../base/src/types"))
for _p in [_src_dir, _base_types_dir]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest
from supply_mapper import (
    aoqiwei_dispatch_to_receiving,
    aoqiwei_purchase_order_to_unified,
    aoqiwei_supplier_to_unified,
)

TENANT_ID = "tenant-001"
STORE_ID = "store-001"


# ══════════════════════════════════════════════════════════════
# aoqiwei_supplier_to_unified
# ══════════════════════════════════════════════════════════════


class TestAoqiweiSupplierToUnified:
    def _make_raw(self, **overrides) -> dict:
        base = {
            "supplierCode": "SUP001",
            "supplierName": "测试供应商",
            "contactName": "张三",
            "contactPhone": "13800138000",
            "supplierAddress": "湖南省长沙市",
            "supplierStatus": 1,
            "categoryList": ["蔬菜", "水果"],
        }
        base.update(overrides)
        return base

    def test_full_fields_mapped_correctly(self):
        raw = self._make_raw()
        result = aoqiwei_supplier_to_unified(raw, TENANT_ID)

        assert result["external_id"] == "SUP001"
        assert result["source"] == "aoqiwei"
        assert result["name"] == "测试供应商"
        assert result["contact_name"] == "张三"
        assert result["contact_phone"] == "13800138000"
        assert result["address"] == "湖南省长沙市"
        assert result["is_active"] is True
        assert result["categories"] == ["蔬菜", "水果"]
        assert result["tenant_id"] == TENANT_ID

    def test_id_is_deterministic(self):
        """相同 supplierCode + tenant_id 生成相同 UUID"""
        r1 = aoqiwei_supplier_to_unified(self._make_raw(), TENANT_ID)
        r2 = aoqiwei_supplier_to_unified(self._make_raw(), TENANT_ID)
        assert r1["id"] == r2["id"]

    def test_different_tenant_produces_different_id(self):
        r1 = aoqiwei_supplier_to_unified(self._make_raw(), "tenant-A")
        r2 = aoqiwei_supplier_to_unified(self._make_raw(), "tenant-B")
        assert r1["id"] != r2["id"]

    def test_supplier_status_0_is_inactive(self):
        raw = self._make_raw(supplierStatus=0)
        result = aoqiwei_supplier_to_unified(raw, TENANT_ID)
        assert result["is_active"] is False

    def test_supplier_status_1_is_active(self):
        raw = self._make_raw(supplierStatus=1)
        result = aoqiwei_supplier_to_unified(raw, TENANT_ID)
        assert result["is_active"] is True

    def test_supplier_status_none_defaults_to_active(self):
        raw = self._make_raw(supplierStatus=None)
        result = aoqiwei_supplier_to_unified(raw, TENANT_ID)
        assert result["is_active"] is True

    def test_supplier_status_missing_defaults_to_active(self):
        raw = self._make_raw()
        del raw["supplierStatus"]
        result = aoqiwei_supplier_to_unified(raw, TENANT_ID)
        assert result["is_active"] is True

    def test_category_list_as_comma_string(self):
        raw = self._make_raw(categoryList="蔬菜,水果,肉类")
        result = aoqiwei_supplier_to_unified(raw, TENANT_ID)
        assert result["categories"] == ["蔬菜", "水果", "肉类"]

    def test_category_list_empty(self):
        raw = self._make_raw(categoryList=[])
        result = aoqiwei_supplier_to_unified(raw, TENANT_ID)
        assert result["categories"] == []

    def test_category_list_none(self):
        raw = self._make_raw(categoryList=None)
        result = aoqiwei_supplier_to_unified(raw, TENANT_ID)
        assert result["categories"] == []

    def test_optional_fields_none(self):
        """联系人/电话/地址为 None 时映射为空字符串，不抛异常"""
        raw = self._make_raw(contactName=None, contactPhone=None, supplierAddress=None)
        result = aoqiwei_supplier_to_unified(raw, TENANT_ID)
        assert result["contact_name"] == ""
        assert result["contact_phone"] == ""
        assert result["address"] == ""

    def test_missing_supplier_code_raises_value_error(self):
        raw = self._make_raw(supplierCode=None)
        with pytest.raises(ValueError, match="supplierCode"):
            aoqiwei_supplier_to_unified(raw, TENANT_ID)

    def test_empty_supplier_code_raises_value_error(self):
        raw = self._make_raw(supplierCode="")
        with pytest.raises(ValueError, match="supplierCode"):
            aoqiwei_supplier_to_unified(raw, TENANT_ID)

    def test_missing_supplier_name_raises_value_error(self):
        raw = self._make_raw(supplierName=None)
        with pytest.raises(ValueError, match="supplierName"):
            aoqiwei_supplier_to_unified(raw, TENANT_ID)

    def test_empty_tenant_id_raises_value_error(self):
        raw = self._make_raw()
        with pytest.raises(ValueError, match="tenant_id"):
            aoqiwei_supplier_to_unified(raw, "")


# ══════════════════════════════════════════════════════════════
# aoqiwei_purchase_order_to_unified
# ══════════════════════════════════════════════════════════════


class TestAoqiweiPurchaseOrderToUnified:
    def _make_raw(self, **overrides) -> dict:
        base = {
            "orderNo": "PO2026031200001",
            "depotCode": "DC001",
            "supplierCode": "SUP001",
            "orderDate": "2026-03-12",
            "totalAmount": 158600,  # 1586.00 元（分）
            "status": 1,
            "goodList": [
                {
                    "goodCode": "G001",
                    "goodName": "里脊肉",
                    "qty": 10,
                    "unit": "kg",
                    "price": 8800,  # 88.00 元（分）
                },
                {
                    "goodCode": "G002",
                    "goodName": "西红柿",
                    "qty": 20,
                    "unit": "kg",
                    "price": 350,  # 3.50 元（分）
                },
            ],
        }
        base.update(overrides)
        return base

    def test_full_fields_mapped_correctly(self):
        raw = self._make_raw()
        result = aoqiwei_purchase_order_to_unified(raw, TENANT_ID, STORE_ID)

        assert result["external_id"] == "PO2026031200001"
        assert result["source"] == "aoqiwei"
        assert result["store_id"] == STORE_ID
        assert result["supplier_id"] == "SUP001"
        assert result["order_date"] == "2026-03-12"
        assert result["tenant_id"] == TENANT_ID
        assert result["depot_code"] == "DC001"

    def test_total_amount_converted_from_fen_to_yuan(self):
        raw = self._make_raw(totalAmount=158600)
        result = aoqiwei_purchase_order_to_unified(raw, TENANT_ID, STORE_ID)
        assert result["total_amount"] == pytest.approx(1586.0)

    def test_status_0_maps_to_ordered(self):
        raw = self._make_raw(status=0)
        result = aoqiwei_purchase_order_to_unified(raw, TENANT_ID, STORE_ID)
        assert result["status"] == "ordered"

    def test_status_1_maps_to_received(self):
        raw = self._make_raw(status=1)
        result = aoqiwei_purchase_order_to_unified(raw, TENANT_ID, STORE_ID)
        assert result["status"] == "received"

    def test_status_2_maps_to_stocked(self):
        raw = self._make_raw(status=2)
        result = aoqiwei_purchase_order_to_unified(raw, TENANT_ID, STORE_ID)
        assert result["status"] == "stocked"

    def test_unknown_status_defaults_to_ordered(self):
        raw = self._make_raw(status=99)
        result = aoqiwei_purchase_order_to_unified(raw, TENANT_ID, STORE_ID)
        assert result["status"] == "ordered"

    def test_status_none_defaults_to_ordered(self):
        raw = self._make_raw(status=None)
        result = aoqiwei_purchase_order_to_unified(raw, TENANT_ID, STORE_ID)
        assert result["status"] == "ordered"

    def test_items_mapped_correctly(self):
        raw = self._make_raw()
        result = aoqiwei_purchase_order_to_unified(raw, TENANT_ID, STORE_ID)
        items = result["items"]

        assert len(items) == 2
        assert items[0]["good_code"] == "G001"
        assert items[0]["good_name"] == "里脊肉"
        assert items[0]["quantity"] == pytest.approx(10.0)
        assert items[0]["unit"] == "kg"
        assert items[0]["unit_price"] == pytest.approx(88.0)
        assert items[0]["subtotal"] == pytest.approx(880.0)

        assert items[1]["good_code"] == "G002"
        assert items[1]["unit_price"] == pytest.approx(3.5)

    def test_empty_good_list(self):
        raw = self._make_raw(goodList=[])
        result = aoqiwei_purchase_order_to_unified(raw, TENANT_ID, STORE_ID)
        assert result["items"] == []

    def test_good_list_none(self):
        raw = self._make_raw(goodList=None)
        result = aoqiwei_purchase_order_to_unified(raw, TENANT_ID, STORE_ID)
        assert result["items"] == []

    def test_item_with_none_price(self):
        raw = self._make_raw(
            goodList=[
                {
                    "goodCode": "G003",
                    "goodName": "豆腐",
                    "qty": 5,
                    "unit": "块",
                    "price": None,
                }
            ]
        )
        result = aoqiwei_purchase_order_to_unified(raw, TENANT_ID, STORE_ID)
        assert result["items"][0]["unit_price"] == pytest.approx(0.0)

    def test_item_with_none_qty(self):
        raw = self._make_raw(
            goodList=[
                {
                    "goodCode": "G003",
                    "goodName": "豆腐",
                    "qty": None,
                    "unit": "块",
                    "price": 100,
                }
            ]
        )
        result = aoqiwei_purchase_order_to_unified(raw, TENANT_ID, STORE_ID)
        assert result["items"][0]["quantity"] == pytest.approx(0.0)

    def test_total_amount_zero(self):
        raw = self._make_raw(totalAmount=0)
        result = aoqiwei_purchase_order_to_unified(raw, TENANT_ID, STORE_ID)
        assert result["total_amount"] == pytest.approx(0.0)

    def test_total_amount_none(self):
        raw = self._make_raw(totalAmount=None)
        result = aoqiwei_purchase_order_to_unified(raw, TENANT_ID, STORE_ID)
        assert result["total_amount"] == pytest.approx(0.0)

    def test_id_is_deterministic(self):
        r1 = aoqiwei_purchase_order_to_unified(self._make_raw(), TENANT_ID, STORE_ID)
        r2 = aoqiwei_purchase_order_to_unified(self._make_raw(), TENANT_ID, STORE_ID)
        assert r1["id"] == r2["id"]

    def test_missing_order_no_raises_value_error(self):
        raw = self._make_raw(orderNo=None)
        with pytest.raises(ValueError, match="orderNo"):
            aoqiwei_purchase_order_to_unified(raw, TENANT_ID, STORE_ID)

    def test_empty_order_no_raises_value_error(self):
        raw = self._make_raw(orderNo="")
        with pytest.raises(ValueError, match="orderNo"):
            aoqiwei_purchase_order_to_unified(raw, TENANT_ID, STORE_ID)

    def test_empty_tenant_id_raises_value_error(self):
        raw = self._make_raw()
        with pytest.raises(ValueError, match="tenant_id"):
            aoqiwei_purchase_order_to_unified(raw, "", STORE_ID)

    def test_empty_store_id_raises_value_error(self):
        raw = self._make_raw()
        with pytest.raises(ValueError, match="store_id"):
            aoqiwei_purchase_order_to_unified(raw, TENANT_ID, "")


# ══════════════════════════════════════════════════════════════
# aoqiwei_dispatch_to_receiving
# ══════════════════════════════════════════════════════════════


class TestAoqiweiDispatchToReceiving:
    def _make_raw(self, **overrides) -> dict:
        base = {
            "dispatchOrderNo": "DO20260312001",
            "shopCode": "SHOP001",
            "dispatchDate": "2026-03-12",
            "goodList": [
                {
                    "goodCode": "G001",
                    "goodName": "里脊肉",
                    "qty": 10,
                    "unit": "kg",
                },
                {
                    "goodCode": "G002",
                    "goodName": "西红柿",
                    "qty": 20,
                    "unit": "kg",
                },
            ],
        }
        base.update(overrides)
        return base

    def test_full_fields_mapped_correctly(self):
        raw = self._make_raw()
        result = aoqiwei_dispatch_to_receiving(raw, TENANT_ID, STORE_ID)

        assert result["external_dispatch_no"] == "DO20260312001"
        assert result["source"] == "aoqiwei"
        assert result["tenant_id"] == TENANT_ID
        assert result["store_id"] == STORE_ID
        assert result["shop_code"] == "SHOP001"
        assert result["dispatch_date"] == "2026-03-12"
        assert result["item_count"] == 2

    def test_items_mapped_for_receiving_service(self):
        """items 格式应兼容 receiving_service.create_receiving() 的期望格式"""
        raw = self._make_raw()
        result = aoqiwei_dispatch_to_receiving(raw, TENANT_ID, STORE_ID)
        items = result["items"]

        assert len(items) == 2
        item = items[0]
        # receiving_service 约定的字段
        assert item["ingredient_id"] == "G001"
        assert item["name"] == "里脊肉"
        assert item["ordered_qty"] == pytest.approx(10.0)
        assert item["received_qty"] == pytest.approx(10.0)  # 默认实收 = 应收
        assert item["quality"] == "pass"
        assert item["unit"] == "kg"

    def test_empty_good_list(self):
        raw = self._make_raw(goodList=[])
        result = aoqiwei_dispatch_to_receiving(raw, TENANT_ID, STORE_ID)
        assert result["items"] == []
        assert result["item_count"] == 0

    def test_good_list_none(self):
        raw = self._make_raw(goodList=None)
        result = aoqiwei_dispatch_to_receiving(raw, TENANT_ID, STORE_ID)
        assert result["items"] == []

    def test_item_with_none_qty(self):
        raw = self._make_raw(
            goodList=[
                {
                    "goodCode": "G003",
                    "goodName": "豆腐",
                    "qty": None,
                    "unit": "块",
                }
            ]
        )
        result = aoqiwei_dispatch_to_receiving(raw, TENANT_ID, STORE_ID)
        assert result["items"][0]["ordered_qty"] == pytest.approx(0.0)

    def test_item_with_none_good_code(self):
        raw = self._make_raw(
            goodList=[
                {
                    "goodCode": None,
                    "goodName": "未知货品",
                    "qty": 5,
                    "unit": "kg",
                }
            ]
        )
        result = aoqiwei_dispatch_to_receiving(raw, TENANT_ID, STORE_ID)
        assert result["items"][0]["ingredient_id"] == ""

    def test_item_with_none_unit(self):
        raw = self._make_raw(
            goodList=[
                {
                    "goodCode": "G001",
                    "goodName": "里脊肉",
                    "qty": 5,
                    "unit": None,
                }
            ]
        )
        result = aoqiwei_dispatch_to_receiving(raw, TENANT_ID, STORE_ID)
        assert result["items"][0]["unit"] == ""

    def test_missing_dispatch_no_raises_value_error(self):
        raw = self._make_raw(dispatchOrderNo=None)
        with pytest.raises(ValueError, match="dispatchOrderNo"):
            aoqiwei_dispatch_to_receiving(raw, TENANT_ID, STORE_ID)

    def test_empty_dispatch_no_raises_value_error(self):
        raw = self._make_raw(dispatchOrderNo="")
        with pytest.raises(ValueError, match="dispatchOrderNo"):
            aoqiwei_dispatch_to_receiving(raw, TENANT_ID, STORE_ID)

    def test_empty_tenant_id_raises_value_error(self):
        raw = self._make_raw()
        with pytest.raises(ValueError, match="tenant_id"):
            aoqiwei_dispatch_to_receiving(raw, "", STORE_ID)

    def test_empty_store_id_raises_value_error(self):
        raw = self._make_raw()
        with pytest.raises(ValueError, match="store_id"):
            aoqiwei_dispatch_to_receiving(raw, TENANT_ID, "")

    def test_shop_code_none_defaults_to_empty_string(self):
        raw = self._make_raw(shopCode=None)
        result = aoqiwei_dispatch_to_receiving(raw, TENANT_ID, STORE_ID)
        assert result["shop_code"] == ""

    def test_dispatch_date_none_defaults_to_empty_string(self):
        raw = self._make_raw(dispatchDate=None)
        result = aoqiwei_dispatch_to_receiving(raw, TENANT_ID, STORE_ID)
        assert result["dispatch_date"] == ""
