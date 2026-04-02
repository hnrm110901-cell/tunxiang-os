"""渠道核对服务 — 微信/支付宝/现金逐渠道对账

系统金额 vs POS记录，按渠道生成对账报告。
所有金额单位：分（fen）。
"""
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import Date, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Order
from shared.ontology.src.enums import OrderStatus

from ..models.enums import PaymentStatus
from ..models.payment import Payment

logger = structlog.get_logger()


class ChannelVerifyService:
    """渠道核对服务

    逐渠道对比系统金额 vs POS收款记录，发现差异。
    """

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = uuid.UUID(tenant_id)

    async def verify_wechat_payments(
        self,
        store_id: str,
        target_date: str,
    ) -> dict:
        """微信支付核对：系统金额 vs POS记录

        Args:
            store_id: 门店ID
            target_date: "YYYY-MM-DD"
        """
        return await self._verify_channel(store_id, target_date, "wechat")

    async def verify_alipay_payments(
        self,
        store_id: str,
        target_date: str,
    ) -> dict:
        """支付宝核对：系统金额 vs POS记录"""
        return await self._verify_channel(store_id, target_date, "alipay")

    async def verify_cash_payments(
        self,
        store_id: str,
        target_date: str,
    ) -> dict:
        """现金核对：系统金额 vs POS记录"""
        return await self._verify_channel(store_id, target_date, "cash")

    async def generate_channel_report(
        self,
        store_id: str,
        target_date: str,
    ) -> dict:
        """生成全渠道对账报告

        Returns:
            {channels: [{name, system_total_fen, pos_total_fen, variance_fen, match_rate}]}
        """
        channels_to_check = ["wechat", "alipay", "cash", "unionpay", "member_balance"]
        channel_results = []

        for channel in channels_to_check:
            result = await self._verify_channel(store_id, target_date, channel)
            channel_results.append({
                "name": channel,
                "system_total_fen": result["system_total_fen"],
                "pos_total_fen": result["pos_total_fen"],
                "variance_fen": result["variance_fen"],
                "match_rate": result["match_rate"],
                "transaction_count": result["transaction_count"],
                "matched_count": result["matched_count"],
                "unmatched_count": result["unmatched_count"],
            })

        # 汇总
        total_system = sum(c["system_total_fen"] for c in channel_results)
        total_pos = sum(c["pos_total_fen"] for c in channel_results)
        total_variance = total_system - total_pos
        overall_match_rate = (
            round(total_pos / total_system, 4)
            if total_system > 0
            else 1.0
        )

        report = {
            "store_id": store_id,
            "date": target_date,
            "channels": channel_results,
            "summary": {
                "total_system_fen": total_system,
                "total_pos_fen": total_pos,
                "total_variance_fen": total_variance,
                "overall_match_rate": overall_match_rate,
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(
            "channel_report_generated",
            store_id=store_id,
            date=target_date,
            total_system_fen=total_system,
            total_variance_fen=total_variance,
            overall_match_rate=overall_match_rate,
            tenant_id=str(self.tenant_id),
        )

        return report

    # ─────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────

    async def _verify_channel(
        self,
        store_id: str,
        target_date: str,
        channel: str,
    ) -> dict:
        """核对单个渠道

        system_total_fen: 系统订单中该渠道的支付总额
        pos_total_fen: POS支付记录中该渠道的总额（有trade_no的视为已确认）
        """
        store_uuid = uuid.UUID(store_id)
        dt = datetime.strptime(target_date, "%Y-%m-%d").date()

        # 查当日该门店所有已完成订单
        orders_result = await self.db.execute(
            select(Order.id).where(
                Order.store_id == store_uuid,
                Order.tenant_id == self.tenant_id,
                Order.status == OrderStatus.completed.value,
                cast(Order.order_time, Date) == dt,
            )
        )
        order_ids = [row[0] for row in orders_result.all()]

        if not order_ids:
            return {
                "channel": channel,
                "system_total_fen": 0,
                "pos_total_fen": 0,
                "variance_fen": 0,
                "match_rate": 1.0,
                "transaction_count": 0,
                "matched_count": 0,
                "unmatched_count": 0,
                "unmatched_items": [],
            }

        # 查该渠道所有支付记录
        payments_result = await self.db.execute(
            select(Payment).where(
                Payment.order_id.in_(order_ids),
                Payment.method == channel,
                Payment.status.in_([
                    PaymentStatus.paid.value,
                    PaymentStatus.partial_refund.value,
                ]),
            )
        )
        payments = payments_result.scalars().all()

        # 系统总额 = 所有该渠道支付记录总额
        system_total_fen = sum(p.amount_fen for p in payments)

        # POS确认总额 = 有 trade_no 的支付记录总额（现金支付全部算已确认）
        matched_payments = []
        unmatched_payments = []

        for p in payments:
            if channel == "cash" or p.trade_no:
                matched_payments.append(p)
            else:
                unmatched_payments.append(p)

        pos_total_fen = sum(p.amount_fen for p in matched_payments)
        variance_fen = system_total_fen - pos_total_fen

        match_rate = (
            round(pos_total_fen / system_total_fen, 4)
            if system_total_fen > 0
            else 1.0
        )

        unmatched_items = [
            {
                "payment_id": str(p.id),
                "payment_no": p.payment_no,
                "order_id": str(p.order_id),
                "amount_fen": p.amount_fen,
                "paid_at": p.paid_at.isoformat() if p.paid_at else None,
            }
            for p in unmatched_payments
        ]

        return {
            "channel": channel,
            "system_total_fen": system_total_fen,
            "pos_total_fen": pos_total_fen,
            "variance_fen": variance_fen,
            "match_rate": match_rate,
            "transaction_count": len(payments),
            "matched_count": len(matched_payments),
            "unmatched_count": len(unmatched_payments),
            "unmatched_items": unmatched_items,
        }
