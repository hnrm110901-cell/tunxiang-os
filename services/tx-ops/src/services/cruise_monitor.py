"""E2 营业巡航 — 实时看板、桌台巡航、出餐巡航、沽清巡航、巡台记录

持续监控营业状态，发现异常自动告警。
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog

from shared.events import UniversalPublisher, OpsEventType

log = structlog.get_logger(__name__)

# ─── 告警级别 & 类型 ───

ALERT_LEVELS = ("info", "warning", "critical")

ALERT_TYPES = {
    "table_overtime":      "桌台超时未结账",
    "table_uncleaned":     "空桌未清台",
    "cooking_timeout":     "出餐超时",
    "cooking_backlog":     "出餐堆积",
    "stockout_new":        "新增沽清",
    "stockout_risk":       "即将沽清预警",
    "low_table_usage":     "桌台利用率低",
    "high_wait_time":      "等位时间过长",
}

# ─── 默认阈值 ───

DEFAULT_THRESHOLDS = {
    "table_overtime_minutes": 120,       # 桌台超时: 2小时
    "table_unclean_minutes": 10,         # 清台超时: 10分钟
    "cooking_timeout_minutes": 25,       # 出餐超时: 25分钟（海鲜标准）
    "cooking_backlog_count": 15,         # 堆积订单数
    "low_table_usage_pct": 30,           # 低利用率阈值
    "high_wait_minutes": 20,             # 等位超时
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  实时看板
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def get_realtime_dashboard(
    store_id: str,
    tenant_id: str,
    db: Any,
) -> Dict[str, Any]:
    """获取门店实时经营看板。

    聚合收入、订单、桌台利用率、平均等待时间和活跃告警。

    Args:
        store_id: 门店 ID
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        {"revenue_fen": int, "orders": int, "table_usage_pct": float,
         "avg_wait_min": float, "alerts": [...], "snapshot_at": str}
    """
    # 实际实现从 db 聚合; 这里返回结构骨架
    now = datetime.utcnow().isoformat()

    # 调用各巡航模块收集告警
    table_alerts = await check_table_cruise(store_id, tenant_id, db)
    cooking_alerts = await check_cooking_cruise(store_id, tenant_id, db)
    stockout_alerts = await check_stockout_cruise(store_id, tenant_id, db)

    all_alerts = table_alerts + cooking_alerts + stockout_alerts

    dashboard = {
        "store_id": store_id,
        "tenant_id": tenant_id,
        "revenue_fen": 0,
        "orders": 0,
        "table_usage_pct": 0.0,
        "avg_wait_min": 0.0,
        "alerts": all_alerts,
        "alert_count": len(all_alerts),
        "snapshot_at": now,
    }

    log.info(
        "dashboard_snapshot",
        store_id=store_id,
        tenant_id=tenant_id,
        alert_count=len(all_alerts),
    )
    return dashboard


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  桌台巡航
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def check_table_cruise(
    store_id: str,
    tenant_id: str,
    db: Any,
    *,
    thresholds: Optional[Dict[str, int]] = None,
    tables: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """桌台巡航：检测超时未结账 / 空桌未清台。

    Args:
        store_id: 门店 ID
        tenant_id: 租户 ID
        db: 数据库会话
        thresholds: 自定义阈值
        tables: 桌台状态列表（测试注入用）

    Returns:
        告警列表 [{"alert_type": str, "level": str, "table_id": str, ...}]
    """
    thr = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    alerts: List[Dict[str, Any]] = []
    now = datetime.utcnow()

    for table in (tables or []):
        table_id = table.get("table_id", "")
        status = table.get("status", "")
        occupied_since = table.get("occupied_since")
        cleared_at = table.get("cleared_at")

        # 超时未结账
        if status == "occupied" and occupied_since:
            if isinstance(occupied_since, str):
                occupied_since = datetime.fromisoformat(occupied_since)
            elapsed = (now - occupied_since).total_seconds() / 60
            if elapsed > thr["table_overtime_minutes"]:
                alerts.append({
                    "alert_type": "table_overtime",
                    "level": "warning",
                    "table_id": table_id,
                    "elapsed_min": round(elapsed, 1),
                    "threshold_min": thr["table_overtime_minutes"],
                    "message": f"桌台 {table_id} 已用餐 {round(elapsed)}分钟，超出 {thr['table_overtime_minutes']}分钟阈值",
                    "detected_at": now.isoformat(),
                })

        # 空桌未清台
        if status == "needs_cleaning" and cleared_at:
            if isinstance(cleared_at, str):
                cleared_at = datetime.fromisoformat(cleared_at)
            idle = (now - cleared_at).total_seconds() / 60
            if idle > thr["table_unclean_minutes"]:
                alerts.append({
                    "alert_type": "table_uncleaned",
                    "level": "warning",
                    "table_id": table_id,
                    "idle_min": round(idle, 1),
                    "threshold_min": thr["table_unclean_minutes"],
                    "message": f"桌台 {table_id} 已空闲 {round(idle)}分钟未清台",
                    "detected_at": now.isoformat(),
                })

    if alerts:
        log.warning(
            "table_cruise_alerts",
            store_id=store_id,
            tenant_id=tenant_id,
            alert_count=len(alerts),
        )
    return alerts


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  出餐巡航
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def check_cooking_cruise(
    store_id: str,
    tenant_id: str,
    db: Any,
    *,
    thresholds: Optional[Dict[str, int]] = None,
    orders: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """出餐巡航：检测超时出餐 / 订单堆积。

    Args:
        store_id: 门店 ID
        tenant_id: 租户 ID
        db: 数据库会话
        thresholds: 自定义阈值
        orders: 待出餐订单列表（测试注入用）

    Returns:
        告警列表
    """
    thr = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    alerts: List[Dict[str, Any]] = []
    now = datetime.utcnow()
    pending_orders = orders or []

    # 出餐堆积
    if len(pending_orders) > thr["cooking_backlog_count"]:
        alerts.append({
            "alert_type": "cooking_backlog",
            "level": "critical",
            "pending_count": len(pending_orders),
            "threshold": thr["cooking_backlog_count"],
            "message": f"待出餐订单 {len(pending_orders)} 单，超出 {thr['cooking_backlog_count']} 单阈值",
            "detected_at": now.isoformat(),
        })

    # 逐单检测超时
    for order in pending_orders:
        order_id = order.get("order_id", "")
        created_at = order.get("created_at")
        if created_at:
            if isinstance(created_at, str):
                created_at = datetime.fromisoformat(created_at)
            elapsed = (now - created_at).total_seconds() / 60
            if elapsed > thr["cooking_timeout_minutes"]:
                alerts.append({
                    "alert_type": "cooking_timeout",
                    "level": "warning",
                    "order_id": order_id,
                    "elapsed_min": round(elapsed, 1),
                    "threshold_min": thr["cooking_timeout_minutes"],
                    "message": f"订单 {order_id} 已等待 {round(elapsed)}分钟出餐",
                    "detected_at": now.isoformat(),
                })

    if alerts:
        log.warning(
            "cooking_cruise_alerts",
            store_id=store_id,
            tenant_id=tenant_id,
            alert_count=len(alerts),
        )
    return alerts


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  沽清巡航
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def check_stockout_cruise(
    store_id: str,
    tenant_id: str,
    db: Any,
    *,
    dishes: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """沽清巡航：检测已沽清 / 即将沽清的菜品。

    Args:
        store_id: 门店 ID
        tenant_id: 租户 ID
        db: 数据库会话
        dishes: 菜品库存列表（测试注入用）

    Returns:
        告警列表
    """
    alerts: List[Dict[str, Any]] = []
    now = datetime.utcnow()

    for dish in (dishes or []):
        dish_id = dish.get("dish_id", "")
        dish_name = dish.get("name", "")
        remaining = dish.get("remaining_qty", 0)
        daily_avg = dish.get("daily_avg_sales", 0)

        if remaining <= 0:
            alerts.append({
                "alert_type": "stockout_new",
                "level": "critical",
                "dish_id": dish_id,
                "dish_name": dish_name,
                "remaining_qty": remaining,
                "message": f"菜品 {dish_name} 已沽清",
                "detected_at": now.isoformat(),
            })
        elif daily_avg > 0 and remaining < daily_avg * 0.3:
            alerts.append({
                "alert_type": "stockout_risk",
                "level": "warning",
                "dish_id": dish_id,
                "dish_name": dish_name,
                "remaining_qty": remaining,
                "daily_avg_sales": daily_avg,
                "message": f"菜品 {dish_name} 余量 {remaining}，低于日均销量30%",
                "detected_at": now.isoformat(),
            })

    if alerts:
        log.warning(
            "stockout_cruise_alerts",
            store_id=store_id,
            tenant_id=tenant_id,
            alert_count=len(alerts),
        )
    return alerts


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  巡台记录
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def record_patrol(
    store_id: str,
    operator_id: str,
    findings: List[Dict[str, Any]],
    tenant_id: str,
    db: Any,
) -> Dict[str, Any]:
    """记录巡台发现。

    Args:
        store_id: 门店 ID
        operator_id: 操作人 ID
        findings: 发现列表, 每项 {"type": str, "description": str, "severity": str, "location": str}
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        {"patrol_id": str, "store_id": str, "findings_count": int,
         "recorded_at": str, "operator_id": str}
    """
    patrol_id = f"patrol_{store_id}_{uuid.uuid4().hex[:8]}"

    enriched_findings = []
    for idx, finding in enumerate(findings):
        enriched_findings.append({
            "finding_id": f"{patrol_id}_f{idx:03d}",
            "type": finding.get("type", "observation"),
            "description": finding.get("description", ""),
            "severity": finding.get("severity", "info"),
            "location": finding.get("location", ""),
            "recorded_at": datetime.utcnow().isoformat(),
        })

    record = {
        "patrol_id": patrol_id,
        "store_id": store_id,
        "tenant_id": tenant_id,
        "operator_id": operator_id,
        "findings": enriched_findings,
        "findings_count": len(enriched_findings),
        "recorded_at": datetime.utcnow().isoformat(),
    }

    log.info(
        "patrol_recorded",
        store_id=store_id,
        tenant_id=tenant_id,
        patrol_id=patrol_id,
        operator_id=operator_id,
        findings_count=len(enriched_findings),
    )

    issues_count = sum(
        1 for f in enriched_findings if f.get("severity") in ("warning", "critical")
    )
    asyncio.create_task(UniversalPublisher.publish(
        event_type=OpsEventType.INSPECTION_COMPLETED,
        tenant_id=uuid.UUID(tenant_id),
        store_id=uuid.UUID(store_id),
        entity_id=None,
        event_data={"inspection_id": patrol_id, "score": None, "issues_count": issues_count},
        source_service="tx-ops",
    ))

    return record
