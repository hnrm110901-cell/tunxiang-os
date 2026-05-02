"""CDC LISTEN/NOTIFY 监听器 -- 订阅关键表变更通知

核心组件：
- CDCChangeEvent: 标准化变更事件数据模型
- CDCTriggerManager: 管理 PostgreSQL CDC 触发器函数和表级触发器
- CDCListener: 监听 PG NOTIFY 频道，解析并分发 CDCChangeEvent

架构：
  1. CDCTriggerManager 在每个表上创建 AFTER INSERT/UPDATE/DELETE 触发器
  2. 触发器调用 cdc_notify_trigger() 函数，将变更序列化为 JSON 并通过 NOTIFY 发送
  3. CDCListener 通过 asyncpg 订阅对应频道，接收通知
  4. 解析 JSON → CDCChangeEvent → 分发给注册的 handler

设计要点：
-  触发器 payload 走 PG NOTIFY（≤8000 字节），变更数据限制在 payload_columns 范围内
-  支持 Mock 模式（无 PG 连接时的测试）
-  handler 失败不影响其他 handler 和 listener 主循环
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/tunxiang",
)

# Handler 类型：接收 CDCChangeEvent，返回 None（异步）
ChangeHandler = Callable[["CDCChangeEvent"], asyncio.Future[None]]

# ──────────────────────────────────────────────────────────────────────
# 数据模型
# ──────────────────────────────────────────────────────────────────────


class CDCChangeEvent(BaseModel):
    """标准化 CDC 变更事件。

    来自 PG 触发器发出的 NOTIFY payload 解析结果。
    金额字段约定为分（整数），与 Ontology 规范一致。

    Attributes:
        table:          表名
        schema:         模式名（默认 "public"）
        operation:      操作类型（INSERT/UPDATE/DELETE）
        key_values:     主键列值字典，如 {"id": "abc-123"}
        new_data:       新行数据（INSERT/UPDATE 时的 NEW 值，DELETE 时为 None）
        old_data:       旧行数据（UPDATE/DELETE 时的 OLD 值，INSERT 时为 None）
        changed_at:     变更时间（ISO 8601 UTC）
        transaction_id: PG 事务 ID（用于因果追踪）
        tenant_id:      租户 ID（从行数据提取，用于路由/过滤）
    """

    table: str
    schema: str = "public"
    operation: str  # INSERT | UPDATE | DELETE
    key_values: dict[str, Any]
    new_data: Optional[dict[str, Any]] = None
    old_data: Optional[dict[str, Any]] = None
    changed_at: str = ""
    transaction_id: Optional[str] = None
    tenant_id: Optional[str] = None

    def model_post_init(self, _context: Any) -> None:
        """自动填充 changed_at 和提取 tenant_id。"""
        if not self.changed_at:
            self.changed_at = datetime.now(timezone.utc).isoformat()
        # 自动从 new_data 或 old_data 提取 tenant_id
        if self.tenant_id is None:
            src = self.new_data or self.old_data or {}
            self.tenant_id = src.get("tenant_id")


# ──────────────────────────────────────────────────────────────────────
# PG 触发器函数管理
# ──────────────────────────────────────────────────────────────────────

_CDC_NOTIFY_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION cdc_notify_trigger()
RETURNS trigger AS $$
DECLARE
    payload_json text;
    channel_name text;
    old_json text;
    new_json text;
    key_json text;
    txid_val text;
BEGIN
    -- 构建 channel 名：cdc_{table_name}
    channel_name := 'cdc_' || TG_TABLE_NAME;

    -- 序列化 OLD / NEW
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        old_json := row_to_json(OLD)::text;
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        new_json := row_to_json(NEW)::text;
    END IF;

    -- 提取主键值
    IF TG_OP = 'DELETE' THEN
        key_json := row_to_json(OLD)::text;
    ELSE
        key_json := row_to_json(NEW)::text;
    END IF;

    -- 获取当前事务 ID
    txid_val := txid_current()::text;

    -- 构建 payload JSON
    -- 注意：payload 必须 ≤ 8000 字节（PG NOTIFY 限制）
    payload_json := json_build_object(
        'table', TG_TABLE_NAME,
        'schema', TG_TABLE_SCHEMA,
        'operation', TG_OP,
        'key_values', key_json,
        'new_data', CASE WHEN TG_OP IN ('INSERT', 'UPDATE') THEN new_json::json ELSE NULL END,
        'old_data', CASE WHEN TG_OP IN ('UPDATE', 'DELETE') THEN old_json::json ELSE NULL END,
        'transaction_id', txid_val,
        'changed_at', now() AT TIME ZONE 'UTC'
    )::text;

    -- 如果 payload 超过 7500 字节，做字段裁剪
    IF length(payload_json) > 7500 THEN
        -- 裁剪到只保留主键信息，完整数据从表查询
        payload_json := json_build_object(
            'table', TG_TABLE_NAME,
            'schema', TG_TABLE_SCHEMA,
            'operation', TG_OP,
            'key_values', key_json,
            'new_data', NULL,
            'old_data', NULL,
            'transaction_id', txid_val,
            'changed_at', now() AT TIME ZONE 'UTC',
            'truncated', true
        )::text;
    END IF;

    PERFORM pg_notify(channel_name, payload_json);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
"""


class CDCTriggerManager:
    """管理 PostgreSQL CDC 触发器函数和表级触发器。

    职责：
    - 在 PostgreSQL 中创建 cdc_notify_trigger() 函数（如果不存在）
    - 为配置中的每个表创建 AFTER INSERT/UPDATE/DELETE 触发器
    - 支持清理（移除触发器）
    - 支持 Mock 模式（不连接 PG）

    Args:
        dsn:  PostgreSQL 连接字符串。None 使用环境变量 DATABASE_URL。
        mock: Mock 模式，不连接真实 PG。
    """

    def __init__(self, dsn: str | None = None, *, mock: bool = False) -> None:
        self._dsn = dsn or DATABASE_URL
        self._mock = mock
        self._pool: Optional[object] = None  # asyncpg.Pool
        self._created_triggers: list[tuple[str, str]] = []  # (table, trigger_name)

    async def _get_pool(self) -> object:
        """延迟获取连接池。"""
        if self._pool is None:
            import asyncpg

            self._pool = await asyncpg.create_pool(
                self._dsn,
                min_size=1,
                max_size=3,
                command_timeout=10,
            )
        return self._pool

    async def ensure_trigger_function(self) -> None:
        """创建 cdc_notify_trigger() 函数（幂等）。"""
        if self._mock:
            logger.info("cdc_trigger_manager_mock_skip_function")
            return

        pool = await self._get_pool()
        async with pool.acquire() as conn:  # type: ignore[union-attr]
            await conn.execute(_CDC_NOTIFY_FUNCTION_SQL)
        logger.info("cdc_notify_function_ensured")

    async def create_table_trigger(
        self,
        table_name: str,
        schema: str = "public",
        operations: list[str] | None = None,
    ) -> str:
        """为指定表创建 CDC 触发器（幂等）。

        Args:
            table_name:  表名，如 "orders"
            schema:      模式名，默认 "public"
            operations:  操作列表，如 ["INSERT", "UPDATE", "DELETE"]。None 表示全部。

        Returns:
            触发器名称，如 "cdc_notify_orders"。

        Raises:
            asyncpg.PostgresError: PG 执行失败
        """
        trigger_name = f"cdc_notify_{table_name}"
        ops = operations or ["INSERT", "UPDATE", "DELETE"]
        ops_str = " OR ".join(ops)

        if self._mock:
            self._created_triggers.append((table_name, trigger_name))
            logger.debug("cdc_trigger_mock_created", table=table_name, trigger=trigger_name)
            return trigger_name

        pool = await self._get_pool()
        async with pool.acquire() as conn:  # type: ignore[union-attr]
            # 使用 DO 块检查是否已存在，幂等创建
            await conn.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_trigger
                        WHERE tgname = $1
                          AND tgrelid = ($2 || '.' || $3)::regclass
                    ) THEN
                        EXECUTE format(
                            'CREATE TRIGGER %I
                             AFTER %s ON %I.%I
                             FOR EACH ROW EXECUTE FUNCTION cdc_notify_trigger()',
                            $1, $4, $2, $3
                        );
                    END IF;
                END $$;
                """,
                trigger_name,
                schema,
                table_name,
                ops_str,
            )

        self._created_triggers.append((table_name, trigger_name))
        logger.info(
            "cdc_trigger_created",
            table=f"{schema}.{table_name}",
            trigger=trigger_name,
            operations=ops,
        )
        return trigger_name

    async def create_all_triggers(self, config: "CDCConfig") -> list[str]:
        """根据配置批量创建所有表触发器。

        Args:
            config: CDCConfig 实例，包含要监听的表列表。

        Returns:
            已创建的触发器名称列表。
        """
        await self.ensure_trigger_function()
        trigger_names: list[str] = []
        for table_cfg in config.tables:
            name = await self.create_table_trigger(
                table_name=table_cfg.table_name,
                schema=table_cfg.schema,
                operations=table_cfg.operations,
            )
            trigger_names.append(name)
        return trigger_names

    async def drop_trigger(self, table_name: str, schema: str = "public") -> None:
        """移除指定表的 CDC 触发器。

        Args:
            table_name: 表名
            schema:     模式名
        """
        trigger_name = f"cdc_notify_{table_name}"
        if self._mock:
            self._created_triggers = [
                (t, tr) for t, tr in self._created_triggers if t != table_name
            ]
            return

        pool = await self._get_pool()
        async with pool.acquire() as conn:  # type: ignore[union-attr]
            await conn.execute(
                "DROP TRIGGER IF EXISTS %s ON %s.%s",
                trigger_name,
                schema,
                table_name,
            )
        logger.info("cdc_trigger_dropped", table=f"{schema}.{table_name}")

    async def drop_all_triggers(self) -> None:
        """移除所有已创建的 CDC 触发器。"""
        for table_name, trigger_name in self._created_triggers:
            await self.drop_trigger(table_name)
        self._created_triggers.clear()
        logger.info("cdc_all_triggers_dropped")

    async def close(self) -> None:
        """关闭连接池。"""
        if self._pool is not None:
            await self._pool.close()  # type: ignore[union-attr]
            self._pool = None


# ──────────────────────────────────────────────────────────────────────
# CDC 监听器
# ──────────────────────────────────────────────────────────────────────


class CDCListener:
    """PG LISTEN/NOTIFY 监听器 — 实时接收表变更通知。

    职责：
    - 订阅多个 PG NOTIFY 频道（cdc_{table_name}）
    - 接收并解析 NOTIFY payload → CDCChangeEvent
    - 分发给注册的 handler（通过 on_table 装饰器或 add_handler）
    - 支持优雅启动/停止

    用法：
        listener = CDCListener()
        listener.on_table("orders")(handle_order_change)
        await listener.start()
        # ... 运行中 ...
        await listener.stop()

    Args:
        dsn:  PostgreSQL 连接字符串。None 使用环境变量 DATABASE_URL。
        mock: Mock 模式，不连接真实 PG。
    """

    def __init__(self, dsn: str | None = None, *, mock: bool = False) -> None:
        self._dsn = dsn or DATABASE_URL
        self._mock = mock
        self._conn: Optional[object] = None  # asyncpg.Connection
        self._handlers: dict[str, list[ChangeHandler]] = {}  # table_name → [handler, ...]
        self._wildcard_handlers: list[ChangeHandler] = []  # * → [handler, ...]
        self._running = False
        self._listen_task: Optional[asyncio.Task] = None
        self._trigger_manager: Optional[CDCTriggerManager] = None
        # Mock 注入事件用
        self._mock_queue: asyncio.Queue[CDCChangeEvent] = asyncio.Queue()

    # ── Handler 注册 ──

    def on_table(self, table_name: str) -> Callable[[ChangeHandler], ChangeHandler]:
        """装饰器：注册指定表的变更处理器。

        Usage:
            @listener.on_table("orders")
            async def handle_orders(event: CDCChangeEvent):
                ...

        Args:
            table_name: 表名（与 CDC 配置中的 table_name 一致）

        Returns:
            装饰器函数
        """

        def decorator(fn: ChangeHandler) -> ChangeHandler:
            self._handlers.setdefault(table_name, []).append(fn)
            logger.info(
                "cdc_listener_handler_registered",
                table=table_name,
                handler=fn.__name__,
            )
            return fn

        return decorator

    def on_any_table(self, handler: ChangeHandler) -> ChangeHandler:
        """注册通配符处理器 — 接收所有表的变更事件。

        Usage:
            @listener.on_any_table
            async def handle_all(event: CDCChangeEvent):
                ...
        """
        self._wildcard_handlers.append(handler)
        logger.info("cdc_listener_wildcard_handler_registered", handler=handler.__name__)
        return handler

    def add_handler(self, table_name: str, handler: ChangeHandler) -> None:
        """命令式注册处理器。

        Args:
            table_name: 表名（"*" 表示所有表）
            handler:    异步处理函数
        """
        if table_name == "*":
            self._wildcard_handlers.append(handler)
        else:
            self._handlers.setdefault(table_name, []).append(handler)
        logger.info("cdc_listener_handler_added", table=table_name, handler=handler.__name__)

    # ── 生命周期 ──

    async def start(self, config: Optional["CDCConfig"] = None) -> None:
        """启动监听器。

        1. (可选) 创建 PG 触发器
        2. 连接到 PG
        3. 订阅所有配置的频道
        4. 启动后台监听循环

        Args:
            config: CDCConfig。非 None 时自动创建 PG 触发器。

        Raises:
            OSError: PG 连接失败
            asyncpg.PostgresError: PG 操作失败
        """
        if self._running:
            logger.warning("cdc_listener_already_running")
            return

        # 创建触发器（如果需要）
        if config is not None and not self._mock:
            self._trigger_manager = CDCTriggerManager(dsn=self._dsn)
            await self._trigger_manager.create_all_triggers(config)

        # 连接 PG 并订阅频道
        if not self._mock:
            import asyncpg

            self._conn = await asyncpg.connect(self._dsn, timeout=10)

            # 获取需要监听的表名（从 config 或已注册的 handler）
            tables_to_listen = self._resolve_tables(config)

            # 订阅每个频道
            for table_name in tables_to_listen:
                channel = f"cdc_{table_name}"
                await self._conn.add_listener(channel, self._on_notification)  # type: ignore[union-attr]
                logger.info("cdc_listener_subscribed", channel=channel, table=table_name)

        self._running = True
        self._listen_task = asyncio.create_task(self._listen_loop())

        listen_count = len(self._resolve_tables(config))
        logger.info(
            "cdc_listener_started",
            tables=list(listen_count),
            mock=self._mock,
        )

    async def stop(self) -> None:
        """优雅关闭监听器。

        1. 取消监听循环
        2. 取消 PG 频道订阅
        3. 断开 PG 连接
        4. 标记停止
        """
        if not self._running:
            return

        self._running = False

        # 取消监听循环
        if self._listen_task is not None:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None

        # 取消 PG 订阅并断开连接
        if self._conn is not None:
            try:
                for table_name in list(self._handlers.keys()) + ["*"]:
                    channel = f"cdc_{table_name}"
                    try:
                        await self._conn.remove_listener(channel, self._on_notification)  # type: ignore[union-attr]
                    except (OSError, RuntimeError):
                        pass
                await self._conn.close()  # type: ignore[union-attr]
            except (OSError, RuntimeError) as exc:
                logger.warning("cdc_listener_close_error", error=str(exc))
            finally:
                self._conn = None

        # 关闭触发器管理器
        if self._trigger_manager is not None:
            await self._trigger_manager.close()
            self._trigger_manager = None

        logger.info("cdc_listener_stopped")

    # ── Mock 注入（测试用）──

    async def inject_mock_event(self, event: CDCChangeEvent) -> None:
        """Mock 模式：注入模拟变更事件。

        Args:
            event: 模拟的 CDCChangeEvent

        Raises:
            RuntimeError: 非 Mock 模式下调用
        """
        if not self._mock:
            raise RuntimeError("inject_mock_event() only works in mock mode")
        await self._mock_queue.put(event)
        logger.debug(
            "cdc_listener_mock_injected",
            table=event.table,
            operation=event.operation,
        )

    # ── 内部实现 ──

    def _resolve_tables(self, config: Optional["CDCConfig"]) -> list[str]:
        """从 config 和已注册 handler 解析需要监听的表名列表。"""
        tables: set[str] = set()
        if config is not None:
            for t in config.tables:
                tables.add(t.table_name)
        tables.update(self._handlers.keys())
        if self._wildcard_handlers and config is not None:
            for t in config.tables:
                tables.add(t.table_name)
        return sorted(tables)

    def _on_notification(
        self,
        connection: object,
        pid: int,
        channel: str,
        payload: str,
    ) -> None:
        """asyncpg NOTIFY 回调（同步执行）。

        将通知分派到 asyncio 事件循环处理。

        Args:
            connection: asyncpg Connection 实例
            pid:        PG 后端进程 ID
            channel:    频道名，如 "cdc_orders"
            payload:    NOTIFY payload（JSON 字符串）
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # 无事件循环时静默丢弃
            return
        loop.create_task(self._dispatch_notification(channel, payload))

    async def _dispatch_notification(self, channel: str, payload: str) -> None:
        """解析 NOTIFY payload 并分发给 handler。

        解析失败不传播异常。
        """
        try:
            event = CDCChangeEvent.model_validate_json(payload)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error(
                "cdc_listener_deserialize_failed",
                channel=channel,
                payload_preview=payload[:200],
                error=str(exc),
            )
            return

        # 分发到表级 handler
        handlers = self._handlers.get(event.table, [])
        for handler in handlers:
            await self._invoke_handler_safely(handler, event, event.table)

        # 分发到通配符 handler
        for handler in self._wildcard_handlers:
            await self._invoke_handler_safely(handler, event, "*")

        logger.debug(
            "cdc_event_dispatched",
            table=event.table,
            operation=event.operation,
            handler_count=len(handlers) + len(self._wildcard_handlers),
        )

    async def _invoke_handler_safely(
        self, handler: ChangeHandler, event: CDCChangeEvent, scope: str
    ) -> None:
        """安全调用单个 handler，捕获并记录异常。"""
        try:
            await handler(event)
        except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
            logger.error(
                "cdc_listener_handler_failed",
                scope=scope,
                handler=handler.__name__,
                table=event.table,
                operation=event.operation,
                error=str(exc),
                exc_info=True,
            )

    async def _listen_loop(self) -> None:
        """主监听循环。

        在 Mock 模式下消费内存队列。
        在真实 PG 模式下，asyncpg 的回调已处理分发，此循环仅维持心跳。
        """
        while self._running:
            if self._mock:
                try:
                    # 非阻塞获取，最多等 0.5 秒
                    event = await asyncio.wait_for(self._mock_queue.get(), timeout=0.5)
                    # 分发到 handler
                    handlers = self._handlers.get(event.table, [])
                    for handler in handlers:
                        await self._invoke_handler_safely(handler, event, event.table)
                    for handler in self._wildcard_handlers:
                        await self._invoke_handler_safely(handler, event, "*")
                except asyncio.TimeoutError:
                    pass
            else:
                # 真实 PG 模式：保持连接活跃，检查连接状态
                if self._conn is None:
                    logger.warning("cdc_listener_connection_lost")
                    self._running = False
                    return
                await asyncio.sleep(1)
