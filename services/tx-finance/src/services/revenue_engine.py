"""营收计算引擎 — 核心财务数据源

所有金额单位：分（fen）。金额 /100 转元仅在展示层做。
依赖 RLS + 显式 tenant_id 双重隔离，禁止跨租户访问。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import structlog
from sqlalchemy import func, select, text, and_
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Order, OrderItem, DishCategory, Dish

logger = structlog.get_logger(__name__)


def _safe_ratio(numerator: int | float, denominator: int | float) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 4)


def _day_window(biz_date: date) -> tuple[datetime, datetime]:
    """返回业务日期的 UTC 时间窗口（00:00:00 ~ 23:59:59）"""
    start = datetime.combine(biz_date, datetime.min.time()).replace(tzinfo=timezone.utc)
    end = datetime.combine(biz_date, datetime.max.time()).replace(tzinfo=timezone.utc)
    return start, end


# ─── 数据类 ──────────────────────────────────────────────────────────────────

@dataclass
class PaymentBreakdown:
    """按支付方式分类的营收明细"""
    method: str           # cash/wechat/alipay/unionpay/credit/member_balance/unknown
    label: str            # 中文标签
    amount_fen: int
    order_count: int
    ratio: float = 0.0


@dataclass
class DailyRevenue:
    """日营收汇总"""
    store_id: uuid.UUID
    biz_date: date
    gross_revenue_fen: int             # 含折扣前金额
    total_discount_fen: int            # 折扣总额
    refund_fen: int                    # 退款金额（退菜 subtotal 之和）
    net_revenue_fen: int               # 净营收 = gross - discount - refund
    order_count: int
    payment_breakdown: list[PaymentBreakdown] = field(default_factory=list)

    @property
    def avg_ticket_fen(self) -> int:
        return self.net_revenue_fen // self.order_count if self.order_count > 0 else 0


@dataclass
class CategoryRevenue:
    """按菜品分类的营收明细"""
    category_id: uuid.UUID | None
    category_name: str
    revenue_fen: int
    order_count: int
    dish_count: int
    ratio: float = 0.0


@dataclass
class ChannelRevenue:
    """按渠道（堂食/外卖/宴席）的营收明细"""
    channel: str          # dine_in/takeaway/delivery/banquet/other
    label: str            # 中文标签
    revenue_fen: int
    order_count: int
    ratio: float = 0.0


# ─── RevenueEngine ──────────────────────────────────────────────────────────

_PAYMENT_LABELS: dict[str, str] = {
    "cash":           "现金",
    "wechat":         "微信",
    "alipay":         "支付宝",
    "unionpay":       "银联",
    "credit":         "挂账",
    "member_balance": "会员余额",
    "unknown":        "未知",
}

_ORDER_TYPE_LABELS: dict[str, str] = {
    "dine_in":  "堂食",
    "takeaway": "外带",
    "delivery": "外卖",
    "banquet":  "宴席",
    "catering": "团餐",
    "retail":   "零售",
}

_COMPLETED_STATUSES = ["completed", "settled", "paid"]


class RevenueEngine:
    """营收计算引擎

    所有公共方法显式接收 tenant_id，配合 RLS 双重隔离。
    """

    # ── 公共接口 ──────────────────────────────────────────────

    async def get_daily_revenue(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        biz_date: date,
        db: AsyncSession,
    ) -> DailyRevenue:
        """计算日营收

        流程：
        1. 查询当日 status in completed/settled/paid 的订单，汇总毛收、折扣、单量
        2. 按 order_metadata.payment_method 分类汇总支付方式（含比率）
        3. 计算退菜金额（order_items where return_flag=True）
        4. 净营收 = 毛收 - 折扣 - 退款
        """
        log = logger.bind(
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            biz_date=str(biz_date),
        )
        start_dt, end_dt = _day_window(biz_date)

        # ── 1. 订单汇总 ──────────────────────────────────────
        agg_result = await db.execute(
            select(
                func.coalesce(func.sum(Order.total_amount_fen), 0).label("gross"),
                func.coalesce(func.sum(Order.discount_amount_fen), 0).label("discount"),
                func.count(Order.id).label("cnt"),
            )
            .where(
                and_(
                    Order.tenant_id == tenant_id,
                    Order.store_id == store_id,
                    Order.status.in_(_COMPLETED_STATUSES),
                    Order.order_time >= start_dt,
                    Order.order_time <= end_dt,
                    Order.is_deleted == False,  # noqa: E712
                )
            )
        )
        agg = agg_result.one()
        gross_revenue_fen = int(agg.gross)
        total_discount_fen = int(agg.discount)
        order_count = int(agg.cnt)

        # ── 2. 按支付方式分类 ────────────────────────────────
        payment_breakdown = await self._payment_breakdown(
            tenant_id, store_id, start_dt, end_dt, gross_revenue_fen, db
        )

        # ── 3. 退菜金额 ──────────────────────────────────────
        refund_result = await db.execute(
            select(
                func.coalesce(func.sum(OrderItem.subtotal_fen), 0)
            )
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
        refund_fen = int(refund_result.scalar_one())

        net_revenue_fen = gross_revenue_fen - total_discount_fen - refund_fen

        log.info(
            "daily_revenue_computed",
            gross_revenue_fen=gross_revenue_fen,
            total_discount_fen=total_discount_fen,
            refund_fen=refund_fen,
            net_revenue_fen=net_revenue_fen,
            order_count=order_count,
        )

        return DailyRevenue(
            store_id=store_id,
            biz_date=biz_date,
            gross_revenue_fen=gross_revenue_fen,
            total_discount_fen=total_discount_fen,
            refund_fen=refund_fen,
            net_revenue_fen=net_revenue_fen,
            order_count=order_count,
            payment_breakdown=payment_breakdown,
        )

    async def get_revenue_by_category(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        biz_date: date,
        db: AsyncSession,
    ) -> list[CategoryRevenue]:
        """按菜品分类统计营收（含分类占比）"""
        start_dt, end_dt = _day_window(biz_date)

        result = await db.execute(
            select(
                DishCategory.id.label("cat_id"),
                DishCategory.name.label("cat_name"),
                func.coalesce(func.sum(OrderItem.subtotal_fen), 0).label("revenue"),
                func.count(func.distinct(Order.id)).label("order_cnt"),
                func.count(func.distinct(OrderItem.dish_id)).label("dish_cnt"),
            )
            .join(Order, OrderItem.order_id == Order.id)
            .join(Dish, OrderItem.dish_id == Dish.id)
            .join(DishCategory, Dish.category_id == DishCategory.id)
            .where(
                and_(
                    Order.tenant_id == tenant_id,
                    Order.store_id == store_id,
                    Order.status.in_(_COMPLETED_STATUSES),
                    Order.order_time >= start_dt,
                    Order.order_time <= end_dt,
                    Order.is_deleted == False,  # noqa: E712
                )
            )
            .group_by(DishCategory.id, DishCategory.name)
            .order_by(func.sum(OrderItem.subtotal_fen).desc())
        )
        rows = result.all()
        total_rev = sum(int(r.revenue) for r in rows)

        categories = [
            CategoryRevenue(
                category_id=r.cat_id,
                category_name=r.cat_name or "未分类",
                revenue_fen=int(r.revenue),
                order_count=int(r.order_cnt),
                dish_count=int(r.dish_cnt),
                ratio=_safe_ratio(int(r.revenue), total_rev),
            )
            for r in rows
        ]
        logger.info(
            "revenue_by_category_computed",
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            biz_date=str(biz_date),
            category_count=len(categories),
            total_revenue_fen=total_rev,
        )
        return categories

    async def get_revenue_by_channel(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        biz_date: date,
        db: AsyncSession,
    ) -> list[ChannelRevenue]:
        """按渠道统计营收（堂食/外卖/宴席等）"""
        start_dt, end_dt = _day_window(biz_date)

        result = await db.execute(
            select(
                Order.order_type,
                func.coalesce(func.sum(Order.final_amount_fen), 0).label("revenue"),
                func.count(Order.id).label("order_cnt"),
            )
            .where(
                and_(
                    Order.tenant_id == tenant_id,
                    Order.store_id == store_id,
                    Order.status.in_(_COMPLETED_STATUSES),
                    Order.order_time >= start_dt,
                    Order.order_time <= end_dt,
                    Order.is_deleted == False,  # noqa: E712
                )
            )
            .group_by(Order.order_type)
            .order_by(func.sum(Order.final_amount_fen).desc())
        )
        rows = result.all()
        total_rev = sum(int(r.revenue) for r in rows)

        channels = [
            ChannelRevenue(
                channel=r.order_type or "other",
                label=_ORDER_TYPE_LABELS.get(r.order_type or "other", r.order_type or "其他"),
                revenue_fen=int(r.revenue),
                order_count=int(r.order_cnt),
                ratio=_safe_ratio(int(r.revenue), total_rev),
            )
            for r in rows
        ]
        logger.info(
            "revenue_by_channel_computed",
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            biz_date=str(biz_date),
            channel_count=len(channels),
        )
        return channels

    async def get_revenue_trend(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        start_date: date,
        end_date: date,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        """按日返回区间内的营收趋势"""
        start_dt = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=timezone.utc)
        end_dt = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=timezone.utc)

        result = await db.execute(
            select(
                func.date_trunc("day", Order.order_time).label("day"),
                func.coalesce(func.sum(Order.final_amount_fen), 0).label("revenue"),
                func.count(Order.id).label("order_cnt"),
            )
            .where(
                and_(
                    Order.tenant_id == tenant_id,
                    Order.store_id == store_id,
                    Order.status.in_(_COMPLETED_STATUSES),
                    Order.order_time >= start_dt,
                    Order.order_time <= end_dt,
                    Order.is_deleted == False,  # noqa: E712
                )
            )
            .group_by(text("1"))
            .order_by(text("1"))
        )
        return [
            {
                "date": str(r.day.date()) if r.day else "",
                "revenue_fen": int(r.revenue),
                "order_count": int(r.order_cnt),
            }
            for r in result.all()
        ]

    # ── 内部方法 ──────────────────────────────────────────────

    async def _payment_breakdown(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        start_dt: datetime,
        end_dt: datetime,
        total_revenue_fen: int,
        db: AsyncSession,
    ) -> list[PaymentBreakdown]:
        """从 order_metadata.payment_method 分组统计支付方式占比"""
        result = await db.execute(
            select(
                func.coalesce(
                    Order.order_metadata["payment_method"].as_string(),
                    text("'unknown'"),
                ).label("method"),
                func.coalesce(func.sum(Order.final_amount_fen), 0).label("amount"),
                func.count(Order.id).label("cnt"),
            )
            .where(
                and_(
                    Order.tenant_id == tenant_id,
                    Order.store_id == store_id,
                    Order.status.in_(_COMPLETED_STATUSES),
                    Order.order_time >= start_dt,
                    Order.order_time <= end_dt,
                    Order.is_deleted == False,  # noqa: E712
                )
            )
            .group_by("method")
        )
        return [
            PaymentBreakdown(
                method=r.method or "unknown",
                label=_PAYMENT_LABELS.get(r.method or "unknown", r.method or "其他"),
                amount_fen=int(r.amount),
                order_count=int(r.cnt),
                ratio=_safe_ratio(int(r.amount), total_revenue_fen),
            )
            for r in result.all()
        ]
