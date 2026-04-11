"""Event Bus — 事件驱动 Agent 协同网格（双轨并行：内存 + Redis Streams）

替代 MemoryBus 的被动查询模式，改为主动事件驱动：
- Agent 发布事件 → EventBus 触发所有注册的处理器（内存，毫秒级）
- 同时异步持久化到 Redis Streams（agent_events），实现跨进程、跨服务可见性
- 支持事件链路追踪（correlation_id）
- Redis 不可用时降级处理：只记录警告，不影响内存触发的主流程

升级记录：
- v2（2026-04-01）：新增 Redis Streams 持久化（双轨并行），AgentEvent 增加 tenant_id 字段
"""
import asyncio
import json
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class AgentEvent:
    """Agent 事件"""
    event_type: str
    source_agent: str
    store_id: str
    data: dict = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    tenant_id: Optional[str] = None  # 可选，RLS 租户隔离用


class EventBus:
    """事件驱动 Agent 网格

    - register_handler: 注册 event_type → (agent_id, handler) 映射
    - publish: 发布事件，触发内存处理器（毫秒级），并异步持久化到 Redis Streams
    - get_event_chain: 按 correlation_id 追踪事件链路
    - get_stream: 查询某类事件的最近 N 条
    - get_redis / close_redis: Redis 单例连接管理
    """

    _redis: Optional[Any] = None  # Redis 单例连接（类变量，跨实例共享）

    def __init__(self, max_per_stream: int = 1000):
        self._streams: dict[str, list[AgentEvent]] = defaultdict(list)
        self._handlers: dict[str, list[tuple[str, Callable]]] = defaultdict(list)
        self._max_per_stream = max_per_stream

    @classmethod
    async def get_redis(cls) -> Any:
        """获取（或创建）Redis 连接单例"""
        import os

        import redis.asyncio as aioredis

        if cls._redis is None:
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            cls._redis = await aioredis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=3,
            )
        return cls._redis

    @classmethod
    async def close_redis(cls) -> None:
        """关闭 Redis 连接（服务关闭时调用）"""
        if cls._redis is not None:
            await cls._redis.aclose()
            cls._redis = None
            logger.info("event_bus_redis_closed")

    def register_handler(
        self,
        event_type: str,
        agent_id: str,
        handler: Callable,
    ) -> None:
        """注册事件处理器

        Args:
            event_type: 事件类型
            agent_id: 处理器所属 Agent ID
            handler: 处理函数，接收 AgentEvent 返回 dict
        """
        self._handlers[event_type].append((agent_id, handler))
        logger.info(
            "handler_registered",
            event_type=event_type,
            agent_id=agent_id,
        )

    async def publish(self, event: AgentEvent) -> list[dict]:
        """发布事件 -> 触发所有注册的处理器 -> 返回处理结果

        Args:
            event: 待发布的事件

        Returns:
            各处理器的执行结果列表
        """
        # 存入事件流
        stream = self._streams[event.event_type]
        stream.append(event)
        if len(stream) > self._max_per_stream:
            self._streams[event.event_type] = stream[-self._max_per_stream:]

        logger.info(
            "event_published",
            event_id=event.event_id,
            event_type=event.event_type,
            source_agent=event.source_agent,
            store_id=event.store_id,
            correlation_id=event.correlation_id,
        )

        # 触发所有处理器
        results: list[dict] = []
        handlers = self._handlers.get(event.event_type, [])

        for agent_id, handler in handlers:
            try:
                # 支持 sync 和 async handler
                if asyncio.iscoroutinefunction(handler):
                    result = await handler(event)
                else:
                    result = handler(event)

                result_entry = {
                    "agent_id": agent_id,
                    "event_id": event.event_id,
                    "success": True,
                    "result": result,
                }
                results.append(result_entry)
                logger.info(
                    "handler_executed",
                    event_id=event.event_id,
                    agent_id=agent_id,
                    success=True,
                )
            except Exception as e:  # 事件分发兜底：单个handler异常不能阻塞其他handler执行
                result_entry = {
                    "agent_id": agent_id,
                    "event_id": event.event_id,
                    "success": False,
                    "error": str(e),
                }
                results.append(result_entry)
                logger.error(
                    "handler_failed",
                    event_id=event.event_id,
                    agent_id=agent_id,
                    error=str(e),
                    exc_info=True,
                )

        # 异步持久化到 Redis Streams（不阻塞，不影响返回值）
        asyncio.create_task(self._persist_to_redis(event))

        return results

    async def _persist_to_redis(self, event: AgentEvent) -> None:
        """将事件异步写入 Redis Stream（agent_events）。

        失败时只记录警告，不抛异常，不影响内存触发的主流程。
        仅捕获 OSError（网络连接失败）和 RuntimeError（协议层异常）。
        """
        try:
            redis = await self.get_redis()

            fields: dict[str, str] = {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "source_agent": event.source_agent,
                "store_id": event.store_id,
                "tenant_id": event.tenant_id or "",
                "data": json.dumps(event.data, ensure_ascii=False),
                "correlation_id": event.correlation_id,
                "timestamp": str(event.timestamp),
            }

            entry_id: str = await redis.xadd(
                "agent_events",
                fields,
                maxlen=50_000,
                approximate=True,
            )

            logger.debug(
                "event_persisted_to_redis",
                event_id=event.event_id,
                event_type=event.event_type,
                entry_id=entry_id,
            )

        except OSError as exc:
            # Redis 连接失败（网络问题）— 降级，不影响主业务
            logger.warning(
                "event_redis_persist_failed_os",
                event_id=event.event_id,
                event_type=event.event_type,
                error=str(exc),
            )
            EventBus._redis = None  # 重置连接，下次重试
        except RuntimeError as exc:
            # Redis 协议层异常（如连接池耗尽）
            logger.warning(
                "event_redis_persist_failed_runtime",
                event_id=event.event_id,
                event_type=event.event_type,
                error=str(exc),
            )

    async def get_event_chain(self, correlation_id: str) -> list[AgentEvent]:
        """获取事件链路（一个 correlation_id 关联的所有事件）

        Args:
            correlation_id: 事件关联 ID

        Returns:
            按时间排序的事件列表
        """
        chain: list[AgentEvent] = []
        for events in self._streams.values():
            for event in events:
                if event.correlation_id == correlation_id:
                    chain.append(event)
        chain.sort(key=lambda e: e.timestamp)
        return chain

    def get_stream(
        self,
        event_type: str,
        limit: int = 100,
    ) -> list[AgentEvent]:
        """获取事件流（最近 N 条）

        Args:
            event_type: 事件类型
            limit: 最多返回条数

        Returns:
            按时间倒序的事件列表
        """
        events = self._streams.get(event_type, [])
        return list(reversed(events[-limit:]))

    def get_handler_count(self, event_type: str) -> int:
        """获取某事件类型的处理器数量"""
        return len(self._handlers.get(event_type, []))

    def get_all_event_types(self) -> list[str]:
        """获取所有已注册的事件类型"""
        return list(set(list(self._handlers.keys()) + list(self._streams.keys())))

    def clear(self) -> None:
        """清空所有事件和处理器（测试用）"""
        self._streams.clear()
        self._handlers.clear()


# ─── 预注册事件处理器映射 ───

DEFAULT_EVENT_HANDLERS: dict[str, list[tuple[str, str]]] = {
    "inventory_surplus": [
        ("smart_menu", "adjust_push_recommendations"),
        ("private_ops", "trigger_surplus_promotion"),
    ],
    "inventory_shortage": [
        ("smart_menu", "reduce_shortage_items"),
        ("serve_dispatch", "alert_kitchen_shortage"),
    ],
    "discount_violation": [
        ("discount_guard", "log_violation"),
        ("private_ops", "notify_store_manager"),
    ],
    "vip_arrival": [
        ("member_insight", "load_vip_preferences"),
        ("serve_dispatch", "assign_senior_waiter"),
    ],
    "daily_plan_generated": [
        ("private_ops", "notify_manager_for_approval"),
    ],
    "order_completed": [
        ("finance_audit", "update_daily_revenue"),
        ("inventory_alert", "deduct_ingredients"),
    ],
    "shift_handover": [
        ("finance_audit", "generate_shift_summary"),
        ("store_inspect", "trigger_shift_checklist"),
    ],

    # ── 交易域事件驱动 ────────────────────────────────────────────────
    "trade.order.paid": [
        ("member_insight", "update_customer_rfm"),      # 更新会员RFM分层
        ("private_ops", "check_journey_trigger"),        # 检查私域旅程触发条件
        ("finance_audit", "update_daily_revenue"),       # 更新日营收
    ],
    "trade.discount.blocked": [
        ("discount_guard", "log_violation"),             # 记录折扣违规
        ("finance_audit", "flag_discount_anomaly"),      # 财务稽核标记
    ],
    "trade.daily_settlement.completed": [
        ("finance_audit", "generate_shift_summary"),     # 生成班次财务摘要
        ("store_inspect", "trigger_shift_checklist"),    # 触发班次质检清单
    ],

    # ── 供应链域事件驱动 ──────────────────────────────────────────────
    "supply.stock.low": [
        ("inventory_alert", "assess_shortage_severity"), # 评估库存短缺严重程度
        ("smart_menu", "suggest_alternatives"),          # 推荐替代菜品
    ],
    "supply.stock.zero": [
        ("smart_menu", "mark_sold_out"),                 # 标记售罄
        ("inventory_alert", "urgent_reorder_notify"),    # 紧急补货通知
    ],
    "supply.ingredient.expiring": [
        ("inventory_alert", "plan_usage"),               # 制定快速用料计划
        ("smart_menu", "push_expiry_specials"),          # 推荐到期食材特价菜
    ],
    "supply.receiving.variance": [
        ("finance_audit", "flag_receiving_variance"),    # 财务稽核标记收货差异
    ],

    # ── 组织人事域事件驱动 ────────────────────────────────────────────
    "org.attendance.late": [
        ("store_inspect", "log_attendance_issue"),       # 记录考勤问题
    ],
    "org.attendance.exception": [
        ("store_inspect", "create_followup_task"),       # 创建跟进任务
    ],
    "org.approval.completed": [
        ("finance_audit", "process_approval_result"),    # 审批完成后财务联动
    ],

    # ── 财务域事件驱动 ────────────────────────────────────────────────
    "finance.cost_rate.exceeded": [
        ("finance_audit", "root_cause_analysis"),        # 成本率超标原因分析
        ("smart_menu", "flag_high_cost_dishes"),         # 标记高成本菜品
    ],
    "finance.daily_pl.generated": [
        ("finance_audit", "check_pl_anomaly"),           # P&L异常检测
    ],

    # ── 千人千面Agent事件驱动 ────────────────────────────────────────
    "member.profile_updated": [
        ("personalization", "generate_batch_reasons"),    # 用户画像更新→重新生成推荐理由
    ],
    "trade.order.paid": [
        ("personalization", "generate_reorder_prompt"),   # 消费后→生成复购提醒文案
    ],

    # ── 排位Agent事件驱动 ────────────────────────────────────────────
    "trade.table.freed": [
        ("queue_seating", "auto_call_next"),              # 桌台空出自动叫号
    ],
    "trade.queue.ticket_created": [
        ("queue_seating", "predict_wait_time"),           # 新排队预测等位时间
    ],
    "trade.reservation.no_show": [
        ("queue_seating", "handle_no_show_release"),      # 爽约释放桌位
    ],

    # ── 后厨超时Agent事件驱动 ────────────────────────────────────────
    "kds.item.overtime_warning": [
        ("kitchen_overtime", "analyze_overtime_cause"),    # 出餐超时原因分析
        ("kitchen_overtime", "auto_rush_notify"),          # 自动催菜
    ],
    "kds.scan.scheduled": [
        ("kitchen_overtime", "scan_overtime_items"),       # 定时扫描超时项
    ],

    # ── 收银异常Agent事件驱动 ────────────────────────────────────────
    "trade.order.reverse_settled": [
        ("billing_anomaly", "detect_reverse_settle_anomaly"),  # 反结账异常检测
    ],
    "trade.payment.confirmed": [
        ("billing_anomaly", "detect_payment_anomaly"),    # 支付异常检测
    ],
    "trade.shift.closed": [
        ("billing_anomaly", "analyze_shift_variance"),    # 班结现金差异
    ],

    # ── 闭店Agent事件驱动 ────────────────────────────────────────────
    "ops.closing_time.approaching": [
        ("closing_ops", "pre_closing_check"),             # 闭店前30分钟预检
        ("closing_ops", "remind_unsettled_orders"),       # 未结单提醒
    ],
    "ops.checklist.closing_submitted": [
        ("closing_ops", "check_checklist_status"),        # 检查单提交追踪
    ],
    "ops.daily_settlement.completed": [
        ("closing_ops", "validate_daily_settlement"),     # 日结数据校验
        ("closing_ops", "generate_closing_report"),       # 生成闭店报告
    ],
}


def create_default_event_bus() -> EventBus:
    """创建带预注册处理器的 EventBus（使用占位 handler）

    生产环境中，handler 应替换为实际的 Agent 方法调用。
    """
    bus = EventBus()
    for event_type, handlers in DEFAULT_EVENT_HANDLERS.items():
        for agent_id, action_name in handlers:
            # 占位处理器：记录事件并返回动作名
            def make_handler(aid: str, act: str) -> Callable:
                def handler(event: AgentEvent) -> dict:
                    return {
                        "agent_id": aid,
                        "action": act,
                        "event_type": event.event_type,
                        "store_id": event.store_id,
                        "processed": True,
                    }
                return handler

            bus.register_handler(event_type, agent_id, make_handler(agent_id, action_name))
    return bus
