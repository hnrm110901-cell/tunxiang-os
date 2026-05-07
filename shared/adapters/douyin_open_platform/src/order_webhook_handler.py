"""抖音团购 Webhook 核销事件处理器

抖音生活服务开放平台推送字段参考（核销事件）：
  event: "order.verify"
  data:
    order_id: str
    verify_code: str          # 券码
    shop_id: str              # 抖音门店 ID
    user_phone: str           # 顾客手机号（已脱敏，核销时可获取）
    open_id: str              # 顾客抖音 openid
    pay_amount: int           # 实付金额（分）
    sku_list: list[dict]      # [{sku_id, sku_name, count, price}]
    verify_time: int          # 核销时间戳（秒）

使用方：
    handler = DouyinOrderWebhookHandler(binding_service, tenant_id)
    result = await handler.handle(raw_payload, db)
"""

import uuid
from typing import Any

import structlog

logger = structlog.get_logger()


class DouyinOrderWebhookHandler:
    """处理抖音团购推送事件，核销时调用 PlatformBindingService"""

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
            payload: 抖音推送的原始 JSON 字典
            db: AsyncSession

        Returns:
            {"ok": True, "event": str, "data": dict}
        """
        event: str = payload.get("event", "")
        log = logger.bind(
            platform="douyin",
            event=event,
            order_id=payload.get("data", {}).get("order_id"),
            tenant_id=str(self._tenant_id),
        )
        log.info("douyin_webhook_received")

        if event == "order.verify":
            data = await self._handle_order_verified(payload.get("data", payload), db, log)
        else:
            log.info("douyin_webhook_ignored", reason="not_verify_event")
            data = {"action": "ignored"}

        return {"ok": True, "event": event, "data": data}

    # ─── 事件处理 ───

    async def _handle_order_verified(
        self,
        event_data: dict[str, Any],
        db: Any,
        log: Any,
    ) -> dict[str, Any]:
        """核销事件：解析字段，调用 PlatformBindingService 绑定 Golden ID"""
        sku_list = event_data.get("sku_list", [])

        order_data = {
            "order_no": str(event_data.get("order_id", event_data.get("verify_code", ""))),
            "amount_fen": int(event_data.get("pay_amount", 0)),
            "store_id": str(event_data.get("shop_id", "")),
            "phone": str(event_data.get("user_phone", "")) or None,
            "douyin_openid": str(event_data.get("open_id", "")) or None,
            "items": [
                {
                    "sku_id": str(sku.get("sku_id", "")),
                    "name": str(sku.get("sku_name", "")),
                    "quantity": int(sku.get("count", 1)),
                    "price_fen": int(sku.get("price", 0)),
                }
                for sku in sku_list
            ],
        }

        log.info(
            "douyin_order_verified",
            order_no=order_data["order_no"],
            amount_fen=order_data["amount_fen"],
            has_phone=bool(order_data["phone"]),
            has_openid=bool(order_data["douyin_openid"]),
        )

        result = await self._svc.bind_douyin_order(
            order_data=order_data,
            tenant_id=self._tenant_id,
            db=db,
        )
        return result
