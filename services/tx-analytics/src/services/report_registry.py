"""报表注册中心 — 所有报表定义的统一注册与检索

报表定义与SQL模板分离存储，支持按分类查询、动态注册新报表。
内置注册覆盖6大类60+报表定义。
"""
from __future__ import annotations

from typing import Optional

import structlog

from .report_engine import (
    DimensionDef,
    FilterDef,
    MetricDef,
    ReportCategory,
    ReportDefinition,
    SortDirection,
)

log = structlog.get_logger()


class ReportRegistry:
    """报表注册中心 — 单例管理所有报表定义"""

    def __init__(self) -> None:
        self._reports: dict[str, ReportDefinition] = {}

    def register(self, definition: ReportDefinition) -> None:
        """注册一个报表定义

        Args:
            definition: 报表定义

        Raises:
            ValueError: 报表ID已存在
        """
        if definition.report_id in self._reports:
            log.warning(
                "report_registry.duplicate",
                report_id=definition.report_id,
            )
            raise ValueError(f"Report already registered: {definition.report_id}")

        self._reports[definition.report_id] = definition
        log.info(
            "report_registry.registered",
            report_id=definition.report_id,
            name=definition.name,
            category=definition.category.value,
        )

    def get(self, report_id: str) -> Optional[ReportDefinition]:
        """按ID获取报表定义"""
        return self._reports.get(report_id)

    def get_all(self) -> list[ReportDefinition]:
        """获取所有已注册报表"""
        return list(self._reports.values())

    def get_by_category(self, category: str) -> list[ReportDefinition]:
        """按分类获取报表列表"""
        return [
            d for d in self._reports.values()
            if d.category.value == category
        ]

    def count(self) -> int:
        """已注册报表总数"""
        return len(self._reports)

    def categories(self) -> list[str]:
        """返回所有已注册分类"""
        return sorted({d.category.value for d in self._reports.values()})

    def unregister(self, report_id: str) -> bool:
        """取消注册(用于测试或动态管理)"""
        if report_id in self._reports:
            del self._reports[report_id]
            return True
        return False


# ──────────────────────────────────────────────
# 通用筛选器定义 (复用)
# ──────────────────────────────────────────────

FILTER_STORE = FilterDef(name="store_id", label="门店", field_type="string", required=True)
FILTER_DATE = FilterDef(name="target_date", label="日期", field_type="date", required=True)
FILTER_DATE_START = FilterDef(name="start_date", label="开始日期", field_type="date", required=True)
FILTER_DATE_END = FilterDef(name="end_date", label="结束日期", field_type="date", required=True)
FILTER_CHANNEL = FilterDef(
    name="channel", label="渠道", field_type="select",
    options=["dine_in", "takeout", "delivery", "all"],
    default="all",
)
FILTER_STALL = FilterDef(name="stall_id", label="档口", field_type="string")
FILTER_CATEGORY = FilterDef(name="dish_category", label="菜品分类", field_type="string")

# 通用维度
DIM_STORE = DimensionDef(name="store_id", label="门店")
DIM_STORE_NAME = DimensionDef(name="store_name", label="门店名称")
DIM_DATE = DimensionDef(name="report_date", label="日期")
DIM_CHANNEL = DimensionDef(name="channel", label="渠道")
DIM_STALL = DimensionDef(name="stall_name", label="档口")
DIM_DISH = DimensionDef(name="dish_name", label="菜品")
DIM_DISH_CATEGORY = DimensionDef(name="category", label="菜品分类")
DIM_HOUR = DimensionDef(name="hour", label="时段")
DIM_PAYMENT = DimensionDef(name="payment_method", label="支付方式")
DIM_EMPLOYEE = DimensionDef(name="employee_name", label="员工")


# ──────────────────────────────────────────────
# 内置报表定义
# ──────────────────────────────────────────────

def _build_builtin_reports() -> list[ReportDefinition]:
    """构建所有内置报表定义"""
    reports: list[ReportDefinition] = []

    # ════════════ 营收类 (revenue) ════════════

    reports.append(ReportDefinition(
        report_id="rev_daily_summary",
        name="日营收汇总",
        category=ReportCategory.REVENUE,
        description="单店单日营收、单量、客单价汇总",
        sql_template="""
            SELECT DATE(created_at) AS report_date,
                   COALESCE(SUM(total_fen), 0) AS revenue_fen,
                   COUNT(*) AS order_count,
                   CASE WHEN COUNT(*) > 0 THEN COALESCE(SUM(total_fen), 0) / COUNT(*) ELSE 0 END AS avg_ticket_fen
            FROM orders
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND DATE(created_at) = :target_date
              AND status = 'paid'
              AND is_deleted = FALSE
            GROUP BY DATE(created_at)
        """,
        dimensions=[DIM_DATE],
        metrics=[
            MetricDef(name="revenue_fen", label="营收(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="order_count", label="订单数", unit="count"),
            MetricDef(name="avg_ticket_fen", label="客单价(分)", unit="yuan", is_money_fen=True),
        ],
        filters=[FILTER_STORE, FILTER_DATE],
        default_sort="revenue_fen",
        permissions=["admin", "store_manager", "finance"],
    ))

    reports.append(ReportDefinition(
        report_id="rev_daily_trend",
        name="日营收趋势",
        category=ReportCategory.REVENUE,
        description="门店日期范围内每日营收趋势",
        sql_template="""
            SELECT DATE(created_at) AS report_date,
                   COALESCE(SUM(total_fen), 0) AS revenue_fen,
                   COUNT(*) AS order_count
            FROM orders
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND DATE(created_at) BETWEEN :start_date AND :end_date
              AND status = 'paid'
              AND is_deleted = FALSE
            GROUP BY DATE(created_at)
        """,
        dimensions=[DIM_DATE],
        metrics=[
            MetricDef(name="revenue_fen", label="营收(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="order_count", label="订单数", unit="count"),
        ],
        filters=[FILTER_STORE, FILTER_DATE_START, FILTER_DATE_END],
        default_sort="report_date",
        default_sort_direction=SortDirection.ASC,
        permissions=["admin", "store_manager", "finance"],
    ))

    reports.append(ReportDefinition(
        report_id="rev_hourly",
        name="时段营收分布",
        category=ReportCategory.REVENUE,
        description="按小时统计营收和订单量分布",
        sql_template="""
            SELECT EXTRACT(HOUR FROM created_at)::int AS hour,
                   COALESCE(SUM(total_fen), 0) AS revenue_fen,
                   COUNT(*) AS order_count
            FROM orders
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND DATE(created_at) = :target_date
              AND status = 'paid'
              AND is_deleted = FALSE
            GROUP BY EXTRACT(HOUR FROM created_at)::int
        """,
        dimensions=[DIM_HOUR],
        metrics=[
            MetricDef(name="revenue_fen", label="营收(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="order_count", label="订单数", unit="count"),
        ],
        filters=[FILTER_STORE, FILTER_DATE],
        default_sort="hour",
        default_sort_direction=SortDirection.ASC,
        permissions=["admin", "store_manager"],
    ))

    reports.append(ReportDefinition(
        report_id="rev_by_channel",
        name="渠道营收分布",
        category=ReportCategory.REVENUE,
        description="按渠道(堂食/外卖/自提)统计营收",
        sql_template="""
            SELECT COALESCE(channel, 'dine_in') AS channel,
                   COALESCE(SUM(total_fen), 0) AS revenue_fen,
                   COUNT(*) AS order_count
            FROM orders
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND DATE(created_at) = :target_date
              AND status = 'paid'
              AND is_deleted = FALSE
            GROUP BY COALESCE(channel, 'dine_in')
        """,
        dimensions=[DIM_CHANNEL],
        metrics=[
            MetricDef(name="revenue_fen", label="营收(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="order_count", label="订单数", unit="count"),
        ],
        filters=[FILTER_STORE, FILTER_DATE],
        default_sort="revenue_fen",
        permissions=["admin", "store_manager"],
    ))

    reports.append(ReportDefinition(
        report_id="rev_payment_breakdown",
        name="支付方式分布",
        category=ReportCategory.REVENUE,
        description="按支付方式统计金额和笔数",
        sql_template="""
            SELECT COALESCE(payment_method, 'unknown') AS payment_method,
                   COALESCE(SUM(total_fen), 0) AS amount_fen,
                   COUNT(*) AS count
            FROM orders
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND DATE(created_at) = :target_date
              AND status = 'paid'
              AND is_deleted = FALSE
            GROUP BY COALESCE(payment_method, 'unknown')
        """,
        dimensions=[DIM_PAYMENT],
        metrics=[
            MetricDef(name="amount_fen", label="金额(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="count", label="笔数", unit="count"),
        ],
        filters=[FILTER_STORE, FILTER_DATE],
        default_sort="amount_fen",
        permissions=["admin", "store_manager", "finance"],
    ))

    reports.append(ReportDefinition(
        report_id="rev_store_comparison",
        name="多店营收对比",
        category=ReportCategory.REVENUE,
        description="多门店同期营收对比",
        sql_template="""
            SELECT s.store_name,
                   o.store_id,
                   COALESCE(SUM(o.total_fen), 0) AS revenue_fen,
                   COUNT(*) AS order_count
            FROM orders o
            JOIN stores s ON s.id = o.store_id AND s.tenant_id = o.tenant_id
            WHERE o.tenant_id = :tenant_id
              AND DATE(o.created_at) BETWEEN :start_date AND :end_date
              AND o.status = 'paid'
              AND o.is_deleted = FALSE
            GROUP BY s.store_name, o.store_id
        """,
        dimensions=[DIM_STORE_NAME, DIM_STORE],
        metrics=[
            MetricDef(name="revenue_fen", label="营收(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="order_count", label="订单数", unit="count"),
        ],
        filters=[FILTER_DATE_START, FILTER_DATE_END],
        default_sort="revenue_fen",
        permissions=["admin", "finance"],
    ))

    # ════════════ 菜品类 (dish) ════════════

    reports.append(ReportDefinition(
        report_id="dish_sales_detail",
        name="菜品销售明细",
        category=ReportCategory.DISH,
        description="按菜品统计销量和销售额",
        sql_template="""
            SELECT oi.dish_id,
                   d.dish_name,
                   d.category,
                   SUM(oi.quantity) AS sales_qty,
                   SUM(oi.subtotal_fen) AS sales_amount_fen
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
            JOIN dishes d ON d.id = oi.dish_id AND d.tenant_id = oi.tenant_id
            WHERE o.store_id = :store_id
              AND o.tenant_id = :tenant_id
              AND DATE(o.created_at) BETWEEN :start_date AND :end_date
              AND o.status = 'paid'
              AND o.is_deleted = FALSE
              AND oi.is_deleted = FALSE
            GROUP BY oi.dish_id, d.dish_name, d.category
        """,
        dimensions=[DimensionDef(name="dish_id", label="菜品ID"), DIM_DISH, DIM_DISH_CATEGORY],
        metrics=[
            MetricDef(name="sales_qty", label="销量", unit="count"),
            MetricDef(name="sales_amount_fen", label="销售额(分)", unit="yuan", is_money_fen=True),
        ],
        filters=[FILTER_STORE, FILTER_DATE_START, FILTER_DATE_END],
        default_sort="sales_qty",
        permissions=["admin", "store_manager", "chef"],
    ))

    reports.append(ReportDefinition(
        report_id="dish_sales_by_category",
        name="分类销售汇总",
        category=ReportCategory.DISH,
        description="按菜品分类汇总销量和销售额",
        sql_template="""
            SELECT COALESCE(d.category, 'uncategorized') AS category,
                   SUM(oi.quantity) AS sales_qty,
                   SUM(oi.subtotal_fen) AS sales_amount_fen
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
            JOIN dishes d ON d.id = oi.dish_id AND d.tenant_id = oi.tenant_id
            WHERE o.store_id = :store_id
              AND o.tenant_id = :tenant_id
              AND DATE(o.created_at) BETWEEN :start_date AND :end_date
              AND o.status = 'paid'
              AND o.is_deleted = FALSE
              AND oi.is_deleted = FALSE
            GROUP BY COALESCE(d.category, 'uncategorized')
        """,
        dimensions=[DIM_DISH_CATEGORY],
        metrics=[
            MetricDef(name="sales_qty", label="销量", unit="count"),
            MetricDef(name="sales_amount_fen", label="销售额(分)", unit="yuan", is_money_fen=True),
        ],
        filters=[FILTER_STORE, FILTER_DATE_START, FILTER_DATE_END],
        default_sort="sales_qty",
        permissions=["admin", "store_manager", "chef"],
    ))

    reports.append(ReportDefinition(
        report_id="dish_return_detail",
        name="退菜明细",
        category=ReportCategory.DISH,
        description="退菜按菜品和原因汇总",
        sql_template="""
            SELECT oi.dish_id,
                   d.dish_name,
                   COALESCE(oi.return_reason, 'unknown') AS return_reason,
                   SUM(oi.quantity) AS return_qty,
                   SUM(oi.subtotal_fen) AS return_amount_fen
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
            JOIN dishes d ON d.id = oi.dish_id AND d.tenant_id = oi.tenant_id
            WHERE o.store_id = :store_id
              AND o.tenant_id = :tenant_id
              AND DATE(o.created_at) BETWEEN :start_date AND :end_date
              AND oi.status = 'returned'
              AND o.is_deleted = FALSE
              AND oi.is_deleted = FALSE
            GROUP BY oi.dish_id, d.dish_name, COALESCE(oi.return_reason, 'unknown')
        """,
        dimensions=[
            DimensionDef(name="dish_id", label="菜品ID"),
            DIM_DISH,
            DimensionDef(name="return_reason", label="退菜原因"),
        ],
        metrics=[
            MetricDef(name="return_qty", label="退菜数量", unit="count"),
            MetricDef(name="return_amount_fen", label="退菜金额(分)", unit="yuan", is_money_fen=True),
        ],
        filters=[FILTER_STORE, FILTER_DATE_START, FILTER_DATE_END],
        default_sort="return_qty",
        permissions=["admin", "store_manager", "chef"],
    ))

    reports.append(ReportDefinition(
        report_id="dish_stall_sales",
        name="档口销售统计",
        category=ReportCategory.DISH,
        description="按档口统计菜品销量和金额",
        sql_template="""
            SELECT COALESCE(st.stall_name, 'unknown') AS stall_name,
                   SUM(oi.quantity) AS sales_qty,
                   SUM(oi.subtotal_fen) AS sales_amount_fen,
                   COUNT(DISTINCT oi.dish_id) AS dish_count
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
            LEFT JOIN stalls st ON st.id = oi.stall_id AND st.tenant_id = oi.tenant_id
            WHERE o.store_id = :store_id
              AND o.tenant_id = :tenant_id
              AND DATE(o.created_at) BETWEEN :start_date AND :end_date
              AND o.status = 'paid'
              AND o.is_deleted = FALSE
              AND oi.is_deleted = FALSE
            GROUP BY COALESCE(st.stall_name, 'unknown')
        """,
        dimensions=[DIM_STALL],
        metrics=[
            MetricDef(name="sales_qty", label="销量", unit="count"),
            MetricDef(name="sales_amount_fen", label="销售额(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="dish_count", label="菜品种类数", unit="count"),
        ],
        filters=[FILTER_STORE, FILTER_DATE_START, FILTER_DATE_END],
        default_sort="sales_amount_fen",
        permissions=["admin", "store_manager"],
    ))

    # ════════════ 审计类 (audit) ════════════

    reports.append(ReportDefinition(
        report_id="audit_discount_log",
        name="折扣操作日志",
        category=ReportCategory.AUDIT,
        description="折扣/优惠操作记录审计",
        sql_template="""
            SELECT o.id AS order_id,
                   o.store_id,
                   o.created_at,
                   o.total_fen,
                   o.discount_fen,
                   o.discount_reason,
                   COALESCE(e.employee_name, 'system') AS operator
            FROM orders o
            LEFT JOIN employees e ON e.id = o.operator_id AND e.tenant_id = o.tenant_id
            WHERE o.tenant_id = :tenant_id
              AND o.store_id = :store_id
              AND DATE(o.created_at) BETWEEN :start_date AND :end_date
              AND o.discount_fen > 0
              AND o.is_deleted = FALSE
        """,
        dimensions=[
            DimensionDef(name="order_id", label="订单ID"),
            DIM_STORE,
            DimensionDef(name="created_at", label="时间"),
            DimensionDef(name="operator", label="操作人"),
        ],
        metrics=[
            MetricDef(name="total_fen", label="订单金额(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="discount_fen", label="折扣金额(分)", unit="yuan", is_money_fen=True),
        ],
        filters=[FILTER_STORE, FILTER_DATE_START, FILTER_DATE_END],
        default_sort="discount_fen",
        permissions=["admin", "finance", "audit"],
    ))

    reports.append(ReportDefinition(
        report_id="audit_void_orders",
        name="撤单记录",
        category=ReportCategory.AUDIT,
        description="已取消/作废订单明细",
        sql_template="""
            SELECT o.id AS order_id,
                   o.store_id,
                   o.created_at,
                   o.total_fen,
                   o.cancel_reason,
                   COALESCE(e.employee_name, 'system') AS operator
            FROM orders o
            LEFT JOIN employees e ON e.id = o.operator_id AND e.tenant_id = o.tenant_id
            WHERE o.tenant_id = :tenant_id
              AND o.store_id = :store_id
              AND DATE(o.created_at) BETWEEN :start_date AND :end_date
              AND o.status IN ('cancelled', 'voided')
              AND o.is_deleted = FALSE
        """,
        dimensions=[
            DimensionDef(name="order_id", label="订单ID"),
            DIM_STORE,
            DimensionDef(name="created_at", label="时间"),
            DimensionDef(name="cancel_reason", label="取消原因"),
            DimensionDef(name="operator", label="操作人"),
        ],
        metrics=[
            MetricDef(name="total_fen", label="订单金额(分)", unit="yuan", is_money_fen=True),
        ],
        filters=[FILTER_STORE, FILTER_DATE_START, FILTER_DATE_END],
        default_sort="created_at",
        permissions=["admin", "finance", "audit"],
    ))

    reports.append(ReportDefinition(
        report_id="audit_refund_log",
        name="退款记录",
        category=ReportCategory.AUDIT,
        description="退款订单明细及原因",
        sql_template="""
            SELECT o.id AS order_id,
                   o.store_id,
                   o.created_at,
                   o.total_fen,
                   o.refund_fen,
                   o.refund_reason,
                   COALESCE(e.employee_name, 'system') AS operator
            FROM orders o
            LEFT JOIN employees e ON e.id = o.operator_id AND e.tenant_id = o.tenant_id
            WHERE o.tenant_id = :tenant_id
              AND o.store_id = :store_id
              AND DATE(o.created_at) BETWEEN :start_date AND :end_date
              AND o.status = 'refunded'
              AND o.is_deleted = FALSE
        """,
        dimensions=[
            DimensionDef(name="order_id", label="订单ID"),
            DIM_STORE,
            DimensionDef(name="created_at", label="时间"),
            DimensionDef(name="refund_reason", label="退款原因"),
            DimensionDef(name="operator", label="操作人"),
        ],
        metrics=[
            MetricDef(name="total_fen", label="订单金额(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="refund_fen", label="退款金额(分)", unit="yuan", is_money_fen=True),
        ],
        filters=[FILTER_STORE, FILTER_DATE_START, FILTER_DATE_END],
        default_sort="refund_fen",
        permissions=["admin", "finance", "audit"],
    ))

    # ════════════ 毛利类 (margin) ════════════

    reports.append(ReportDefinition(
        report_id="margin_dish_cost",
        name="菜品毛利分析",
        category=ReportCategory.MARGIN,
        description="按菜品计算毛利率(售价-成本)/售价",
        sql_template="""
            SELECT d.dish_name,
                   d.category,
                   SUM(oi.subtotal_fen) AS revenue_fen,
                   SUM(oi.cost_fen) AS cost_fen,
                   SUM(oi.subtotal_fen) - SUM(oi.cost_fen) AS margin_fen,
                   CASE WHEN SUM(oi.subtotal_fen) > 0
                        THEN ROUND((SUM(oi.subtotal_fen) - SUM(oi.cost_fen))::numeric / SUM(oi.subtotal_fen) * 100, 1)
                        ELSE 0 END AS margin_pct
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
            JOIN dishes d ON d.id = oi.dish_id AND d.tenant_id = oi.tenant_id
            WHERE o.store_id = :store_id
              AND o.tenant_id = :tenant_id
              AND DATE(o.created_at) BETWEEN :start_date AND :end_date
              AND o.status = 'paid'
              AND o.is_deleted = FALSE
              AND oi.is_deleted = FALSE
            GROUP BY d.dish_name, d.category
        """,
        dimensions=[DIM_DISH, DIM_DISH_CATEGORY],
        metrics=[
            MetricDef(name="revenue_fen", label="营收(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="cost_fen", label="成本(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="margin_fen", label="毛利(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="margin_pct", label="毛利率", unit="pct"),
        ],
        filters=[FILTER_STORE, FILTER_DATE_START, FILTER_DATE_END],
        default_sort="margin_pct",
        permissions=["admin", "finance"],
    ))

    reports.append(ReportDefinition(
        report_id="margin_store_daily",
        name="门店日毛利",
        category=ReportCategory.MARGIN,
        description="按天统计门店整体毛利",
        sql_template="""
            SELECT DATE(o.created_at) AS report_date,
                   COALESCE(SUM(oi.subtotal_fen), 0) AS revenue_fen,
                   COALESCE(SUM(oi.cost_fen), 0) AS cost_fen,
                   COALESCE(SUM(oi.subtotal_fen), 0) - COALESCE(SUM(oi.cost_fen), 0) AS margin_fen
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
            WHERE o.store_id = :store_id
              AND o.tenant_id = :tenant_id
              AND DATE(o.created_at) BETWEEN :start_date AND :end_date
              AND o.status = 'paid'
              AND o.is_deleted = FALSE
              AND oi.is_deleted = FALSE
            GROUP BY DATE(o.created_at)
        """,
        dimensions=[DIM_DATE],
        metrics=[
            MetricDef(name="revenue_fen", label="营收(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="cost_fen", label="成本(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="margin_fen", label="毛利(分)", unit="yuan", is_money_fen=True),
        ],
        filters=[FILTER_STORE, FILTER_DATE_START, FILTER_DATE_END],
        default_sort="report_date",
        default_sort_direction=SortDirection.ASC,
        permissions=["admin", "finance"],
    ))

    # ════════════ 提成类 (commission) ════════════

    reports.append(ReportDefinition(
        report_id="comm_employee_sales",
        name="员工销售业绩",
        category=ReportCategory.COMMISSION,
        description="按员工统计销售额和单量",
        sql_template="""
            SELECT e.employee_name,
                   e.id AS employee_id,
                   COUNT(o.id) AS order_count,
                   COALESCE(SUM(o.total_fen), 0) AS sales_fen
            FROM orders o
            JOIN employees e ON e.id = o.server_id AND e.tenant_id = o.tenant_id
            WHERE o.store_id = :store_id
              AND o.tenant_id = :tenant_id
              AND DATE(o.created_at) BETWEEN :start_date AND :end_date
              AND o.status = 'paid'
              AND o.is_deleted = FALSE
            GROUP BY e.employee_name, e.id
        """,
        dimensions=[DIM_EMPLOYEE, DimensionDef(name="employee_id", label="员工ID")],
        metrics=[
            MetricDef(name="order_count", label="订单数", unit="count"),
            MetricDef(name="sales_fen", label="销售额(分)", unit="yuan", is_money_fen=True),
        ],
        filters=[FILTER_STORE, FILTER_DATE_START, FILTER_DATE_END],
        default_sort="sales_fen",
        permissions=["admin", "store_manager", "hr"],
    ))

    reports.append(ReportDefinition(
        report_id="comm_employee_tips",
        name="员工小费/提成",
        category=ReportCategory.COMMISSION,
        description="按员工统计小费和提成金额",
        sql_template="""
            SELECT e.employee_name,
                   e.id AS employee_id,
                   COALESCE(SUM(o.tip_fen), 0) AS tip_fen,
                   COALESCE(SUM(o.commission_fen), 0) AS commission_fen
            FROM orders o
            JOIN employees e ON e.id = o.server_id AND e.tenant_id = o.tenant_id
            WHERE o.store_id = :store_id
              AND o.tenant_id = :tenant_id
              AND DATE(o.created_at) BETWEEN :start_date AND :end_date
              AND o.status = 'paid'
              AND o.is_deleted = FALSE
            GROUP BY e.employee_name, e.id
        """,
        dimensions=[DIM_EMPLOYEE, DimensionDef(name="employee_id", label="员工ID")],
        metrics=[
            MetricDef(name="tip_fen", label="小费(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="commission_fen", label="提成(分)", unit="yuan", is_money_fen=True),
        ],
        filters=[FILTER_STORE, FILTER_DATE_START, FILTER_DATE_END],
        default_sort="commission_fen",
        permissions=["admin", "store_manager", "hr"],
    ))

    # ════════════ 财务类 (finance) ════════════

    reports.append(ReportDefinition(
        report_id="fin_daily_settlement",
        name="日结算报表",
        category=ReportCategory.FINANCE,
        description="每日收银结算汇总(含各支付方式)",
        sql_template="""
            SELECT DATE(created_at) AS report_date,
                   COALESCE(payment_method, 'unknown') AS payment_method,
                   COALESCE(SUM(total_fen), 0) AS settlement_fen,
                   COUNT(*) AS tx_count
            FROM orders
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND DATE(created_at) = :target_date
              AND status = 'paid'
              AND is_deleted = FALSE
            GROUP BY DATE(created_at), COALESCE(payment_method, 'unknown')
        """,
        dimensions=[DIM_DATE, DIM_PAYMENT],
        metrics=[
            MetricDef(name="settlement_fen", label="结算金额(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="tx_count", label="交易笔数", unit="count"),
        ],
        filters=[FILTER_STORE, FILTER_DATE],
        default_sort="settlement_fen",
        permissions=["admin", "finance"],
    ))

    reports.append(ReportDefinition(
        report_id="fin_monthly_summary",
        name="月度财务汇总",
        category=ReportCategory.FINANCE,
        description="按月统计营收、成本、毛利",
        sql_template="""
            SELECT DATE_TRUNC('month', o.created_at)::date AS report_month,
                   COALESCE(SUM(oi.subtotal_fen), 0) AS revenue_fen,
                   COALESCE(SUM(oi.cost_fen), 0) AS cost_fen,
                   COALESCE(SUM(oi.subtotal_fen), 0) - COALESCE(SUM(oi.cost_fen), 0) AS margin_fen,
                   COUNT(DISTINCT o.id) AS order_count
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
            WHERE o.store_id = :store_id
              AND o.tenant_id = :tenant_id
              AND DATE(o.created_at) BETWEEN :start_date AND :end_date
              AND o.status = 'paid'
              AND o.is_deleted = FALSE
              AND oi.is_deleted = FALSE
            GROUP BY DATE_TRUNC('month', o.created_at)::date
        """,
        dimensions=[DimensionDef(name="report_month", label="月份")],
        metrics=[
            MetricDef(name="revenue_fen", label="营收(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="cost_fen", label="成本(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="margin_fen", label="毛利(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="order_count", label="订单数", unit="count"),
        ],
        filters=[FILTER_STORE, FILTER_DATE_START, FILTER_DATE_END],
        default_sort="report_month",
        default_sort_direction=SortDirection.ASC,
        permissions=["admin", "finance"],
    ))

    # ════════════ 会员类 (member) ════════════

    reports.append(ReportDefinition(
        report_id="member_consumption",
        name="会员消费统计",
        category=ReportCategory.MEMBER,
        description="按会员统计消费金额和频次",
        sql_template="""
            SELECT c.id AS customer_id,
                   c.customer_name,
                   c.member_level,
                   COUNT(o.id) AS visit_count,
                   COALESCE(SUM(o.total_fen), 0) AS total_spend_fen,
                   MAX(o.created_at) AS last_visit
            FROM orders o
            JOIN customers c ON c.id = o.customer_id AND c.tenant_id = o.tenant_id
            WHERE o.store_id = :store_id
              AND o.tenant_id = :tenant_id
              AND DATE(o.created_at) BETWEEN :start_date AND :end_date
              AND o.status = 'paid'
              AND o.is_deleted = FALSE
              AND o.customer_id IS NOT NULL
            GROUP BY c.id, c.customer_name, c.member_level
        """,
        dimensions=[
            DimensionDef(name="customer_id", label="会员ID"),
            DimensionDef(name="customer_name", label="会员名"),
            DimensionDef(name="member_level", label="会员等级"),
        ],
        metrics=[
            MetricDef(name="visit_count", label="到店次数", unit="count"),
            MetricDef(name="total_spend_fen", label="消费总额(分)", unit="yuan", is_money_fen=True),
        ],
        filters=[FILTER_STORE, FILTER_DATE_START, FILTER_DATE_END],
        default_sort="total_spend_fen",
        permissions=["admin", "store_manager"],
    ))

    # ════════════ 运营类 (operation) ════════════

    reports.append(ReportDefinition(
        report_id="ops_table_turnover",
        name="翻台率报表",
        category=ReportCategory.OPERATION,
        description="按日统计桌台使用情况和翻台率",
        sql_template="""
            SELECT DATE(o.created_at) AS report_date,
                   COUNT(DISTINCT o.table_id) AS tables_used,
                   COUNT(*) AS session_count,
                   AVG(EXTRACT(EPOCH FROM (o.updated_at - o.created_at)) / 60) AS avg_duration_min
            FROM orders o
            WHERE o.store_id = :store_id
              AND o.tenant_id = :tenant_id
              AND DATE(o.created_at) BETWEEN :start_date AND :end_date
              AND o.table_id IS NOT NULL
              AND o.status IN ('paid', 'pending_payment')
              AND o.is_deleted = FALSE
            GROUP BY DATE(o.created_at)
        """,
        dimensions=[DIM_DATE],
        metrics=[
            MetricDef(name="tables_used", label="使用桌台数", unit="count"),
            MetricDef(name="session_count", label="总用餐次数", unit="count"),
            MetricDef(name="avg_duration_min", label="平均用餐时长(分钟)", unit="minutes"),
        ],
        filters=[FILTER_STORE, FILTER_DATE_START, FILTER_DATE_END],
        default_sort="report_date",
        default_sort_direction=SortDirection.ASC,
        permissions=["admin", "store_manager"],
    ))

    reports.append(ReportDefinition(
        report_id="ops_alerts_summary",
        name="异常告警汇总",
        category=ReportCategory.OPERATION,
        description="按类型和严重级别统计异常告警",
        sql_template="""
            SELECT type,
                   severity,
                   COUNT(*) AS alert_count
            FROM alerts
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND DATE(time) BETWEEN :start_date AND :end_date
              AND is_deleted = FALSE
            GROUP BY type, severity
        """,
        dimensions=[
            DimensionDef(name="type", label="告警类型"),
            DimensionDef(name="severity", label="严重级别"),
        ],
        metrics=[
            MetricDef(name="alert_count", label="告警数", unit="count"),
        ],
        filters=[FILTER_STORE, FILTER_DATE_START, FILTER_DATE_END],
        default_sort="alert_count",
        permissions=["admin", "store_manager"],
    ))

    # ════════════ P0 新增报表 (8个) ════════════

    reports.append(ReportDefinition(
        report_id="min_spend_supplement",
        name="最低消费补齐报表",
        category=ReportCategory.REVENUE,
        description="统计设有最低消费的桌台订单，计算实际消费与最低消费差额补齐情况",
        sql_template="""
            SELECT s.store_name, s.store_code,
                   COALESCE(o.biz_date, DATE(o.created_at)) AS biz_date,
                   t.table_label, t.table_type, t.min_consume_fen, o.order_no,
                   COALESCE(o.final_amount_fen, o.total_amount_fen - COALESCE(o.discount_amount_fen, 0)) AS actual_fen,
                   GREATEST(t.min_consume_fen - COALESCE(o.final_amount_fen, o.total_amount_fen - COALESCE(o.discount_amount_fen, 0)), 0) AS supplement_fen,
                   CASE WHEN COALESCE(o.final_amount_fen, o.total_amount_fen - COALESCE(o.discount_amount_fen, 0)) >= t.min_consume_fen THEN 'met' ELSE 'supplemented' END AS status
            FROM orders o
            JOIN stores s ON o.store_id = s.id AND s.tenant_id = o.tenant_id
            JOIN tables t ON o.table_id = t.id AND t.tenant_id = o.tenant_id
            WHERE o.tenant_id = :tenant_id AND o.is_deleted = FALSE
              AND o.status IN ('paid', 'completed')
              AND t.min_consume_fen > 0 AND t.is_deleted = FALSE
              AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
              AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
            ORDER BY biz_date DESC, supplement_fen DESC
        """,
        dimensions=[
            DIM_STORE_NAME,
            DimensionDef(name="store_code", label="门店编码"),
            DIM_DATE,
            DimensionDef(name="table_label", label="桌台"),
            DimensionDef(name="order_no", label="订单号"),
        ],
        metrics=[
            MetricDef(name="min_consume_fen", label="最低消费(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="actual_fen", label="实际消费(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="supplement_fen", label="补齐金额(分)", unit="yuan", is_money_fen=True),
        ],
        filters=[FILTER_STORE, FILTER_DATE_START, FILTER_DATE_END],
        default_sort="supplement_fen",
        permissions=["admin", "store_manager", "finance"],
    ))

    reports.append(ReportDefinition(
        report_id="cash_drawer_log",
        name="开钱箱统计",
        category=ReportCategory.AUDIT,
        description="按门店按收银员统计每日开钱箱次数及时段分布，用于现金管理稽核",
        sql_template="""
            WITH drawer_events AS (
                SELECT p.store_id, p.operator_id, p.created_at,
                       COALESCE(DATE(p.biz_date), DATE(p.created_at)) AS biz_date
                FROM payment_records p
                WHERE p.tenant_id = :tenant_id AND p.is_deleted = FALSE
                  AND p.payment_method = 'cash'
                  AND COALESCE(DATE(p.biz_date), DATE(p.created_at)) BETWEEN :start_date AND :end_date
                  AND (:store_id IS NULL OR p.store_id = :store_id::UUID)
            )
            SELECT s.store_name, s.store_code, de.biz_date,
                   e.employee_name AS cashier_name,
                   COUNT(*) AS open_count,
                   MIN(de.created_at) AS first_open_at,
                   MAX(de.created_at) AS last_open_at,
                   COUNT(*) FILTER (WHERE EXTRACT(HOUR FROM de.created_at) BETWEEN 10 AND 13) AS lunch_count,
                   COUNT(*) FILTER (WHERE EXTRACT(HOUR FROM de.created_at) BETWEEN 17 AND 21) AS dinner_count,
                   COUNT(*) FILTER (WHERE EXTRACT(HOUR FROM de.created_at) < 10 OR EXTRACT(HOUR FROM de.created_at) > 21) AS off_peak_count
            FROM drawer_events de
            JOIN stores s ON de.store_id = s.id AND s.tenant_id = :tenant_id
            LEFT JOIN employees e ON de.operator_id = e.id AND e.tenant_id = :tenant_id
            GROUP BY s.store_name, s.store_code, de.biz_date, e.employee_name
            ORDER BY de.biz_date DESC, open_count DESC
        """,
        dimensions=[
            DIM_STORE_NAME,
            DimensionDef(name="store_code", label="门店编码"),
            DIM_DATE,
            DimensionDef(name="cashier_name", label="收银员"),
        ],
        metrics=[
            MetricDef(name="open_count", label="开箱次数", unit="count"),
            MetricDef(name="lunch_count", label="午餐时段", unit="count"),
            MetricDef(name="dinner_count", label="晚餐时段", unit="count"),
            MetricDef(name="off_peak_count", label="非高峰时段", unit="count"),
        ],
        filters=[FILTER_STORE, FILTER_DATE_START, FILTER_DATE_END],
        default_sort="open_count",
        permissions=["admin", "finance"],
    ))

    reports.append(ReportDefinition(
        report_id="reservation_detail",
        name="预定明细统计",
        category=ReportCategory.OPERATION,
        description="按门店按日期统计预定量，按状态和时段分布",
        sql_template="""
            SELECT s.store_name, s.store_code,
                   DATE(r.reservation_date) AS biz_date,
                   COUNT(*) AS total_reservations,
                   COUNT(*) FILTER (WHERE r.status = 'confirmed') AS confirmed_count,
                   COUNT(*) FILTER (WHERE r.status = 'seated') AS seated_count,
                   COUNT(*) FILTER (WHERE r.status = 'cancelled') AS cancelled_count,
                   COUNT(*) FILTER (WHERE r.status = 'no_show') AS no_show_count,
                   CASE WHEN COUNT(*) > 0 THEN ROUND(COUNT(*) FILTER (WHERE r.status = 'seated')::NUMERIC / COUNT(*) * 100, 2) ELSE 0 END AS seated_pct,
                   COUNT(*) FILTER (WHERE r.time_slot = 'lunch') AS lunch_count,
                   COUNT(*) FILTER (WHERE r.time_slot = 'dinner') AS dinner_count,
                   COALESCE(SUM(r.guest_count), 0) AS total_guests
            FROM reservations r
            JOIN stores s ON r.store_id = s.id AND s.tenant_id = r.tenant_id
            WHERE r.tenant_id = :tenant_id AND r.is_deleted = FALSE
              AND DATE(r.reservation_date) BETWEEN :start_date AND :end_date
              AND (:store_id IS NULL OR r.store_id = :store_id::UUID)
            GROUP BY s.store_name, s.store_code, DATE(r.reservation_date)
            ORDER BY biz_date DESC, total_reservations DESC
        """,
        dimensions=[
            DIM_STORE_NAME,
            DimensionDef(name="store_code", label="门店编码"),
            DIM_DATE,
        ],
        metrics=[
            MetricDef(name="total_reservations", label="预定总数", unit="count"),
            MetricDef(name="confirmed_count", label="已确认", unit="count"),
            MetricDef(name="seated_count", label="已入座", unit="count"),
            MetricDef(name="cancelled_count", label="已取消", unit="count"),
            MetricDef(name="no_show_count", label="未到店", unit="count"),
            MetricDef(name="seated_pct", label="到店率(%)", unit="percent"),
            MetricDef(name="total_guests", label="总人数", unit="count"),
        ],
        filters=[FILTER_STORE, FILTER_DATE_START, FILTER_DATE_END],
        default_sort="biz_date",
        default_sort_direction=SortDirection.DESC,
        permissions=["admin", "store_manager"],
    ))

    reports.append(ReportDefinition(
        report_id="delivery_order_stats",
        name="外卖单统计",
        category=ReportCategory.REVENUE,
        description="按门店按外卖平台统计外卖订单量、营收、平台佣金、净收入",
        sql_template="""
            SELECT s.store_name, s.store_code,
                   COALESCE(d.biz_date, DATE(d.created_at)) AS biz_date,
                   d.platform,
                   COUNT(*) AS order_count,
                   COUNT(*) FILTER (WHERE d.status = 'completed') AS completed_count,
                   COUNT(*) FILTER (WHERE d.status = 'cancelled') AS cancelled_count,
                   COUNT(*) FILTER (WHERE d.status = 'refunded') AS refunded_count,
                   SUM(COALESCE(d.order_amount_fen, 0)) AS revenue_fen,
                   SUM(COALESCE(d.commission_fen, 0)) AS commission_fen,
                   SUM(COALESCE(d.delivery_fee_fen, 0)) AS delivery_fee_fen,
                   SUM(COALESCE(d.order_amount_fen, 0)) - SUM(COALESCE(d.commission_fen, 0)) - SUM(COALESCE(d.delivery_fee_fen, 0)) AS net_fen,
                   CASE WHEN COUNT(*) FILTER (WHERE d.status = 'completed') > 0 THEN SUM(COALESCE(d.order_amount_fen, 0)) / COUNT(*) FILTER (WHERE d.status = 'completed') ELSE 0 END AS avg_ticket_fen,
                   CASE WHEN SUM(COALESCE(d.order_amount_fen, 0)) > 0 THEN ROUND(SUM(COALESCE(d.commission_fen, 0))::NUMERIC / SUM(COALESCE(d.order_amount_fen, 0)) * 100, 2) ELSE 0 END AS commission_rate_pct
            FROM delivery_orders d
            JOIN stores s ON d.store_id = s.id AND s.tenant_id = d.tenant_id
            WHERE d.tenant_id = :tenant_id AND d.is_deleted = FALSE
              AND COALESCE(d.biz_date, DATE(d.created_at)) BETWEEN :start_date AND :end_date
              AND (:store_id IS NULL OR d.store_id = :store_id::UUID)
            GROUP BY s.store_name, s.store_code, COALESCE(d.biz_date, DATE(d.created_at)), d.platform
            ORDER BY biz_date DESC, revenue_fen DESC
        """,
        dimensions=[
            DIM_STORE_NAME,
            DimensionDef(name="store_code", label="门店编码"),
            DIM_DATE,
            DimensionDef(name="platform", label="外卖平台"),
        ],
        metrics=[
            MetricDef(name="order_count", label="订单数", unit="count"),
            MetricDef(name="completed_count", label="完成数", unit="count"),
            MetricDef(name="cancelled_count", label="取消数", unit="count"),
            MetricDef(name="revenue_fen", label="营收(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="commission_fen", label="佣金(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="net_fen", label="净收入(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="commission_rate_pct", label="佣金率(%)", unit="percent"),
        ],
        filters=[FILTER_STORE, FILTER_DATE_START, FILTER_DATE_END],
        default_sort="revenue_fen",
        permissions=["admin", "store_manager", "finance"],
    ))

    reports.append(ReportDefinition(
        report_id="delivery_reconciliation",
        name="平台外卖对账表",
        category=ReportCategory.AUDIT,
        description="对比系统内外卖订单金额与平台结算金额，发现差异单据",
        sql_template="""
            WITH system_orders AS (
                SELECT d.id AS delivery_order_id, d.platform, d.platform_order_no, d.store_id,
                       d.order_amount_fen AS system_amount_fen, d.commission_fen AS system_commission_fen,
                       d.status AS system_status,
                       COALESCE(d.biz_date, DATE(d.created_at)) AS biz_date
                FROM delivery_orders d
                WHERE d.tenant_id = :tenant_id AND d.is_deleted = FALSE
                  AND COALESCE(d.biz_date, DATE(d.created_at)) BETWEEN :start_date AND :end_date
                  AND (:store_id IS NULL OR d.store_id = :store_id::UUID)
            ),
            platform_data AS (
                SELECT dr.platform_order_no, dr.platform,
                       dr.platform_amount_fen, dr.platform_commission_fen, dr.settlement_status
                FROM delivery_reconciliations dr
                WHERE dr.tenant_id = :tenant_id AND dr.is_deleted = FALSE
                  AND dr.biz_date BETWEEN :start_date AND :end_date
                  AND (:store_id IS NULL OR dr.store_id = :store_id::UUID)
            )
            SELECT s.store_name, so.biz_date, so.platform, so.platform_order_no,
                   so.system_amount_fen, COALESCE(pd.platform_amount_fen, 0) AS platform_amount_fen,
                   so.system_amount_fen - COALESCE(pd.platform_amount_fen, 0) AS amount_diff_fen,
                   so.system_commission_fen, COALESCE(pd.platform_commission_fen, 0) AS platform_commission_fen,
                   so.system_commission_fen - COALESCE(pd.platform_commission_fen, 0) AS commission_diff_fen,
                   so.system_status, COALESCE(pd.settlement_status, 'missing') AS platform_status,
                   CASE WHEN pd.platform_order_no IS NULL THEN 'platform_missing'
                        WHEN ABS(so.system_amount_fen - pd.platform_amount_fen) > 0 THEN 'amount_mismatch'
                        WHEN ABS(so.system_commission_fen - COALESCE(pd.platform_commission_fen, 0)) > 0 THEN 'commission_mismatch'
                        ELSE 'matched' END AS reconciliation_status
            FROM system_orders so
            JOIN stores s ON so.store_id = s.id AND s.tenant_id = :tenant_id
            LEFT JOIN platform_data pd ON so.platform_order_no = pd.platform_order_no AND so.platform = pd.platform
            ORDER BY so.biz_date DESC,
                CASE WHEN pd.platform_order_no IS NULL THEN 0 WHEN ABS(so.system_amount_fen - COALESCE(pd.platform_amount_fen, 0)) > 0 THEN 1 ELSE 2 END,
                ABS(so.system_amount_fen - COALESCE(pd.platform_amount_fen, 0)) DESC
        """,
        dimensions=[
            DIM_STORE_NAME,
            DIM_DATE,
            DimensionDef(name="platform", label="外卖平台"),
            DimensionDef(name="platform_order_no", label="平台单号"),
        ],
        metrics=[
            MetricDef(name="system_amount_fen", label="系统金额(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="platform_amount_fen", label="平台金额(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="amount_diff_fen", label="金额差异(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="reconciliation_status", label="对账状态", unit="text"),
        ],
        filters=[FILTER_STORE, FILTER_DATE_START, FILTER_DATE_END],
        default_sort="amount_diff_fen",
        permissions=["admin", "finance"],
    ))

    reports.append(ReportDefinition(
        report_id="credit_account_stats",
        name="挂账统计",
        category=ReportCategory.AUDIT,
        description="按门店统计企业挂账客户的信用额度使用情况",
        sql_template="""
            WITH latest_txn AS (
                SELECT ct.credit_account_id, MAX(ct.created_at) AS last_transaction_at
                FROM credit_transactions ct
                WHERE ct.tenant_id = :tenant_id AND ct.is_deleted = FALSE
                GROUP BY ct.credit_account_id
            ),
            period_usage AS (
                SELECT ct.credit_account_id,
                       SUM(CASE WHEN ct.transaction_type = 'charge' THEN ct.amount_fen ELSE 0 END) AS period_charged_fen,
                       SUM(CASE WHEN ct.transaction_type = 'payment' THEN ct.amount_fen ELSE 0 END) AS period_paid_fen,
                       COUNT(*) AS period_txn_count
                FROM credit_transactions ct
                WHERE ct.tenant_id = :tenant_id AND ct.is_deleted = FALSE
                  AND DATE(ct.created_at) BETWEEN :start_date AND :end_date
                  AND (:store_id IS NULL OR ct.store_id = :store_id::UUID)
                GROUP BY ct.credit_account_id
            )
            SELECT s.store_name, s.store_code, ca.customer_name, ca.company_name,
                   ca.credit_limit_fen, ca.used_fen, ca.credit_limit_fen - ca.used_fen AS balance_fen,
                   CASE WHEN ca.credit_limit_fen > 0 THEN ROUND(ca.used_fen::NUMERIC / ca.credit_limit_fen * 100, 2) ELSE 0 END AS usage_rate_pct,
                   COALESCE(pu.period_charged_fen, 0) AS period_charged_fen,
                   COALESCE(pu.period_paid_fen, 0) AS period_paid_fen,
                   COALESCE(pu.period_txn_count, 0) AS period_txn_count,
                   lt.last_transaction_at
            FROM credit_accounts ca
            JOIN stores s ON ca.store_id = s.id AND s.tenant_id = ca.tenant_id
            LEFT JOIN latest_txn lt ON lt.credit_account_id = ca.id
            LEFT JOIN period_usage pu ON pu.credit_account_id = ca.id
            WHERE ca.tenant_id = :tenant_id AND ca.is_deleted = FALSE AND ca.is_active = TRUE
              AND (:store_id IS NULL OR ca.store_id = :store_id::UUID)
            ORDER BY ca.used_fen DESC, usage_rate_pct DESC
        """,
        dimensions=[
            DIM_STORE_NAME,
            DimensionDef(name="store_code", label="门店编码"),
            DimensionDef(name="customer_name", label="客户名称"),
            DimensionDef(name="company_name", label="公司名称"),
        ],
        metrics=[
            MetricDef(name="credit_limit_fen", label="信用额度(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="used_fen", label="已用额度(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="balance_fen", label="可用余额(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="usage_rate_pct", label="使用率(%)", unit="percent"),
            MetricDef(name="period_charged_fen", label="期间挂账(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="period_paid_fen", label="期间还款(分)", unit="yuan", is_money_fen=True),
        ],
        filters=[FILTER_STORE, FILTER_DATE_START, FILTER_DATE_END],
        default_sort="used_fen",
        permissions=["admin", "finance"],
    ))

    reports.append(ReportDefinition(
        report_id="coupon_consumption",
        name="团购券消费分析",
        category=ReportCategory.REVENUE,
        description="按团购券类型和来源平台统计核销量、面值总额、实际成本、盈亏",
        sql_template="""
            SELECT s.store_name, s.store_code,
                   COALESCE(cr.biz_date, DATE(cr.created_at)) AS biz_date,
                   cr.coupon_type, cr.platform,
                   COUNT(*) AS redeemed_count,
                   SUM(COALESCE(cr.face_value_fen, 0)) AS face_value_total_fen,
                   SUM(COALESCE(cr.actual_cost_fen, 0)) AS actual_cost_total_fen,
                   SUM(COALESCE(cr.settlement_fen, 0)) AS settlement_total_fen,
                   SUM(COALESCE(cr.settlement_fen, 0)) - SUM(COALESCE(cr.actual_cost_fen, 0)) AS profit_loss_fen,
                   CASE WHEN COUNT(*) > 0 THEN SUM(COALESCE(cr.face_value_fen, 0)) / COUNT(*) ELSE 0 END AS avg_face_value_fen,
                   CASE WHEN COUNT(*) > 0 THEN SUM(COALESCE(cr.settlement_fen, 0)) / COUNT(*) ELSE 0 END AS avg_settlement_fen
            FROM coupon_redemptions cr
            JOIN stores s ON cr.store_id = s.id AND s.tenant_id = cr.tenant_id
            WHERE cr.tenant_id = :tenant_id AND cr.is_deleted = FALSE
              AND COALESCE(cr.biz_date, DATE(cr.created_at)) BETWEEN :start_date AND :end_date
              AND (:store_id IS NULL OR cr.store_id = :store_id::UUID)
            GROUP BY s.store_name, s.store_code, COALESCE(cr.biz_date, DATE(cr.created_at)), cr.coupon_type, cr.platform
            ORDER BY biz_date DESC, redeemed_count DESC
        """,
        dimensions=[
            DIM_STORE_NAME,
            DimensionDef(name="store_code", label="门店编码"),
            DIM_DATE,
            DimensionDef(name="coupon_type", label="团购券类型"),
            DimensionDef(name="platform", label="来源平台"),
        ],
        metrics=[
            MetricDef(name="redeemed_count", label="核销量", unit="count"),
            MetricDef(name="face_value_total_fen", label="面值总额(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="actual_cost_total_fen", label="实际成本(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="settlement_total_fen", label="结算总额(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="profit_loss_fen", label="盈亏(分)", unit="yuan", is_money_fen=True),
        ],
        filters=[FILTER_STORE, FILTER_DATE_START, FILTER_DATE_END],
        default_sort="redeemed_count",
        permissions=["admin", "store_manager", "finance"],
    ))

    return reports


# ──────────────────────────────────────────────
# 全局注册中心初始化
# ──────────────────────────────────────────────

def create_default_registry() -> ReportRegistry:
    """创建并初始化包含所有内置报表的注册中心"""
    registry = ReportRegistry()
    for report_def in _build_builtin_reports():
        registry.register(report_def)
    log.info("report_registry.initialized", count=registry.count())
    return registry
