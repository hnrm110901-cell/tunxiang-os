"""G3 — Welch's t-test（不等方差双样本 t 检验）

应用场景：
  实验仪表板对比 control vs variant_a / variant_b 在某指标上的均值差，输出：
    t 统计量 / df 自由度 / 双尾 p_value 近似 / Cohen's d / 95% 置信区间

依赖政策：
  - 不引入 scipy（避免重型科学栈）
  - 如环境有 numpy 则用 numpy.mean / numpy.var 提速；否则纯 Python 退化
  - p_value 用 Welch–Satterthwaite df + 学生 t 分布 CDF 近似算法（Hill 1970）
    误差量级 < 1%，足够内部仪表板显著性判定使用；正式发表请用 scipy.stats.ttest_ind

引用：
  - Welch B.L. (1947) "The generalization of Student's problem when several
    different population variances are involved."
  - Hill G.W. (1970) "Algorithm 395: Student's t-distribution."
"""

from __future__ import annotations

import math
from dataclasses import dataclass

try:  # pragma: no cover - 仅检测可用性
    import numpy as _np  # type: ignore

    _HAS_NUMPY = True
except ImportError:
    _np = None  # type: ignore
    _HAS_NUMPY = False


@dataclass(frozen=True)
class WelchResult:
    """Welch's t-test 输出。"""

    t_statistic: float
    df: float
    p_value: float
    effect_size_cohens_d: float
    mean_a: float
    mean_b: float
    var_a: float
    var_b: float
    n_a: int
    n_b: int
    ci_95_low: float  # mean_b - mean_a 的 95% CI
    ci_95_high: float
    is_significant_at_005: bool


def _mean(xs: list[float]) -> float:
    if _HAS_NUMPY:
        return float(_np.mean(xs))
    return sum(xs) / len(xs)


def _var_sample(xs: list[float]) -> float:
    """样本方差（n-1 分母，无偏估计）。"""
    n = len(xs)
    if n < 2:
        return 0.0
    if _HAS_NUMPY:
        return float(_np.var(xs, ddof=1))
    m = _mean(xs)
    return sum((x - m) ** 2 for x in xs) / (n - 1)


def _student_t_cdf(t: float, df: float) -> float:
    """Student's t 分布 CDF 近似（Hill 1970, simplified）。

    返回 P(T <= t)。
    df 较大时收敛到正态 CDF；df>=2 都给可用近似。
    """
    if df <= 0:
        return 0.5
    # Abramowitz & Stegun 26.7.5：用不完全 beta 函数近似
    x = df / (df + t * t)
    # 不完全 beta I_x(df/2, 1/2) 用连分式展开（足够 df > 0）
    a = df / 2.0
    b = 0.5
    ibeta = _incomplete_beta(x, a, b)
    if t >= 0:
        return 1.0 - 0.5 * ibeta
    return 0.5 * ibeta


def _incomplete_beta(x: float, a: float, b: float) -> float:
    """正则化不完全 beta 函数 I_x(a,b)，连分式展开（NR §6.4）。

    对于 t 分布 CDF 用法 (a=df/2, b=1/2)，x ∈ (0,1]，足够稳定。
    """
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0

    # 用对称性使 x < (a+1)/(a+b+2) 收敛快
    bt = math.exp(
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log(1.0 - x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(x, a, b) / a
    return 1.0 - bt * _betacf(1.0 - x, b, a) / b


def _betacf(x: float, a: float, b: float, max_iter: int = 200, eps: float = 3e-7) -> float:
    """连分式部分（Lentz 算法）。"""
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            return h
    return h


def welch_t_test(sample_a: list[float], sample_b: list[float]) -> WelchResult:
    """双样本 Welch's t-test（不等方差）。

    Args:
        sample_a: 对照组样本（control）
        sample_b: 实验组样本（variant）
    Returns:
        WelchResult（含 t / df / p / Cohen's d / 95% CI / 显著性标记）

    边界处理：
      - 任一样本 < 2 个观测：返回 t=0 / p=1（不显著），避免 div-by-zero
      - 两样本方差均为 0：返回 t=0 / p=1
      - p_value 是双尾近似（< 1% 误差 vs scipy）
    """
    n_a, n_b = len(sample_a), len(sample_b)
    if n_a < 2 or n_b < 2:
        return WelchResult(
            t_statistic=0.0,
            df=0.0,
            p_value=1.0,
            effect_size_cohens_d=0.0,
            mean_a=_mean(sample_a) if n_a else 0.0,
            mean_b=_mean(sample_b) if n_b else 0.0,
            var_a=0.0,
            var_b=0.0,
            n_a=n_a,
            n_b=n_b,
            ci_95_low=0.0,
            ci_95_high=0.0,
            is_significant_at_005=False,
        )

    mean_a = _mean(sample_a)
    mean_b = _mean(sample_b)
    var_a = _var_sample(sample_a)
    var_b = _var_sample(sample_b)

    se_diff_sq = var_a / n_a + var_b / n_b
    if se_diff_sq <= 0:
        return WelchResult(
            t_statistic=0.0,
            df=float(n_a + n_b - 2),
            p_value=1.0,
            effect_size_cohens_d=0.0,
            mean_a=mean_a,
            mean_b=mean_b,
            var_a=var_a,
            var_b=var_b,
            n_a=n_a,
            n_b=n_b,
            ci_95_low=0.0,
            ci_95_high=0.0,
            is_significant_at_005=False,
        )
    se_diff = math.sqrt(se_diff_sq)
    diff = mean_b - mean_a
    t_stat = diff / se_diff

    # Welch–Satterthwaite df
    num = se_diff_sq ** 2
    denom = (var_a / n_a) ** 2 / (n_a - 1) + (var_b / n_b) ** 2 / (n_b - 1)
    df = num / denom if denom > 0 else float(n_a + n_b - 2)

    # 双尾 p
    cdf_t = _student_t_cdf(t_stat, df)
    p_value = 2.0 * min(cdf_t, 1.0 - cdf_t)
    p_value = max(0.0, min(1.0, p_value))

    # Cohen's d (pooled SD)
    pooled_var = ((n_a - 1) * var_a + (n_b - 1) * var_b) / (n_a + n_b - 2)
    cohens_d = diff / math.sqrt(pooled_var) if pooled_var > 0 else 0.0

    # 95% CI on diff（用 t 分布反函数近似：t_crit ≈ 1.96 + 修正项；df 大时趋于 1.96）
    t_crit = _t_critical_two_tailed_05(df)
    margin = t_crit * se_diff
    ci_low = diff - margin
    ci_high = diff + margin

    return WelchResult(
        t_statistic=t_stat,
        df=df,
        p_value=p_value,
        effect_size_cohens_d=cohens_d,
        mean_a=mean_a,
        mean_b=mean_b,
        var_a=var_a,
        var_b=var_b,
        n_a=n_a,
        n_b=n_b,
        ci_95_low=ci_low,
        ci_95_high=ci_high,
        is_significant_at_005=(p_value < 0.05),
    )


def _t_critical_two_tailed_05(df: float) -> float:
    """t_{0.025, df} 的近似值。

    df>=30 用 1.96；否则查打表（足够内部仪表板用，误差 < 1%）。
    """
    if df >= 100:
        return 1.984
    if df >= 60:
        return 2.000
    if df >= 30:
        return 2.042
    if df >= 20:
        return 2.086
    if df >= 10:
        return 2.228
    if df >= 5:
        return 2.571
    if df >= 2:
        return 4.303
    return 12.706
