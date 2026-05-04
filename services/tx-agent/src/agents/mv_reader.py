"""Phase C2-Agent — 物化视图共享读取 helper

每个函数接受 (db_session, tenant_id, optional store_id, optional date_range)
返回 TypedDict / List[dict] 结果，附带 docstring 说明所用 MV 和用途。

Gate: 环境变量 TX_AGENT_USE_MV_READS=true 时走 MV 路径，否则走直接查询降级。

物化视图清单（13 个）：
  v148 原始 8 个：
    mv_discount_health     — 折扣率/授权链/泄漏类型（因果链①）
    mv_channel_margin      — 各渠道真实到手毛利（因果链②）
    mv_inventory_bom       — BOM理论vs实际耗用差异（因果链③）
    mv_member_clv          — 会员生命周期价值（因果链⑤）
    mv_store_pnl           — 门店实时P&L（因果链④）
    mv_daily_settlement    — 日结状态/差异项（因果链⑦）
    mv_safety_compliance   — 食安检查完成率（新模块⑧）
    mv_energy_efficiency   — 能耗/营收比（新模块⑨）

  v385 新增 4 个：
    mv_table_turnover      — 翻台率/桌均营收（因果链④扩展）
    mv_dish_profitability  — 菜品维度的真实盈利
    mv_employee_efficiency — 人效指标/出勤评分
    mv_customer_ltv        — 客户LTV/流失风险（因果链⑤扩展）

  单独迁移：
    mv_public_opinion      — 舆情/点评聚合
    mv_agent_roi_monthly   — Agent ROI 月度汇总
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

logger = structlog.get_logger(__name__)

_USE_MV_READS = os.getenv("TX_AGENT_USE_MV_READS", "").lower() == "true"

# ─────────────────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────────────────


def _ensure_date(d: Optional[str | date | datetime]) -> date:
    """将字符串/date/datetime 统一转为 date。"""
    if d is None:
        return date.today()
    if isinstance(d, date):
        return d
    if isinstance(d, datetime):
        return d.date()
    return date.fromisoformat(str(d))


def _str_or(v: Any) -> str:
    """将 DB 返回值安全转为 str。"""
    if v is None:
        return ""
    return str(v)


def _int_or(v: Any, default: int = 0) -> int:
    if v is None:
        return default
    return int(v)


def _float_or(v: Any, default: float = 0.0) -> float:
    if v is None:
        return default
    return float(v)


def _iso(d: Any) -> str:
    """将 date/datetime 转为 ISO 字符串。"""
    if d is None:
        return ""
    if isinstance(d, (date, datetime)):
        return d.isoformat()
    return str(d)


# ─────────────────────────────────────────────────────────────────────────────
# 1. mv_discount_health
# ─────────────────────────────────────────────────────────────────────────────


async def get_discount_health(
    db: Any,
    tenant_id: str,
    store_id: Optional[str] = None,
    stat_date: Optional[str | date] = None,
    days: int = 7,
) -> list[dict[str, Any]]:
    """从 mv_discount_health 读取折扣健康数据。

    视图主键: (tenant_id, store_id, stat_date)

    Args:
        db: SQLAlchemy AsyncSession
        tenant_id: 租户 ID
        store_id: 可选门店过滤
        stat_date: 可选单日查询，默认最近 days 天
        days: 当未指定 stat_date 时，查询最近多少天

    Returns:
        list[dict] with keys: store_id, stat_date, total_orders, discounted_orders,
        discount_rate, total_discount_fen, unauthorized_count, leak_types,
        top_operators, threshold_breaches, updated_at
    """
    dt = _ensure_date(stat_date) if stat_date else None
    store_clause = "AND store_id = :sid" if store_id else ""
    params: dict[str, Any] = {"tenant_id": tenant_id}

    if dt:
        date_clause = "AND stat_date = :dt"
        params["dt"] = dt
    else:
        date_clause = f"AND stat_date >= CURRENT_DATE - :days"
        params["days"] = days

    if store_id:
        params["sid"] = store_id

    q = text(f"""
        SELECT store_id, stat_date, total_orders, discounted_orders,
               discount_rate, total_discount_fen, unauthorized_count,
               leak_types, top_operators, threshold_breaches, updated_at
        FROM mv_discount_health
        WHERE tenant_id = :tenant_id
          {date_clause}
          {store_clause}
        ORDER BY stat_date DESC
    """)
    try:
        result = await db.execute(q, params)
        rows = []
        for r in result.mappings():
            item = dict(r)
            item["store_id"] = _str_or(item.get("store_id"))
            item["stat_date"] = _iso(item.get("stat_date"))
            item["updated_at"] = _iso(item.get("updated_at"))
            rows.append(item)
        return rows
    except (OperationalError, ProgrammingError) as exc:
        logger.warning("mv_reader_discount_health_failed", error=str(exc))
        return []


# ─────────────────────────────────────────────────────────────────────────────
# 2. mv_channel_margin
# ─────────────────────────────────────────────────────────────────────────────


async def get_channel_margin(
    db: Any,
    tenant_id: str,
    store_id: Optional[str] = None,
    channel: Optional[str] = None,
    stat_date: Optional[str | date] = None,
    days: int = 30,
) -> list[dict[str, Any]]:
    """从 mv_channel_margin 读取各渠道真实毛利。

    视图主键: (tenant_id, store_id, stat_date, channel)

    Args:
        db: SQLAlchemy AsyncSession
        tenant_id: 租户 ID
        store_id: 可选门店过滤
        channel: 可选渠道过滤 (dine_in/meituan/eleme/douyin)
        stat_date: 可选单日查询
        days: 当未指定 stat_date 时，查询最近多少天

    Returns:
        list[dict] with keys: store_id, stat_date, channel, gross_revenue_fen,
        commission_fen, promotion_subsidy_fen, net_revenue_fen, cogs_fen,
        gross_margin_fen, gross_margin_rate, order_count
    """
    dt = _ensure_date(stat_date) if stat_date else None
    clauses = []
    params: dict[str, Any] = {"tenant_id": tenant_id}

    if dt:
        clauses.append("AND stat_date = :dt")
        params["dt"] = dt
    else:
        clauses.append(f"AND stat_date >= CURRENT_DATE - :days")
        params["days"] = days
    if store_id:
        clauses.append("AND store_id = :sid")
        params["sid"] = store_id
    if channel:
        clauses.append("AND channel = :ch")
        params["ch"] = channel

    q = text(f"""
        SELECT store_id, stat_date, channel,
               gross_revenue_fen, commission_fen, promotion_subsidy_fen,
               net_revenue_fen, cogs_fen, gross_margin_fen, gross_margin_rate,
               order_count
        FROM mv_channel_margin
        WHERE tenant_id = :tenant_id
          {' '.join(clauses)}
        ORDER BY stat_date DESC, channel
    """)
    try:
        result = await db.execute(q, params)
        rows = []
        for r in result.mappings():
            item = dict(r)
            item["store_id"] = _str_or(item.get("store_id"))
            item["stat_date"] = _iso(item.get("stat_date"))
            rows.append(item)
        return rows
    except (OperationalError, ProgrammingError) as exc:
        logger.warning("mv_reader_channel_margin_failed", error=str(exc))
        return []


# ─────────────────────────────────────────────────────────────────────────────
# 3. mv_inventory_bom
# ─────────────────────────────────────────────────────────────────────────────


async def get_inventory_bom(
    db: Any,
    tenant_id: str,
    store_id: Optional[str] = None,
    stat_date: Optional[str | date] = None,
    days: int = 7,
    min_loss_rate: float = 0.0,
) -> list[dict[str, Any]]:
    """从 mv_inventory_bom 读取 BOM 损耗数据。

    视图主键: (tenant_id, store_id, stat_date, ingredient_id)

    Args:
        db: SQLAlchemy AsyncSession
        tenant_id: 租户 ID
        store_id: 可选门店过滤
        stat_date: 可选单日查询
        days: 最近多少天
        min_loss_rate: 最小损耗率过滤（如 0.05 只返回损耗>5%）

    Returns:
        list[dict] with keys: store_id, stat_date, ingredient_id, ingredient_name,
        theoretical_usage_g, actual_usage_g, waste_g, unexplained_loss_g,
        loss_rate
    """
    dt = _ensure_date(stat_date) if stat_date else None
    clauses = []
    params: dict[str, Any] = {"tenant_id": tenant_id}

    if dt:
        clauses.append("AND stat_date = :dt")
        params["dt"] = dt
    else:
        clauses.append(f"AND stat_date >= CURRENT_DATE - :days")
        params["days"] = days
    if store_id:
        clauses.append("AND store_id = :sid")
        params["sid"] = store_id
    if min_loss_rate > 0:
        clauses.append("AND loss_rate >= :min_lr")
        params["min_lr"] = min_loss_rate

    q = text(f"""
        SELECT store_id, stat_date, ingredient_id, ingredient_name,
               theoretical_usage_g, actual_usage_g, waste_g,
               unexplained_loss_g, loss_rate
        FROM mv_inventory_bom
        WHERE tenant_id = :tenant_id
          {' '.join(clauses)}
        ORDER BY unexplained_loss_g DESC
        LIMIT 200
    """)
    try:
        result = await db.execute(q, params)
        rows = []
        for r in result.mappings():
            item = dict(r)
            item["store_id"] = _str_or(item.get("store_id"))
            item["ingredient_id"] = _str_or(item.get("ingredient_id"))
            item["stat_date"] = _iso(item.get("stat_date"))
            rows.append(item)
        return rows
    except (OperationalError, ProgrammingError) as exc:
        logger.warning("mv_reader_inventory_bom_failed", error=str(exc))
        return []


# ─────────────────────────────────────────────────────────────────────────────
# 4. mv_member_clv
# ─────────────────────────────────────────────────────────────────────────────


async def get_member_clv(
    db: Any,
    tenant_id: str,
    min_clv_fen: int = 0,
    churn_threshold: float = 0.0,
    top_n: int = 50,
) -> list[dict[str, Any]]:
    """从 mv_member_clv 读取会员 CLV 快照。

    视图主键: (tenant_id, customer_id)
    注意: 该视图以租户为维度（不分门店），store_id 参数仅用于日志。

    Args:
        db: SQLAlchemy AsyncSession
        tenant_id: 租户 ID
        min_clv_fen: 最低 CLV 过滤（分）
        churn_threshold: 流失概率阈值（0-1）
        top_n: 返回 TOP N

    Returns:
        list[dict] with keys: customer_id, total_spend_fen, visit_count,
        voucher_used_count, voucher_cost_fen, stored_value_balance_fen,
        clv_fen, churn_probability, next_visit_days, last_visit_at,
        rfm_segment, updated_at
    """
    params: dict[str, Any] = {
        "tenant_id": tenant_id,
        "min_clv_fen": min_clv_fen,
        "churn_threshold": churn_threshold,
        "top_n": top_n,
    }

    q = text("""
        SELECT customer_id, total_spend_fen, visit_count,
               voucher_used_count, voucher_cost_fen, stored_value_balance_fen,
               clv_fen, churn_probability, next_visit_days, last_visit_at,
               rfm_segment, updated_at
        FROM mv_member_clv
        WHERE tenant_id = :tenant_id
          AND clv_fen >= :min_clv_fen
          AND churn_probability >= :churn_threshold
        ORDER BY clv_fen DESC
        LIMIT :top_n
    """)
    try:
        result = await db.execute(q, params)
        rows = []
        for r in result.mappings():
            item = dict(r)
            item["customer_id"] = _str_or(item.get("customer_id"))
            item["last_visit_at"] = _iso(item.get("last_visit_at"))
            item["updated_at"] = _iso(item.get("updated_at"))
            rows.append(item)
        return rows
    except (OperationalError, ProgrammingError) as exc:
        logger.warning("mv_reader_member_clv_failed", error=str(exc))
        return []


# ─────────────────────────────────────────────────────────────────────────────
# 5. mv_store_pnl
# ─────────────────────────────────────────────────────────────────────────────


async def get_store_pnl(
    db: Any,
    tenant_id: str,
    store_id: Optional[str] = None,
    stat_date: Optional[str | date] = None,
    months: int = 3,
) -> list[dict[str, Any]]:
    """从 mv_store_pnl 读取门店 P&L 数据。

    视图主键: (tenant_id, store_id, stat_date)

    Args:
        db: SQLAlchemy AsyncSession
        tenant_id: 租户 ID
        store_id: 可选门店过滤
        stat_date: 可选单月查询
        months: 最近几个月

    Returns:
        list[dict] with keys: store_id, brand_id, stat_date, gross_revenue_fen,
        net_revenue_fen, cogs_fen, gross_profit_fen, gross_margin_rate,
        labor_cost_fen, overhead_fen, net_profit_fen, order_count,
        customer_count, avg_check_fen, stored_value_new_fen,
        stored_value_consumed_fen
    """
    dt = _ensure_date(stat_date) if stat_date else None
    clauses = []
    params: dict[str, Any] = {"tenant_id": tenant_id}

    if dt:
        clauses.append("AND stat_date = :dt")
        params["dt"] = dt
    else:
        clauses.append(f"AND stat_date >= CURRENT_DATE - INTERVAL '{months} months'")
    if store_id:
        clauses.append("AND store_id = :sid")
        params["sid"] = store_id

    q = text(f"""
        SELECT store_id, brand_id, stat_date,
               gross_revenue_fen, net_revenue_fen, cogs_fen,
               gross_profit_fen, gross_margin_rate,
               labor_cost_fen, overhead_fen, net_profit_fen,
               order_count, customer_count, avg_check_fen,
               stored_value_new_fen, stored_value_consumed_fen,
               updated_at
        FROM mv_store_pnl
        WHERE tenant_id = :tenant_id
          {' '.join(clauses)}
        ORDER BY stat_date DESC
        LIMIT 100
    """)
    try:
        result = await db.execute(q, params)
        rows = []
        for r in result.mappings():
            item = dict(r)
            item["store_id"] = _str_or(item.get("store_id"))
            item["brand_id"] = _str_or(item.get("brand_id"))
            item["stat_date"] = _iso(item.get("stat_date"))
            item["updated_at"] = _iso(item.get("updated_at"))
            rows.append(item)
        return rows
    except (OperationalError, ProgrammingError) as exc:
        logger.warning("mv_reader_store_pnl_failed", error=str(exc))
        return []


# ─────────────────────────────────────────────────────────────────────────────
# 6. mv_daily_settlement
# ─────────────────────────────────────────────────────────────────────────────


async def get_daily_settlement(
    db: Any,
    tenant_id: str,
    store_id: Optional[str] = None,
    stat_date: Optional[str | date] = None,
    status: Optional[str] = None,
    days: int = 7,
) -> list[dict[str, Any]]:
    """从 mv_daily_settlement 读取日清日结状态。

    视图主键: (tenant_id, store_id, stat_date)

    Args:
        db: SQLAlchemy AsyncSession
        tenant_id: 租户 ID
        store_id: 可选门店过滤
        stat_date: 可选单日查询
        status: 可选状态过滤 (open/pending_reconcile/closed/discrepancy)
        days: 最近多少天

    Returns:
        list[dict] with keys: store_id, stat_date, status, cash_declared_fen,
        cash_system_fen, cash_discrepancy_fen, wechat_received_fen,
        alipay_received_fen, card_received_fen, stored_value_consumed_fen,
        total_revenue_fen, pending_items, closed_at, closed_by
    """
    dt = _ensure_date(stat_date) if stat_date else None
    clauses = []
    params: dict[str, Any] = {"tenant_id": tenant_id}

    if dt:
        clauses.append("AND stat_date = :dt")
        params["dt"] = dt
    else:
        clauses.append(f"AND stat_date >= CURRENT_DATE - :days")
        params["days"] = days
    if store_id:
        clauses.append("AND store_id = :sid")
        params["sid"] = store_id
    if status:
        clauses.append("AND status = :st")
        params["st"] = status

    q = text(f"""
        SELECT store_id, stat_date, status,
               cash_declared_fen, cash_system_fen, cash_discrepancy_fen,
               wechat_received_fen, alipay_received_fen, card_received_fen,
               stored_value_consumed_fen, total_revenue_fen,
               pending_items, closed_at, closed_by, updated_at
        FROM mv_daily_settlement
        WHERE tenant_id = :tenant_id
          {' '.join(clauses)}
        ORDER BY stat_date DESC
    """)
    try:
        result = await db.execute(q, params)
        rows = []
        for r in result.mappings():
            item = dict(r)
            item["store_id"] = _str_or(item.get("store_id"))
            item["stat_date"] = _iso(item.get("stat_date"))
            item["closed_at"] = _iso(item.get("closed_at"))
            item["closed_by"] = _str_or(item.get("closed_by"))
            item["updated_at"] = _iso(item.get("updated_at"))
            rows.append(item)
        return rows
    except (OperationalError, ProgrammingError) as exc:
        logger.warning("mv_reader_daily_settlement_failed", error=str(exc))
        return []


# ─────────────────────────────────────────────────────────────────────────────
# 7. mv_safety_compliance
# ─────────────────────────────────────────────────────────────────────────────


async def get_safety_compliance(
    db: Any,
    tenant_id: str,
    store_id: Optional[str] = None,
    weeks: int = 4,
) -> list[dict[str, Any]]:
    """从 mv_safety_compliance 读取食安合规数据。

    视图主键: (tenant_id, store_id, stat_week)，stat_week 为 ISO 周一的日期。

    Args:
        db: SQLAlchemy AsyncSession
        tenant_id: 租户 ID
        store_id: 可选门店过滤
        weeks: 最近几周

    Returns:
        list[dict] with keys: store_id, stat_week, sample_logged_count,
        inspection_required, inspection_done, inspection_rate,
        violation_count, expiry_alerts, overdue_certificates,
        compliance_score
    """
    clauses = []
    params: dict[str, Any] = {"tenant_id": tenant_id}
    if store_id:
        clauses.append("AND store_id = :sid")
        params["sid"] = store_id
    clauses.append(f"AND stat_week >= CURRENT_DATE - INTERVAL '{weeks} weeks'")

    q = text(f"""
        SELECT store_id, stat_week, sample_logged_count,
               inspection_required, inspection_done, inspection_rate,
               violation_count, expiry_alerts, overdue_certificates,
               compliance_score, updated_at
        FROM mv_safety_compliance
        WHERE tenant_id = :tenant_id
          {' '.join(clauses)}
        ORDER BY stat_week DESC
    """)
    try:
        result = await db.execute(q, params)
        rows = []
        for r in result.mappings():
            item = dict(r)
            item["store_id"] = _str_or(item.get("store_id"))
            item["stat_week"] = _iso(item.get("stat_week"))
            item["updated_at"] = _iso(item.get("updated_at"))
            rows.append(item)
        return rows
    except (OperationalError, ProgrammingError) as exc:
        logger.warning("mv_reader_safety_compliance_failed", error=str(exc))
        return []


# ─────────────────────────────────────────────────────────────────────────────
# 8. mv_energy_efficiency
# ─────────────────────────────────────────────────────────────────────────────


async def get_energy_efficiency(
    db: Any,
    tenant_id: str,
    store_id: Optional[str] = None,
    stat_date: Optional[str | date] = None,
    days: int = 30,
) -> list[dict[str, Any]]:
    """从 mv_energy_efficiency 读取能耗效率数据。

    视图主键: (tenant_id, store_id, stat_date)

    Args:
        db: SQLAlchemy AsyncSession
        tenant_id: 租户 ID
        store_id: 可选门店过滤
        stat_date: 可选单日查询
        days: 最近多少天

    Returns:
        list[dict] with keys: store_id, stat_date, electricity_kwh, gas_m3,
        water_ton, energy_cost_fen, revenue_fen, energy_revenue_ratio,
        anomaly_count, off_hours_anomalies
    """
    dt = _ensure_date(stat_date) if stat_date else None
    clauses = []
    params: dict[str, Any] = {"tenant_id": tenant_id}

    if dt:
        clauses.append("AND stat_date = :dt")
        params["dt"] = dt
    else:
        clauses.append(f"AND stat_date >= CURRENT_DATE - :days")
        params["days"] = days
    if store_id:
        clauses.append("AND store_id = :sid")
        params["sid"] = store_id

    q = text(f"""
        SELECT store_id, stat_date, electricity_kwh, gas_m3, water_ton,
               energy_cost_fen, revenue_fen, energy_revenue_ratio,
               anomaly_count, off_hours_anomalies, updated_at
        FROM mv_energy_efficiency
        WHERE tenant_id = :tenant_id
          {' '.join(clauses)}
        ORDER BY stat_date DESC
    """)
    try:
        result = await db.execute(q, params)
        rows = []
        for r in result.mappings():
            item = dict(r)
            item["store_id"] = _str_or(item.get("store_id"))
            item["stat_date"] = _iso(item.get("stat_date"))
            item["updated_at"] = _iso(item.get("updated_at"))
            rows.append(item)
        return rows
    except (OperationalError, ProgrammingError) as exc:
        logger.warning("mv_reader_energy_efficiency_failed", error=str(exc))
        return []


# ─────────────────────────────────────────────────────────────────────────────
# 9. mv_table_turnover
# ─────────────────────────────────────────────────────────────────────────────


async def get_table_turnover(
    db: Any,
    tenant_id: str,
    store_id: Optional[str] = None,
    stat_date: Optional[str | date] = None,
    stat_hour: int = 0,
    days: int = 7,
) -> list[dict[str, Any]]:
    """从 mv_table_turnover 读取翻台率数据。

    视图主键: (tenant_id, store_id, stat_date, stat_hour)
    stat_hour=0 表示全天汇总，1-23 表示小时明细。

    Args:
        db: SQLAlchemy AsyncSession
        tenant_id: 租户 ID
        store_id: 可选门店过滤
        stat_date: 可选单日查询
        stat_hour: 小时（0=全天汇总, 1-23=小时明细）
        days: 最近多少天

    Returns:
        list[dict] with keys: store_id, stat_date, stat_hour, total_tables,
        occupied_tables, turnover_count, avg_occupancy_mins,
        peak_hour_tables, avg_party_size, revenue_per_table_fen,
        table_utilization_rate
    """
    dt = _ensure_date(stat_date) if stat_date else None
    params: dict[str, Any] = {
        "tenant_id": tenant_id,
        "stat_hour": stat_hour,
    }

    if dt:
        date_clause = "AND stat_date = :dt"
        params["dt"] = dt
    else:
        date_clause = f"AND stat_date >= CURRENT_DATE - :days"
        params["days"] = days

    store_clause = "AND store_id = :sid" if store_id else ""
    if store_id:
        params["sid"] = store_id

    q = text(f"""
        SELECT store_id, stat_date, stat_hour, total_tables,
               occupied_tables, turnover_count, avg_occupancy_mins,
               peak_hour_tables, avg_party_size, revenue_per_table_fen,
               table_utilization_rate, updated_at
        FROM mv_table_turnover
        WHERE tenant_id = :tenant_id
          AND stat_hour = :stat_hour
          {date_clause}
          {store_clause}
        ORDER BY stat_date DESC
    """)
    try:
        result = await db.execute(q, params)
        rows = []
        for r in result.mappings():
            item = dict(r)
            item["store_id"] = _str_or(item.get("store_id"))
            item["stat_date"] = _iso(item.get("stat_date"))
            item["updated_at"] = _iso(item.get("updated_at"))
            rows.append(item)
        return rows
    except (OperationalError, ProgrammingError) as exc:
        logger.warning("mv_reader_table_turnover_failed", error=str(exc))
        return []


# ─────────────────────────────────────────────────────────────────────────────
# 10. mv_dish_profitability
# ─────────────────────────────────────────────────────────────────────────────


async def get_dish_profitability(
    db: Any,
    tenant_id: str,
    store_id: Optional[str] = None,
    stat_date: Optional[str | date] = None,
    category: Optional[str] = None,
    min_margin_rate: float = 0.0,
    days: int = 30,
    top_n: int = 100,
) -> list[dict[str, Any]]:
    """从 mv_dish_profitability 读取菜品盈利数据。

    视图主键: (tenant_id, store_id, dish_id, stat_date)

    Args:
        db: SQLAlchemy AsyncSession
        tenant_id: 租户 ID
        store_id: 可选门店过滤
        stat_date: 可选单日查询
        category: 可选品类过滤
        min_margin_rate: 最低毛利率过滤
        days: 最近多少天
        top_n: 返回 TOP N

    Returns:
        list[dict] with keys: store_id, dish_id, dish_name, category,
        stat_date, order_count, gross_revenue_fen, discount_fen,
        net_revenue_fen, bom_cost_fen, channel_fee_fen,
        gross_margin_fen, gross_margin_rate, profitability_rank,
        popularity_rank, recommendation_score
    """
    dt = _ensure_date(stat_date) if stat_date else None
    clauses = []
    params: dict[str, Any] = {
        "tenant_id": tenant_id,
        "min_mr": min_margin_rate,
        "top_n": top_n,
    }

    if dt:
        clauses.append("AND stat_date = :dt")
        params["dt"] = dt
    else:
        clauses.append(f"AND stat_date >= CURRENT_DATE - :days")
        params["days"] = days
    if store_id:
        clauses.append("AND store_id = :sid")
        params["sid"] = store_id
    if category:
        clauses.append("AND category = :cat")
        params["cat"] = category

    q = text(f"""
        SELECT store_id, dish_id, dish_name, category, stat_date,
               order_count, gross_revenue_fen, discount_fen,
               net_revenue_fen, bom_cost_fen, channel_fee_fen,
               gross_margin_fen, gross_margin_rate,
               profitability_rank, popularity_rank, recommendation_score,
               updated_at
        FROM mv_dish_profitability
        WHERE tenant_id = :tenant_id
          AND gross_margin_rate >= :min_mr
          {' '.join(clauses)}
        ORDER BY gross_margin_fen DESC
        LIMIT :top_n
    """)
    try:
        result = await db.execute(q, params)
        rows = []
        for r in result.mappings():
            item = dict(r)
            item["store_id"] = _str_or(item.get("store_id"))
            item["dish_id"] = _str_or(item.get("dish_id"))
            item["stat_date"] = _iso(item.get("stat_date"))
            item["updated_at"] = _iso(item.get("updated_at"))
            rows.append(item)
        return rows
    except (OperationalError, ProgrammingError) as exc:
        logger.warning("mv_reader_dish_profitability_failed", error=str(exc))
        return []


# ─────────────────────────────────────────────────────────────────────────────
# 11. mv_employee_efficiency
# ─────────────────────────────────────────────────────────────────────────────


async def get_employee_efficiency(
    db: Any,
    tenant_id: str,
    store_id: Optional[str] = None,
    employee_id: Optional[str] = None,
    stat_date: Optional[str | date] = None,
    role_type: Optional[str] = None,
    min_efficiency_score: float = 0.0,
    days: int = 30,
    top_n: int = 100,
) -> list[dict[str, Any]]:
    """从 mv_employee_efficiency 读取人效指标。

    视图主键: (tenant_id, store_id, employee_id, stat_date)

    Args:
        db: SQLAlchemy AsyncSession
        tenant_id: 租户 ID
        store_id: 可选门店过滤
        employee_id: 可选员工过滤
        stat_date: 可选单日查询
        role_type: 可选角色过滤 (chef/waiter/cashier/manager)
        min_efficiency_score: 最低效能分过滤
        days: 最近多少天
        top_n: 返回 TOP N

    Returns:
        list[dict] with keys: store_id, employee_id, employee_name, role_type,
        stat_date, shift_hours, orders_handled, revenue_contributed_fen,
        avg_service_time_sec, tips_fen, efficiency_score,
        attendance_score, error_incidents
    """
    dt = _ensure_date(stat_date) if stat_date else None
    clauses = []
    params: dict[str, Any] = {
        "tenant_id": tenant_id,
        "min_es": min_efficiency_score,
        "top_n": top_n,
    }

    if dt:
        clauses.append("AND stat_date = :dt")
        params["dt"] = dt
    else:
        clauses.append(f"AND stat_date >= CURRENT_DATE - :days")
        params["days"] = days
    if store_id:
        clauses.append("AND store_id = :sid")
        params["sid"] = store_id
    if employee_id:
        clauses.append("AND employee_id = :eid")
        params["eid"] = employee_id
    if role_type:
        clauses.append("AND role_type = :rt")
        params["rt"] = role_type

    q = text(f"""
        SELECT store_id, employee_id, employee_name, role_type, stat_date,
               shift_hours, orders_handled, revenue_contributed_fen,
               avg_service_time_sec, tips_fen, efficiency_score,
               attendance_score, error_incidents, updated_at
        FROM mv_employee_efficiency
        WHERE tenant_id = :tenant_id
          AND efficiency_score >= :min_es
          {' '.join(clauses)}
        ORDER BY stat_date DESC, efficiency_score DESC
        LIMIT :top_n
    """)
    try:
        result = await db.execute(q, params)
        rows = []
        for r in result.mappings():
            item = dict(r)
            item["store_id"] = _str_or(item.get("store_id"))
            item["employee_id"] = _str_or(item.get("employee_id"))
            item["stat_date"] = _iso(item.get("stat_date"))
            item["updated_at"] = _iso(item.get("updated_at"))
            rows.append(item)
        return rows
    except (OperationalError, ProgrammingError) as exc:
        logger.warning("mv_reader_employee_efficiency_failed", error=str(exc))
        return []


# ─────────────────────────────────────────────────────────────────────────────
# 12. mv_customer_ltv
# ─────────────────────────────────────────────────────────────────────────────


async def get_customer_ltv(
    db: Any,
    tenant_id: str,
    min_predicted_ltv_fen: int = 0,
    churn_risk_threshold: float = 0.0,
    ltv_tier: Optional[str] = None,
    top_n: int = 100,
) -> list[dict[str, Any]]:
    """从 mv_customer_ltv 读取客户 LTV 数据。

    视图主键: (tenant_id, customer_id)

    Args:
        db: SQLAlchemy AsyncSession
        tenant_id: 租户 ID
        min_predicted_ltv_fen: 最低预测 LTV 过滤（分）
        churn_risk_threshold: 流失风险阈值（0-1）
        ltv_tier: 可选 LTV 分层过滤
        top_n: 返回 TOP N

    Returns:
        list[dict] with keys: customer_id, customer_name, member_level,
        first_order_date, last_order_date, total_orders, total_spent_fen,
        avg_order_value_fen, visit_frequency_days, preferred_channel,
        preferred_categories, discount_sensitivity, churn_risk,
        predicted_ltv_fen, ltv_tier
    """
    clauses = []
    params: dict[str, Any] = {
        "tenant_id": tenant_id,
        "min_ltv": min_predicted_ltv_fen,
        "churn_threshold": churn_risk_threshold,
        "top_n": top_n,
    }

    if ltv_tier:
        clauses.append("AND ltv_tier = :tier")
        params["tier"] = ltv_tier

    q = text(f"""
        SELECT customer_id, customer_name, member_level,
               first_order_date, last_order_date,
               total_orders, total_spent_fen, avg_order_value_fen,
               visit_frequency_days, preferred_channel,
               preferred_categories, discount_sensitivity,
               churn_risk, predicted_ltv_fen, ltv_tier, updated_at
        FROM mv_customer_ltv
        WHERE tenant_id = :tenant_id
          AND predicted_ltv_fen >= :min_ltv
          AND churn_risk >= :churn_threshold
          {' '.join(clauses)}
        ORDER BY predicted_ltv_fen DESC
        LIMIT :top_n
    """)
    try:
        result = await db.execute(q, params)
        rows = []
        for r in result.mappings():
            item = dict(r)
            item["customer_id"] = _str_or(item.get("customer_id"))
            item["first_order_date"] = _iso(item.get("first_order_date"))
            item["last_order_date"] = _iso(item.get("last_order_date"))
            item["updated_at"] = _iso(item.get("updated_at"))
            rows.append(item)
        return rows
    except (OperationalError, ProgrammingError) as exc:
        logger.warning("mv_reader_customer_ltv_failed", error=str(exc))
        return []


# ─────────────────────────────────────────────────────────────────────────────
# 13. mv_public_opinion
# ─────────────────────────────────────────────────────────────────────────────


async def get_public_opinion(
    db: Any,
    tenant_id: str,
    store_id: Optional[str] = None,
    platform: Optional[str] = None,
    days: int = 30,
    min_sentiment_score: float = 0.0,
    top_n: int = 50,
) -> list[dict[str, Any]]:
    """从 mv_public_opinion 读取舆情/点评聚合数据。

    数据来源: public_opinion.* 事件，由 PublicOpinionProjector 维护。

    Args:
        db: SQLAlchemy AsyncSession
        tenant_id: 租户 ID
        store_id: 可选门店过滤
        platform: 可选平台过滤 (dianping/meituan/xiaohongshu/douyin)
        days: 最近多少天
        min_sentiment_score: 最低情感分
        top_n: 返回 TOP N

    Returns:
        list[dict] with relevant keys from the view
    """
    clauses = []
    params: dict[str, Any] = {
        "tenant_id": tenant_id,
        "top_n": top_n,
    }

    if store_id:
        clauses.append("AND store_id = :sid")
        params["sid"] = store_id
    if platform:
        clauses.append("AND platform = :plat")
        params["plat"] = platform
    if min_sentiment_score > 0:
        clauses.append("AND sentiment_score >= :min_ss")
        params["min_ss"] = min_sentiment_score
    clauses.append(f"AND fetched_at >= CURRENT_DATE - :days")
    params["days"] = days

    q = text(f"""
        SELECT *
        FROM mv_public_opinion
        WHERE tenant_id = :tenant_id
          {' '.join(clauses)}
        ORDER BY fetched_at DESC
        LIMIT :top_n
    """)
    try:
        result = await db.execute(q, params)
        rows = []
        for r in result.mappings():
            item = dict(r)
            for key in ("tenant_id", "store_id", "id"):
                if key in item:
                    item[key] = _str_or(item.get(key))
            for key in ("fetched_at", "created_at", "updated_at"):
                if key in item:
                    item[key] = _iso(item.get(key))
            rows.append(item)
        return rows
    except (OperationalError, ProgrammingError) as exc:
        logger.warning("mv_reader_public_opinion_failed", error=str(exc))
        return []
