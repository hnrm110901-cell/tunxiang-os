"""支付网关 — 收钱吧聚合支付对接 + 多支付拆单

收钱吧SDK封装：微信/支付宝/银联/云闪付统一处理。
所有金额单位：分（fen）。
"""
import uuid
from datetime import datetime, timezone, date, timedelta
from typing import Optional

import structlog
from sqlalchemy import select, update, func, and_, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Order
from shared.ontology.src.enums import OrderStatus
from ..models.payment import Payment, Refund
from ..models.enums import PaymentMethod, PaymentStatus, RefundType
from .shouqianba_client import ShouqianbaClient, ShouqianbaError

logger = structlog.get_logger()

# 需要走收钱吧的支付方式
_SQB_METHODS = {"wechat", "alipay", "unionpay"}


def _gen_payment_no() -> str:
    now = datetime.now(timezone.utc)
    return f"PAY{now.strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:4].upper()}"


def _gen_refund_no() -> str:
    now = datetime.now(timezone.utc)
    return f"REF{now.strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:4].upper()}"


class PaymentGateway:
    """支付网关 — 收钱吧聚合支付对接 + 多支付拆单

    收钱吧SDK封装：微信/支付宝/银联/云闪付统一处理。
    """

    PAYMENT_METHODS = {
        "cash": {"name": "现金", "need_trade_no": False, "fee_rate": 0},
        "wechat": {"name": "微信支付", "need_trade_no": True, "fee_rate": 0.006},
        "alipay": {"name": "支付宝", "need_trade_no": True, "fee_rate": 0.006},
        "unionpay": {"name": "银联", "need_trade_no": True, "fee_rate": 0.005},
        "member_balance": {"name": "会员余额", "need_trade_no": False, "fee_rate": 0},
        "credit_account": {"name": "挂账", "need_trade_no": False, "fee_rate": 0},
    }

    def __init__(
        self,
        db: AsyncSession,
        tenant_id: str,
        sqb_client: Optional[ShouqianbaClient] = None,
    ):
        self.db = db
        self.tenant_id = uuid.UUID(tenant_id)
        self.sqb_client = sqb_client

    async def create_payment(
        self,
        order_id: str,
        method: str,
        amount_fen: int,
        auth_code: Optional[str] = None,
    ) -> dict:
        """创建支付 — 扫码支付时 auth_code 为顾客付款码

        对于微信/支付宝/银联等在线支付，调用收钱吧 Upay API。
        """
        if method not in self.PAYMENT_METHODS:
            raise ValueError(f"不支持的支付方式: {method}")

        method_config = self.PAYMENT_METHODS[method]

        # 验证订单存在
        order_uuid = uuid.UUID(order_id)
        result = await self.db.execute(
            select(Order).where(Order.id == order_uuid, Order.tenant_id == self.tenant_id)
        )
        order = result.scalar_one_or_none()
        if not order:
            raise ValueError(f"订单不存在: {order_id}")

        payment_no = _gen_payment_no()

        trade_no = None
        qr_code = None
        sqb_response: Optional[dict] = None

        if method in _SQB_METHODS and method_config["need_trade_no"]:
            if not self.sqb_client:
                raise RuntimeError("收钱吧客户端未配置，无法处理在线支付")

            subject = f"订单{order_id[:8]}"
            try:
                if auth_code:
                    # B扫C：收银员扫顾客付款码
                    sqb_response = await self.sqb_client.pay(
                        client_sn=payment_no,
                        total_amount=amount_fen,
                        dynamic_id=auth_code,
                        subject=subject,
                    )
                    trade_no = sqb_response.get("sn")
                else:
                    # C扫B：顾客扫店铺码
                    sqb_response = await self.sqb_client.precreate(
                        client_sn=payment_no,
                        total_amount=amount_fen,
                        subject=subject,
                    )
                    trade_no = sqb_response.get("sn")
                    qr_code = sqb_response.get("qr_code")
            except ShouqianbaError as exc:
                logger.error(
                    "sqb_payment_failed",
                    payment_no=payment_no,
                    method=method,
                    amount_fen=amount_fen,
                    error=str(exc),
                    result_code=exc.result_code,
                    error_code=exc.error_code,
                )
                raise RuntimeError(f"收钱吧支付失败: {exc}") from exc

        # 计算手续费
        fee_rate = method_config["fee_rate"]
        fee_fen = round(amount_fen * fee_rate)

        # C扫B 预下单时状态为 pending（等待顾客扫码支付）
        initial_status = PaymentStatus.paid.value
        paid_at = datetime.now(timezone.utc)
        if method in _SQB_METHODS and not auth_code:
            initial_status = PaymentStatus.pending.value if hasattr(PaymentStatus, "pending") else "pending"
            paid_at = None  # type: ignore[assignment]

        payment = Payment(
            id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            order_id=order_uuid,
            payment_no=payment_no,
            method=method,
            amount_fen=amount_fen,
            status=initial_status,
            trade_no=trade_no,
            paid_at=paid_at,
            payment_category=self._method_to_category(method),
            extra={
                "fee_fen": fee_fen,
                "fee_rate": fee_rate,
                "auth_code": auth_code,
                "qr_code": qr_code,
            },
        )
        self.db.add(payment)
        await self.db.flush()

        logger.info(
            "payment_created",
            payment_no=payment_no,
            method=method,
            amount_fen=amount_fen,
            fee_fen=fee_fen,
            trade_no=trade_no,
            status=initial_status,
        )

        return {
            "payment_id": str(payment.id),
            "payment_no": payment_no,
            "trade_no": trade_no,
            "qr_code": qr_code,
            "status": initial_status,
            "fee_fen": fee_fen,
        }

    async def query_payment(self, payment_no: str) -> dict:
        """查询支付详情"""
        result = await self.db.execute(
            select(Payment).where(
                Payment.payment_no == payment_no,
                Payment.tenant_id == self.tenant_id,
            )
        )
        payment = result.scalar_one_or_none()
        if not payment:
            raise ValueError(f"支付记录不存在: {payment_no}")

        return {
            "payment_id": str(payment.id),
            "payment_no": payment.payment_no,
            "order_id": str(payment.order_id),
            "method": payment.method,
            "amount_fen": payment.amount_fen,
            "status": payment.status,
            "trade_no": payment.trade_no,
            "paid_at": payment.paid_at.isoformat() if payment.paid_at else None,
            "extra": payment.extra,
        }

    async def refund(
        self,
        payment_id: str,
        refund_amount_fen: int,
        reason: str,
    ) -> dict:
        """退款 — 原路返回

        微信/支付宝等在线支付走原路退款（调收钱吧退款接口）。
        现金退款标记状态。
        """
        pay_uuid = uuid.UUID(payment_id)
        result = await self.db.execute(
            select(Payment).where(Payment.id == pay_uuid, Payment.tenant_id == self.tenant_id)
        )
        payment = result.scalar_one_or_none()
        if not payment:
            raise ValueError(f"支付记录不存在: {payment_id}")

        if payment.status not in (PaymentStatus.paid.value, PaymentStatus.partial_refund.value):
            raise ValueError(f"支付状态 {payment.status} 不可退款")

        if refund_amount_fen > payment.amount_fen:
            raise ValueError("退款金额超过支付金额")

        refund_no = _gen_refund_no()

        # 原路退款：在线支付走收钱吧退款API
        refund_trade_no = None
        method_config = self.PAYMENT_METHODS.get(payment.method, {})
        if payment.method in _SQB_METHODS and payment.trade_no:
            if not self.sqb_client:
                raise RuntimeError("收钱吧客户端未配置，无法处理在线退款")
            try:
                sqb_refund_resp = await self.sqb_client.refund(
                    sn=payment.trade_no,
                    refund_request_no=refund_no,
                    refund_amount=refund_amount_fen,
                )
                refund_trade_no = sqb_refund_resp.get("sn")
            except ShouqianbaError as exc:
                logger.error(
                    "sqb_refund_failed",
                    payment_no=payment.payment_no,
                    refund_no=refund_no,
                    amount_fen=refund_amount_fen,
                    error=str(exc),
                    result_code=exc.result_code,
                    error_code=exc.error_code,
                )
                raise RuntimeError(f"收钱吧退款失败: {exc}") from exc

        # 确定退款类型
        refund_type = (
            RefundType.full.value
            if refund_amount_fen == payment.amount_fen
            else RefundType.partial.value
        )

        refund_record = Refund(
            id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            order_id=payment.order_id,
            payment_id=pay_uuid,
            refund_no=refund_no,
            refund_type=refund_type,
            amount_fen=refund_amount_fen,
            reason=reason,
            refunded_at=datetime.now(timezone.utc),
            trade_no=refund_trade_no,
        )
        self.db.add(refund_record)

        # 更新支付状态
        new_status = (
            PaymentStatus.refunded.value
            if refund_amount_fen == payment.amount_fen
            else PaymentStatus.partial_refund.value
        )
        payment.status = new_status

        await self.db.flush()

        logger.info(
            "refund_processed",
            refund_no=refund_no,
            payment_no=payment.payment_no,
            amount_fen=refund_amount_fen,
            refund_type=refund_type,
        )

        return {
            "refund_id": str(refund_record.id),
            "refund_no": refund_no,
            "refund_trade_no": refund_trade_no,
            "amount_fen": refund_amount_fen,
            "status": new_status,
        }

    async def split_payment(
        self,
        order_id: str,
        splits: list[dict],
    ) -> dict:
        """拆单支付 — 多种支付方式组合

        Args:
            splits: [{method, amount_fen, auth_code?}]

        按顺序执行每笔支付。任一失败则回滚已成功的支付。
        """
        order_uuid = uuid.UUID(order_id)
        result = await self.db.execute(
            select(Order).where(Order.id == order_uuid, Order.tenant_id == self.tenant_id)
        )
        order = result.scalar_one_or_none()
        if not order:
            raise ValueError(f"订单不存在: {order_id}")

        # 校验总额
        total_split = sum(s["amount_fen"] for s in splits)
        if total_split != order.final_amount_fen:
            raise ValueError(
                f"拆单总额 {total_split} != 订单应付 {order.final_amount_fen}"
            )

        # 按顺序执行支付
        payment_records = []
        total_fee_fen = 0
        completed_payment_ids = []

        for i, split in enumerate(splits):
            try:
                pay_result = await self.create_payment(
                    order_id=order_id,
                    method=split["method"],
                    amount_fen=split["amount_fen"],
                    auth_code=split.get("auth_code"),
                )
                payment_records.append(pay_result)
                total_fee_fen += pay_result["fee_fen"]
                completed_payment_ids.append(pay_result["payment_id"])
            except (ValueError, RuntimeError) as e:
                # 回滚已完成的支付
                logger.error(
                    "split_payment_failed",
                    order_id=order_id,
                    failed_index=i,
                    error=str(e),
                )
                for pid in completed_payment_ids:
                    pay_q = await self.db.execute(
                        select(Payment).where(Payment.id == uuid.UUID(pid))
                    )
                    pay = pay_q.scalar_one_or_none()
                    if pay:
                        pay.status = PaymentStatus.failed.value

                await self.db.flush()
                return {
                    "success": False,
                    "payment_records": payment_records,
                    "total_fee_fen": total_fee_fen,
                    "error": f"第{i+1}笔支付失败: {str(e)}",
                }

        return {
            "success": True,
            "payment_records": payment_records,
            "total_fee_fen": total_fee_fen,
        }

    async def daily_summary(
        self,
        store_id: str,
        biz_date: str,
    ) -> dict:
        """日汇总 — 按支付方式汇总当日流水

        Args:
            biz_date: "YYYY-MM-DD"
        """
        store_uuid = uuid.UUID(store_id)
        target_date = datetime.strptime(biz_date, "%Y-%m-%d").date()

        # 查当日所有已完成订单
        orders_result = await self.db.execute(
            select(Order).where(
                Order.store_id == store_uuid,
                Order.tenant_id == self.tenant_id,
                Order.status == OrderStatus.completed.value,
                cast(Order.completed_at, Date) == target_date,
            )
        )
        orders = orders_result.scalars().all()
        order_ids = [o.id for o in orders]

        if not order_ids:
            return {
                "biz_date": biz_date,
                "store_id": store_id,
                "order_count": 0,
                "total_revenue_fen": 0,
                "total_fee_fen": 0,
                "net_revenue_fen": 0,
                "by_method": {},
            }

        # 查所有支付记录
        payments_result = await self.db.execute(
            select(Payment).where(
                Payment.order_id.in_(order_ids),
                Payment.status.in_([PaymentStatus.paid.value, PaymentStatus.partial_refund.value]),
            )
        )
        payments = payments_result.scalars().all()

        # 查退款
        refunds_result = await self.db.execute(
            select(Refund).where(Refund.order_id.in_(order_ids))
        )
        refunds = refunds_result.scalars().all()

        # 按支付方式汇总
        by_method = {}
        total_revenue = 0
        total_fee = 0

        for p in payments:
            method = p.method
            if method not in by_method:
                by_method[method] = {
                    "method": method,
                    "method_name": self.PAYMENT_METHODS.get(method, {}).get("name", method),
                    "count": 0,
                    "total_fen": 0,
                    "fee_fen": 0,
                    "net_fen": 0,
                }
            by_method[method]["count"] += 1
            by_method[method]["total_fen"] += p.amount_fen
            fee = (p.extra or {}).get("fee_fen", 0)
            by_method[method]["fee_fen"] += fee
            by_method[method]["net_fen"] += p.amount_fen - fee
            total_revenue += p.amount_fen
            total_fee += fee

        total_refund = sum(r.amount_fen for r in refunds)

        return {
            "biz_date": biz_date,
            "store_id": store_id,
            "order_count": len(orders),
            "total_revenue_fen": total_revenue,
            "total_refund_fen": total_refund,
            "total_fee_fen": total_fee,
            "net_revenue_fen": total_revenue - total_fee - total_refund,
            "by_method": by_method,
        }

    @staticmethod
    def _method_to_category(method: str) -> str:
        mapping = {
            "cash": "现金",
            "wechat": "移动支付",
            "alipay": "移动支付",
            "unionpay": "银联卡",
            "member_balance": "会员消费",
            "credit_account": "挂账",
        }
        return mapping.get(method, "other")
