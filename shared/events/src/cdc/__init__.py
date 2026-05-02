"""shared.events.src.cdc -- 屯象OS 轻量级 CDC 实时数据管道

基于 PostgreSQL 原生 capability（LISTEN/NOTIFY）的变更数据捕获系统，用于：
- 实时物化视图更新（替代 300 秒轮询）
- 驾驶舱/告警实时数据推送
- 增量 ETL 到分析引擎

架构概览：
  ┌──────────────┐     NOTIFY       ┌───────────────┐    publish    ┌────────────────┐
  │ PostgreSQL   │ ───────────────→ │ CDCListener   │ ───────────→ │ CDCStreamWriter│
  │ (trigger)    │  cdc_{table}     │ (asyncpg)     │              │ (Redis/Memory) │
  └──────────────┘                  └───────────────┘              └───────┬────────┘
                                                                          │
                                                               ┌──────────▼─────────┐
                                                               │   CDCConsumer(s)    │
                                                               │ (per group/table)   │
                                                               └──────────┬──────────┘
                                                                          │
                                                               ┌──────────▼──────────┐
                                                               │  Materialized Views │
                                                               └─────────────────────┘

核心组件：
- CDCConfig / TableCDCConfig:    管道配置（哪些表/哪些列/哪个消费者组）
- CDCTriggerManager:            管理 PG 触发器函数和表级触发器
- CDCListener:                  监听 PG NOTIFY 频道，解析变更事件
- CDCStreamWriter:              变更事件 → Redis Stream（或内存队列）
- CDCConsumer:                  消费变更事件，调用投影器更新物化视图
- CDCPipelineMetrics:           全维度可观测性指标
- CDCPipeline:                  高层编排器（一键启动/停止完整管道）

使用方式一：快速启动（零配置，使用 DEFAULT_CDC_CONFIG）
    from shared.events.src.cdc import CDCPipeline

    pipeline = CDCPipeline()
    await pipeline.start()     # 创建触发器 + 启动监听 + 启动消费
    # ... 运行中 ...
    await pipeline.shutdown()  # 优雅关闭

使用方式二：自定义配置
    from shared.events.src.cdc import CDCPipeline, CDCConfig, TableCDCConfig

    config = CDCConfig(
        tables=[
            TableCDCConfig(table_name="orders", consumer_group="analytics"),
            ...
        ]
    )
    pipeline = CDCPipeline(config=config)
    await pipeline.start()

使用方式三：组件级（精细控制）
    from shared.events.src.cdc import CDCListener, CDCStreamWriter, CDCConsumer

    listener = CDCListener()
    writer = CDCStreamWriter()
    await writer.connect()
    ...
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import structlog

from .config import CDCMode, CDCConfig, DEFAULT_CDC_CONFIG, TableCDCConfig
from .consumer import CDCConsumer
from .listener import CDCChangeEvent, CDCListener, CDCTriggerManager
from .metrics import CDCEventMetrics, CDCLatencyMetrics, CDCMetrics, CDCPipelineMetrics
from .stream_writer import CDCStreamWriter

logger = structlog.get_logger(__name__)


class CDCPipeline:
    """CDC 数据管道 — 高层编排器。

    职责：
    - 一键启动完整 CDC 管道（触发器创建 + 监听 + 流写入 + 消费）
    - 管理所有子组件的生命周期
    - 暴露统一监控接口

    Args:
        config:         CDCConfig 实例。None 使用 DEFAULT_CDC_CONFIG。
        projectors:     table_name → projector_fn 映射。用于 CDCConsumer。
        db_dsn:         PostgreSQL 连接字符串。None 使用 DATABASE_URL 环境变量。
        redis_url:      Redis 连接 URL。None 使用 REDIS_URL 环境变量，再不可用则降级内存。
        dev_mode:       开发模式（跳过 PG 触发器创建，使用内存队列）
        enable_metrics: 启用指标收集

    生命周期：
        pipeline = CDCPipeline()
        await pipeline.start()
        # ... 管道运行中 ...
        stats = await pipeline.get_stats()
        await pipeline.shutdown()

    优雅降级策略：
        - Redis 不可用 → 自动降级到内存队列
        - PG 连接失败 → 提升 OSError（需要人工介入）
        - 触发器创建失败 → 提升异常（需要 DBA 权限）
    """

    def __init__(
        self,
        config: Optional[CDCConfig] = None,
        projectors: Optional[dict[str, Any]] = None,
        db_dsn: Optional[str] = None,
        redis_url: Optional[str] = None,
        *,
        dev_mode: bool = False,
        enable_metrics: bool = True,
    ) -> None:
        self.config = config or DEFAULT_CDC_CONFIG

        if dev_mode:
            self.config.dev_mode = True

        self._db_dsn = db_dsn
        self._redis_url = redis_url
        self._dev_mode = dev_mode
        self._enable_metrics = enable_metrics

        # 子组件（延迟初始化）
        self._trigger_manager: Optional[CDCTriggerManager] = None
        self._listener: Optional[CDCListener] = None
        self._writer: Optional[CDCStreamWriter] = None
        self._consumers: list[CDCConsumer] = []
        self._projectors = projectors or {}
        self._metrics: Optional[CDCPipelineMetrics] = None
        self._started = False

    # ── 生命周期 ──

    async def start(self) -> None:
        """启动完整 CDC 管道。

        启动顺序：
        1. 初始化指标收集器
        2. 创建 PG 触发器（非 dev 模式）
        3. 连接流写入器（Redis 或内存）
        4. 启动监听器（订阅 PG NOTIFY 频道）
        5. 启动消费者（按分组）

        Raises:
            OSError: PG 或 Redis 连接失败
            RuntimeError: 管道已启动
        """
        if self._started:
            raise RuntimeError("CDCPipeline is already started")

        if self._enable_metrics:
            self._metrics = CDCPipelineMetrics()

        logger.info(
            "cdc_pipeline_starting",
            mode=self.config.mode.value,
            tables=[t.table_name for t in self.config.tables],
            dev_mode=self._dev_mode,
        )

        # 1. 创建 PG 触发器（非 dev 模式）
        if not self._dev_mode and self.config.mode == CDCMode.NOTIFY:
            self._trigger_manager = CDCTriggerManager(dsn=self._db_dsn)
            await self._trigger_manager.create_all_triggers(self.config)

        # 2. 连接流写入器
        mock_writer = self._dev_mode or self.config.dev_mode
        self._writer = CDCStreamWriter(
            redis_url=self._redis_url,
            stream_prefix=self.config.redis_stream_key_prefix,
            mock=mock_writer,
        )
        await self._writer.connect()

        # 3. 启动监听器
        mock_listener = self._dev_mode or self.config.dev_mode
        self._listener = CDCListener(dsn=self._db_dsn, mock=mock_listener)

        # 注册默认 handler：监听器事件 → 流写入器
        await self._wire_listener_to_writer()

        await self._listener.start(config=None if mock_listener else self.config)

        # 4. 启动消费者
        await self._start_consumers()

        self._started = True
        logger.info("cdc_pipeline_started", table_count=len(self.config.tables))

    async def shutdown(self) -> None:
        """优雅关闭 CDC 管道。

        关闭顺序（逆序）：
        1. 停止消费者
        2. 停止监听器
        3. 关闭流写入器
        4. (可选) 移除 PG 触发器
        5. 导出最终指标
        """
        if not self._started:
            logger.warning("cdc_pipeline_not_started")
            return

        logger.info("cdc_pipeline_shutting_down")

        # 1. 停止消费者
        for consumer in self._consumers:
            try:
                await consumer.stop()
            except (OSError, RuntimeError) as exc:
                logger.warning("cdc_pipeline_consumer_stop_error", group=consumer.group, error=str(exc))
        self._consumers.clear()

        # 2. 停止监听器
        if self._listener is not None:
            try:
                await self._listener.stop()
            except (OSError, RuntimeError) as exc:
                logger.warning("cdc_pipeline_listener_stop_error", error=str(exc))
            self._listener = None

        # 3. 关闭流写入器
        if self._writer is not None:
            try:
                await self._writer.close()
            except (OSError, RuntimeError) as exc:
                logger.warning("cdc_pipeline_writer_close_error", error=str(exc))
            self._writer = None

        # 4. 触发器保留（不自动移除，避免数据丢失）
        if self._trigger_manager is not None:
            try:
                await self._trigger_manager.close()
            except (OSError, RuntimeError) as exc:
                logger.warning("cdc_pipeline_trigger_manager_close_error", error=str(exc))
            self._trigger_manager = None

        self._started = False

        # 5. 导出最终指标
        if self._metrics is not None:
            snapshot = self._metrics.snapshot()
            logger.info(
                "cdc_pipeline_shutdown_complete",
                events_received=snapshot["events"]["events_received"],
                events_processed=snapshot["events"]["events_processed"],
                events_failed=snapshot["events"]["events_failed"],
                success_rate=snapshot["success_rate"],
                uptime_seconds=snapshot["uptime_seconds"],
            )

    # ── 内部实现 ──

    async def _wire_listener_to_writer(self) -> None:
        """将监听器的变更事件转发到流写入器。

        为配置中的每个表注册 handler：CDCChangeEvent → CDCStreamWriter.publish()
        """
        if self._listener is None or self._writer is None:
            return

        writer = self._writer
        metrics = self._metrics

        async def forward_event(event: CDCChangeEvent) -> None:
            """内部 handler：接收变更事件 → 写入流。"""
            try:
                msg_id = await writer.publish(event)
                if metrics is not None:
                    metrics.record_event(event.table)
                logger.debug(
                    "cdc_pipeline_event_forwarded",
                    table=event.table,
                    operation=event.operation,
                    msg_id=msg_id,
                )
            except (OSError, RuntimeError) as exc:
                logger.error(
                    "cdc_pipeline_forward_failed",
                    table=event.table,
                    operation=event.operation,
                    error=str(exc),
                )
                if metrics is not None:
                    metrics.record_failed(event.table, str(exc))

        # 为每个配置的表注册转发 handler
        for table_cfg in self.config.tables:
            self._listener.add_handler(table_cfg.table_name, forward_event)

    async def _start_consumers(self) -> None:
        """按消费者分组启动消费者。

        如果提供了 projectors，按表分发给对应分组的消费者。
        """
        if not self._projectors or self._writer is None:
            logger.info("cdc_pipeline_no_projectors", skipping_consumers=True)
            return

        # 按 consumer_group 分组 projectors
        group_projectors: dict[str, dict[str, Any]] = {}
        for table_name, projector_fn in self._projectors.items():
            # 查找该表的 consumer_group
            group = self._resolve_consumer_group(table_name)
            group_projectors.setdefault(group, {})[table_name] = projector_fn

        # 每个分组创建一个 CDCConsumer
        for group, projectors in group_projectors.items():
            consumer = CDCConsumer(
                group=group,
                stream_writer=self._writer,
                projectors=projectors,
                config=self.config,
                metrics=self._metrics,
            )
            await consumer.start()
            self._consumers.append(consumer)
            logger.info(
                "cdc_pipeline_consumer_created",
                group=group,
                tables=list(projectors.keys()),
            )

    def _resolve_consumer_group(self, table_name: str) -> str:
        """查找表对应的消费者分组。"""
        for t in self.config.tables:
            if t.table_name == table_name:
                return t.consumer_group
        return "default"

    # ── 注册投影器 ──

    def register_projector(self, table_name: str, projector_fn: Any) -> None:
        """注册投影器函数（在 start() 之前调用）。

        Args:
            table_name:   表名
            projector_fn: async fn(events: list[CDCChangeEvent]) -> int
        """
        self._projectors[table_name] = projector_fn
        logger.info("cdc_pipeline_projector_registered", table=table_name)

    # ── 监控 ──

    async def get_stats(self) -> dict[str, Any]:
        """获取管道运行统计。

        Returns:
            包含所有子组件指标的字典。
        """
        # 消费者统计
        consumer_stats = []
        for c in self._consumers:
            consumer_stats.append(c.get_stats())

        # 管道级指标
        pipeline_metrics = {}
        if self._metrics is not None:
            pipeline_metrics = self._metrics.snapshot()

        return {
            "started": self._started,
            "mode": self.config.mode.value,
            "dev_mode": self._dev_mode,
            "table_count": len(self.config.tables),
            "tables": [t.table_name for t in self.config.tables],
            "consumer_count": len(self._consumers),
            "consumers": consumer_stats,
            "pipeline": pipeline_metrics,
        }

    def get_metrics(self) -> Optional[CDCPipelineMetrics]:
        """获取指标收集器（用于外部监控集成）。"""
        return self._metrics

    # ── 上下文管理器支持 ──

    async def __aenter__(self) -> "CDCPipeline":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.shutdown()


# 公共导出
__all__ = [
    # ── 配置 ──
    "CDCConfig",
    "TableCDCConfig",
    "CDCMode",
    "DEFAULT_CDC_CONFIG",
    # ── 核心组件 ──
    "CDCPipeline",
    "CDCListener",
    "CDCStreamWriter",
    "CDCConsumer",
    "CDCTriggerManager",
    # ── 数据模型 ──
    "CDCChangeEvent",
    # ── 监控指标 ──
    "CDCMetrics",
    "CDCPipelineMetrics",
    "CDCEventMetrics",
    "CDCLatencyMetrics",
]
