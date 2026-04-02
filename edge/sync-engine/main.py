"""main.py — 屯象OS 边缘同步引擎启动入口

启动流程：
  1. 从环境变量 / .env 读取 SyncConfig
  2. 初始化 structlog（JSON 格式）
  3. 创建 SyncEngine 并调用 run_forever

使用：
  python main.py                        # 直接运行
  launchctl load com.tunxiang.sync-engine.plist  # macOS 开机自启
"""
from __future__ import annotations

import asyncio
import logging
import sys

import structlog
from config import SyncConfig
from sync_engine import SyncEngine


def _setup_logging(log_level: str) -> None:
    """配置 structlog 结构化日志（JSON 输出）"""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


async def main() -> None:
    config = SyncConfig()  # type: ignore[call-arg]  # 必填项从环境变量读取
    _setup_logging(config.LOG_LEVEL)

    log = structlog.get_logger()
    log.info(
        "main.starting",
        store_id=config.STORE_ID,
        tenant_id=config.TENANT_ID,
        sync_interval_seconds=config.SYNC_INTERVAL_SECONDS,
        batch_size=config.BATCH_SIZE,
        sync_timeout=config.SYNC_TIMEOUT_SECONDS,
    )

    engine = SyncEngine(
        local_dsn=config.LOCAL_PG_DSN,
        cloud_dsn=config.CLOUD_PG_DSN,
        store_id=config.STORE_ID,
        tenant_id=config.TENANT_ID,
        batch_size=config.BATCH_SIZE,
        sync_timeout=config.SYNC_TIMEOUT_SECONDS,
        max_retry_backoff=config.MAX_RETRY_BACKOFF,
    )

    await engine.run_forever(interval_seconds=config.SYNC_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
