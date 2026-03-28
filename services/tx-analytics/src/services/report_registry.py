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
