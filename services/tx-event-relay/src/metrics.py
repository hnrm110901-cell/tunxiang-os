"""Prometheus metrics for tx-event-relay (fail-open import 模式).

fail-open import 兜底 per memory `feedback_tier1_ci_minimal_deps_trap.md`:
  Tier 1 CI workflow 只装 ~10 包, prometheus_client 不一定在测试时可用. 用 no-op
  stub 兜底, 避免单元测试 collect 阶段 ImportError 阻塞 PR.

shadow 验收 #5: outbox_pending_count + relay_delivery_lag_seconds 须可抓.
"""
from __future__ import annotations

try:
    from prometheus_client import Counter, Gauge, Histogram

    _PROM_AVAILABLE = True
except ImportError:  # noqa: BLE001
    _PROM_AVAILABLE = False

    class _NoOpMetric:
        """no-op fallback when prometheus_client 不可用 (CI minimal deps)."""

        def __init__(self, *args, **kwargs) -> None:
            pass

        def inc(self, *args, **kwargs) -> None:
            pass

        def dec(self, *args, **kwargs) -> None:
            pass

        def set(self, *args, **kwargs) -> None:
            pass

        def observe(self, *args, **kwargs) -> None:
            pass

        def labels(self, *args, **kwargs) -> "_NoOpMetric":
            return self

    Counter = _NoOpMetric  # type: ignore[assignment,misc]
    Gauge = _NoOpMetric  # type: ignore[assignment,misc]
    Histogram = _NoOpMetric  # type: ignore[assignment,misc]


# 当前积压 outbox 行数 (未投递)
outbox_pending_count = Gauge(
    "tx_event_relay_outbox_pending_count",
    "Number of undelivered outbox rows currently pending in trade_event_outbox.",
)

# 投递成功 / 失败计数
outbox_delivery_total = Counter(
    "tx_event_relay_outbox_delivery_total",
    "Total outbox rows processed (success or shadow dry-run).",
    ["result"],  # result = success | shadow_dry_run
)

# 投递延迟 (created_at → 处理时间), shadow 期间记录 dry-run lag
relay_delivery_lag_seconds = Histogram(
    "tx_event_relay_delivery_lag_seconds",
    "Seconds between outbox row created_at and relay processing.",
    buckets=(0.05, 0.1, 0.5, 1.0, 5.0, 30.0, 60.0, 300.0),
)

# PG 不可达计数 (asyncpg.PostgresConnectionError 触发)
relay_pg_failure_total = Counter(
    "tx_event_relay_pg_failure_total",
    "PostgreSQL connection failures encountered by relay loop.",
)

# outermost except 兜底触发计数 (非 PG 异常)
relay_loop_unexpected_total = Counter(
    "tx_event_relay_loop_unexpected_total",
    "Unexpected exceptions caught by outermost relay loop except (exc_info logged).",
)
