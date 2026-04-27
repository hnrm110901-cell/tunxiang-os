"""structlog JSON 日志配置 — 含 stdlib 桥接。

桥接目的：让 uvicorn / SQLAlchemy / asyncpg / alembic 等通过 stdlib `logging`
发出的日志也走 structlog 的 JSON 渲染管线，避免业务日志和框架日志格式分裂
（一部分 JSON、一部分纯文本）破坏可观测查询和告警规则。

参考：https://www.structlog.org/en/stable/standard-library.html
"""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(level: str = "INFO") -> None:
    """全局配置 structlog + stdlib bridge，统一 JSON 输出。"""

    log_level = getattr(logging, level.upper(), logging.INFO)

    # 共享处理器链：stdlib 进入 ProcessorFormatter 之前先跑这些；
    # structlog 自身也跑同一份链，保证两条路径产出字段一致。
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    # stdlib 路径：用 ProcessorFormatter 在 root logger 上挂 JSON 渲染
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(log_level)

    # structlog 路径：链尾用 wrap_for_formatter 把事件包成 stdlib 兼容形式，
    # 由 LoggerFactory 转交给 stdlib handler，最终由 ProcessorFormatter 渲染。
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
