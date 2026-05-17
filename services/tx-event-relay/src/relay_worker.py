"""relay_worker — Outbox polling + delivery 主循环.

W3 P0 issue #757 shadow mode 实现:
  - 循环 polling trade_event_outbox 表
  - shadow_mode = True (env RELAY_SHADOW_MODE 默认 true): log + metrics, 0 events.append
  - shadow_mode = False: 抛 NotImplementedError (W11 follow-up issue #767 实现真投递)

容错设计:
  - asyncpg.PostgresConnectionError: backoff (1s → 2s → 4s → max 30s) + counter inc + continue
  - 任何 Exception (broad except 仅 outermost, 加 exc_info=True per CLAUDE.md §14): 同上
  - shutdown_event 信号: 跳出循环

强红线 (per plan §7.1):
  - shadow_mode=True 分支显式 log + continue, 0 业务副作用
  - 严禁 fall-through 进入真投递路径 (NotImplementedError 显式抛)
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import structlog

try:
    import asyncpg
except ImportError:  # pragma: no cover — CI minimal deps fallback
    asyncpg = None  # type: ignore[assignment]

from .metrics import (
    outbox_delivery_total,
    outbox_pending_count,
    relay_delivery_lag_seconds,
    relay_loop_unexpected_total,
    relay_pg_failure_total,
)
from .outbox_repo import fetch_pending_batch

logger = structlog.get_logger(__name__)


# Backoff schedule (秒): exponential, cap at 30s
_BACKOFF_SCHEDULE: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0, 16.0, 30.0)


@dataclass
class RelayConfig:
    """Relay worker 运行配置 (env 注入)."""

    shadow_mode: bool
    poll_interval_ms: int
    batch_size: int

    @classmethod
    def from_env(cls) -> "RelayConfig":
        return cls(
            shadow_mode=os.getenv("RELAY_SHADOW_MODE", "true").lower() == "true",
            poll_interval_ms=int(os.getenv("RELAY_POLL_INTERVAL_MS", "500")),
            batch_size=int(os.getenv("RELAY_BATCH_SIZE", "100")),
        )


def _lag_seconds(created_at: datetime | None) -> float:
    """计算 outbox row created_at 到当前的延迟秒数."""
    if created_at is None:
        return 0.0
    now = datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return max((now - created_at).total_seconds(), 0.0)


def _backoff_seconds(attempt: int) -> float:
    """Exponential backoff with cap.

    attempt: 0-based 重试次数. attempt=0 → 1s, attempt=5+ → 30s cap.
    """
    idx = min(attempt, len(_BACKOFF_SCHEDULE) - 1)
    return _BACKOFF_SCHEDULE[idx]


async def relay_loop(
    pool: Any,  # asyncpg.Pool, typed Any 兼容 import-fail-open
    config: RelayConfig,
    shutdown_event: asyncio.Event,
) -> None:
    """Outbox relay 主循环.

    Args:
        pool: asyncpg connection pool (min=1 max=3, 不复用 SQLAlchemy
            async_session_factory per memory `feedback_projector_asyncpg_pool_model.md`).
        config: shadow_mode / poll_interval_ms / batch_size.
        shutdown_event: lifespan shutdown 信号.
    """
    consecutive_failures = 0
    logger.info(
        "relay_loop_started",
        shadow_mode=config.shadow_mode,
        poll_interval_ms=config.poll_interval_ms,
        batch_size=config.batch_size,
    )

    while not shutdown_event.is_set():
        try:
            # 从 outbox_repo 拿一批未投递行
            rows = await fetch_pending_batch(pool, config.batch_size)
            consecutive_failures = 0  # 成功 reset backoff

            for row in rows:
                if config.shadow_mode:
                    # Phase 3 shadow: log only, 0 业务副作用 (强红线)
                    logger.info(
                        "relay_shadow_dry_run",
                        outbox_id=str(row.get("id", "")),
                        event_type=row.get("event_type", ""),
                        stream_id=row.get("stream_id", ""),
                        tenant_id=str(row.get("tenant_id", "")),
                    )
                    outbox_delivery_total.labels(result="shadow_dry_run").inc()
                    relay_delivery_lag_seconds.observe(_lag_seconds(row.get("created_at")))
                    continue
                # W11 follow-up issue #767: 真投递路径 (本 PR 严禁实现)
                raise NotImplementedError(
                    "real delivery path scheduled for W11 follow-up issue #767"
                )

            # 整批处理完 → 正常 sleep poll_interval
            await asyncio.sleep(config.poll_interval_ms / 1000)

        except _PgConnectionError as exc:
            logger.warning(
                "relay_pg_unavailable",
                error=str(exc),
                consecutive_failures=consecutive_failures,
                exc_info=True,
            )
            relay_pg_failure_total.inc()
            await asyncio.sleep(_backoff_seconds(consecutive_failures))
            consecutive_failures += 1
            continue

        except NotImplementedError:
            # W11 path 直接 propagate (shadow_mode=false 是 fatal 配置错)
            raise

        except Exception as exc:  # noqa: BLE001 — outermost shadow loop, exc_info+continue per CLAUDE.md §14
            logger.error(
                "relay_loop_unexpected",
                error=str(exc),
                error_type=type(exc).__name__,
                consecutive_failures=consecutive_failures,
                exc_info=True,
            )
            relay_loop_unexpected_total.inc()
            await asyncio.sleep(_backoff_seconds(consecutive_failures))
            consecutive_failures += 1
            continue

    logger.info("relay_loop_shutdown", reason="shutdown_event_set")


def _get_pg_connection_error_class() -> type[BaseException]:
    """asyncpg PostgresConnectionError class, fail-open 兜底.

    CI minimal deps 不装 asyncpg 时返回一个永不匹配的 sentinel 类, 让 except
    分支静态 bind 但运行时不触 (避免 ImportError 阻塞测试 collect).
    """
    if asyncpg is None:
        # Sentinel: 永不会被实际异常 isinstance 匹配
        class _UnreachablePgError(BaseException):
            pass

        return _UnreachablePgError
    return asyncpg.exceptions.PostgresConnectionError


_PgConnectionError = _get_pg_connection_error_class()


# 监控辅助 (供 main.py /health 使用)
def update_pending_count_gauge(value: int) -> None:
    """Gauge set helper, 供 outbox_repo 调用更新积压数."""
    outbox_pending_count.set(value)
