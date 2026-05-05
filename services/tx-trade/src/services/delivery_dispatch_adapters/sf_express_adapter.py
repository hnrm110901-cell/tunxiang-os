"""顺丰同城 SfExpressAdapter — 顺丰同城急送

接入文档：https://open.sf-express.com/
认证：app_key + app_secret，HMAC-SHA256 签名
"""

from __future__ import annotations

import hashlib
import hmac
import time

import structlog

from .base import (
    BaseDeliveryDispatchAdapter,
    DispatchOrderInput,
    DispatchResult,
    RiderLocation,
    gen_mock_provider_order_id,
    now_utc,
)

logger = structlog.get_logger(__name__)


class SfExpressAdapter(BaseDeliveryDispatchAdapter):
    provider = "shunfeng"

    BASE_URL = "https://sci-open-isre.sf-express.com/openapi/sfintracity"

    def _sign(self, body: str, timestamp: str) -> str:
        """顺丰同城签名：HMAC-SHA256(secret, body + timestamp)"""
        secret = self.config.app_secret or ""
        msg = (body + timestamp).encode("utf-8")
        return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()

    async def _call_api(self, action: str, payload: dict) -> dict:
        """统一 HTTP 入口（mock）"""
        timestamp = str(int(time.time() * 1000))
        # 真实实现：httpx.post(url, json=payload, headers={"X-Sign": _sign, "X-Timestamp": ts})
        logger.info(
            "sf_express.api_call_mock",
            action=action,
            shop_id=self.config.shop_no,
            ts=timestamp,
        )
        return {
            "errorCode": "S0000",
            "errorMsg": "OK",
            "msgData": {
                "sfOrderId": gen_mock_provider_order_id(self.provider),
                "estimatedMinutes": payload.get("estimated_minutes", 30),
            },
        }

    async def dispatch(self, order: DispatchOrderInput) -> DispatchResult:
        if not (self.config.app_key and self.config.shop_no):
            return DispatchResult(
                success=False,
                provider_order_id=None,
                estimated_minutes=order.estimated_minutes,
                error_code="CONFIG_INCOMPLETE",
                error_message="顺丰同城配置缺少 app_key 或 shop_no",
            )

        payload = {
            "merchantOrderId": order.dispatch_id,
            "shopId": self.config.shop_no,
            "deliveryAddress": order.delivery_address,
            "receiverLat": order.delivery_lat,
            "receiverLng": order.delivery_lng,
            "distance": order.distance_meters,
            "deliveryFeeFen": order.delivery_fee_fen,
            "tipFen": order.tip_fen,
            "estimated_minutes": order.estimated_minutes,
            "callbackUrl": self.config.callback_url or "",
            "phone": order.customer_phone or "",
        }
        result = await self._call_api("order/create", payload)
        if result.get("errorCode") != "S0000":
            return DispatchResult(
                success=False,
                provider_order_id=None,
                estimated_minutes=order.estimated_minutes,
                raw=result,
                error_code=result.get("errorCode"),
                error_message=result.get("errorMsg", "顺丰同城下单失败"),
            )

        msg_data = result.get("msgData") or {}
        return DispatchResult(
            success=True,
            provider_order_id=msg_data.get("sfOrderId"),
            estimated_minutes=int(msg_data.get("estimatedMinutes") or order.estimated_minutes),
            raw=result,
        )

    async def cancel(self, provider_order_id: str, reason: str) -> bool:
        result = await self._call_api(
            "order/cancel",
            {"sfOrderId": provider_order_id, "cancelReason": reason},
        )
        return result.get("errorCode") == "S0000"

    async def query_location(self, provider_order_id: str) -> RiderLocation:
        result = await self._call_api(
            "order/query",
            {"sfOrderId": provider_order_id},
        )
        # mock fake position
        seed = int(hashlib.md5(provider_order_id.encode("utf-8")).hexdigest()[:6], 16)
        return RiderLocation(
            rider_lat=28.2282 + (seed % 80) * 0.00012,
            rider_lng=112.9388 + (seed % 80) * 0.00012,
            rider_name=f"顺丰骑士{seed % 1000:03d}",
            rider_phone="139****" + str(seed % 10000).zfill(4),
            updated_at=now_utc(),
            raw=result,
        )

    async def notify_pickup_ready(
        self,
        provider_order_id: str,
        dispatch_id: str,
    ) -> bool:
        """顺丰同城提供商家备餐完成通知接口"""
        result = await self._call_api(
            "order/mealReady",
            {"sfOrderId": provider_order_id, "merchantOrderId": dispatch_id},
        )
        return result.get("errorCode") == "S0000"
