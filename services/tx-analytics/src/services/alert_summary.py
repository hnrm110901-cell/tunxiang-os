"""异常摘要 — 经营预警与异常事件聚合

异常类型：discount_anomaly / cooking_timeout / stockout / margin_drop / food_safety
严重级别：critical / warning / info
"""

from datetime import datetime

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .sql_queries import query_alerts_today

log = structlog.get_logger()

# 支持的异常类型
ALERT_TYPES = {
    "discount_anomaly",
    "cooking_timeout",
    "stockout",
    "margin_drop",
    "food_safety",
}

# 严重级别优先级（用于排序）
SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


# ─── 纯函数：统计聚合 ───


def aggregate_alert_stats(alerts: list[dict]) -> dict:
    """从告警列表聚合统计数据

    Returns:
        {total, by_severity: {critical, warning, info},
         by_type: {...}, unresolved}
    """
    by_severity = {"critical": 0, "warning": 0, "info": 0}
    by_type: dict[str, int] = {}
    unresolved = 0

    for alert in alerts:
        sev = alert.get("severity", "info")
        by_severity[sev] = by_severity.get(sev, 0) + 1

        atype = alert.get("type", "unknown")
        by_type[atype] = by_type.get(atype, 0) + 1

        if alert.get("status") != "resolved":
            unresolved += 1

    return {
        "total": len(alerts),
        "by_severity": by_severity,
        "by_type": by_type,
        "unresolved": unresolved,
    }


def sort_alerts_by_severity(alerts: list[dict]) -> list[dict]:
    """按严重级别排序：critical > warning > info，同级别按时间倒序"""
    return sorted(
        alerts,
        key=lambda a: (
            SEVERITY_ORDER.get(a.get("severity", "info"), 9),
            -(a.get("_ts", 0)),
        ),
    )


# ─── 今日告警列表 ───


async def get_today_alerts(
    store_id: str,
    tenant_id: str,
    db,
) -> list[dict]:
    """获取今日告警列表（单店）

    Returns:
        [{id, type, severity, title, detail, time, status, action_required}]
    """
    log.info("get_today_alerts", store_id=store_id, tenant_id=tenant_id)

    raw = await _query_today_alerts(db, store_id, tenant_id)
    sorted_alerts = sort_alerts_by_severity(raw)

    # 移除内部排序字段
    for alert in sorted_alerts:
        alert.pop("_ts", None)

    return sorted_alerts


# ─── 异常统计（全租户） ───


async def get_alert_stats(
    tenant_id: str,
    db,
) -> dict:
    """获取全租户异常统计

    Returns:
        {total, by_severity: {critical, warning, info}, by_type: {...}, unresolved}
    """
    log.info("get_alert_stats", tenant_id=tenant_id)

    all_alerts = await _query_all_alerts_today(db, tenant_id)
    return aggregate_alert_stats(all_alerts)


# ─── 数据库查询（通过统一SQL查询层） ───


async def _query_today_alerts(db: AsyncSession, store_id: str, tenant_id: str) -> list[dict]:
    """查询今日告警，委托给 sql_queries 统一查询层

    额外添加 _ts 字段用于排序。
    """
    alerts = await query_alerts_today(store_id, tenant_id, db)

    # 添加排序用时间戳
    for alert in alerts:
        time_str = alert.get("time", "")
        try:
            dt = datetime.fromisoformat(time_str)
            alert["_ts"] = int(dt.hour * 100 + dt.minute)
        except (ValueError, TypeError):
            alert["_ts"] = 0

    return alerts


async def _query_all_alerts_today(db: AsyncSession, tenant_id: str) -> list[dict]:
    """查询全租户今日告警"""
    today = datetime.now().date()
    row = await db.execute(
        text("""
            SELECT type, severity, status
            FROM alerts
            WHERE tenant_id = :tenant_id
              AND DATE(time) = :today
              AND is_deleted = FALSE
        """),
        {"tenant_id": tenant_id, "today": today},
    )
    return [dict(r) for r in row.mappings().all()]
