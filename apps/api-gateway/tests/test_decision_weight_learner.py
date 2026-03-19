"""
DecisionWeightLearner 单元测试

覆盖：
  - compute_accuracy_ratio: 三种 outcome 的边界情况
  - compute_gradient: 超预期/不达预期/持平 的梯度方向
  - apply_gradient: clip + normalize 保证性质
  - 组合：多轮更新后权重收敛方向
  - DecisionWeightLearner.get_weights: DB miss → 返回默认值
  - DecisionWeightLearner.update_from_feedback: 端到端 mock DB
"""

import os
for _k, _v in {
    "DATABASE_URL":          "postgresql+asyncpg://test:test@localhost/test",
    "REDIS_URL":             "redis://localhost:6379/0",
    "CELERY_BROKER_URL":     "redis://localhost:6379/0",
    "CELERY_RESULT_BACKEND": "redis://localhost:6379/0",
    "SECRET_KEY":            "test-secret-key",
    "JWT_SECRET":            "test-jwt-secret",
}.items():
    os.environ.setdefault(_k, _v)

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.services.decision_weight_learner import (
    DEFAULT_WEIGHTS,
    LEARNING_RATE,
    WEIGHT_MAX,
    WEIGHT_MIN,
    DecisionWeightLearner,
    apply_gradient,
    compute_accuracy_ratio,
    compute_gradient,
)


# ═══════════════════════════════════════════════════════════════════════════════
# compute_accuracy_ratio
# ═══════════════════════════════════════════════════════════════════════════════

class TestComputeAccuracyRatio:
    def test_success_over_expected_capped_at_2(self):
        assert compute_accuracy_ratio("success", 3000, 1000) == 2.0

    def test_success_exact_match(self):
        assert compute_accuracy_ratio("success", 1000, 1000) == 1.0

    def test_success_under_expected(self):
        ratio = compute_accuracy_ratio("success", 500, 1000)
        assert ratio == 0.5

    def test_partial_half_score(self):
        ratio = compute_accuracy_ratio("partial", 1000, 1000)
        assert ratio == 0.5  # min(1.0, 1.0 * 0.5)

    def test_partial_over_cap(self):
        ratio = compute_accuracy_ratio("partial", 3000, 1000)
        assert ratio == 1.0  # min(1.0, 3.0 * 0.5)

    def test_failure_always_zero(self):
        assert compute_accuracy_ratio("failure", 9999, 1) == 0.0

    def test_zero_expected_saving_handled(self):
        # expected_saving=0 → max(0, 1.0) = 1.0 in denominator
        ratio = compute_accuracy_ratio("success", 500, 0)
        assert ratio == min(2.0, 500.0)  # = 2.0 (capped)


# ═══════════════════════════════════════════════════════════════════════════════
# compute_gradient
# ═══════════════════════════════════════════════════════════════════════════════

class TestComputeGradient:
    def test_above_mean_score_gets_positive_gradient_on_success(self):
        # 新算法使用相对偏差：高于均值的维度在成功时梯度 > 0
        # scores = {financial:90, urgency:30, confidence:70, execution:50}, mean=60
        # financial 高于均值(90>60) → success → gradient > 0
        grad = compute_gradient(DEFAULT_WEIGHTS, {
            "financial": 90, "urgency": 30, "confidence": 70, "execution": 50
        }, 1.5)
        assert grad["financial"] > 0   # above mean, success
        assert grad["urgency"] < 0     # below mean, success

    def test_above_mean_score_gets_negative_gradient_on_failure(self):
        # 高于均值的维度在失败时梯度 < 0（该维度误判了方向）
        grad = compute_gradient(DEFAULT_WEIGHTS, {
            "financial": 90, "urgency": 30, "confidence": 70, "execution": 50
        }, 0.0)
        assert grad["financial"] < 0   # above mean, failure
        assert grad["urgency"] > 0     # below mean, failure

    def test_exact_expectation_zero_gradient(self):
        # accuracy_ratio=1 → advantage=0 → all gradients = 0
        grad = compute_gradient(DEFAULT_WEIGHTS, {
            "financial": 80, "urgency": 70, "confidence": 90, "execution": 60
        }, 1.0)
        assert all(abs(v) < 1e-10 for v in grad.values())

    def test_gradients_sum_to_zero(self):
        # 相对偏差法使梯度之和 ≈ 0（不改变权重总量）
        grad = compute_gradient(DEFAULT_WEIGHTS, {
            "financial": 80, "urgency": 50, "confidence": 90, "execution": 40
        }, 1.5)
        assert abs(sum(grad.values())) < 1e-9

    def test_high_above_mean_gets_larger_magnitude(self):
        # financial 远高于均值 → 梯度绝对值大于接近均值的维度
        grad = compute_gradient(DEFAULT_WEIGHTS, {
            "financial": 95, "urgency": 55, "confidence": 60, "execution": 50
        }, 1.5)
        assert abs(grad["financial"]) > abs(grad["urgency"])


# ═══════════════════════════════════════════════════════════════════════════════
# apply_gradient
# ═══════════════════════════════════════════════════════════════════════════════

class TestApplyGradient:
    def test_weights_sum_to_one(self):
        grad = {"financial": 0.05, "urgency": -0.03, "confidence": 0.02, "execution": -0.01}
        new_w = apply_gradient(DEFAULT_WEIGHTS, grad)
        assert abs(sum(new_w.values()) - 1.0) < 1e-5

    def test_all_weights_within_bounds(self):
        # 极端梯度，迭代 clip+normalize 后仍应在边界内
        # 用相对偏差梯度（sum≈0），避免单维度极端值
        grad = {"financial": 0.5, "urgency": -0.5, "confidence": 0.3, "execution": -0.3}
        new_w = apply_gradient(DEFAULT_WEIGHTS, grad)
        assert all(WEIGHT_MIN - 1e-6 <= v <= WEIGHT_MAX + 1e-6 for v in new_w.values())
        assert abs(sum(new_w.values()) - 1.0) < 1e-5

    def test_zero_gradient_preserves_direction(self):
        zero_grad = {k: 0.0 for k in DEFAULT_WEIGHTS}
        new_w = apply_gradient(DEFAULT_WEIGHTS, zero_grad)
        # 无梯度 → 权重比例不变（归一化后与原始相同）
        for k in DEFAULT_WEIGHTS:
            assert abs(new_w[k] - DEFAULT_WEIGHTS[k]) < 1e-5

    def test_successful_decision_increases_dominant_dimension(self):
        """
        财务分很高的决策执行成功 → 多轮后 financial 权重应上升
        """
        weights = DEFAULT_WEIGHTS.copy()
        dim_scores = {"financial": 95, "urgency": 20, "confidence": 80, "execution": 60}
        for _ in range(20):
            grad   = compute_gradient(weights, dim_scores, 1.5)
            weights = apply_gradient(weights, grad)
        assert weights["financial"] > DEFAULT_WEIGHTS["financial"]

    def test_failed_decision_decreases_dominant_dimension(self):
        """
        财务分很高的决策执行失败 → 多轮后 financial 权重应下降
        """
        weights = DEFAULT_WEIGHTS.copy()
        dim_scores = {"financial": 95, "urgency": 20, "confidence": 80, "execution": 60}
        for _ in range(20):
            grad    = compute_gradient(weights, dim_scores, 0.0)
            weights = apply_gradient(weights, grad)
        assert weights["financial"] < DEFAULT_WEIGHTS["financial"]


# ═══════════════════════════════════════════════════════════════════════════════
# DecisionWeightLearner (mock DB)
# ═══════════════════════════════════════════════════════════════════════════════

class TestDecisionWeightLearner:
    @pytest.mark.asyncio
    async def test_get_weights_returns_defaults_when_no_db_row(self):
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)
        learner  = DecisionWeightLearner()
        weights  = await learner.get_weights("STORE_MISSING", mock_db)
        assert weights == DEFAULT_WEIGHTS

    @pytest.mark.asyncio
    async def test_get_weights_returns_store_specific(self):
        from src.models.weight_learning import DecisionWeightConfig
        row = MagicMock(spec=DecisionWeightConfig)
        row.w_financial  = 0.50
        row.w_urgency    = 0.25
        row.w_confidence = 0.15
        row.w_execution  = 0.10

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=row)

        learner  = DecisionWeightLearner()
        weights  = await learner.get_weights("STORE_001", mock_db)
        assert weights["financial"] == 0.50

    @pytest.mark.asyncio
    async def test_update_skips_when_zero_expected(self):
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)

        learner = DecisionWeightLearner()
        result  = await learner.update_from_feedback(
            store_id="S001",
            dim_scores={"financial": 80, "urgency": 60, "confidence": 70, "execution": 100},
            outcome="success",
            actual_impact_yuan=500.0,
            expected_saving_yuan=0.0,   # ← 触发跳过
            db=mock_db,
        )
        # 返回默认权重（跳过更新）
        assert result == DEFAULT_WEIGHTS

    @pytest.mark.asyncio
    async def test_update_creates_new_row_for_unknown_store(self):
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        learner = DecisionWeightLearner()
        result  = await learner.update_from_feedback(
            store_id="S_NEW",
            dim_scores={"financial": 80, "urgency": 60, "confidence": 70, "execution": 100},
            outcome="success",
            actual_impact_yuan=1200.0,
            expected_saving_yuan=1000.0,
            db=mock_db,
        )
        mock_db.add.assert_called_once()
        # 成功案例：financial 梯度为正 → 新权重不低于最小值
        assert result["financial"] >= WEIGHT_MIN
        assert abs(sum(result.values()) - 1.0) < 1e-4

    @pytest.mark.asyncio
    async def test_history_capped_at_max(self):
        """update_history 超过 MAX_HISTORY 时自动裁剪"""
        from src.services.decision_weight_learner import MAX_HISTORY
        from src.models.weight_learning import DecisionWeightConfig

        # 模拟已有 MAX_HISTORY 条历史记录的门店
        row = MagicMock(spec=DecisionWeightConfig)
        row.w_financial  = 0.40
        row.w_urgency    = 0.30
        row.w_confidence = 0.20
        row.w_execution  = 0.10
        row.sample_count = MAX_HISTORY
        row.update_history = [{"ts": f"ts_{i}"} for i in range(MAX_HISTORY)]
        row.last_updated = None

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=row)
        mock_db.commit = AsyncMock()

        learner = DecisionWeightLearner()
        await learner.update_from_feedback(
            store_id="S001",
            dim_scores={"financial": 80, "urgency": 60, "confidence": 70, "execution": 100},
            outcome="success",
            actual_impact_yuan=800.0,
            expected_saving_yuan=1000.0,
            db=mock_db,
        )
        assert len(row.update_history) == MAX_HISTORY
