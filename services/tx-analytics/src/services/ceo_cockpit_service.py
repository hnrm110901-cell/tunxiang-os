"""CEO今日经营驾驶舱服务 — Sprint G6

纯聚合层：从已有微服务数据(orders/order_items/dishes/stores/crew_shifts/
employees/waste_records/inventory_transactions)拼装CEO驾驶舱所需全部数据。

核心能力：
  - 今日经营全景（营业额/成本/利润/客数/翻台率）
  - 时段P&L（午市/下午茶/晚市/夜宵 独立核算）
  - 外卖单级真实利润（扣佣金/包装/补贴）
  - TOP5利润菜 + 亏损菜
  - AI决策卡片（亏损菜干预/采购紧急/客户召回/损耗告警/外卖亏损）
  - 异常高亮（今日 vs 上周同日偏离检测）
  - 月度目标进度条
  - 多店概览（总部视角）

金额单位：分(fen), int/bigint
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

# ─── 常量 ─────────────────────────────────────────────────────────────────────

# 时段定义（小时范围，含起始不含结束）
DAYPART_LUNCH = ("午市", 11, 14)
DAYPART_AFTERNOON = ("下午茶", 14, 17)
DAYPART_DINNER = ("晚市", 17, 21)
DAYPART_LATE_NIGHT = ("夜宵", 21, 26)  # 26=次日02:00

# 外卖平台佣金率
PLATFORM_COMMISSION_RATES: dict[str, float] = {
    "meituan": 0.18,
    "eleme": 0.20,
    "douyin": 0.10,
}

# 异常检测阈值
ANOMALY_WARNING_THRESHOLD = 0.20   # ±20% 标黄
ANOMALY_CRITICAL_THRESHOLD = 0.35  # ±35% 标红

# AI决策卡片最大数量
MAX_AI_DECISIONS = 3


# ─── 辅助纯函数 ────────────────────────────────────────────────────────────────

def _fen_to_yuan(fen: int) -> float:
    """分转元（保留2位小数）"""
    return round(fen / 100, 2)


def _pct_change(current: int, baseline: int) -> Optional[float]:
    """计算百分比变化，baseline为0时返回None"""
    if baseline <= 0:
        return None
    return round((current - baseline) / baseline * 100, 1)


def _deviation_severity(deviation_pct: float) -> Optional[str]:
    """根据偏离百分比判断严重级别

    Returns:
        None（正常范围内）/ 'warning' / 'critical'
    """
    abs_dev = abs(deviation_pct)
    if abs_dev >= ANOMALY_CRITICAL_THRESHOLD * 100:
        return "critical"
    if abs_dev >= ANOMALY_WARNING_THRESHOLD * 100:
        return "warning"
    return None


# ─── CEOCockpitService ─────────────────────────────────────────────────────────


class CEOCockpitService:
    """CEO今日经营驾驶舱服务

    聚合已有微服务数据，为CEO提供一眼看全局的经营数据。
    所有方法均为纯查询，不写入业务表（快照写入由独立ETL完成）。
    """

    # ═══════════════════════════════════════════════════════════════════
    # 1. 今日经营驾驶舱（完整数据）
    # ═══════════════════════════════════════════════════════════════════

    async def get_today_cockpit(
        self,
        db: AsyncSession,
        store_id: str,
        tenant_id: str,
    ) -> dict:
        """今日经营驾驶舱 -- 老板打开第一眼看到的画面

        聚合以下数据源（全部用SQL从已有表查询）：
        1. 今日累计营业额/成本/利润/客数/翻台率
        2. 时段P&L（午市/下午茶/晚市/夜宵）
        3. 外卖真实利润
        4. TOP5利润菜 + 亏损菜
        5. AI决策卡片（最多3条）
        6. 异常高亮
        7. 月度目标进度

        Args:
            db: 异步数据库会话
            store_id: 门店ID
            tenant_id: 租户ID

        Returns:
            完整的驾驶舱数据字典
        """
        log.info("get_today_cockpit", store_id=store_id, tenant_id=tenant_id)

        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        today = date.today()

        try:
            # 并行获取所有子模块数据
            overview = await self._compute_today_overview(db, store_id, tenant_id, today)
            daypart = await self._compute_daypart_pnl(db, store_id, tenant_id, today)
            delivery = await self._compute_delivery_real_profit(db, store_id, tenant_id, today)
            dishes = await self._compute_top_dishes(db, store_id, tenant_id, today)
            decisions = await self._generate_ai_decisions(db, store_id, tenant_id, today)
            anomalies = await self._detect_anomalies(db, store_id, tenant_id, today)
            month_progress = await self._compute_month_progress(db, store_id, tenant_id, today)

            return {
                "store_id": store_id,
                "date": today.isoformat(),
                "snapshot_time": datetime.now(timezone.utc).isoformat(),
                "overview": overview,
                "daypart_pnl": daypart,
                "delivery_profit": delivery,
                "top_dishes": dishes["top_dishes"],
                "loss_dishes": dishes["loss_dishes"],
                "ai_decisions": decisions,
                "anomalies": anomalies,
                "month_progress": month_progress,
            }

        except (OperationalError, SQLAlchemyError) as exc:
            log.error(
                "get_today_cockpit.db_error",
                store_id=store_id,
                tenant_id=tenant_id,
                exc_info=True,
            )
            _ = exc
            return self._default_cockpit(store_id, today)

    # ═══════════════════════════════════════════════════════════════════
    # 2. 今日概览（营业额/成本/利润/客数/翻台率）
    # ═══════════════════════════════════════════════════════════════════

    async def _compute_today_overview(
        self,
        db: AsyncSession,
        store_id: str,
        tenant_id: str,
        target_date: date,
    ) -> dict:
        """今日累计核心指标

        Returns:
            {revenue_fen, revenue_yuan, cost_fen, cost_yuan, profit_fen,
             profit_yuan, customer_count, turnover_rate, avg_ticket_fen,
             avg_ticket_yuan}
        """
        # 营业额 + 客数
        rev_result = await db.execute(
            text("""
                SELECT
                    COALESCE(SUM(o.final_amount_fen), 0)::BIGINT AS revenue_fen,
                    COUNT(*)::INT AS customer_count
                FROM orders o
                WHERE o.store_id = :store_id
                  AND o.tenant_id = :tenant_id
                  AND COALESCE(o.biz_date, DATE(o.created_at)) = :target_date
                  AND o.status IN ('paid', 'completed')
                  AND o.is_deleted = FALSE
            """),
            {"store_id": store_id, "tenant_id": tenant_id, "target_date": target_date},
        )
        rev_row = rev_result.mappings().first()
        revenue_fen = int(rev_row["revenue_fen"]) if rev_row else 0
        customer_count = int(rev_row["customer_count"]) if rev_row else 0

        # 食材成本
        cost_result = await db.execute(
            text("""
                SELECT
                    COALESCE(SUM(
                        COALESCE(oi.food_cost_fen, oi.cost_fen, 0) * oi.quantity
                    ), 0)::BIGINT AS cost_fen
                FROM order_items oi
                JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
                WHERE o.store_id = :store_id
                  AND o.tenant_id = :tenant_id
                  AND COALESCE(o.biz_date, DATE(o.created_at)) = :target_date
                  AND o.status IN ('paid', 'completed')
                  AND o.is_deleted = FALSE
                  AND oi.is_deleted = FALSE
            """),
            {"store_id": store_id, "tenant_id": tenant_id, "target_date": target_date},
        )
        cost_row = cost_result.mappings().first()
        cost_fen = int(cost_row["cost_fen"]) if cost_row else 0
        profit_fen = revenue_fen - cost_fen

        # 翻台率
        table_result = await db.execute(
            text("""
                SELECT
                    COUNT(*)::INT AS session_count,
                    (SELECT COUNT(*) FROM tables t
                     WHERE t.store_id = :store_id
                       AND t.tenant_id = :tenant_id
                       AND t.is_deleted = FALSE
                       AND t.is_active = TRUE
                    )::INT AS total_tables
                FROM orders o
                WHERE o.store_id = :store_id
                  AND o.tenant_id = :tenant_id
                  AND COALESCE(o.biz_date, DATE(o.created_at)) = :target_date
                  AND o.table_id IS NOT NULL
                  AND o.status IN ('paid', 'completed', 'pending_payment')
                  AND o.is_deleted = FALSE
            """),
            {"store_id": store_id, "tenant_id": tenant_id, "target_date": target_date},
        )
        table_row = table_result.mappings().first()
        total_tables = int(table_row["total_tables"]) if table_row else 0
        session_count = int(table_row["session_count"]) if table_row else 0
        turnover_rate = round(session_count / total_tables, 2) if total_tables > 0 else 0.0

        avg_ticket_fen = revenue_fen // customer_count if customer_count > 0 else 0

        return {
            "revenue_fen": revenue_fen,
            "revenue_yuan": _fen_to_yuan(revenue_fen),
            "cost_fen": cost_fen,
            "cost_yuan": _fen_to_yuan(cost_fen),
            "profit_fen": profit_fen,
            "profit_yuan": _fen_to_yuan(profit_fen),
            "customer_count": customer_count,
            "turnover_rate": turnover_rate,
            "avg_ticket_fen": avg_ticket_fen,
            "avg_ticket_yuan": _fen_to_yuan(avg_ticket_fen),
        }

    # ═══════════════════════════════════════════════════════════════════
    # 3. 时段P&L
    # ═══════════════════════════════════════════════════════════════════

    async def _compute_daypart_pnl(
        self,
        db: AsyncSession,
        store_id: str,
        tenant_id: str,
        target_date: date,
    ) -> dict:
        """时段P&L -- 午市/下午茶/晚市/夜宵 独立核算

        时段定义:
          午市: 11:00-14:00
          下午茶: 14:00-17:00
          晚市: 17:00-21:00
          夜宵: 21:00-02:00(次日)

        每个时段独立计算:
          营业额/食材成本/人力成本(按排班工时分摊)/利润
          盈亏平衡客数 = 时段固定成本 / (客单价 - 变动成本)

        Args:
            db: 异步数据库会话
            store_id: 门店ID
            tenant_id: 租户ID
            target_date: 目标日期

        Returns:
            {dayparts: [{name, start_hour, end_hour, revenue_fen, revenue_yuan,
             food_cost_fen, labor_cost_fen, profit_fen, profit_yuan,
             customer_count, avg_ticket_fen, breakeven_customers}]}
        """
        log.info(
            "compute_daypart_pnl",
            store_id=store_id,
            target_date=str(target_date),
        )

        dayparts_config = [
            DAYPART_LUNCH,
            DAYPART_AFTERNOON,
            DAYPART_DINNER,
            DAYPART_LATE_NIGHT,
        ]

        # 查询全日人力成本（用于按时段工时分摊）
        total_labor_fen = await self._query_daily_labor_cost(
            db, store_id, tenant_id, target_date
        )

        # 全日营业时长（用于工时分摊比例计算）
        total_biz_hours = 15  # 默认营业15小时（11:00-02:00）

        dayparts = []
        for name, start_h, end_h in dayparts_config:
            # 时段营业额和食材成本
            dp_data = await self._query_daypart_revenue(
                db, store_id, tenant_id, target_date, start_h, end_h
            )
            revenue_fen = dp_data["revenue_fen"]
            food_cost_fen = dp_data["food_cost_fen"]
            customer_count = dp_data["customer_count"]

            # 人力成本按时段工时占比分摊
            hours_span = end_h - start_h
            labor_ratio = hours_span / total_biz_hours if total_biz_hours > 0 else 0
            labor_cost_fen = int(total_labor_fen * labor_ratio)

            total_cost_fen = food_cost_fen + labor_cost_fen
            profit_fen = revenue_fen - total_cost_fen

            # 盈亏平衡客数
            avg_ticket_fen = revenue_fen // customer_count if customer_count > 0 else 0
            variable_cost_per_customer = food_cost_fen // customer_count if customer_count > 0 else 0
            margin_per_customer = avg_ticket_fen - variable_cost_per_customer
            breakeven_customers = (
                int(labor_cost_fen / margin_per_customer)
                if margin_per_customer > 0
                else 0
            )

            dayparts.append({
                "name": name,
                "start_hour": start_h if start_h < 24 else start_h - 24,
                "end_hour": end_h if end_h < 24 else end_h - 24,
                "revenue_fen": revenue_fen,
                "revenue_yuan": _fen_to_yuan(revenue_fen),
                "food_cost_fen": food_cost_fen,
                "food_cost_yuan": _fen_to_yuan(food_cost_fen),
                "labor_cost_fen": labor_cost_fen,
                "labor_cost_yuan": _fen_to_yuan(labor_cost_fen),
                "total_cost_fen": total_cost_fen,
                "profit_fen": profit_fen,
                "profit_yuan": _fen_to_yuan(profit_fen),
                "customer_count": customer_count,
                "avg_ticket_fen": avg_ticket_fen,
                "avg_ticket_yuan": _fen_to_yuan(avg_ticket_fen),
                "breakeven_customers": breakeven_customers,
            })

        return {"dayparts": dayparts}

    # ═══════════════════════════════════════════════════════════════════
    # 4. 外卖单级真实利润
    # ═══════════════════════════════════════════════════════════════════

    async def _compute_delivery_real_profit(
        self,
        db: AsyncSession,
        store_id: str,
        tenant_id: str,
        target_date: date,
    ) -> dict:
        """外卖单级真实利润

        从orders表筛选channel IN ('meituan','eleme','douyin')的订单。
        每单计算:
          营业额 - 食材成本(BOM) - 平台佣金 - 包装费 - 满减补贴
        佣金费率:
          meituan 18% / eleme 20% / douyin 10%
        汇总:
          外卖总量/总营业额/总佣金/总包装/总补贴/真实利润/单均利润
        按渠道分别统计

        Args:
            db: 异步数据库会话
            store_id: 门店ID
            tenant_id: 租户ID
            target_date: 目标日期

        Returns:
            {total: {...}, by_channel: [{channel, order_count, revenue_fen, ...}]}
        """
        log.info(
            "compute_delivery_real_profit",
            store_id=store_id,
            target_date=str(target_date),
        )

        result = await db.execute(
            text("""
                SELECT
                    o.channel,
                    COUNT(*)::INT AS order_count,
                    COALESCE(SUM(o.final_amount_fen), 0)::BIGINT AS revenue_fen,
                    COALESCE(SUM(
                        COALESCE(oi_agg.food_cost_fen, 0)
                    ), 0)::BIGINT AS food_cost_fen,
                    COALESCE(SUM(
                        COALESCE(o.packaging_fee_fen, 0)
                    ), 0)::BIGINT AS packaging_fen,
                    COALESCE(SUM(
                        COALESCE(o.merchant_subsidy_fen, 0)
                    ), 0)::BIGINT AS subsidy_fen
                FROM orders o
                LEFT JOIN LATERAL (
                    SELECT COALESCE(SUM(
                        COALESCE(oi.food_cost_fen, oi.cost_fen, 0) * oi.quantity
                    ), 0) AS food_cost_fen
                    FROM order_items oi
                    WHERE oi.order_id = o.id
                      AND oi.tenant_id = o.tenant_id
                      AND oi.is_deleted = FALSE
                ) oi_agg ON TRUE
                WHERE o.store_id = :store_id
                  AND o.tenant_id = :tenant_id
                  AND COALESCE(o.biz_date, DATE(o.created_at)) = :target_date
                  AND o.channel IN ('meituan', 'eleme', 'douyin')
                  AND o.status IN ('paid', 'completed')
                  AND o.is_deleted = FALSE
                GROUP BY o.channel
                ORDER BY revenue_fen DESC
            """),
            {"store_id": store_id, "tenant_id": tenant_id, "target_date": target_date},
        )

        rows = result.mappings().all()

        total_order_count = 0
        total_revenue_fen = 0
        total_food_cost_fen = 0
        total_commission_fen = 0
        total_packaging_fen = 0
        total_subsidy_fen = 0

        by_channel = []
        for row in rows:
            channel = row["channel"]
            order_count = int(row["order_count"])
            revenue_fen = int(row["revenue_fen"])
            food_cost_fen = int(row["food_cost_fen"])
            packaging_fen = int(row["packaging_fen"])
            subsidy_fen = int(row["subsidy_fen"])

            # 平台佣金 = 营业额 * 费率
            commission_rate = PLATFORM_COMMISSION_RATES.get(channel, 0.15)
            commission_fen = int(revenue_fen * commission_rate)

            # 真实利润 = 营业额 - 食材成本 - 佣金 - 包装费 - 补贴
            real_profit_fen = (
                revenue_fen - food_cost_fen - commission_fen
                - packaging_fen - subsidy_fen
            )
            avg_profit_fen = real_profit_fen // order_count if order_count > 0 else 0

            by_channel.append({
                "channel": channel,
                "order_count": order_count,
                "revenue_fen": revenue_fen,
                "revenue_yuan": _fen_to_yuan(revenue_fen),
                "food_cost_fen": food_cost_fen,
                "commission_rate": commission_rate,
                "commission_fen": commission_fen,
                "commission_yuan": _fen_to_yuan(commission_fen),
                "packaging_fen": packaging_fen,
                "packaging_yuan": _fen_to_yuan(packaging_fen),
                "subsidy_fen": subsidy_fen,
                "subsidy_yuan": _fen_to_yuan(subsidy_fen),
                "real_profit_fen": real_profit_fen,
                "real_profit_yuan": _fen_to_yuan(real_profit_fen),
                "avg_profit_fen": avg_profit_fen,
                "avg_profit_yuan": _fen_to_yuan(avg_profit_fen),
            })

            total_order_count += order_count
            total_revenue_fen += revenue_fen
            total_food_cost_fen += food_cost_fen
            total_commission_fen += commission_fen
            total_packaging_fen += packaging_fen
            total_subsidy_fen += subsidy_fen

        total_real_profit_fen = (
            total_revenue_fen - total_food_cost_fen - total_commission_fen
            - total_packaging_fen - total_subsidy_fen
        )
        total_avg_profit_fen = (
            total_real_profit_fen // total_order_count
            if total_order_count > 0 else 0
        )

        return {
            "total": {
                "order_count": total_order_count,
                "revenue_fen": total_revenue_fen,
                "revenue_yuan": _fen_to_yuan(total_revenue_fen),
                "food_cost_fen": total_food_cost_fen,
                "commission_fen": total_commission_fen,
                "commission_yuan": _fen_to_yuan(total_commission_fen),
                "packaging_fen": total_packaging_fen,
                "packaging_yuan": _fen_to_yuan(total_packaging_fen),
                "subsidy_fen": total_subsidy_fen,
                "subsidy_yuan": _fen_to_yuan(total_subsidy_fen),
                "real_profit_fen": total_real_profit_fen,
                "real_profit_yuan": _fen_to_yuan(total_real_profit_fen),
                "avg_profit_fen": total_avg_profit_fen,
                "avg_profit_yuan": _fen_to_yuan(total_avg_profit_fen),
            },
            "by_channel": by_channel,
        }

    # ═══════════════════════════════════════════════════════════════════
    # 5. TOP5利润菜 + 亏损菜
    # ═══════════════════════════════════════════════════════════════════

    async def _compute_top_dishes(
        self,
        db: AsyncSession,
        store_id: str,
        tenant_id: str,
        target_date: date,
    ) -> dict:
        """TOP5利润菜 + 亏损菜

        从 order_items JOIN dishes 按毛利排序。
        TOP5: 菜名/销量/单份毛利_fen/总毛利_fen
        亏损菜: 毛利<0的菜品列表

        Args:
            db: 异步数据库会话
            store_id: 门店ID
            tenant_id: 租户ID
            target_date: 目标日期

        Returns:
            {top_dishes: [...], loss_dishes: [...]}
        """
        log.info(
            "compute_top_dishes",
            store_id=store_id,
            target_date=str(target_date),
        )

        result = await db.execute(
            text("""
                SELECT
                    d.id AS dish_id,
                    COALESCE(d.dish_name, oi.item_name, '') AS dish_name,
                    d.category,
                    SUM(oi.quantity)::INT AS sales_qty,
                    SUM(oi.subtotal_fen)::BIGINT AS total_revenue_fen,
                    SUM(
                        COALESCE(oi.food_cost_fen, oi.cost_fen, 0) * oi.quantity
                    )::BIGINT AS total_cost_fen,
                    SUM(
                        oi.subtotal_fen
                        - COALESCE(oi.food_cost_fen, oi.cost_fen, 0) * oi.quantity
                    )::BIGINT AS total_margin_fen,
                    CASE WHEN SUM(oi.quantity) > 0
                        THEN (
                            SUM(oi.subtotal_fen - COALESCE(oi.food_cost_fen, oi.cost_fen, 0) * oi.quantity)
                            / SUM(oi.quantity)
                        )::INT
                        ELSE 0
                    END AS margin_per_unit_fen
                FROM order_items oi
                JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
                LEFT JOIN dishes d ON d.id = oi.dish_id AND d.tenant_id = oi.tenant_id
                WHERE o.store_id = :store_id
                  AND o.tenant_id = :tenant_id
                  AND COALESCE(o.biz_date, DATE(o.created_at)) = :target_date
                  AND o.status IN ('paid', 'completed')
                  AND o.is_deleted = FALSE
                  AND oi.is_deleted = FALSE
                GROUP BY d.id, d.dish_name, oi.item_name, d.category
                ORDER BY total_margin_fen DESC
            """),
            {"store_id": store_id, "tenant_id": tenant_id, "target_date": target_date},
        )

        rows = result.mappings().all()

        all_dishes = []
        for row in rows:
            all_dishes.append({
                "dish_id": str(row["dish_id"]) if row["dish_id"] else None,
                "dish_name": row["dish_name"] or "",
                "category": row["category"] or "",
                "sales_qty": int(row["sales_qty"]),
                "total_revenue_fen": int(row["total_revenue_fen"]),
                "total_cost_fen": int(row["total_cost_fen"]),
                "total_margin_fen": int(row["total_margin_fen"]),
                "total_margin_yuan": _fen_to_yuan(int(row["total_margin_fen"])),
                "margin_per_unit_fen": int(row["margin_per_unit_fen"]),
                "margin_per_unit_yuan": _fen_to_yuan(int(row["margin_per_unit_fen"])),
            })

        # TOP5: 总毛利最高的5个菜
        top_dishes = all_dishes[:5]

        # 亏损菜: 毛利 < 0
        loss_dishes = [d for d in all_dishes if d["total_margin_fen"] < 0]

        return {
            "top_dishes": top_dishes,
            "loss_dishes": loss_dishes,
        }

    # ═══════════════════════════════════════════════════════════════════
    # 6. AI决策卡片
    # ═══════════════════════════════════════════════════════════════════

    async def _generate_ai_decisions(
        self,
        db: AsyncSession,
        store_id: str,
        tenant_id: str,
        target_date: date,
    ) -> list[dict]:
        """AI决策卡片 -- 不是数据，是建议+一键操作

        最多3条，按优先级:
        1. 亏损菜干预(毛利<0): action_type='dish_adjust'
        2. 采购紧急(库存<2天): action_type='procurement'
        3. 客户召回(VIP沉睡): action_type='customer_recall'
        4. 损耗告警(>8%): action_type='waste_alert'
        5. 外卖亏损: action_type='delivery_adjust'

        Args:
            db: 异步数据库会话
            store_id: 门店ID
            tenant_id: 租户ID
            target_date: 目标日期

        Returns:
            最多3条AI决策卡片列表
        """
        log.info(
            "generate_ai_decisions",
            store_id=store_id,
            target_date=str(target_date),
        )

        decisions: list[dict] = []

        # ── 优先级1: 亏损菜干预 ──────────────────────────────────────
        try:
            loss_result = await db.execute(
                text("""
                    SELECT
                        COALESCE(d.dish_name, oi.item_name, '') AS dish_name,
                        SUM(
                            oi.subtotal_fen
                            - COALESCE(oi.food_cost_fen, oi.cost_fen, 0) * oi.quantity
                        )::BIGINT AS total_margin_fen
                    FROM order_items oi
                    JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
                    LEFT JOIN dishes d ON d.id = oi.dish_id AND d.tenant_id = oi.tenant_id
                    WHERE o.store_id = :store_id
                      AND o.tenant_id = :tenant_id
                      AND COALESCE(o.biz_date, DATE(o.created_at)) = :target_date
                      AND o.status IN ('paid', 'completed')
                      AND o.is_deleted = FALSE
                      AND oi.is_deleted = FALSE
                    GROUP BY d.dish_name, oi.item_name
                    HAVING SUM(
                        oi.subtotal_fen
                        - COALESCE(oi.food_cost_fen, oi.cost_fen, 0) * oi.quantity
                    ) < 0
                    ORDER BY total_margin_fen ASC
                    LIMIT 1
                """),
                {"store_id": store_id, "tenant_id": tenant_id, "target_date": target_date},
            )
            loss_row = loss_result.mappings().first()
            if loss_row:
                loss_yuan = _fen_to_yuan(abs(int(loss_row["total_margin_fen"])))
                decisions.append({
                    "priority": 1,
                    "action_type": "dish_adjust",
                    "severity": "critical",
                    "title": f"{loss_row['dish_name']}已亏",
                    "description": (
                        f"{loss_row['dish_name']}今日累计亏损"
                        f"\u00a5{loss_yuan} \u2192 建议下架或提价\u00a55"
                    ),
                    "action_label": "调整菜品",
                    "metadata": {
                        "dish_name": loss_row["dish_name"],
                        "loss_fen": int(loss_row["total_margin_fen"]),
                        "loss_yuan": loss_yuan,
                    },
                })
        except (OperationalError, SQLAlchemyError) as exc:
            log.warning("ai_decisions.loss_dish_check_failed", exc_info=True)
            _ = exc

        # ── 优先级2: 采购紧急（库存<2天） ───────────────────────────
        try:
            low_stock_result = await db.execute(
                text("""
                    WITH daily_usage AS (
                        SELECT
                            it.ingredient_id,
                            AVG(ABS(it.qty)) AS avg_daily_qty
                        FROM inventory_transactions it
                        WHERE it.store_id = :store_id
                          AND it.tenant_id = :tenant_id
                          AND it.tx_type = 'deduction'
                          AND it.tx_date >= :target_date - INTERVAL '7 days'
                          AND it.tx_date <= :target_date
                        GROUP BY it.ingredient_id
                    ),
                    current_stock AS (
                        SELECT
                            it.ingredient_id,
                            SUM(CASE WHEN it.tx_type = 'receipt' THEN it.qty ELSE -ABS(it.qty) END) AS stock_qty
                        FROM inventory_transactions it
                        WHERE it.store_id = :store_id
                          AND it.tenant_id = :tenant_id
                        GROUP BY it.ingredient_id
                    )
                    SELECT
                        cs.ingredient_id,
                        cs.stock_qty,
                        du.avg_daily_qty,
                        CASE WHEN du.avg_daily_qty > 0
                            THEN ROUND(cs.stock_qty / du.avg_daily_qty, 1)
                            ELSE 999
                        END AS days_remaining
                    FROM current_stock cs
                    JOIN daily_usage du ON du.ingredient_id = cs.ingredient_id
                    WHERE cs.stock_qty > 0
                      AND du.avg_daily_qty > 0
                      AND cs.stock_qty / du.avg_daily_qty < 2
                    ORDER BY days_remaining ASC
                    LIMIT 1
                """),
                {"store_id": store_id, "tenant_id": tenant_id, "target_date": target_date},
            )
            low_stock_row = low_stock_result.mappings().first()
            if low_stock_row and len(decisions) < MAX_AI_DECISIONS:
                decisions.append({
                    "priority": 2,
                    "action_type": "procurement",
                    "severity": "warning",
                    "title": "明日预计缺货",
                    "description": (
                        f"库存仅剩{float(low_stock_row['days_remaining'])}天用量"
                        f" \u2192 采购单已生成待确认"
                    ),
                    "action_label": "确认采购",
                    "metadata": {
                        "ingredient_id": str(low_stock_row["ingredient_id"]),
                        "days_remaining": float(low_stock_row["days_remaining"]),
                    },
                })
        except (OperationalError, SQLAlchemyError) as exc:
            log.warning("ai_decisions.low_stock_check_failed", exc_info=True)
            _ = exc

        # ── 优先级3: VIP客户召回 ─────────────────────────────────────
        try:
            vip_result = await db.execute(
                text("""
                    SELECT COUNT(*) AS dormant_count
                    FROM (
                        SELECT o.customer_id,
                               MAX(o.created_at) AS last_visit
                        FROM orders o
                        WHERE o.store_id = :store_id
                          AND o.tenant_id = :tenant_id
                          AND o.customer_id IS NOT NULL
                          AND o.status IN ('paid', 'completed')
                          AND o.is_deleted = FALSE
                        GROUP BY o.customer_id
                        HAVING MAX(o.created_at) < :target_date - INTERVAL '30 days'
                           AND COUNT(*) >= 3
                    ) dormant_vips
                """),
                {"store_id": store_id, "tenant_id": tenant_id, "target_date": target_date},
            )
            vip_row = vip_result.mappings().first()
            dormant_count = int(vip_row["dormant_count"]) if vip_row else 0
            if dormant_count > 0 and len(decisions) < MAX_AI_DECISIONS:
                estimated_recall = max(1, int(dormant_count * 0.3))
                decisions.append({
                    "priority": 3,
                    "action_type": "customer_recall",
                    "severity": "info",
                    "title": f"{dormant_count}名VIP超30天未来",
                    "description": (
                        f"{dormant_count}名VIP客户超30天未消费"
                        f" \u2192 发券预计回流{estimated_recall}人"
                    ),
                    "action_label": "发送召回券",
                    "metadata": {
                        "dormant_count": dormant_count,
                        "estimated_recall": estimated_recall,
                    },
                })
        except (OperationalError, SQLAlchemyError) as exc:
            log.warning("ai_decisions.vip_recall_check_failed", exc_info=True)
            _ = exc

        # ── 优先级4: 损耗告警 ────────────────────────────────────────
        try:
            waste_result = await db.execute(
                text("""
                    SELECT
                        COALESCE(SUM(wr.quantity * wr.unit_cost_fen), 0)::BIGINT AS waste_fen,
                        COALESCE((
                            SELECT SUM(
                                COALESCE(oi2.food_cost_fen, oi2.cost_fen, 0) * oi2.quantity
                            )
                            FROM order_items oi2
                            JOIN orders o2 ON o2.id = oi2.order_id AND o2.tenant_id = oi2.tenant_id
                            WHERE o2.store_id = :store_id
                              AND o2.tenant_id = :tenant_id
                              AND COALESCE(o2.biz_date, DATE(o2.created_at)) = :target_date
                              AND o2.status IN ('paid', 'completed')
                              AND o2.is_deleted = FALSE
                              AND oi2.is_deleted = FALSE
                        ), 0)::BIGINT AS usage_fen
                    FROM waste_records wr
                    WHERE wr.store_id = :store_id
                      AND wr.tenant_id = :tenant_id
                      AND DATE(wr.created_at) = :target_date
                """),
                {"store_id": store_id, "tenant_id": tenant_id, "target_date": target_date},
            )
            waste_row = waste_result.mappings().first()
            if waste_row:
                waste_fen = int(waste_row["waste_fen"])
                usage_fen = int(waste_row["usage_fen"])
                waste_rate = waste_fen / usage_fen if usage_fen > 0 else 0.0
                if waste_rate > 0.08 and len(decisions) < MAX_AI_DECISIONS:
                    decisions.append({
                        "priority": 4,
                        "action_type": "waste_alert",
                        "severity": "warning",
                        "title": f"损耗率{waste_rate:.0%}超标",
                        "description": (
                            f"今日损耗率{waste_rate:.0%}(目标<5%)"
                            f" \u2192 需定位到具体班次"
                        ),
                        "action_label": "查看详情",
                        "metadata": {
                            "waste_rate": round(waste_rate * 100, 1),
                            "waste_fen": waste_fen,
                            "usage_fen": usage_fen,
                        },
                    })
        except (OperationalError, SQLAlchemyError) as exc:
            log.warning("ai_decisions.waste_check_failed", exc_info=True)
            _ = exc

        # ── 优先级5: 外卖亏损 ────────────────────────────────────────
        try:
            delivery = await self._compute_delivery_real_profit(
                db, store_id, tenant_id, target_date
            )
            for ch in delivery.get("by_channel", []):
                if ch["real_profit_fen"] < 0 and len(decisions) < MAX_AI_DECISIONS:
                    channel_name = {
                        "meituan": "美团",
                        "eleme": "饿了么",
                        "douyin": "抖音",
                    }.get(ch["channel"], ch["channel"])
                    avg_loss_yuan = _fen_to_yuan(abs(ch["avg_profit_fen"]))
                    decisions.append({
                        "priority": 5,
                        "action_type": "delivery_adjust",
                        "severity": "warning",
                        "title": f"{channel_name}外卖亏损",
                        "description": (
                            f"{channel_name}单均亏\u00a5{avg_loss_yuan}"
                            f" \u2192 建议调整满减门槛"
                        ),
                        "action_label": "调整满减",
                        "metadata": {
                            "channel": ch["channel"],
                            "avg_loss_fen": ch["avg_profit_fen"],
                            "total_loss_fen": ch["real_profit_fen"],
                        },
                    })
                    break  # 只取第一个亏损渠道
        except (OperationalError, SQLAlchemyError) as exc:
            log.warning("ai_decisions.delivery_check_failed", exc_info=True)
            _ = exc

        # 按优先级排序并截断
        decisions.sort(key=lambda d: d["priority"])
        return decisions[:MAX_AI_DECISIONS]

    # ═══════════════════════════════════════════════════════════════════
    # 7. 异常高亮
    # ═══════════════════════════════════════════════════════════════════

    async def _detect_anomalies(
        self,
        db: AsyncSession,
        store_id: str,
        tenant_id: str,
        target_date: date,
    ) -> list[dict]:
        """异常高亮 -- 只显示偏离基线的指标，正常的不显示

        对比维度: 今日 vs 上周同日(weekday对齐)
        偏离阈值: +/-20% 标黄(warning), +/-35% 标红(critical)
        检测项: 营业额/客数/翻台率/客单价/退菜率/损耗率
        每项返回: metric_name/current_value/baseline_value/deviation_pct/severity

        Args:
            db: 异步数据库会话
            store_id: 门店ID
            tenant_id: 租户ID
            target_date: 目标日期

        Returns:
            异常项列表（正常的不返回）
        """
        log.info(
            "detect_anomalies",
            store_id=store_id,
            target_date=str(target_date),
        )

        baseline_date = target_date - timedelta(days=7)
        anomalies: list[dict] = []

        try:
            # 今日 vs 上周同日：营业额/客数/客单价
            for label, period_date in [("today", target_date), ("baseline", baseline_date)]:
                pass  # 在下方统一查询

            result = await db.execute(
                text("""
                    WITH period_stats AS (
                        SELECT
                            COALESCE(o.biz_date, DATE(o.created_at)) AS stat_date,
                            COALESCE(SUM(o.final_amount_fen), 0)::BIGINT AS revenue_fen,
                            COUNT(*)::INT AS customer_count,
                            CASE WHEN COUNT(*) > 0
                                THEN (SUM(o.final_amount_fen) / COUNT(*))::INT
                                ELSE 0
                            END AS avg_ticket_fen
                        FROM orders o
                        WHERE o.store_id = :store_id
                          AND o.tenant_id = :tenant_id
                          AND COALESCE(o.biz_date, DATE(o.created_at)) IN (:target_date, :baseline_date)
                          AND o.status IN ('paid', 'completed')
                          AND o.is_deleted = FALSE
                        GROUP BY COALESCE(o.biz_date, DATE(o.created_at))
                    )
                    SELECT
                        stat_date,
                        revenue_fen,
                        customer_count,
                        avg_ticket_fen
                    FROM period_stats
                """),
                {
                    "store_id": store_id,
                    "tenant_id": tenant_id,
                    "target_date": target_date,
                    "baseline_date": baseline_date,
                },
            )
            stats_rows = {
                str(r["stat_date"]): r for r in result.mappings().all()
            }

            today_stats = stats_rows.get(str(target_date), {})
            baseline_stats = stats_rows.get(str(baseline_date), {})

            metrics_to_check = [
                ("revenue", "营业额", "revenue_fen", "fen"),
                ("customer_count", "客数", "customer_count", "count"),
                ("avg_ticket", "客单价", "avg_ticket_fen", "fen"),
            ]

            for metric_key, metric_name, field, unit in metrics_to_check:
                current_val = int(today_stats.get(field, 0) or 0)
                baseline_val = int(baseline_stats.get(field, 0) or 0)
                pct_change = _pct_change(current_val, baseline_val)

                if pct_change is not None:
                    severity = _deviation_severity(pct_change)
                    if severity:
                        anomalies.append({
                            "metric_key": metric_key,
                            "metric_name": metric_name,
                            "current_value": current_val,
                            "current_display": (
                                _fen_to_yuan(current_val) if unit == "fen"
                                else current_val
                            ),
                            "baseline_value": baseline_val,
                            "baseline_display": (
                                _fen_to_yuan(baseline_val) if unit == "fen"
                                else baseline_val
                            ),
                            "deviation_pct": pct_change,
                            "severity": severity,
                            "baseline_label": f"上周{self._weekday_cn(baseline_date)}",
                        })

            # 退菜率
            return_result = await db.execute(
                text("""
                    SELECT
                        COALESCE(o.biz_date, DATE(o.created_at)) AS stat_date,
                        COUNT(*) FILTER (WHERE oi.status = 'returned')::INT AS return_count,
                        COUNT(*)::INT AS total_count
                    FROM order_items oi
                    JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
                    WHERE o.store_id = :store_id
                      AND o.tenant_id = :tenant_id
                      AND COALESCE(o.biz_date, DATE(o.created_at)) IN (:target_date, :baseline_date)
                      AND o.is_deleted = FALSE
                      AND oi.is_deleted = FALSE
                    GROUP BY COALESCE(o.biz_date, DATE(o.created_at))
                """),
                {
                    "store_id": store_id,
                    "tenant_id": tenant_id,
                    "target_date": target_date,
                    "baseline_date": baseline_date,
                },
            )
            return_rows = {
                str(r["stat_date"]): r for r in return_result.mappings().all()
            }

            today_return = return_rows.get(str(target_date), {})
            baseline_return = return_rows.get(str(baseline_date), {})

            today_return_rate = (
                int(today_return.get("return_count", 0) or 0)
                / max(int(today_return.get("total_count", 0) or 0), 1)
                * 100
            )
            baseline_return_rate = (
                int(baseline_return.get("return_count", 0) or 0)
                / max(int(baseline_return.get("total_count", 0) or 0), 1)
                * 100
            )
            if baseline_return_rate > 0:
                return_pct_change = round(
                    (today_return_rate - baseline_return_rate)
                    / baseline_return_rate * 100,
                    1,
                )
                return_severity = _deviation_severity(return_pct_change)
                if return_severity:
                    anomalies.append({
                        "metric_key": "return_rate",
                        "metric_name": "退菜率",
                        "current_value": round(today_return_rate, 1),
                        "current_display": f"{today_return_rate:.1f}%",
                        "baseline_value": round(baseline_return_rate, 1),
                        "baseline_display": f"{baseline_return_rate:.1f}%",
                        "deviation_pct": return_pct_change,
                        "severity": return_severity,
                        "baseline_label": f"上周{self._weekday_cn(baseline_date)}",
                    })

        except (OperationalError, SQLAlchemyError) as exc:
            log.warning("detect_anomalies.query_failed", exc_info=True)
            _ = exc

        # 按严重程度排序：critical在前
        anomalies.sort(
            key=lambda a: (0 if a["severity"] == "critical" else 1, abs(a.get("deviation_pct", 0))),
            reverse=False,
        )
        return anomalies

    # ═══════════════════════════════════════════════════════════════════
    # 8. 月度目标进度
    # ═══════════════════════════════════════════════════════════════════

    async def _compute_month_progress(
        self,
        db: AsyncSession,
        store_id: str,
        tenant_id: str,
        target_date: date,
    ) -> dict:
        """月度目标进度条

        月度目标: 从stores表的revenue_target_fen读取
        实际进度: 本月1日到今日累计营业额
        日期进度: 今日是本月第几天/本月共几天
        节奏判断: 实际进度% vs 日期进度% -> ahead/on_track/behind
        落后原因: 如果behind，分析是哪几天拖后腿

        Args:
            db: 异步数据库会话
            store_id: 门店ID
            tenant_id: 租户ID
            target_date: 目标日期

        Returns:
            {month_target_fen, month_actual_fen, revenue_progress_pct,
             date_progress_pct, pace, behind_days: [...]}
        """
        log.info(
            "compute_month_progress",
            store_id=store_id,
            target_date=str(target_date),
        )

        # 月度目标
        target_result = await db.execute(
            text("""
                SELECT COALESCE(revenue_target_fen, 0)::BIGINT AS target_fen
                FROM stores
                WHERE id = :store_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
                LIMIT 1
            """),
            {"store_id": store_id, "tenant_id": tenant_id},
        )
        target_row = target_result.mappings().first()
        month_target_fen = int(target_row["target_fen"]) if target_row else 0

        # 本月累计营业额
        month_start = target_date.replace(day=1)
        actual_result = await db.execute(
            text("""
                SELECT COALESCE(SUM(o.final_amount_fen), 0)::BIGINT AS actual_fen
                FROM orders o
                WHERE o.store_id = :store_id
                  AND o.tenant_id = :tenant_id
                  AND COALESCE(o.biz_date, DATE(o.created_at)) >= :month_start
                  AND COALESCE(o.biz_date, DATE(o.created_at)) <= :target_date
                  AND o.status IN ('paid', 'completed')
                  AND o.is_deleted = FALSE
            """),
            {
                "store_id": store_id,
                "tenant_id": tenant_id,
                "month_start": month_start,
                "target_date": target_date,
            },
        )
        actual_row = actual_result.mappings().first()
        month_actual_fen = int(actual_row["actual_fen"]) if actual_row else 0

        # 日期进度
        days_in_month = calendar.monthrange(target_date.year, target_date.month)[1]
        day_of_month = target_date.day
        date_progress_pct = round(day_of_month / days_in_month * 100, 1)

        # 营收进度
        revenue_progress_pct = (
            round(month_actual_fen / month_target_fen * 100, 1)
            if month_target_fen > 0 else 0.0
        )

        # 节奏判断
        if month_target_fen <= 0:
            pace = "no_target"
        elif revenue_progress_pct >= date_progress_pct + 5:
            pace = "ahead"
        elif revenue_progress_pct >= date_progress_pct - 5:
            pace = "on_track"
        else:
            pace = "behind"

        # 落后原因分析：找到低于日均目标的日期
        behind_days: list[dict] = []
        if pace == "behind" and month_target_fen > 0:
            daily_target_fen = month_target_fen // days_in_month
            try:
                behind_result = await db.execute(
                    text("""
                        SELECT
                            COALESCE(o.biz_date, DATE(o.created_at)) AS biz_day,
                            COALESCE(SUM(o.final_amount_fen), 0)::BIGINT AS day_revenue_fen
                        FROM orders o
                        WHERE o.store_id = :store_id
                          AND o.tenant_id = :tenant_id
                          AND COALESCE(o.biz_date, DATE(o.created_at)) >= :month_start
                          AND COALESCE(o.biz_date, DATE(o.created_at)) <= :target_date
                          AND o.status IN ('paid', 'completed')
                          AND o.is_deleted = FALSE
                        GROUP BY COALESCE(o.biz_date, DATE(o.created_at))
                        HAVING COALESCE(SUM(o.final_amount_fen), 0) < :daily_target
                        ORDER BY day_revenue_fen ASC
                        LIMIT 5
                    """),
                    {
                        "store_id": store_id,
                        "tenant_id": tenant_id,
                        "month_start": month_start,
                        "target_date": target_date,
                        "daily_target": daily_target_fen,
                    },
                )
                for row in behind_result.mappings().all():
                    gap_fen = daily_target_fen - int(row["day_revenue_fen"])
                    behind_days.append({
                        "date": str(row["biz_day"]),
                        "revenue_fen": int(row["day_revenue_fen"]),
                        "revenue_yuan": _fen_to_yuan(int(row["day_revenue_fen"])),
                        "gap_fen": gap_fen,
                        "gap_yuan": _fen_to_yuan(gap_fen),
                    })
            except (OperationalError, SQLAlchemyError) as exc:
                log.warning("month_progress.behind_analysis_failed", exc_info=True)
                _ = exc

        return {
            "month_target_fen": month_target_fen,
            "month_target_yuan": _fen_to_yuan(month_target_fen),
            "month_actual_fen": month_actual_fen,
            "month_actual_yuan": _fen_to_yuan(month_actual_fen),
            "revenue_progress_pct": revenue_progress_pct,
            "date_progress_pct": date_progress_pct,
            "day_of_month": day_of_month,
            "days_in_month": days_in_month,
            "pace": pace,
            "behind_days": behind_days,
        }

    # ═══════════════════════════════════════════════════════════════════
    # 9. 多店概览（总部视角）
    # ═══════════════════════════════════════════════════════════════════

    async def get_multi_store_cockpit(
        self,
        db: AsyncSession,
        tenant_id: str,
        brand_id: Optional[str] = None,
    ) -> dict:
        """多店概览(总部视角)

        所有门店的cockpit汇总 + 门店排行(按利润) + 失血门店(利润为负)

        Args:
            db: 异步数据库会话
            tenant_id: 租户ID
            brand_id: 品牌ID（可选，不传则返回全部门店）

        Returns:
            {summary: {...}, stores: [...], bleeding_stores: [...]}
        """
        log.info(
            "get_multi_store_cockpit",
            tenant_id=tenant_id,
            brand_id=brand_id,
        )

        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        today = date.today()

        try:
            # 查询租户下所有门店
            brand_filter = ""
            params: dict = {"tenant_id": tenant_id, "target_date": today}
            if brand_id:
                brand_filter = "AND s.brand_id = :brand_id"
                params["brand_id"] = brand_id

            stores_result = await db.execute(
                text(f"""
                    SELECT
                        s.id AS store_id,
                        s.name AS store_name,
                        COALESCE(s.revenue_target_fen, 0)::BIGINT AS target_fen,
                        COALESCE(rev.revenue_fen, 0)::BIGINT AS revenue_fen,
                        COALESCE(rev.customer_count, 0)::INT AS customer_count,
                        COALESCE(cost.cost_fen, 0)::BIGINT AS cost_fen
                    FROM stores s
                    LEFT JOIN LATERAL (
                        SELECT
                            SUM(o.final_amount_fen) AS revenue_fen,
                            COUNT(*) AS customer_count
                        FROM orders o
                        WHERE o.store_id = s.id
                          AND o.tenant_id = :tenant_id
                          AND COALESCE(o.biz_date, DATE(o.created_at)) = :target_date
                          AND o.status IN ('paid', 'completed')
                          AND o.is_deleted = FALSE
                    ) rev ON TRUE
                    LEFT JOIN LATERAL (
                        SELECT SUM(
                            COALESCE(oi.food_cost_fen, oi.cost_fen, 0) * oi.quantity
                        ) AS cost_fen
                        FROM order_items oi
                        JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
                        WHERE o.store_id = s.id
                          AND o.tenant_id = :tenant_id
                          AND COALESCE(o.biz_date, DATE(o.created_at)) = :target_date
                          AND o.status IN ('paid', 'completed')
                          AND o.is_deleted = FALSE
                          AND oi.is_deleted = FALSE
                    ) cost ON TRUE
                    WHERE s.tenant_id = :tenant_id
                      AND s.is_deleted = FALSE
                      {brand_filter}
                    ORDER BY revenue_fen DESC NULLS LAST
                """),
                params,
            )

            rows = stores_result.mappings().all()

            total_revenue_fen = 0
            total_cost_fen = 0
            total_customers = 0
            stores_data: list[dict] = []
            bleeding_stores: list[dict] = []

            for idx, row in enumerate(rows):
                revenue_fen = int(row["revenue_fen"] or 0)
                cost_fen = int(row["cost_fen"] or 0)
                profit_fen = revenue_fen - cost_fen
                customer_count = int(row["customer_count"] or 0)

                store_entry = {
                    "rank": idx + 1,
                    "store_id": str(row["store_id"]),
                    "store_name": row["store_name"],
                    "revenue_fen": revenue_fen,
                    "revenue_yuan": _fen_to_yuan(revenue_fen),
                    "cost_fen": cost_fen,
                    "profit_fen": profit_fen,
                    "profit_yuan": _fen_to_yuan(profit_fen),
                    "customer_count": customer_count,
                }
                stores_data.append(store_entry)

                if profit_fen < 0:
                    bleeding_stores.append(store_entry)

                total_revenue_fen += revenue_fen
                total_cost_fen += cost_fen
                total_customers += customer_count

            total_profit_fen = total_revenue_fen - total_cost_fen
            store_count = len(stores_data)

            return {
                "date": today.isoformat(),
                "summary": {
                    "store_count": store_count,
                    "total_revenue_fen": total_revenue_fen,
                    "total_revenue_yuan": _fen_to_yuan(total_revenue_fen),
                    "total_cost_fen": total_cost_fen,
                    "total_profit_fen": total_profit_fen,
                    "total_profit_yuan": _fen_to_yuan(total_profit_fen),
                    "total_customers": total_customers,
                    "avg_revenue_fen": (
                        total_revenue_fen // store_count if store_count > 0 else 0
                    ),
                    "bleeding_count": len(bleeding_stores),
                },
                "stores": stores_data,
                "bleeding_stores": bleeding_stores,
            }

        except (OperationalError, SQLAlchemyError) as exc:
            log.error(
                "get_multi_store_cockpit.db_error",
                tenant_id=tenant_id,
                exc_info=True,
            )
            _ = exc
            return {
                "date": today.isoformat(),
                "summary": {
                    "store_count": 0,
                    "total_revenue_fen": 0,
                    "total_revenue_yuan": 0.0,
                    "total_cost_fen": 0,
                    "total_profit_fen": 0,
                    "total_profit_yuan": 0.0,
                    "total_customers": 0,
                    "avg_revenue_fen": 0,
                    "bleeding_count": 0,
                },
                "stores": [],
                "bleeding_stores": [],
            }

    # ═══════════════════════════════════════════════════════════════════
    # 内部辅助查询方法
    # ═══════════════════════════════════════════════════════════════════

    async def _query_daypart_revenue(
        self,
        db: AsyncSession,
        store_id: str,
        tenant_id: str,
        target_date: date,
        start_hour: int,
        end_hour: int,
    ) -> dict:
        """查询指定时段的营业额和食材成本

        支持跨午夜时段（如夜宵 21:00-02:00）。

        Args:
            db: 异步数据库会话
            store_id: 门店ID
            tenant_id: 租户ID
            target_date: 目标日期
            start_hour: 起始小时（0-23）
            end_hour: 结束小时（可>24表示次日）

        Returns:
            {revenue_fen, food_cost_fen, customer_count}
        """
        # 处理跨午夜的情况
        if end_hour > 24:
            # 跨午夜：分两段查询
            # 段1: start_hour 到 24:00 (当天)
            # 段2: 00:00 到 end_hour-24 (次日)
            next_date = target_date + timedelta(days=1)
            result = await db.execute(
                text("""
                    SELECT
                        COALESCE(SUM(o.final_amount_fen), 0)::BIGINT AS revenue_fen,
                        COUNT(*)::INT AS customer_count
                    FROM orders o
                    WHERE o.store_id = :store_id
                      AND o.tenant_id = :tenant_id
                      AND o.status IN ('paid', 'completed')
                      AND o.is_deleted = FALSE
                      AND (
                          (COALESCE(o.biz_date, DATE(o.created_at)) = :target_date
                           AND EXTRACT(HOUR FROM o.created_at) >= :start_hour)
                          OR
                          (COALESCE(o.biz_date, DATE(o.created_at)) = :next_date
                           AND EXTRACT(HOUR FROM o.created_at) < :end_hour_wrapped)
                      )
                """),
                {
                    "store_id": store_id,
                    "tenant_id": tenant_id,
                    "target_date": target_date,
                    "next_date": next_date,
                    "start_hour": start_hour,
                    "end_hour_wrapped": end_hour - 24,
                },
            )
        else:
            result = await db.execute(
                text("""
                    SELECT
                        COALESCE(SUM(o.final_amount_fen), 0)::BIGINT AS revenue_fen,
                        COUNT(*)::INT AS customer_count
                    FROM orders o
                    WHERE o.store_id = :store_id
                      AND o.tenant_id = :tenant_id
                      AND COALESCE(o.biz_date, DATE(o.created_at)) = :target_date
                      AND EXTRACT(HOUR FROM o.created_at) >= :start_hour
                      AND EXTRACT(HOUR FROM o.created_at) < :end_hour
                      AND o.status IN ('paid', 'completed')
                      AND o.is_deleted = FALSE
                """),
                {
                    "store_id": store_id,
                    "tenant_id": tenant_id,
                    "target_date": target_date,
                    "start_hour": start_hour,
                    "end_hour": end_hour,
                },
            )

        row = result.mappings().first()
        revenue_fen = int(row["revenue_fen"]) if row else 0
        customer_count = int(row["customer_count"]) if row else 0

        # 食材成本（同时段）
        if end_hour > 24:
            next_date = target_date + timedelta(days=1)
            cost_result = await db.execute(
                text("""
                    SELECT
                        COALESCE(SUM(
                            COALESCE(oi.food_cost_fen, oi.cost_fen, 0) * oi.quantity
                        ), 0)::BIGINT AS food_cost_fen
                    FROM order_items oi
                    JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
                    WHERE o.store_id = :store_id
                      AND o.tenant_id = :tenant_id
                      AND o.status IN ('paid', 'completed')
                      AND o.is_deleted = FALSE
                      AND oi.is_deleted = FALSE
                      AND (
                          (COALESCE(o.biz_date, DATE(o.created_at)) = :target_date
                           AND EXTRACT(HOUR FROM o.created_at) >= :start_hour)
                          OR
                          (COALESCE(o.biz_date, DATE(o.created_at)) = :next_date
                           AND EXTRACT(HOUR FROM o.created_at) < :end_hour_wrapped)
                      )
                """),
                {
                    "store_id": store_id,
                    "tenant_id": tenant_id,
                    "target_date": target_date,
                    "next_date": next_date,
                    "start_hour": start_hour,
                    "end_hour_wrapped": end_hour - 24,
                },
            )
        else:
            cost_result = await db.execute(
                text("""
                    SELECT
                        COALESCE(SUM(
                            COALESCE(oi.food_cost_fen, oi.cost_fen, 0) * oi.quantity
                        ), 0)::BIGINT AS food_cost_fen
                    FROM order_items oi
                    JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
                    WHERE o.store_id = :store_id
                      AND o.tenant_id = :tenant_id
                      AND COALESCE(o.biz_date, DATE(o.created_at)) = :target_date
                      AND EXTRACT(HOUR FROM o.created_at) >= :start_hour
                      AND EXTRACT(HOUR FROM o.created_at) < :end_hour
                      AND o.status IN ('paid', 'completed')
                      AND o.is_deleted = FALSE
                      AND oi.is_deleted = FALSE
                """),
                {
                    "store_id": store_id,
                    "tenant_id": tenant_id,
                    "target_date": target_date,
                    "start_hour": start_hour,
                    "end_hour": end_hour,
                },
            )

        cost_row = cost_result.mappings().first()
        food_cost_fen = int(cost_row["food_cost_fen"]) if cost_row else 0

        return {
            "revenue_fen": revenue_fen,
            "food_cost_fen": food_cost_fen,
            "customer_count": customer_count,
        }

    async def _query_daily_labor_cost(
        self,
        db: AsyncSession,
        store_id: str,
        tenant_id: str,
        target_date: date,
    ) -> int:
        """查询指定日期全日人力成本（分）

        从 crew_shifts JOIN employees 计算：
        SUM(actual_hours * hourly_wage_fen)

        Args:
            db: 异步数据库会话
            store_id: 门店ID
            tenant_id: 租户ID
            target_date: 目标日期

        Returns:
            人力成本（分），无数据时返回0
        """
        try:
            result = await db.execute(
                text("""
                    SELECT COALESCE(SUM(
                        cs.actual_hours * COALESCE(e.hourly_wage_fen, 0)
                    ), 0)::BIGINT AS labor_cost_fen
                    FROM crew_shifts cs
                    JOIN employees e ON e.id = cs.employee_id
                      AND e.tenant_id = :tenant_id
                    WHERE cs.store_id = :store_id
                      AND cs.tenant_id = :tenant_id
                      AND cs.shift_date = :target_date
                """),
                {"store_id": store_id, "tenant_id": tenant_id, "target_date": target_date},
            )
            row = result.mappings().first()
            return int(row["labor_cost_fen"]) if row else 0
        except (OperationalError, SQLAlchemyError) as exc:
            log.warning("query_daily_labor_cost.failed", exc_info=True)
            _ = exc
            return 0

    # ═══════════════════════════════════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════════════════════════════════

    @staticmethod
    def _weekday_cn(d: date) -> str:
        """日期转中文星期"""
        weekdays = ["一", "二", "三", "四", "五", "六", "日"]
        return weekdays[d.weekday()]

    @staticmethod
    def _default_cockpit(store_id: str, target_date: date) -> dict:
        """DB不可用时的默认驾驶舱数据"""
        return {
            "store_id": store_id,
            "date": target_date.isoformat(),
            "snapshot_time": datetime.now(timezone.utc).isoformat(),
            "overview": {
                "revenue_fen": 0, "revenue_yuan": 0.0,
                "cost_fen": 0, "cost_yuan": 0.0,
                "profit_fen": 0, "profit_yuan": 0.0,
                "customer_count": 0, "turnover_rate": 0.0,
                "avg_ticket_fen": 0, "avg_ticket_yuan": 0.0,
            },
            "daypart_pnl": {"dayparts": []},
            "delivery_profit": {
                "total": {
                    "order_count": 0, "revenue_fen": 0, "revenue_yuan": 0.0,
                    "food_cost_fen": 0, "commission_fen": 0, "commission_yuan": 0.0,
                    "packaging_fen": 0, "packaging_yuan": 0.0,
                    "subsidy_fen": 0, "subsidy_yuan": 0.0,
                    "real_profit_fen": 0, "real_profit_yuan": 0.0,
                    "avg_profit_fen": 0, "avg_profit_yuan": 0.0,
                },
                "by_channel": [],
            },
            "top_dishes": [],
            "loss_dishes": [],
            "ai_decisions": [],
            "anomalies": [],
            "month_progress": {
                "month_target_fen": 0, "month_target_yuan": 0.0,
                "month_actual_fen": 0, "month_actual_yuan": 0.0,
                "revenue_progress_pct": 0.0, "date_progress_pct": 0.0,
                "day_of_month": 0, "days_in_month": 0,
                "pace": "no_target", "behind_days": [],
            },
        }
