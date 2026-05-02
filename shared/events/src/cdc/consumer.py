"""CDC 消费者 -- 消费 CDC 事件流，增量更新物化视图

职责：
- 从 Redis Stream（或内存队列）消费 CDCChangeEvent
- 按消费者分组（consumer_group）分发事件
- 调用对应的 projector 函数增量更新物化视图
- 记录消费偏移量（checkpoint），支持断点续传
- 暴露监控指标（CDCPipelineMetrics）

架构：
  Redis Stream → CDCConsumer._consume_loop() → table_projector(event) → 物化视图

消费者分组规则：
- analytics:  orders / order_items / member_transactions → 驾驶舱/报表
- finance:    payments → 日结/对账
- supply:     inventory → 库存预警
- default:    未指定分组的表

设计要点：
- 每种表一个投影器函数（signature: async fn(events: list[CDCChangeEvent]) -> int）
- 投影器失败不阻塞其他表的事件处理
- checkpoint 每 100 条事件或 10 秒保存一次
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Callable, Optional

import structlog

logger = structlog.get_logger(__name__)

DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/tunxiang",
)

# 投影器函数类型：接收事件列表，返回成功处理的事件数
ProjectorFn = Callable[..., asyncio.Future[int]]


class CDCConsumer:
    """CDC 消费者 -- 消费变更事件并更新物化视图。

    按消费者分组订阅事件：
    - analytics: orders / order_items / member_transactions
    - finance:   payments
    - supply:    inventory
    - default:   未指定分组

    Args:
        group:          消费者分组名称
        stream_writer:  CDCStreamWriter 实例（用于消费内存队列/Redis）
        projectors:     table_name → projector_fn 映射
        config:         CDCConfig（用于确定哪些表属于本分组）
        metrics:        CDCPipelineMetrics 实例（监控）

    Usage:
        consumer = CDCConsumer(
            group="analytics",
            stream_writer=writer,
            projectors={"orders": handle_order_changes},
            config=config,
        )
        await consumer.start()
        # ... 运行中 ...
        await consumer.stop()
    """

    def __init__(
        self,
        group: str,
        stream_writer: "CDCStreamWriter",
        projectors: dict[str, ProjectorFn],
        config: Optional["CDCConfig"] = None,
        metrics: Optional["CDCPipelineMetrics"] = None,
    ) -> None:
        self.group = group
        self._writer = stream_writer
        self._projectors = projectors  # table_name → projector_fn
        self._config = config
        self._running = False
        self._consume_tasks: list[asyncio.Task] = []

        # 监控指标
        if metrics is not None:
            self._metrics = metrics
        else:
            from .metrics import CDCPipelineMetrics

            self._metrics = CDCPipelineMetrics()

        # 消费偏移量: table_name → last_message_id
        self._offsets: dict[str, str] = {}
        # 断点续传 offsets: table_name → last_consumed_message_id
        self._checkpoint_file: Optional[str] = None

        # 每 100 条或 10 秒保存一次 checkpoint
        self._checkpoint_interval: int = 100
        self._checkpoint_seconds: float = 10.0
        self._events_since_checkpoint: int = 0
        self._last_checkpoint_time: float = time.monotonic()

    # ── 生命周期 ──

    async def start(self) -> None:
        """启动消费者。

        为每个 projector 表启动独立的消费协程。
        """
        if self._running:
            logger.warning("cdc_consumer_already_running", group=self.group)
            return

        self._running = True
        tables = self._resolve_tables()

        for table_name in tables:
            task = asyncio.create_task(self._consume_loop(table_name))
            self._consume_tasks.append(task)

        logger.info(
            "cdc_consumer_started",
            group=self.group,
            tables=tables,
            projector_count=len(self._projectors),
        )

    async def stop(self) -> None:
        """优雅停止消费者。

        1. 停止所有消费协程
        2. 保存 checkpoint
        3. 记录最终指标
        """
        if not self._running:
            return

        self._running = False

        # 取消所有消费协程
        for task in self._consume_tasks:
            task.cancel()
        await asyncio.gather(*self._consume_tasks, return_exceptions=True)
        self._consume_tasks.clear()

        # 保存最终 checkpoint
        await self._save_checkpoint()

        # 记录终止指标
        snapshot = self._metrics.snapshot()
        logger.info(
            "cdc_consumer_stopped",
            group=self.group,
            events_processed=snapshot["events"]["events_processed"],
            events_failed=snapshot["events"]["events_failed"],
            uptime_seconds=snapshot["uptime_seconds"],
        )

    # ── 配置 ──

    def set_checkpoint_file(self, path: str) -> None:
        """设置 checkpoint 文件路径（用于断点续传）。

        Args:
            path: 文件路径，如 "/var/lib/tunxiang/cdc_checkpoints/analytics.json"
        """
        self._checkpoint_file = path

    async def _save_checkpoint(self) -> None:
        """持久化消费偏移量到 checkpoint 文件。"""
        if self._checkpoint_file is None or not self._offsets:
            return
        try:
            checkpoint_data = {
                "group": self.group,
                "offsets": dict(self._offsets),
                "saved_at": int(time.time()),
            }
            os.makedirs(os.path.dirname(self._checkpoint_file), exist_ok=True)
            with open(self._checkpoint_file, "w") as f:
                json.dump(checkpoint_data, f, indent=2)
            logger.debug(
                "cdc_checkpoint_saved",
                group=self.group,
                offsets=self._offsets,
            )
        except (OSError, ValueError) as exc:
            logger.error(
                "cdc_checkpoint_save_failed",
                group=self.group,
                error=str(exc),
            )
        self._events_since_checkpoint = 0
        self._last_checkpoint_time = time.monotonic()

    async def load_checkpoint(self) -> dict[str, str]:
        """从 checkpoint 文件恢复消费偏移量。

        Returns:
            {table_name: last_message_id} 字典
        """
        if self._checkpoint_file is None:
            return {}
        try:
            with open(self._checkpoint_file) as f:
                data = json.load(f)
            self._offsets = data.get("offsets", {})
            logger.info(
                "cdc_checkpoint_loaded",
                group=self.group,
                offset_count=len(self._offsets),
            )
            return dict(self._offsets)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logger.warning(
                "cdc_checkpoint_load_failed",
                group=self.group,
                error=str(exc),
            )
            return {}

    # ── 消费循环 ──

    def _resolve_tables(self) -> list[str]:
        """解析本消费者分组处理的表列表。"""
        tables: list[str] = []
        if self._config is not None:
            for t in self._config.tables:
                if t.consumer_group == self.group and t.table_name in self._projectors:
                    tables.append(t.table_name)
        # 如果 config 未提供，消费所有已注册 projector 的表
        if not tables:
            tables = list(self._projectors.keys())
        return tables

    async def _consume_loop(self, table_name: str) -> None:
        """单表消费循环。

        从内存队列或 Redis Stream 拉取事件并投喂给投影器。

        Args:
            table_name: 要消费的表名
        """
        logger.info("cdc_consume_loop_started", group=self.group, table=table_name)
        batch: list["CDCChangeEvent"] = []
        projector = self._projectors[table_name]
        config = self._get_table_config(table_name)
        batch_size = config.batch_size if config else 100

        while self._running:
            try:
                # 从内存队列拉取事件
                stream_key = f"{self._writer._stream_prefix}:{table_name}:changes"
                raw_events = self._writer._in_memory.get(stream_key)
                if raw_events:
                    # 批量取出
                    to_process = []
                    while raw_events and len(to_process) < batch_size:
                        raw = raw_events.popleft()
                        to_process.append(raw)

                    for raw in to_process:
                        try:
                            event = self._parse_event(raw["data"])
                            if event is not None:
                                batch.append(event)
                        except (json.JSONDecodeError, ValueError, KeyError) as exc:
                            logger.error(
                                "cdc_consumer_parse_failed",
                                table=table_name,
                                error=str(exc),
                            )
                            self._metrics.record_failed(table_name, str(exc))

                # 处理积累的批次
                if batch:
                    await self._process_batch(table_name, batch, projector)
                    batch = []

                # 检查是否需要保存 checkpoint
                if self._events_since_checkpoint >= self._checkpoint_interval:
                    await self._save_checkpoint()
                elif time.monotonic() - self._last_checkpoint_time > self._checkpoint_seconds:
                    await self._save_checkpoint()

                await asyncio.sleep(self._config.poll_interval_seconds if self._config else 1.0)

            except asyncio.CancelledError:
                # 协程被取消，处理剩余批次
                if batch:
                    await self._process_batch(table_name, batch, projector)
                await self._save_checkpoint()
                logger.info("cdc_consume_loop_cancelled", group=self.group, table=table_name)
                return

            except (OSError, RuntimeError, ValueError) as exc:
                logger.error(
                    "cdc_consume_loop_error",
                    group=self.group,
                    table=table_name,
                    error=str(exc),
                    exc_info=True,
                )
                await asyncio.sleep(1.0)

    async def _process_batch(
        self,
        table_name: str,
        batch: list["CDCChangeEvent"],
        projector: ProjectorFn,
    ) -> None:
        """处理一批事件：调用投影器，更新指标。

        Args:
            table_name: 表名
            batch:      CDCChangeEvent 列表
            projector:  投影器函数
        """
        start_time = time.monotonic()
        try:
            count = await projector(batch)
            self._metrics.events.events_processed += count
            self._metrics.record_processed(table_name)
            for event in batch:
                self._metrics.latency.record_e2e(
                    (time.monotonic() - start_time) * 1000 / max(len(batch), 1)
                )
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            error_msg = str(exc)
            self._metrics.events_failed += 1
            self._metrics.record_failed(table_name, error_msg)
            logger.error(
                "cdc_projector_failed",
                group=self.group,
                table=table_name,
                batch_size=len(batch),
                error=error_msg,
                exc_info=True,
            )

        self._events_since_checkpoint += len(batch)

        # 更新最后事件偏移量
        for event in batch:
            self._metrics.set_last_event_at(event.changed_at)

    @staticmethod
    def _parse_event(raw_data: str) -> Optional["CDCChangeEvent"]:
        """从 Redis/memory payload 反序列化 CDCChangeEvent。"""
        from .listener import CDCChangeEvent

        return CDCChangeEvent.model_validate_json(raw_data)

    def _get_table_config(self, table_name: str) -> Optional["TableCDCConfig"]:
        """获取指定表的 CDC 配置片段。"""
        if self._config is None:
            return None
        for t in self._config.tables:
            if t.table_name == table_name:
                return t
        return None

    # ── 指标暴露 ──

    @property
    def metrics(self) -> "CDCPipelineMetrics":
        """获取当前消费者的指标收集器。"""
        return self._metrics

    def get_stats(self) -> dict[str, Any]:
        """获取消费者统计信息。"""
        return {
            "group": self.group,
            "running": self._running,
            "tables": self._resolve_tables(),
            "offsets": dict(self._offsets),
            "events_since_checkpoint": self._events_since_checkpoint,
            "metrics": self._metrics.snapshot(),
        }
