"""Sprint A2 Saga 本地 SQLite 缓冲模块。

组件：
  - buffer.py   — SagaBuffer：aiosqlite 持久化缓冲（enqueue/flush_ready/mark_*）
  - flusher.py  — SagaFlusher：后台 Worker 消费 pending 条目补发到 tx-trade

门禁：
  - 徐记海鲜 DEMO：断网 100 单零丢失
  - 4h TTL + dead letter 机制（不自动删除，等人工确认）
  - 磁盘写满降级到内存队列（不崩溃）
  - tenant_id 行级隔离 + device_id 过滤（文件层 + 行级双隔离）
  - aiosqlite 异步，不阻塞主业务

关联：CLAUDE.md §8 离线优先 / §17 Tier1 / §20 Tier1 测试标准
Flag：edge.payment.saga_buffer（默认 off，5%→50%→100% 灰度）
"""

from .buffer import (
    DEFAULT_BUFFER_PATH,
    TTL_SECONDS,
    SagaBuffer,
    SagaBufferEntry,
    SagaBufferState,
    SagaBufferStats,
)

__all__ = [
    "SagaBuffer",
    "SagaBufferEntry",
    "SagaBufferStats",
    "SagaBufferState",
    "DEFAULT_BUFFER_PATH",
    "TTL_SECONDS",
]
