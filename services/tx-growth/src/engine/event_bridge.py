"""Event Bridge — 业务事件 → Journey Engine 桥接

监听来自 event_bus（或 Redis Stream）的业务事件，
将事件格式化后调用 JourneyEngine.handle_event()。

监听的事件类型：
  order_completed        → trigger_event: post_order / first_visit（按 order_count）
  customer_created       → trigger_event: first_visit
  reservation_made       → trigger_event: reservation_made（暂未在 journey_definitions 中，预留）
  customer_inactive_7d   → trigger_event: 7day_inactive
  customer_inactive_30d  → trigger_event: 30day_inactive
  birthday_approaching   → trigger_event: birthday
  banquet_completed      → trigger_event: banquet_completed
  high_ltv_detected      → trigger_event: high_ltv

使用方式：
    bridge = EventBridge(journey_engine, db_session_factory)
    await bridge.start()          # 启动后台监听
    await bridge.stop()           # 关闭（lifespan 结束时调用）
"""

import asyncio
import uuid
from typing import Any, Callable

import structlog

logger = structlog.get_logger(__name__)

# 事件类型 → journey trigger_event 映射
_EVENT_TO_TRIGGER: dict[str, str] = {
    "order_completed": "post_order",
    "customer_created": "first_visit",
    "customer_inactive_7d": "7day_inactive",
    "customer_inactive_15d": "15day_inactive",
    "customer_inactive_30d": "30day_inactive",
    "birthday_approaching": "birthday",
    "banquet_completed": "banquet_completed",
    "high_ltv_detected": "high_ltv",
    "reservation_abandoned": "reservation_abandoned",
    "new_dish_launch": "new_dish_launch",
}

# first_visit 单独处理：order_count == 1 时才触发
_FIRST_VISIT_ORDER_COUNT_THRESHOLD = 1


class EventBridge:
    """
    事件桥接器：订阅业务事件，触发 Journey Engine。

    设计：
      - 使用 asyncio.Queue 作为内部缓冲（解耦事件发布和 Journey 处理）
      - db_session_factory 每次事件处理创建独立 Session（避免长连接污染）
      - 支持注册外部 event_bus handler（兼容现有 AgentEvent/EventBus 架构）
    """

    def __init__(
        self,
        journey_engine: Any,
        db_session_factory: Callable[[], Any],
        queue_size: int = 1000,
    ) -> None:
        self._engine = journey_engine
        self._db_factory = db_session_factory
        self._queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=queue_size)
        self._running = False
        self._worker_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """启动事件处理 worker。"""
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("event_bridge_started")

    async def stop(self) -> None:
        """停止事件处理 worker。"""
        self._running = False
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("event_bridge_stopped")

    # ------------------------------------------------------------------
    # 事件接收入口
    # ------------------------------------------------------------------

    async def on_event(self, event_type: str, payload: dict) -> None:
        """
        外部调用入口：将业务事件放入处理队列。

        Args:
            event_type: 原始业务事件类型（如 "order_completed"）
            payload:    事件负载（必须包含 tenant_id, customer_id）
        """
        try:
            self._queue.put_nowait({"event_type": event_type, "payload": payload})
        except asyncio.QueueFull:
            logger.warning(
                "event_bridge_queue_full",
                event_type=event_type,
                customer_id=payload.get("customer_id"),
            )

    def make_agent_event_handler(self, event_type: str) -> Callable:
        """
        生成兼容 AgentEvent/EventBus 的 handler 函数。

        使用示例：
            bus.register_handler(
                "order_completed",
                "journey_bridge",
                bridge.make_agent_event_handler("order_completed"),
            )
        """

        async def handler(agent_event: Any) -> dict:
            payload = {
                "tenant_id": agent_event.data.get("tenant_id"),
                "customer_id": agent_event.data.get("customer_id"),
                "store_id": agent_event.store_id,
                **agent_event.data,
            }
            await self.on_event(event_type, payload)
            return {"bridged": True, "event_type": event_type}

        return handler

    # ------------------------------------------------------------------
    # 内部 worker 循环
    # ------------------------------------------------------------------

    async def _worker_loop(self) -> None:
        """消费队列，逐一处理事件。"""
        while self._running:
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            try:
                await self._process_event(item["event_type"], item["payload"])
            except (OSError, RuntimeError, ValueError) as exc:
                logger.error(
                    "event_bridge_process_error",
                    event_type=item.get("event_type"),
                    error=str(exc),
                    exc_info=True,
                )
            finally:
                self._queue.task_done()

    async def _process_event(self, event_type: str, payload: dict) -> None:
        """
        处理单条事件：格式化后调用 JourneyEngine.handle_event()。

        支持 first_visit 特殊逻辑：order_completed + order_count == 1 时，
        额外触发 first_visit 旅程。
        """
        tenant_id_str = payload.get("tenant_id")
        customer_id_str = payload.get("customer_id")

        if not tenant_id_str or not customer_id_str:
            logger.warning(
                "event_bridge_missing_ids",
                event_type=event_type,
                tenant_id=tenant_id_str,
                customer_id=customer_id_str,
            )
            return

        try:
            tenant_id = uuid.UUID(str(tenant_id_str))
            customer_id = uuid.UUID(str(customer_id_str))
        except ValueError:
            logger.warning(
                "event_bridge_invalid_uuid",
                tenant_id=tenant_id_str,
                customer_id=customer_id_str,
            )
            return

        # 确定 journey trigger_event
        trigger_events: list[str] = []

        mapped = _EVENT_TO_TRIGGER.get(event_type)
        if mapped:
            trigger_events.append(mapped)

        # order_completed + 首单 → 额外触发 first_visit
        if event_type == "order_completed":
            order_count = payload.get("order_count", 0)
            if order_count == _FIRST_VISIT_ORDER_COUNT_THRESHOLD:
                if "first_visit" not in trigger_events:
                    trigger_events.append("first_visit")

        if not trigger_events:
            return

        async with self._db_factory() as db:
            for trigger_event in trigger_events:
                try:
                    result = await self._engine.handle_event(
                        tenant_id=tenant_id,
                        event_type=trigger_event,
                        customer_id=customer_id,
                        context=payload,
                        db=db,
                    )
                    await db.commit()
                    logger.info(
                        "event_bridge_processed",
                        event_type=event_type,
                        trigger_event=trigger_event,
                        customer_id=str(customer_id),
                        enrollments_created=result.get("enrollments_created", 0),
                    )
                except (OSError, RuntimeError, ValueError) as exc:
                    await db.rollback()
                    logger.error(
                        "event_bridge_handle_event_error",
                        trigger_event=trigger_event,
                        customer_id=str(customer_id),
                        error=str(exc),
                        exc_info=True,
                    )


# ---------------------------------------------------------------------------
# 全局单例（供 main.py 使用）
# ---------------------------------------------------------------------------

_bridge_instance: EventBridge | None = None


def get_event_bridge(
    journey_engine: Any | None = None,
    db_session_factory: Callable | None = None,
) -> EventBridge:
    """获取全局 EventBridge 单例（懒初始化）。"""
    global _bridge_instance
    if _bridge_instance is None:
        if journey_engine is None or db_session_factory is None:
            raise RuntimeError("EventBridge 尚未初始化，请传入 journey_engine 和 db_session_factory")
        _bridge_instance = EventBridge(journey_engine, db_session_factory)
    return _bridge_instance
