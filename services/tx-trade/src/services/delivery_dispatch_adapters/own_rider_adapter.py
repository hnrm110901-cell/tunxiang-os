"""自有骑手 OwnRiderAdapter — 门店自有骑手池

不调用三方 API，直接写库 + 通过事件总线/WebSocket 通知骑手 App。

当前 mock 行为：
  - dispatch: 立即返回 success=True 并生成 OWN-XXXX 编号
  - cancel:   返回 True
  - query_location: 由调用方传入最近一次 App 上报的位置（通过路由层另外的接口写入）
  - notify_pickup_ready: 通过 WebSocket 通道（占位）+ event_bus 推送

后续接入：替换 _publish_to_rider_app 为真实 push（FCM / 个推 / WebSocket）。
"""

from __future__ import annotations

import asyncio

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


class OwnRiderAdapter(BaseDeliveryDispatchAdapter):
    provider = "self_rider"

    async def _publish_to_rider_app(self, event: str, payload: dict) -> bool:
        """向自有骑手 App 推送事件（占位）

        生产实现：
          - 优先 WebSocket（已在线骑手）
          - 离线降级到 FCM/个推
          - 落库到 rider_notifications 兜底
        """
        logger.info(
            "own_rider.publish_to_app",
            event=event,
            store_id=self.config.store_id,
            payload_keys=list(payload),
        )
        # 模拟异步推送的 await，方便单测覆盖
        await asyncio.sleep(0)
        return True

    async def dispatch(self, order: DispatchOrderInput) -> DispatchResult:
        # 自有骑手无需远程鉴权；推一条 NEW_DISPATCH 到骑手 App
        provider_order_id = gen_mock_provider_order_id(self.provider)
        await self._publish_to_rider_app(
            "rider.new_dispatch",
            {
                "dispatch_id": order.dispatch_id,
                "order_id": order.order_id,
                "store_id": order.store_id,
                "address": order.delivery_address,
                "lat": order.delivery_lat,
                "lng": order.delivery_lng,
                "distance_meters": order.distance_meters,
                "delivery_fee_fen": order.delivery_fee_fen,
                "tip_fen": order.tip_fen,
                "estimated_minutes": order.estimated_minutes,
            },
        )
        return DispatchResult(
            success=True,
            provider_order_id=provider_order_id,
            estimated_minutes=order.estimated_minutes,
            raw={"channel": "own_rider", "published_at": now_utc().isoformat()},
        )

    async def cancel(self, provider_order_id: str, reason: str) -> bool:
        await self._publish_to_rider_app(
            "rider.dispatch_cancelled",
            {"provider_order_id": provider_order_id, "reason": reason},
        )
        return True

    async def query_location(self, provider_order_id: str) -> RiderLocation:
        # 自有骑手位置由 App 周期性 POST 到 /rider/location，路由层直接读 DB
        # 此处兜底返回 None 位置，路由层会 fallback 到 DB 中已存值
        return RiderLocation(
            rider_lat=None,
            rider_lng=None,
            rider_name=None,
            rider_phone=None,
            updated_at=now_utc(),
            raw={"note": "self_rider location is reported by rider app"},
        )

    async def notify_pickup_ready(
        self,
        provider_order_id: str,
        dispatch_id: str,
    ) -> bool:
        """KDS 出餐完成 → 推送 PICKUP_READY 到骑手 App"""
        return await self._publish_to_rider_app(
            "rider.pickup_ready",
            {
                "dispatch_id": dispatch_id,
                "provider_order_id": provider_order_id,
            },
        )
