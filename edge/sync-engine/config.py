"""config.py — 屯象OS 边缘同步引擎配置

从环境变量或 .env 文件读取，使用 pydantic-settings。
必填项：CLOUD_PG_DSN / STORE_ID / TENANT_ID（无默认值，启动时报错提示）
"""

from __future__ import annotations

from pydantic_settings import BaseSettings


class SyncConfig(BaseSettings):
    # 本地 PostgreSQL（Mac mini 本地副本）
    LOCAL_PG_DSN: str = "postgresql+asyncpg://localhost:5432/tunxiang_local"

    # 云端 PostgreSQL（腾讯云），从环境变量 CLOUD_PG_DSN 读取，无默认值
    CLOUD_PG_DSN: str

    # 门店标识与租户标识
    STORE_ID: str
    TENANT_ID: str

    # 同步节奏（秒）
    SYNC_INTERVAL_SECONDS: int = 300

    # 指数退避最大等待时间（秒）
    MAX_RETRY_BACKOFF: int = 3600  # 最大 1 小时

    # 每批次同步行数
    BATCH_SIZE: int = 100

    # 单轮同步超时（秒）
    SYNC_TIMEOUT_SECONDS: int = 60

    # 日志级别
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
