"""P0 报表引擎 — 8张每日必看报表的结构化 Pydantic 模型 + 异步查询实现

设计原则：
- 每张报表对应独立的 async 方法，返回强类型 Pydantic V2 模型
- 所有 DB 查询强制 tenant_id 过滤（RLS 兼容）
- DB 不可用时抛 RuntimeError（不返回空数据掩盖故障）
- 金额字段统一以「分(fen)」存储，接口层按需转元
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()


# ──────────────────────────────────────────────
# 1. 营业收入汇总表 — DailyRevenueSummary
# ──────────────────────────────────────────────

class StoreRevenueLine(BaseModel):
    """单店单日营收明细行"""
    store_id: str
    store_name: str
    biz_date: date
    order_count: int
    table_count: int
    revenue_fen: int = Field(description="实收金额（分）")
    discount_fen: int = Field(description="折扣金额（分）")
    avg_ticket_fen: int = Field(description="人均消费（分）")
    vs_yesterday_pct: Optional[float] = Field(None, description="较昨日涨幅%")
    vs_last_week_pct: Optional[float] = Field(None, description="较上周同日涨幅%")


class DailyRevenueSummary(BaseModel):
    """营业收入汇总表（P0）"""
    tenant_id: str
    biz_date: date
    generated_at: datetime
    total_revenue_fen: int
    total_orders: int
    store_lines: list[StoreRevenueLine]


# ──────────────────────────────────────────────
# 2. 付款折扣表 — PaymentDiscountReport
# ──────────────────────────────────────────────

class DiscountLine(BaseModel):
    """折扣明细行"""
    discount_type: str = Field(description="折扣类型：member/employee/activity/manual/none")
    discount_label: str
    use_count: int
    discount_fen: int
    operator_name: Optional[str] = None
    pct_of_total: float = Field(description="占当日总折扣的比例%")


class PaymentDiscountReport(BaseModel):
    """门店付款折扣表（P0）"""
    tenant_id: str
    store_id: str
    store_name: str
    biz_date: date
    generated_at: datetime
    total_discount_fen: int
    lines: list[DiscountLine]


# ──────────────────────────────────────────────
# 3. 门店日现金流 — CashflowByStore / DailyCashflow
# ──────────────────────────────────────────────

class CashflowLine(BaseModel):
    """支付方式现金流明细行"""
    store_id: str
    store_name: str
    payment_method: str
    income_fen: int
    refund_fen: int
    net_fen: int


class CashflowByStore(BaseModel):
    """门店日现金流报表 — 多店汇总（P0）"""
    tenant_id: str
    biz_date: date
    generated_at: datetime
    total_income_fen: int
    total_refund_fen: int
    total_net_fen: int
    lines: list[CashflowLine]


class DailyCashflow(BaseModel):
    """门店日现金流报表 — 单店详情（P0，含找零/备用金）"""
    tenant_id: str
    store_id: str
    store_name: str
    biz_date: date
    generated_at: datetime
    cash_start_fen: int = Field(0, description="备用金（分）")
    cash_income_fen: int = Field(description="现金实收（分）")
    cash_change_fen: int = Field(0, description="找零合计（分）")
    cash_net_fen: int = Field(description="现金净收（分）")
    total_income_fen: int
    total_refund_fen: int
    total_net_fen: int
    lines: list[CashflowLine]


# ──────────────────────────────────────────────
# 4. 菜品销售统计表 — DishSalesStats
# ──────────────────────────────────────────────

class DishSalesLine(BaseModel):
    """菜品销售明细行"""
    dish_name: str
    category_name: Optional[str] = None
    price_fen: int = Field(description="标准售价（分）")
    sales_qty: int
    sales_amount_fen: int
    revenue_pct: float = Field(description="占总销售额%")
    qty_rank: int
    revenue_rank: int
    vs_yesterday_qty_pct: Optional[float] = None


class DishSalesStats(BaseModel):
    """菜品销售统计表（P0）"""
    tenant_id: str
    store_id: str
    biz_date: date
    generated_at: datetime
    total_sales_fen: int
    total_qty: int
    lines: list[DishSalesLine]


# ──────────────────────────────────────────────
# 5. 账单稽核表 — BillingAudit
# ──────────────────────────────────────────────

class AnomalyLine(BaseModel):
    """异常订单行"""
    order_no: str
    table_label: Optional[str] = None
    total_amount_fen: int
    discount_fen: int
    actual_fen: int
    anomaly_type: str = Field(description="high_discount/return_dish/refund/manual/normal")
    operator_name: Optional[str] = None
    created_at: datetime


class BillingAudit(BaseModel):
    """账单稽核表（P0）"""
    tenant_id: str
    store_id: str
    biz_date: date
    generated_at: datetime
    anomaly_count: int
    total_anomaly_discount_fen: int
    lines: list[AnomalyLine]


# ──────────────────────────────────────────────
# 6. 实时营业统计 — RealtimeStoreStats
# ──────────────────────────────────────────────

class RealtimeStoreStats(BaseModel):
    """门店实时营业统计（P0，今日截至当前）"""
    tenant_id: str
    store_id: str
    store_name: str
    as_of: datetime = Field(description="数据截至时间")
    revenue_fen: int = Field(description="今日实收（分）")
    order_count: int
    paid_count: int
    avg_ticket_fen: int
    occupied_tables: int
    total_tables: int
    occupancy_pct: float
    waiting_groups: int = Field(0, description="当前等位组数")
    peak_hour: Optional[int] = None


# ──────────────────────────────────────────────
# 7. 每日收款分门店统计表 — StoreRevenue (list)
# ──────────────────────────────────────────────

class StoreRevenue(BaseModel):
    """单店收款汇总行"""
    store_id: str
    store_name: str
    biz_date: date
    payment_method: str
    payment_count: int
    collection_fen: int
    pct: float = Field(description="占该门店当日收款%")


# ──────────────────────────────────────────────
# P0Reports — 异步查询服务类
# ──────────────────────────────────────────────

_DISCOUNT_LABELS: dict[str, str] = {
    "member": "会员折扣",
    "employee": "员工折扣",
    "activity": "活动折扣",
    "manual": "手动折扣",
    "none": "无折扣",
}


def _require_db(db: Optional[AsyncSession]) -> AsyncSession:
    """校验 DB 会话可用，不可用时抛明确错误（不返回空数据掩盖故障）"""
    if db is None:
        raise RuntimeError(
            "Database session is required for P0 reports. "
            "Ensure db is injected via dependency injection."
        )
    return db


class P0Reports:
    """P0 报表服务 — 8张每日必看报表的异步实现"""

    # ── 1. 营业收入汇总表 ──

    async def daily_revenue_summary(
        self,
        tenant_id: str,
        store_ids: Optional[list[str]],
        target_date: date,
        db: Optional[AsyncSession] = None,
    ) -> DailyRevenueSummary:
        """营业收入汇总表（P0）

        - 多门店汇总 / 单店明细两种模式
        - 字段：门店/营业额/桌次/人均/同比昨天/同比上周同日
        - 数据源：orders WHERE status='paid' AND DATE(completed_at)=date
        """
        session = _require_db(db)
        log.info("p0.daily_revenue_summary", tenant_id=tenant_id, date=str(target_date))

        from datetime import timedelta
        yesterday = target_date - timedelta(days=1)
        last_week = target_date - timedelta(days=7)

        store_filter = (
            "AND o.store_id = ANY(:store_ids)"
            if store_ids
            else ""
        )

        sql = text(f"""
            SELECT
                o.store_id::text                                              AS store_id,
                s.store_name,
                COUNT(*)                                                       AS order_count,
                COUNT(DISTINCT o.table_id)                                     AS table_count,
                COALESCE(SUM(o.final_amount_fen), 0)                          AS revenue_fen,
                COALESCE(SUM(o.discount_amount_fen), 0)                       AS discount_fen,
                CASE WHEN COUNT(*) > 0
                     THEN COALESCE(SUM(o.final_amount_fen), 0) / COUNT(*)
                     ELSE 0
                END                                                            AS avg_ticket_fen
            FROM orders o
            JOIN stores s ON s.id = o.store_id AND s.tenant_id = o.tenant_id
            WHERE o.tenant_id  = :tenant_id
              AND o.is_deleted = FALSE
              AND o.status     = 'paid'
              AND COALESCE(o.biz_date, DATE(o.created_at)) = :target_date
              {store_filter}
            GROUP BY o.store_id, s.store_name
            ORDER BY revenue_fen DESC
        """)

        params: dict = {"tenant_id": tenant_id, "target_date": target_date}
        if store_ids:
            params["store_ids"] = store_ids

        result = await session.execute(sql, params)
        rows = result.mappings().all()

        # 查询昨日 / 上周同日 数据用于环比
        cmp_sql = text(f"""
            SELECT
                o.store_id::text AS store_id,
                COALESCE(o.biz_date, DATE(o.created_at))              AS biz_date,
                COALESCE(SUM(o.final_amount_fen), 0)                  AS revenue_fen
            FROM orders o
            WHERE o.tenant_id  = :tenant_id
              AND o.is_deleted = FALSE
              AND o.status     = 'paid'
              AND COALESCE(o.biz_date, DATE(o.created_at)) IN (:yesterday, :last_week)
              {store_filter}
            GROUP BY o.store_id, COALESCE(o.biz_date, DATE(o.created_at))
        """)
        cmp_params: dict = {
            "tenant_id": tenant_id,
            "yesterday": yesterday,
            "last_week": last_week,
        }
        if store_ids:
            cmp_params["store_ids"] = store_ids

        cmp_result = await session.execute(cmp_sql, cmp_params)
        cmp_rows = cmp_result.mappings().all()

        # 建立比较数据索引
        cmp_index: dict[tuple, int] = {}
        for r in cmp_rows:
            cmp_index[(r["store_id"], str(r["biz_date"]))] = r["revenue_fen"]

        def _pct(current: int, previous: int) -> Optional[float]:
            if previous <= 0:
                return None
            return round((current - previous) / previous * 100, 1)

        lines = []
        total_revenue = 0
        total_orders = 0
        for r in rows:
            sid = r["store_id"]
            rev = r["revenue_fen"]
            total_revenue += rev
            total_orders += r["order_count"]
            lines.append(StoreRevenueLine(
                store_id=sid,
                store_name=r["store_name"],
                biz_date=target_date,
                order_count=r["order_count"],
                table_count=r["table_count"],
                revenue_fen=rev,
                discount_fen=r["discount_fen"],
                avg_ticket_fen=r["avg_ticket_fen"],
                vs_yesterday_pct=_pct(rev, cmp_index.get((sid, str(yesterday)), 0)),
                vs_last_week_pct=_pct(rev, cmp_index.get((sid, str(last_week)), 0)),
            ))

        return DailyRevenueSummary(
            tenant_id=tenant_id,
            biz_date=target_date,
            generated_at=datetime.now(timezone.utc),
            total_revenue_fen=total_revenue,
            total_orders=total_orders,
            store_lines=lines,
        )

    # ── 2. 付款折扣表 ──

    async def payment_discount_report(
        self,
        tenant_id: str,
        store_id: str,
        target_date: date,
        db: Optional[AsyncSession] = None,
    ) -> PaymentDiscountReport:
        """门店付款折扣表（P0）

        - 各折扣类型：会员折扣/员工折扣/活动折扣/手动折扣
        - 字段：折扣类型/使用次数/折扣金额/操作员/占比
        - 数据源：orders + discount_audit_log WHERE DATE(created_at)=date
        """
        session = _require_db(db)
        log.info(
            "p0.payment_discount_report",
            tenant_id=tenant_id,
            store_id=store_id,
            date=str(target_date),
        )

        sql = text("""
            SELECT
                COALESCE(o.order_metadata->>'discount_type', 'none') AS discount_type,
                COUNT(*)                                               AS use_count,
                COALESCE(SUM(o.discount_amount_fen), 0)               AS discount_fen,
                s.store_name
            FROM orders o
            JOIN stores s ON s.id = o.store_id AND s.tenant_id = o.tenant_id
            WHERE o.tenant_id  = :tenant_id
              AND o.store_id   = :store_id::UUID
              AND o.is_deleted = FALSE
              AND o.status     = 'paid'
              AND COALESCE(o.biz_date, DATE(o.created_at)) = :target_date
              AND COALESCE(o.discount_amount_fen, 0) > 0
            GROUP BY COALESCE(o.order_metadata->>'discount_type', 'none'), s.store_name
            ORDER BY discount_fen DESC
        """)
        result = await session.execute(
            sql,
            {"tenant_id": tenant_id, "store_id": store_id, "target_date": target_date},
        )
        rows = result.mappings().all()

        total_discount_fen = sum(r["discount_fen"] for r in rows)
        store_name = rows[0]["store_name"] if rows else store_id

        lines = [
            DiscountLine(
                discount_type=r["discount_type"],
                discount_label=_DISCOUNT_LABELS.get(r["discount_type"], r["discount_type"]),
                use_count=r["use_count"],
                discount_fen=r["discount_fen"],
                pct_of_total=(
                    round(r["discount_fen"] / total_discount_fen * 100, 2)
                    if total_discount_fen > 0 else 0.0
                ),
            )
            for r in rows
        ]

        return PaymentDiscountReport(
            tenant_id=tenant_id,
            store_id=store_id,
            store_name=store_name,
            biz_date=target_date,
            generated_at=datetime.now(timezone.utc),
            total_discount_fen=total_discount_fen,
            lines=lines,
        )

    # ── 3a. 收款分门店汇总 ──

    async def cashflow_by_store(
        self,
        tenant_id: str,
        target_date: date,
        db: Optional[AsyncSession] = None,
    ) -> CashflowByStore:
        """门店日现金流报表（P0）

        - 按支付方式分类（现金/微信/支付宝/刷卡/挂账）
        - 字段：门店/支付方式/收款金额/退款金额/净收款
        - 数据源：payments + refunds 表
        """
        session = _require_db(db)
        log.info("p0.cashflow_by_store", tenant_id=tenant_id, date=str(target_date))

        income_sql = text("""
            SELECT
                o.store_id::text                       AS store_id,
                s.store_name,
                COALESCE(p.method, 'unknown')          AS payment_method,
                COALESCE(SUM(p.amount_fen), 0)         AS income_fen
            FROM payments p
            JOIN orders o ON p.order_id = o.id AND p.tenant_id = o.tenant_id
            JOIN stores s ON s.id = o.store_id AND s.tenant_id = o.tenant_id
            WHERE p.tenant_id  = :tenant_id
              AND p.is_deleted = FALSE
              AND p.status     = 'paid'
              AND o.is_deleted = FALSE
              AND COALESCE(o.biz_date, DATE(p.paid_at)) = :target_date
            GROUP BY o.store_id, s.store_name, COALESCE(p.method, 'unknown')
        """)

        refund_sql = text("""
            SELECT
                o.store_id::text                       AS store_id,
                COALESCE(p.method, 'unknown')          AS payment_method,
                COALESCE(SUM(r.amount_fen), 0)         AS refund_fen
            FROM refunds r
            JOIN orders o ON r.order_id = o.id AND r.tenant_id = o.tenant_id
            JOIN payments p ON r.payment_id = p.id AND r.tenant_id = p.tenant_id
            WHERE r.tenant_id  = :tenant_id
              AND r.is_deleted = FALSE
              AND o.is_deleted = FALSE
              AND COALESCE(o.biz_date, DATE(r.refunded_at)) = :target_date
            GROUP BY o.store_id, COALESCE(p.method, 'unknown')
        """)

        params = {"tenant_id": tenant_id, "target_date": target_date}
        income_rows = (await session.execute(income_sql, params)).mappings().all()
        refund_rows = (await session.execute(refund_sql, params)).mappings().all()

        refund_index: dict[tuple, int] = {
            (r["store_id"], r["payment_method"]): r["refund_fen"]
            for r in refund_rows
        }

        lines = []
        total_income = 0
        total_refund = 0
        for r in income_rows:
            ref = refund_index.get((r["store_id"], r["payment_method"]), 0)
            net = r["income_fen"] - ref
            total_income += r["income_fen"]
            total_refund += ref
            lines.append(CashflowLine(
                store_id=r["store_id"],
                store_name=r["store_name"],
                payment_method=r["payment_method"],
                income_fen=r["income_fen"],
                refund_fen=ref,
                net_fen=net,
            ))

        return CashflowByStore(
            tenant_id=tenant_id,
            biz_date=target_date,
            generated_at=datetime.now(timezone.utc),
            total_income_fen=total_income,
            total_refund_fen=total_refund,
            total_net_fen=total_income - total_refund,
            lines=lines,
        )

    # ── 3b. 单店日现金流（含找零/备用金）──

    async def cashflow_daily(
        self,
        tenant_id: str,
        store_id: str,
        target_date: date,
        db: Optional[AsyncSession] = None,
    ) -> DailyCashflow:
        """门店日现金流报表（P0）— 单店详情，含找零/备用金"""
        session = _require_db(db)
        log.info(
            "p0.cashflow_daily",
            tenant_id=tenant_id,
            store_id=store_id,
            date=str(target_date),
        )

        # 汇总收款
        income_sql = text("""
            SELECT
                s.store_name,
                COALESCE(p.method, 'unknown')     AS payment_method,
                COALESCE(SUM(p.amount_fen), 0)    AS income_fen
            FROM payments p
            JOIN orders o ON p.order_id = o.id AND p.tenant_id = o.tenant_id
            JOIN stores s ON s.id = o.store_id AND s.tenant_id = o.tenant_id
            WHERE p.tenant_id  = :tenant_id
              AND o.store_id   = :store_id::UUID
              AND p.is_deleted = FALSE
              AND p.status     = 'paid'
              AND o.is_deleted = FALSE
              AND COALESCE(o.biz_date, DATE(p.paid_at)) = :target_date
            GROUP BY s.store_name, COALESCE(p.method, 'unknown')
        """)

        refund_sql = text("""
            SELECT
                COALESCE(p.method, 'unknown')     AS payment_method,
                COALESCE(SUM(r.amount_fen), 0)    AS refund_fen
            FROM refunds r
            JOIN orders o ON r.order_id = o.id AND r.tenant_id = o.tenant_id
            JOIN payments p ON r.payment_id = p.id AND r.tenant_id = p.tenant_id
            WHERE r.tenant_id  = :tenant_id
              AND o.store_id   = :store_id::UUID
              AND r.is_deleted = FALSE
              AND o.is_deleted = FALSE
              AND COALESCE(o.biz_date, DATE(r.refunded_at)) = :target_date
            GROUP BY COALESCE(p.method, 'unknown')
        """)

        # 查询备用金和找零
        cash_sql = text("""
            SELECT
                COALESCE(SUM(CASE WHEN cs.type = 'opening' THEN cs.amount_fen END), 0) AS cash_start_fen,
                COALESCE(SUM(CASE WHEN cs.type = 'change'  THEN cs.amount_fen END), 0) AS cash_change_fen
            FROM cash_sessions cs
            WHERE cs.tenant_id  = :tenant_id
              AND cs.store_id   = :store_id::UUID
              AND DATE(cs.session_date) = :target_date
              AND cs.is_deleted = FALSE
        """)

        params = {"tenant_id": tenant_id, "store_id": store_id, "target_date": target_date}
        income_rows = (await session.execute(income_sql, params)).mappings().all()
        refund_rows = (await session.execute(refund_sql, params)).mappings().all()

        # 备用金查询失败时安全降级（表可能不存在）
        cash_start = 0
        cash_change = 0
        try:
            cash_row = (await session.execute(cash_sql, params)).mappings().first()
            if cash_row:
                cash_start = cash_row["cash_start_fen"]
                cash_change = cash_row["cash_change_fen"]
        except Exception:  # cash_sessions 表可能未迁移
            log.warning("p0.cashflow_daily.cash_sessions_unavailable", store_id=store_id)

        store_name = income_rows[0]["store_name"] if income_rows else store_id
        refund_index: dict[str, int] = {r["payment_method"]: r["refund_fen"] for r in refund_rows}

        lines = []
        total_income = 0
        total_refund = 0
        cash_income = 0
        for r in income_rows:
            ref = refund_index.get(r["payment_method"], 0)
            total_income += r["income_fen"]
            total_refund += ref
            if r["payment_method"] == "cash":
                cash_income += r["income_fen"]
            lines.append(CashflowLine(
                store_id=store_id,
                store_name=store_name,
                payment_method=r["payment_method"],
                income_fen=r["income_fen"],
                refund_fen=ref,
                net_fen=r["income_fen"] - ref,
            ))

        return DailyCashflow(
            tenant_id=tenant_id,
            store_id=store_id,
            store_name=store_name,
            biz_date=target_date,
            generated_at=datetime.now(timezone.utc),
            cash_start_fen=cash_start,
            cash_income_fen=cash_income,
            cash_change_fen=cash_change,
            cash_net_fen=cash_income - cash_change,
            total_income_fen=total_income,
            total_refund_fen=total_refund,
            total_net_fen=total_income - total_refund,
            lines=lines,
        )

    # ── 4. 菜品销售统计表 ──

    async def dish_sales_stats(
        self,
        tenant_id: str,
        store_id: str,
        target_date: date,
        db: Optional[AsyncSession] = None,
    ) -> DishSalesStats:
        """菜品销售统计表（P0）

        - 字段：菜品名/分类/售价/销量/销售额/占比/同比
        - 排序：按销售额降序
        """
        session = _require_db(db)
        log.info(
            "p0.dish_sales_stats",
            tenant_id=tenant_id,
            store_id=store_id,
            date=str(target_date),
        )

        from datetime import timedelta
        yesterday = target_date - timedelta(days=1)

        sql = text("""
            WITH today AS (
                SELECT
                    d.id                                                   AS dish_id,
                    d.dish_name,
                    dc.name                                                AS category_name,
                    COALESCE(d.price_fen, 0)                              AS price_fen,
                    SUM(oi.quantity)                                       AS sales_qty,
                    SUM(oi.subtotal_fen)                                   AS sales_amount_fen,
                    ROUND(
                        SUM(oi.subtotal_fen)::NUMERIC
                        / NULLIF(SUM(SUM(oi.subtotal_fen)) OVER (), 0) * 100,
                    2)                                                     AS revenue_pct,
                    RANK() OVER (ORDER BY SUM(oi.quantity) DESC)          AS qty_rank,
                    RANK() OVER (ORDER BY SUM(oi.subtotal_fen) DESC)      AS revenue_rank
                FROM order_items oi
                JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
                JOIN dishes d ON d.id = oi.dish_id AND d.tenant_id = oi.tenant_id
                LEFT JOIN dish_categories dc
                       ON dc.id = d.category_id AND dc.tenant_id = d.tenant_id
                WHERE o.tenant_id  = :tenant_id
                  AND o.store_id   = :store_id::UUID
                  AND o.is_deleted = FALSE
                  AND oi.is_deleted = FALSE
                  AND o.status     = 'paid'
                  AND COALESCE(o.biz_date, DATE(o.created_at)) = :target_date
                GROUP BY d.id, d.dish_name, dc.name, COALESCE(d.price_fen, 0)
            ),
            prev AS (
                SELECT
                    d.id                 AS dish_id,
                    SUM(oi.quantity)     AS sales_qty_prev
                FROM order_items oi
                JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
                JOIN dishes d ON d.id = oi.dish_id AND d.tenant_id = oi.tenant_id
                WHERE o.tenant_id  = :tenant_id
                  AND o.store_id   = :store_id::UUID
                  AND o.is_deleted = FALSE
                  AND oi.is_deleted = FALSE
                  AND o.status     = 'paid'
                  AND COALESCE(o.biz_date, DATE(o.created_at)) = :yesterday
                GROUP BY d.id
            )
            SELECT
                t.*,
                CASE WHEN p.sales_qty_prev > 0
                     THEN ROUND(
                         (t.sales_qty - p.sales_qty_prev)::NUMERIC
                         / p.sales_qty_prev * 100, 1)
                     ELSE NULL
                END AS vs_yesterday_qty_pct
            FROM today t
            LEFT JOIN prev p ON p.dish_id = t.dish_id
            ORDER BY t.sales_amount_fen DESC
        """)

        result = await session.execute(
            sql,
            {"tenant_id": tenant_id, "store_id": store_id,
             "target_date": target_date, "yesterday": yesterday},
        )
        rows = result.mappings().all()

        total_sales = sum(r["sales_amount_fen"] for r in rows)
        total_qty = sum(r["sales_qty"] for r in rows)

        lines = [
            DishSalesLine(
                dish_name=r["dish_name"],
                category_name=r["category_name"],
                price_fen=r["price_fen"],
                sales_qty=r["sales_qty"],
                sales_amount_fen=r["sales_amount_fen"],
                revenue_pct=float(r["revenue_pct"] or 0),
                qty_rank=r["qty_rank"],
                revenue_rank=r["revenue_rank"],
                vs_yesterday_qty_pct=(
                    float(r["vs_yesterday_qty_pct"])
                    if r["vs_yesterday_qty_pct"] is not None
                    else None
                ),
            )
            for r in rows
        ]

        return DishSalesStats(
            tenant_id=tenant_id,
            store_id=store_id,
            biz_date=target_date,
            generated_at=datetime.now(timezone.utc),
            total_sales_fen=total_sales,
            total_qty=total_qty,
            lines=lines,
        )

    # ── 5. 账单稽核表 ──

    async def billing_audit(
        self,
        tenant_id: str,
        store_id: str,
        target_date: date,
        db: Optional[AsyncSession] = None,
    ) -> BillingAudit:
        """账单稽核表（P0）

        - 异常订单检测：退单/折扣异常/时间异常/金额异常
        - 字段：订单号/桌号/金额/异常类型/操作员/时间
        """
        session = _require_db(db)
        log.info(
            "p0.billing_audit",
            tenant_id=tenant_id,
            store_id=store_id,
            date=str(target_date),
        )

        sql = text("""
            WITH anomaly AS (
                SELECT
                    o.order_no,
                    t.label                                                    AS table_label,
                    o.total_amount_fen,
                    COALESCE(o.discount_amount_fen, 0)                        AS discount_fen,
                    COALESCE(o.final_amount_fen,
                             o.total_amount_fen - COALESCE(o.discount_amount_fen, 0)) AS actual_fen,
                    e.employee_name                                            AS operator_name,
                    o.created_at,
                    -- 折扣超过应收50%
                    COALESCE(o.discount_amount_fen, 0) > o.total_amount_fen * 0.5
                        AS is_high_discount,
                    -- 存在退菜
                    (SELECT COUNT(*) > 0
                     FROM order_items oi
                     WHERE oi.order_id = o.id
                       AND oi.tenant_id = o.tenant_id
                       AND oi.is_deleted = FALSE
                       AND (oi.status = 'returned' OR oi.notes LIKE '%%退%%'))
                        AS has_return,
                    -- 存在退款
                    (SELECT COUNT(*) > 0
                     FROM refunds r
                     WHERE r.order_id = o.id
                       AND r.tenant_id = o.tenant_id
                       AND r.is_deleted = FALSE)
                        AS has_refund,
                    -- 手工操作
                    o.order_metadata->>'manual_adjust' = 'true'
                    OR o.order_metadata->>'discount_type' = 'manual'
                        AS is_manual
                FROM orders o
                LEFT JOIN tables t
                       ON t.id = o.table_id AND t.tenant_id = o.tenant_id
                LEFT JOIN employees e
                       ON e.id = o.cashier_id AND e.tenant_id = o.tenant_id
                WHERE o.tenant_id  = :tenant_id
                  AND o.store_id   = :store_id::UUID
                  AND o.is_deleted = FALSE
                  AND COALESCE(o.biz_date, DATE(o.created_at)) = :target_date
            )
            SELECT
                order_no,
                table_label,
                total_amount_fen,
                discount_fen,
                actual_fen,
                operator_name,
                created_at,
                CASE
                    WHEN is_high_discount THEN 'high_discount'
                    WHEN has_return       THEN 'return_dish'
                    WHEN has_refund       THEN 'refund'
                    WHEN is_manual        THEN 'manual'
                END AS anomaly_type
            FROM anomaly
            WHERE is_high_discount OR has_return OR has_refund OR is_manual
            ORDER BY created_at DESC
        """)

        result = await session.execute(
            sql,
            {"tenant_id": tenant_id, "store_id": store_id, "target_date": target_date},
        )
        rows = result.mappings().all()

        total_anomaly_discount = sum(
            r["discount_fen"] for r in rows
            if r["anomaly_type"] in ("high_discount", "manual")
        )

        lines = [
            AnomalyLine(
                order_no=r["order_no"],
                table_label=r["table_label"],
                total_amount_fen=r["total_amount_fen"],
                discount_fen=r["discount_fen"],
                actual_fen=r["actual_fen"],
                anomaly_type=r["anomaly_type"],
                operator_name=r["operator_name"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

        return BillingAudit(
            tenant_id=tenant_id,
            store_id=store_id,
            biz_date=target_date,
            generated_at=datetime.now(timezone.utc),
            anomaly_count=len(lines),
            total_anomaly_discount_fen=total_anomaly_discount,
            lines=lines,
        )

    # ── 6. 实时营业统计 ──

    async def realtime_store_stats(
        self,
        tenant_id: str,
        store_id: str,
        db: Optional[AsyncSession] = None,
    ) -> RealtimeStoreStats:
        """门店实时营业统计（P0，今日截至当前）

        - 实时营业额/桌次/在台桌数/等位人数/今日人均
        """
        session = _require_db(db)
        log.info(
            "p0.realtime_store_stats",
            tenant_id=tenant_id,
            store_id=store_id,
        )

        revenue_sql = text("""
            SELECT
                s.store_name,
                COUNT(*)                                              AS order_count,
                COUNT(*) FILTER (WHERE o.status = 'paid')            AS paid_count,
                COALESCE(SUM(o.final_amount_fen)
                    FILTER (WHERE o.status = 'paid'), 0)             AS revenue_fen,
                CASE WHEN COUNT(*) FILTER (WHERE o.status = 'paid') > 0
                     THEN COALESCE(SUM(o.final_amount_fen)
                              FILTER (WHERE o.status = 'paid'), 0)
                          / COUNT(*) FILTER (WHERE o.status = 'paid')
                     ELSE 0
                END                                                   AS avg_ticket_fen,
                MAX(EXTRACT(HOUR FROM o.created_at)
                    FILTER (WHERE o.status = 'paid'))::INT            AS peak_hour
            FROM orders o
            JOIN stores s ON s.id = o.store_id AND s.tenant_id = o.tenant_id
            WHERE o.tenant_id  = :tenant_id
              AND o.store_id   = :store_id::UUID
              AND o.is_deleted = FALSE
              AND COALESCE(o.biz_date, DATE(o.created_at)) = CURRENT_DATE
            GROUP BY s.store_name
        """)

        table_sql = text("""
            SELECT
                COUNT(*) FILTER (WHERE status = 'occupied') AS occupied_tables,
                COUNT(*)                                     AS total_tables
            FROM tables
            WHERE store_id   = :store_id::UUID
              AND tenant_id  = :tenant_id
              AND is_deleted = FALSE
        """)

        waiting_sql = text("""
            SELECT COUNT(*) AS waiting_groups
            FROM waitlist
            WHERE store_id   = :store_id::UUID
              AND tenant_id  = :tenant_id
              AND status     = 'waiting'
              AND is_deleted = FALSE
        """)

        params = {"tenant_id": tenant_id, "store_id": store_id}
        rev_row = (await session.execute(revenue_sql, params)).mappings().first()
        tbl_row = (await session.execute(table_sql, params)).mappings().first()

        waiting = 0
        try:
            w_row = (await session.execute(waiting_sql, params)).mappings().first()
            if w_row:
                waiting = w_row["waiting_groups"]
        except Exception:
            log.warning("p0.realtime_store_stats.waitlist_unavailable", store_id=store_id)

        store_name = rev_row["store_name"] if rev_row else store_id
        revenue_fen = rev_row["revenue_fen"] if rev_row else 0
        order_count = rev_row["order_count"] if rev_row else 0
        paid_count = rev_row["paid_count"] if rev_row else 0
        avg_ticket_fen = rev_row["avg_ticket_fen"] if rev_row else 0
        peak_hour = rev_row["peak_hour"] if rev_row else None

        occupied = tbl_row["occupied_tables"] if tbl_row else 0
        total = tbl_row["total_tables"] if tbl_row else 0
        occupancy_pct = round(occupied / total * 100, 1) if total > 0 else 0.0

        return RealtimeStoreStats(
            tenant_id=tenant_id,
            store_id=store_id,
            store_name=store_name,
            as_of=datetime.now(timezone.utc),
            revenue_fen=revenue_fen,
            order_count=order_count,
            paid_count=paid_count,
            avg_ticket_fen=avg_ticket_fen,
            occupied_tables=occupied,
            total_tables=total,
            occupancy_pct=occupancy_pct,
            waiting_groups=waiting,
            peak_hour=peak_hour,
        )

    # ── 7. 每日收款分门店统计表 ──

    async def daily_revenue_by_store(
        self,
        tenant_id: str,
        target_date: date,
        db: Optional[AsyncSession] = None,
    ) -> list[StoreRevenue]:
        """每日收款分门店统计表（P0）

        按门店 + 支付方式汇总 payments，含占比。
        """
        session = _require_db(db)
        log.info(
            "p0.daily_revenue_by_store",
            tenant_id=tenant_id,
            date=str(target_date),
        )

        sql = text("""
            SELECT
                o.store_id::text                                               AS store_id,
                s.store_name,
                COALESCE(p.method, 'unknown')                                  AS payment_method,
                COUNT(*)                                                        AS payment_count,
                COALESCE(SUM(p.amount_fen), 0)                                 AS collection_fen,
                ROUND(
                    COALESCE(SUM(p.amount_fen), 0)::NUMERIC
                    / NULLIF(
                        SUM(SUM(p.amount_fen)) OVER (
                            PARTITION BY o.store_id,
                                         COALESCE(o.biz_date, DATE(p.paid_at))
                        ), 0
                    ) * 100,
                2)                                                              AS pct
            FROM payments p
            JOIN orders o ON p.order_id = o.id AND p.tenant_id = o.tenant_id
            JOIN stores s ON s.id = o.store_id AND s.tenant_id = o.tenant_id
            WHERE p.tenant_id  = :tenant_id
              AND p.is_deleted = FALSE
              AND p.status     = 'paid'
              AND o.is_deleted = FALSE
              AND COALESCE(o.biz_date, DATE(p.paid_at)) = :target_date
            GROUP BY o.store_id, s.store_name,
                     COALESCE(o.biz_date, DATE(p.paid_at)),
                     COALESCE(p.method, 'unknown')
            ORDER BY s.store_name, collection_fen DESC
        """)

        result = await session.execute(
            sql, {"tenant_id": tenant_id, "target_date": target_date}
        )
        rows = result.mappings().all()

        return [
            StoreRevenue(
                store_id=r["store_id"],
                store_name=r["store_name"],
                biz_date=target_date,
                payment_method=r["payment_method"],
                payment_count=r["payment_count"],
                collection_fen=r["collection_fen"],
                pct=float(r["pct"] or 0),
            )
            for r in rows
        ]

    # ── 日汇总（经营诊断 Agent 调用接口）──

    async def daily_summary_for_agent(
        self,
        tenant_id: str,
        store_id: str,
        target_date: date,
        db: Optional[AsyncSession] = None,
    ) -> dict:
        """日汇总供经营诊断 Agent 调用

        聚合当日核心指标，以 dict 形式返回，便于 Agent prompt 直接消费。
        """
        session = _require_db(db)
        log.info(
            "p0.daily_summary_for_agent",
            tenant_id=tenant_id,
            store_id=store_id,
            date=str(target_date),
        )

        # 并发查询各维度
        rev = await self.daily_revenue_summary(
            tenant_id, [store_id], target_date, db=session
        )
        rt = await self.realtime_store_stats(tenant_id, store_id, db=session)
        audit = await self.billing_audit(tenant_id, store_id, target_date, db=session)
        dish = await self.dish_sales_stats(tenant_id, store_id, target_date, db=session)

        store_line = next(
            (s for s in rev.store_lines if s.store_id == store_id), None
        )

        return {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "biz_date": target_date.isoformat(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "revenue": {
                "actual_fen": store_line.revenue_fen if store_line else 0,
                "discount_fen": store_line.discount_fen if store_line else 0,
                "order_count": store_line.order_count if store_line else 0,
                "avg_ticket_fen": store_line.avg_ticket_fen if store_line else 0,
                "vs_yesterday_pct": store_line.vs_yesterday_pct if store_line else None,
                "vs_last_week_pct": store_line.vs_last_week_pct if store_line else None,
            },
            "realtime": {
                "occupancy_pct": rt.occupancy_pct,
                "occupied_tables": rt.occupied_tables,
                "total_tables": rt.total_tables,
                "waiting_groups": rt.waiting_groups,
                "peak_hour": rt.peak_hour,
            },
            "audit": {
                "anomaly_count": audit.anomaly_count,
                "total_anomaly_discount_fen": audit.total_anomaly_discount_fen,
            },
            "top_dishes": [
                {
                    "dish_name": d.dish_name,
                    "sales_qty": d.sales_qty,
                    "sales_amount_fen": d.sales_amount_fen,
                    "revenue_pct": d.revenue_pct,
                }
                for d in dish.lines[:10]
            ],
        }
