"""美团外卖订单 Webhook 事件处理器

事件类型：
  - order_paid      顾客下单并支付（通知接单）
  - order_verified  到店核销（触发 Golden ID 绑定）

美团推送字段参考（核销事件）：
  event_type, order_id, day_seq, status,
  recipient_phone, meituan_user_id, openid,
  order_total_price (分), detail (JSON 字符串), app_poi_code

使用方：
    handler = MeituanOrderWebhookHandler(binding_service, tenant_id)
    result = await handler.handle(raw_payload, db)
"""
import uuid
from typing import Any

import structlog

logger = structlog.get_logger()

# 美团核销状态码（order_verified 对应 status=5 已完成 / 自定义核销事件）
_VERIFIED_STATUSES = {5, 9}   # 5=已完成, 9=核销（部分平台用此值）


class MeituanOrderWebhookHandler:
    """处理美团外卖推送事件，核销时调用 PlatformBindingService"""

    def __init__(self, binding_service: Any, tenant_id: uuid.UUID) -> None:
        """
        Args:
            binding_service: PlatformBindingService 实例
            tenant_id: 租户 UUID
        """
        self._svc = binding_service
        self._tenant_id = tenant_id

    async def handle(
        self,
        payload: dict[str, Any],
        db: Any,  # AsyncSession
    ) -> dict[str, Any]:
        """统一事件入口

        Args:
            payload: 美团推送的原始 JSON 字典
            db: AsyncSession

        Returns:
            {"ok": True, "event_type": str, "data": dict}
        """
        event_type: str = payload.get("event_type", "")
        log = logger.bind(
            platform="meituan",
            event_type=event_type,
            order_id=payload.get("order_id"),
            tenant_id=str(self._tenant_id),
        )
        log.info("meituan_webhook_received")

        if event_type == "order_paid":
            data = await self._handle_order_paid(payload, log)
        elif event_type == "order_verified":
            data = await self._handle_order_verified(payload, db, log)
        else:
            # 未知事件类型：核销状态码兜底判断
            status = int(payload.get("status", 0))
            if status in _VERIFIED_STATUSES:
                data = await self._handle_order_verified(payload, db, log)
            else:
                log.info("meituan_webhook_ignored", reason="unknown_event_type")
                data = {"action": "ignored"}

        return {"ok": True, "event_type": event_type, "data": data}

    # ─── 事件处理 ───

    async def _handle_order_paid(
        self,
        payload: dict[str, Any],
        log: Any,
    ) -> dict[str, Any]:
        """下单支付事件：记录日志，暂不触发绑定（核销时才确认消费）"""
        log.info(
            "meituan_order_paid",
            order_id=payload.get("order_id"),
            amount_fen=payload.get("order_total_price"),
        )
        return {
            "action": "received",
            "order_id": str(payload.get("order_id", "")),
        }

    async def _handle_order_verified(
        self,
        payload: dict[str, Any],
        db: Any,
        log: Any,
    ) -> dict[str, Any]:
        """核销事件：解析订单字段，调用 PlatformBindingService 绑定 Golden ID"""
        import json as _json

        # 解析商品明细
        detail_raw = payload.get("detail", "[]")
        try:
            items = _json.loads(detail_raw) if isinstance(detail_raw, str) else detail_raw
        except (_json.JSONDecodeError, TypeError):
            items = []

        order_data = {
            "order_no": str(payload.get("order_id", payload.get("day_seq", ""))),
            "amount_fen": int(payload.get("order_total_price", 0)),
            "store_id": str(payload.get("app_poi_code", "")),
            "phone": str(payload.get("recipient_phone", "")) or None,
            "meituan_user_id": str(payload.get("meituan_user_id", "")) or None,
            "meituan_openid": str(payload.get("openid", "")) or None,
            "items": [
                {
                    "sku_id": str(item.get("app_food_code", "")),
                    "name": str(item.get("food_name", "")),
                    "quantity": int(item.get("quantity", 1)),
                    "price_fen": int(item.get("price", 0)),
                }
                for item in items
            ],
        }

        log.info(
            "meituan_order_verified",
            order_no=order_data["order_no"],
            amount_fen=order_data["amount_fen"],
            has_phone=bool(order_data["phone"]),
            has_meituan_id=bool(order_data["meituan_user_id"]),
        )

        result = await self._svc.bind_meituan_order(
            order_data=order_data,
            tenant_id=self._tenant_id,
            db=db,
        )
        return result
