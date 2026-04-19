"""D7 通知引擎 — 联动派单系统发送多渠道通知

支持渠道: wecom(企业微信) / feishu(飞书) / sms(短信) / push(推送) / in_app(应用内)
当前为 mock 实现, 不发送真实消息, 但接口完整可替换。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog

log = structlog.get_logger(__name__)

# ─── 支持的通知渠道 ───

VALID_CHANNELS = ("wecom", "feishu", "sms", "push", "in_app")

# ─── 内存存储(生产环境替换为 DB) ───

_notification_history: List[Dict[str, Any]] = []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  发送通知
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def send_notification(
    recipient_id: str,
    channel: str,
    title: str,
    content: str,
    tenant_id: str,
    db: Any,
) -> Dict[str, Any]:
    """发送通知(mock 实现)。

    Args:
        recipient_id: 接收人 ID
        channel: 通知渠道 (wecom/feishu/sms/push/in_app)
        title: 通知标题
        content: 通知内容
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        {"notification_id": str, "recipient_id": str, "channel": str,
         "status": "sent", "sent_at": str}

    Raises:
        ValueError: 无效的通知渠道
    """
    if channel not in VALID_CHANNELS:
        raise ValueError(f"Invalid channel '{channel}'. Valid channels: {', '.join(VALID_CHANNELS)}")

    notification_id = f"notif_{uuid.uuid4().hex[:8]}"
    sent_at = datetime.utcnow().isoformat()

    record = {
        "notification_id": notification_id,
        "tenant_id": tenant_id,
        "recipient_id": recipient_id,
        "channel": channel,
        "title": title,
        "content": content,
        "status": "sent",  # mock: 直接标记为已发送
        "sent_at": sent_at,
        "delivered_at": None,
        "read_at": None,
    }

    _notification_history.append(record)

    # ── Mock 渠道分发(日志记录, 不实际发送) ──
    log.info(
        "notification_sent_mock",
        notification_id=notification_id,
        tenant_id=tenant_id,
        recipient_id=recipient_id,
        channel=channel,
        title=title,
    )

    return {
        "notification_id": notification_id,
        "recipient_id": recipient_id,
        "channel": channel,
        "status": "sent",
        "sent_at": sent_at,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  批量通知派单对象
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def send_alert_notification(
    alert: Dict[str, Any],
    assignees: List[Dict[str, Any]],
    tenant_id: str,
    db: Any,
    *,
    channels: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """批量通知派单对象。

    Args:
        alert: 预警信息
            {
                "alert_type": str,
                "store_id": str,
                "summary": str,
                "severity": str,
                "task_id": str,
            }
        assignees: 被派单人列表
            [{"id": str, "name": str, "role": str}, ...]
        tenant_id: 租户 ID
        db: 数据库会话
        channels: 通知渠道列表, 默认 ["in_app", "wecom"]

    Returns:
        {
            "alert_type": str,
            "total_notifications": int,
            "notifications": [{notification_id, recipient_id, channel, status}, ...],
        }
    """
    channels_ = channels or ["in_app", "wecom"]
    severity = alert.get("severity", "normal")
    alert_type = alert.get("alert_type", "unknown")
    store_id = alert.get("store_id", "")
    summary = alert.get("summary", "")
    task_id = alert.get("task_id", "")

    severity_label = {"urgent": "[紧急]", "severe": "[严重]", "normal": ""}.get(severity, "")
    title = f"{severity_label}运营预警 - {alert_type}"
    content = f"门店: {store_id}\n类型: {alert_type}\n详情: {summary}\n任务编号: {task_id}\n请尽快处理。"

    results: List[Dict[str, Any]] = []

    for assignee in assignees:
        recipient_id = assignee.get("id", "")
        for ch in channels_:
            try:
                notif = await send_notification(
                    recipient_id=recipient_id,
                    channel=ch,
                    title=title,
                    content=content,
                    tenant_id=tenant_id,
                    db=db,
                )
                results.append(notif)
            except ValueError as exc:
                log.warning(
                    "notification_channel_invalid",
                    channel=ch,
                    recipient_id=recipient_id,
                    error=str(exc),
                )

    log.info(
        "alert_notifications_sent",
        tenant_id=tenant_id,
        alert_type=alert_type,
        store_id=store_id,
        assignee_count=len(assignees),
        notification_count=len(results),
    )

    return {
        "alert_type": alert_type,
        "store_id": store_id,
        "total_notifications": len(results),
        "notifications": results,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  通知历史查询
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def get_notification_history(
    recipient_id: str,
    tenant_id: str,
    db: Any,
    *,
    limit: int = 50,
    history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """查询接收人的通知历史。

    Args:
        recipient_id: 接收人 ID
        tenant_id: 租户 ID
        db: 数据库会话
        limit: 最多返回条数
        history: 通知列表(测试注入用)

    Returns:
        {"recipient_id": str, "total": int, "items": [...]}
    """
    all_records = history if history is not None else _notification_history

    items = [r for r in all_records if r.get("recipient_id") == recipient_id and r.get("tenant_id") == tenant_id]

    # 按发送时间倒序
    items.sort(key=lambda x: x.get("sent_at", ""), reverse=True)
    items = items[:limit]

    log.info(
        "notification_history_queried",
        tenant_id=tenant_id,
        recipient_id=recipient_id,
        total=len(items),
    )

    return {
        "recipient_id": recipient_id,
        "tenant_id": tenant_id,
        "total": len(items),
        "items": items,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  辅助: 清空内存(测试用)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _reset_store() -> None:
    """清空内存存储(测试用)。"""
    _notification_history.clear()
