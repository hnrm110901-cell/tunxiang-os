"""积分到期管理 — 到期查询/提醒推送/批量清零/到期日历

每年固定日期清零（可配置），支持定时任务批量处理。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)

# ── 内存存储 ──────────────────────────────────────────────────

_points_batches: dict[str, list[dict]] = {}  # customer_id -> [batch]
_expiry_config: dict[str, dict] = {}  # tenant_id -> config
_reminder_log: list[dict] = []  # 提醒发送日志
_cleared_log: list[dict] = []  # 清零日志

# 默认到期配置
DEFAULT_EXPIRY_CONFIG = {
    "expiry_month": 12,    # 到期月份
    "expiry_day": 31,      # 到期日期
    "reminder_days": [30, 7, 3, 1],  # 提前N天提醒
    "batch_validity_days": 365,  # 每批积分有效天数
}


# ── 工具函数 ──────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _get_expiry_config(tenant_id: str) -> dict:
    """获取租户的到期配置"""
    return _expiry_config.get(tenant_id, DEFAULT_EXPIRY_CONFIG)


def _calculate_expiry_date(earned_at: datetime, config: dict) -> datetime:
    """计算积分到期日期"""
    validity_days = config.get("batch_validity_days", 365)
    return earned_at + timedelta(days=validity_days)


# ── 服务函数 ──────────────────────────────────────────────────


async def get_expiring_points(
    customer_id: str,
    tenant_id: str,
    db: Any = None,
) -> dict[str, Any]:
    """获取即将到期的积分信息

    Args:
        customer_id: 客户ID
        tenant_id: 租户ID
        db: 数据库会话

    Returns:
        {"customer_id", "expiring_points", "expiry_date",
         "days_remaining", "total_points", "batches"}
    """
    config = _get_expiry_config(tenant_id)
    now = _now_utc()
    batches = _points_batches.get(customer_id, [])

    # 筛选该租户的批次
    tenant_batches = [
        b for b in batches
        if b.get("tenant_id") == tenant_id and not b.get("cleared", False)
    ]

    # 计算总积分和即将到期的积分
    total_points = sum(b.get("remaining_points", 0) for b in tenant_batches)
    expiring_points = 0
    nearest_expiry: Optional[datetime] = None

    expiring_batches = []
    for batch in tenant_batches:
        expiry_date = batch.get("expiry_date")
        if not expiry_date:
            continue
        if isinstance(expiry_date, str):
            expiry_date = datetime.fromisoformat(expiry_date)
        remaining = batch.get("remaining_points", 0)
        if remaining <= 0:
            continue

        days_left = (expiry_date - now).days
        if 0 < days_left <= 90:  # 90天内到期的算即将到期
            expiring_points += remaining
            expiring_batches.append({
                "batch_id": batch["batch_id"],
                "remaining_points": remaining,
                "expiry_date": expiry_date.isoformat(),
                "days_remaining": days_left,
            })
            if nearest_expiry is None or expiry_date < nearest_expiry:
                nearest_expiry = expiry_date

    days_remaining = (nearest_expiry - now).days if nearest_expiry else -1

    logger.info(
        "points_expiry.queried",
        customer_id=customer_id,
        total_points=total_points,
        expiring_points=expiring_points,
        days_remaining=days_remaining,
        tenant_id=tenant_id,
    )

    return {
        "customer_id": customer_id,
        "expiring_points": expiring_points,
        "expiry_date": nearest_expiry.isoformat() if nearest_expiry else None,
        "days_remaining": days_remaining,
        "total_points": total_points,
        "batches": expiring_batches,
    }


async def send_expiry_reminder(
    customer_id: str,
    tenant_id: str,
    db: Any = None,
) -> dict[str, Any]:
    """推送到期提醒（模板消息）

    Args:
        customer_id: 客户ID
        tenant_id: 租户ID
        db: 数据库会话

    Returns:
        {"customer_id", "sent", "expiring_points", "message_type"}
    """
    expiry_info = await get_expiring_points(customer_id, tenant_id, db)
    expiring_points = expiry_info.get("expiring_points", 0)
    days_remaining = expiry_info.get("days_remaining", -1)

    if expiring_points <= 0:
        logger.info(
            "points_expiry.no_expiring",
            customer_id=customer_id,
            tenant_id=tenant_id,
        )
        return {
            "customer_id": customer_id,
            "sent": False,
            "reason": "no_expiring_points",
        }

    # 确定提醒渠道
    config = _get_expiry_config(tenant_id)
    reminder_days = config.get("reminder_days", [30, 7, 3, 1])

    if days_remaining not in reminder_days and days_remaining > 0:
        # 非提醒日, 仍然发送但标记为手动
        message_type = "manual_reminder"
    else:
        message_type = "auto_reminder"

    # 构建模板消息
    message = {
        "template": "points_expiry_reminder",
        "customer_id": customer_id,
        "data": {
            "expiring_points": expiring_points,
            "days_remaining": days_remaining,
            "expiry_date": expiry_info.get("expiry_date"),
        },
    }

    now = _now_utc()
    reminder_record = {
        "reminder_id": str(uuid.uuid4()),
        "customer_id": customer_id,
        "tenant_id": tenant_id,
        "message_type": message_type,
        "expiring_points": expiring_points,
        "days_remaining": days_remaining,
        "sent_at": now.isoformat(),
    }
    _reminder_log.append(reminder_record)

    logger.info(
        "points_expiry.reminder_sent",
        customer_id=customer_id,
        expiring_points=expiring_points,
        days_remaining=days_remaining,
        message_type=message_type,
        tenant_id=tenant_id,
    )

    return {
        "customer_id": customer_id,
        "sent": True,
        "expiring_points": expiring_points,
        "days_remaining": days_remaining,
        "message_type": message_type,
        "sent_at": now.isoformat(),
    }


async def batch_clear_expired(
    tenant_id: str,
    db: Any = None,
) -> dict[str, Any]:
    """批量清零过期积分（定时任务）

    Args:
        tenant_id: 租户ID
        db: 数据库会话

    Returns:
        {"cleared_count", "cleared_points_total", "affected_customers", "details"}
    """
    now = _now_utc()
    cleared_count = 0
    cleared_points_total = 0
    affected_customers: set[str] = set()
    details: list[dict] = []

    for customer_id, batches in _points_batches.items():
        for batch in batches:
            if batch.get("tenant_id") != tenant_id:
                continue
            if batch.get("cleared", False):
                continue

            expiry_date = batch.get("expiry_date")
            if not expiry_date:
                continue
            if isinstance(expiry_date, str):
                expiry_date = datetime.fromisoformat(expiry_date)

            remaining = batch.get("remaining_points", 0)
            if remaining <= 0:
                continue

            if now >= expiry_date:
                # 清零
                batch["cleared"] = True
                batch["cleared_at"] = now.isoformat()
                batch["cleared_points"] = remaining
                batch["remaining_points"] = 0

                cleared_count += 1
                cleared_points_total += remaining
                affected_customers.add(customer_id)
                details.append({
                    "customer_id": customer_id,
                    "batch_id": batch["batch_id"],
                    "cleared_points": remaining,
                    "expiry_date": expiry_date.isoformat(),
                })

    cleared_record = {
        "clear_id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "cleared_count": cleared_count,
        "cleared_points_total": cleared_points_total,
        "affected_customers": len(affected_customers),
        "executed_at": now.isoformat(),
    }
    _cleared_log.append(cleared_record)

    logger.info(
        "points_expiry.batch_cleared",
        cleared_count=cleared_count,
        cleared_points_total=cleared_points_total,
        affected_customers=len(affected_customers),
        tenant_id=tenant_id,
    )

    return {
        "cleared_count": cleared_count,
        "cleared_points_total": cleared_points_total,
        "affected_customers": len(affected_customers),
        "details": details,
    }


async def get_expiry_calendar(
    tenant_id: str,
    db: Any = None,
) -> dict[str, Any]:
    """全年积分到期日历

    Args:
        tenant_id: 租户ID
        db: 数据库会话

    Returns:
        {"tenant_id", "year", "monthly_summary", "total_expiring"}
    """
    now = _now_utc()
    current_year = now.year

    # 按月汇总到期积分
    monthly_summary: dict[int, dict] = {}
    for month in range(1, 13):
        monthly_summary[month] = {
            "month": month,
            "expiring_points": 0,
            "batch_count": 0,
            "customer_count": 0,
        }

    customer_sets: dict[int, set] = {m: set() for m in range(1, 13)}
    total_expiring = 0

    for customer_id, batches in _points_batches.items():
        for batch in batches:
            if batch.get("tenant_id") != tenant_id:
                continue
            if batch.get("cleared", False):
                continue

            expiry_date = batch.get("expiry_date")
            if not expiry_date:
                continue
            if isinstance(expiry_date, str):
                expiry_date = datetime.fromisoformat(expiry_date)

            remaining = batch.get("remaining_points", 0)
            if remaining <= 0:
                continue

            if expiry_date.year == current_year:
                month = expiry_date.month
                monthly_summary[month]["expiring_points"] += remaining
                monthly_summary[month]["batch_count"] += 1
                customer_sets[month].add(customer_id)
                total_expiring += remaining

    for month in range(1, 13):
        monthly_summary[month]["customer_count"] = len(customer_sets[month])

    logger.info(
        "points_expiry.calendar",
        year=current_year,
        total_expiring=total_expiring,
        tenant_id=tenant_id,
    )

    return {
        "tenant_id": tenant_id,
        "year": current_year,
        "monthly_summary": list(monthly_summary.values()),
        "total_expiring": total_expiring,
    }


# ── 数据注入（测试用） ──────────────────────────────────────────


def add_points_batch(
    customer_id: str,
    tenant_id: str,
    points: int,
    earned_at: Optional[datetime] = None,
    expiry_date: Optional[datetime] = None,
) -> dict:
    """添加积分批次（测试/内部调用）"""
    config = _get_expiry_config(tenant_id)
    now = earned_at or _now_utc()
    exp_date = expiry_date or _calculate_expiry_date(now, config)

    batch = {
        "batch_id": str(uuid.uuid4()),
        "customer_id": customer_id,
        "tenant_id": tenant_id,
        "earned_points": points,
        "remaining_points": points,
        "earned_at": now.isoformat(),
        "expiry_date": exp_date if isinstance(exp_date, datetime) else exp_date,
        "cleared": False,
    }
    _points_batches.setdefault(customer_id, []).append(batch)
    return batch


def set_expiry_config(tenant_id: str, config: dict) -> None:
    """设置租户到期配置"""
    _expiry_config[tenant_id] = {**DEFAULT_EXPIRY_CONFIG, **config}


def clear_all_expiry_data() -> None:
    """清空所有数据 (仅测试用)"""
    _points_batches.clear()
    _expiry_config.clear()
    _reminder_log.clear()
    _cleared_log.clear()
