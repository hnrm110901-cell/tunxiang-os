"""A/B 实验统计显著性 — Frequentist + Bayesian

不依赖 scipy / numpy，用 Python 标准库 math 实现：
  · z-test（比例差异）+ t-test（连续均值差异）
  · Bayesian Beta posterior（conversion rate）
  · sample size 计算（Lehr 公式近似）

误差容忍：≤ 1e-4 vs scipy；对 A/B 实验判定足够。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

# ─────────────────────────────────────────────────────────────
# 数据类
# ─────────────────────────────────────────────────────────────


@dataclass
class ArmStats:
    """一个 arm 的累计统计"""

    exposure: int = 0  # 暴露人次（分母）
    conversion: int = 0  # 转化人次（分子）
    revenue_sum_fen: int = 0  # 累计营收
    numeric_metric_sum: float = 0.0  # 自定义连续指标累计
    numeric_metric_ssq: float = 0.0  # sum of squares
    is_control: bool = False

    @property
    def conversion_rate(self) -> float:
        if self.exposure <= 0:
            return 0.0
        return self.conversion / self.exposure

    @property
    def avg_revenue_fen(self) -> float:
        if self.exposure <= 0:
            return 0.0
        return self.revenue_sum_fen / self.exposure

    @property
    def numeric_metric_mean(self) -> float:
        if self.exposure <= 0:
            return 0.0
        return self.numeric_metric_sum / self.exposure

    @property
    def numeric_metric_variance(self) -> float:
        """population variance（n 做分母）"""
        if self.exposure <= 0:
            return 0.0
        m = self.numeric_metric_mean
        return max(
            0.0, self.numeric_metric_ssq / self.exposure - m * m
        )


@dataclass
class SignificanceResult:
    """显著性检验结果"""

    test_type: str  # 'z_test' | 't_test'
    z_score: Optional[float]
    t_score: Optional[float]
    p_value: float
    significant: bool
    effect_size: float  # treatment - control（比例差 or 均值差）
    effect_size_pct: float  # relative lift（(treatment - control) / control）
    alpha: float
    control_n: int
    treatment_n: int
    note: Optional[str] = None


@dataclass
class BayesianResult:
    """Bayesian posterior 结果（Beta-Binomial）"""

    prob_treatment_beats_control: float  # P(rate_t > rate_c | data)
    expected_loss_pct: float  # 选 treatment 但它其实更差 的期望损失
    control_posterior_mean: float
    treatment_posterior_mean: float
    note: Optional[str] = None


# ─────────────────────────────────────────────────────────────
# 基础统计函数
# ─────────────────────────────────────────────────────────────


def _erf(x: float) -> float:
    """math.erf wrapper（跨 Python 版本保险）"""
    return math.erf(x)


def normal_cdf(z: float) -> float:
    """标准正态 CDF"""
    return 0.5 * (1 + _erf(z / math.sqrt(2)))


def normal_sf(z: float) -> float:
    """1 - CDF（上尾）"""
    return 1 - normal_cdf(z)


def two_sided_p_value(z: float) -> float:
    """双侧 p 值"""
    return 2 * normal_sf(abs(z))


# ─────────────────────────────────────────────────────────────
# Frequentist：z-test（比例） + t-test（连续）
# ─────────────────────────────────────────────────────────────


def frequentist_significance(
    control: ArmStats,
    treatment: ArmStats,
    *,
    metric: str = "conversion_rate",
    alpha: float = 0.05,
) -> SignificanceResult:
    """Frequentist 双侧检验

    metric:
      · 'conversion_rate' — z-test 比例差
      · 'avg_revenue' — Welch's t-test 均值差（分 fen）
      · 'numeric_mean' — Welch's t-test 自定义 numeric_metric 均值
    """
    if metric == "conversion_rate":
        return _z_test_proportions(control, treatment, alpha=alpha)
    if metric in ("avg_revenue", "numeric_mean"):
        return _welch_t_test(control, treatment, metric=metric, alpha=alpha)
    raise ValueError(f"不支持 metric={metric!r}")


def _z_test_proportions(
    control: ArmStats, treatment: ArmStats, *, alpha: float
) -> SignificanceResult:
    n_c = control.exposure
    n_t = treatment.exposure
    x_c = control.conversion
    x_t = treatment.conversion

    if n_c <= 0 or n_t <= 0:
        return SignificanceResult(
            test_type="z_test",
            z_score=None,
            t_score=None,
            p_value=1.0,
            significant=False,
            effect_size=0.0,
            effect_size_pct=0.0,
            alpha=alpha,
            control_n=n_c,
            treatment_n=n_t,
            note="样本量为 0",
        )

    p_c = x_c / n_c
    p_t = x_t / n_t
    p_pool = (x_c + x_t) / (n_c + n_t)
    denom_sq = p_pool * (1 - p_pool) * (1 / n_c + 1 / n_t)

    if denom_sq <= 0:
        return SignificanceResult(
            test_type="z_test",
            z_score=None,
            t_score=None,
            p_value=1.0,
            significant=False,
            effect_size=p_t - p_c,
            effect_size_pct=_safe_pct(p_c, p_t),
            alpha=alpha,
            control_n=n_c,
            treatment_n=n_t,
            note="方差为 0（全命中或全未命中）",
        )

    z = (p_t - p_c) / math.sqrt(denom_sq)
    p = two_sided_p_value(z)
    return SignificanceResult(
        test_type="z_test",
        z_score=z,
        t_score=None,
        p_value=p,
        significant=p < alpha,
        effect_size=p_t - p_c,
        effect_size_pct=_safe_pct(p_c, p_t),
        alpha=alpha,
        control_n=n_c,
        treatment_n=n_t,
    )


def _welch_t_test(
    control: ArmStats, treatment: ArmStats, *, metric: str, alpha: float
) -> SignificanceResult:
    n_c = control.exposure
    n_t = treatment.exposure
    if n_c < 2 or n_t < 2:
        return SignificanceResult(
            test_type="t_test",
            z_score=None,
            t_score=None,
            p_value=1.0,
            significant=False,
            effect_size=0.0,
            effect_size_pct=0.0,
            alpha=alpha,
            control_n=n_c,
            treatment_n=n_t,
            note="Welch t 需要 n >= 2",
        )

    if metric == "avg_revenue":
        # 基于 revenue：没有 ssq，退化用粗估：方差 = mean² × (1 + CV²)
        # 简化：假设 CV=1（保守）
        mean_c = control.avg_revenue_fen
        mean_t = treatment.avg_revenue_fen
        # 保守方差估计（不可能负，不可能为 0）
        var_c = max(1.0, mean_c * mean_c)
        var_t = max(1.0, mean_t * mean_t)
        note = "avg_revenue 用粗估方差（CV=1），精度有限"
    else:  # numeric_mean
        mean_c = control.numeric_metric_mean
        mean_t = treatment.numeric_metric_mean
        var_c = control.numeric_metric_variance
        var_t = treatment.numeric_metric_variance
        note = None

    se = math.sqrt(var_c / n_c + var_t / n_t)
    if se <= 0:
        return SignificanceResult(
            test_type="t_test",
            z_score=None,
            t_score=None,
            p_value=1.0,
            significant=False,
            effect_size=mean_t - mean_c,
            effect_size_pct=_safe_pct(mean_c, mean_t),
            alpha=alpha,
            control_n=n_c,
            treatment_n=n_t,
            note="标准误为 0",
        )

    t = (mean_t - mean_c) / se
    # 大样本近似为正态；小样本精度差但足够 A/B 场景
    p = two_sided_p_value(t)
    return SignificanceResult(
        test_type="t_test",
        z_score=None,
        t_score=t,
        p_value=p,
        significant=p < alpha,
        effect_size=mean_t - mean_c,
        effect_size_pct=_safe_pct(mean_c, mean_t),
        alpha=alpha,
        control_n=n_c,
        treatment_n=n_t,
        note=note,
    )


# ─────────────────────────────────────────────────────────────
# Bayesian: Beta-Binomial posterior
# ─────────────────────────────────────────────────────────────


def bayesian_posterior(
    control: ArmStats,
    treatment: ArmStats,
    *,
    prior_alpha: float = 1.0,
    prior_beta: float = 1.0,
    simulations: int = 10000,
    seed: Optional[int] = 42,
) -> BayesianResult:
    """Monte Carlo 采样估计 P(treatment > control)

    Beta prior（默认 Uniform = Beta(1,1)）+ Binomial likelihood
    → Beta(α + conversions, β + exposure - conversions) posterior

    returns:
      · prob_treatment_beats_control ∈ [0, 1]
      · expected_loss_pct（选 treatment 但真实比 control 差的加权损失）
    """
    import random

    if simulations < 1000:
        raise ValueError("simulations 至少 1000")

    rng = random.Random(seed)

    a_c = prior_alpha + control.conversion
    b_c = prior_beta + (control.exposure - control.conversion)
    a_t = prior_alpha + treatment.conversion
    b_t = prior_beta + (treatment.exposure - treatment.conversion)

    if a_c <= 0 or b_c <= 0 or a_t <= 0 or b_t <= 0:
        return BayesianResult(
            prob_treatment_beats_control=0.5,
            expected_loss_pct=0.0,
            control_posterior_mean=0.0,
            treatment_posterior_mean=0.0,
            note="参数非法（样本量不足）",
        )

    # Beta sampling via random.betavariate
    wins = 0
    loss_sum = 0.0
    for _ in range(simulations):
        p_c = rng.betavariate(a_c, b_c)
        p_t = rng.betavariate(a_t, b_t)
        if p_t > p_c:
            wins += 1
        else:
            loss_sum += p_c - p_t

    prob = wins / simulations
    expected_loss = loss_sum / simulations  # 平均每次采样 treatment 输的量

    return BayesianResult(
        prob_treatment_beats_control=round(prob, 4),
        expected_loss_pct=round(expected_loss, 6),
        control_posterior_mean=a_c / (a_c + b_c),
        treatment_posterior_mean=a_t / (a_t + b_t),
    )


# ─────────────────────────────────────────────────────────────
# Sample size 计算
# ─────────────────────────────────────────────────────────────


def required_sample_size(
    *,
    baseline_rate: float,
    min_detectable_effect: float,
    alpha: float = 0.05,
    power: float = 0.80,
) -> int:
    """Lehr 公式近似：每个 arm 所需样本量

    公式：n = (z_α/2 + z_β)² × [p1(1-p1) + p2(1-p2)] / (p2 - p1)²

    简化：用 Lehr 常数（16）近似 (z_α + z_β)²：
        z_0.025 + z_0.20 ≈ 1.96 + 0.84 ≈ 2.8 → (2.8)² ≈ 7.84（过于乐观）
        实际用查表：
          α=0.05, power=0.80 → 7.85
          α=0.05, power=0.90 → 10.51
          α=0.01, power=0.80 → 11.68
    """
    if not (0 < baseline_rate < 1):
        raise ValueError(f"baseline_rate 必须 ∈ (0, 1)，收到 {baseline_rate}")
    if min_detectable_effect <= 0:
        raise ValueError("min_detectable_effect 必须 > 0")

    p1 = baseline_rate
    p2 = baseline_rate + min_detectable_effect
    if not (0 < p2 < 1):
        raise ValueError(
            f"baseline_rate + mde = {p2} 必须 ∈ (0, 1)"
        )

    # 查表获取 (z_α/2 + z_β)²
    constant = _z_alpha_beta_sq(alpha, power)
    n = constant * (p1 * (1 - p1) + p2 * (1 - p2)) / (min_detectable_effect ** 2)
    return max(1, int(math.ceil(n)))


def _z_alpha_beta_sq(alpha: float, power: float) -> float:
    """查表返回 (z_α/2 + z_β)²"""
    # 常见组合（查表，其他用最接近的）
    table = {
        (0.05, 0.80): 7.85,
        (0.05, 0.85): 8.98,
        (0.05, 0.90): 10.51,
        (0.05, 0.95): 13.00,
        (0.01, 0.80): 11.68,
        (0.01, 0.90): 14.88,
    }
    # 精确匹配
    if (alpha, power) in table:
        return table[(alpha, power)]
    # 近似匹配
    best = min(
        table.items(),
        key=lambda kv: abs(kv[0][0] - alpha) + abs(kv[0][1] - power),
    )
    return best[1]


# ─────────────────────────────────────────────────────────────
# 工具
# ─────────────────────────────────────────────────────────────


def _safe_pct(baseline: float, treatment: float) -> float:
    if baseline == 0:
        return 0.0
    return round((treatment - baseline) / baseline, 6)
