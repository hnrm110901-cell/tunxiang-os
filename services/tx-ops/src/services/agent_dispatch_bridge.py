"""Agent事件总线 → 自动派单桥接层

桥接 tx-agent 的 EventBus 预警事件与 tx-ops 的自动派单引擎。
当 Agent 产生预警事件时，自动转换为派单请求并派发。

事件流: Agent → EventBus.publish() → bridge handler → auto_dispatch.process_agent_alert()
"""

from __future__ import annotations

import time
from typing import Any, Callable

import structlog

log = structlog.get_logger(__name__)

# Agent 事件类型 → 派单 alert_type 映射
EVENT_TO_ALERT_TYPE: dict[str, str] = {
    "discount_violation": "discount_anomaly",
    "inventory_shortage": "stockout",
    "inventory_surplus": "margin_drop",
    "vip_arrival": "vip_arrival",
    "order_completed": "order_completed",
    "shift_handover": "shift_handover",
    "cooking_timeout": "cooking_timeout",
    "food_safety_alert": "food_safety",
    "cashier_anomaly": "cashier_anomaly",
    "margin_drop": "margin_drop",
}

# 需要触发自动派单的事件类型（非所有事件都需要派单）
DISPATCHABLE_EVENTS: set[str] = {
    "discount_violation",
    "inventory_shortage",
    "cooking_timeout",
    "food_safety_alert",
    "cashier_anomaly",
    "margin_drop",
}

# 事件严重级别映射
EVENT_SEVERITY_MAP: dict[str, str] = {
    "discount_violation": "severe",
    "inventory_shortage": "normal",
    "cooking_timeout": "severe",
    "food_safety_alert": "urgent",
    "cashier_anomaly": "severe",
    "margin_drop": "severe",
}


async def listen_agent_events(
    tenant_id: str,
    db: Any,
    event_bus: Any,
) -> dict:
    """监听 Agent 产生的预警事件并注册自动派单处理器

    Args:
        tenant_id: 租户ID
        db: 数据库会话
        event_bus: tx-agent EventBus 实例

    Returns:
        {"registered_events": [str], "handler_count": int}
    """
    log.info("listen_agent_events.start", tenant_id=tenant_id)

    registered: list[str] = []

    for event_type in DISPATCHABLE_EVENTS:
        handler = _make_dispatch_handler(tenant_id, db)
        event_bus.register_handler(
            event_type=event_type,
            agent_id=f"dispatch_bridge_{tenant_id}",
            handler=handler,
        )
        registered.append(event_type)
        log.info(
            "listen_agent_events.handler_registered",
            event_type=event_type,
            tenant_id=tenant_id,
        )

    result = {
        "registered_events": sorted(registered),
        "handler_count": len(registered),
    }
    log.info("listen_agent_events.done", tenant_id=tenant_id, **result)
    return result


def _make_dispatch_handler(tenant_id: str, db: Any) -> Callable:
    """创建闭包处理器，捕获 tenant_id 和 db"""

    async def _handler(event: Any) -> dict:
        return await route_to_dispatch(
            event=_event_to_dict(event),
            tenant_id=tenant_id,
            db=db,
        )

    return _handler


def _event_to_dict(event: Any) -> dict:
    """将 AgentEvent dataclass 转换为 dict"""
    if isinstance(event, dict):
        return event
    return {
        "event_type": getattr(event, "event_type", ""),
        "source_agent": getattr(event, "source_agent", "unknown"),
        "store_id": getattr(event, "store_id", ""),
        "data": getattr(event, "data", {}),
        "event_id": getattr(event, "event_id", ""),
        "correlation_id": getattr(event, "correlation_id", ""),
        "timestamp": getattr(event, "timestamp", time.time()),
    }


async def route_to_dispatch(
    event: dict,
    tenant_id: str,
    db: Any,
) -> dict:
    """将 Agent 事件转换为派单请求并调用 auto_dispatch

    Args:
        event: Agent 事件数据 (dict 形式)
            {
                "event_type": "discount_violation",
                "source_agent": "discount_guard",
                "store_id": "store_001",
                "data": {"summary": "...", "detail": {...}},
            }
        tenant_id: 租户ID
        db: 数据库会话

    Returns:
        {
            "dispatched": bool,
            "task_id": str | None,
            "event_type": str,
            "alert_type": str,
            "reason": str | None,
        }
    """
    event_type = event.get("event_type", "")
    store_id = event.get("store_id", "")
    source_agent = event.get("source_agent", "unknown")
    data = event.get("data", {})

    log.info(
        "route_to_dispatch.start",
        event_type=event_type,
        store_id=store_id,
        source_agent=source_agent,
        tenant_id=tenant_id,
    )

    # 检查是否为可派单事件
    if event_type not in DISPATCHABLE_EVENTS:
        log.info(
            "route_to_dispatch.skip",
            event_type=event_type,
            reason="not_dispatchable",
            tenant_id=tenant_id,
        )
        return {
            "dispatched": False,
            "task_id": None,
            "event_type": event_type,
            "alert_type": None,
            "reason": f"event_type '{event_type}' is not dispatchable",
        }

    # 转换为派单 alert 格式
    alert_type = EVENT_TO_ALERT_TYPE.get(event_type, event_type)
    severity = EVENT_SEVERITY_MAP.get(event_type, "normal")
    summary = data.get("summary", f"{source_agent} detected {event_type}")

    alert = {
        "alert_type": alert_type,
        "store_id": store_id,
        "source_agent": source_agent,
        "summary": summary,
        "detail": data.get("detail", data),
        "severity": severity,
    }

    # 调用自动派单引擎
    from ..services.auto_dispatch import process_agent_alert

    try:
        task = await process_agent_alert(
            alert=alert,
            tenant_id=tenant_id,
            db=db,
        )
        log.info(
            "route_to_dispatch.success",
            event_type=event_type,
            alert_type=alert_type,
            task_id=task.get("task_id"),
            tenant_id=tenant_id,
        )
        return {
            "dispatched": True,
            "task_id": task.get("task_id"),
            "event_type": event_type,
            "alert_type": alert_type,
            "reason": None,
        }
    except ValueError as exc:
        log.warning(
            "route_to_dispatch.failed",
            event_type=event_type,
            alert_type=alert_type,
            error=str(exc),
            tenant_id=tenant_id,
        )
        return {
            "dispatched": False,
            "task_id": None,
            "event_type": event_type,
            "alert_type": alert_type,
            "reason": str(exc),
        }


def register_agent_hooks(
    event_bus: Any,
    tenant_id: str,
    db: Any,
) -> dict:
    """注册所有 Agent 的预警回调到事件总线

    为每个可派单事件类型注册处理器，当 Agent 发布预警事件时
    自动触发 route_to_dispatch 创建派单任务。

    Args:
        event_bus: tx-agent EventBus 实例
        tenant_id: 租户ID
        db: 数据库会话

    Returns:
        {
            "hooks_registered": int,
            "event_types": [str],
            "agent_id": str,
        }
    """
    agent_id = f"dispatch_bridge_{tenant_id}"
    registered_types: list[str] = []

    log.info(
        "register_agent_hooks.start",
        tenant_id=tenant_id,
        agent_id=agent_id,
    )

    for event_type in sorted(DISPATCHABLE_EVENTS):
        handler = _make_dispatch_handler(tenant_id, db)
        event_bus.register_handler(
            event_type=event_type,
            agent_id=agent_id,
            handler=handler,
        )
        registered_types.append(event_type)

    result = {
        "hooks_registered": len(registered_types),
        "event_types": registered_types,
        "agent_id": agent_id,
    }

    log.info(
        "register_agent_hooks.done",
        tenant_id=tenant_id,
        hooks_registered=len(registered_types),
    )
    return result
