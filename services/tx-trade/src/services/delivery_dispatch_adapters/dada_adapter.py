"""达达 DadaAdapter — 三方众包配送

接入文档：https://newopen.imdada.cn/
认证：app_key + app_secret + source_id（=merchant_id）
签名：MD5(参数排序拼接 + secret)

当前阶段（mock）：返回 fake provider_order_id；接入真实 API 时替换 _call_api。
"""

from __future__ import annotations

import hashlib
import json

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


class DadaAdapter(BaseDeliveryDispatchAdapter):
    provider = "dada"

    BASE_URL = "https://newopen.imdada.cn/api/v1_0"

    def _sign(self, params: dict) -> str:
        """达达签名算法：参数 key 字典序排序，拼接成 'k1v1k2v2...' + secret，MD5 大写"""
        secret = self.config.app_secret or ""
        sorted_kv = "".join(f"{k}{v}" for k, v in sorted(params.items()) if v is not None)
        raw = f"{sorted_kv}{secret}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()

    async def _call_api(self, action: str, payload: dict) -> dict:
        """统一 HTTP 入口（当前 mock 实现）

        生产环境替换为：
            async with httpx.AsyncClient() as cli:
                resp = await cli.post(f"{self.BASE_URL}/{action}", json=payload)
                resp.raise_for_status()
                return resp.json()
        """
        logger.info("dada.api_call_mock", action=action, dispatch_id=payload.get("shop_no"))
        return {
            "status": "success",
            "code": 0,
            "result": {
                "deliveryNo": gen_mock_provider_order_id(self.provider),
                "deliveryFee": payload.get("delivery_fee_fen", 0) / 100,
                "tipsFee": payload.get("tip_fen", 0) / 100,
            },
        }

    async def dispatch(self, order: DispatchOrderInput) -> DispatchResult:
        if not (self.config.app_key and self.config.merchant_id):
            return DispatchResult(
                success=False,
                provider_order_id=None,
                estimated_minutes=order.estimated_minutes,
                error_code="CONFIG_INCOMPLETE",
                error_message="达达配置缺少 app_key 或 merchant_id",
            )

        payload = {
            "shop_no": self.config.shop_no or self.config.store_id,
            "origin_id": order.dispatch_id,
            "city_code": str(self.config.extra_config.get("city_code", "")),
            "cargo_price": 0,
            "cargo_weight": float(self.config.extra_config.get("default_weight_kg", 1.0)),
            "is_prepay": 0,
            "receiver_name": "顾客",
            "receiver_address": order.delivery_address,
            "receiver_phone": order.customer_phone or "",
            "delivery_fee_fen": order.delivery_fee_fen,
            "tip_fen": order.tip_fen,
            "callback": self.config.callback_url or "",
            "app_key": self.config.app_key,
        }
        # 签名（mock 阶段也保留签名调用，确保接入时配置即可生效）
        _signature = self._sign(payload)

        api_result = await self._call_api("orderAddSingle", payload)
        if api_result.get("code") != 0:
            return DispatchResult(
                success=False,
                provider_order_id=None,
                estimated_minutes=order.estimated_minutes,
                raw=api_result,
                error_code=str(api_result.get("code")),
                error_message=api_result.get("msg", "达达下单失败"),
            )

        result_data = api_result.get("result") or {}
        provider_order_id = result_data.get("deliveryNo")
        return DispatchResult(
            success=True,
            provider_order_id=provider_order_id,
            estimated_minutes=order.estimated_minutes,
            raw=api_result,
        )

    async def cancel(self, provider_order_id: str, reason: str) -> bool:
        payload = {
            "order_id": provider_order_id,
            "cancel_reason_id": 1,
            "cancel_reason": reason,
            "app_key": self.config.app_key,
        }
        _signature = self._sign(payload)
        result = await self._call_api("orderCancel", payload)
        return result.get("code") == 0

    async def query_location(self, provider_order_id: str) -> RiderLocation:
        payload = {
            "order_id": provider_order_id,
            "app_key": self.config.app_key,
        }
        _signature = self._sign(payload)
        result = await self._call_api("orderQuery", payload)
        # mock：构造确定性的 fake 位置（实际接入需解析 result.result.transporter_lat 等）
        seed = int(hashlib.md5(provider_order_id.encode("utf-8")).hexdigest()[:6], 16)
        return RiderLocation(
            rider_lat=28.2282 + (seed % 100) * 0.0001,
            rider_lng=112.9388 + (seed % 100) * 0.0001,
            rider_name=f"达达骑手{seed % 1000:03d}",
            rider_phone="138****" + str(seed % 10000).zfill(4),
            updated_at=now_utc(),
            raw=result,
        )

    async def notify_pickup_ready(
        self,
        provider_order_id: str,
        dispatch_id: str,
    ) -> bool:
        """达达：商家不主动通知，骑手到店扫码取货。仅记 log。"""
        logger.info(
            "dada.pickup_ready_noop",
            provider_order_id=provider_order_id,
            dispatch_id=dispatch_id,
            note="达达无主动通知接口，骑手到店扫码取货",
        )
        # 兼容 json 序列化兜底（占位，未来若有接口再替换）
        _ = json.dumps({"dispatch_id": dispatch_id})
        return True
