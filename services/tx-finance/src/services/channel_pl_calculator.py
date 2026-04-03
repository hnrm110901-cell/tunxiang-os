"""渠道结算对账引擎 — ChannelPLCalculator

功能：
- 按渠道计算 P&L（毛利、抽佣、食材成本）
- 将平台账单与系统订单逐单核对，生成差异记录
- 根据 settlement_days 预测未来资金到账
- 差异汇总统计
"""
import uuid
from datetime import date, timedelta
from typing import Optional

import structlog
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.sales_channel import DEFAULT_CHANNELS, get_channel_by_id

logger = structlog.get_logger(__name__)

# 渠道配置快速查表（channel_id → SalesChannel）
_CHANNEL_MAP = {ch.channel_id: ch for ch in DEFAULT_CHANNELS}

# 平台名称 → 渠道 ID 映射（用于对账时关联）
_PLATFORM_TO_CHANNEL: dict[str, str] = {
    "meituan": "ch_meituan",
    "eleme": "ch_eleme",
    "douyin": "ch_douyin",
}


# ─── Pydantic v2 数据模型 ─────────────────────────────────────────────────────

class ChannelRow(BaseModel):
    channel_id: str
    channel_name: str
    order_count: int
    gross_revenue_fen: int
    commission_fen: int
    food_cost_fen: int
    gross_profit_fen: int
    gross_margin: float  # 0.0-1.0


class ChannelPLReport(BaseModel):
    store_id: uuid.UUID
    start_date: date
    end_date: date
    channels: list[ChannelRow]
    total_gross_revenue_fen: int
    total_gross_profit_fen: int
    overall_margin: float


class ReconcileResult(BaseModel):
    bill_id: uuid.UUID
    total_platform_orders: int
    matched_orders: int
    discrepancy_count: int
    total_diff_fen: int
    discrepancies: list[dict]


class ReceivableForecast(BaseModel):
    store_id: uuid.UUID
    platform: str
    order_date: date
    expected_receive_date: date
    expected_amount_fen: int
    status: str


class DiscrepancySummary(BaseModel):
    total_discrepancy_count: int
    open_count: int
    total_diff_fen: int
    diff_rate: float  # 差异金额 / 总账单金额


# ─── 计算引擎 ─────────────────────────────────────────────────────────────────

class ChannelPLCalculator:
    """渠道 P&L 计算 + 对账 + 到账预测"""

    async def calculate_channel_pl(
        self,
        store_id: uuid.UUID,
        tenant_id: uuid.UUID,
        start_date: date,
        end_date: date,
        channel_id: Optional[str] = None,
        db: AsyncSession = None,
    ) -> ChannelPLReport:
        """计算指定门店/时段/渠道的 P&L

        计算逻辑：
        - gross_revenue = sum(delivery_orders.total_fen)，按 sales_channel 分组
        - commission = sum(delivery_orders.commission_fen)（直接读取订单中已记录的佣金）
        - food_cost = sum(order_items.food_cost_fen)（如有；无则为 0）
        - gross_profit = gross_revenue - commission - food_cost
        - gross_margin = gross_profit / gross_revenue
        """
        # 查询外卖订单（按渠道聚合）
        where_channel = "AND d.sales_channel = :channel_id" if channel_id else ""
        params: dict = {
            "store_id": str(store_id),
            "tenant_id": str(tenant_id),
            "start_date": str(start_date),
            "end_date": str(end_date),
        }
        if channel_id:
            params["channel_id"] = channel_id

        delivery_sql = text(f"""
            SELECT
                d.sales_channel                         AS channel_id,
                COUNT(*)                                AS order_count,
                COALESCE(SUM(d.total_fen), 0)           AS gross_revenue_fen,
                COALESCE(SUM(d.commission_fen), 0)      AS commission_fen
            FROM delivery_orders d
            WHERE d.store_id = :store_id::UUID
              AND d.tenant_id = :tenant_id::UUID
              AND d.status = 'completed'
              AND DATE(d.created_at) BETWEEN :start_date::DATE AND :end_date::DATE
              {where_channel}
            GROUP BY d.sales_channel
        """)

        result = await db.execute(delivery_sql, params)
        rows = result.mappings().all()

        channel_rows: list[ChannelRow] = []
        for row in rows:
            ch_id = row["channel_id"] or "unknown"
            ch_config = get_channel_by_id(ch_id)
            ch_name = ch_config.channel_name if ch_config else ch_id

            gross_rev = int(row["gross_revenue_fen"])
            commission = int(row["commission_fen"])

            # food_cost: 尝试从 order_items 聚合（如无该表则为 0）
            food_cost = await self._get_food_cost(
                store_id=store_id,
                tenant_id=tenant_id,
                channel_id=ch_id,
                start_date=start_date,
                end_date=end_date,
                db=db,
            )

            gross_profit = gross_rev - commission - food_cost
            gross_margin = (gross_profit / gross_rev) if gross_rev > 0 else 0.0

            channel_rows.append(ChannelRow(
                channel_id=ch_id,
                channel_name=ch_name,
                order_count=int(row["order_count"]),
                gross_revenue_fen=gross_rev,
                commission_fen=commission,
                food_cost_fen=food_cost,
                gross_profit_fen=gross_profit,
                gross_margin=round(gross_margin, 4),
            ))

        total_revenue = sum(r.gross_revenue_fen for r in channel_rows)
        total_profit = sum(r.gross_profit_fen for r in channel_rows)
        overall_margin = (total_profit / total_revenue) if total_revenue > 0 else 0.0

        return ChannelPLReport(
            store_id=store_id,
            start_date=start_date,
            end_date=end_date,
            channels=channel_rows,
            total_gross_revenue_fen=total_revenue,
            total_gross_profit_fen=total_profit,
            overall_margin=round(overall_margin, 4),
        )

    async def _get_food_cost(
        self,
        store_id: uuid.UUID,
        tenant_id: uuid.UUID,
        channel_id: str,
        start_date: date,
        end_date: date,
        db: AsyncSession,
    ) -> int:
        """从 order_items 查询食材成本（如表不存在则返回 0）"""
        try:
            result = await db.execute(
                text("""
                    SELECT COALESCE(SUM(oi.food_cost_fen), 0) AS total_food_cost
                    FROM order_items oi
                    JOIN delivery_orders d ON d.id = oi.order_id
                    WHERE d.store_id = :store_id::UUID
                      AND d.tenant_id = :tenant_id::UUID
                      AND d.sales_channel = :channel_id
                      AND d.status = 'completed'
                      AND DATE(d.created_at) BETWEEN :start_date::DATE AND :end_date::DATE
                """),
                {
                    "store_id": str(store_id),
                    "tenant_id": str(tenant_id),
                    "channel_id": channel_id,
                    "start_date": str(start_date),
                    "end_date": str(end_date),
                },
            )
            row = result.mappings().first()
            return int(row["total_food_cost"]) if row else 0
        except Exception:
            # order_items 表可能尚未建立，返回 0 不影响其他计算
            return 0

    async def reconcile_bill(
        self,
        bill_id: uuid.UUID,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> ReconcileResult:
        """将平台账单与系统订单逐单核对

        步骤：
        1. 从 platform_bills 获取账单基本信息和 raw_data（含订单列表）
        2. 查询系统中对应时段/平台的 delivery_orders
        3. 逐单比对 platform_order_id，金额差异 > 1分 记录为差异
        4. 将差异写入 settlement_discrepancies
        5. 更新 bill.status = 'reconciled'
        """
        # 1. 读取账单
        bill_row = await db.execute(
            text("""
                SELECT id, store_id, platform, bill_period, bill_type,
                       gross_amount_fen, raw_data
                FROM platform_bills
                WHERE id = :bill_id::UUID
                  AND tenant_id = :tenant_id::UUID
            """),
            {"bill_id": str(bill_id), "tenant_id": str(tenant_id)},
        )
        bill = bill_row.mappings().first()
        if bill is None:
            raise ValueError(f"账单不存在或无权访问: {bill_id}")

        store_id = bill["store_id"]
        platform = bill["platform"]
        raw_data: dict = bill["raw_data"] or {}

        # raw_data 应包含 {"orders": [{"platform_order_id": "...", "amount_fen": ...}, ...]}
        platform_orders: list[dict] = raw_data.get("orders", [])
        platform_order_map: dict[str, int] = {
            o["platform_order_id"]: o.get("amount_fen", 0)
            for o in platform_orders
            if "platform_order_id" in o
        }

        # 2. 从系统查询同平台的完成订单（按 bill_period 过滤）
        bill_period: str = bill["bill_period"]
        # bill_period 格式: YYYY-MM 或 YYYY-MM-DD（周结/日结）
        if len(bill_period) == 7:  # YYYY-MM
            period_filter = "TO_CHAR(d.created_at AT TIME ZONE 'Asia/Shanghai', 'YYYY-MM') = :bill_period"
        else:  # YYYY-MM-DD
            period_filter = "DATE(d.created_at AT TIME ZONE 'Asia/Shanghai') = :bill_period::DATE"

        sys_result = await db.execute(
            text(f"""
                SELECT platform_order_id, total_fen, id AS internal_order_id
                FROM delivery_orders d
                WHERE d.store_id = :store_id::UUID
                  AND d.tenant_id = :tenant_id::UUID
                  AND d.platform = :platform
                  AND d.status = 'completed'
                  AND {period_filter}
            """),
            {
                "store_id": str(store_id),
                "tenant_id": str(tenant_id),
                "platform": platform,
                "bill_period": bill_period,
            },
        )
        sys_orders = sys_result.mappings().all()
        sys_order_map: dict[str, dict] = {
            row["platform_order_id"]: dict(row) for row in sys_orders
        }

        discrepancies: list[dict] = []

        # 3. 逐单比对
        all_platform_ids = set(platform_order_map.keys())
        all_sys_ids = set(sys_order_map.keys())

        # 平台有、系统无
        for pid in all_platform_ids - all_sys_ids:
            discrepancies.append({
                "platform_order_id": pid,
                "internal_order_id": None,
                "platform_amount_fen": platform_order_map[pid],
                "system_amount_fen": 0,
                "discrepancy_type": "order_missing_in_system",
            })

        # 系统有、平台无
        for pid in all_sys_ids - all_platform_ids:
            sys_ord = sys_order_map[pid]
            discrepancies.append({
                "platform_order_id": pid,
                "internal_order_id": str(sys_ord["internal_order_id"]),
                "platform_amount_fen": 0,
                "system_amount_fen": sys_ord["total_fen"],
                "discrepancy_type": "order_missing_in_bill",
            })

        # 双方都有，比对金额
        for pid in all_platform_ids & all_sys_ids:
            p_amt = platform_order_map[pid]
            s_amt = sys_order_map[pid]["total_fen"]
            diff = abs(p_amt - s_amt)
            if diff > 0:  # 分为单位，差异 > 0.00元即记录
                discrepancies.append({
                    "platform_order_id": pid,
                    "internal_order_id": str(sys_order_map[pid]["internal_order_id"]),
                    "platform_amount_fen": p_amt,
                    "system_amount_fen": s_amt,
                    "discrepancy_type": "amount_mismatch",
                })

        # 4. 写入差异记录
        if discrepancies:
            for d in discrepancies:
                await db.execute(
                    text("""
                        INSERT INTO settlement_discrepancies (
                            tenant_id, store_id, platform, bill_id,
                            platform_order_id, internal_order_id,
                            platform_amount_fen, system_amount_fen,
                            discrepancy_type, status
                        ) VALUES (
                            :tenant_id::UUID, :store_id::UUID, :platform, :bill_id::UUID,
                            :platform_order_id, :internal_order_id::UUID,
                            :platform_amount_fen, :system_amount_fen,
                            :discrepancy_type, 'open'
                        )
                        ON CONFLICT DO NOTHING
                    """),
                    {
                        "tenant_id": str(tenant_id),
                        "store_id": str(store_id),
                        "platform": platform,
                        "bill_id": str(bill_id),
                        "platform_order_id": d["platform_order_id"],
                        "internal_order_id": d["internal_order_id"],
                        "platform_amount_fen": d["platform_amount_fen"],
                        "system_amount_fen": d["system_amount_fen"],
                        "discrepancy_type": d["discrepancy_type"],
                    },
                )

        # 5. 更新账单状态
        await db.execute(
            text("""
                UPDATE platform_bills
                SET status = 'reconciled', updated_at = NOW()
                WHERE id = :bill_id::UUID AND tenant_id = :tenant_id::UUID
            """),
            {"bill_id": str(bill_id), "tenant_id": str(tenant_id)},
        )
        await db.commit()

        matched = len(all_platform_ids & all_sys_ids) - sum(
            1 for d in discrepancies if d["discrepancy_type"] == "amount_mismatch"
        )
        total_diff = sum(
            abs(d["platform_amount_fen"] - d["system_amount_fen"])
            for d in discrepancies
        )

        logger.info(
            "bill_reconciled",
            bill_id=str(bill_id),
            platform=platform,
            total_platform_orders=len(platform_orders),
            discrepancy_count=len(discrepancies),
            total_diff_fen=total_diff,
        )

        return ReconcileResult(
            bill_id=bill_id,
            total_platform_orders=len(platform_orders),
            matched_orders=matched,
            discrepancy_count=len(discrepancies),
            total_diff_fen=total_diff,
            discrepancies=discrepancies,
        )

    async def generate_receivable_forecast(
        self,
        store_id: uuid.UUID,
        tenant_id: uuid.UUID,
        days_ahead: int = 30,
        db: AsyncSession = None,
    ) -> list[ReceivableForecast]:
        """根据历史订单和 settlement_days 生成到账预测

        逻辑：
        - 查询过去 days_ahead 天内的外卖平台完成订单（按平台+下单日期聚合）
        - 用各平台 settlement_days 计算预期到账日期
        - 写入 receivable_forecasts 表（UPSERT）
        - 返回预测列表
        """
        today = date.today()
        window_start = today - timedelta(days=days_ahead)

        result = await db.execute(
            text("""
                SELECT
                    platform,
                    DATE(created_at AT TIME ZONE 'Asia/Shanghai') AS order_date,
                    COALESCE(SUM(merchant_receive_fen), 0) AS expected_amount_fen
                FROM delivery_orders
                WHERE store_id = :store_id::UUID
                  AND tenant_id = :tenant_id::UUID
                  AND status = 'completed'
                  AND DATE(created_at AT TIME ZONE 'Asia/Shanghai') >= :window_start::DATE
                GROUP BY platform, DATE(created_at AT TIME ZONE 'Asia/Shanghai')
                ORDER BY order_date
            """),
            {
                "store_id": str(store_id),
                "tenant_id": str(tenant_id),
                "window_start": str(window_start),
            },
        )
        rows = result.mappings().all()

        forecasts: list[ReceivableForecast] = []
        for row in rows:
            platform = row["platform"]
            ch_id = _PLATFORM_TO_CHANNEL.get(platform)
            ch_config = _CHANNEL_MAP.get(ch_id) if ch_id else None
            settlement_days = ch_config.settlement_days if ch_config else 7

            order_date_val: date = row["order_date"]
            expected_date = order_date_val + timedelta(days=settlement_days)
            expected_fen = int(row["expected_amount_fen"])

            # 判断状态
            if expected_date < today:
                status = "overdue"
            else:
                status = "pending"

            # UPSERT 到 receivable_forecasts
            await db.execute(
                text("""
                    INSERT INTO receivable_forecasts (
                        tenant_id, store_id, platform,
                        order_date, expected_receive_date, expected_amount_fen, status
                    ) VALUES (
                        :tenant_id::UUID, :store_id::UUID, :platform,
                        :order_date::DATE, :expected_date::DATE, :expected_fen, :status
                    )
                    ON CONFLICT (tenant_id, store_id, platform, order_date)
                    DO UPDATE SET
                        expected_receive_date = EXCLUDED.expected_receive_date,
                        expected_amount_fen   = EXCLUDED.expected_amount_fen,
                        status = CASE
                            WHEN receivable_forecasts.actual_receive_date IS NOT NULL THEN 'received'
                            ELSE EXCLUDED.status
                        END
                """),
                {
                    "tenant_id": str(tenant_id),
                    "store_id": str(store_id),
                    "platform": platform,
                    "order_date": str(order_date_val),
                    "expected_date": str(expected_date),
                    "expected_fen": expected_fen,
                    "status": status,
                },
            )

            forecasts.append(ReceivableForecast(
                store_id=store_id,
                platform=platform,
                order_date=order_date_val,
                expected_receive_date=expected_date,
                expected_amount_fen=expected_fen,
                status=status,
            ))

        await db.commit()
        return forecasts

    async def get_discrepancy_summary(
        self,
        store_id: uuid.UUID,
        tenant_id: uuid.UUID,
        platform: Optional[str] = None,
        db: AsyncSession = None,
    ) -> DiscrepancySummary:
        """差异汇总统计

        返回：
        - 总差异数量
        - 待处理（open）数量
        - 总差异金额（分）
        - 差异率 = 总差异金额 / 关联账单总金额
        """
        platform_filter = "AND sd.platform = :platform" if platform else ""
        params: dict = {
            "store_id": str(store_id),
            "tenant_id": str(tenant_id),
        }
        if platform:
            params["platform"] = platform

        summary_result = await db.execute(
            text(f"""
                SELECT
                    COUNT(*)                                        AS total_count,
                    COUNT(*) FILTER (WHERE sd.status = 'open')     AS open_count,
                    COALESCE(SUM(ABS(sd.diff_fen)), 0)             AS total_diff_fen
                FROM settlement_discrepancies sd
                WHERE sd.store_id = :store_id::UUID
                  AND sd.tenant_id = :tenant_id::UUID
                  {platform_filter}
            """),
            params,
        )
        summary = summary_result.mappings().first()

        total_count = int(summary["total_count"])
        open_count = int(summary["open_count"])
        total_diff = int(summary["total_diff_fen"])

        # 关联账单总金额（用于计算差异率）
        bill_params: dict = {
            "store_id": str(store_id),
            "tenant_id": str(tenant_id),
        }
        if platform:
            bill_params["platform"] = platform

        bill_result = await db.execute(
            text(f"""
                SELECT COALESCE(SUM(gross_amount_fen), 0) AS total_bill_fen
                FROM platform_bills
                WHERE store_id = :store_id::UUID
                  AND tenant_id = :tenant_id::UUID
                  {platform_filter.replace('sd.platform', 'platform') if platform else ''}
            """),
            bill_params,
        )
        bill_row = bill_result.mappings().first()
        total_bill_fen = int(bill_row["total_bill_fen"]) if bill_row else 0
        diff_rate = (total_diff / total_bill_fen) if total_bill_fen > 0 else 0.0

        return DiscrepancySummary(
            total_discrepancy_count=total_count,
            open_count=open_count,
            total_diff_fen=total_diff,
            diff_rate=round(diff_rate, 6),
        )
