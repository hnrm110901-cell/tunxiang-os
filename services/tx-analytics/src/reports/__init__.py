"""屯象OS 报表定义注册表

P0 每日必看报表(8个) + P2 月度报表。
报表引擎(report_engine.py)通过 REPORT_REGISTRY 字典获取报表定义。
每个报表包含 REPORT_ID / REPORT_NAME / CATEGORY / SQL_TEMPLATE / DIMENSIONS / METRICS / FILTERS。
金额单位: 分(fen), int。引擎层自动转元。
"""

from services.tx_analytics.src.reports import (
    # 其他已有报表
    area_guest_table,
    audit_bill_list,
    # P2 月度稽核报表
    audit_log,
    audit_summary,
    bill_audit,
    # P0 新增报表 (8个)
    cash_drawer_log,
    # P1 每周分析报表
    combo_sales,
    commission_cashier,
    commission_chef,
    commission_cutter,
    commission_orderer,
    commission_runner,
    # P2 月度提成报表
    commission_summary,
    commission_waiter,
    cooking_speed,
    coupon_consumption,
    credit_account_stats,
    daily_cashflow,
    # P0 每日必看报表
    daily_revenue,
    daily_revenue_by_day,
    daily_store_collection,
    delivery_order_stats,
    delivery_reconciliation,
    deposit_stats,
    dept_sales_ratio,
    discount_detail,
    discount_stats,
    dish_classification_index,
    dish_hourly,
    dish_sales_stats,
    dish_timeout,
    finance_cashier_daily,
    finance_cashier_variance,
    finance_payment_summary,
    gift_dish_analysis,
    margin_by_channel,
    margin_by_store,
    # P2 月度毛利报表
    margin_by_type,
    margin_each_order,
    margin_operation,
    margin_per_order,
    margin_total_order,
    member_consumption,
    min_spend_supplement,
    payment_discount,
    realtime_stats,
    reservation_detail,
    return_analysis,
    revenue_structure,
    sales_channel,
    sales_transfer,
    scm_ar_ledger,
    scm_bom_cost_analysis,
    scm_cost_margin,
    scm_inventory_balance,
    scm_inventory_ledger,
    scm_inventory_status,
    scm_inventory_warning,
    scm_purchase_ranking,
    # 供应链报表 (15个)
    scm_purchase_stats,
    scm_receipt_balance,
    scm_receiving_detail,
    scm_supplier_summary,
    scm_transfer_stats,
    scm_waste_report,
    scm_yield_comparison,
    store_anomaly,
    table_stats,
)

# P0 每日必看报表模块列表
_P0_REPORTS = [
    daily_revenue,
    daily_revenue_by_day,
    payment_discount,
    daily_store_collection,
    daily_cashflow,
    dish_sales_stats,
    bill_audit,
    realtime_stats,
    # 新增 8 个 P0 报表
    min_spend_supplement,
    cash_drawer_log,
    reservation_detail,
    delivery_order_stats,
    delivery_reconciliation,
    credit_account_stats,
    member_consumption,
    coupon_consumption,
]

# 其他报表模块列表
_OTHER_REPORTS = [
    area_guest_table,
    dish_hourly,
    finance_cashier_daily,
    finance_cashier_variance,
    finance_payment_summary,
    margin_each_order,
    margin_per_order,
    margin_total_order,
    revenue_structure,
    sales_channel,
    table_stats,
]

# P1 每周分析报表模块列表
_P1_REPORTS = [
    revenue_structure,
    sales_channel,
    area_guest_table,
    table_stats,
    dish_hourly,
    combo_sales,
    return_analysis,
    gift_dish_analysis,
    dept_sales_ratio,
    dish_timeout,
    store_anomaly,
    discount_stats,
]

# P2 月度报表模块列表（毛利 + 提成 + 稽核）
_P2_REPORTS = [
    # 毛利报表 (7个)
    margin_per_order,
    margin_total_order,
    margin_each_order,
    margin_by_type,
    margin_operation,
    margin_by_channel,
    margin_by_store,
    # 提成报表 (8个)
    commission_summary,
    commission_waiter,
    commission_orderer,
    commission_cutter,
    commission_chef,
    commission_runner,
    commission_cashier,
    dish_classification_index,
    # 稽核报表 (7个)
    audit_log,
    audit_bill_list,
    audit_summary,
    cooking_speed,
    deposit_stats,
    sales_transfer,
    discount_detail,
]

# 供应链报表模块列表 (15个)
_SCM_REPORTS = [
    scm_purchase_stats,
    scm_receiving_detail,
    scm_supplier_summary,
    scm_purchase_ranking,
    scm_transfer_stats,
    scm_waste_report,
    scm_inventory_balance,
    scm_inventory_status,
    scm_receipt_balance,
    scm_inventory_ledger,
    scm_inventory_warning,
    scm_cost_margin,
    scm_yield_comparison,
    scm_bom_cost_analysis,
    scm_ar_ledger,
]

# 全部报表
_ALL_REPORTS = _P0_REPORTS + _OTHER_REPORTS + [
    m for m in _P1_REPORTS if m not in _P0_REPORTS and m not in _OTHER_REPORTS
] + [
    m for m in _P2_REPORTS if m not in _P0_REPORTS and m not in _OTHER_REPORTS and m not in _P1_REPORTS
] + _SCM_REPORTS

# 报表注册表: REPORT_ID -> 模块
REPORT_REGISTRY: dict[str, object] = {
    mod.REPORT_ID: mod for mod in _ALL_REPORTS
}

# 按分类索引
REPORTS_BY_CATEGORY: dict[str, list[object]] = {}
for _mod in _ALL_REPORTS:
    REPORTS_BY_CATEGORY.setdefault(_mod.CATEGORY, []).append(_mod)


def get_report(report_id: str):
    """根据报表ID获取报表定义模块

    Args:
        report_id: 报表ID，如 'daily_revenue'

    Returns:
        报表定义模块，包含 SQL_TEMPLATE / DIMENSIONS / METRICS / FILTERS

    Raises:
        KeyError: 报表ID不存在
    """
    if report_id not in REPORT_REGISTRY:
        raise KeyError(f"Report not found: {report_id}")
    return REPORT_REGISTRY[report_id]


def list_reports(category: str | None = None) -> list[dict]:
    """列出所有已注册报表的摘要信息

    Args:
        category: 可选，按分类筛选 (revenue/cashflow/product/audit/realtime)
    """
    source = REPORTS_BY_CATEGORY.get(category, []) if category else _ALL_REPORTS
    return [
        {
            "report_id": mod.REPORT_ID,
            "report_name": mod.REPORT_NAME,
            "category": mod.CATEGORY,
            "dimensions": mod.DIMENSIONS,
            "metrics": mod.METRICS,
            "filters": mod.FILTERS,
        }
        for mod in source
    ]


def list_p0_reports() -> list[dict]:
    """列出P0每日必看报表"""
    return [
        {
            "report_id": mod.REPORT_ID,
            "report_name": mod.REPORT_NAME,
            "category": mod.CATEGORY,
        }
        for mod in _P0_REPORTS
    ]


def list_p1_reports() -> list[dict]:
    """列出P1每周分析报表"""
    return [
        {
            "report_id": mod.REPORT_ID,
            "report_name": mod.REPORT_NAME,
            "category": mod.CATEGORY,
        }
        for mod in _P1_REPORTS
    ]


def list_p2_reports() -> list[dict]:
    """列出P2月度报表（毛利/提成/稽核）"""
    return [
        {
            "report_id": mod.REPORT_ID,
            "report_name": mod.REPORT_NAME,
            "category": mod.CATEGORY,
        }
        for mod in _P2_REPORTS
    ]


def list_scm_reports() -> list[dict]:
    """列出供应链报表(15个)"""
    return [
        {
            "report_id": mod.REPORT_ID,
            "report_name": mod.REPORT_NAME,
            "category": mod.CATEGORY,
        }
        for mod in _SCM_REPORTS
    ]
