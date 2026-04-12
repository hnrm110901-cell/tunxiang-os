"""
费控事件消费者服务
订阅来自其他微服务的业务事件，路由到对应的 Agent 处理函数。

订阅的事件：
  ops.daily_close.completed    → A1备用金守护（日结对账）
  org.employee.departed        → A1备用金守护（账户冻结）
  supply.purchase_order.goods_received → 采购付款联动（P1实现）
  trade.revenue.daily_summary  → A4预算预警（P1实现）

设计原则：
  - 幂等性：同一事件重复消费只处理一次（基于 event_id 去重）
  - 快速响应：事件接收即返回 200，实际处理异步执行
  - 失败隔离：单个事件处理失败不影响其他事件
  - 审计日志：每条事件消费记录都写日志
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import date
from typing import Any
from uuid import UUID

import structlog

log = structlog.get_logger(__name__)

# 内存幂等 set（LRU，最多保存最近1000条）
_processed_events: OrderedDict[str, bool] = OrderedDict()
MAX_IDEMPOTENCY_CACHE = 1000


def _is_duplicate(event_id: str) -> bool:
    """检查事件是否已处理（内存LRU幂等）。

    同一 event_id 的事件只处理一次。服务重启后缓存清空，
    可接受少量重复处理（P1升级为Redis持久化幂等）。
    """
    if event_id in _processed_events:
        return True
    _processed_events[event_id] = True
    if len(_processed_events) > MAX_IDEMPOTENCY_CACHE:
        _processed_events.popitem(last=False)
    return False


async def process_event(
    db_factory: Any,
    event_type: str,
    event_id: str,
    tenant_id: str,
    payload: dict[str, Any],
) -> None:
    """事件处理主路由。

    db_factory: 异步数据库 session 工厂（后台任务需要独立 session）。
    支持 TenantSession(tenant_id) 协议（async context manager）。
    """
    if _is_duplicate(event_id):
        log.info(
            "event_duplicate_skipped",
            event_id=event_id,
            event_type=event_type,
        )
        return

    log.info(
        "event_processing",
        event_id=event_id,
        event_type=event_type,
        tenant_id=tenant_id,
    )

    try:
        async with db_factory(tenant_id) as db:
            if event_type == "ops.daily_close.completed":
                await _handle_daily_close(db, UUID(tenant_id), payload)

            elif event_type == "org.employee.departed":
                await _handle_employee_departure(db, UUID(tenant_id), payload)

            elif event_type == "supply.purchase_order.goods_received":
                # P1实现：采购付款联动
                log.info(
                    "event_deferred",
                    event_type=event_type,
                    reason="P1_not_implemented",
                )

            elif event_type == "trade.revenue.daily_summary":
                # P1实现：A4预算动态调整
                log.info(
                    "event_deferred",
                    event_type=event_type,
                    reason="P1_not_implemented",
                )

            else:
                log.warning(
                    "event_unknown_type",
                    event_type=event_type,
                    event_id=event_id,
                )

    except (ValueError, KeyError) as exc:
        log.error(
            "event_processing_failed",
            event_id=event_id,
            event_type=event_type,
            error=str(exc),
            exc_info=True,
        )
        # 不向上抛出：事件处理失败不应影响其他业务

    except Exception as exc:  # noqa: BLE001 — 最外层兜底，防止后台任务静默崩溃
        log.error(
            "event_processing_unexpected_error",
            event_id=event_id,
            event_type=event_type,
            error=str(exc),
            exc_info=True,
        )


async def _handle_daily_close(
    db: Any,
    tenant_id: UUID,
    payload: dict[str, Any],
) -> None:
    """处理 ops.daily_close.completed 事件。

    payload 预期字段：
      store_id              (str UUID, 必填)
      pos_session_id        (str, 可选)
      close_date            (str ISO date, 可选，默认今日)
      pos_petty_cash_declared (int 分, 可选，默认 0)
    """
    try:
        from src.agents.a1_petty_cash_guardian import run as a1_run
    except ImportError:
        log.warning(
            "a1_agent_not_available",
            trigger="pos_daily_close",
            note="A1 agent not yet implemented; skipping.",
        )
        return

    store_id = UUID(payload["store_id"])
    pos_session_id = payload.get("pos_session_id", "")
    close_date_str = payload.get("close_date", str(date.today()))
    close_date = date.fromisoformat(close_date_str)
    pos_declared = int(payload.get("pos_petty_cash_declared", 0))

    result = await a1_run(
        db=db,
        tenant_id=tenant_id,
        trigger="pos_daily_close",
        payload={
            "store_id": store_id,
            "pos_session_id": pos_session_id,
            "pos_declared_petty_cash": pos_declared,
            "close_date": close_date,
        },
    )
    log.info(
        "daily_close_handled",
        store_id=str(store_id),
        tenant_id=str(tenant_id),
        result=result,
    )


async def _handle_employee_departure(
    db: Any,
    tenant_id: UUID,
    payload: dict[str, Any],
) -> None:
    """处理 org.employee.departed 事件。

    payload 预期字段：
      employee_id     (str UUID, 必填)
      store_id        (str UUID, 可选，无则用零值 UUID)
      departure_date  (str ISO date, 可选，默认今日)
    """
    try:
        from src.agents.a1_petty_cash_guardian import run as a1_run
    except ImportError:
        log.warning(
            "a1_agent_not_available",
            trigger="employee_departure",
            note="A1 agent not yet implemented; skipping.",
        )
        return

    employee_id = UUID(payload["employee_id"])
    store_id = UUID(
        payload.get("store_id", "00000000-0000-0000-0000-000000000000")
    )
    departure_date_str = payload.get("departure_date", str(date.today()))
    departure_date = date.fromisoformat(departure_date_str)

    result = await a1_run(
        db=db,
        tenant_id=tenant_id,
        trigger="employee_departure",
        payload={
            "store_id": store_id,
            "employee_id": employee_id,
            "departure_date": departure_date,
        },
    )
    log.info(
        "employee_departure_handled",
        employee_id=str(employee_id),
        tenant_id=str(tenant_id),
        result=result,
    )
