"""
心理距离分层模块 psychological_segmentation 单元测试 — B1·方向一
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest
from psychological_segmentation import (
    DISTANCE_STRATEGY,
    PsychologicalDistance,
    classify_psychological_distance,
    classify_with_strategy,
    get_distance_strategy,
)


# ── 枚举完整性 ────────────────────────────────────────────────────────────────


class TestDistanceStrategyStructure:
    def test_all_five_distances_defined(self):
        assert len(PsychologicalDistance) == 5

    def test_strategy_covers_all_distances(self):
        assert set(DISTANCE_STRATEGY.keys()) == set(PsychologicalDistance)

    def test_each_strategy_has_required_fields(self):
        required = {"description", "wrong_action", "right_action", "principle", "content_level"}
        for dist, strat in DISTANCE_STRATEGY.items():
            missing = required - set(strat.keys())
            assert not missing, f"{dist} 缺少字段: {missing}"

    def test_lost_reconstructed_requires_human_intervention(self):
        strat = DISTANCE_STRATEGY[PsychologicalDistance.LOST_RECONSTRUCTED]
        assert strat["content_level"] == "human_intervention"

    def test_near_distances_use_concrete_content(self):
        near_s = DISTANCE_STRATEGY[PsychologicalDistance.NEAR_SITUATIONAL]
        near_h = DISTANCE_STRATEGY[PsychologicalDistance.NEAR_HABIT_BREAK]
        assert near_s["content_level"] == "concrete"
        assert near_h["content_level"] == "concrete"

    def test_far_abstract_no_discount(self):
        """《怪诞行为学》：高折扣会拉低价格锚点，FAR_ABSTRACT 策略明确禁止折扣。"""
        strat = DISTANCE_STRATEGY[PsychologicalDistance.FAR_ABSTRACT]
        assert "折扣" in strat["wrong_action"] or "折扣" in strat["principle"]


# ── classify_psychological_distance 阈值测试 ─────────────────────────────────


class TestClassifyPsychologicalDistance:
    """
    比值 ratio = recency_days / avg_visit_interval：
      < 1.2  → NEAR_SITUATIONAL
      < 2.0  → NEAR_HABIT_BREAK
      < 3.5  → MID_FADING
      < 6.0  → FAR_ABSTRACT
      >= 6.0 → LOST_RECONSTRUCTED
    """

    def test_ratio_below_1_2_is_near_situational(self):
        # ratio = 5/7 = 0.71
        result = classify_psychological_distance(recency_days=5, avg_visit_interval=7.0)
        assert result == PsychologicalDistance.NEAR_SITUATIONAL

    def test_ratio_exactly_1_2_is_near_habit_break(self):
        # ratio = 12/10 = 1.2
        result = classify_psychological_distance(recency_days=12, avg_visit_interval=10.0)
        assert result == PsychologicalDistance.NEAR_HABIT_BREAK

    def test_ratio_between_1_2_and_2_0_is_near_habit_break(self):
        # ratio = 14/10 = 1.4
        result = classify_psychological_distance(recency_days=14, avg_visit_interval=10.0)
        assert result == PsychologicalDistance.NEAR_HABIT_BREAK

    def test_ratio_at_2_0_is_mid_fading(self):
        # ratio = 20/10 = 2.0
        result = classify_psychological_distance(recency_days=20, avg_visit_interval=10.0)
        assert result == PsychologicalDistance.MID_FADING

    def test_ratio_between_2_and_3_5_is_mid_fading(self):
        # ratio = 30/10 = 3.0
        result = classify_psychological_distance(recency_days=30, avg_visit_interval=10.0)
        assert result == PsychologicalDistance.MID_FADING

    def test_ratio_at_3_5_is_far_abstract(self):
        # ratio = 35/10 = 3.5
        result = classify_psychological_distance(recency_days=35, avg_visit_interval=10.0)
        assert result == PsychologicalDistance.FAR_ABSTRACT

    def test_ratio_at_6_is_lost_reconstructed(self):
        # ratio = 60/10 = 6.0
        result = classify_psychological_distance(recency_days=60, avg_visit_interval=10.0)
        assert result == PsychologicalDistance.LOST_RECONSTRUCTED

    def test_ratio_above_6_is_lost_reconstructed(self):
        # ratio = 90/7 ≈ 12.9
        result = classify_psychological_distance(recency_days=90, avg_visit_interval=7.0)
        assert result == PsychologicalDistance.LOST_RECONSTRUCTED

    def test_high_frequency_user_same_days_closer_distance(self):
        """高频用户（每7天来一次）30天未来 ratio=4.3，但低频用户（每30天来）ratio=1.0。"""
        high_freq = classify_psychological_distance(recency_days=30, avg_visit_interval=7.0)
        low_freq  = classify_psychological_distance(recency_days=30, avg_visit_interval=30.0)
        # 高频用户心理距离更远
        distances = [
            PsychologicalDistance.NEAR_SITUATIONAL,
            PsychologicalDistance.NEAR_HABIT_BREAK,
            PsychologicalDistance.MID_FADING,
            PsychologicalDistance.FAR_ABSTRACT,
            PsychologicalDistance.LOST_RECONSTRUCTED,
        ]
        assert distances.index(high_freq) > distances.index(low_freq)

    def test_interval_floor_at_1_prevents_division_by_zero(self):
        result = classify_psychological_distance(recency_days=5, avg_visit_interval=0.0)
        # 不应抛出异常，且 ratio=5/1=5 → FAR_ABSTRACT
        assert result == PsychologicalDistance.FAR_ABSTRACT

    def test_recent_interaction_reduces_distance(self):
        """最近有非消费互动（打开推送）应降低心理距离。"""
        without_interaction = classify_psychological_distance(
            recency_days=20, avg_visit_interval=10.0
        )
        with_interaction = classify_psychological_distance(
            recency_days=20, avg_visit_interval=10.0, last_interaction_days=3
        )
        distances = [
            PsychologicalDistance.NEAR_SITUATIONAL,
            PsychologicalDistance.NEAR_HABIT_BREAK,
            PsychologicalDistance.MID_FADING,
            PsychologicalDistance.FAR_ABSTRACT,
            PsychologicalDistance.LOST_RECONSTRUCTED,
        ]
        assert distances.index(with_interaction) <= distances.index(without_interaction)

    def test_interaction_beyond_recency_not_applied(self):
        """互动时间比消费时间还早，不应降低距离（last_interaction_days > recency_days）。"""
        base = classify_psychological_distance(recency_days=30, avg_visit_interval=10.0)
        with_old_interaction = classify_psychological_distance(
            recency_days=30, avg_visit_interval=10.0, last_interaction_days=35
        )
        # last_interaction_days > recency_days，不触发降距
        assert with_old_interaction == base


# ── get_distance_strategy 和 classify_with_strategy ─────────────────────────


class TestGetDistanceStrategy:
    def test_returns_correct_strategy(self):
        strat = get_distance_strategy(PsychologicalDistance.NEAR_SITUATIONAL)
        assert strat["content_level"] == "concrete"

    def test_mid_fading_strategy_uses_person(self):
        strat = get_distance_strategy(PsychologicalDistance.MID_FADING)
        assert strat["content_level"] == "concrete_person"


class TestClassifyWithStrategy:
    def test_returns_distance_and_strategy(self):
        result = classify_with_strategy(recency_days=5, avg_visit_interval=7.0)
        assert "distance" in result
        assert "strategy" in result

    def test_distance_matches_strategy(self):
        result = classify_with_strategy(recency_days=5, avg_visit_interval=7.0)
        assert result["distance"] == PsychologicalDistance.NEAR_SITUATIONAL
        assert result["strategy"]["content_level"] == "concrete"

    def test_lost_reconstructed_strategy_says_human(self):
        result = classify_with_strategy(recency_days=90, avg_visit_interval=7.0)
        assert result["distance"] == PsychologicalDistance.LOST_RECONSTRUCTED
        assert result["strategy"]["content_level"] == "human_intervention"
