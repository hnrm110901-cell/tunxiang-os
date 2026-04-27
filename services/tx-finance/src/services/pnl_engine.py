"""损益表计算引擎 v2 — 真实财务计算

P&L 结构（全部以分为单位）：
  gross_revenue                    — 合计营收（各渠道）
  - discount_amount                — 折扣
  = net_revenue                    — 净营收
  - food_cost                      — 食材成本（BOM + 损耗 + 活鲜死亡）
  = gross_profit                   — 毛利
  - labor_cost                     — 人工成本（排班实际工时 × 时薪 或 比率 fallback）
  - rent_cost                      — 房租（月租/当月天数）
  - utilities_cost                 — 水电（配置日均值）
  - other_cost                     — 其他费用
  = operating_profit               — 经营利润（EBIT）
  = net_profit                     — 净利润（当前与 operating_profit 相同，预留税后）

数据来源：
  orders / order_items             — 收入聚合
  cost_items                       — 成本明细（采购/损耗）
  live_seafood_weigh_records       — 活鲜称重（死亡损耗）
  fish_tank_zones                  — 鱼缸盘点
  finance_configs / Store.config   — 财务配置（成本比例/月租/水电）
  crew_shifts / employees          — 实际工时人工成本

禁止 broad except；最外层兜底必须带 exc_info=True。
所有金额：分（fen）。
"""

from __future__ import annotations

import asyncio
import calendar
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import structlog
from sqlalchemy import and_, func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events import FinanceEventType, UniversalPublisher
from shared.ontology.src.entities import Order, OrderItem, Store

logger = structlog.get_logger(__name__)

# ── 已完成订单状态 ────────────────────────────────────────────────────────────
_COMPLETED_STATUSES = ("completed", "settled", "paid")

# ── 渠道归类映射（order.channel → daily_pnl 字段）────────────────────────────
_CHANNEL_DINE_IN = ("dine_in", "table", "pos", "self_order")
_CHANNEL_TAKEAWAY = ("meituan", "eleme", "delivery", "takeaway", "douyin_delivery")
_CHANNEL_BANQUET = ("banquet", "private_room")

# ── 活鲜称重单位换算到克 ──────────────────────────────────────────────────────
_WEIGHT_TO_GRAM: dict[str, float] = {
    "kg": 1000.0,
    "g": 1.0,
    "jin": 500.0,  # 斤 = 500g
    "liang": 50.0,  # 两 = 50g
}


def _safe_ratio(numerator: int | float, denominator: int | float) -> float:
    """防零除，返回保留4位小数的浮点数。"""
    if denominator == 0:
        return 0.0
    return float(Decimal(str(numerator / denominator)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def _pct(ratio: float) -> Decimal:
    """比率转百分比，保留2位小数（用于写入 NUMERIC(5,2) 字段）。"""
    return Decimal(str(ratio * 100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _day_window(biz_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(biz_date, datetime.min.time()).replace(tzinfo=timezone.utc)
    end = datetime.combine(biz_date, datetime.max.time()).replace(tzinfo=timezone.utc)
    return start, end


# ─── 结果数据类 ───────────────────────────────────────────────────────────────


@dataclass
class ChannelRevenue:
    """按渠道分类的收入明细。"""

    dine_in_revenue_fen: int = 0
    takeaway_revenue_fen: int = 0
    banquet_revenue_fen: int = 0
    other_revenue_fen: int = 0
    discount_amount_fen: int = 0
    orders_count: int = 0


@dataclass
class FoodCostBreakdown:
    """食材成本明细。"""

    bom_cost_fen: int = 0  # BOM 理论成本（来自 order_items.food_cost_fen）
    wastage_cost_fen: int = 0  # 损耗成本（cost_items 中的 wastage 记录）
    live_seafood_death_fen: int = 0  # 活鲜死亡损耗成本


@dataclass
class DailyPnLResult:
    """日 P&L 计算结果，用于写入 daily_pnl 表。"""

    store_id: uuid.UUID
    pnl_date: date

    # 收入
    gross_revenue_fen: int
    dine_in_revenue_fen: int
    takeaway_revenue_fen: int
    banquet_revenue_fen: int
    discount_amount_fen: int
    net_revenue_fen: int

    # 成本
    food_cost_fen: int
    labor_cost_fen: int
    rent_cost_fen: int
    utilities_cost_fen: int
    other_cost_fen: int
    total_cost_fen: int

    # 利润
    gross_profit_fen: int
    gross_margin_pct: Decimal
    operating_profit_fen: int
    net_profit_fen: int
    net_margin_pct: Decimal

    # 经营指标
    orders_count: int
    avg_order_value_fen: int
    table_turnover_rate: Decimal

    # 成本明细（用于报表展示）
    food_cost_breakdown: FoodCostBreakdown = field(default_factory=FoodCostBreakdown)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "store_id": str(self.store_id),
            "pnl_date": str(self.pnl_date),
            "revenue": {
                "gross_revenue_fen": self.gross_revenue_fen,
                "dine_in_revenue_fen": self.dine_in_revenue_fen,
                "takeaway_revenue_fen": self.takeaway_revenue_fen,
                "banquet_revenue_fen": self.banquet_revenue_fen,
                "discount_amount_fen": self.discount_amount_fen,
                "net_revenue_fen": self.net_revenue_fen,
            },
            "cost": {
                "food_cost_fen": self.food_cost_fen,
                "food_cost_breakdown": {
                    "bom_cost_fen": self.food_cost_breakdown.bom_cost_fen,
                    "wastage_cost_fen": self.food_cost_breakdown.wastage_cost_fen,
                    "live_seafood_death_fen": self.food_cost_breakdown.live_seafood_death_fen,
                },
                "labor_cost_fen": self.labor_cost_fen,
                "rent_cost_fen": self.rent_cost_fen,
                "utilities_cost_fen": self.utilities_cost_fen,
                "other_cost_fen": self.other_cost_fen,
                "total_cost_fen": self.total_cost_fen,
            },
            "profit": {
                "gross_profit_fen": self.gross_profit_fen,
                "gross_margin_pct": float(self.gross_margin_pct),
                "operating_profit_fen": self.operating_profit_fen,
                "net_profit_fen": self.net_profit_fen,
                "net_margin_pct": float(self.net_margin_pct),
            },
            "kpi": {
                "orders_count": self.orders_count,
                "avg_order_value_fen": self.avg_order_value_fen,
                "table_turnover_rate": float(self.table_turnover_rate),
                "food_cost_ratio": _safe_ratio(self.food_cost_fen, self.net_revenue_fen),
                "labor_cost_ratio": _safe_ratio(self.labor_cost_fen, self.net_revenue_fen),
                "gross_margin": _safe_ratio(self.gross_profit_fen, self.net_revenue_fen),
                "operating_margin": _safe_ratio(self.operating_profit_fen, self.net_revenue_fen),
            },
            **self.extra,
        }


# ─── PnLEngine ────────────────────────────────────────────────────────────────


class PnLEngine:
    """
    日 P&L 自动计算引擎。

    数据来源：orders 表（收入） + cost_items 表（成本） + finance_configs（配置）
    + live_seafood_weigh_records（活鲜损耗） + crew_shifts / employees（人工成本）
    """

    async def calculate_daily_pnl(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        pnl_date: date,
        db: AsyncSession,
    ) -> DailyPnLResult:
        """
        计算指定门店指定日期的 P&L，并 upsert 写入 daily_pnl 表。

        事务性保证：计算全部完成后一次性写入，任何 SQLAlchemyError 导致整体回滚。

        步骤：
        1. 从 orders 聚合当日净营收（按渠道分）
        2. 计算食材成本（BOM + 损耗 + 活鲜死亡）
        3. 从 finance_configs / Store.config 读取劳动力/房租/水电配置
        4. 计算毛利/经营利润/净利润/各项率
        5. upsert daily_pnl 表
        6. 发布 DAILY_PL_GENERATED 事件
        """
        log = logger.bind(
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            pnl_date=str(pnl_date),
        )
        log.info("pnl_engine.calculate_daily_pnl.start")

        try:
            async with db.begin_nested():
                # ── 1. 收入聚合 ──────────────────────────────────────────
                channel_rev = await self._aggregate_revenue(tenant_id, store_id, pnl_date, db)

                gross_revenue_fen = (
                    channel_rev.dine_in_revenue_fen
                    + channel_rev.takeaway_revenue_fen
                    + channel_rev.banquet_revenue_fen
                    + channel_rev.other_revenue_fen
                )
                net_revenue_fen = gross_revenue_fen - channel_rev.discount_amount_fen

                # ── 2. 食材成本 ──────────────────────────────────────────
                food_breakdown = await self._calculate_food_cost_breakdown(tenant_id, store_id, pnl_date, db)
                food_cost_fen = (
                    food_breakdown.bom_cost_fen
                    + food_breakdown.wastage_cost_fen
                    + food_breakdown.live_seafood_death_fen
                )

                # ── 3. 门店配置（人工/房租/水电/其他）────────────────────
                store_cfg = await self._fetch_finance_config(tenant_id, store_id, pnl_date, db)
                days_in_month = calendar.monthrange(pnl_date.year, pnl_date.month)[1]

                labor_cost_fen = await self._compute_labor_cost(
                    tenant_id, store_id, pnl_date, net_revenue_fen, store_cfg, db
                )
                rent_cost_fen = store_cfg.get("rent_monthly_fen", 0) // days_in_month
                utilities_cost_fen = store_cfg.get("utilities_daily_fen", 0)
                other_cost_fen = store_cfg.get("other_daily_opex_fen", 0)

                total_cost_fen = food_cost_fen + labor_cost_fen + rent_cost_fen + utilities_cost_fen + other_cost_fen

                # ── 4. 利润计算 ──────────────────────────────────────────
                gross_profit_fen = net_revenue_fen - food_cost_fen
                operating_profit_fen = (
                    gross_profit_fen - labor_cost_fen - rent_cost_fen - utilities_cost_fen - other_cost_fen
                )
                net_profit_fen = operating_profit_fen  # 预留税后字段

                gross_margin_pct = _pct(_safe_ratio(gross_profit_fen, net_revenue_fen))
                net_margin_pct = _pct(_safe_ratio(net_profit_fen, net_revenue_fen))

                avg_order_value_fen = net_revenue_fen // channel_rev.orders_count if channel_rev.orders_count > 0 else 0

                # 翻台率：从 store 实体读取桌位数
                table_turnover_rate = await self._compute_table_turnover(
                    tenant_id, store_id, pnl_date, channel_rev.orders_count, db
                )

                result = DailyPnLResult(
                    store_id=store_id,
                    pnl_date=pnl_date,
                    gross_revenue_fen=gross_revenue_fen,
                    dine_in_revenue_fen=channel_rev.dine_in_revenue_fen,
                    takeaway_revenue_fen=channel_rev.takeaway_revenue_fen,
                    banquet_revenue_fen=channel_rev.banquet_revenue_fen,
                    discount_amount_fen=channel_rev.discount_amount_fen,
                    net_revenue_fen=net_revenue_fen,
                    food_cost_fen=food_cost_fen,
                    food_cost_breakdown=food_breakdown,
                    labor_cost_fen=labor_cost_fen,
                    rent_cost_fen=rent_cost_fen,
                    utilities_cost_fen=utilities_cost_fen,
                    other_cost_fen=other_cost_fen,
                    total_cost_fen=total_cost_fen,
                    gross_profit_fen=gross_profit_fen,
                    gross_margin_pct=gross_margin_pct,
                    operating_profit_fen=operating_profit_fen,
                    net_profit_fen=net_profit_fen,
                    net_margin_pct=net_margin_pct,
                    orders_count=channel_rev.orders_count,
                    avg_order_value_fen=avg_order_value_fen,
                    table_turnover_rate=table_turnover_rate,
                )

                # ── 5. upsert daily_pnl 表 ─────────────────────────────
                await self._upsert_daily_pnl(tenant_id, result, db)

        except IntegrityError as exc:
            log.error("pnl_engine.upsert.integrity_error", error=str(exc), exc_info=True)
            raise
        except SQLAlchemyError as exc:
            log.error("pnl_engine.calculate_daily_pnl.db_error", error=str(exc), exc_info=True)
            raise

        log.info(
            "pnl_engine.calculate_daily_pnl.done",
            gross_revenue_fen=gross_revenue_fen,
            net_revenue_fen=net_revenue_fen,
            food_cost_fen=food_cost_fen,
            gross_profit_fen=gross_profit_fen,
            operating_profit_fen=operating_profit_fen,
            orders_count=channel_rev.orders_count,
        )

        # ── 6. 发布事件（fire-and-forget，不阻塞主流程）─────────────────
        asyncio.create_task(
            UniversalPublisher.publish(
                event_type=FinanceEventType.DAILY_PL_GENERATED,
                tenant_id=tenant_id,
                store_id=store_id,
                entity_id=store_id,
                event_data={
                    "date": str(pnl_date),
                    "net_revenue_fen": net_revenue_fen,
                    "food_cost_fen": food_cost_fen,
                    "gross_profit_fen": gross_profit_fen,
                    "gross_margin_pct": float(gross_margin_pct),
                    "operating_profit_fen": operating_profit_fen,
                },
                source_service="tx-finance",
            )
        )

        return result

    async def sync_revenue_from_orders(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        sync_date: date,
        db: AsyncSession,
    ) -> int:
        """
        从 orders 表同步收入记录到 revenue_records 表。

        处理逻辑：
        - 折扣金额（order.discount_amount_fen）
        - 渠道分类（dine_in/meituan/eleme/banquet/self_order）
        - 团购/代金券订单：is_actual_revenue=False，actual_revenue_fen 按 85% 估算
        - 已存在记录的订单跳过（upsert by order_id）

        返回：同步的新记录数。
        """
        log = logger.bind(
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            sync_date=str(sync_date),
        )

        start_dt, end_dt = _day_window(sync_date)

        # 查询当日已完成订单
        orders_result = await db.execute(
            select(
                Order.id,
                Order.channel,
                Order.total_amount_fen,
                Order.discount_amount_fen,
                Order.payment_method,
                Order.order_time,
            ).where(
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
        orders = orders_result.fetchall()

        if not orders:
            log.info("sync_revenue_from_orders.no_orders")
            return 0

        # 获取已同步的 order_id 集合，避免重复插入
        existing_result = await db.execute(
            text("""
                SELECT order_id FROM revenue_records
                WHERE tenant_id = :tenant_id::UUID
                  AND store_id = :store_id::UUID
                  AND record_date = :record_date
                  AND is_deleted = FALSE
            """),
            {
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
                "record_date": sync_date.isoformat(),
            },
        )
        existing_order_ids = {str(r[0]) for r in existing_result.fetchall() if r[0]}

        synced_count = 0
        for order in orders:
            order_id_str = str(order.id)
            if order_id_str in existing_order_ids:
                continue

            channel = _normalize_channel(order.channel or "dine_in")
            gross_amount = int(order.total_amount_fen or 0)
            discount = int(order.discount_amount_fen or 0)
            net_amount = gross_amount - discount

            # 团购渠道（meituan/eleme）实际到账率约 85%
            is_group_buy_channel = channel in ("meituan", "eleme")
            is_actual_revenue = not is_group_buy_channel
            actual_revenue_fen = int(net_amount * 0.85) if is_group_buy_channel else net_amount

            await db.execute(
                text("""
                    INSERT INTO revenue_records
                    (tenant_id, store_id, record_date, order_id, channel,
                     gross_amount_fen, discount_fen, net_amount_fen,
                     payment_method, is_actual_revenue, actual_revenue_fen)
                    VALUES
                    (:tenant_id::UUID, :store_id::UUID, :record_date, :order_id::UUID, :channel,
                     :gross_amount, :discount, :net_amount,
                     :payment_method, :is_actual_revenue, :actual_revenue_fen)
                    ON CONFLICT (tenant_id, order_id)
                    DO UPDATE SET
                        gross_amount_fen = EXCLUDED.gross_amount_fen,
                        discount_fen = EXCLUDED.discount_fen,
                        net_amount_fen = EXCLUDED.net_amount_fen,
                        actual_revenue_fen = EXCLUDED.actual_revenue_fen
                """),
                {
                    "tenant_id": str(tenant_id),
                    "store_id": str(store_id),
                    "record_date": sync_date.isoformat(),
                    "order_id": order_id_str,
                    "channel": channel,
                    "gross_amount": gross_amount,
                    "discount": discount,
                    "net_amount": net_amount,
                    "payment_method": order.payment_method or "unknown",
                    "is_actual_revenue": is_actual_revenue,
                    "actual_revenue_fen": actual_revenue_fen,
                },
            )
            synced_count += 1

        log.info("sync_revenue_from_orders.done", synced_count=synced_count)
        return synced_count

    async def calculate_food_cost(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        cost_date: date,
        db: AsyncSession,
    ) -> int:
        """
        计算当日食材成本（分）：
        1. 从 order_items.food_cost_fen 字段聚合（BOM 成本）
        2. 加上 cost_items 表中 cost_type=wastage 的当日损耗记录
        3. 加上活鲜死亡损耗（live_seafood_weigh_records 取消/死亡记录）

        返回总食材成本（分）。
        """
        breakdown = await self._calculate_food_cost_breakdown(tenant_id, store_id, cost_date, db)
        return breakdown.bom_cost_fen + breakdown.wastage_cost_fen + breakdown.live_seafood_death_fen

    async def get_live_seafood_loss(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        loss_date: date,
        db: AsyncSession,
    ) -> int:
        """
        计算活鲜损耗成本（分）。

        方法：
        - 从 cost_items 中查 cost_type=live_seafood_death 的当日记录求和
        - 若无明细记录，则从 fish_tank_zones 读取当日盘点差异并按 alive_rate_pct 估算

        返回活鲜损耗成本（分）。
        """
        log = logger.bind(
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            loss_date=str(loss_date),
        )

        # 先查 cost_items 中已记录的活鲜死亡成本
        explicit_result = await db.execute(
            text("""
                SELECT COALESCE(SUM(amount_fen), 0)
                FROM cost_items
                WHERE tenant_id = :tenant_id::UUID
                  AND store_id = :store_id::UUID
                  AND cost_date = :cost_date
                  AND cost_type = 'live_seafood_death'
                  AND is_deleted = FALSE
            """),
            {
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
                "cost_date": loss_date.isoformat(),
            },
        )
        explicit_loss = int(explicit_result.scalar() or 0)
        if explicit_loss > 0:
            log.debug("live_seafood_loss.from_cost_items", amount_fen=explicit_loss)
            return explicit_loss

        # Fallback：从 live_seafood_weigh_records 的当日取消/死亡记录估算
        # 取消的称重记录视为活鲜损耗（顾客退单后鱼无法回池的场景）
        cancelled_result = await db.execute(
            text("""
                SELECT
                    COALESCE(SUM(r.amount_fen), 0) AS cancelled_amount,
                    COUNT(*) AS cancelled_count
                FROM live_seafood_weigh_records r
                WHERE r.tenant_id = :tenant_id::UUID
                  AND r.store_id = :store_id::UUID
                  AND r.status = 'cancelled'
                  AND r.updated_at::date = :loss_date
                  AND r.is_deleted = FALSE
            """),
            {
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
                "loss_date": loss_date.isoformat(),
            },
        )
        cancelled_row = cancelled_result.fetchone()
        cancelled_amount = int(cancelled_row[0]) if cancelled_row else 0

        # 从 fish_tank_zones 的 alive_rate_pct 估算自然死亡损耗
        # 若某鱼缸当天有盘点记录（dish.live_stock_weight_g 变化），计算差异损耗
        tank_loss_result = await db.execute(
            text("""
                SELECT
                    COALESCE(SUM(
                        d.purchase_price_fen * (1.0 - d.alive_rate_pct / 100.0)
                        * d.live_stock_weight_g / 500.0
                    ), 0) AS estimated_loss
                FROM dishes d
                JOIN fish_tank_zones tz ON tz.id = d.tank_zone_id
                WHERE d.tenant_id = :tenant_id::UUID
                  AND tz.store_id = :store_id::UUID
                  AND d.alive_rate_pct IS NOT NULL
                  AND d.alive_rate_pct < 100
                  AND d.is_deleted = FALSE
                  AND tz.is_deleted = FALSE
                  AND tz.is_active = TRUE
            """),
            {
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
            },
        )
        tank_loss = int(tank_loss_result.scalar() or 0)

        total_loss = cancelled_amount + tank_loss
        log.debug(
            "live_seafood_loss.estimated",
            cancelled_amount=cancelled_amount,
            tank_loss=tank_loss,
            total_loss=total_loss,
        )
        return total_loss

    # ─── 私有方法 ─────────────────────────────────────────────────────────────

    async def _aggregate_revenue(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        biz_date: date,
        db: AsyncSession,
    ) -> ChannelRevenue:
        """从 orders 表按渠道聚合当日收入。"""
        start_dt, end_dt = _day_window(biz_date)

        result = await db.execute(
            select(
                Order.channel,
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
            .group_by(Order.channel)
        )
        rows = result.fetchall()

        channel_rev = ChannelRevenue()
        for row in rows:
            ch = _normalize_channel(row.channel or "dine_in")
            gross = int(row.gross)
            discount = int(row.discount)
            count = int(row.cnt)

            channel_rev.orders_count += count
            channel_rev.discount_amount_fen += discount

            if ch in _CHANNEL_DINE_IN:
                channel_rev.dine_in_revenue_fen += gross
            elif ch in _CHANNEL_TAKEAWAY:
                channel_rev.takeaway_revenue_fen += gross
            elif ch in _CHANNEL_BANQUET:
                channel_rev.banquet_revenue_fen += gross
            else:
                channel_rev.other_revenue_fen += gross

        return channel_rev

    async def _calculate_food_cost_breakdown(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        cost_date: date,
        db: AsyncSession,
    ) -> FoodCostBreakdown:
        """计算食材成本三分量：BOM + 损耗 + 活鲜死亡。"""
        start_dt, end_dt = _day_window(cost_date)

        # 1. BOM 理论成本（order_items.food_cost_fen 字段）
        bom_result = await db.execute(
            select(
                func.coalesce(func.sum(OrderItem.food_cost_fen), 0).label("bom_cost"),
            )
            .join(Order, OrderItem.order_id == Order.id)
            .where(
                and_(
                    Order.tenant_id == tenant_id,
                    Order.store_id == store_id,
                    Order.status.in_(_COMPLETED_STATUSES),
                    Order.order_time >= start_dt,
                    Order.order_time <= end_dt,
                    Order.is_deleted == False,  # noqa: E712
                    OrderItem.return_flag == False,  # noqa: E712
                )
            )
        )
        bom_cost_fen = int(bom_result.scalar_one())

        # 2. 损耗成本（cost_items 表 wastage 类型）
        wastage_result = await db.execute(
            text("""
                SELECT COALESCE(SUM(amount_fen), 0)
                FROM cost_items
                WHERE tenant_id = :tenant_id::UUID
                  AND store_id = :store_id::UUID
                  AND cost_date = :cost_date
                  AND cost_type = 'wastage'
                  AND is_deleted = FALSE
            """),
            {
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
                "cost_date": cost_date.isoformat(),
            },
        )
        wastage_cost_fen = int(wastage_result.scalar() or 0)

        # 3. 活鲜死亡损耗
        live_seafood_death_fen = await self.get_live_seafood_loss(tenant_id, store_id, cost_date, db)

        return FoodCostBreakdown(
            bom_cost_fen=bom_cost_fen,
            wastage_cost_fen=wastage_cost_fen,
            live_seafood_death_fen=live_seafood_death_fen,
        )

    async def _fetch_finance_config(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        config_date: date,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """
        读取财务配置，优先从 finance_configs 表（门店专属 > 集团级），
        fallback 到 Store.config 字段。

        返回包含以下键的 dict（缺失的键有默认值）：
          rent_monthly_fen        — 月租金（分）
          utilities_daily_fen     — 日水电（分）
          other_daily_opex_fen    — 日其他费用（分）
          labor_cost_pct          — 人工成本目标比率（0-1 float）
          target_food_cost_pct    — 食材成本目标比率（0-1 float）
        """
        # 从 finance_configs 表读取，优先门店级配置，按 effective_from 取最近生效版本
        cfg_result = await db.execute(
            text("""
                SELECT config_type, value_fen, value_pct
                FROM finance_configs
                WHERE tenant_id = :tenant_id::UUID
                  AND (store_id = :store_id::UUID OR store_id IS NULL)
                  AND (effective_from IS NULL OR effective_from <= :cfg_date)
                  AND (effective_until IS NULL OR effective_until >= :cfg_date)
                  AND is_deleted = FALSE
                ORDER BY
                    CASE WHEN store_id IS NOT NULL THEN 0 ELSE 1 END,
                    effective_from DESC NULLS LAST
            """),
            {
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
                "cfg_date": config_date.isoformat(),
            },
        )
        cfg_rows = cfg_result.fetchall()

        config: dict[str, Any] = {}
        seen_types: set[str] = set()
        for row in cfg_rows:
            cfg_type = row[0]
            if cfg_type in seen_types:
                continue  # 同类型取优先级最高的（门店级 > 集团级）
            seen_types.add(cfg_type)
            if row[1] is not None:
                config[cfg_type] = int(row[1])
            elif row[2] is not None:
                config[cfg_type] = float(row[2]) / 100.0  # pct → ratio

        # Fallback：从 Store.config JSON 字段补充缺失的配置
        if len(seen_types) < 3:
            store_result = await db.execute(
                select(Store.config, Store.labor_cost_ratio_target).where(
                    and_(
                        Store.id == store_id,
                        Store.tenant_id == tenant_id,
                        Store.is_deleted == False,  # noqa: E712
                    )
                )
            )
            store_row = store_result.first()
            if store_row:
                store_cfg = store_row.config if isinstance(store_row.config, dict) else {}
                if "rent_monthly_fen" not in config:
                    config["rent_monthly_fen"] = store_cfg.get("monthly_rent_fen", 0)
                if "utilities_daily_fen" not in config:
                    monthly_util = store_cfg.get("monthly_utilities_fen", 0)
                    days = calendar.monthrange(config_date.year, config_date.month)[1]
                    config["utilities_daily_fen"] = monthly_util // days if monthly_util else 0
                if "labor_cost_pct" not in config:
                    config["labor_cost_pct"] = float(store_row.labor_cost_ratio_target or 0.25)
                if "other_daily_opex_fen" not in config:
                    config["other_daily_opex_fen"] = store_cfg.get("daily_other_opex_fen", 0)

        # 默认值兜底
        config.setdefault("rent_monthly_fen", 0)
        config.setdefault("utilities_daily_fen", 0)
        config.setdefault("other_daily_opex_fen", 0)
        config.setdefault("labor_cost_pct", 0.25)
        config.setdefault("target_food_cost_pct", 0.30)

        return config

    async def _compute_labor_cost(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        biz_date: date,
        net_revenue_fen: int,
        store_cfg: dict[str, Any],
        db: AsyncSession,
    ) -> int:
        """
        人工成本计算：
        优先从 crew_shifts 表查实际工时 × Employee.hourly_wage_fen，
        次级 fallback 到门店配置 labor_cost_pct × net_revenue。
        """
        start_dt, end_dt = _day_window(biz_date)
        try:
            result = await db.execute(
                text("""
                    SELECT COALESCE(SUM(
                        cs.actual_hours * COALESCE(e.hourly_wage_fen, 0)
                    ), 0) AS labor_cost
                    FROM crew_shifts cs
                    JOIN employees e ON e.id = cs.employee_id
                    WHERE cs.store_id = :store_id::UUID
                      AND cs.tenant_id = :tenant_id::UUID
                      AND cs.shift_start >= :start_dt
                      AND cs.shift_start <= :end_dt
                      AND cs.is_deleted = FALSE
                """),
                {
                    "store_id": str(store_id),
                    "tenant_id": str(tenant_id),
                    "start_dt": start_dt.isoformat(),
                    "end_dt": end_dt.isoformat(),
                },
            )
            labor_cost = int(result.scalar() or 0)
            if labor_cost > 0:
                return labor_cost
        except SQLAlchemyError as exc:
            logger.warning(
                "labor_cost_from_shifts.failed_fallback",
                store_id=str(store_id),
                error=str(exc),
                exc_info=True,
            )

        # Fallback：比率估算
        ratio = float(store_cfg.get("labor_cost_pct") or 0.25)
        return int(net_revenue_fen * ratio)

    async def _compute_table_turnover(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        biz_date: date,
        orders_count: int,
        db: AsyncSession,
    ) -> Decimal:
        """
        翻台率 = 完成堂食订单数 / 门店桌位数。
        门店桌位数从 Store.config.table_count 读取，缺失则返回 0。
        """
        try:
            store_result = await db.execute(
                select(Store.config).where(
                    and_(
                        Store.id == store_id,
                        Store.tenant_id == tenant_id,
                        Store.is_deleted == False,  # noqa: E712
                    )
                )
            )
            store_row = store_result.first()
            if store_row and isinstance(store_row.config, dict):
                table_count = int(store_row.config.get("table_count", 0))
                if table_count > 0:
                    ratio = Decimal(str(orders_count / table_count)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    return ratio
        except SQLAlchemyError as exc:
            logger.warning(
                "table_turnover.failed",
                store_id=str(store_id),
                error=str(exc),
                exc_info=True,
            )
        return Decimal("0.00")

    async def _upsert_daily_pnl(
        self,
        tenant_id: uuid.UUID,
        result: DailyPnLResult,
        db: AsyncSession,
    ) -> None:
        """Upsert daily_pnl 表（唯一键：tenant_id + store_id + pnl_date）。"""
        await db.execute(
            text("""
                INSERT INTO daily_pnl (
                    tenant_id, store_id, pnl_date,
                    gross_revenue_fen, dine_in_revenue_fen, takeaway_revenue_fen,
                    banquet_revenue_fen, discount_amount_fen, net_revenue_fen,
                    food_cost_fen, labor_cost_fen, rent_cost_fen,
                    utilities_cost_fen, other_cost_fen, total_cost_fen,
                    gross_profit_fen, gross_margin_pct,
                    operating_profit_fen, net_profit_fen, net_margin_pct,
                    orders_count, avg_order_value_fen, table_turnover_rate,
                    status, calculated_at
                ) VALUES (
                    :tenant_id::UUID, :store_id::UUID, :pnl_date,
                    :gross_revenue_fen, :dine_in_revenue_fen, :takeaway_revenue_fen,
                    :banquet_revenue_fen, :discount_amount_fen, :net_revenue_fen,
                    :food_cost_fen, :labor_cost_fen, :rent_cost_fen,
                    :utilities_cost_fen, :other_cost_fen, :total_cost_fen,
                    :gross_profit_fen, :gross_margin_pct,
                    :operating_profit_fen, :net_profit_fen, :net_margin_pct,
                    :orders_count, :avg_order_value_fen, :table_turnover_rate,
                    'draft', now()
                )
                ON CONFLICT (tenant_id, store_id, pnl_date)
                DO UPDATE SET
                    gross_revenue_fen       = EXCLUDED.gross_revenue_fen,
                    dine_in_revenue_fen     = EXCLUDED.dine_in_revenue_fen,
                    takeaway_revenue_fen    = EXCLUDED.takeaway_revenue_fen,
                    banquet_revenue_fen     = EXCLUDED.banquet_revenue_fen,
                    discount_amount_fen     = EXCLUDED.discount_amount_fen,
                    net_revenue_fen         = EXCLUDED.net_revenue_fen,
                    food_cost_fen           = EXCLUDED.food_cost_fen,
                    labor_cost_fen          = EXCLUDED.labor_cost_fen,
                    rent_cost_fen           = EXCLUDED.rent_cost_fen,
                    utilities_cost_fen      = EXCLUDED.utilities_cost_fen,
                    other_cost_fen          = EXCLUDED.other_cost_fen,
                    total_cost_fen          = EXCLUDED.total_cost_fen,
                    gross_profit_fen        = EXCLUDED.gross_profit_fen,
                    gross_margin_pct        = EXCLUDED.gross_margin_pct,
                    operating_profit_fen    = EXCLUDED.operating_profit_fen,
                    net_profit_fen          = EXCLUDED.net_profit_fen,
                    net_margin_pct          = EXCLUDED.net_margin_pct,
                    orders_count            = EXCLUDED.orders_count,
                    avg_order_value_fen     = EXCLUDED.avg_order_value_fen,
                    table_turnover_rate     = EXCLUDED.table_turnover_rate,
                    calculated_at           = now(),
                    updated_at              = now()
                WHERE daily_pnl.status != 'locked'
            """),
            {
                "tenant_id": str(tenant_id),
                "store_id": str(result.store_id),
                "pnl_date": result.pnl_date.isoformat(),
                "gross_revenue_fen": result.gross_revenue_fen,
                "dine_in_revenue_fen": result.dine_in_revenue_fen,
                "takeaway_revenue_fen": result.takeaway_revenue_fen,
                "banquet_revenue_fen": result.banquet_revenue_fen,
                "discount_amount_fen": result.discount_amount_fen,
                "net_revenue_fen": result.net_revenue_fen,
                "food_cost_fen": result.food_cost_fen,
                "labor_cost_fen": result.labor_cost_fen,
                "rent_cost_fen": result.rent_cost_fen,
                "utilities_cost_fen": result.utilities_cost_fen,
                "other_cost_fen": result.other_cost_fen,
                "total_cost_fen": result.total_cost_fen,
                "gross_profit_fen": result.gross_profit_fen,
                "gross_margin_pct": float(result.gross_margin_pct),
                "operating_profit_fen": result.operating_profit_fen,
                "net_profit_fen": result.net_profit_fen,
                "net_margin_pct": float(result.net_margin_pct),
                "orders_count": result.orders_count,
                "avg_order_value_fen": result.avg_order_value_fen,
                "table_turnover_rate": float(result.table_turnover_rate),
            },
        )


# ─── 工具函数 ─────────────────────────────────────────────────────────────────


def _normalize_channel(raw_channel: str) -> str:
    """将订单渠道原始值归一化为标准渠道名。"""
    ch = (raw_channel or "").lower().strip()
    if ch in _CHANNEL_DINE_IN or ch == "dine_in":
        return "dine_in"
    if ch in ("meituan", "美团"):
        return "meituan"
    if ch in ("eleme", "ele", "饿了么"):
        return "eleme"
    if ch in ("douyin", "douyin_delivery", "抖音"):
        return "douyin_delivery"
    if ch in _CHANNEL_BANQUET or ch == "banquet":
        return "banquet"
    if ch in ("self_order", "self-order", "自助点餐"):
        return "self_order"
    return ch or "dine_in"
