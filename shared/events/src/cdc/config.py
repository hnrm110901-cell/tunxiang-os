"""CDC 配置 -- 管理哪些表需要变更捕获

定义 CDC（Change Data Capture）数据管道的完整配置模型：
- CDCMode: 变更捕获模式（NOTIFY / POLLING / WAL）
- TableCDCConfig: 单表的 CDC 配置（操作类型 / 键列 / 消费者分组）
- CDCConfig: 管道级配置（模式 / 表列表 / Redis Stream 前缀 / 批量参数）
- DEFAULT_CDC_CONFIG: 屯象OS 生产环境默认配置
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class CDCMode(str, Enum):
    """变更捕获模式。

    NOTIFY:  PG LISTEN/NOTIFY 触发器推送（推荐，亚秒级延迟）
    POLLING: 定时轮询 PG（回退方案，延迟~1秒）
    WAL:     WAL-based 日志解码（未来，依赖 wal2json 插件）
    """

    NOTIFY = "notify"
    POLLING = "polling"
    WAL = "wal"


class TableCDCConfig(BaseModel):
    """单表 CDC 配置。

    定义需要对哪个表捕获哪些操作的哪些列，以及由哪个消费者分组处理。

    Attributes:
        table_name:      表名（如 "orders"）
        schema:          模式名（默认 "public"）
        operations:      捕获的操作类型列表（INSERT/UPDATE/DELETE）
        key_columns:     主键列列表（用于识别变更实体）
        payload_columns: 捕获的列列表，["*"] 表示全部列
        batch_size:      每批处理的事件数上限
        consumer_group:  消费者分组名称（决定哪个消费者处理）
    """

    table_name: str
    schema: str = "public"
    operations: list[str] = Field(default_factory=lambda: ["INSERT", "UPDATE", "DELETE"])
    key_columns: list[str] = Field(default_factory=lambda: ["id"])
    payload_columns: list[str] = Field(default_factory=lambda: ["*"])
    batch_size: int = Field(default=100, ge=1, le=10000)
    consumer_group: str = "default"


class CDCConfig(BaseModel):
    """CDC 管道配置。

    定义整个 CDC 管道的运行参数。

    Attributes:
        mode:                     变更捕获模式（默认 NOTIFY）
        tables:                   需要捕获的表配置列表
        redis_stream_key_prefix:  Redis Stream key 前缀
        max_batch_size:           单批最大事件数
        consumer_timeout_ms:      消费者拉取超时（毫秒）
        poll_interval_seconds:    轮询间隔（POLLING 模式，秒）
        notify_channel_prefix:    PG NOTIFY 频道名前缀
        dev_mode:                 开发模式（in-memory queue，不连 Redis）
    """

    mode: CDCMode = CDCMode.NOTIFY
    tables: list[TableCDCConfig] = Field(default_factory=list)
    redis_stream_key_prefix: str = "cdc"
    max_batch_size: int = Field(default=1000, ge=1, le=50000)
    consumer_timeout_ms: int = Field(default=5000, ge=100, le=60000)
    poll_interval_seconds: float = Field(default=1.0, ge=0.1, le=60.0)
    notify_channel_prefix: str = "cdc"
    dev_mode: bool = False


# ──────────────────────────────────────────────────────────────────────
# 屯象OS 生产环境默认 CDC 配置
# ──────────────────────────────────────────────────────────────────────

DEFAULT_CDC_CONFIG = CDCConfig(
    mode=CDCMode.NOTIFY,
    tables=[
        TableCDCConfig(
            table_name="orders",
            key_columns=["id"],
            payload_columns=[
                "id",
                "tenant_id",
                "store_id",
                "total_fen",
                "status",
                "channel_type",
                "created_at",
                "updated_at",
            ],
            consumer_group="analytics",
        ),
        TableCDCConfig(
            table_name="order_items",
            key_columns=["id"],
            payload_columns=[
                "id",
                "order_id",
                "tenant_id",
                "dish_id",
                "quantity",
                "unit_price_fen",
                "total_fen",
                "created_at",
            ],
            consumer_group="analytics",
        ),
        TableCDCConfig(
            table_name="payments",
            key_columns=["id"],
            payload_columns=[
                "id",
                "order_id",
                "tenant_id",
                "amount_fen",
                "method",
                "status",
                "paid_at",
            ],
            consumer_group="finance",
        ),
        TableCDCConfig(
            table_name="member_transactions",
            key_columns=["id"],
            payload_columns=[
                "id",
                "member_id",
                "tenant_id",
                "type",
                "amount_fen",
                "balance_fen",
                "created_at",
            ],
            consumer_group="analytics",
        ),
        TableCDCConfig(
            table_name="inventory",
            key_columns=["id"],
            payload_columns=[
                "id",
                "tenant_id",
                "store_id",
                "ingredient_id",
                "quantity",
                "unit",
                "updated_at",
            ],
            consumer_group="supply",
        ),
    ],
)
