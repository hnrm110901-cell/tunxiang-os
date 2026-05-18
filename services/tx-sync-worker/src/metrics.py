"""Prometheus metrics for tx-sync-worker (fail-open import 模式).

fail-open import 兜底 per memory `feedback_tier1_ci_minimal_deps_trap.md`:
  CI workflow 只装 ~10 包, prometheus_client 不一定在测试时可用. 用 no-op
  stub 兜底, 避免单元测试 collect 阶段 ImportError 阻塞 PR.

5 个 metrics (per plan §3.3):
  tx_sync_worker_executions_total{job, status}      Counter — 每次 cron firing 计数
  tx_sync_worker_last_run_timestamp_seconds{job}    Gauge   — 最近 run 时间戳
  tx_sync_worker_duration_seconds{job}              Histogram — 单次 job 耗时
  tx_sync_worker_retry_total{job, attempt}          Counter — 重试次数
  tx_sync_worker_dry_run_active                     Gauge   — dry_run 模式开关 (1=on/0=off)
"""
from __future__ import annotations

try:
    from prometheus_client import Counter, Gauge, Histogram

    _PROM_AVAILABLE = True
except ImportError:  # pragma: no cover — CI minimal deps fallback
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


# 每次 cron firing 计数 (status = dry_run | success | failed | error)
sync_executions_total = Counter(
    "tx_sync_worker_executions_total",
    "Total cron firings by job and status (dry_run | success | failed | error).",
    ["job", "status"],
)

# 最近 run 时间戳 (UNIX seconds, dry_run 模式也记录 fire 时间)
sync_last_run_timestamp_seconds = Gauge(
    "tx_sync_worker_last_run_timestamp_seconds",
    "UNIX timestamp of the last cron firing (any status).",
    ["job"],
)

# 单次 job 耗时 Histogram
sync_duration_seconds = Histogram(
    "tx_sync_worker_duration_seconds",
    "Seconds spent in a single cron job execution.",
    ["job"],
    buckets=(0.01, 0.1, 0.5, 1.0, 5.0, 30.0, 60.0, 300.0, 600.0),
)

# 重试次数计数 (与 _with_retry 配合)
sync_retry_total = Counter(
    "tx_sync_worker_retry_total",
    "Total retry attempts by job and attempt number.",
    ["job", "attempt"],
)

# dry_run 模式状态 (lifespan 启动时 set; Phase 2 翻 false 时 alert)
sync_dry_run_active = Gauge(
    "tx_sync_worker_dry_run_active",
    "dry_run mode flag: 1=on (no-op log only), 0=off (real adapter call).",
)
