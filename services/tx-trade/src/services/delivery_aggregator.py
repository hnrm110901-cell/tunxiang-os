"""外卖平台聚合器 — 统一接口

职责：
  1. 接收并验证各平台 Webhook 推送
  2. 解析为内部统一 DeliveryOrder 格式，写入 delivery_orders 表
  3. 将外卖订单转换为内部 orders/order_items，写入交易履约链路
  4. 通过 WebSocket 广播到 KDS
  5. 回调平台接单/拒单确认

金额：所有金额统一使用分（int），避免浮点精度问题。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

import structlog

from .delivery_adapters import (
    BaseDeliveryAdapter,
    DeliveryOrder,
    DouyinAdapter,
    ElemeAdapter,
    MeituanAdapter,
)

logger = structlog.get_logger(__name__)

# ─────────────────────────────────────────────────────────────────
# Pydantic 响应模型
# ─────────────────────────────────────────────────────────────────

from pydantic import BaseModel, Field


class DeliveryPlatformStats(BaseModel):
    """单个平台日统计"""

    platform: str
    order_count: int = 0
    revenue_fen: int = 0  # 平台营收（总金额）
    commission_fen: int = 0  # 平台佣金
    net_revenue_fen: int = 0  # 实收 = revenue - commission
    effective_rate: float = 0.0  # 实际费率 = commission / revenue


class DeliveryDailyStats(BaseModel):
    """外卖日统计汇总"""

    date: date
    tenant_id: UUID
    store_id: UUID
    platforms: list[DeliveryPlatformStats] = Field(default_factory=list)
    total_orders: int = 0
    total_revenue_fen: int = 0
    total_commission_fen: int = 0
    total_net_revenue_fen: int = 0


# ─────────────────────────────────────────────────────────────────
# 聚合器
# ─────────────────────────────────────────────────────────────────


class DeliveryAggregator:
    """外卖平台聚合器 — 统一调度美团/饿了么/抖音订单流转"""

    SUPPORTED_PLATFORMS = ("meituan", "eleme", "douyin")

    def _get_adapter(
        self,
        platform: str,
        app_id: str,
        app_secret: str,
        shop_id: str,
    ) -> BaseDeliveryAdapter:
        """根据平台标识返回对应适配器实例"""
        adapters: dict[str, type[BaseDeliveryAdapter]] = {
            "meituan": MeituanAdapter,
            "eleme": ElemeAdapter,
            "douyin": DouyinAdapter,
        }
        cls = adapters.get(platform)
        if cls is None:
            raise ValueError(f"不支持的外卖平台: {platform}")
        return cls(app_id=app_id, app_secret=app_secret, shop_id=shop_id)

    async def receive_order(
        self,
        platform: str,
        raw_payload: dict,
        tenant_id: UUID,
        *,
        app_id: str,
        app_secret: str,
        shop_id: str,
        commission_rate: float,
        store_id: UUID,
        db_session,  # AsyncSession（生产环境注入）
        broadcast_fn=None,  # 可选的 WebSocket 广播回调
    ) -> DeliveryOrder:
        """
        接收外卖平台 Webhook 推送的订单。

        流程：
          1. 获取平台适配器
          2. 解析为统一 DeliveryOrder 格式
          3. 计算佣金
          4. 写入 delivery_orders 表（生产环境通过 db_session 执行）
          5. 转换为内部 Order 格式，写入 orders/order_items
          6. 通过 WebSocket 广播到 KDS
          7. 返回 DeliveryOrder（供路由层向平台返回确认）

        Args:
            platform:        平台标识 meituan/eleme/douyin
            raw_payload:     平台原始 JSON 字典
            tenant_id:       租户 ID（从平台配置表查出）
            app_id:          平台 AppID（从配置表读取）
            app_secret:      平台密钥明文（解密后传入）
            shop_id:         平台店铺 ID
            commission_rate: 佣金费率（如 0.18）
            store_id:        内部门店 ID
            db_session:      数据库异步会话
            broadcast_fn:    KDS 广播函数，签名 async (tenant_id, store_id, event) -> None
        """
        log = logger.bind(
            platform=platform,
            tenant_id=str(tenant_id),
            store_id=str(store_id),
        )

        # 1. 获取适配器并解析
        adapter = self._get_adapter(platform, app_id, app_secret, shop_id)
        try:
            order = adapter.parse_order(raw_payload)
        except ValueError as exc:
            log.error("delivery_receive_parse_failed", error=str(exc))
            raise

        # 2. 计算佣金（取整，四舍五入）
        commission_fen = round(order.total_fen * commission_rate)
        log.info(
            "delivery_order_parsed",
            platform_order_id=order.platform_order_id,
            total_fen=order.total_fen,
            commission_fen=commission_fen,
        )

        # 3. 写入 delivery_orders 表
        #    生产环境：通过 db_session 执行 INSERT，此处为骨架注释
        #    示例：
        #      await db_session.execute(
        #          insert(DeliveryOrderModel).values(
        #              id=uuid.uuid4(),
        #              tenant_id=tenant_id,
        #              store_id=store_id,
        #              platform=order.platform,
        #              platform_order_id=order.platform_order_id,
        #              status=order.status,
        #              items=[item.model_dump() for item in order.items],
        #              total_fen=order.total_fen,
        #              delivery_fee_fen=order.delivery_fee_fen,
        #              commission_fen=commission_fen,
        #              customer_name=order.customer_name,
        #              customer_phone=order.customer_phone,
        #              delivery_address=order.delivery_address,
        #              estimated_delivery_at=order.estimated_delivery_at,
        #              raw_payload=order.raw_payload,
        #          )
        #      )

        # 4. 转换为内部 Order 格式并写入 orders 表
        #    外卖订单作为 order_type='delivery' 的普通订单进入履约链路
        #    内部 Order 字段映射：
        #      store_id, tenant_id, order_type='delivery'
        #      source_platform = platform
        #      items → order_items（dish_id 通过 delivery_platform_items 映射）
        #    生产环境：调用 OrderRepository.create_from_delivery(...)

        # 5. 广播到 KDS
        if broadcast_fn is not None:
            try:
                await broadcast_fn(
                    tenant_id=tenant_id,
                    store_id=store_id,
                    event={
                        "type": "delivery_order_new",
                        "platform": order.platform,
                        "platform_order_id": order.platform_order_id,
                        "total_fen": order.total_fen,
                        "items_count": len(order.items),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                log.info("delivery_order_broadcasted_to_kds", platform_order_id=order.platform_order_id)
            except Exception as exc:  # noqa: BLE001 — MLPS3-P0: KDS广播失败不阻断接单，最外层兜底
                # 广播失败不阻断主流程
                log.warning("delivery_kds_broadcast_failed", error=str(exc), exc_info=True)

        return order

    async def confirm_order(
        self,
        delivery_order_id: UUID,
        *,
        db_session,
    ) -> bool:
        """
        确认接单：
          1. 查询 delivery_orders 表，获取 platform/platform_order_id/config
          2. 加载对应平台配置（app_id/app_secret）
          3. 调用平台 API confirm
          4. 更新 delivery_orders.status = 'confirmed'

        生产环境：需注入 db_session 查询并更新。
        """
        log = logger.bind(delivery_order_id=str(delivery_order_id))
        log.info("delivery_confirm_order", note="生产环境需查询DB并调用平台confirm API")
        # 生产环境实现：
        #   order = await DeliveryOrderRepository.get(db_session, delivery_order_id)
        #   config = await DeliveryConfigRepository.get_by_store_platform(
        #       db_session, order.store_id, order.platform)
        #   adapter = self._get_adapter(order.platform, config.app_id,
        #                               decrypt(config.app_secret), config.shop_id)
        #   ok = await adapter.confirm_order(order.platform_order_id)
        #   if ok:
        #       await DeliveryOrderRepository.update_status(
        #           db_session, delivery_order_id, 'confirmed')
        #   return ok
        return True

    async def reject_order(
        self,
        delivery_order_id: UUID,
        reason: str,
        *,
        db_session,
    ) -> bool:
        """
        拒单：
          1. 查询 delivery_orders 表
          2. 调用平台 API reject
          3. 更新 status = 'rejected'，记录 reject_reason
        """
        log = logger.bind(delivery_order_id=str(delivery_order_id), reason=reason)
        log.info("delivery_reject_order", note="生产环境需查询DB并调用平台reject API")
        return True

    async def update_delivery_status(
        self,
        delivery_order_id: UUID,
        status: str,
        *,
        db_session,
    ) -> None:
        """
        更新配送状态（骑手取单/已送达等）：
          合法状态转换：
            confirmed → preparing → ready → dispatched → delivered
          写入 delivery_orders.status + updated_at
        """
        valid_statuses = {
            "confirmed",
            "preparing",
            "ready",
            "dispatched",
            "delivered",
            "cancelled",
        }
        if status not in valid_statuses:
            raise ValueError(f"无效的配送状态: {status}，合法值：{valid_statuses}")

        log = logger.bind(delivery_order_id=str(delivery_order_id), new_status=status)
        log.info("delivery_update_status", note="生产环境需通过 DeliveryOrderRepository 更新")
        # 生产环境：
        #   await DeliveryOrderRepository.update_status(db_session, delivery_order_id, status)

    async def get_daily_stats(
        self,
        tenant_id: UUID,
        store_id: UUID,
        target_date: date,
        *,
        db_session,
    ) -> DeliveryDailyStats:
        """
        外卖日统计：按平台分组汇总订单数/营收/佣金/实收/费率。

        SQL 骨架（生产环境）：
          SELECT
            platform,
            COUNT(*)                          AS order_count,
            SUM(total_fen)                    AS revenue_fen,
            SUM(commission_fen)               AS commission_fen,
            SUM(total_fen - commission_fen)   AS net_revenue_fen
          FROM delivery_orders
          WHERE tenant_id = :tenant_id
            AND store_id  = :store_id
            AND created_at::date = :target_date
            AND status NOT IN ('cancelled', 'rejected')
            AND is_deleted = FALSE
          GROUP BY platform
        """
        log = logger.bind(
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            date=target_date.isoformat(),
        )
        log.info("delivery_daily_stats", note="生产环境需通过 DB 聚合查询")

        # 骨架：返回空统计（生产环境替换为 DB 查询结果）
        return DeliveryDailyStats(
            date=target_date,
            tenant_id=tenant_id,
            store_id=store_id,
            platforms=[],
            total_orders=0,
            total_revenue_fen=0,
            total_commission_fen=0,
            total_net_revenue_fen=0,
        )
