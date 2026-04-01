"""日结服务 — V1迁入(165行)并增强

日结 = 营业日收尾：汇总→盘点→对账→店长说明→审核。
所有金额单位：分（fen）。
"""
import asyncio
import uuid
from datetime import datetime, timezone, date, timedelta
from typing import Optional

import structlog
from sqlalchemy import select, update, func, and_, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events import UniversalPublisher, TradeEventType

from shared.ontology.src.entities import Order
from shared.ontology.src.enums import OrderStatus
from ..models.settlement import Settlement
from ..models.payment import Payment, Refund
from ..models.enums import PaymentMethod, PaymentStatus

logger = structlog.get_logger()


class DailySettlementService:
    """日结服务 — V1迁入并增强

    日结 = 营业日收尾：汇总→盘点→对账→店长说明→审核。
    """

    SETTLEMENT_STATUS = [
        "draft",
        "counting",
        "reviewing",
        "manager_confirmed",
        "chef_confirmed",
        "submitted",
        "approved",
        "closed",
        "reopened",
    ]

    # 状态流转规则
    STATUS_TRANSITIONS = {
        "draft": ["counting"],
        "counting": ["reviewing"],
        "reviewing": ["manager_confirmed"],
        "manager_confirmed": ["chef_confirmed", "submitted"],
        "chef_confirmed": ["submitted"],
        "submitted": ["approved", "reopened"],
        "approved": ["closed"],
        "closed": ["reopened"],
        "reopened": ["draft"],
    }

    # 现金差异告警阈值（分）= ¥10
    CASH_VARIANCE_THRESHOLD_FEN = 1000

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = uuid.UUID(tenant_id)

    async def create_settlement(
        self,
        store_id: str,
        biz_date: str,
    ) -> dict:
        """创建日结草稿 — 自动汇总当日经营数据

        Args:
            biz_date: "YYYY-MM-DD"
        """
        store_uuid = uuid.UUID(store_id)
        target_date = datetime.strptime(biz_date, "%Y-%m-%d").date()

        # 检查是否已存在
        existing = await self.db.execute(
            select(Settlement).where(
                Settlement.store_id == store_uuid,
                Settlement.settlement_date == target_date,
                Settlement.tenant_id == self.tenant_id,
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError(f"日结已存在: {biz_date}")

        # 汇总订单数据
        summary = await self._aggregate_day_data(store_uuid, target_date)

        settlement = Settlement(
            id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            store_id=store_uuid,
            settlement_date=target_date,
            settlement_type="daily",
            total_revenue_fen=summary["total_revenue_fen"],
            total_discount_fen=summary["total_discount_fen"],
            total_refund_fen=summary["total_refund_fen"],
            net_revenue_fen=summary["net_revenue_fen"],
            cash_fen=summary["cash_fen"],
            wechat_fen=summary["wechat_fen"],
            alipay_fen=summary["alipay_fen"],
            unionpay_fen=summary["unionpay_fen"],
            credit_fen=summary["credit_fen"],
            member_balance_fen=summary["member_balance_fen"],
            total_orders=summary["total_orders"],
            total_guests=summary["total_guests"],
            avg_per_guest_fen=summary["avg_per_guest_fen"],
            cash_expected_fen=summary["cash_fen"],
            details={
                "status": "draft",
                "biz_date": biz_date,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "summary": summary,
            },
        )
        self.db.add(settlement)
        await self.db.flush()

        logger.info(
            "settlement_created",
            store_id=store_id,
            biz_date=biz_date,
            total_revenue=summary["total_revenue_fen"],
            total_orders=summary["total_orders"],
        )

        return self._settlement_to_dict(settlement)

    async def record_cash_count(
        self,
        settlement_id: str,
        counted_amount_fen: int,
        denomination_breakdown: Optional[dict] = None,
    ) -> dict:
        """现金盘点 — 记录实际现金并计算差异

        Args:
            denomination_breakdown: {100: 5, 50: 3, 20: 2, 10: 5, 5: 3, 1: 8, 0.5: 4}
                面额(元) → 张数
        """
        settlement = await self._get_settlement(settlement_id)

        settlement.cash_actual_fen = counted_amount_fen
        settlement.cash_diff_fen = counted_amount_fen - settlement.cash_expected_fen

        # 更新details状态
        details = settlement.details or {}
        details["status"] = "counting"
        details["cash_count"] = {
            "counted_amount_fen": counted_amount_fen,
            "expected_amount_fen": settlement.cash_expected_fen,
            "diff_fen": settlement.cash_diff_fen,
            "denomination_breakdown": denomination_breakdown,
            "counted_at": datetime.now(timezone.utc).isoformat(),
        }
        settlement.details = details

        await self.db.flush()

        logger.info(
            "cash_counted",
            settlement_id=settlement_id,
            expected=settlement.cash_expected_fen,
            actual=counted_amount_fen,
            diff=settlement.cash_diff_fen,
        )

        return {
            "settlement_id": settlement_id,
            "cash_expected_fen": settlement.cash_expected_fen,
            "cash_actual_fen": counted_amount_fen,
            "cash_diff_fen": settlement.cash_diff_fen,
            "denomination_breakdown": denomination_breakdown,
            "variance_alert": abs(settlement.cash_diff_fen) > self.CASH_VARIANCE_THRESHOLD_FEN,
        }

    async def add_manager_comment(
        self,
        settlement_id: str,
        comment: str,
        next_day_actions: list[str],
    ) -> dict:
        """店长说明 — 记录当日经营说明 + 次日跟进事项"""
        settlement = await self._get_settlement(settlement_id)

        details = settlement.details or {}
        details["status"] = "manager_confirmed"
        details["manager_comment"] = {
            "comment": comment,
            "next_day_actions": next_day_actions,
            "commented_at": datetime.now(timezone.utc).isoformat(),
        }
        settlement.details = details

        await self.db.flush()

        return {
            "settlement_id": settlement_id,
            "status": "manager_confirmed",
            "comment": comment,
            "next_day_actions": next_day_actions,
        }

    async def add_chef_comment(
        self,
        settlement_id: str,
        comment: str,
        waste_notes: list[str],
    ) -> dict:
        """厨师长说明 — 记录后厨情况 + 损耗说明"""
        settlement = await self._get_settlement(settlement_id)

        details = settlement.details or {}
        details["status"] = "chef_confirmed"
        details["chef_comment"] = {
            "comment": comment,
            "waste_notes": waste_notes,
            "commented_at": datetime.now(timezone.utc).isoformat(),
        }
        settlement.details = details

        await self.db.flush()

        return {
            "settlement_id": settlement_id,
            "status": "chef_confirmed",
            "comment": comment,
            "waste_notes": waste_notes,
        }

    async def submit_for_review(self, settlement_id: str) -> dict:
        """提交审核"""
        settlement = await self._get_settlement(settlement_id)

        details = settlement.details or {}
        current_status = details.get("status", "draft")

        if current_status not in ("manager_confirmed", "chef_confirmed"):
            raise ValueError(f"当前状态 {current_status} 不可提交审核，需先完成店长/厨师长确认")

        details["status"] = "submitted"
        details["submitted_at"] = datetime.now(timezone.utc).isoformat()
        settlement.details = details

        await self.db.flush()

        return {
            "settlement_id": settlement_id,
            "status": "submitted",
            "submitted_at": details["submitted_at"],
        }

    async def approve_settlement(
        self,
        settlement_id: str,
        reviewer_id: str,
    ) -> dict:
        """审核通过"""
        settlement = await self._get_settlement(settlement_id)

        details = settlement.details or {}
        current_status = details.get("status", "draft")

        if current_status != "submitted":
            raise ValueError(f"当前状态 {current_status} 不可审核，需先提交审核")

        details["status"] = "approved"
        details["approved_at"] = datetime.now(timezone.utc).isoformat()
        details["reviewer_id"] = reviewer_id
        settlement.details = details
        settlement.operator_id = reviewer_id
        settlement.settled_at = datetime.now(timezone.utc)

        await self.db.flush()

        logger.info(
            "settlement_approved",
            settlement_id=settlement_id,
            reviewer_id=reviewer_id,
        )

        asyncio.create_task(UniversalPublisher.publish(
            event_type=TradeEventType.DAILY_SETTLEMENT_COMPLETED,
            tenant_id=self.tenant_id,
            store_id=settlement.store_id,
            entity_id=settlement.id,
            event_data={
                "revenue_fen": settlement.total_revenue_fen,
                "order_count": settlement.total_orders,
                "store_id": str(settlement.store_id),
            },
            source_service="tx-trade",
        ))

        return {
            "settlement_id": settlement_id,
            "status": "approved",
            "reviewer_id": reviewer_id,
            "approved_at": details["approved_at"],
        }

    async def get_settlement(
        self,
        store_id: str,
        biz_date: str,
    ) -> dict:
        """查询日结详情"""
        store_uuid = uuid.UUID(store_id)
        target_date = datetime.strptime(biz_date, "%Y-%m-%d").date()

        result = await self.db.execute(
            select(Settlement).where(
                Settlement.store_id == store_uuid,
                Settlement.settlement_date == target_date,
                Settlement.tenant_id == self.tenant_id,
            )
        )
        settlement = result.scalar_one_or_none()
        if not settlement:
            raise ValueError(f"日结不存在: {store_id}/{biz_date}")

        return self._settlement_to_dict(settlement)

    async def get_settlement_history(
        self,
        store_id: str,
        days: int = 30,
    ) -> list[dict]:
        """查询日结历史"""
        store_uuid = uuid.UUID(store_id)
        cutoff = date.today() - timedelta(days=days)

        result = await self.db.execute(
            select(Settlement).where(
                Settlement.store_id == store_uuid,
                Settlement.tenant_id == self.tenant_id,
                Settlement.settlement_date >= cutoff,
            ).order_by(Settlement.settlement_date.desc())
        )
        settlements = result.scalars().all()

        return [self._settlement_to_dict(s) for s in settlements]

    async def get_settlement_warnings(
        self,
        settlement_id: str,
    ) -> list[dict]:
        """检测日结异常预警

        自动检测：
        1. 现金差异 > ¥10
        2. 异常折扣率（> 15%）
        3. 缺少店长/厨师长确认
        4. 退款异常（退款 > 营收10%）
        """
        settlement = await self._get_settlement(settlement_id)
        warnings = []

        # 1. 现金差异
        if settlement.cash_diff_fen is not None:
            if abs(settlement.cash_diff_fen) > self.CASH_VARIANCE_THRESHOLD_FEN:
                warnings.append({
                    "type": "cash_variance",
                    "severity": "high",
                    "message": f"现金差异 ¥{settlement.cash_diff_fen / 100:.2f}，超过阈值 ¥{self.CASH_VARIANCE_THRESHOLD_FEN / 100:.2f}",
                    "value": settlement.cash_diff_fen,
                    "threshold": self.CASH_VARIANCE_THRESHOLD_FEN,
                })

        # 2. 折扣率异常
        if settlement.total_revenue_fen > 0:
            discount_rate = settlement.total_discount_fen / settlement.total_revenue_fen
            if discount_rate > 0.15:
                warnings.append({
                    "type": "high_discount_rate",
                    "severity": "medium",
                    "message": f"折扣率 {discount_rate:.1%} 超过15%",
                    "value": round(discount_rate, 4),
                    "threshold": 0.15,
                })

        # 3. 退款异常
        if settlement.total_revenue_fen > 0:
            refund_rate = settlement.total_refund_fen / settlement.total_revenue_fen
            if refund_rate > 0.10:
                warnings.append({
                    "type": "high_refund_rate",
                    "severity": "high",
                    "message": f"退款率 {refund_rate:.1%} 超过10%",
                    "value": round(refund_rate, 4),
                    "threshold": 0.10,
                })

        # 4. 缺少确认
        details = settlement.details or {}
        status = details.get("status", "draft")
        if status in ("draft", "counting", "reviewing"):
            if "manager_comment" not in details:
                warnings.append({
                    "type": "missing_manager_comment",
                    "severity": "low",
                    "message": "缺少店长经营说明",
                })
            if "chef_comment" not in details:
                warnings.append({
                    "type": "missing_chef_comment",
                    "severity": "low",
                    "message": "缺少厨师长说明",
                })

        return warnings

    # ─────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────

    async def _get_settlement(self, settlement_id: str) -> Settlement:
        result = await self.db.execute(
            select(Settlement).where(
                Settlement.id == uuid.UUID(settlement_id),
                Settlement.tenant_id == self.tenant_id,
            )
        )
        settlement = result.scalar_one_or_none()
        if not settlement:
            raise ValueError(f"日结不存在: {settlement_id}")
        return settlement

    async def _aggregate_day_data(
        self,
        store_id: uuid.UUID,
        target_date: date,
    ) -> dict:
        """汇总当日经营数据"""
        # 查当日所有已完成订单
        orders_result = await self.db.execute(
            select(Order).where(
                Order.store_id == store_id,
                Order.tenant_id == self.tenant_id,
                Order.status == OrderStatus.completed.value,
                cast(Order.order_time, Date) == target_date,
            )
        )
        orders = orders_result.scalars().all()
        order_ids = [o.id for o in orders]

        total_revenue = sum(o.final_amount_fen or 0 for o in orders)
        total_discount = sum(o.discount_amount_fen or 0 for o in orders)
        total_guests = sum(o.guest_count or 1 for o in orders)

        # 按支付方式汇总
        method_totals = {
            "cash": 0,
            "wechat": 0,
            "alipay": 0,
            "unionpay": 0,
            "credit_account": 0,
            "member_balance": 0,
        }

        total_refund = 0
        if order_ids:
            payments_result = await self.db.execute(
                select(Payment).where(
                    Payment.order_id.in_(order_ids),
                    Payment.status.in_([PaymentStatus.paid.value, PaymentStatus.partial_refund.value]),
                )
            )
            payments = payments_result.scalars().all()
            for p in payments:
                if p.method in method_totals:
                    method_totals[p.method] += p.amount_fen

            # 退款汇总
            refunds_result = await self.db.execute(
                select(Refund).where(Refund.order_id.in_(order_ids))
            )
            refunds = refunds_result.scalars().all()
            total_refund = sum(r.amount_fen for r in refunds)

        net_revenue = total_revenue - total_refund
        avg_per_guest = round(total_revenue / total_guests) if total_guests > 0 else 0

        return {
            "total_revenue_fen": total_revenue,
            "total_discount_fen": total_discount,
            "total_refund_fen": total_refund,
            "net_revenue_fen": net_revenue,
            "cash_fen": method_totals["cash"],
            "wechat_fen": method_totals["wechat"],
            "alipay_fen": method_totals["alipay"],
            "unionpay_fen": method_totals["unionpay"],
            "credit_fen": method_totals["credit_account"],
            "member_balance_fen": method_totals["member_balance"],
            "total_orders": len(orders),
            "total_guests": total_guests,
            "avg_per_guest_fen": avg_per_guest,
        }

    @staticmethod
    def _settlement_to_dict(s: Settlement) -> dict:
        return {
            "id": str(s.id),
            "store_id": str(s.store_id),
            "settlement_date": s.settlement_date.isoformat() if isinstance(s.settlement_date, date) else str(s.settlement_date),
            "settlement_type": s.settlement_type,
            "status": (s.details or {}).get("status", "draft"),
            "total_revenue_fen": s.total_revenue_fen,
            "total_discount_fen": s.total_discount_fen,
            "total_refund_fen": s.total_refund_fen,
            "net_revenue_fen": s.net_revenue_fen,
            "by_method": {
                "cash": s.cash_fen,
                "wechat": s.wechat_fen,
                "alipay": s.alipay_fen,
                "unionpay": s.unionpay_fen,
                "credit": s.credit_fen,
                "member_balance": s.member_balance_fen,
            },
            "total_orders": s.total_orders,
            "total_guests": s.total_guests,
            "avg_per_guest_fen": s.avg_per_guest_fen,
            "cash_expected_fen": s.cash_expected_fen,
            "cash_actual_fen": s.cash_actual_fen,
            "cash_diff_fen": s.cash_diff_fen,
            "operator_id": s.operator_id,
            "settled_at": s.settled_at.isoformat() if s.settled_at else None,
            "details": s.details,
        }
