"""G3 — ExperimentDashboard：跨变体显著性汇总

输入：
  experiment_key + 监控指标列表 + 时间窗口
输出：
  ExperimentSummary：每个 (metric, variant_pair) 的 lift / p_value / 是否显著

依赖注入：
  - exposure_lookup: 给定 (tenant, exp_key, time_window) 返回 {variant: [subject_ids]}
  - metrics_repo: 给定 (tenant, metric_key, subject_ids, time_window) 返回 list[float]

  这样测试时直接 mock，不需要真连物化视图。生产环境的实现挂在
  services/tx-analytics/src/experiment/repositories.py（后续 PR 再补；本 PR 先
  保证 dashboard 函数边界清晰可测）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

import structlog

from .metrics import WelchResult, welch_t_test

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class TimeWindow:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class VariantMetricCell:
    """单个 (metric, variant) 的统计单元。"""

    variant: str
    metric_key: str
    n: int
    mean: float


@dataclass(frozen=True)
class PairwiseResult:
    """control vs variant 的 Welch 检验结果。"""

    metric_key: str
    control_variant: str
    test_variant: str
    welch: WelchResult
    lift_pct: float  # (mean_b - mean_a) / mean_a * 100, mean_a==0 → 0


@dataclass
class ExperimentSummary:
    experiment_key: str
    time_window: TimeWindow
    variant_subjects: dict[str, list[str]] = field(default_factory=dict)
    cells: list[VariantMetricCell] = field(default_factory=list)
    pairs: list[PairwiseResult] = field(default_factory=list)


class ExposureLookup(Protocol):
    async def list_subjects_by_variant(
        self,
        tenant_id: str,
        experiment_key: str,
        time_window: TimeWindow,
    ) -> dict[str, list[str]]:
        """返回 {variant_name: [subject_id, ...]}。"""


class MetricsRepository(Protocol):
    async def fetch_metric(
        self,
        tenant_id: str,
        metric_key: str,
        subject_ids: list[str],
        time_window: TimeWindow,
    ) -> list[float]:
        """返回每个 subject 在窗口内某指标的观测值列表（一维）。"""


class ExperimentDashboard:
    def __init__(
        self,
        *,
        exposure_lookup: ExposureLookup,
        metrics_repo: MetricsRepository,
        control_variant_name: str = "control",
    ) -> None:
        self._exp = exposure_lookup
        self._met = metrics_repo
        self._control_name = control_variant_name

    async def summarize(
        self,
        *,
        tenant_id: str,
        experiment_key: str,
        metric_keys: list[str],
        time_window: TimeWindow,
    ) -> ExperimentSummary:
        """对每个 metric × (control vs variant) 跑 Welch's t-test。"""
        summary = ExperimentSummary(
            experiment_key=experiment_key,
            time_window=time_window,
        )

        try:
            subjects_by_variant = await self._exp.list_subjects_by_variant(
                tenant_id=tenant_id,
                experiment_key=experiment_key,
                time_window=time_window,
            )
        except (ConnectionError, TimeoutError, OSError, RuntimeError) as e:
            logger.warning(
                "experiment_dashboard_subjects_failed",
                tenant_id=tenant_id,
                experiment_key=experiment_key,
                error=str(e),
            )
            return summary

        summary.variant_subjects = subjects_by_variant
        if self._control_name not in subjects_by_variant:
            logger.warning(
                "experiment_dashboard_no_control",
                experiment_key=experiment_key,
                variants=list(subjects_by_variant.keys()),
            )
            return summary

        control_subjects = subjects_by_variant[self._control_name]

        for metric_key in metric_keys:
            # 对照组样本
            try:
                control_samples = await self._met.fetch_metric(
                    tenant_id=tenant_id,
                    metric_key=metric_key,
                    subject_ids=control_subjects,
                    time_window=time_window,
                )
            except (ConnectionError, TimeoutError, OSError, RuntimeError) as e:
                logger.warning(
                    "metric_fetch_failed",
                    metric_key=metric_key,
                    variant=self._control_name,
                    error=str(e),
                )
                continue

            control_mean = (
                sum(control_samples) / len(control_samples) if control_samples else 0.0
            )
            summary.cells.append(
                VariantMetricCell(
                    variant=self._control_name,
                    metric_key=metric_key,
                    n=len(control_samples),
                    mean=control_mean,
                )
            )

            for variant_name, variant_subjects in subjects_by_variant.items():
                if variant_name == self._control_name:
                    continue

                try:
                    variant_samples = await self._met.fetch_metric(
                        tenant_id=tenant_id,
                        metric_key=metric_key,
                        subject_ids=variant_subjects,
                        time_window=time_window,
                    )
                except (ConnectionError, TimeoutError, OSError, RuntimeError) as e:
                    logger.warning(
                        "metric_fetch_failed",
                        metric_key=metric_key,
                        variant=variant_name,
                        error=str(e),
                    )
                    continue

                variant_mean = (
                    sum(variant_samples) / len(variant_samples)
                    if variant_samples
                    else 0.0
                )
                summary.cells.append(
                    VariantMetricCell(
                        variant=variant_name,
                        metric_key=metric_key,
                        n=len(variant_samples),
                        mean=variant_mean,
                    )
                )

                welch = welch_t_test(control_samples, variant_samples)
                lift_pct = (
                    ((variant_mean - control_mean) / control_mean) * 100.0
                    if control_mean
                    else 0.0
                )
                summary.pairs.append(
                    PairwiseResult(
                        metric_key=metric_key,
                        control_variant=self._control_name,
                        test_variant=variant_name,
                        welch=welch,
                        lift_pct=lift_pct,
                    )
                )

        return summary
