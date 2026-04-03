"""营收聚合 Service 层 — 业务计算逻辑

封装：
  A. 日营收快报（含按支付方式/小时分布）
  B. 多日期范围营收报表（支持 day/week/month 粒度）
  C. 支付方式对账汇总

所有金额单位：分（fen）。
禁止 broad except，最外层兜底带 exc_info=True。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from .revenue_aggregation_repository import RevenueAggregationRepository

logger = structlog.get_logger(__name__)

_PAYMENT_LABELS: dict[str, str] = {
    "cash":           "现金",
    "wechat":         "微信",
    "alipay":         "支付宝",
    "unionpay":       "银联",
    "meituan":        "美团",
    "eleme":          "饿了么",
    "douyin":         "抖音",
    "credit":         "挂账",
    "member_balance": "会员余额",
    "coupon":         "优惠券",
    "unknown":        "未知",
}


def _safe_ratio(numerator: int | float, denominator: int | float) -> float:
    return round(numerator / denominator, 4) if denominator != 0 else 0.0


def _payment_label(method: str) -> str:
    return _PAYMENT_LABELS.get(method, method)


# ─── 数据类 ──────────────────────────────────────────────────────────────────

@dataclass
class PaymentMethodSummary:
    """单个支付方式汇总"""
    method: str
    label: str
    amount_fen: int
    order_count: int
    ratio: float = 0.0


@dataclass
class HourlyBucket:
    """单小时营收桶"""
    hour: int
    order_count: int
    revenue_fen: int


@dataclass
class DailyRevenueFast:
    """日营收快报"""
    store_id: str
    biz_date: str
    gross_revenue_fen: int
    discount_fen: int
    refund_fen: int
    net_revenue_fen: int
    order_count: int
    avg_ticket_fen: int
    payment_breakdown: list[PaymentMethodSummary] = field(default_factory=list)
    hourly_breakdown: list[HourlyBucket] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "store_id": self.store_id,
            "biz_date": self.biz_date,
            "gross_revenue_fen": self.gross_revenue_fen,
            "discount_fen": self.discount_fen,
            "refund_fen": self.refund_fen,
            "net_revenue_fen": self.net_revenue_fen,
            "order_count": self.order_count,
            "avg_ticket_fen": self.avg_ticket_fen,
            "payment_breakdown": [
                {
                    "method": p.method,
                    "label": p.label,
                    "amount_fen": p.amount_fen,
                    "order_count": p.order_count,
                    "ratio": p.ratio,
                }
                for p in self.payment_breakdown
            ],
            "hourly_breakdown": [
                {
                    "hour": h.hour,
                    "order_count": h.order_count,
                    "revenue_fen": h.revenue_fen,
                }
                for h in self.hourly_breakdown
            ],
        }


@dataclass
class RevenueTrendPoint:
    """营收趋势时序数据点"""
    period: str
    revenue_fen: int
    discount_fen: int
    order_count: int


@dataclass
class RevenueRangeReport:
    """多日期范围营收报表"""
    store_id: str
    start_date: str
    end_date: str
    granularity: str
    gross_revenue_fen: int
    discount_fen: int
    refund_fen: int
    net_revenue_fen: int
    order_count: int
    avg_ticket_fen: int
    trend: list[RevenueTrendPoint] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "store_id": self.store_id,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "granularity": self.granularity,
            "summary": {
                "gross_revenue_fen": self.gross_revenue_fen,
                "discount_fen": self.discount_fen,
                "refund_fen": self.refund_fen,
                "net_revenue_fen": self.net_revenue_fen,
                "order_count": self.order_count,
                "avg_ticket_fen": self.avg_ticket_fen,
            },
            "trend": [
                {
                    "period": t.period,
                    "revenue_fen": t.revenue_fen,
                    "discount_fen": t.discount_fen,
                    "order_count": t.order_count,
                }
                for t in self.trend
            ],
        }


@dataclass
class PaymentReconciliationRow:
    """单个支付方式对账行"""
    method: str
    label: str
    order_count: int
    order_amount_fen: int   # 应收（来自 orders.final_amount_fen 汇总）
    paid_amount_fen: int    # 实收（来自 payments.amount_fen 汇总）
    refund_amount_fen: int  # 退款（来自 refunds.amount_fen 汇总）
    net_fen: int            # 净实收 = paid - refund
    diff_fen: int           # 差异 = paid - order_amount（正=多收，负=少收）


@dataclass
class PaymentReconciliationReport:
    """支付方式对账报表"""
    store_id: str
    start_date: str
    end_date: str
    total_order_amount_fen: int
    total_paid_amount_fen: int
    total_refund_amount_fen: int
    total_net_fen: int
    total_diff_fen: int
    rows: list[PaymentReconciliationRow] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "store_id": self.store_id,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "totals": {
                "order_amount_fen": self.total_order_amount_fen,
                "paid_amount_fen": self.total_paid_amount_fen,
                "refund_amount_fen": self.total_refund_amount_fen,
                "net_fen": self.total_net_fen,
                "diff_fen": self.total_diff_fen,
            },
            "rows": [
                {
                    "method": r.method,
                    "label": r.label,
                    "order_count": r.order_count,
                    "order_amount_fen": r.order_amount_fen,
                    "paid_amount_fen": r.paid_amount_fen,
                    "refund_amount_fen": r.refund_amount_fen,
                    "net_fen": r.net_fen,
                    "diff_fen": r.diff_fen,
                }
                for r in self.rows
            ],
        }


# ─── Service ─────────────────────────────────────────────────────────────────

class RevenueAggregationService:
    """营收聚合服务

    所有公共方法显式接收 tenant_id，配合 RLS 双重隔离。
    """

    def __init__(self) -> None:
        self._repo = RevenueAggregationRepository()

    # ── A. 日营收快报 ─────────────────────────────────────────────

    async def get_daily_revenue_fast(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        biz_date: date,
        db: AsyncSession,
    ) -> DailyRevenueFast:
        """计算日营收快报

        流程：
        1. 从 orders 表聚合毛收、折扣、订单数
        2. 从 payments 表获取支付方式分布
        3. 从 refunds 表获取退款额
        4. 计算净营收 = 毛收 - 折扣 - 退款
        5. 从 orders 表计算小时分布
        """
        log = logger.bind(
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            biz_date=str(biz_date),
        )

        # 1. 订单汇总
        summary = await self._repo.fetch_daily_order_summary(
            tenant_id, store_id, biz_date, db
        )
        gross_revenue_fen = summary["gross_revenue_fen"]
        discount_fen = summary["discount_fen"]
        order_count = summary["order_count"]

        # 2. 支付方式分布
        payment_rows = await self._repo.fetch_payment_breakdown(
            tenant_id, store_id, biz_date, db
        )
        total_paid = sum(r["amount_fen"] for r in payment_rows)
        payment_breakdown = [
            PaymentMethodSummary(
                method=r["method"],
                label=_payment_label(r["method"]),
                amount_fen=r["amount_fen"],
                order_count=r["order_count"],
                ratio=_safe_ratio(r["amount_fen"], total_paid),
            )
            for r in payment_rows
        ]

        # 3. 退款（优先从 refunds 表，fallback 到 order_items.return_flag）
        try:
            refund_fen = await self._repo.fetch_daily_refund_from_payments(
                tenant_id, store_id, biz_date, db
            )
        except Exception as exc:  # noqa: BLE001 — DB driver 级别可能有多种异常
            log.warning(
                "daily_revenue_fast.refund_from_payments_failed_fallback",
                error=str(exc),
            )
            refund_fen = await self._repo.fetch_daily_refund_from_items(
                tenant_id, store_id, biz_date, db
            )

        # 4. 净营收
        net_revenue_fen = gross_revenue_fen - discount_fen - refund_fen
        avg_ticket_fen = net_revenue_fen // order_count if order_count > 0 else 0

        # 5. 小时分布
        hourly_rows = await self._repo.fetch_hourly_breakdown(
            tenant_id, store_id, biz_date, db
        )
        hourly_breakdown = [
            HourlyBucket(
                hour=r["hour"],
                order_count=r["order_count"],
                revenue_fen=r["revenue_fen"],
            )
            for r in hourly_rows
        ]

        log.info(
            "daily_revenue_fast.computed",
            gross_revenue_fen=gross_revenue_fen,
            discount_fen=discount_fen,
            refund_fen=refund_fen,
            net_revenue_fen=net_revenue_fen,
            order_count=order_count,
        )

        return DailyRevenueFast(
            store_id=str(store_id),
            biz_date=str(biz_date),
            gross_revenue_fen=gross_revenue_fen,
            discount_fen=discount_fen,
            refund_fen=refund_fen,
            net_revenue_fen=net_revenue_fen,
            order_count=order_count,
            avg_ticket_fen=avg_ticket_fen,
            payment_breakdown=payment_breakdown,
            hourly_breakdown=hourly_breakdown,
        )

    # ── B. 多日期范围营收报表 ─────────────────────────────────────

    async def get_revenue_range_report(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        start_date: date,
        end_date: date,
        granularity: str,
        db: AsyncSession,
    ) -> RevenueRangeReport:
        """多日期范围营收报表

        支持 day/week/month 聚合粒度，返回摘要 + 时序数据。
        """
        if granularity not in ("day", "week", "month"):
            raise ValueError(f"granularity 必须为 day/week/month，收到: {granularity!r}")

        log = logger.bind(
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            start_date=str(start_date),
            end_date=str(end_date),
            granularity=granularity,
        )

        # 区间汇总
        summary = await self._repo.fetch_range_order_summary(
            tenant_id, store_id, start_date, end_date, db
        )
        gross_revenue_fen = summary["gross_revenue_fen"]
        discount_fen = summary["discount_fen"]
        order_count = summary["order_count"]

        # 区间退款
        try:
            refund_fen = await self._repo.fetch_range_refund_from_payments(
                tenant_id, store_id, start_date, end_date, db
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "revenue_range_report.refund_query_failed_zero",
                error=str(exc),
            )
            refund_fen = 0

        net_revenue_fen = gross_revenue_fen - discount_fen - refund_fen
        avg_ticket_fen = net_revenue_fen // order_count if order_count > 0 else 0

        # 时序数据
        trend_rows = await self._repo.fetch_revenue_by_granularity(
            tenant_id, store_id, start_date, end_date, granularity, db
        )
        trend = [
            RevenueTrendPoint(
                period=r["period"],
                revenue_fen=r["revenue_fen"],
                discount_fen=r["discount_fen"],
                order_count=r["order_count"],
            )
            for r in trend_rows
        ]

        log.info(
            "revenue_range_report.computed",
            gross_revenue_fen=gross_revenue_fen,
            net_revenue_fen=net_revenue_fen,
            order_count=order_count,
            trend_points=len(trend),
        )

        return RevenueRangeReport(
            store_id=str(store_id),
            start_date=str(start_date),
            end_date=str(end_date),
            granularity=granularity,
            gross_revenue_fen=gross_revenue_fen,
            discount_fen=discount_fen,
            refund_fen=refund_fen,
            net_revenue_fen=net_revenue_fen,
            order_count=order_count,
            avg_ticket_fen=avg_ticket_fen,
            trend=trend,
        )

    # ── C. 支付方式对账 ───────────────────────────────────────────

    async def get_payment_reconciliation(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        start_date: date,
        end_date: date,
        db: AsyncSession,
    ) -> PaymentReconciliationReport:
        """支付方式对账汇总

        对每种支付方式计算：应收（订单侧）vs 实收（支付侧）vs 退款
        """
        log = logger.bind(
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            start_date=str(start_date),
            end_date=str(end_date),
        )

        rows_raw = await self._repo.fetch_payment_reconciliation(
            tenant_id, store_id, start_date, end_date, db
        )

        rows: list[PaymentReconciliationRow] = []
        for r in rows_raw:
            net_fen = r["paid_amount_fen"] - r["refund_amount_fen"]
            diff_fen = r["paid_amount_fen"] - r["order_amount_fen"]
            rows.append(
                PaymentReconciliationRow(
                    method=r["method"],
                    label=_payment_label(r["method"]),
                    order_count=r["order_count"],
                    order_amount_fen=r["order_amount_fen"],
                    paid_amount_fen=r["paid_amount_fen"],
                    refund_amount_fen=r["refund_amount_fen"],
                    net_fen=net_fen,
                    diff_fen=diff_fen,
                )
            )

        total_order_amount = sum(r.order_amount_fen for r in rows)
        total_paid = sum(r.paid_amount_fen for r in rows)
        total_refund = sum(r.refund_amount_fen for r in rows)
        total_net = total_paid - total_refund
        total_diff = total_paid - total_order_amount

        log.info(
            "payment_reconciliation.computed",
            total_order_amount_fen=total_order_amount,
            total_paid_amount_fen=total_paid,
            total_refund_amount_fen=total_refund,
            total_diff_fen=total_diff,
            row_count=len(rows),
        )

        return PaymentReconciliationReport(
            store_id=str(store_id),
            start_date=str(start_date),
            end_date=str(end_date),
            total_order_amount_fen=total_order_amount,
            total_paid_amount_fen=total_paid,
            total_refund_amount_fen=total_refund,
            total_net_fen=total_net,
            total_diff_fen=total_diff,
            rows=rows,
        )
