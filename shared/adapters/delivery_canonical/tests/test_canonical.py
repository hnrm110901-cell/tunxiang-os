"""Sprint E1 — canonical_delivery 转换器测试

覆盖：
  · base：CanonicalDeliveryOrder / CanonicalDeliveryItem 合法性 + 自动 net 计算
  · 工具：compute_payload_sha256 / mask_phone / hash_address / to_fen / _parse_ts
  · registry：register / get / transform / 非法 platform
  · 5 个 transformer：
      · meituan：外卖 + 到店 + 未知 status 降级 + item 解析错误 + 金额
      · eleme：VALID→accepted 映射 + 分单位金额
      · douyin：毫秒时间戳 + group_buy 识别 + platform_subsidy
      · xiaohongshu：核销场景 + status=completed
      · wechat：内部订单 + internal_dish_id 回填
  · v285 迁移静态断言

执行：
  pytest shared/adapters/delivery_canonical/tests/ -v
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.adapters.delivery_canonical import (  # noqa: E402
    CanonicalDeliveryItem,
    CanonicalDeliveryOrder,
    TransformationError,
    get_transformer,
    list_supported_platforms,
    transform,
)
from shared.adapters.delivery_canonical.base import (  # noqa: E402
    compute_payload_sha256,
    hash_address,
    mask_phone,
    to_fen,
)
from shared.adapters.delivery_canonical.transformers import (  # noqa: E402
    DouyinTransformer,
    ElemeTransformer,
    MeituanTransformer,
    _parse_ts,
)

TENANT = "00000000-0000-0000-0000-000000000001"


# ─────────────────────────────────────────────────────────────
# 1. 工具函数
# ─────────────────────────────────────────────────────────────


class TestUtilities:
    def test_compute_payload_sha256_stable(self):
        p1 = {"b": 2, "a": 1}
        p2 = {"a": 1, "b": 2}
        assert compute_payload_sha256(p1) == compute_payload_sha256(p2)

    def test_compute_payload_sha256_differs(self):
        assert compute_payload_sha256({"a": 1}) != compute_payload_sha256({"a": 2})

    def test_mask_phone_standard(self):
        assert mask_phone("13812345678") == "138****5678"

    def test_mask_phone_short(self):
        assert mask_phone("1234") == "****"

    def test_mask_phone_none(self):
        assert mask_phone(None) is None

    def test_mask_phone_with_dashes(self):
        assert mask_phone("138-1234-5678") == "138****5678"

    def test_hash_address_stable(self):
        a1 = hash_address("长沙市芙蓉区韶山路")
        a2 = hash_address("长沙市芙蓉区韶山路")
        assert a1 == a2 and len(a1) == 64

    def test_hash_address_strips_case(self):
        assert hash_address("  Hello  ") == hash_address("hello")

    def test_hash_address_none(self):
        assert hash_address(None) is None

    def test_to_fen_float(self):
        assert to_fen(88.50) == 8850

    def test_to_fen_string(self):
        assert to_fen("88.50") == 8850

    def test_to_fen_int_treated_as_fen(self):
        # 已是整数 → 视为 fen 原样返回
        assert to_fen(8850) == 8850

    def test_to_fen_none_zero(self):
        assert to_fen(None) == 0
        assert to_fen("") == 0
        assert to_fen("bad") == 0

    def test_parse_ts_seconds_unix(self):
        assert _parse_ts(1745000000) is not None
        assert _parse_ts(1745000000).tzinfo is not None

    def test_parse_ts_millis_unix(self):
        ts = _parse_ts(1745000000000)  # 13 digits → ms
        assert ts is not None
        # 秒和毫秒应该解析到同一个时间
        assert ts == _parse_ts(1745000000)

    def test_parse_ts_iso(self):
        assert _parse_ts("2026-04-23T12:00:00+08:00") is not None

    def test_parse_ts_iso_z(self):
        assert _parse_ts("2026-04-23T12:00:00Z") is not None

    def test_parse_ts_none_empty(self):
        assert _parse_ts(None) is None
        assert _parse_ts("") is None
        assert _parse_ts(0) is None

    def test_parse_ts_bad_string(self):
        assert _parse_ts("not a date") is None


# ─────────────────────────────────────────────────────────────
# 2. CanonicalDeliveryOrder / Item
# ─────────────────────────────────────────────────────────────


class TestCanonicalModels:
    def _placed_at(self) -> datetime:
        return datetime(2026, 4, 23, 12, 0, tzinfo=timezone.utc)

    def test_item_auto_computes_subtotal(self):
        item = CanonicalDeliveryItem(
            platform_sku_id="x",
            dish_name_platform="鱼香肉丝",
            quantity=3,
            unit_price_fen=2800,
            subtotal_fen=0,  # 留空
        )
        assert item.subtotal_fen == 8400

    def test_item_auto_computes_total(self):
        item = CanonicalDeliveryItem(
            platform_sku_id="x",
            dish_name_platform="x",
            quantity=1,
            unit_price_fen=5000,
            subtotal_fen=5000,
            discount_amount_fen=500,
        )
        assert item.total_fen == 4500

    def test_item_rejects_zero_quantity(self):
        with pytest.raises(TransformationError, match="quantity"):
            CanonicalDeliveryItem(
                platform_sku_id="x",
                dish_name_platform="x",
                quantity=0,
                unit_price_fen=100,
                subtotal_fen=0,
            )

    def test_order_rejects_bad_platform(self):
        with pytest.raises(TransformationError, match="platform"):
            CanonicalDeliveryOrder(
                tenant_id=TENANT,
                platform="unknown_platform",
                platform_order_id="x",
                placed_at=self._placed_at(),
            )

    def test_order_rejects_bad_status(self):
        with pytest.raises(TransformationError, match="status"):
            CanonicalDeliveryOrder(
                tenant_id=TENANT,
                platform="meituan",
                platform_order_id="x",
                placed_at=self._placed_at(),
                status="nonsense",
            )

    def test_order_rejects_empty_order_id(self):
        with pytest.raises(TransformationError, match="platform_order_id"):
            CanonicalDeliveryOrder(
                tenant_id=TENANT,
                platform="meituan",
                platform_order_id="",
                placed_at=self._placed_at(),
            )

    def test_order_auto_computes_net_amount(self):
        order = CanonicalDeliveryOrder(
            tenant_id=TENANT,
            platform="meituan",
            platform_order_id="x",
            placed_at=self._placed_at(),
            gross_amount_fen=10000,
            discount_amount_fen=1500,
            platform_commission_fen=800,
            platform_subsidy_fen=300,
        )
        # 10000 - 1500 - 800 + 300 = 8000
        assert order.net_amount_fen == 8000

    def test_order_auto_computes_sha256(self):
        order = CanonicalDeliveryOrder(
            tenant_id=TENANT,
            platform="meituan",
            platform_order_id="x",
            placed_at=self._placed_at(),
            raw_payload={"a": 1},
        )
        assert order.payload_sha256 is not None
        assert len(order.payload_sha256) == 64

    def test_order_transformation_errors_append(self):
        order = CanonicalDeliveryOrder(
            tenant_id=TENANT,
            platform="meituan",
            platform_order_id="x",
            placed_at=self._placed_at(),
        )
        order.add_transformation_error("status", 999, "unknown")
        assert len(order.transformation_errors) == 1
        assert order.transformation_errors[0]["field"] == "status"

    def test_order_to_insert_params_contract(self):
        order = CanonicalDeliveryOrder(
            tenant_id=TENANT,
            platform="meituan",
            platform_order_id="x",
            placed_at=self._placed_at(),
        )
        params = order.to_insert_params()
        # 关键字段必须存在（供 INSERT 语句消费）
        for key in (
            "tenant_id",
            "platform",
            "platform_order_id",
            "placed_at",
            "payload_sha256",
            "raw_payload",
            "canonical_version",
        ):
            assert key in params


# ─────────────────────────────────────────────────────────────
# 3. Registry
# ─────────────────────────────────────────────────────────────


class TestRegistry:
    def test_list_supported_platforms_has_5(self):
        supported = list_supported_platforms()
        for p in ("meituan", "eleme", "douyin", "xiaohongshu", "wechat"):
            assert p in supported

    def test_get_transformer_returns_correct(self):
        assert isinstance(get_transformer("meituan"), MeituanTransformer)
        assert isinstance(get_transformer("eleme"), ElemeTransformer)
        assert isinstance(get_transformer("douyin"), DouyinTransformer)

    def test_get_transformer_unknown_raises(self):
        with pytest.raises(TransformationError, match="找不到"):
            get_transformer("not_exist")


# ─────────────────────────────────────────────────────────────
# 4. MeituanTransformer
# ─────────────────────────────────────────────────────────────


class TestMeituanTransformer:
    def _payload(self, **overrides) -> dict:
        payload = {
            "orderId": "MT20260423001",
            "appPoiCode": "SHOP001",
            "poiId": 12345,
            "status": 2,
            "orderTime": 1776945600,
            "deliveryTime": 1776949200,
            "totalPrice": 88.50,
            "originalPrice": 100.00,
            "shippingFee": 5.00,
            "recipientName": "张三",
            "recipientPhone": "13812345678",
            "recipientAddress": "长沙市芙蓉区韶山路 1 号",
            "detail": [
                {
                    "appFoodCode": "F001",
                    "food_name": "鱼香肉丝",
                    "quantity": 1,
                    "price": 28.00,
                    "food_discount": 2.00,
                },
                {
                    "appFoodCode": "F002",
                    "food_name": "宫保鸡丁",
                    "quantity": 2,
                    "price": 32.00,
                },
            ],
            "orderType": 1,
        }
        payload.update(overrides)
        return payload

    def test_basic_transformation(self):
        order = transform("meituan", self._payload(), tenant_id=TENANT)
        assert order.platform == "meituan"
        assert order.platform_order_id == "MT20260423001"
        assert order.status == "preparing"
        assert order.order_type == "delivery"
        assert order.platform_sub_type == "meituan_delivery"
        assert order.gross_amount_fen == 10000
        assert order.paid_amount_fen == 8850 + 500  # total + shipping
        # discount = original - total = 10000 - 8850 = 1150
        assert order.discount_amount_fen == 1150
        assert len(order.items) == 2
        assert order.items[0].dish_name_platform == "鱼香肉丝"
        assert order.items[0].unit_price_fen == 2800
        assert order.items[1].subtotal_fen == 6400  # 32 * 2 * 100

    def test_dine_in_sub_type(self):
        order = transform(
            "meituan",
            self._payload(orderType=2),
            tenant_id=TENANT,
        )
        assert order.order_type == "dine_in"
        assert order.platform_sub_type == "meituan_dine_in"

    def test_unknown_status_degrades_with_warning(self):
        order = transform(
            "meituan",
            self._payload(status=999),
            tenant_id=TENANT,
        )
        assert order.status == "pending"  # 降级
        error_fields = [e["field"] for e in order.transformation_errors]
        assert "status" in error_fields

    def test_missing_order_id_raises(self):
        with pytest.raises(TransformationError, match="orderId"):
            transform("meituan", self._payload(orderId=""), tenant_id=TENANT)

    def test_phone_masked(self):
        order = transform("meituan", self._payload(), tenant_id=TENANT)
        assert order.customer_phone_masked == "138****5678"

    def test_address_hashed(self):
        order = transform("meituan", self._payload(), tenant_id=TENANT)
        assert order.customer_address_hash is not None
        assert len(order.customer_address_hash) == 64

    def test_supports_detects_meituan_payload(self):
        t = MeituanTransformer()
        assert t.supports({"appPoiCode": "x"}) is True
        assert t.supports({"poiId": 1}) is True
        assert t.supports({"order_id": "x"}) is False


# ─────────────────────────────────────────────────────────────
# 5. ElemeTransformer
# ─────────────────────────────────────────────────────────────


class TestElemeTransformer:
    def _payload(self, **overrides) -> dict:
        payload = {
            "id": "E20260423001",
            "shop_id": "P123",
            "activeAt": "2026-04-23T12:00:00+08:00",
            "deliverFee": 500,
            "totalPrice": 8850,
            "originalPrice": 10000,
            "status": "VALID",
            "consigneeName": "李四",
            "consigneePhone": "13912345678",
            "consigneeAddress": "上海市浦东新区",
            "groups": [
                {
                    "type": "food",
                    "items": [
                        {
                            "id": "sku1",
                            "name": "鱼香肉丝",
                            "quantity": 1,
                            "price": 2800,
                            "total": 2800,
                        },
                        {
                            "id": "sku2",
                            "name": "蛋花汤",
                            "quantity": 2,
                            "price": 1500,
                            "total": 3000,
                        },
                    ],
                }
            ],
        }
        payload.update(overrides)
        return payload

    def test_basic_transformation(self):
        order = transform("eleme", self._payload(), tenant_id=TENANT)
        assert order.platform == "eleme"
        assert order.platform_order_id == "E20260423001"
        assert order.status == "accepted"
        assert order.gross_amount_fen == 10000
        assert order.delivery_fee_fen == 500
        assert len(order.items) == 2

    def test_status_map(self):
        for status_in, status_out in [
            ("UNPROCESSED", "pending"),
            ("COMPLETED", "completed"),
            ("CANCELLED", "cancelled"),
            ("REFUND_SUCCESSFUL", "refunded"),
        ]:
            order = transform(
                "eleme", self._payload(status=status_in), tenant_id=TENANT
            )
            assert order.status == status_out

    def test_unknown_status_degrades(self):
        order = transform(
            "eleme", self._payload(status="FUTURE_STATUS"), tenant_id=TENANT
        )
        assert order.status == "pending"
        assert any(
            e["field"] == "status" for e in order.transformation_errors
        )

    def test_missing_id_raises(self):
        with pytest.raises(TransformationError, match="id"):
            transform("eleme", self._payload(id=""), tenant_id=TENANT)

    def test_supports_detects_eleme(self):
        t = ElemeTransformer()
        assert t.supports({"groups": [], "id": "x"}) is True
        assert t.supports({"consigneePhone": "x"}) is True


# ─────────────────────────────────────────────────────────────
# 6. DouyinTransformer
# ─────────────────────────────────────────────────────────────


class TestDouyinTransformer:
    def _payload(self, **overrides) -> dict:
        payload = {
            "order_id": "DY20260423001",
            "poi_id": "poi_xxx",
            "status": 4,
            "create_time": 1776945600000,  # ms
            "expected_time": 1776949200000,
            "origin_amount": 10000,
            "pay_amount": 8000,
            "platform_allowance": 500,
            "service_fee": 300,
            "delivery_fee": 500,
            "receiver": {
                "name": "王五",
                "phone": "13712345678",
                "address": "广州市",
            },
            "items": [
                {"sku_id": "D1", "name": "套餐A", "count": 1, "price": 5000},
                {"sku_id": "D2", "name": "饮料", "count": 3, "price": 1000},
            ],
            "order_type": "takeout",
        }
        payload.update(overrides)
        return payload

    def test_basic_transformation(self):
        order = transform("douyin", self._payload(), tenant_id=TENANT)
        assert order.platform == "douyin"
        assert order.status == "delivering"
        assert order.order_type == "delivery"
        assert order.platform_sub_type == "douyin_takeout"
        assert order.gross_amount_fen == 10000
        assert order.platform_subsidy_fen == 500
        assert order.platform_commission_fen == 300

    def test_group_buy_recognized(self):
        order = transform(
            "douyin",
            self._payload(order_type="group_buy"),
            tenant_id=TENANT,
        )
        assert order.order_type == "group_buy"
        assert order.platform_sub_type == "douyin_group_buy"

    def test_millisecond_timestamp_parsed(self):
        order = transform("douyin", self._payload(), tenant_id=TENANT)
        # 1776945600 秒 = 2026-04-23 12:00 UTC
        assert order.placed_at.year == 2026
        assert order.placed_at.month == 4
        assert order.placed_at.day == 23

    def test_items_parsed(self):
        order = transform("douyin", self._payload(), tenant_id=TENANT)
        assert len(order.items) == 2
        assert order.items[1].subtotal_fen == 3000

    def test_missing_create_time_raises(self):
        with pytest.raises(TransformationError, match="create_time"):
            transform(
                "douyin", self._payload(create_time=None), tenant_id=TENANT
            )


# ─────────────────────────────────────────────────────────────
# 7. XiaohongshuTransformer
# ─────────────────────────────────────────────────────────────


class TestXiaohongshuTransformer:
    def _payload(self, **overrides) -> dict:
        payload = {
            "verify_code": "XHS123456",
            "shop_code": "SHOP001",
            "sku_name": "双人套餐",
            "verify_time": "2026-04-23T12:30:00+08:00",
            "origin_price": 19800,
            "pay_price": 14900,
            "user": {"nick": "美食家", "phone_last4": "5678"},
        }
        payload.update(overrides)
        return payload

    def test_basic_transformation(self):
        order = transform("xiaohongshu", self._payload(), tenant_id=TENANT)
        assert order.platform == "xiaohongshu"
        assert order.order_type == "group_buy"
        assert order.status == "completed"
        assert order.gross_amount_fen == 19800
        assert order.paid_amount_fen == 14900
        assert order.discount_amount_fen == 4900
        assert len(order.items) == 1

    def test_phone_last4_format(self):
        order = transform("xiaohongshu", self._payload(), tenant_id=TENANT)
        assert order.customer_phone_masked == "****5678"

    def test_completed_at_set(self):
        order = transform("xiaohongshu", self._payload(), tenant_id=TENANT)
        assert order.completed_at is not None

    def test_missing_verify_code_raises(self):
        with pytest.raises(TransformationError, match="verify_code"):
            transform(
                "xiaohongshu",
                self._payload(verify_code=""),
                tenant_id=TENANT,
            )


# ─────────────────────────────────────────────────────────────
# 8. WechatTransformer
# ─────────────────────────────────────────────────────────────


class TestWechatTransformer:
    def _payload(self, **overrides) -> dict:
        payload = {
            "order_id": "WX20260423001",
            "store_id": "00000000-0000-0000-0000-000000000099",
            "user_openid": "oxxxxxx",
            "phone": "13512345678",
            "items": [
                {
                    "dish_id": "00000000-0000-0000-0000-000000000111",
                    "name": "鱼香肉丝",
                    "qty": 1,
                    "price_fen": 2800,
                }
            ],
            "total_fen": 2800,
            "placed_at": "2026-04-23T12:00:00+08:00",
            "order_type": "dine_in",
        }
        payload.update(overrides)
        return payload

    def test_basic_transformation(self):
        order = transform("wechat", self._payload(), tenant_id=TENANT)
        assert order.platform == "wechat"
        assert order.platform_sub_type == "wechat_miniapp"
        assert order.order_type == "dine_in"
        assert order.store_id == "00000000-0000-0000-0000-000000000099"

    def test_internal_dish_id_populated(self):
        order = transform("wechat", self._payload(), tenant_id=TENANT)
        assert order.items[0].internal_dish_id == (
            "00000000-0000-0000-0000-000000000111"
        )

    def test_missing_order_id_raises(self):
        with pytest.raises(TransformationError, match="order_id"):
            transform("wechat", self._payload(order_id=""), tenant_id=TENANT)


# ─────────────────────────────────────────────────────────────
# 9. v285 迁移静态断言
# ─────────────────────────────────────────────────────────────


class TestV285Migration:
    @pytest.fixture
    def migration_source(self) -> str:
        path = (
            ROOT
            / "shared"
            / "db-migrations"
            / "versions"
            / "v285_canonical_delivery_orders.py"
        )
        return path.read_text(encoding="utf-8")

    def test_revision_chain(self, migration_source):
        assert 'revision = "v285_canonical_delivery"' in migration_source
        assert 'down_revision = "v284_coupon_materialized_views"' in migration_source

    def test_table_canonical_delivery_orders(self, migration_source):
        assert "canonical_delivery_orders" in migration_source
        assert "canonical_delivery_items" in migration_source

    def test_all_5_platforms_in_check(self, migration_source):
        for p in ("meituan", "eleme", "douyin", "xiaohongshu", "wechat", "other"):
            assert f"'{p}'" in migration_source

    def test_all_status_states_in_check(self, migration_source):
        for s in (
            "pending",
            "accepted",
            "preparing",
            "dispatched",
            "delivering",
            "delivered",
            "completed",
            "cancelled",
            "refunded",
            "error",
        ):
            assert f"'{s}'" in migration_source

    def test_all_order_types_in_check(self, migration_source):
        for ot in ("delivery", "pickup", "dine_in", "group_buy"):
            assert f"'{ot}'" in migration_source

    def test_idempotent_unique_constraints(self, migration_source):
        assert "ux_canonical_delivery_platform_order" in migration_source
        assert "ux_canonical_delivery_payload_sha" in migration_source
        assert "ux_canonical_delivery_no" in migration_source

    def test_enables_rls_on_both_tables(self, migration_source):
        assert (
            "ALTER TABLE canonical_delivery_orders ENABLE ROW LEVEL SECURITY"
            in migration_source
        )
        assert (
            "ALTER TABLE canonical_delivery_items ENABLE ROW LEVEL SECURITY"
            in migration_source
        )
        assert "app.tenant_id" in migration_source

    def test_has_raw_payload_sha256_fields(self, migration_source):
        assert "raw_payload" in migration_source
        assert "payload_sha256" in migration_source
        assert "canonical_version" in migration_source
