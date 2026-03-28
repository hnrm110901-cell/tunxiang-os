"""异常摘要 — 经营预警与异常事件聚合

异常类型：discount_anomaly / cooking_timeout / stockout / margin_drop / food_safety
严重级别：critical / warning / info
"""
import structlog
from datetime import datetime
from typing import Optional

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


# ─── 数据库查询（桩函数） ───

async def _query_today_alerts(
    db, store_id: str, tenant_id: str
) -> list[dict]:
    """查询今日告警"""
    if db is None:
        now = datetime.now()
        return [
            {
                "id": "alert-001",
                "type": "discount_anomaly",
                "severity": "critical",
                "title": "异常折扣：8号桌全单5折",
                "detail": "服务员张三对8号桌执行全单5折，超出授权范围（最高7折）",
                "time": now.replace(hour=12, minute=35).isoformat(),
                "status": "pending",
                "action_required": True,
                "_ts": 1235,
            },
            {
                "id": "alert-002",
                "type": "cooking_timeout",
                "severity": "warning",
                "title": "出餐超时：剁椒鱼头(23号桌)",
                "detail": "已等待28分钟，目标出餐时间20分钟",
                "time": now.replace(hour=12, minute=50).isoformat(),
                "status": "pending",
                "action_required": True,
                "_ts": 1250,
            },
            {
                "id": "alert-003",
                "type": "stockout",
                "severity": "warning",
                "title": "临近售罄：小龙虾（剩余3份）",
                "detail": "预计14:00前售罄，建议提前86数量或下架",
                "time": now.replace(hour=11, minute=20).isoformat(),
                "status": "acknowledged",
                "action_required": False,
                "_ts": 1120,
            },
            {
                "id": "alert-004",
                "type": "margin_drop",
                "severity": "info",
                "title": "毛利率波动：午市毛利率降至58%",
                "detail": "较昨日同期下降3.2个百分点，主因小龙虾原材料涨价",
                "time": now.replace(hour=13, minute=15).isoformat(),
                "status": "resolved",
                "action_required": False,
                "_ts": 1315,
            },
        ]

    today = datetime.now().date()
    row = await db.execute(
        """
        SELECT id, type, severity, title, detail,
               time, status, action_required,
               EXTRACT(EPOCH FROM time)::int AS _ts
        FROM alerts
        WHERE store_id = :store_id
          AND tenant_id = :tenant_id
          AND DATE(time) = :today
          AND is_deleted = FALSE
        """,
        {"store_id": store_id, "tenant_id": tenant_id, "today": today},
    )
    return [dict(r) for r in row.mappings().all()]


async def _query_all_alerts_today(db, tenant_id: str) -> list[dict]:
    """查询全租户今日告警"""
    if db is None:
        # 复用 mock
        return [
            {"type": "discount_anomaly", "severity": "critical", "status": "pending"},
            {"type": "cooking_timeout", "severity": "warning", "status": "pending"},
            {"type": "stockout", "severity": "warning", "status": "acknowledged"},
            {"type": "margin_drop", "severity": "info", "status": "resolved"},
            {"type": "food_safety", "severity": "critical", "status": "pending"},
            {"type": "cooking_timeout", "severity": "warning", "status": "resolved"},
            {"type": "discount_anomaly", "severity": "warning", "status": "pending"},
        ]

    today = datetime.now().date()
    row = await db.execute(
        """
        SELECT type, severity, status
        FROM alerts
        WHERE tenant_id = :tenant_id
          AND DATE(time) = :today
          AND is_deleted = FALSE
        """,
        {"tenant_id": tenant_id, "today": today},
    )
    return [dict(r) for r in row.mappings().all()]
