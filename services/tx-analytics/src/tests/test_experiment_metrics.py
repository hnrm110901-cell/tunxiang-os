"""Sprint G — G3 Welch's t-test 单测（Tier 3）。

参照值用 hardcoded 数据计算（参考 scipy.stats.ttest_ind(equal_var=False)），
保证误差 < 1%。
"""

from __future__ import annotations

from ..experiment.metrics import welch_t_test


def test_welch_t_test_known_dataset_matches_scipy_within_1pct() -> None:
    """已知数据集 — scipy.stats.ttest_ind(a, b, equal_var=False) 比对。

    sample_a 与 sample_b 数据点：
      a = [9.8, 10.2, 10.0, 9.9, 10.1, 10.3, 9.7, 10.4]
      b = [10.5, 10.8, 11.0, 10.7, 11.2, 11.1, 10.9, 11.3]
    Reference（手算 + scipy.stats.ttest_ind(a, b, equal_var=False) 一致）：
      t ≈ 6.9289, df ≈ 13.898, p ≈ 7.27e-06

    本实现允许 t 误差 < 1%，p_value 数量级一致（< 1e-4）。
    """
    a = [9.8, 10.2, 10.0, 9.9, 10.1, 10.3, 9.7, 10.4]
    b = [10.5, 10.8, 11.0, 10.7, 11.2, 11.1, 10.9, 11.3]
    result = welch_t_test(a, b)

    # 期望 t > 0（b 均值更高，diff = mean_b - mean_a）
    assert result.t_statistic > 0
    # |t| ≈ 6.9289 — 允许 1% 相对误差
    assert abs(abs(result.t_statistic) - 6.9289) / 6.9289 < 0.01
    # df ≈ 13.898
    assert abs(result.df - 13.898) < 0.5
    # p_value ≈ 7.3e-6（非常小）— 数量级一致
    assert result.p_value < 1e-4
    assert result.is_significant_at_005 is True


def test_significant_when_p_below_005() -> None:
    """两样本均值差大且方差小 → 显著。"""
    a = [1.0, 1.1, 0.9, 1.0, 1.05]
    b = [2.0, 2.1, 1.95, 2.05, 2.0]
    r = welch_t_test(a, b)
    assert r.p_value < 0.05
    assert r.is_significant_at_005 is True


def test_not_significant_when_p_above_005() -> None:
    """两样本几乎重合 → 不显著。"""
    a = [1.0, 1.1, 0.9, 1.05, 0.95, 1.02]
    b = [1.05, 0.98, 1.03, 1.0, 1.07, 0.97]
    r = welch_t_test(a, b)
    assert r.p_value > 0.05
    assert r.is_significant_at_005 is False


def test_small_sample_returns_safe_default() -> None:
    """样本 < 2 时安全返回不显著。"""
    r = welch_t_test([1.0], [2.0, 3.0])
    assert r.p_value == 1.0
    assert r.is_significant_at_005 is False


def test_zero_variance_safe() -> None:
    """两组都为常数 → t=0 或 NaN 路径，p=1。"""
    r = welch_t_test([1.0, 1.0, 1.0], [1.0, 1.0, 1.0])
    assert r.p_value == 1.0
    assert r.is_significant_at_005 is False


def test_cohens_d_direction() -> None:
    """diff > 0 → Cohen's d > 0。"""
    a = [1.0, 1.0, 1.1, 0.9, 1.05]
    b = [3.0, 3.1, 2.9, 3.05, 2.95]
    r = welch_t_test(a, b)
    assert r.effect_size_cohens_d > 0
    # 大效应量
    assert r.effect_size_cohens_d > 2.0


def test_ci_95_contains_diff() -> None:
    """CI 95 必须包含点估计 diff = mean_b - mean_a。"""
    a = [10.0, 10.5, 9.8, 10.2, 10.1]
    b = [11.0, 11.3, 10.8, 11.2, 11.1]
    r = welch_t_test(a, b)
    diff = r.mean_b - r.mean_a
    assert r.ci_95_low <= diff <= r.ci_95_high
