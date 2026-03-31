"""支付网关 — 收钱吧聚合支付对接 + 多支付拆单

收钱吧SDK封装：微信/支付宝/银联/云闪付统一处理。
所有金额单位：分（fen）。
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select, func, cast, Date, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Order
from shared.ontology.src.enums import OrderStatus
from ..models.payment import Payment, Refund
from ..models.enums import PaymentStatus, RefundType
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

    # fee_rate_permil: 手续费千分比（整数），避免 float 精度问题
    # 例：6 表示千分之六 (0.6%)
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
    ):
        self.db = db
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")
        try:
            self.tenant_id = uuid.UUID(tenant_id)
        except (ValueError, AttributeError) as exc:
            raise ValueError(f"tenant_id 格式非法: {tenant_id}") from exc
        self.sqb_client = sqb_client

    async def create_payment(
        self,
        order_id: str,
        method: str,
        amount_fen: int,
        auth_code: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        """创建支付 — 扫码支付时 auth_code 为顾客付款码

        对于微信/支付宝/银联等在线支付，调用收钱吧 Upay API。

        idempotency_key 参数说明：
          客户端幂等键，格式建议: {device_id}-{order_id[:8]}-{unix_timestamp_seconds}
          例：pos001-a3f2b1c4-1743420000

          规则：
            - 同一笔支付操作，POS 重试时必须使用相同的幂等键
            - 不同笔支付（即使同一订单）必须使用不同的幂等键
            - 幂等键有效期 24 小时（DB 索引不自动清理，依赖 VACUUM）
            - 如果客户端不传，服务端不做幂等保护（向下兼容旧客户端）
            - failed 状态的支付记录不触发幂等命中，允许用相同 key 重试
        """
        if method not in self.PAYMENT_METHODS:
            raise ValueError(f"不支持的支付方式: {method}")
        if not isinstance(amount_fen, int) or amount_fen <= 0:
            raise ValueError(f"支付金额必须为正整数(分)，当前值: {amount_fen}")

        method_config = self.PAYMENT_METHODS[method]

        # 验证订单存在
        order_uuid = uuid.UUID(order_id)
        result = await self.db.execute(
            select(Order).where(Order.id == order_uuid, Order.tenant_id == self.tenant_id)
        )
        order = result.scalar_one_or_none()
        if not order:
            raise ValueError(f"订单不存在: {order_id}")

        # ── 幂等检查：如果相同 idempotency_key 已有非失败记录，直接返回 ────
        if idempotency_key:
            existing_result = await self.db.execute(
                text(
                    "SELECT id, payment_no, trade_no, status, "
                    "extra->>'qr_code' AS qr_code, extra->>'fee_fen' AS fee_fen "
                    "FROM payments "
                    "WHERE tenant_id = :tid AND idempotency_key = :ikey "
                    "AND status <> 'failed' "
                    "LIMIT 1"
                ),
                {"tid": str(self.tenant_id), "ikey": idempotency_key},
            )
            existing = existing_result.mappings().first()
            if existing:
                logger.info(
                    "payment.idempotent_hit",
                    idempotency_key=idempotency_key,
                    payment_no=existing["payment_no"],
                )
                return {
                    "payment_id": str(existing["id"]),
                    "payment_no": existing["payment_no"],
                    "trade_no": existing["trade_no"],
                    "qr_code": existing["qr_code"],
                    "status": existing["status"],
                    "fee_fen": int(existing["fee_fen"] or 0),
                    "idempotent": True,  # 标记本次为幂等命中，非新支付
                }

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

        # 计算手续费（整数千分比，避免 float 精度丢失）
        fee_rate_permil: int = method_config["fee_rate_permil"]
        fee_fen = (amount_fen * fee_rate_permil + 999) // 1000  # 向上取整

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
            idempotency_key=idempotency_key,
            extra={
                "fee_fen": fee_fen,
                "fee_rate_permil": fee_rate_permil,
                "qr_code": qr_code,
            },
        )
        self.db.add(payment)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            # 并发写入相同 idempotency_key 时，唯一约束触发 IntegrityError
            # 回滚当前 flush，重新查询已落盘的记录并返回（幂等命中）
            await self.db.rollback()
            if idempotency_key:
                logger.warning(
                    "payment.idempotency_conflict",
                    idempotency_key=idempotency_key,
                    payment_no=payment_no,
                    error=str(exc),
                )
                retry_result = await self.db.execute(
                    text(
                        "SELECT id, payment_no, trade_no, status, "
                        "extra->>'qr_code' AS qr_code, extra->>'fee_fen' AS fee_fen "
                        "FROM payments "
                        "WHERE tenant_id = :tid AND idempotency_key = :ikey "
                        "AND status <> 'failed' "
                        "LIMIT 1"
                    ),
                    {"tid": str(self.tenant_id), "ikey": idempotency_key},
                )
                winner = retry_result.mappings().first()
                if winner:
                    return {
                        "payment_id": str(winner["id"]),
                        "payment_no": winner["payment_no"],
                        "trade_no": winner["trade_no"],
                        "qr_code": winner["qr_code"],
                        "status": winner["status"],
                        "fee_fen": int(winner["fee_fen"] or 0),
                        "idempotent": True,
                    }
            raise SQLAlchemyError(f"支付记录写入失败（非幂等冲突）: {exc}") from exc

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

        if refund_amount_fen <= 0:
            raise ValueError(f"退款金额必须大于0，当前值: {refund_amount_fen}")

        # 查询已退款总额，防止多次部分退款累计超过支付金额
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

        # 确定退款类型（基于累计退款总额判断）
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

        # 更新支付状态（基于累计退款总额判断）
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

        if not splits:
            raise ValueError("拆单列表不能为空")

        # 逐项校验
        for idx, s in enumerate(splits):
            if "method" not in s or "amount_fen" not in s:
                raise ValueError(f"拆单第{idx+1}项缺少 method 或 amount_fen")
            if not isinstance(s["amount_fen"], int) or s["amount_fen"] <= 0:
                raise ValueError(f"拆单第{idx+1}项金额必须为正整数(分)")

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
                # 回滚：已完成的在线支付需调用收钱吧退款/撤单
                rollback_errors: list[str] = []
                for pay_rec in payment_records:
                    pid = pay_rec["payment_id"]
                    pay_q = await self.db.execute(
                        select(Payment).where(Payment.id == uuid.UUID(pid))
                    )
                    pay = pay_q.scalar_one_or_none()
                    if not pay:
                        continue

                    # 在线支付且有 trade_no，需调收钱吧撤单
                    if (
                        pay.method in _SQB_METHODS
                        and pay.trade_no
                        and self.sqb_client
                    ):
                        try:
                            await self.sqb_client.cancel(pay.trade_no)
                            logger.info(
                                "split_rollback_cancel_ok",
                                payment_no=pay.payment_no,
                                trade_no=pay.trade_no,
                            )
                        except ShouqianbaError as cancel_err:
                            # 撤单失败，尝试退款
                            try:
                                rollback_refund_no = _gen_refund_no()
                                await self.sqb_client.refund(
                                    sn=pay.trade_no,
                                    refund_request_no=rollback_refund_no,
                                    refund_amount=pay.amount_fen,
                                )
                                logger.info(
                                    "split_rollback_refund_ok",
                                    payment_no=pay.payment_no,
                                    trade_no=pay.trade_no,
                                )
                            except ShouqianbaError as refund_err:
                                rollback_errors.append(
                                    f"{pay.payment_no}: 撤单失败({cancel_err})，"
                                    f"退款也失败({refund_err})"
                                )
                                logger.error(
                                    "split_rollback_failed",
                                    payment_no=pay.payment_no,
                                    trade_no=pay.trade_no,
                                    cancel_error=str(cancel_err),
                                    refund_error=str(refund_err),
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

        # 查所有支付记录（必须带 tenant_id 过滤）
        payments_result = await self.db.execute(
            select(Payment).where(
                Payment.order_id.in_(order_ids),
                Payment.tenant_id == self.tenant_id,
                Payment.status.in_([PaymentStatus.paid.value, PaymentStatus.partial_refund.value]),
            )
        )
        payments = payments_result.scalars().all()

        # 查退款（必须带 tenant_id 过滤）
        refunds_result = await self.db.execute(
            select(Refund).where(
                Refund.order_id.in_(order_ids),
                Refund.tenant_id == self.tenant_id,
            )
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
