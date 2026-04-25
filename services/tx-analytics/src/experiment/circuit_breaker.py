"""G4 — CircuitBreakerEvaluator：实验熔断器

规则（决策点）：
  默认阈值 -20%（experiment_definitions.circuit_breaker_threshold_pct，可逐实验覆盖）
  过去 1 小时核心指标对比 control vs variant：
    任意 variant 跌幅 > threshold → tripped=True
    所有 variant 在阈值内 → tripped=False

状态持久化：
  1. 写一条 EXPERIMENT.CIRCUIT_BREAKER_TRIPPED 事件（PG events 表 → 投影器消费）
  2. UPDATE experiment_definitions SET enabled=FALSE
  3. 写文件 flags/experiments/{key}.disabled.yaml（供运维 / Grafana 探测）
     注意：本动作只对 flags/experiments/ 目录生效，不动 flags/ 既有 flag。

调度：
  本模块只导出 evaluate / disable / reset 同步函数。挂 main.py 周期任务的工作
  留给后续运维 PR（避免本 PR 同时改 main.py）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional, Protocol

import structlog

logger = structlog.get_logger(__name__)

# 文件落地路径（相对仓库根）。运维可监控这个目录变动以可视化熔断状态。
_FLAG_DIR = "flags/experiments"


@dataclass(frozen=True)
class MetricSnapshot:
    """单个核心指标在某段时间窗内的均值（按 variant 分桶）。"""

    metric_key: str
    by_variant: dict[str, float]  # {"control": 0.985, "variant_a": 0.72}


@dataclass(frozen=True)
class VariantBreach:
    variant: str
    metric_key: str
    drop_pct: float  # 负数表示跌幅
    threshold_pct: float


@dataclass(frozen=True)
class CircuitBreakerStatus:
    experiment_key: str
    tripped: bool
    threshold_pct: float
    breaches: list[VariantBreach] = field(default_factory=list)
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class CoreMetricsProvider(Protocol):
    async def snapshot_last_hour(
        self,
        tenant_id: str,
        experiment_key: str,
    ) -> list[MetricSnapshot]:
        """返回 [MetricSnapshot, ...]，每个 metric 一项，by_variant 含 control + 各 variant。"""


class ExperimentDefinitionWriter(Protocol):
    async def disable_experiment(
        self, tenant_id: str, experiment_key: str, reason: str
    ) -> bool: ...


class CircuitBreakerEvaluator:
    """熔断评估器（无状态，每次 evaluate 重新计算）。"""

    def __init__(
        self,
        *,
        metrics_provider: CoreMetricsProvider,
        definition_writer: ExperimentDefinitionWriter,
        emit_func: Optional[Callable[..., Awaitable[Optional[str]]]] = None,
        flag_dir: str = _FLAG_DIR,
        control_variant: str = "control",
    ) -> None:
        self._metrics = metrics_provider
        self._writer = definition_writer
        self._emit = emit_func
        self._flag_dir = flag_dir
        self._control = control_variant

    async def evaluate(
        self,
        *,
        tenant_id: str,
        experiment_key: str,
        threshold_pct: float = -20.0,
    ) -> CircuitBreakerStatus:
        """评估是否应熔断。永不抛异常。"""
        try:
            snapshots = await self._metrics.snapshot_last_hour(
                tenant_id=tenant_id, experiment_key=experiment_key
            )
        except (ConnectionError, TimeoutError, OSError, RuntimeError) as e:
            logger.warning(
                "circuit_breaker_metrics_failed",
                tenant_id=tenant_id,
                experiment_key=experiment_key,
                error=str(e),
            )
            return CircuitBreakerStatus(
                experiment_key=experiment_key,
                tripped=False,
                threshold_pct=threshold_pct,
            )

        breaches: list[VariantBreach] = []
        for snapshot in snapshots:
            control_value = snapshot.by_variant.get(self._control)
            if control_value is None or control_value == 0:
                # 无 control 基线 → 跳过该指标（无法判断跌幅）
                continue
            for variant_name, variant_value in snapshot.by_variant.items():
                if variant_name == self._control:
                    continue
                # 跌幅百分比（负数为跌）
                drop_pct = ((variant_value - control_value) / abs(control_value)) * 100.0
                if drop_pct < threshold_pct:
                    breaches.append(
                        VariantBreach(
                            variant=variant_name,
                            metric_key=snapshot.metric_key,
                            drop_pct=drop_pct,
                            threshold_pct=threshold_pct,
                        )
                    )

        return CircuitBreakerStatus(
            experiment_key=experiment_key,
            tripped=bool(breaches),
            threshold_pct=threshold_pct,
            breaches=breaches,
        )

    async def trip(
        self,
        *,
        tenant_id: str,
        experiment_key: str,
        status: CircuitBreakerStatus,
    ) -> None:
        """熔断动作：关 enabled + 落 flag 文件 + 发事件。

        每一步独立失败：任一失败不影响其它两步。
        """
        # 1. 关 experiment_definitions.enabled
        try:
            reason = "; ".join(
                f"{b.variant}.{b.metric_key} drop={b.drop_pct:.2f}%"
                for b in status.breaches[:5]
            )
            await self._writer.disable_experiment(
                tenant_id=tenant_id,
                experiment_key=experiment_key,
                reason=reason or "circuit_breaker_tripped",
            )
        except (ConnectionError, TimeoutError, OSError, RuntimeError) as e:
            logger.warning(
                "circuit_breaker_disable_failed",
                experiment_key=experiment_key,
                error=str(e),
            )

        # 2. 落 flag 文件
        self._write_flag_file(experiment_key=experiment_key, status=status)

        # 3. 发事件（旁路）
        if self._emit is not None:
            try:
                from shared.events.src.event_types import ExperimentEventType

                tripped_event = ExperimentEventType.CIRCUIT_BREAKER_TRIPPED
            except ImportError:
                class _TrippedFallback:
                    value = "experiment.circuit_breaker_tripped"

                tripped_event = _TrippedFallback()

            try:
                await self._emit(
                    event_type=tripped_event,
                    tenant_id=tenant_id,
                    stream_id=experiment_key,
                    payload={
                        "experiment_key": experiment_key,
                        "threshold_pct": status.threshold_pct,
                        "breaches": [
                            {
                                "variant": b.variant,
                                "metric_key": b.metric_key,
                                "drop_pct": b.drop_pct,
                            }
                            for b in status.breaches
                        ],
                        "evaluated_at": status.evaluated_at.isoformat(),
                    },
                    source_service="tx-analytics",
                )
            except (ConnectionError, TimeoutError, OSError, RuntimeError) as e:
                logger.warning(
                    "circuit_breaker_emit_failed",
                    experiment_key=experiment_key,
                    error=str(e),
                )

    async def reset(
        self,
        *,
        tenant_id: str,
        experiment_key: str,
        actor: str,
    ) -> None:
        """管理员手动重置熔断。删 flag 文件 + 发 RESET 事件。

        重新启用实验 enabled 由调用方（管理员控制台）单独发起，避免本模块越权。
        """
        self._remove_flag_file(experiment_key=experiment_key)

        if self._emit is not None:
            try:
                from shared.events.src.event_types import ExperimentEventType

                reset_event = ExperimentEventType.CIRCUIT_BREAKER_RESET
            except ImportError:
                class _ResetFallback:
                    value = "experiment.circuit_breaker_reset"

                reset_event = _ResetFallback()

            try:
                await self._emit(
                    event_type=reset_event,
                    tenant_id=tenant_id,
                    stream_id=experiment_key,
                    payload={
                        "experiment_key": experiment_key,
                        "actor": actor,
                        "reset_at": datetime.now(timezone.utc).isoformat(),
                    },
                    source_service="tx-analytics",
                )
            except (ConnectionError, TimeoutError, OSError, RuntimeError) as e:
                logger.warning(
                    "circuit_breaker_reset_emit_failed",
                    experiment_key=experiment_key,
                    error=str(e),
                )

    # ── flag 文件落地（不动既有 flags 目录） ───────────────────────────────

    def _flag_path(self, experiment_key: str) -> str:
        safe = experiment_key.replace("/", "_").replace("..", "_")
        return os.path.join(self._flag_dir, f"{safe}.disabled.yaml")

    def _write_flag_file(self, *, experiment_key: str, status: CircuitBreakerStatus) -> None:
        try:
            os.makedirs(self._flag_dir, exist_ok=True)
        except OSError as e:
            logger.warning("circuit_breaker_flag_mkdir_failed", error=str(e))
            return

        path = self._flag_path(experiment_key)
        breach_lines = []
        for b in status.breaches:
            breach_lines.append(
                f"  - variant: {b.variant}\n"
                f"    metric_key: {b.metric_key}\n"
                f"    drop_pct: {b.drop_pct:.4f}\n"
                f"    threshold_pct: {b.threshold_pct:.4f}"
            )
        breach_yaml = "\n".join(breach_lines) if breach_lines else "  []"
        body = (
            f"# 自动生成 — 实验熔断器（不要手动编辑；通过 reset API 清理）\n"
            f"experiment_key: {experiment_key}\n"
            f"tripped: true\n"
            f"threshold_pct: {status.threshold_pct:.4f}\n"
            f"evaluated_at: {status.evaluated_at.isoformat()}\n"
            f"breaches:\n{breach_yaml}\n"
        )
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(body)
        except OSError as e:
            logger.warning("circuit_breaker_flag_write_failed", path=path, error=str(e))

    def _remove_flag_file(self, *, experiment_key: str) -> None:
        path = self._flag_path(experiment_key)
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError as e:
            logger.warning("circuit_breaker_flag_remove_failed", path=path, error=str(e))
