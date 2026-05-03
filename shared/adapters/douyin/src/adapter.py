"""
抖音生活服务开放平台 API 适配器
提供团购券管理、订单查询、门店信息、结算单等功能

底层 HTTP 调用委托给 DouyinClient，本类只做业务编排。

幂等性: idempotency_key/is_duplicate/mark_idempotent
事件:   异步发射适配器同步事件(参考 Sprint F1 / PR F)
"""

import asyncio
import hashlib
import json
from typing import Any, Dict, Set

import structlog

from .client import DouyinClient

logger = structlog.get_logger()


class DouyinAdapter:
    """抖音生活服务开放平台适配器（委托 DouyinClient 处理认证/签名/HTTP）"""

    def __init__(self, config: Dict[str, Any]):
        """
        初始化适配器

        Args:
            config: 配置字典，包含:
                - app_id: 应用ID
                - app_secret: 应用密钥
                - sandbox: 是否沙箱环境（默认 False）
                - timeout: 超时时间（秒，默认 30）
                - retry_times: 重试次数（默认 3）
        """
        self.config = config
        self.client = DouyinClient(
            app_id=config.get("app_id"),
            app_secret=config.get("app_secret"),
            sandbox=config.get("sandbox", False),
            timeout=config.get("timeout", 30),
            retry_times=config.get("retry_times", 3),
        )
        self._tenant_id: str = config.get("tenant_id", "")
        self._nonce_store: Set[str] = set()

        logger.info(
            "抖音生活服务适配器初始化",
            sandbox=config.get("sandbox", False),
        )

    # ==================== 幂等性 ====================

    def idempotency_key(self, operation: str, payload: Dict[str, Any]) -> str:
        """基于 operation + payload 生成确定性幂等键。"""
        raw = f"{operation}:{self._tenant_id}:{json.dumps(payload, sort_keys=True)}"
        return hashlib.md5(raw.encode()).hexdigest()

    def is_duplicate(self, key: str) -> bool:
        return key in self._nonce_store

    def mark_idempotent(self, key: str) -> None:
        self._nonce_store.add(key)

    # ==================== 事件发射 ====================

    async def _emit_sync_event(
        self, event_type: str, scope: str, stream_id: str, payload: dict
    ) -> None:
        """发射适配器同步事件（fire-and-forget，失败只记 warning）。

        Args:
            event_type: 事件类型短名（如 status_pushed / sync_finished）
            scope:      同步范围（orders / menu / members / status_push）
            stream_id:  聚合根 ID
            payload:    业务数据
        """
        try:
            from shared.events.src.event_types import AdapterEventType
            from shared.adapters.base.src.event_bus import emit_adapter_event

            evt = getattr(AdapterEventType, event_type.upper(), AdapterEventType.STATUS_PUSHED)
            asyncio.create_task(
                emit_adapter_event(
                    adapter_name="douyin",
                    event_type=evt,
                    scope=scope,
                    stream_id=stream_id,
                    payload=payload,
                    tenant_id=self._tenant_id,
                )
            )
        except Exception:  # noqa: BLE001 — 事件发射失败不阻断主流程
            logger.warning("douyin.event_emit_failed", exc_info=True)

    # ==================== 团购券接口 ====================

    async def query_coupons(
        self,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """查询团购券列表"""
        logger.info("查询团购券列表", page=page, page_size=page_size)
        result = await self.client.request(
            "POST",
            "/api/apps/trade/v2/coupon/query_list/",
            data={"page": page, "page_size": page_size},
        )
        data = result.get("data", {})
        asyncio.create_task(
            self._emit_sync_event(
                "status_pushed",
                "coupon_query",
                f"douyin:coupon:list",
                {"page": page, "page_size": page_size},
            )
        )
        return data

    async def get_coupon_detail(self, coupon_id: str) -> Dict[str, Any]:
        """查询团购券详情"""
        logger.info("查询团购券详情", coupon_id=coupon_id)
        result = await self.client.request(
            "POST",
            "/api/apps/trade/v2/coupon/query_detail/",
            data={"coupon_id": coupon_id},
        )
        data = result.get("data", {})
        asyncio.create_task(
            self._emit_sync_event(
                "status_pushed",
                "coupon_detail",
                f"douyin:coupon:{coupon_id}",
                {"coupon_id": coupon_id},
            )
        )
        return data

    async def verify_coupon(self, code: str, shop_id: str) -> Dict[str, Any]:
        """
        核销团购券（委托 DouyinClient.verify_certificate）

        Args:
            code: 券码
            shop_id: 抖音门店 ID
        """
        logger.info("核销团购券", shop_id=shop_id)
        data = await self.client.verify_certificate(
            encrypted_code=code,
            shop_id=shop_id,
        )
        asyncio.create_task(
            self._emit_sync_event(
                "status_pushed",
                "coupon_verify",
                f"douyin:coupon:verify:{shop_id}",
                {"code": code, "shop_id": shop_id},
            )
        )
        return data

    # ==================== 订单接口 ====================

    async def query_orders(
        self,
        start_time: str,
        end_time: str,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """
        查询团购订单列表

        Args:
            start_time: 开始时间 (ISO 格式)
            end_time: 结束时间 (ISO 格式)
            page: 页码
            page_size: 每页大小
        """
        logger.info("查询团购订单", start_time=start_time, end_time=end_time, page=page)
        result = await self.client.request(
            "POST",
            "/api/apps/trade/v2/order/query_list/",
            data={
                "start_time": start_time,
                "end_time": end_time,
                "page": page,
                "page_size": page_size,
            },
        )
        data = result.get("data", {})
        asyncio.create_task(
            self._emit_sync_event(
                "sync_finished",
                "orders",
                f"douyin:orders:{start_time}:{end_time}",
                {"start_time": start_time, "end_time": end_time, "page": page},
            )
        )
        return data

    async def get_order_detail(self, order_id: str) -> Dict[str, Any]:
        """查询团购订单详情"""
        logger.info("查询团购订单详情", order_id=order_id)
        data = await self.client.query_order(order_id)
        asyncio.create_task(
            self._emit_sync_event(
                "sync_finished",
                "order_detail",
                f"douyin:order:{order_id}",
                {"order_id": order_id},
            )
        )
        return data

    # ==================== 门店接口 ====================

    async def get_shop_info(self, shop_id: str) -> Dict[str, Any]:
        """查询抖音门店信息"""
        logger.info("查询抖音门店信息", shop_id=shop_id)
        result = await self.client.request(
            "POST",
            "/api/apps/trade/v2/shop/query/",
            data={"shop_id": shop_id},
        )
        data = result.get("data", {})
        asyncio.create_task(
            self._emit_sync_event(
                "sync_finished",
                "shop_info",
                f"douyin:shop:{shop_id}",
                {"shop_id": shop_id},
            )
        )
        return data

    # ==================== 结算接口 ====================

    async def query_settlements(
        self,
        start_date: str,
        end_date: str,
    ) -> Dict[str, Any]:
        """
        查询结算单列表

        Args:
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
        """
        logger.info("查询结算单", start_date=start_date, end_date=end_date)
        result = await self.client.request(
            "POST",
            "/api/apps/trade/v2/settlement/query_list/",
            data={"start_date": start_date, "end_date": end_date},
        )
        data = result.get("data", {})
        asyncio.create_task(
            self._emit_sync_event(
                "sync_finished",
                "settlement",
                f"douyin:settlement:{start_date}:{end_date}",
                {"start_date": start_date, "end_date": end_date},
            )
        )
        return data

    # ==================== 资源管理 ====================

    async def close(self) -> None:
        """关闭适配器，释放资源"""
        logger.info("关闭抖音生活服务适配器")
        await self.client.close()
