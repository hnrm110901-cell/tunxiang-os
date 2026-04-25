"""Sprint G — G1 纯函数分桶单测（Tier 3）。"""

from __future__ import annotations

from ..experiment.assignment import (
    CONTROL_BUCKET,
    Variant,
    assign_bucket,
)


def test_pure_function_same_input_same_bucket() -> None:
    """纯函数：相同输入永远相同输出（跑 100 次完全一致）。"""
    variants = [
        Variant(name="control", weight=5000),
        Variant(name="variant_a", weight=5000),
    ]
    results = [
        assign_bucket("checkout.v2", "user_42", variants, "seed_alpha")
        for _ in range(100)
    ]
    buckets = {r.bucket for r in results}
    positions = {r.bucket_position for r in results}
    assert len(buckets) == 1
    assert len(positions) == 1


def test_bucket_distribution_within_tolerance() -> None:
    """10000 次跑，control/variant_a 各占 ±2% 范围。"""
    variants = [
        Variant(name="control", weight=5000),
        Variant(name="variant_a", weight=5000),
    ]
    counts: dict[str, int] = {"control": 0, "variant_a": 0}
    for i in range(10000):
        result = assign_bucket(
            "checkout.v2", f"user_{i}", variants, "seed_uniformity"
        )
        counts[result.bucket] += 1

    for bucket_name, count in counts.items():
        # 期望 5000，允许 ±400（4%）
        assert abs(count - 5000) < 400, (
            f"{bucket_name} 分桶 {count} 次，超出 ±4% 容差"
        )


def test_variant_weights_respected() -> None:
    """70/20/10 权重，10000 次跑，比例分别落在容差内。"""
    variants = [
        Variant(name="control", weight=7000),
        Variant(name="variant_a", weight=2000),
        Variant(name="variant_b", weight=1000),
    ]
    counts: dict[str, int] = {"control": 0, "variant_a": 0, "variant_b": 0}
    for i in range(10000):
        result = assign_bucket(
            "pricing.v3", f"device_{i}", variants, "seed_weighted"
        )
        counts[result.bucket] += 1

    assert abs(counts["control"] - 7000) < 400
    assert abs(counts["variant_a"] - 2000) < 300
    assert abs(counts["variant_b"] - 1000) < 200


def test_empty_variants_returns_control() -> None:
    """variants 为空 → control + reason='no_variants'。"""
    result = assign_bucket("anything", "user_1", [], "seed_x")
    assert result.bucket == CONTROL_BUCKET
    assert result.fallback_reason == "no_variants"


def test_zero_weight_returns_control() -> None:
    """所有 weight=0 → control + reason='zero_weight'。"""
    variants = [
        Variant(name="control", weight=0),
        Variant(name="variant_a", weight=0),
    ]
    result = assign_bucket("anything", "user_1", variants, "seed_x")
    assert result.bucket == CONTROL_BUCKET
    assert result.fallback_reason == "zero_weight"


def test_weight_normalization_recorded() -> None:
    """权重之和不为 10000 时归一并记录 fallback_reason。"""
    variants = [
        Variant(name="control", weight=50),  # 50/100 = 50%
        Variant(name="variant_a", weight=50),
    ]
    result = assign_bucket("normalize.test", "user_1", variants, "seed_x")
    assert result.bucket in {"control", "variant_a"}
    assert result.fallback_reason == "weight_normalized"


def test_invalid_subject_id_returns_control() -> None:
    variants = [Variant(name="variant_a", weight=10000)]
    # 空字符串 subject_id
    result = assign_bucket("k", "", variants, "seed")
    assert result.bucket == CONTROL_BUCKET
    assert result.fallback_reason == "invalid_subject_id"


def test_seed_changes_buckets() -> None:
    """同 subject 不同 seed → 桶可能不同（保护可重放性的反向证明）。"""
    variants = [
        Variant(name="control", weight=5000),
        Variant(name="variant_a", weight=5000),
    ]
    diff = 0
    for i in range(200):
        a = assign_bucket("ex", f"user_{i}", variants, "seed_one")
        b = assign_bucket("ex", f"user_{i}", variants, "seed_two")
        if a.bucket != b.bucket:
            diff += 1
    assert 30 < diff < 170  # 不同 seed 大致一半翻面
