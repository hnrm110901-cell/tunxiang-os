"""CDC 监控指标 -- 延迟/吞吐量/积压监控

提供 CDC 管道的全维度可观测性指标：
- CDCEventMetrics: 事件级计数（received/processed/failed）
- CDCLatencyMetrics: 延迟分布（end-to-end + 各阶段延迟）
- CDCPipelineMetrics: 管道级聚合指标

所有指标线程安全（async context 下单线程，无需锁）。

用法：
    metrics = CDCPipelineMetrics()
    metrics.events.record_received()
    metrics.latency.record_e2e(42.5)  # ms
    snapshot = metrics.snapshot()     # 导出为 dict
"""

from __future__ import annotations

import time
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


class CDCEventMetrics:
    """CDC 事件计数指标 — 按表维度统计。"""

    def __init__(self) -> None:
        self.events_received: int = 0
        self.events_processed: int = 0
        self.events_failed: int = 0
        self.events_skipped: int = 0
        self.last_event_at: Optional[str] = None  # ISO timestamp of last event
        self.last_error: Optional[str] = None
        # Per-table counters: table_name -> {"received": N, "processed": N, "failed": N}
        self.per_table: dict[str, dict[str, int]] = {}

    def record_received(self, table: str) -> None:
        """记录事件接收。"""
        self.events_received += 1
        t = self._ensure_table(table)
        t["received"] += 1

    def record_processed(self, table: str) -> None:
        """记录事件处理成功。"""
        self.events_processed += 1
        t = self._ensure_table(table)
        t["processed"] += 1

    def record_failed(self, table: str, error: str) -> None:
        """记录事件处理失败。"""
        self.events_failed += 1
        self.last_error = error
        t = self._ensure_table(table)
        t["failed"] += 1

    def record_skipped(self, table: str, reason: str = "duplicate") -> None:
        """记录事件跳过。"""
        self.events_skipped += 1
        t = self._ensure_table(table)
        t.setdefault("skipped", 0)
        t["skipped"] += 1

    def set_last_event_at(self, iso_timestamp: str) -> None:
        """记录最后事件时间。"""
        self.last_event_at = iso_timestamp

    def _ensure_table(self, table: str) -> dict[str, int]:
        if table not in self.per_table:
            self.per_table[table] = {"received": 0, "processed": 0, "failed": 0, "skipped": 0}
        return self.per_table[table]

    def snapshot(self) -> dict:
        return {
            "events_received": self.events_received,
            "events_processed": self.events_processed,
            "events_failed": self.events_failed,
            "events_skipped": self.events_skipped,
            "last_event_at": self.last_event_at,
            "last_error": self.last_error,
            "per_table": dict(self.per_table),
        }


class CDCLatencyMetrics:
    """CDC 延迟指标 — 端到端及分阶段延迟。

    所有延迟单位为毫秒（float）。
    """

    def __init__(self, window_size: int = 1000) -> None:
        self._window_size = window_size
        self._e2e_samples: list[float] = []  # end-to-end latency (table change → consumer processed)
        self._notify_samples: list[float] = []  # DB write → NOTIFY received
        self._stream_samples: list[float] = []  # NOTIFY received → Redis Stream
        self._consume_samples: list[float] = []  # Redis Stream → consumer processed

    def record_e2e(self, latency_ms: float) -> None:
        """记录端到端延迟（表变更 → 消费者处理完成）。"""
        self._e2e_samples.append(latency_ms)
        self._trim()

    def record_notify(self, latency_ms: float) -> None:
        """记录 NOTIFY 阶段延迟（DB 写入 → NOTIFY 接收）。"""
        self._notify_samples.append(latency_ms)
        self._trim()

    def record_stream(self, latency_ms: float) -> None:
        """记录 Stream 写入延迟（NOTIFY 接收 → Redis Stream 写入）。"""
        self._stream_samples.append(latency_ms)
        self._trim()

    def record_consume(self, latency_ms: float) -> None:
        """记录消费延迟（Redis 拉取 → 消费者处理完成）。"""
        self._consume_samples.append(latency_ms)
        self._trim()

    def _trim(self) -> None:
        """保持滑动窗口大小。"""
        for lst in [self._e2e_samples, self._notify_samples, self._stream_samples, self._consume_samples]:
            if len(lst) > self._window_size:
                lst[:] = lst[-self._window_size:]

    def _percentile(self, samples: list[float], p: float) -> float:
        """计算滑动窗口内百分位数。"""
        if not samples:
            return 0.0
        sorted_samples = sorted(samples)
        idx = int(len(sorted_samples) * p / 100.0)
        idx = min(idx, len(sorted_samples) - 1)
        return sorted_samples[idx]

    def snapshot(self) -> dict:
        return {
            "e2e": {
                "p50_ms": round(self._percentile(self._e2e_samples, 50), 2),
                "p95_ms": round(self._percentile(self._e2e_samples, 95), 2),
                "p99_ms": round(self._percentile(self._e2e_samples, 99), 2),
                "avg_ms": round(sum(self._e2e_samples) / len(self._e2e_samples), 2) if self._e2e_samples else 0.0,
                "sample_count": len(self._e2e_samples),
            },
            "notify": {
                "p50_ms": round(self._percentile(self._notify_samples, 50), 2),
                "p95_ms": round(self._percentile(self._notify_samples, 95), 2),
                "p99_ms": round(self._percentile(self._notify_samples, 99), 2),
            },
            "stream": {
                "p50_ms": round(self._percentile(self._stream_samples, 50), 2),
                "p95_ms": round(self._percentile(self._stream_samples, 95), 2),
            },
            "consume": {
                "p50_ms": round(self._percentile(self._consume_samples, 50), 2),
                "p95_ms": round(self._percentile(self._consume_samples, 95), 2),
            },
        }


class CDCPipelineMetrics:
    """CDC 管道级聚合指标 — 事件计数 + 延迟分布 + 积压 + 吞吐量。"""

    def __init__(self) -> None:
        self.events = CDCEventMetrics()
        self.latency = CDCLatencyMetrics(window_size=1000)
        self._start_time: float = time.monotonic()
        self._throughput_window: list[tuple[float, int]] = []  # (timestamp_s, event_count)
        self._throughput_window_seconds: float = 60.0  # 60-second throughput window

    def record_event(self, table: str) -> None:
        """记录一个事件到达管道入口。"""
        self.events.record_received(table)
        self._record_throughput(1)

    def record_processed(self, table: str) -> None:
        """记录一个事件被消费者成功处理。"""
        self.events.record_processed(table)

    def record_failed(self, table: str, error: str) -> None:
        """记录一个事件处理失败。"""
        self.events.record_failed(table, error)

    def _record_throughput(self, count: int) -> None:
        now = time.monotonic()
        self._throughput_window.append((now, count))
        # 修剪到 60 秒窗口
        cutoff = now - self._throughput_window_seconds
        self._throughput_window = [(ts, cnt) for ts, cnt in self._throughput_window if ts > cutoff]

    @property
    def events_per_second(self) -> float:
        """最近 60 秒平均吞吐量（events/s）。"""
        now = time.monotonic()
        cutoff = now - self._throughput_window_seconds
        recent = [(ts, cnt) for ts, cnt in self._throughput_window if ts > cutoff]
        if not recent:
            return 0.0
        total_count = sum(cnt for _, cnt in recent)
        elapsed = now - recent[0][0] if recent else 1.0
        return round(total_count / max(elapsed, 0.1), 2)

    @property
    def uptime_seconds(self) -> float:
        """管道运行时长（秒）。"""
        return round(time.monotonic() - self._start_time, 2)

    @property
    def success_rate(self) -> float:
        """事件处理成功率（0.0 - 1.0）。"""
        total = self.events.events_received
        if total == 0:
            return 1.0
        return round(1.0 - (self.events.events_failed / total), 4)

    @property
    def backlog(self) -> int:
        """当前积压事件数（received - processed）。"""
        return self.events.events_received - self.events.events_processed

    def snapshot(self) -> dict:
        """导出完整指标快照为 dict（JSON 可序列化）。"""
        return {
            "uptime_seconds": self.uptime_seconds,
            "throughput_eps": self.events_per_second,
            "success_rate": self.success_rate,
            "backlog": self.backlog,
            "events": self.events.snapshot(),
            "latency": self.latency.snapshot(),
        }


class CDCMetrics:
    """CDC 指标收集器（向后兼容别名）。

    Attributes:
        events_received:   累计接收事件数
        events_processed:  累计处理事件数
        events_failed:     累计失败事件数
        last_event_at:     最后事件时间（ISO 格式字符串，None 表示无事件）
        p99_latency_ms:    端到端 p99 延迟（毫秒）
    """

    def __init__(self) -> None:
        self.events_received: int = 0
        self.events_processed: int = 0
        self.events_failed: int = 0
        self.last_event_at: Optional[str] = None
        self.p99_latency_ms: float = 0.0
        self._pipeline = CDCPipelineMetrics()

    def record_event(self, table: str = "unknown") -> None:
        """记录事件接收。"""
        self.events_received += 1
        self._pipeline.record_event(table)

    def record_processed(self, table: str = "unknown") -> None:
        """记录事件处理成功。"""
        self.events_processed += 1
        self._pipeline.record_processed(table)

    def record_failed(self, error: str, table: str = "unknown") -> None:
        """记录事件处理失败。"""
        self.events_failed += 1
        self._pipeline.record_failed(table, error)

    def set_last_event_at(self, iso_timestamp: str) -> None:
        """设置最后事件时间。"""
        self.last_event_at = iso_timestamp

    def record_latency(self, latency_ms: float) -> None:
        """记录端到端延迟（毫秒）。"""
        self._pipeline.latency.record_e2e(latency_ms)
        # 更新 p99 近似值
        self.p99_latency_ms = self._pipeline.latency._percentile(
            self._pipeline.latency._e2e_samples, 99
        )

    @property
    def backlog(self) -> int:
        """当前积压事件数。"""
        return self.events_received - self.events_processed

    @property
    def success_rate(self) -> float:
        """事件处理成功率。"""
        if self.events_received == 0:
            return 1.0
        return round(1.0 - (self.events_failed / self.events_received), 4)

    def snapshot(self) -> dict:
        """导出完整指标快照。"""
        return {
            "events_received": self.events_received,
            "events_processed": self.events_processed,
            "events_failed": self.events_failed,
            "backlog": self.backlog,
            "success_rate": self.success_rate,
            "p99_latency_ms": round(self.p99_latency_ms, 2),
            "last_event_at": self.last_event_at,
            "pipeline": self._pipeline.snapshot(),
        }
