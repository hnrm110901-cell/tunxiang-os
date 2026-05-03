"""视频号小店渠道适配器 — VC-1.1

将微信视频号小店（Channels EC）的订单格式转换为屯象内部订单格式。
所有金额单位：分（fen）。

微信文档：https://developers.weixin.qq.com/doc/channels/API/order/
"""

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger()

# 视频号订单状态映射
_CHANNELS_EC_STATUS_MAP: dict[str, str] = {
    "1": "pending_payment",  # 待支付
    "2": "paid",             # 已支付
    "3": "preparing",        # 已发货/备货中
    "4": "completed",        # 已完成
    "5": "cancelled",        # 已取消
    "200": "refunded",       # 已退款
}


def _gen_internal_order_id() -> str:
    return str(uuid.uuid4())


def _gen_internal_order_no(channel_order_id: str) -> str:
    now = datetime.now(timezone.utc)
    return f"EC{now.strftime('%Y%m%d%H%M%S')}{channel_order_id[-6:].upper()}"


class ChannelsECAdapter:
    """视频号小店渠道适配器

    将微信 Channels EC 的订单推送转换为屯象 tx-trade 内部订单格式。
    Mock 模式：当 CHANNELS_EC_APP_ID 未配置时返回示例数据。
    """

    def __init__(self) -> None:
        self._enabled = True  # 始终可用，回调在 Gateway 层做鉴权

    # ── 状态映射 ──

    @classmethod
    def map_status(cls, channels_status: str) -> str:
        """将视频号订单状态映射为内部状态。"""
        return _CHANNELS_EC_STATUS_MAP.get(channels_status, "pending_payment")

    # ── 订单转换 ──

    @classmethod
    def parse_order(cls, raw: dict[str, Any]) -> dict[str, Any]:
        """将视频号小店订单 JSON 转换为屯象内部订单结构。

        Args:
            raw: 微信视频号小店订单回调数据

        Returns:
            内部订单字典
        """
        order_id = raw.get("order_id", "")
        items_raw = raw.get("product_infos", raw.get("items", []))
        items: list[dict[str, Any]] = []
        for item in items_raw:
            items.append({
                "sku_id": item.get("sku_id", item.get("product_id", "")),
                "name": item.get("product_name", item.get("name", "")),
                "quantity": int(item.get("count", item.get("quantity", 1))),
                "price_fen": int(item.get("price", item.get("real_price", 0))),
                "img_url": item.get("img", item.get("thumb_img", "")),
            })

        amount_fen = int(raw.get("total_price", raw.get("pay_amount", 0)))
        status_str = str(raw.get("status", "1"))

        return {
            "channel_order_id": order_id,
            "channel": "channels_ec",
            "status": cls.map_status(status_str),
            "status_code": status_str,
            "items": items,
            "total_fen": amount_fen,
            "pay_amount_fen": int(raw.get("pay_amount", amount_fen)),
            "freight_fen": int(raw.get("freight", 0)),
            "discount_fen": int(raw.get("discounted_price", 0)),
            "openid": raw.get("openid", ""),
            "unionid": raw.get("unionid", ""),
            "receiver": {
                "name": raw.get("receiver_info", {}).get("receiver_name", ""),
                "phone": raw.get("receiver_info", {}).get("receiver_phone", ""),
                "address": raw.get("receiver_info", {}).get("address_detail", ""),
            },
            "remark": raw.get("remark", ""),
            "created_at": raw.get("create_time", datetime.now(timezone.utc).isoformat()),
            "updated_at": raw.get("update_time", datetime.now(timezone.utc).isoformat()),
        }

    @classmethod
    def to_internal_order(
        cls,
        parsed: dict[str, Any],
        tenant_id: str,
        store_id: str,
    ) -> dict[str, Any]:
        """将解析后的订单转换为可持久化的内部订单。

        Args:
            parsed: parse_order() 的输出
            tenant_id: 租户 ID
            store_id: 门店 ID

        Returns:
            内部订单数据（含 internal_order_id / internal_order_no）
        """
        internal_id = _gen_internal_order_id()
        internal_no = _gen_internal_order_no(parsed["channel_order_id"])
        now = datetime.now(timezone.utc).isoformat()

        return {
            "internal_order_id": internal_id,
            "internal_order_no": internal_no,
            "tenant_id": tenant_id,
            "store_id": store_id,
            "channel": "channels_ec",
            "channel_order_id": parsed["channel_order_id"],
            "status": parsed["status"],
            "items": parsed["items"],
            "total_fen": parsed["total_fen"],
            "pay_amount_fen": parsed["pay_amount_fen"],
            "freight_fen": parsed["freight_fen"],
            "discount_fen": parsed["discount_fen"],
            "openid": parsed["openid"],
            "receiver": parsed["receiver"],
            "remark": parsed["remark"],
            "created_at": parsed["created_at"],
            "updated_at": now,
            "synced_at": now,
        }

    @classmethod
    def mock_order(cls, store_id: str = "store_001") -> dict[str, Any]:
        """生成模拟视频号订单（开发测试用）。"""
        now = datetime.now(timezone.utc).isoformat()
        return {
            "order_id": f"ec_mock_{uuid.uuid4().hex[:8]}",
            "product_infos": [
                {
                    "product_id": "prod_001",
                    "product_name": "招牌水煮鱼（视频号专享）",
                    "count": 1,
                    "price": 6800,
                    "img": "https://mmbiz.qpic.cn/example/fish.jpg",
                },
                {
                    "product_id": "prod_002",
                    "product_name": "酸菜鱼套餐",
                    "count": 2,
                    "price": 9800,
                    "img": "https://mmbiz.qpic.io/example/sour_fish.jpg",
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
            "create_time": now,
            "update_time": now,
        }
