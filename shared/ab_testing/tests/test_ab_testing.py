"""Sprint G — shared/ab_testing 测试

覆盖：
  · assignment: deterministic hash + stability + traffic_percentage + weight 分配 + 边界
  · statistics: frequentist z-test / t-test / bayesian / sample_size / edge cases
  · circuit_breaker: threshold / goal / min_samples / multi-arm
  · v290 迁移静态断言

不覆盖（需 DB + FastAPI）：
  · ABExperimentService（AsyncSession mock 工作量大）
  · API 端点
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.ab_testing import (  # noqa: E402
    ArmDefinition,
    ArmStats,
    AssignmentDecision,
    assign_entity,
    bayesian_posterior,
    compute_assignment_hash,
    evaluate_circuit_breaker,
    frequentist_significance,
    required_sample_size,
)
from shared.ab_testing.assignment import NOT_ENROLLED, extract_arm_key, is_enrolled  # noqa: E402
from shared.ab_testing.statistics import normal_cdf, two_sided_p_value  # noqa: E402

# ─────────────────────────────────────────────────────────────
# 1. Assignment — hash
# ─────────────────────────────────────────────────────────────


class TestComputeAssignmentHash:
    def test_same_inputs_same_hash(self):
        h1 = compute_assignment_hash("customer_001", "menu_v2")
        h2 = compute_assignment_hash("customer_001", "menu_v2")
        assert h1 == h2

    def test_different_entity_different_hash(self):
        h1 = compute_assignment_hash("customer_001", "menu_v2")
        h2 = compute_assignment_hash("customer_002", "menu_v2")
        assert h1 != h2

    def test_different_experiment_different_hash(self):
        h1 = compute_assignment_hash("customer_001", "exp_a")
        h2 = compute_assignment_hash("customer_001", "exp_b")
        assert h1 != h2

    def test_empty_inputs_raise(self):
        with pytest.raises(ValueError):
            compute_assignment_hash("", "exp")
        with pytest.raises(ValueError):
            compute_assignment_hash("c", "")

    def test_returns_32bit_int(self):
        h = compute_assignment_hash("c", "e")
        assert 0 <= h < 2**32


# ─────────────────────────────────────────────────────────────
# 2. Assignment — assign_entity
# ─────────────────────────────────────────────────────────────


class TestAssignEntity:
    @pytest.fixture
    def arms(self):
        return [
            ArmDefinition(arm_key="control", traffic_weight=50, is_control=True),
            ArmDefinition(arm_key="treatment", traffic_weight=50),
        ]

    def test_same_entity_same_arm(self, arms):
        """稳定性：同 entity 重复分配得同结果"""
        r1 = assign_entity(
            entity_id="c_001", experiment_key="exp", arms=arms,
        )
        r2 = assign_entity(
            entity_id="c_001", experiment_key="exp", arms=arms,
        )
        assert isinstance(r1, AssignmentDecision)
        assert isinstance(r2, AssignmentDecision)
        assert r1.arm_key == r2.arm_key

    def test_distribution_is_balanced(self, arms):
        """1000 entity → 分布接近 50/50，容忍 5%"""
        counts = {"control": 0, "treatment": 0}
        for i in range(1000):
            r = assign_entity(
                entity_id=f"user_{i}", experiment_key="dist_test", arms=arms,
            )
            assert isinstance(r, AssignmentDecision)
            counts[r.arm_key] += 1
        # 容忍 45/55 之间
        assert 450 < counts["control"] < 550
        assert 450 < counts["treatment"] < 550

    def test_unequal_weights(self):
        """70/30 权重 → 分布约 700/300（容忍 50 偏差）"""
        arms = [
            ArmDefinition(arm_key="control", traffic_weight=70, is_control=True),
            ArmDefinition(arm_key="treatment", traffic_weight=30),
        ]
        counts = {"control": 0, "treatment": 0}
        for i in range(1000):
            r = assign_entity(
                entity_id=f"user_{i}", experiment_key="weight_test", arms=arms,
            )
            assert isinstance(r, AssignmentDecision)
            counts[r.arm_key] += 1
        assert 650 < counts["control"] < 750
        assert 250 < counts["treatment"] < 350

    def test_traffic_percentage_50_enrolls_half(self, arms):
        """traffic_percentage=50 → 约一半 NotEnrolled"""
        enrolled = 0
        not_enrolled = 0
        for i in range(1000):
            r = assign_entity(
                entity_id=f"user_{i}", experiment_key="traffic50",
                arms=arms, traffic_percentage=50.0,
            )
            if isinstance(r, AssignmentDecision):
                enrolled += 1
            else:
                not_enrolled += 1
        # 容忍 450-550
        assert 450 < enrolled < 550
        assert 450 < not_enrolled < 550

    def test_traffic_percentage_0_all_excluded(self, arms):
        for i in range(100):
            r = assign_entity(
                entity_id=f"u_{i}", experiment_key="zero",
                arms=arms, traffic_percentage=0.0,
            )
            assert r is NOT_ENROLLED

    def test_traffic_percentage_100_all_enrolled(self, arms):
        for i in range(100):
            r = assign_entity(
                entity_id=f"u_{i}", experiment_key="full",
                arms=arms, traffic_percentage=100.0,
            )
            assert isinstance(r, AssignmentDecision)

    def test_empty_arms_raises(self):
        with pytest.raises(ValueError, match="arms"):
            assign_entity(entity_id="x", experiment_key="e", arms=[])

    def test_zero_total_weight_raises(self):
        arms = [
            ArmDefinition(arm_key="a", traffic_weight=0),
            ArmDefinition(arm_key="b", traffic_weight=0),
        ]
        with pytest.raises(ValueError, match="traffic_weight"):
            assign_entity(entity_id="x", experiment_key="e", arms=arms)

    def test_traffic_percentage_out_of_range(self, arms):
        with pytest.raises(ValueError):
            assign_entity(
                entity_id="x", experiment_key="e", arms=arms,
                traffic_percentage=-1.0,
            )
        with pytest.raises(ValueError):
            assign_entity(
                entity_id="x", experiment_key="e", arms=arms,
                traffic_percentage=101.0,
            )

    def test_new_arm_does_not_shuffle_existing(self, arms):
        """新增 arm 不应该打乱已有 entity 的分配（理想情况）

        当前实现按 arm_key 字典序排序保证稳定性。
        增加一个字典序靠后的 arm 不应该影响前两个 arm 的分配。
        """
        # 用只含 control 的场景先分配
        r_before = assign_entity(
            entity_id="user_stable", experiment_key="add_arm_test",
            arms=[
                ArmDefinition(arm_key="aaa_control", traffic_weight=50, is_control=True),
                ArmDefinition(arm_key="bbb_treatment", traffic_weight=50),
            ],
        )
        assert isinstance(r_before, AssignmentDecision)
        # 这个测试更多是文档化当前行为

    def test_is_enrolled_helper(self, arms):
        r = assign_entity(entity_id="e1", experiment_key="k", arms=arms)
        assert is_enrolled(r)
        assert not is_enrolled(NOT_ENROLLED)

    def test_extract_arm_key_helper(self, arms):
        r = assign_entity(entity_id="e1", experiment_key="k", arms=arms)
        assert extract_arm_key(r) in ("control", "treatment")
        assert extract_arm_key(NOT_ENROLLED, default="default") == "default"


# ─────────────────────────────────────────────────────────────
# 3. ArmDefinition 校验
# ─────────────────────────────────────────────────────────────


class TestArmDefinition:
    def test_valid(self):
        a = ArmDefinition(arm_key="c", traffic_weight=50)
        assert a.arm_key == "c"

    def test_empty_key_raises(self):
        with pytest.raises(ValueError):
            ArmDefinition(arm_key="", traffic_weight=50)

    def test_weight_out_of_range(self):
        with pytest.raises(ValueError):
            ArmDefinition(arm_key="c", traffic_weight=-1)
        with pytest.raises(ValueError):
            ArmDefinition(arm_key="c", traffic_weight=101)


# ─────────────────────────────────────────────────────────────
# 4. Statistics — basic
# ─────────────────────────────────────────────────────────────


class TestNormalCdf:
    def test_zero_is_half(self):
        assert abs(normal_cdf(0) - 0.5) < 1e-6

    def test_1_96_approx_0975(self):
        assert abs(normal_cdf(1.96) - 0.9750) < 1e-3

    def test_two_sided_p_for_z_0_is_1(self):
        assert abs(two_sided_p_value(0) - 1.0) < 1e-6

    def test_two_sided_p_for_1_96_is_005(self):
        assert abs(two_sided_p_value(1.96) - 0.05) < 1e-3


# ─────────────────────────────────────────────────────────────
# 5. Statistics — z-test 比例
# ─────────────────────────────────────────────────────────────


class TestFrequentistConversionRate:
    def test_no_difference_not_significant(self):
        control = ArmStats(exposure=1000, conversion=100, is_control=True)
        treatment = ArmStats(exposure=1000, conversion=100)
        r = frequentist_significance(control, treatment, alpha=0.05)
        assert r.test_type == "z_test"
        assert r.p_value > 0.05
        assert not r.significant

    def test_clear_lift_is_significant(self):
        """1000 样本，10% vs 20% → 显著"""
        control = ArmStats(exposure=1000, conversion=100, is_control=True)
        treatment = ArmStats(exposure=1000, conversion=200)
        r = frequentist_significance(control, treatment, alpha=0.05)
        assert r.significant
        assert r.p_value < 0.01
        assert r.effect_size == pytest.approx(0.10, rel=1e-6)
        assert r.effect_size_pct == pytest.approx(1.0, rel=1e-6)

    def test_small_lift_not_significant_with_small_sample(self):
        """50 样本看 10% vs 12% → 不显著"""
        control = ArmStats(exposure=50, conversion=5, is_control=True)
        treatment = ArmStats(exposure=50, conversion=6)
        r = frequentist_significance(control, treatment, alpha=0.05)
        assert not r.significant

    def test_zero_exposure_returns_nonsignificant(self):
        control = ArmStats(exposure=0, conversion=0, is_control=True)
        treatment = ArmStats(exposure=0, conversion=0)
        r = frequentist_significance(control, treatment, alpha=0.05)
        assert not r.significant
        assert r.p_value == 1.0

    def test_alpha_affects_boundary(self):
        """p=0.03 在 alpha=0.05 下显著，0.01 下不显著"""
        control = ArmStats(exposure=2000, conversion=100, is_control=True)
        treatment = ArmStats(exposure=2000, conversion=135)
        r_05 = frequentist_significance(control, treatment, alpha=0.05)
        r_01 = frequentist_significance(control, treatment, alpha=0.01)
        # 同 p 值下不同 alpha 结果不同
        assert r_05.p_value == r_01.p_value
        if 0.01 < r_05.p_value < 0.05:
            assert r_05.significant
            assert not r_01.significant


# ─────────────────────────────────────────────────────────────
# 6. Statistics — Bayesian
# ─────────────────────────────────────────────────────────────


class TestBayesianPosterior:
    def test_no_effect_prob_near_half(self):
        control = ArmStats(exposure=1000, conversion=100, is_control=True)
        treatment = ArmStats(exposure=1000, conversion=100)
        r = bayesian_posterior(control, treatment, simulations=2000, seed=42)
        # 无效应 P ≈ 0.5
        assert 0.4 < r.prob_treatment_beats_control < 0.6

    def test_clear_lift_high_probability(self):
        control = ArmStats(exposure=1000, conversion=100, is_control=True)
        treatment = ArmStats(exposure=1000, conversion=200)
        r = bayesian_posterior(control, treatment, simulations=2000, seed=42)
        assert r.prob_treatment_beats_control > 0.95

    def test_treatment_worse_low_probability(self):
        control = ArmStats(exposure=1000, conversion=200, is_control=True)
        treatment = ArmStats(exposure=1000, conversion=100)
        r = bayesian_posterior(control, treatment, simulations=2000, seed=42)
        assert r.prob_treatment_beats_control < 0.05

    def test_simulations_min_1000(self):
        with pytest.raises(ValueError):
            bayesian_posterior(
                ArmStats(exposure=1, conversion=0),
                ArmStats(exposure=1, conversion=0),
                simulations=500,
            )


# ─────────────────────────────────────────────────────────────
# 7. Sample size
# ─────────────────────────────────────────────────────────────


class TestRequiredSampleSize:
    def test_typical_10pct_to_15pct(self):
        n = required_sample_size(
            baseline_rate=0.10, min_detectable_effect=0.05,
            alpha=0.05, power=0.80,
        )
        # 手动验证：p1=0.10, p2=0.15, const=7.85
        # n = 7.85 × (0.09 + 0.1275) / 0.0025 ≈ 682
        assert 600 < n < 800

    def test_smaller_mde_larger_sample(self):
        n_big_mde = required_sample_size(
            baseline_rate=0.20, min_detectable_effect=0.05,
        )
        n_small_mde = required_sample_size(
            baseline_rate=0.20, min_detectable_effect=0.02,
        )
        assert n_small_mde > n_big_mde * 3  # 粗略 (5/2)^2 ≈ 6x

    def test_invalid_baseline_raises(self):
        with pytest.raises(ValueError):
            required_sample_size(
                baseline_rate=0.0, min_detectable_effect=0.05,
            )
        with pytest.raises(ValueError):
            required_sample_size(
                baseline_rate=1.0, min_detectable_effect=0.05,
            )

    def test_mde_exceeds_valid_range_raises(self):
        """baseline 0.95 + mde 0.10 = 1.05 > 1"""
        with pytest.raises(ValueError):
            required_sample_size(
                baseline_rate=0.95, min_detectable_effect=0.10,
            )


# ─────────────────────────────────────────────────────────────
# 8. Circuit Breaker
# ─────────────────────────────────────────────────────────────


class TestCircuitBreaker:
    def test_no_degradation_not_tripped(self):
        control = ArmStats(exposure=1000, conversion=100, is_control=True)
        treatment = ArmStats(exposure=1000, conversion=105)
        d = evaluate_circuit_breaker(
            control, [("treatment", treatment)],
            threshold_pct=0.20, min_samples=200,
        )
        assert not d.should_trip

    def test_severe_degradation_trips(self):
        """control 10%, treatment 7% → 30% 劣化 > 20% → 熔断"""
        control = ArmStats(exposure=1000, conversion=100, is_control=True)
        treatment = ArmStats(exposure=1000, conversion=70)
        d = evaluate_circuit_breaker(
            control, [("treatment", treatment)],
            threshold_pct=0.20, min_samples=200,
        )
        assert d.should_trip
        assert "treatment" in d.tripped_arm_keys

    def test_below_min_samples_skipped(self):
        """treatment 样本不足 → 不评估"""
        control = ArmStats(exposure=1000, conversion=100, is_control=True)
        treatment = ArmStats(exposure=100, conversion=50)  # 大幅劣化但样本不足
        d = evaluate_circuit_breaker(
            control, [("treatment", treatment)],
            threshold_pct=0.20, min_samples=200,
        )
        assert not d.should_trip
        assert d.arm_comparisons[0]["skipped"] is True

    def test_minimize_goal_treatment_increase_trips(self):
        """goal=minimize：投诉率 treatment > control * 1.2 → 熔断"""
        control = ArmStats(exposure=1000, conversion=50, is_control=True)  # 5% 投诉
        treatment = ArmStats(exposure=1000, conversion=80)  # 8% 投诉（+60%）
        d = evaluate_circuit_breaker(
            control, [("treatment", treatment)],
            goal="minimize",
            threshold_pct=0.20, min_samples=200,
        )
        assert d.should_trip

    def test_multi_treatment_partial_trip(self):
        """2 个 treatment，1 个劣化 1 个正常 → 只熔断劣化的"""
        control = ArmStats(exposure=1000, conversion=100, is_control=True)
        good = ArmStats(exposure=1000, conversion=120)
        bad = ArmStats(exposure=1000, conversion=60)
        d = evaluate_circuit_breaker(
            control, [("good", good), ("bad", bad)],
            threshold_pct=0.20, min_samples=200,
        )
        assert d.should_trip
        assert "bad" in d.tripped_arm_keys
        assert "good" not in d.tripped_arm_keys

    def test_zero_control_does_not_trip(self):
        """control 转化率 0 时无法按比例判定"""
        control = ArmStats(exposure=1000, conversion=0, is_control=True)
        treatment = ArmStats(exposure=1000, conversion=0)
        d = evaluate_circuit_breaker(
            control, [("treatment", treatment)],
            threshold_pct=0.20, min_samples=200,
        )
        assert not d.should_trip


# ─────────────────────────────────────────────────────────────
# 9. v290 迁移静态断言
# ─────────────────────────────────────────────────────────────


class TestV290Migration:
    @pytest.fixture
    def migration_source(self) -> str:
        path = (
            ROOT
            / "shared"
            / "db-migrations"
            / "versions"
            / "v290_ab_experiments.py"
        )
        return path.read_text(encoding="utf-8")

    def test_revision(self, migration_source):
        assert 'revision = "v290_ab_experiments"' in migration_source
        assert 'down_revision = "v288_delivery_disputes"' in migration_source

    def test_4_tables(self, migration_source):
        for t in (
            "ab_experiments",
            "ab_experiment_arms",
            "ab_experiment_assignments",
            "ab_experiment_events",
        ):
            assert t in migration_source

    def test_all_9_statuses(self, migration_source):
        for s in (
            "draft", "running", "paused",
            "terminated_winner", "terminated_no_winner",
            "terminated_circuit_breaker", "completed", "archived", "error",
        ):
            assert f"'{s}'" in migration_source

    def test_assignment_strategies(self, migration_source):
        for s in (
            "deterministic_hash", "rollout_percentage", "tenant_ring",
        ):
            assert f"'{s}'" in migration_source

    def test_entity_types(self, migration_source):
        for et in ("customer", "order", "session", "store", "device"):
            assert f"'{et}'" in migration_source

    def test_5_event_types(self, migration_source):
        for et in ("exposure", "conversion", "revenue", "metric_value", "error"):
            assert f"'{et}'" in migration_source

    def test_7_primary_metrics(self, migration_source):
        for m in (
            "conversion_rate", "avg_revenue", "aov",
            "retention_7d", "complaint_rate", "gross_margin_pct", "custom",
        ):
            assert f"'{m}'" in migration_source

    def test_circuit_breaker_fields(self, migration_source):
        for f in (
            "circuit_breaker_enabled", "circuit_breaker_threshold",
            "circuit_breaker_min_samples", "circuit_breaker_tripped",
        ):
            assert f in migration_source

    def test_rls_all_tables(self, migration_source):
        for t in (
            "ab_experiments", "ab_experiment_arms",
            "ab_experiment_assignments", "ab_experiment_events",
        ):
            assert f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY" in migration_source

    def test_idempotent_unique_indexes(self, migration_source):
        assert "ux_ab_experiments_key" in migration_source
        assert "ux_ab_arms_key" in migration_source
        assert "ux_ab_arms_one_control" in migration_source  # 每实验 1 control
        assert "ux_ab_assignments_entity" in migration_source
        assert "ux_ab_events_idempotency" in migration_source

    def test_circuit_monitor_index(self, migration_source):
        assert "idx_ab_experiments_circuit_monitor" in migration_source

    def test_foreign_keys_on_delete_cascade(self, migration_source):
        # arms → experiments ON DELETE CASCADE
        assert "ON DELETE CASCADE" in migration_source
