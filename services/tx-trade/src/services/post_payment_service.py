"""支付后推券服务 — Closed Loop Marketing

对标 Toast Closed Loop Marketing。
支付完成后根据消费行为智能推券，通过微信推送给顾客。

推券策略：
  a. 首单顾客 → 发"二次回头券"（满100减20）
  b. 高价值顾客(S1/S2) → 发"VIP 专属券"
  c. 点了某菜品 → 发"关联菜品券"（如点了鱼头→送酸菜鱼5元券）
  d. 消费满额 → 发"满赠券"
"""

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Customer, Order, OrderItem

logger = structlog.get_logger()


# ─── 关联菜品推荐规则（可配置化，当前硬编码示例） ───

_RELATED_DISH_COUPONS: dict[str, dict] = {
    # dish_name 关键词 → 推荐券配置
    "鱼头": {
        "coupon_name": "酸菜鱼5元优惠券",
        "discount_fen": 500,
        "min_order_amount_fen": 5000,
        "related_dish": "酸菜鱼",
    },
    "小龙虾": {
        "coupon_name": "蒜蓉粉丝虾8元优惠券",
        "discount_fen": 800,
        "min_order_amount_fen": 8000,
        "related_dish": "蒜蓉粉丝虾",
    },
    "烤鱼": {
        "coupon_name": "水煮鱼片5元优惠券",
        "discount_fen": 500,
        "min_order_amount_fen": 5000,
        "related_dish": "水煮鱼片",
    },
}

# ─── 满赠门槛配置 ───

_FULL_AMOUNT_THRESHOLDS: list[dict] = [
    {"min_fen": 30000, "coupon_name": "满300赠50券", "discount_fen": 5000, "min_order_fen": 20000},
    {"min_fen": 20000, "coupon_name": "满200赠30券", "discount_fen": 3000, "min_order_fen": 15000},
    {"min_fen": 10000, "coupon_name": "满100赠15券", "discount_fen": 1500, "min_order_fen": 8000},
]


class PostPaymentService:
    """支付后推券服务"""

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = uuid.UUID(tenant_id)

    async def trigger_post_payment(
        self,
        order_id: str,
        customer_id: str,
    ) -> dict:
        """支付完成后触发推券

        分析本单消费金额和菜品，根据策略发券并推送微信。
        此函数应异步调用，不阻塞结账流程。
        """
        # 加载订单
        order_result = await self.db.execute(
            select(Order).where(
                Order.id == uuid.UUID(order_id),
                Order.tenant_id == self.tenant_id,
            )
        )
        order = order_result.scalar_one_or_none()
        if not order:
            logger.warning("post_payment_order_not_found", order_id=order_id)
            return {"issued_coupons": [], "reason": "订单不存在"}

        # 加载顾客
        customer_result = await self.db.execute(
            select(Customer).where(
                Customer.id == uuid.UUID(customer_id),
                Customer.tenant_id == self.tenant_id,
            )
        )
        customer = customer_result.scalar_one_or_none()
        if not customer:
            logger.warning("post_payment_customer_not_found", customer_id=customer_id)
            return {"issued_coupons": [], "reason": "顾客不存在"}

        # 加载订单明细
        items_result = await self.db.execute(select(OrderItem).where(OrderItem.order_id == uuid.UUID(order_id)))
        items = items_result.scalars().all()
        item_names = [i.item_name for i in items if i.item_name]

        # 分析并生成推券
        issued_coupons: list[dict] = []
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(days=30)).isoformat()

        # 策略 a: 首单顾客 → 二次回头券
        total_orders = customer.total_order_count or 0
        if total_orders <= 1:
            coupon = self._create_coupon(
                customer_id=customer_id,
                coupon_name="二次回头券 · 满100减20",
                coupon_type="activity",
                discount_fen=2000,
                min_order_amount_fen=10000,
                expires_at=expires_at,
                reason="首单顾客回头激励",
            )
            issued_coupons.append(coupon)

        # 策略 b: 高价值顾客(S1/S2) → VIP 专属券
        rfm_level = customer.rfm_level or "S3"
        if rfm_level in ("S1", "S2"):
            coupon = self._create_coupon(
                customer_id=customer_id,
                coupon_name="VIP专属券 · 满200减50",
                coupon_type="activity",
                discount_fen=5000,
                min_order_amount_fen=20000,
                expires_at=expires_at,
                reason=f"VIP顾客({rfm_level})专属权益",
            )
            issued_coupons.append(coupon)

        # 策略 c: 点了某菜品 → 关联菜品券
        for item_name in item_names:
            for keyword, config in _RELATED_DISH_COUPONS.items():
                if keyword in item_name:
                    coupon = self._create_coupon(
                        customer_id=customer_id,
                        coupon_name=config["coupon_name"],
                        coupon_type="activity",
                        discount_fen=config["discount_fen"],
                        min_order_amount_fen=config["min_order_amount_fen"],
                        expires_at=expires_at,
                        reason=f"关联推荐: 点了{item_name}→推{config['related_dish']}",
                    )
                    issued_coupons.append(coupon)
                    break  # 每个菜品只匹配一条规则

        # 策略 d: 消费满额 → 满赠券
        final_amount: int = order.final_amount_fen or 0
        for threshold in _FULL_AMOUNT_THRESHOLDS:
            if final_amount >= threshold["min_fen"]:
                coupon = self._create_coupon(
                    customer_id=customer_id,
                    coupon_name=threshold["coupon_name"],
                    coupon_type="general",
                    discount_fen=threshold["discount_fen"],
                    min_order_amount_fen=threshold["min_order_fen"],
                    expires_at=expires_at,
                    reason=f"消费满{threshold['min_fen'] // 100}元赠券",
                )
                issued_coupons.append(coupon)
                break  # 只发最高档

        # 推送微信通知
        if issued_coupons and customer.wechat_openid:
            await self._send_coupon_notification(
                customer=customer,
                order=order,
                coupons=issued_coupons,
            )

        logger.info(
            "post_payment_coupons_issued",
            order_id=order_id,
            customer_id=customer_id,
            coupon_count=len(issued_coupons),
            coupon_names=[c["coupon_name"] for c in issued_coupons],
        )

        return {
            "order_id": order_id,
            "customer_id": customer_id,
            "issued_coupons": issued_coupons,
        }

    def _create_coupon(
        self,
        *,
        customer_id: str,
        coupon_name: str,
        coupon_type: str,
        discount_fen: int,
        min_order_amount_fen: int,
        expires_at: str,
        reason: str,
    ) -> dict:
        """创建优惠券并存入 CouponStore"""
        from .coupon_service import _CouponStore

        coupon_code = f"POST-{uuid.uuid4().hex[:8].upper()}"
        coupon_data = {
            "coupon_code": coupon_code,
            "coupon_name": coupon_name,
            "coupon_type": coupon_type,
            "discount_fen": discount_fen,
            "min_order_amount_fen": min_order_amount_fen,
            "customer_id": customer_id,
            "tenant_id": str(self.tenant_id),
            "status": "active",
            "stackable": True,
            "expires_at": expires_at,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": "post_payment",
            "reason": reason,
        }
        _CouponStore.save(coupon_code, coupon_data)

        return coupon_data

    async def _send_coupon_notification(
        self,
        *,
        customer: Customer,
        order: Order,
        coupons: list[dict],
    ) -> None:
        """通过微信推送券通知"""
        try:
            from services.tx_ops.src.services.notification_service import NotificationService  # noqa: E501
        except ImportError:
            # 跨服务引用可能失败，降级到日志
            logger.info(
                "post_payment_notification_skipped",
                reason="notification_service unavailable",
                customer_id=str(customer.id),
            )
            return

        try:
            notification_svc = NotificationService(
                db=self.db,
                tenant_id=str(self.tenant_id),
            )

            coupon_summary = "、".join(c["coupon_name"] for c in coupons[:3])
            if len(coupons) > 3:
                coupon_summary += f"等{len(coupons)}张券"

            amount_yuan = (order.final_amount_fen or 0) / 100

            await notification_svc.send_wechat(
                openid=customer.wechat_openid,
                template_id="coupon_issued",
                data={
                    "first": {"value": "感谢您的光临，为您送上专属优惠券！"},
                    "keyword1": {"value": f"¥{amount_yuan:.2f}"},
                    "keyword2": {"value": coupon_summary},
                    "keyword3": {"value": "有效期30天"},
                    "remark": {"value": "点击查看券详情，期待再次为您服务"},
                },
                url=f"/pages/coupon/list?source=post_payment&order={str(order.id)[:8]}",
            )
        except (ConnectionError, TimeoutError, ValueError, RuntimeError) as exc:
            # 推送失败不影响核心流程
            logger.warning(
                "post_payment_wechat_failed",
                customer_id=str(customer.id),
                error=str(exc),
            )
