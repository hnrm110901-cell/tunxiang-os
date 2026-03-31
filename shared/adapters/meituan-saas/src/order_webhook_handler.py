"""美团外卖订单 Webhook 事件处理器

事件类型：
  - order_paid      顾客下单并支付（通知接单，支持自动接单）
  - order_verified  到店核销（触发 Golden ID 绑定）

美团推送字段参考（核销事件）：
  event_type, order_id, day_seq, status,
  recipient_phone, meituan_user_id, openid,
  order_total_price (分), detail (JSON 字符串), app_poi_code

使用方：
    handler = MeituanOrderWebhookHandler(binding_service, tenant_id)
    result = await handler.handle(raw_payload, db)
    # 自动接单需传入 store_id 和 current_hour_count：
    handler = MeituanOrderWebhookHandler(binding_service, tenant_id, store_id="xxx")
    result = await handler.handle(raw_payload, db, current_hour_count=5)
"""
import uuid
from typing import Any, Optional

import structlog

logger = structlog.get_logger()

# 美团核销状态码（order_verified 对应 status=5 已完成 / 自定义核销事件）
_VERIFIED_STATUSES = {5, 9}   # 5=已完成, 9=核销（部分平台用此值）


class MeituanOrderWebhookHandler:
    """处理美团外卖推送事件，核销时调用 PlatformBindingService"""

    def __init__(
        self,
        binding_service: Any,
        tenant_id: uuid.UUID,
        store_id: Optional[str] = None,
    ) -> None:
        """
        Args:
            binding_service: PlatformBindingService 实例
            tenant_id: 租户 UUID
            store_id: 门店 ID（传入时启用自动接单功能）
        """
        self._svc = binding_service
        self._tenant_id = tenant_id
        self._store_id = store_id

    async def handle(
        self,
        payload: dict[str, Any],
        db: Any,  # AsyncSession
        current_hour_count: int = 0,
    ) -> dict[str, Any]:
        """统一事件入口

        Args:
            payload: 美团推送的原始 JSON 字典
            db: AsyncSession
            current_hour_count: 当前小时已自动接单数（由调用方统计后传入，用于上限判断）

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
            data = await self._handle_order_paid(payload, db, log, current_hour_count)
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
        db: Any,
        log: Any,
        current_hour_count: int = 0,
    ) -> dict[str, Any]:
        """下单支付事件：判断是否自动接单，若是则调用美团接单 API。

        自动接单逻辑：
          1. 需要 store_id 已在构造时传入
          2. 调用 DeliveryOpsService.should_auto_accept() 判断（考虑开关+每小时上限）
          3. 若应自动接单，调用美团接单 API（携带当前出餐时间）
          4. 不影响手动接单流程 —— 若不满足自动接单条件，返回 action=pending_manual
        """
        order_id = str(payload.get("order_id", ""))
        store_id = self._store_id or str(payload.get("app_poi_code", ""))

        log.info(
            "meituan_order_paid",
            order_id=order_id,
            amount_fen=payload.get("order_total_price"),
            store_id=store_id,
        )

        # ── 自动接单路径 ──────────────────────────────────────────────
        if store_id:
            try:
                from services.tx_trade.src.services.delivery_ops_service import (  # noqa: PLC0415
                    DeliveryOpsService,
                )
                ops_svc = DeliveryOpsService()
                should_accept = await ops_svc.should_auto_accept(
                    store_id=store_id,
                    platform="meituan",
                    tenant_id=self._tenant_id,
                    current_hour_count=current_hour_count,
                    db=db,
                )

                if should_accept:
                    prep_time_min = await ops_svc.get_current_prep_time(
                        store_id=store_id,
                        platform="meituan",
                        tenant_id=self._tenant_id,
                        db=db,
                    )
                    accept_result = await self._call_meituan_accept_api(
                        order_id=order_id,
                        prep_time_min=prep_time_min,
                        log=log,
                    )
                    log.info(
                        "meituan_order_auto_accepted",
                        order_id=order_id,
                        prep_time_min=prep_time_min,
                    )
                    return {
                        "action": "auto_accepted",
                        "order_id": order_id,
                        "prep_time_min": prep_time_min,
                        "meituan_accept_result": accept_result,
                    }
                else:
                    log.info(
                        "meituan_order_pending_manual",
                        order_id=order_id,
                        reason="auto_accept_disabled_or_limit_reached",
                    )
            except ImportError:
                # DeliveryOpsService 不可用时降级为手动接单（跨模块调用路径问题）
                log.warning(
                    "meituan_auto_accept_unavailable",
                    reason="DeliveryOpsService import failed — fallback to manual",
                )
            except Exception as exc:  # noqa: BLE001 — 自动接单失败不阻断主流程
                log.error(
                    "meituan_auto_accept_error",
                    error=str(exc),
                    exc_info=True,
                )

        # ── 手动接单兜底（自动接单未触发或失败） ──────────────────────
        return {
            "action": "pending_manual",
            "order_id": order_id,
        }

    async def _call_meituan_accept_api(
        self,
        order_id: str,
        prep_time_min: int,
        log: Any,
    ) -> dict[str, Any]:
        """调用美团接单 API（通知美团已接单并设置出餐时间）。

        TODO: 配置真实 API Key 后替换此 mock 实现。
              美团接单接口文档：
              https://developer.meituan.com/openapi/docs/food/order/accept
              请求参数：
                - app_id: 美团商家 AppID（从 MEITUAN_APP_ID 环境变量读取）
                - sign: 签名（HMAC-MD5，密钥从 MEITUAN_APP_SECRET 读取）
                - order_id: 订单号
                - shipping_time: 预计出餐时间（分钟）
              需申请"自动接单"权限后才能调用此接口。
        """
        log.info(
            "meituan_accept_api_mock",
            order_id=order_id,
            prep_time_min=prep_time_min,
            note="TODO: replace with real Meituan accept API call",
        )
        # Mock 返回，保持接口形状与真实 API 一致
        return {
            "mock": True,
            "order_id": order_id,
            "prep_time_min": prep_time_min,
            "status": "accepted",
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
