"""支付网关 — 收钱吧/拉卡拉聚合支付对接 + 多支付拆单

支持两个聚合支付 provider：
  - 收钱吧 (ShouqianbA/Upay)：默认 provider
  - 拉卡拉聚合支付：通过 lakala_client 参数启用

所有金额单位：分（fen）。
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select, func, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Order
from shared.ontology.src.enums import OrderStatus
from ..models.payment import Payment, Refund
from ..models.enums import PaymentStatus, RefundType
from .shouqianba_client import ShouqianbaClient, ShouqianbaError
from .lakala_client import LakalaClient, LakalaError

logger = structlog.get_logger()

# 需要走收钱吧的支付方式
_SQB_METHODS = {"wechat", "alipay", "unionpay"}
# 需要走拉卡拉的支付方式（与收钱吧互斥，由构造时传入的 client 决定）
_LKL_METHODS = {"wechat", "alipay", "unionpay", "yunshan"}


def _gen_payment_no() -> str:
    now = datetime.now(timezone.utc)
    return f"PAY{now.strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:4].upper()}"


def _gen_refund_no() -> str:
    now = datetime.now(timezone.utc)
    return f"REF{now.strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:4].upper()}"


class PaymentGateway:
    """支付网关 — 收钱吧/拉卡拉聚合支付对接 + 多支付拆单"""

    PAYMENT_METHODS = {
        "cash": {"name": "现金", "need_trade_no": False, "fee_rate_permil": 0},
        "wechat": {"name": "微信支付", "need_trade_no": True, "fee_rate_permil": 6},
        "alipay": {"name": "支付宝", "need_trade_no": True, "fee_rate_permil": 6},
        "unionpay": {"name": "银联", "need_trade_no": True, "fee_rate_permil": 5},
        "member_balance": {"name": "会员余额", "need_trade_no": False, "fee_rate_permil": 0},
        "credit_account": {"name": "挂账", "need_trade_no": False, "fee_rate_permil": 0},
    }

    def __init__(
        self,
        db: AsyncSession,
        tenant_id: str,
        sqb_client: Optional[ShouqianbaClient] = None,
        lakala_client: Optional[LakalaClient] = None,
    ):
        self.db = db
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")
        try:
            self.tenant_id = uuid.UUID(tenant_id)
        except (ValueError, AttributeError) as exc:
            raise ValueError(f"tenant_id 格式非法: {tenant_id}") from exc
        self.sqb_client = sqb_client
        self.lakala_client = lakala_client

    async def create_payment(
        self,
        order_id: str,
        method: str,
        amount_fen: int,
        auth_code: Optional[str] = None,
        extra_params: Optional[dict] = None,
    ) -> dict:
        """创建支付

        extra_params（拉卡拉场景）:
          - spbill_ip:  终端IP（默认 "127.0.0.1"）
          - sub_openid: 用户openID（公众号/小程序必传）
          - notify_url: 异步通知地址
          - pay_type:   "dynamic_qr"（默认）/ "jsapi" / "mini_jsapi"
        """
        if method not in self.PAYMENT_METHODS:
            raise ValueError(f"不支持的支付方式: {method}")
        if not isinstance(amount_fen, int) or amount_fen <= 0:
            raise ValueError(f"支付金额必须为正整数(分)，当前值: {amount_fen}")

        method_config = self.PAYMENT_METHODS[method]

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

        if method in _SQB_METHODS and method_config["need_trade_no"]:
            if self.lakala_client:
                # ── 拉卡拉聚合支付 ──────────────────────────────────────────────
                subject = f"订单{order_id[:8]}"
                spbill_ip = (extra_params or {}).get("spbill_ip", "127.0.0.1")
                sub_openid = (extra_params or {}).get("sub_openid", "")
                notify_url = (extra_params or {}).get("notify_url", "")
                try:
                    if auth_code:
                        lkl_response = await self.lakala_client.micropay(
                            out_trade_no=payment_no,
                            amount_fen=amount_fen,
                            subject=subject,
                            auth_code=auth_code,
                            spbill_ip=spbill_ip,
                            notify_url=notify_url,
                        )
                        trade_no = lkl_response.get("transactionId", "")
                    else:
                        pay_type = (extra_params or {}).get("pay_type", "dynamic_qr")
                        if pay_type == "mini_jsapi":
                            lkl_response = await self.lakala_client.mini_jsapi(
                                out_trade_no=payment_no,
                                amount_fen=amount_fen,
                                subject=subject,
                                spbill_ip=spbill_ip,
                                sub_openid=sub_openid,
                                notify_url=notify_url,
                            )
                        elif pay_type == "jsapi":
                            lkl_response = await self.lakala_client.jsapi(
                                out_trade_no=payment_no,
                                amount_fen=amount_fen,
                                subject=subject,
                                spbill_ip=spbill_ip,
                                sub_openid=sub_openid,
                                notify_url=notify_url,
                            )
                        else:
                            lkl_response = await self.lakala_client.dynamic_qr(
                                out_trade_no=payment_no,
                                amount_fen=amount_fen,
                                subject=subject,
                                spbill_ip=spbill_ip,
                                notify_url=notify_url,
                            )
                            qr_code = lkl_response.get("qrUrl", "")
                        trade_no = lkl_response.get("transactionId", "")
                except LakalaError as exc:
                    logger.error(
                        "lakala_payment_failed",
                        payment_no=payment_no,
                        method=method,
                        amount_fen=amount_fen,
                        error=str(exc),
                        rsp_code=exc.rsp_code,
                    )
                    raise RuntimeError(f"拉卡拉支付失败: {exc}") from exc

            elif self.sqb_client:
                # ── 收钱吧聚合支付 ──────────────────────────────────────────────
                subject = f"订单{order_id[:8]}"
                try:
                    if auth_code:
                        sqb_response = await self.sqb_client.pay(
                            client_sn=payment_no,
                            total_amount=amount_fen,
                            dynamic_id=auth_code,
                            subject=subject,
                        )
                        trade_no = sqb_response.get("sn")
                    else:
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
            else:
                raise RuntimeError("支付客户端未配置（收钱吧/拉卡拉均未注入），无法处理在线支付")

        fee_rate_permil: int = method_config["fee_rate_permil"]
        fee_fen = (amount_fen * fee_rate_permil + 999) // 1000

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
                "fee_rate_permil": fee_rate_permil,
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
        """退款 — 原路返回"""
        pay_uuid = uuid.UUID(payment_id)
        result = await self.db.execute(
            select(Payment).where(Payment.id == pay_uuid, Payment.tenant_id == self.tenant_id)
        )
        payment = result.scalar_one_or_none()
        if not payment:
            raise ValueError(f"支付记录不存在: {payment_id}")

        if payment.status not in (PaymentStatus.paid.value, PaymentStatus.partial_refund.value):
            raise ValueError(f"支付状态 {payment.status} 不可退款")

        if refund_amount_fen <= 0:
            raise ValueError(f"退款金额必须大于0，当前值: {refund_amount_fen}")

        existing_refunds_result = await self.db.execute(
            select(func.coalesce(func.sum(Refund.amount_fen), 0)).where(
                Refund.payment_id == pay_uuid,
                Refund.tenant_id == self.tenant_id,
            )
        )
        already_refunded_fen: int = existing_refunds_result.scalar_one()
        refundable_fen = payment.amount_fen - already_refunded_fen

        if refund_amount_fen > refundable_fen:
            raise ValueError(
                f"退款金额 {refund_amount_fen} 超过可退金额 {refundable_fen}"
                f"（已退 {already_refunded_fen} / 支付 {payment.amount_fen}）"
            )

        refund_no = _gen_refund_no()
        refund_trade_no = None

        if payment.method in _SQB_METHODS and payment.trade_no:
            if self.lakala_client:
                try:
                    lkl_refund_resp = await self.lakala_client.refund(
                        out_trade_no=payment.payment_no,
                        out_refund_no=refund_no,
                        refund_amount_fen=refund_amount_fen,
                        total_amount_fen=payment.amount_fen,
                        reason=reason,
                    )
                    refund_trade_no = lkl_refund_resp.get("transactionId", "")
                except LakalaError as exc:
                    logger.error(
                        "lakala_refund_failed",
                        payment_no=payment.payment_no,
                        refund_no=refund_no,
                        amount_fen=refund_amount_fen,
                        error=str(exc),
                        rsp_code=exc.rsp_code,
                    )
                    raise RuntimeError(f"拉卡拉退款失败: {exc}") from exc
            elif self.sqb_client:
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
            else:
                raise RuntimeError("支付客户端未配置，无法处理在线退款")

        total_refunded_after = already_refunded_fen + refund_amount_fen
        refund_type = (
            RefundType.full.value
            if total_refunded_after == payment.amount_fen
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

        new_status = (
            PaymentStatus.refunded.value
            if total_refunded_after == payment.amount_fen
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

    async def split_payment(self, order_id: str, splits: list[dict]) -> dict:
        """拆单支付 — 多种支付方式组合，任一失败自动回滚"""
        order_uuid = uuid.UUID(order_id)
        result = await self.db.execute(
            select(Order).where(Order.id == order_uuid, Order.tenant_id == self.tenant_id)
        )
        order = result.scalar_one_or_none()
        if not order:
            raise ValueError(f"订单不存在: {order_id}")

        if not splits:
            raise ValueError("拆单列表不能为空")

        for idx, s in enumerate(splits):
            if "method" not in s or "amount_fen" not in s:
                raise ValueError(f"拆单第{idx+1}项缺少 method 或 amount_fen")
            if not isinstance(s["amount_fen"], int) or s["amount_fen"] <= 0:
                raise ValueError(f"拆单第{idx+1}项金额必须为正整数(分)")

        total_split = sum(s["amount_fen"] for s in splits)
        if total_split != order.final_amount_fen:
            raise ValueError(f"拆单总额 {total_split} != 订单应付 {order.final_amount_fen}")

        payment_records = []
        total_fee_fen = 0

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
            except (ValueError, RuntimeError) as e:
                logger.error("split_payment_failed", order_id=order_id, failed_index=i, error=str(e))
                rollback_errors: list[str] = []

                for pay_rec in payment_records:
                    pid = pay_rec["payment_id"]
                    pay_q = await self.db.execute(
                        select(Payment).where(Payment.id == uuid.UUID(pid))
                    )
                    pay = pay_q.scalar_one_or_none()
                    if not pay:
                        continue

                    if pay.method in _SQB_METHODS:
                        if self.lakala_client:
                            try:
                                await self.lakala_client.close(pay.payment_no)
                                logger.info("split_rollback_lkl_close_ok", payment_no=pay.payment_no)
                            except LakalaError as close_err:
                                try:
                                    rollback_refund_no = _gen_refund_no()
                                    await self.lakala_client.refund(
                                        out_trade_no=pay.payment_no,
                                        out_refund_no=rollback_refund_no,
                                        refund_amount_fen=pay.amount_fen,
                                        total_amount_fen=pay.amount_fen,
                                    )
                                    logger.info("split_rollback_lkl_refund_ok", payment_no=pay.payment_no)
                                except LakalaError as refund_err:
                                    rollback_errors.append(
                                        f"{pay.payment_no}: 拉卡拉关单失败({close_err})，退款也失败({refund_err})"
                                    )
                        elif pay.trade_no and self.sqb_client:
                            try:
                                await self.sqb_client.cancel(pay.trade_no)
                            except ShouqianbaError as cancel_err:
                                try:
                                    rollback_refund_no = _gen_refund_no()
                                    await self.sqb_client.refund(
                                        sn=pay.trade_no,
                                        refund_request_no=rollback_refund_no,
                                        refund_amount=pay.amount_fen,
                                    )
                                except ShouqianbaError as refund_err:
                                    rollback_errors.append(
                                        f"{pay.payment_no}: 撤单失败({cancel_err})，退款也失败({refund_err})"
                                    )

                    pay.status = PaymentStatus.failed.value

                await self.db.flush()

                error_msg = f"第{i+1}笔支付失败: {str(e)}"
                if rollback_errors:
                    error_msg += f"; 回滚异常(需人工介入): {'; '.join(rollback_errors)}"

                return {
                    "success": False,
                    "payment_records": payment_records,
                    "total_fee_fen": total_fee_fen,
                    "error": error_msg,
                    "rollback_errors": rollback_errors,
                }

        return {
            "success": True,
            "payment_records": payment_records,
            "total_fee_fen": total_fee_fen,
        }

    async def daily_summary(self, store_id: str, biz_date: str) -> dict:
        """日汇总 — 按支付方式汇总当日流水"""
        store_uuid = uuid.UUID(store_id)
        target_date = datetime.strptime(biz_date, "%Y-%m-%d").date()

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

        payments_result = await self.db.execute(
            select(Payment).where(
                Payment.order_id.in_(order_ids),
                Payment.tenant_id == self.tenant_id,
                Payment.status.in_([PaymentStatus.paid.value, PaymentStatus.partial_refund.value]),
            )
        )
        payments = payments_result.scalars().all()

        refunds_result = await self.db.execute(
            select(Refund).where(
                Refund.order_id.in_(order_ids),
                Refund.tenant_id == self.tenant_id,
            )
        )
        refunds = refunds_result.scalars().all()

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
