"""P0 日报表引擎 — 8张必看报表

报表清单（P0）：
  1. daily_revenue_summary      营业收入汇总表
  2. payment_discount_report    门店付款折扣表
  3. cashflow_by_store           门店日现金流报表
  4. dish_sales_stats            菜品销售统计表
  5. billing_audit               账单稽核表
  6. realtime_store_stats        门店实时营业统计表
  7. category_revenue_report     分类营收报表
  8. cost_margin_report          成本毛利报表

所有金额：分（fen）。禁止 broad except，最外层兜底带 exc_info=True。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import and_, extract, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Dish, DishCategory, Order, OrderItem

logger = structlog.get_logger(__name__)

_COMPLETED = ["completed", "settled", "paid"]


def _safe_ratio(n: int | float, d: int | float) -> float:
    return round(n / d, 4) if d != 0 else 0.0


def _day_window(biz_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(biz_date, datetime.min.time()).replace(tzinfo=timezone.utc)
    end = datetime.combine(biz_date, datetime.max.time()).replace(tzinfo=timezone.utc)
    return start, end


# ─── 数据类 ──────────────────────────────────────────────────────────────────


@dataclass
class DailyRevenueSummary:
    """P0-1: 营业收入汇总表"""

    store_id: str
    biz_date: str
    gross_revenue_fen: int
    discount_fen: int
    refund_fen: int
    net_revenue_fen: int
    order_count: int
    avg_ticket_fen: int
    by_channel: list[dict[str, Any]] = field(default_factory=list)
    by_meal_period: list[dict[str, Any]] = field(default_factory=list)

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
            "by_channel": self.by_channel,
            "by_meal_period": self.by_meal_period,
        }


@dataclass
class PaymentDiscountReport:
    """P0-2: 门店付款折扣表"""

    store_id: str
    biz_date: str
    total_discount_fen: int
    discount_rate: float
    by_payment_method: list[dict[str, Any]] = field(default_factory=list)
    by_discount_type: list[dict[str, Any]] = field(default_factory=list)
    gift_amount_fen: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "store_id": self.store_id,
            "biz_date": self.biz_date,
            "total_discount_fen": self.total_discount_fen,
            "discount_rate": self.discount_rate,
            "by_payment_method": self.by_payment_method,
            "by_discount_type": self.by_discount_type,
            "gift_amount_fen": self.gift_amount_fen,
        }


@dataclass
class CashflowByStore:
    """P0-3: 门店日现金流报表"""

    store_id: str
    biz_date: str
    cash_in_fen: int  # 现金收入
    wechat_in_fen: int  # 微信收款
    alipay_in_fen: int  # 支付宝收款
    unionpay_in_fen: int  # 银联收款
    member_balance_in_fen: int  # 会员余额收款
    credit_in_fen: int  # 挂账收款
    total_in_fen: int  # 总流入
    refund_out_fen: int  # 退款流出
    net_cashflow_fen: int  # 净现金流
    payment_detail: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "store_id": self.store_id,
            "biz_date": self.biz_date,
            "inflow": {
                "cash_fen": self.cash_in_fen,
                "wechat_fen": self.wechat_in_fen,
                "alipay_fen": self.alipay_in_fen,
                "unionpay_fen": self.unionpay_in_fen,
                "member_balance_fen": self.member_balance_in_fen,
                "credit_fen": self.credit_in_fen,
                "total_fen": self.total_in_fen,
            },
            "outflow": {"refund_fen": self.refund_out_fen},
            "net_cashflow_fen": self.net_cashflow_fen,
            "payment_detail": self.payment_detail,
        }


@dataclass
class DishSalesStats:
    """P0-4: 菜品销售统计表"""

    store_id: str
    biz_date: str
    total_dish_count: int
    total_revenue_fen: int
    top_dishes: list[dict[str, Any]] = field(default_factory=list)  # 销量TOP20
    by_category: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "store_id": self.store_id,
            "biz_date": self.biz_date,
            "total_dish_count": self.total_dish_count,
            "total_revenue_fen": self.total_revenue_fen,
            "top_dishes": self.top_dishes,
            "by_category": self.by_category,
        }


@dataclass
class BillingAudit:
    """P0-5: 账单稽核表"""

    store_id: str
    audit_date: str
    order_count: int
    gross_revenue_fen: int
    discount_fen: int
    refund_fen: int
    net_revenue_fen: int
    return_count: int
    return_amount_fen: int
    gift_count: int
    gift_amount_fen: int
    abnormal_order_count: int
    margin_alert_count: int
    hourly_breakdown: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "store_id": self.store_id,
            "audit_date": self.audit_date,
            "summary": {
                "order_count": self.order_count,
                "gross_revenue_fen": self.gross_revenue_fen,
                "discount_fen": self.discount_fen,
                "refund_fen": self.refund_fen,
                "net_revenue_fen": self.net_revenue_fen,
            },
            "returns": {
                "return_count": self.return_count,
                "return_amount_fen": self.return_amount_fen,
            },
            "gifts": {
                "gift_count": self.gift_count,
                "gift_amount_fen": self.gift_amount_fen,
            },
            "alerts": {
                "abnormal_order_count": self.abnormal_order_count,
                "margin_alert_count": self.margin_alert_count,
            },
            "hourly_breakdown": self.hourly_breakdown,
        }


@dataclass
class RealtimeStoreStats:
    """P0-6: 门店实时营业统计（当日截至当前时刻）"""

    store_id: str
    as_of: str  # ISO 时间戳
    biz_date: str
    revenue_so_far_fen: int
    order_count_so_far: int
    avg_ticket_fen: int
    last_hour_revenue_fen: int
    last_hour_order_count: int
    peak_hour: str  # "14:00"
    peak_revenue_fen: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "store_id": self.store_id,
            "as_of": self.as_of,
            "biz_date": self.biz_date,
            "revenue_so_far_fen": self.revenue_so_far_fen,
            "order_count_so_far": self.order_count_so_far,
            "avg_ticket_fen": self.avg_ticket_fen,
            "last_hour": {
                "revenue_fen": self.last_hour_revenue_fen,
                "order_count": self.last_hour_order_count,
            },
            "peak_hour": self.peak_hour,
            "peak_revenue_fen": self.peak_revenue_fen,
        }


# ─── ReportEngine ─────────────────────────────────────────────────────────────

_PAYMENT_LABELS = {
    "cash": "现金",
    "wechat": "微信",
    "alipay": "支付宝",
    "unionpay": "银联",
    "credit": "挂账",
    "member_balance": "会员余额",
}
_CHANNEL_LABELS = {
    "dine_in": "堂食",
    "takeaway": "外带",
    "delivery": "外卖",
    "banquet": "宴席",
    "catering": "团餐",
    "retail": "零售",
}
_DISCOUNT_LABELS = {
    "coupon": "活动优惠",
    "vip": "会员折扣",
    "manager": "经理折扣",
    "promotion": "促销活动",
}


class ReportEngine:
    """P0 日报表引擎"""

    # ── P0-1: 营业收入汇总表 ─────────────────────────────────

    async def daily_revenue_summary(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        biz_date: date,
        db: AsyncSession,
    ) -> DailyRevenueSummary:
        """营业收入汇总：渠道分布 + 餐段分布"""
        start_dt, end_dt = _day_window(biz_date)
        log = logger.bind(tenant_id=str(tenant_id), store_id=str(store_id), biz_date=str(biz_date))

        # 总汇
        agg = await db.execute(
            select(
                func.coalesce(func.sum(Order.total_amount_fen), 0).label("gross"),
                func.coalesce(func.sum(Order.discount_amount_fen), 0).label("discount"),
                func.count(Order.id).label("cnt"),
            ).where(
                and_(
                    Order.tenant_id == tenant_id,
                    Order.store_id == store_id,
                    Order.status.in_(_COMPLETED),
                    Order.order_time >= start_dt,
                    Order.order_time <= end_dt,
                    Order.is_deleted == False,  # noqa: E712
                )
            )
        )
        row = agg.one()
        gross_fen = int(row.gross)
        discount_fen = int(row.discount)
        order_count = int(row.cnt)

        # 退菜
        refund_fen = int(
            (
                await db.execute(
                    select(func.coalesce(func.sum(OrderItem.subtotal_fen), 0))
                    .join(Order, OrderItem.order_id == Order.id)
                    .where(
                        and_(
                            Order.tenant_id == tenant_id,
                            Order.store_id == store_id,
                            Order.order_time >= start_dt,
                            Order.order_time <= end_dt,
                            Order.is_deleted == False,  # noqa: E712
                            OrderItem.return_flag == True,  # noqa: E712
                        )
                    )
                )
            ).scalar_one()
        )

        net_fen = gross_fen - discount_fen - refund_fen
        avg_ticket = net_fen // order_count if order_count > 0 else 0

        # 按渠道
        ch_rows = (
            await db.execute(
                select(
                    Order.order_type,
                    func.coalesce(func.sum(Order.final_amount_fen), 0).label("rev"),
                    func.count(Order.id).label("cnt"),
                )
                .where(
                    and_(
                        Order.tenant_id == tenant_id,
                        Order.store_id == store_id,
                        Order.status.in_(_COMPLETED),
                        Order.order_time >= start_dt,
                        Order.order_time <= end_dt,
                        Order.is_deleted == False,  # noqa: E712
                    )
                )
                .group_by(Order.order_type)
            )
        ).all()
        by_channel = [
            {
                "channel": r.order_type or "other",
                "label": _CHANNEL_LABELS.get(r.order_type or "other", r.order_type or "其他"),
                "revenue_fen": int(r.rev),
                "order_count": int(r.cnt),
                "ratio": _safe_ratio(int(r.rev), net_fen),
            }
            for r in ch_rows
        ]

        # 按小时（餐段分析）
        hr_rows = (
            await db.execute(
                select(
                    extract("hour", Order.order_time).label("hr"),
                    func.coalesce(func.sum(Order.final_amount_fen), 0).label("rev"),
                    func.count(Order.id).label("cnt"),
                )
                .where(
                    and_(
                        Order.tenant_id == tenant_id,
                        Order.store_id == store_id,
                        Order.status.in_(_COMPLETED),
                        Order.order_time >= start_dt,
                        Order.order_time <= end_dt,
                        Order.is_deleted == False,  # noqa: E712
                    )
                )
                .group_by("hr")
                .order_by("hr")
            )
        ).all()
        by_meal_period = [
            {
                "hour": f"{int(r.hr):02d}:00",
                "revenue_fen": int(r.rev),
                "order_count": int(r.cnt),
            }
            for r in hr_rows
        ]

        log.info("daily_revenue_summary_generated", net_revenue_fen=net_fen, order_count=order_count)

        return DailyRevenueSummary(
            store_id=str(store_id),
            biz_date=str(biz_date),
            gross_revenue_fen=gross_fen,
            discount_fen=discount_fen,
            refund_fen=refund_fen,
            net_revenue_fen=net_fen,
            order_count=order_count,
            avg_ticket_fen=avg_ticket,
            by_channel=by_channel,
            by_meal_period=by_meal_period,
        )

    # ── P0-2: 门店付款折扣表 ────────────────────────────────

    async def payment_discount_report(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        biz_date: date,
        db: AsyncSession,
    ) -> PaymentDiscountReport:
        """付款方式 × 折扣类型双维度报表"""
        start_dt, end_dt = _day_window(biz_date)

        # 总折扣 & 总毛收
        totals = (
            await db.execute(
                select(
                    func.coalesce(func.sum(Order.total_amount_fen), 0).label("gross"),
                    func.coalesce(func.sum(Order.discount_amount_fen), 0).label("discount"),
                ).where(
                    and_(
                        Order.tenant_id == tenant_id,
                        Order.store_id == store_id,
                        Order.status.in_(_COMPLETED),
                        Order.order_time >= start_dt,
                        Order.order_time <= end_dt,
                        Order.is_deleted == False,  # noqa: E712
                    )
                )
            )
        ).one()
        gross_fen = int(totals.gross)
        total_discount_fen = int(totals.discount)
        discount_rate = _safe_ratio(total_discount_fen, gross_fen)

        # 按支付方式
        pm_rows = (
            await db.execute(
                select(
                    func.coalesce(Order.order_metadata["payment_method"].as_string(), text("'unknown'")).label(
                        "method"
                    ),
                    func.coalesce(func.sum(Order.final_amount_fen), 0).label("amount"),
                    func.count(Order.id).label("cnt"),
                )
                .where(
                    and_(
                        Order.tenant_id == tenant_id,
                        Order.store_id == store_id,
                        Order.status.in_(_COMPLETED),
                        Order.order_time >= start_dt,
                        Order.order_time <= end_dt,
                        Order.is_deleted == False,  # noqa: E712
                    )
                )
                .group_by("method")
            )
        ).all()
        by_payment_method = [
            {
                "method": r.method or "unknown",
                "label": _PAYMENT_LABELS.get(r.method or "unknown", r.method or "其他"),
                "amount_fen": int(r.amount),
                "order_count": int(r.cnt),
                "ratio": _safe_ratio(int(r.amount), gross_fen),
            }
            for r in pm_rows
        ]

        # 按折扣类型
        dt_rows = (
            await db.execute(
                select(
                    func.coalesce(Order.discount_type, text("'other'")).label("dtype"),
                    func.coalesce(func.sum(Order.discount_amount_fen), 0).label("discount"),
                    func.count(Order.id).label("cnt"),
                )
                .where(
                    and_(
                        Order.tenant_id == tenant_id,
                        Order.store_id == store_id,
                        Order.discount_amount_fen > 0,
                        Order.order_time >= start_dt,
                        Order.order_time <= end_dt,
                        Order.is_deleted == False,  # noqa: E712
                    )
                )
                .group_by("dtype")
            )
        ).all()
        by_discount_type = [
            {
                "type": r.dtype or "other",
                "label": _DISCOUNT_LABELS.get(r.dtype or "other", r.dtype or "其他"),
                "discount_fen": int(r.discount),
                "order_count": int(r.cnt),
                "ratio": _safe_ratio(int(r.discount), total_discount_fen),
            }
            for r in dt_rows
        ]

        # 赠菜金额
        gift_fen = int(
            (
                await db.execute(
                    select(func.coalesce(func.sum(OrderItem.subtotal_fen), 0))
                    .join(Order, OrderItem.order_id == Order.id)
                    .where(
                        and_(
                            Order.tenant_id == tenant_id,
                            Order.store_id == store_id,
                            Order.order_time >= start_dt,
                            Order.order_time <= end_dt,
                            Order.is_deleted == False,  # noqa: E712
                            OrderItem.gift_flag == True,  # noqa: E712
                        )
                    )
                )
            ).scalar_one()
        )

        logger.info(
            "payment_discount_report_generated",
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            biz_date=str(biz_date),
            total_discount_fen=total_discount_fen,
        )

        return PaymentDiscountReport(
            store_id=str(store_id),
            biz_date=str(biz_date),
            total_discount_fen=total_discount_fen,
            discount_rate=discount_rate,
            by_payment_method=by_payment_method,
            by_discount_type=by_discount_type,
            gift_amount_fen=gift_fen,
        )

    # ── P0-3: 门店日现金流报表 ───────────────────────────────

    async def cashflow_by_store(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        biz_date: date,
        db: AsyncSession,
    ) -> CashflowByStore:
        """各支付渠道流入 + 退款流出 = 净现金流"""
        start_dt, end_dt = _day_window(biz_date)

        pm_rows = (
            await db.execute(
                select(
                    func.coalesce(Order.order_metadata["payment_method"].as_string(), text("'unknown'")).label(
                        "method"
                    ),
                    func.coalesce(func.sum(Order.final_amount_fen), 0).label("amount"),
                    func.count(Order.id).label("cnt"),
                )
                .where(
                    and_(
                        Order.tenant_id == tenant_id,
                        Order.store_id == store_id,
                        Order.status.in_(_COMPLETED),
                        Order.order_time >= start_dt,
                        Order.order_time <= end_dt,
                        Order.is_deleted == False,  # noqa: E712
                    )
                )
                .group_by("method")
            )
        ).all()

        pm_map: dict[str, int] = {}
        payment_detail: list[dict[str, Any]] = []
        for r in pm_rows:
            m = r.method or "unknown"
            pm_map[m] = int(r.amount)
            payment_detail.append(
                {
                    "method": m,
                    "label": _PAYMENT_LABELS.get(m, m),
                    "amount_fen": int(r.amount),
                    "order_count": int(r.cnt),
                }
            )

        total_in_fen = sum(pm_map.values())

        refund_fen = int(
            (
                await db.execute(
                    select(func.coalesce(func.sum(OrderItem.subtotal_fen), 0))
                    .join(Order, OrderItem.order_id == Order.id)
                    .where(
                        and_(
                            Order.tenant_id == tenant_id,
                            Order.store_id == store_id,
                            Order.order_time >= start_dt,
                            Order.order_time <= end_dt,
                            Order.is_deleted == False,  # noqa: E712
                            OrderItem.return_flag == True,  # noqa: E712
                        )
                    )
                )
            ).scalar_one()
        )

        logger.info(
            "cashflow_by_store_generated",
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            biz_date=str(biz_date),
            total_in_fen=total_in_fen,
            refund_fen=refund_fen,
        )

        return CashflowByStore(
            store_id=str(store_id),
            biz_date=str(biz_date),
            cash_in_fen=pm_map.get("cash", 0),
            wechat_in_fen=pm_map.get("wechat", 0),
            alipay_in_fen=pm_map.get("alipay", 0),
            unionpay_in_fen=pm_map.get("unionpay", 0),
            member_balance_in_fen=pm_map.get("member_balance", 0),
            credit_in_fen=pm_map.get("credit", 0),
            total_in_fen=total_in_fen,
            refund_out_fen=refund_fen,
            net_cashflow_fen=total_in_fen - refund_fen,
            payment_detail=payment_detail,
        )

    # ── P0-4: 菜品销售统计表 ────────────────────────────────

    async def dish_sales_stats(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        biz_date: date,
        db: AsyncSession,
        top_n: int = 20,
    ) -> DishSalesStats:
        """菜品销量 TOP-N + 按分类汇总"""
        start_dt, end_dt = _day_window(biz_date)

        # TOP-N 菜品
        dish_rows = (
            await db.execute(
                select(
                    OrderItem.dish_id,
                    OrderItem.item_name,
                    func.sum(OrderItem.quantity).label("qty"),
                    func.coalesce(func.sum(OrderItem.subtotal_fen), 0).label("revenue"),
                    func.coalesce(func.avg(OrderItem.unit_price_fen), 0).label("avg_price"),
                )
                .join(Order, OrderItem.order_id == Order.id)
                .where(
                    and_(
                        Order.tenant_id == tenant_id,
                        Order.store_id == store_id,
                        Order.status.in_(_COMPLETED),
                        Order.order_time >= start_dt,
                        Order.order_time <= end_dt,
                        Order.is_deleted == False,  # noqa: E712
                        OrderItem.gift_flag == False,  # noqa: E712  exclude gifts
                    )
                )
                .group_by(OrderItem.dish_id, OrderItem.item_name)
                .order_by(func.sum(OrderItem.quantity).desc())
                .limit(top_n)
            )
        ).all()

        total_revenue_fen = int(
            (
                await db.execute(
                    select(func.coalesce(func.sum(OrderItem.subtotal_fen), 0))
                    .join(Order, OrderItem.order_id == Order.id)
                    .where(
                        and_(
                            Order.tenant_id == tenant_id,
                            Order.store_id == store_id,
                            Order.status.in_(_COMPLETED),
                            Order.order_time >= start_dt,
                            Order.order_time <= end_dt,
                            Order.is_deleted == False,  # noqa: E712
                            OrderItem.gift_flag == False,  # noqa: E712
                        )
                    )
                )
            ).scalar_one()
        )

        total_dish_qty = int(
            (
                await db.execute(
                    select(func.coalesce(func.sum(OrderItem.quantity), 0))
                    .join(Order, OrderItem.order_id == Order.id)
                    .where(
                        and_(
                            Order.tenant_id == tenant_id,
                            Order.store_id == store_id,
                            Order.status.in_(_COMPLETED),
                            Order.order_time >= start_dt,
                            Order.order_time <= end_dt,
                            Order.is_deleted == False,  # noqa: E712
                            OrderItem.gift_flag == False,  # noqa: E712
                        )
                    )
                )
            ).scalar_one()
        )

        top_dishes = [
            {
                "dish_id": str(r.dish_id) if r.dish_id else None,
                "dish_name": r.item_name,
                "quantity": int(r.qty),
                "revenue_fen": int(r.revenue),
                "avg_price_fen": int(r.avg_price),
                "revenue_ratio": _safe_ratio(int(r.revenue), total_revenue_fen),
            }
            for r in dish_rows
        ]

        # 按分类汇总
        cat_rows = (
            await db.execute(
                select(
                    DishCategory.id.label("cat_id"),
                    DishCategory.name.label("cat_name"),
                    func.sum(OrderItem.quantity).label("qty"),
                    func.coalesce(func.sum(OrderItem.subtotal_fen), 0).label("revenue"),
                )
                .join(Order, OrderItem.order_id == Order.id)
                .join(Dish, OrderItem.dish_id == Dish.id)
                .join(DishCategory, Dish.category_id == DishCategory.id)
                .where(
                    and_(
                        Order.tenant_id == tenant_id,
                        Order.store_id == store_id,
                        Order.status.in_(_COMPLETED),
                        Order.order_time >= start_dt,
                        Order.order_time <= end_dt,
                        Order.is_deleted == False,  # noqa: E712
                        OrderItem.gift_flag == False,  # noqa: E712
                    )
                )
                .group_by(DishCategory.id, DishCategory.name)
                .order_by(func.sum(OrderItem.subtotal_fen).desc())
            )
        ).all()
        by_category = [
            {
                "category_id": str(r.cat_id) if r.cat_id else None,
                "category_name": r.cat_name or "未分类",
                "quantity": int(r.qty),
                "revenue_fen": int(r.revenue),
                "revenue_ratio": _safe_ratio(int(r.revenue), total_revenue_fen),
            }
            for r in cat_rows
        ]

        logger.info(
            "dish_sales_stats_generated",
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            biz_date=str(biz_date),
            total_dish_qty=total_dish_qty,
        )

        return DishSalesStats(
            store_id=str(store_id),
            biz_date=str(biz_date),
            total_dish_count=total_dish_qty,
            total_revenue_fen=total_revenue_fen,
            top_dishes=top_dishes,
            by_category=by_category,
        )

    # ── P0-5: 账单稽核表 ────────────────────────────────────

    async def billing_audit(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        biz_date: date,
        db: AsyncSession,
    ) -> BillingAudit:
        """账单稽核：退菜、赠菜、异常订单、毛利告警、按小时分布"""
        start_dt, end_dt = _day_window(biz_date)

        # 订单汇总
        agg = (
            await db.execute(
                select(
                    func.count(Order.id).label("cnt"),
                    func.coalesce(func.sum(Order.total_amount_fen), 0).label("gross"),
                    func.coalesce(func.sum(Order.discount_amount_fen), 0).label("discount"),
                    func.coalesce(func.sum(Order.final_amount_fen), 0).label("net"),
                ).where(
                    and_(
                        Order.tenant_id == tenant_id,
                        Order.store_id == store_id,
                        Order.status.in_(_COMPLETED),
                        Order.order_time >= start_dt,
                        Order.order_time <= end_dt,
                        Order.is_deleted == False,  # noqa: E712
                    )
                )
            )
        ).one()

        # 退菜
        ret = (
            await db.execute(
                select(
                    func.count(OrderItem.id).label("cnt"),
                    func.coalesce(func.sum(OrderItem.subtotal_fen), 0).label("amount"),
                )
                .join(Order, Order.id == OrderItem.order_id)
                .where(
                    and_(
                        Order.tenant_id == tenant_id,
                        Order.store_id == store_id,
                        Order.order_time >= start_dt,
                        Order.order_time <= end_dt,
                        Order.is_deleted == False,  # noqa: E712
                        OrderItem.return_flag == True,  # noqa: E712
                    )
                )
            )
        ).one()

        # 赠菜
        gift = (
            await db.execute(
                select(
                    func.count(OrderItem.id).label("cnt"),
                    func.coalesce(func.sum(OrderItem.subtotal_fen), 0).label("amount"),
                )
                .join(Order, Order.id == OrderItem.order_id)
                .where(
                    and_(
                        Order.tenant_id == tenant_id,
                        Order.store_id == store_id,
                        Order.order_time >= start_dt,
                        Order.order_time <= end_dt,
                        Order.is_deleted == False,  # noqa: E712
                        OrderItem.gift_flag == True,  # noqa: E712
                    )
                )
            )
        ).one()

        # 异常订单 & 毛利告警
        abnormal_count = int(
            (
                await db.execute(
                    select(func.count(Order.id)).where(
                        and_(
                            Order.tenant_id == tenant_id,
                            Order.store_id == store_id,
                            Order.order_time >= start_dt,
                            Order.order_time <= end_dt,
                            Order.abnormal_flag == True,  # noqa: E712
                        )
                    )
                )
            ).scalar_one()
        )

        margin_alert_count = int(
            (
                await db.execute(
                    select(func.count(Order.id)).where(
                        and_(
                            Order.tenant_id == tenant_id,
                            Order.store_id == store_id,
                            Order.order_time >= start_dt,
                            Order.order_time <= end_dt,
                            Order.margin_alert_flag == True,  # noqa: E712
                        )
                    )
                )
            ).scalar_one()
        )

        # 按小时
        hourly_rows = (
            await db.execute(
                select(
                    extract("hour", Order.order_time).label("hr"),
                    func.count(Order.id).label("cnt"),
                    func.coalesce(func.sum(Order.final_amount_fen), 0).label("rev"),
                )
                .where(
                    and_(
                        Order.tenant_id == tenant_id,
                        Order.store_id == store_id,
                        Order.status.in_(_COMPLETED),
                        Order.order_time >= start_dt,
                        Order.order_time <= end_dt,
                        Order.is_deleted == False,  # noqa: E712
                    )
                )
                .group_by("hr")
                .order_by("hr")
            )
        ).all()
        hourly_breakdown = [
            {"hour": f"{int(r.hr):02d}:00", "order_count": int(r.cnt), "revenue_fen": int(r.rev)} for r in hourly_rows
        ]

        refund_fen = int(ret.amount)
        net_fen = int(agg.net) - refund_fen

        logger.info(
            "billing_audit_generated",
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            biz_date=str(biz_date),
        )

        return BillingAudit(
            store_id=str(store_id),
            audit_date=str(biz_date),
            order_count=int(agg.cnt),
            gross_revenue_fen=int(agg.gross),
            discount_fen=int(agg.discount),
            refund_fen=refund_fen,
            net_revenue_fen=net_fen,
            return_count=int(ret.cnt),
            return_amount_fen=int(ret.amount),
            gift_count=int(gift.cnt),
            gift_amount_fen=int(gift.amount),
            abnormal_order_count=abnormal_count,
            margin_alert_count=margin_alert_count,
            hourly_breakdown=hourly_breakdown,
        )

    # ── P0-6: 门店实时营业统计 ──────────────────────────────

    async def realtime_store_stats(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        db: AsyncSession,
    ) -> RealtimeStoreStats:
        """当日截至当前时刻的实时营业统计"""
        now = datetime.now(timezone.utc)
        biz_date = now.date()
        start_dt, end_dt = _day_window(biz_date)
        # 截至当前时刻
        actual_end = min(now, end_dt)
        last_hour_start = now - timedelta(hours=1)

        # 今日截至现在
        agg = (
            await db.execute(
                select(
                    func.coalesce(func.sum(Order.final_amount_fen), 0).label("rev"),
                    func.count(Order.id).label("cnt"),
                ).where(
                    and_(
                        Order.tenant_id == tenant_id,
                        Order.store_id == store_id,
                        Order.status.in_(_COMPLETED),
                        Order.order_time >= start_dt,
                        Order.order_time <= actual_end,
                        Order.is_deleted == False,  # noqa: E712
                    )
                )
            )
        ).one()
        revenue_so_far = int(agg.rev)
        order_count_so_far = int(agg.cnt)
        avg_ticket = revenue_so_far // order_count_so_far if order_count_so_far > 0 else 0

        # 最近一小时
        last_hr = (
            await db.execute(
                select(
                    func.coalesce(func.sum(Order.final_amount_fen), 0).label("rev"),
                    func.count(Order.id).label("cnt"),
                ).where(
                    and_(
                        Order.tenant_id == tenant_id,
                        Order.store_id == store_id,
                        Order.status.in_(_COMPLETED),
                        Order.order_time >= last_hour_start,
                        Order.order_time <= actual_end,
                        Order.is_deleted == False,  # noqa: E712
                    )
                )
            )
        ).one()

        # 高峰小时（今日迄今）
        peak_rows = (
            await db.execute(
                select(
                    extract("hour", Order.order_time).label("hr"),
                    func.coalesce(func.sum(Order.final_amount_fen), 0).label("rev"),
                )
                .where(
                    and_(
                        Order.tenant_id == tenant_id,
                        Order.store_id == store_id,
                        Order.status.in_(_COMPLETED),
                        Order.order_time >= start_dt,
                        Order.order_time <= actual_end,
                        Order.is_deleted == False,  # noqa: E712
                    )
                )
                .group_by("hr")
                .order_by(func.sum(Order.final_amount_fen).desc())
                .limit(1)
            )
        ).first()

        peak_hour = f"{int(peak_rows.hr):02d}:00" if peak_rows else "--"
        peak_revenue = int(peak_rows.rev) if peak_rows else 0

        logger.info(
            "realtime_store_stats_generated",
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            revenue_so_far_fen=revenue_so_far,
        )

        return RealtimeStoreStats(
            store_id=str(store_id),
            as_of=now.isoformat(),
            biz_date=str(biz_date),
            revenue_so_far_fen=revenue_so_far,
            order_count_so_far=order_count_so_far,
            avg_ticket_fen=avg_ticket,
            last_hour_revenue_fen=int(last_hr.rev),
            last_hour_order_count=int(last_hr.cnt),
            peak_hour=peak_hour,
            peak_revenue_fen=peak_revenue,
        )
