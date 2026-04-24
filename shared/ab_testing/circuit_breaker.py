"""A/B 实验熔断器 — 自动终止对 control 显著劣化的 treatment

触发条件：
  1. treatment 样本 >= min_samples（避免早期噪声）
  2. treatment 指标劣于 control 超过 threshold_pct 比例
  3. 按 primary_metric_goal 方向判定：
     · maximize：treatment < control × (1 - threshold)
     · minimize：treatment > control × (1 + threshold)

熔断后的动作（由 service 层执行）：
  · 实验 status 从 'running' 转 'terminated_circuit_breaker'
  · 停止给该 arm 分配新 entity
  · 保留历史 assignment 用于审计

设计考量：
  · 纯判定函数（不改 DB，不发通知）；service 层决定后续
  · 单 treatment arm 时判定简单；多 treatment 时逐一判定
  · threshold_pct 建议 0.15~0.25（太低易误伤季节性波动，太高太慢）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .statistics import ArmStats

# ─────────────────────────────────────────────────────────────
# 决策结果
# ─────────────────────────────────────────────────────────────


@dataclass
class CircuitBreakerDecision:
    """熔断评估结果"""

    should_trip: bool
    # 若 should_trip=True，以下字段有值
    tripped_arm_keys: list[str] = field(default_factory=list)
    reason: Optional[str] = None
    # 详细指标对比（每 treatment arm 一条）
    arm_comparisons: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "should_trip": self.should_trip,
            "tripped_arm_keys": self.tripped_arm_keys,
            "reason": self.reason,
            "arm_comparisons": self.arm_comparisons,
        }


# ─────────────────────────────────────────────────────────────
# 主函数
# ─────────────────────────────────────────────────────────────


def evaluate_circuit_breaker(
    control: ArmStats,
    treatments: list[tuple[str, ArmStats]],
    *,
    metric: str = "conversion_rate",
    goal: str = "maximize",
    threshold_pct: float = 0.20,
    min_samples: int = 200,
) -> CircuitBreakerDecision:
    """评估是否需要熔断

    Args:
      control: control arm 的统计
      treatments: [(arm_key, stats), ...] 所有 treatment arms
      metric: 参考 statistics.frequentist_significance 的 metric 参数
      goal: 'maximize' / 'minimize'
      threshold_pct: 劣化阈值（0.20 = 20%）
      min_samples: treatment 至少达此样本量才评估

    Returns:
      CircuitBreakerDecision
    """
    if goal not in ("maximize", "minimize"):
        raise ValueError(f"goal 必须 maximize/minimize，收到 {goal!r}")
    if threshold_pct <= 0 or threshold_pct >= 1:
        raise ValueError("threshold_pct 必须 ∈ (0, 1)")

    control_metric = _metric_value(control, metric)
    comparisons: list[dict] = []
    tripped: list[str] = []
    reasons: list[str] = []

    for arm_key, treatment in treatments:
        if treatment.exposure < min_samples:
            comparisons.append({
                "arm_key": arm_key,
                "exposure": treatment.exposure,
                "skipped": True,
                "reason": f"样本量 {treatment.exposure} < min_samples {min_samples}",
            })
            continue

        treatment_metric = _metric_value(treatment, metric)

        # 计算相对劣化
        should_trip_arm, degradation_pct = _check_degradation(
            control_metric=control_metric,
            treatment_metric=treatment_metric,
            threshold_pct=threshold_pct,
            goal=goal,
        )

        comparisons.append({
            "arm_key": arm_key,
            "exposure": treatment.exposure,
            "control_metric": control_metric,
            "treatment_metric": treatment_metric,
            "degradation_pct": round(degradation_pct, 4),
            "threshold_pct": threshold_pct,
            "should_trip": should_trip_arm,
        })

        if should_trip_arm:
            tripped.append(arm_key)
            reasons.append(
                f"{arm_key}: {metric} 劣化 {degradation_pct*100:.1f}% "
                f"(阈值 {threshold_pct*100:.0f}%)"
            )

    if tripped:
        return CircuitBreakerDecision(
            should_trip=True,
            tripped_arm_keys=tripped,
            reason="; ".join(reasons),
            arm_comparisons=comparisons,
        )

    return CircuitBreakerDecision(
        should_trip=False,
        arm_comparisons=comparisons,
    )


# ─────────────────────────────────────────────────────────────
# 内部
# ─────────────────────────────────────────────────────────────


def _metric_value(arm: ArmStats, metric: str) -> float:
    """从 ArmStats 提取指定 metric 的值"""
    if metric == "conversion_rate":
        return arm.conversion_rate
    if metric == "avg_revenue":
        return arm.avg_revenue_fen
    if metric == "numeric_mean":
        return arm.numeric_metric_mean
    raise ValueError(f"不支持 metric={metric!r}")


def _check_degradation(
    *,
    control_metric: float,
    treatment_metric: float,
    threshold_pct: float,
    goal: str,
) -> tuple[bool, float]:
    """判断 treatment 是否较 control 显著劣化

    Returns:
      (should_trip, degradation_pct)
      degradation_pct 是 treatment 比 control 差多少（相对百分比），负数表示 treatment 更好
    """
    if control_metric == 0:
        # control 为 0 时无法按比例判定；不触发
        return (False, 0.0)

    if goal == "maximize":
        # 目标是提升；treatment 下降 = 劣化
        degradation = (control_metric - treatment_metric) / abs(control_metric)
    else:
        # 目标是降低；treatment 上升 = 劣化
        degradation = (treatment_metric - control_metric) / abs(control_metric)

    should_trip = degradation > threshold_pct
    return (should_trip, degradation)
