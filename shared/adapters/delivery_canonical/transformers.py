"""5 平台 transformer 实现

每个 transformer 只负责把平台原始 payload 映射到 CanonicalDeliveryOrder，
不做业务决策（状态流转 / 库存扣减等由上层 service 处理）。

支持的平台：
  · meituan     — 美团外卖 / 美团到店
  · eleme       — 饿了么
  · douyin      — 抖音外卖 / 抖音团购
  · xiaohongshu — 小红书团购 / 到店
  · wechat      — 微信小程序自营

实际部署时，各平台签名校验 / token 刷新等放在 adapter 层（shared/adapters/{meituan,
eleme,...}/*），本模块只处理结构化 payload。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from .base import (
    CanonicalDeliveryItem,
    CanonicalDeliveryOrder,
    CanonicalTransformer,
    TransformationError,
    compute_payload_sha256,
    hash_address,
    mask_phone,
    to_fen,
)
from .registry import register_transformer

# ─────────────────────────────────────────────────────────────
# 时间工具
# ─────────────────────────────────────────────────────────────


def _parse_ts(value: Any) -> Optional[datetime]:
    """容错解析时间戳：unix 秒 / 毫秒 / ISO 8601 / None"""
    if value is None or value == "" or value == 0:
        return None
    if isinstance(value, (int, float)):
        # 判断是否毫秒（>10^12）
        if value > 1e12:
            value = value / 1000
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        try:
            # ISO 格式 (YYYY-MM-DDTHH:MM:SS 或含时区)
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    return None


# ─────────────────────────────────────────────────────────────
# 美团
# ─────────────────────────────────────────────────────────────


class MeituanTransformer(CanonicalTransformer):
    """美团外卖 / 美团到店 transformer

    参考 payload 结构（美团开放平台）：
      {
        "orderId": "1234567",
        "appPoiCode": "SHOP001",
        "poiId": 12345,
        "status": 2,
        "orderTime": 1745000000,
        "deliveryTime": 1745003600,
        "totalPrice": 88.50,
        "originalPrice": 100.00,
        "shippingFee": 5.00,
        "poiReceiveDetail": {...},
        "recipientName": "张三",
        "recipientPhone": "13812345678",
        "recipientAddress": "长沙市...",
        "detail": [
          {"appFoodCode": "F001", "food_name": "鱼香肉丝", "quantity": 1,
           "price": 28.00, "food_discount": 2.00}
        ],
        "orderType": 1  // 1=delivery, 2=dine_in
      }
    """

    platform = "meituan"
    version = 1

    # 美团 status int → canonical
    STATUS_MAP = {
        0: "pending",
        1: "accepted",
        2: "preparing",
        4: "dispatched",
        8: "delivering",
        9: "delivered",
        10: "completed",
        50: "cancelled",
        51: "refunded",
    }

    ORDER_TYPE_MAP = {1: "delivery", 2: "dine_in", 3: "pickup"}

    def supports(self, raw: dict[str, Any]) -> bool:
        return "appPoiCode" in raw or "poiId" in raw

    def transform(
        self, raw: dict[str, Any], tenant_id: str
    ) -> CanonicalDeliveryOrder:
        order_id = str(raw.get("orderId") or raw.get("order_id") or "").strip()
        if not order_id:
            raise TransformationError("meituan: orderId 缺失")

        placed_at = _parse_ts(raw.get("orderTime") or raw.get("order_time"))
        if placed_at is None:
            raise TransformationError("meituan: orderTime 缺失或无法解析")

        status_raw = raw.get("status")
        canonical_status = self.STATUS_MAP.get(status_raw, "pending")
        order_type_raw = raw.get("orderType") or raw.get("order_type") or 1
        order_type = self.ORDER_TYPE_MAP.get(order_type_raw, "delivery")

        # 美团 payload 金额是元（浮点）
        total = to_fen(raw.get("totalPrice") or raw.get("total_price"))
        original = to_fen(raw.get("originalPrice") or raw.get("original_price"))
        discount = max(0, original - total) if original > total else 0
        shipping_fee = to_fen(raw.get("shippingFee") or raw.get("shipping_fee"))
        commission = to_fen(raw.get("commission") or 0)
        packaging = to_fen(raw.get("packageFee") or raw.get("package_fee") or 0)

        phone = raw.get("recipientPhone") or raw.get("recipient_phone")

        order = CanonicalDeliveryOrder(
            tenant_id=tenant_id,
            platform="meituan",
            platform_order_id=order_id,
            platform_sub_type=(
                "meituan_dine_in" if order_type == "dine_in"
                else "meituan_delivery"
            ),
            placed_at=placed_at,
            order_type=order_type,
            status=canonical_status,
            platform_status_raw=str(status_raw),
            customer_name=raw.get("recipientName") or raw.get("recipient_name"),
            customer_phone_masked=mask_phone(phone),
            customer_address=(
                raw.get("recipientAddress") or raw.get("recipient_address")
            ),
            customer_address_hash=hash_address(
                raw.get("recipientAddress") or raw.get("recipient_address")
            ),
            gross_amount_fen=original,
            discount_amount_fen=discount,
            platform_commission_fen=commission,
            delivery_fee_fen=shipping_fee,
            packaging_fee_fen=packaging,
            paid_amount_fen=total + shipping_fee,
            expected_delivery_at=_parse_ts(
                raw.get("deliveryTime") or raw.get("delivery_time")
            ),
            raw_payload=raw,
            payload_sha256=compute_payload_sha256(raw),
            platform_metadata={
                "appPoiCode": raw.get("appPoiCode"),
                "poiId": raw.get("poiId"),
                "poi_receive_detail": raw.get("poiReceiveDetail"),
            },
            canonical_version=self.version,
        )

        # items
        details = raw.get("detail") or raw.get("items") or []
        for idx, item in enumerate(details, start=1):
            try:
                unit_price = to_fen(item.get("price") or item.get("unit_price"))
                qty = int(item.get("quantity") or 1)
                discount_item = to_fen(
                    item.get("food_discount") or item.get("discount") or 0
                )
                order.items.append(
                    CanonicalDeliveryItem(
                        platform_sku_id=str(
                            item.get("appFoodCode") or item.get("sku_id") or ""
                        ) or None,
                        dish_name_platform=str(
                            item.get("food_name") or item.get("name") or ""
                        ),
                        quantity=qty,
                        unit_price_fen=unit_price,
                        subtotal_fen=unit_price * qty,
                        discount_amount_fen=discount_item,
                        line_no=idx,
                    )
                )
            except (ValueError, TypeError, TransformationError) as exc:
                order.add_transformation_error(
                    f"detail[{idx}]", item, f"item 解析失败: {exc}"
                )

        if status_raw not in self.STATUS_MAP:
            order.add_transformation_error(
                "status", status_raw,
                f"未知 meituan status {status_raw}，降级为 pending",
            )

        return order


# ─────────────────────────────────────────────────────────────
# 饿了么
# ─────────────────────────────────────────────────────────────


class ElemeTransformer(CanonicalTransformer):
    """饿了么 transformer

    参考 payload（饿了么开放平台）：
      {
        "id": "E20260423001",
        "shop_id": "P123",
        "activeAt": "2026-04-23T12:00:00+08:00",
        "deliverFee": 500,    // 分
        "totalPrice": 8850,   // 分
        "originalPrice": 10000,
        "groups": [
          {"type": "food", "items": [
            {"id": "sku1", "name": "鱼香肉丝", "quantity": 1,
             "price": 2800, "total": 2800}
          ]}
        ],
        "consigneeName": "李四",
        "consigneePhone": "13912345678",
        "consigneeAddress": "上海市...",
        "status": "VALID",
        "orderType": "delivery"
      }
    """

    platform = "eleme"
    version = 1

    STATUS_MAP = {
        "UNPROCESSED": "pending",
        "VALID": "accepted",
        "ACCEPTED": "accepted",
        "DELIVERED": "delivered",
        "COMPLETED": "completed",
        "REFUNDING": "pending",
        "SETTLED": "completed",
        "CANCELLED": "cancelled",
        "REFUND_SUCCESSFUL": "refunded",
        "INVALID": "cancelled",
    }

    def supports(self, raw: dict[str, Any]) -> bool:
        return "groups" in raw or "consigneePhone" in raw

    def transform(
        self, raw: dict[str, Any], tenant_id: str
    ) -> CanonicalDeliveryOrder:
        order_id = str(raw.get("id") or raw.get("orderId") or "").strip()
        if not order_id:
            raise TransformationError("eleme: id 缺失")

        placed_at = _parse_ts(
            raw.get("activeAt") or raw.get("active_at") or raw.get("orderTime")
        )
        if placed_at is None:
            raise TransformationError("eleme: activeAt 缺失或无法解析")

        status_raw = str(raw.get("status") or "")
        canonical_status = self.STATUS_MAP.get(status_raw, "pending")

        # 饿了么金额已是分（int）
        total = int(raw.get("totalPrice") or raw.get("total_price") or 0)
        original = int(raw.get("originalPrice") or raw.get("original_price") or total)
        deliver_fee = int(raw.get("deliverFee") or raw.get("deliver_fee") or 0)
        commission = int(raw.get("commission") or 0)
        packaging = int(raw.get("packageFee") or raw.get("package_fee") or 0)
        discount = max(0, original - total) if original > total else 0

        phone = raw.get("consigneePhone") or raw.get("consignee_phone")

        order = CanonicalDeliveryOrder(
            tenant_id=tenant_id,
            platform="eleme",
            platform_order_id=order_id,
            platform_sub_type="eleme_delivery",
            placed_at=placed_at,
            order_type=str(raw.get("orderType") or "delivery"),
            status=canonical_status,
            platform_status_raw=status_raw,
            customer_name=raw.get("consigneeName") or raw.get("consignee_name"),
            customer_phone_masked=mask_phone(phone),
            customer_address=(
                raw.get("consigneeAddress") or raw.get("consignee_address")
            ),
            customer_address_hash=hash_address(
                raw.get("consigneeAddress") or raw.get("consignee_address")
            ),
            gross_amount_fen=original,
            discount_amount_fen=discount,
            platform_commission_fen=commission,
            delivery_fee_fen=deliver_fee,
            packaging_fee_fen=packaging,
            paid_amount_fen=total + deliver_fee,
            raw_payload=raw,
            payload_sha256=compute_payload_sha256(raw),
            platform_metadata={
                "shop_id": raw.get("shop_id") or raw.get("shopId"),
            },
            canonical_version=self.version,
        )

        # items
        groups = raw.get("groups") or []
        line_idx = 1
        for grp in groups:
            for item in grp.get("items") or []:
                try:
                    unit_price = int(item.get("price") or 0)
                    qty = int(item.get("quantity") or 1)
                    order.items.append(
                        CanonicalDeliveryItem(
                            platform_sku_id=str(item.get("id") or "") or None,
                            dish_name_platform=str(item.get("name") or ""),
                            quantity=qty,
                            unit_price_fen=unit_price,
                            subtotal_fen=int(item.get("total") or unit_price * qty),
                            line_no=line_idx,
                        )
                    )
                    line_idx += 1
                except (ValueError, TypeError, TransformationError) as exc:
                    order.add_transformation_error(
                        f"groups.items[{line_idx}]", item, f"item 解析失败: {exc}"
                    )

        if status_raw not in self.STATUS_MAP:
            order.add_transformation_error(
                "status", status_raw,
                f"未知 eleme status {status_raw!r}，降级为 pending",
            )

        return order


# ─────────────────────────────────────────────────────────────
# 抖音
# ─────────────────────────────────────────────────────────────


class DouyinTransformer(CanonicalTransformer):
    """抖音外卖 / 抖音团购 transformer

    抖音的核心区别：
      · 团购核销（order_type=group_buy）占比大，需要显式标识
      · status 是 int，语义与美团相反
      · 时间字段是毫秒级 unix 时间戳

    参考 payload：
      {
        "order_id": "DY202604230001",
        "poi_id": "poi_xxx",
        "status": 4,
        "create_time": 1745000000000,  // ms
        "expected_time": 1745003600000,
        "origin_amount": 10000,  // 分
        "pay_amount": 8000,
        "platform_allowance": 500,  // 平台补贴
        "service_fee": 300,          // 平台抽佣
        "delivery_fee": 500,
        "receiver": {
          "name": "王五",
          "phone": "13712345678",
          "address": "广州市..."
        },
        "items": [{"sku_id": "D1", "name": "套餐A", "count": 1, "price": 5000}],
        "order_type": "takeout"  // takeout / group_buy / dine_in
      }
    """

    platform = "douyin"
    version = 1

    STATUS_MAP = {
        0: "pending",
        1: "accepted",
        2: "preparing",
        3: "dispatched",
        4: "delivering",
        5: "delivered",
        6: "completed",
        7: "cancelled",
        8: "refunded",
    }

    ORDER_TYPE_MAP = {
        "takeout": "delivery",
        "group_buy": "group_buy",
        "dine_in": "dine_in",
        "pickup": "pickup",
    }

    def supports(self, raw: dict[str, Any]) -> bool:
        return "poi_id" in raw and "origin_amount" in raw

    def transform(
        self, raw: dict[str, Any], tenant_id: str
    ) -> CanonicalDeliveryOrder:
        order_id = str(raw.get("order_id") or raw.get("orderId") or "").strip()
        if not order_id:
            raise TransformationError("douyin: order_id 缺失")

        placed_at = _parse_ts(
            raw.get("create_time") or raw.get("createTime")
        )
        if placed_at is None:
            raise TransformationError("douyin: create_time 缺失或无法解析")

        status_raw = raw.get("status")
        canonical_status = self.STATUS_MAP.get(status_raw, "pending")
        order_type_raw = str(raw.get("order_type") or "takeout")
        order_type = self.ORDER_TYPE_MAP.get(order_type_raw, "delivery")

        # 抖音金额已是分
        origin = int(raw.get("origin_amount") or 0)
        pay = int(raw.get("pay_amount") or origin)
        subsidy = int(raw.get("platform_allowance") or 0)
        service_fee = int(raw.get("service_fee") or 0)
        delivery = int(raw.get("delivery_fee") or 0)
        discount = max(0, origin - pay + subsidy)

        receiver = raw.get("receiver") or {}
        phone = receiver.get("phone")

        order = CanonicalDeliveryOrder(
            tenant_id=tenant_id,
            platform="douyin",
            platform_order_id=order_id,
            platform_sub_type=(
                "douyin_group_buy" if order_type == "group_buy"
                else "douyin_takeout"
            ),
            placed_at=placed_at,
            order_type=order_type,
            status=canonical_status,
            platform_status_raw=str(status_raw),
            customer_name=receiver.get("name"),
            customer_phone_masked=mask_phone(phone),
            customer_address=receiver.get("address"),
            customer_address_hash=hash_address(receiver.get("address")),
            gross_amount_fen=origin,
            discount_amount_fen=discount,
            platform_commission_fen=service_fee,
            platform_subsidy_fen=subsidy,
            delivery_fee_fen=delivery,
            paid_amount_fen=pay + delivery,
            expected_delivery_at=_parse_ts(
                raw.get("expected_time") or raw.get("expectedTime")
            ),
            raw_payload=raw,
            payload_sha256=compute_payload_sha256(raw),
            platform_metadata={
                "poi_id": raw.get("poi_id"),
                "order_type_raw": order_type_raw,
            },
            canonical_version=self.version,
        )

        for idx, item in enumerate(raw.get("items") or [], start=1):
            try:
                unit = int(item.get("price") or 0)
                qty = int(item.get("count") or item.get("quantity") or 1)
                order.items.append(
                    CanonicalDeliveryItem(
                        platform_sku_id=str(item.get("sku_id") or "") or None,
                        dish_name_platform=str(item.get("name") or ""),
                        quantity=qty,
                        unit_price_fen=unit,
                        subtotal_fen=unit * qty,
                        line_no=idx,
                    )
                )
            except (ValueError, TypeError, TransformationError) as exc:
                order.add_transformation_error(
                    f"items[{idx}]", item, f"item 解析失败: {exc}"
                )

        if status_raw not in self.STATUS_MAP:
            order.add_transformation_error(
                "status", status_raw,
                f"未知 douyin status {status_raw!r}，降级为 pending",
            )

        return order


# ─────────────────────────────────────────────────────────────
# 小红书
# ─────────────────────────────────────────────────────────────


class XiaohongshuTransformer(CanonicalTransformer):
    """小红书团购 / 到店核销 transformer（初步实现，平台对接待完善）

    小红书主要场景：团购核销。payload 示例：
      {
        "verify_code": "XHS123456",
        "shop_code": "SHOP001",
        "sku_name": "双人套餐",
        "verify_time": "2026-04-23T12:30:00+08:00",
        "origin_price": 19800,
        "pay_price": 14900,
        "user": {"nick": "美食家", "phone_last4": "5678"}
      }
    """

    platform = "xiaohongshu"
    version = 1

    def supports(self, raw: dict[str, Any]) -> bool:
        return "verify_code" in raw or "shop_code" in raw

    def transform(
        self, raw: dict[str, Any], tenant_id: str
    ) -> CanonicalDeliveryOrder:
        verify_code = str(raw.get("verify_code") or "").strip()
        if not verify_code:
            raise TransformationError("xiaohongshu: verify_code 缺失")

        placed_at = _parse_ts(
            raw.get("verify_time") or raw.get("create_time")
        )
        if placed_at is None:
            raise TransformationError("xiaohongshu: verify_time 缺失")

        origin = int(raw.get("origin_price") or 0)
        pay = int(raw.get("pay_price") or origin)
        discount = max(0, origin - pay)

        user = raw.get("user") or {}

        order = CanonicalDeliveryOrder(
            tenant_id=tenant_id,
            platform="xiaohongshu",
            platform_order_id=verify_code,
            platform_sub_type="xiaohongshu_group_buy",
            placed_at=placed_at,
            order_type="group_buy",
            status="completed",  # 核销即完成
            platform_status_raw="verified",
            customer_name=user.get("nick"),
            customer_phone_masked=(
                f"****{user['phone_last4']}" if user.get("phone_last4") else None
            ),
            gross_amount_fen=origin,
            discount_amount_fen=discount,
            paid_amount_fen=pay,
            completed_at=placed_at,
            raw_payload=raw,
            payload_sha256=compute_payload_sha256(raw),
            platform_metadata={"shop_code": raw.get("shop_code")},
            canonical_version=self.version,
        )

        # 单 SKU 核销：items 用 sku_name 填
        sku_name = raw.get("sku_name")
        if sku_name:
            order.items.append(
                CanonicalDeliveryItem(
                    platform_sku_id=raw.get("sku_id"),
                    dish_name_platform=str(sku_name),
                    quantity=int(raw.get("quantity") or 1),
                    unit_price_fen=pay,
                    subtotal_fen=pay,
                    line_no=1,
                )
            )

        return order


# ─────────────────────────────────────────────────────────────
# 微信小程序自营
# ─────────────────────────────────────────────────────────────


class WechatTransformer(CanonicalTransformer):
    """微信小程序自营 transformer

    来自 self_order_engine 的内部 payload（非真正的第三方推送），
    但放在 canonical 层使得上报分析保持一致。

    payload 示例：
      {
        "order_id": "WX20260423001",
        "store_id": "uuid",
        "user_openid": "oxxxxxx",
        "phone": "13512345678",
        "items": [{"dish_id": "uuid", "name": "鱼香肉丝", "qty": 1, "price_fen": 2800}],
        "total_fen": 2800,
        "placed_at": "2026-04-23T12:00:00+08:00",
        "order_type": "dine_in"
      }
    """

    platform = "wechat"
    version = 1

    def supports(self, raw: dict[str, Any]) -> bool:
        return "user_openid" in raw or raw.get("channel") == "wechat_miniapp"

    def transform(
        self, raw: dict[str, Any], tenant_id: str
    ) -> CanonicalDeliveryOrder:
        order_id = str(raw.get("order_id") or raw.get("orderId") or "").strip()
        if not order_id:
            raise TransformationError("wechat: order_id 缺失")

        placed_at = _parse_ts(raw.get("placed_at") or raw.get("create_time"))
        if placed_at is None:
            raise TransformationError("wechat: placed_at 缺失")

        total = int(raw.get("total_fen") or 0)
        phone = raw.get("phone")

        order = CanonicalDeliveryOrder(
            tenant_id=tenant_id,
            platform="wechat",
            platform_order_id=order_id,
            platform_sub_type="wechat_miniapp",
            placed_at=placed_at,
            store_id=raw.get("store_id"),
            order_type=str(raw.get("order_type") or "dine_in"),
            status=str(raw.get("status") or "pending"),
            customer_name=raw.get("customer_name"),
            customer_phone_masked=mask_phone(phone),
            customer_address=raw.get("address"),
            customer_address_hash=hash_address(raw.get("address")),
            gross_amount_fen=total,
            paid_amount_fen=total,
            raw_payload=raw,
            payload_sha256=compute_payload_sha256(raw),
            platform_metadata={
                "openid": raw.get("user_openid"),
                "channel": raw.get("channel") or "wechat_miniapp",
            },
            canonical_version=self.version,
        )

        for idx, item in enumerate(raw.get("items") or [], start=1):
            try:
                unit = int(item.get("price_fen") or item.get("price") or 0)
                qty = int(item.get("qty") or item.get("quantity") or 1)
                order.items.append(
                    CanonicalDeliveryItem(
                        platform_sku_id=str(item.get("dish_id") or "") or None,
                        internal_dish_id=str(item.get("dish_id") or "") or None,
                        dish_name_platform=str(item.get("name") or ""),
                        quantity=qty,
                        unit_price_fen=unit,
                        subtotal_fen=unit * qty,
                        line_no=idx,
                    )
                )
            except (ValueError, TypeError, TransformationError) as exc:
                order.add_transformation_error(
                    f"items[{idx}]", item, f"item 解析失败: {exc}"
                )

        return order


# ─────────────────────────────────────────────────────────────
# 默认注册
# ─────────────────────────────────────────────────────────────

register_transformer(MeituanTransformer())
register_transformer(ElemeTransformer())
register_transformer(DouyinTransformer())
register_transformer(XiaohongshuTransformer())
register_transformer(WechatTransformer())
