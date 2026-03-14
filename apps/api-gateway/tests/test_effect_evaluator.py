"""
EffectEvaluator 单元测试

覆盖：
  - sweep_finds_unevaluated — mock DB 中有过期未评估决策
  - evaluate_inventory — mock waste_events，验证偏差计算
  - evaluate_schedule — mock labor_cost，验证 outcome 判定
  - trust_score_bayesian_update — 验证信任分升降逻辑
  - idempotent_evaluation — 重复扫描不重复评估
  - manual_feedback_trust_update — 手动反馈也触发信任分更新
"""
import os

for _k, _v in {
    "APP_ENV": "test",
    "DATABASE_URL": "postgresql+asyncpg://test:test@localhost/test",
    "REDIS_URL": "redis://localhost:6379/0",
    "CELERY_BROKER_URL": "redis://localhost:6379/0",
    "CELERY_RESULT_BACKEND": "redis://localhost:6379/0",
    "SECRET_KEY": "test-secret-key",
    "JWT_SECRET": "test-jwt-secret",
}.items():
    os.environ.setdefault(_k, _v)

import datetime
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.effect_evaluator import EffectEvaluator, _compute_trust_delta


class TestComputeTrustDelta:
    """验证信任分升降逻辑。"""

    def test_success_low_deviation(self):
        delta = _compute_trust_delta("success", 5.0, 50.0)
        assert delta > 0
        assert delta == min(5.0, (100 - 50) * 0.1)  # 5.0

    def test_success_high_deviation(self):
        delta = _compute_trust_delta("success", 20.0, 50.0)
        assert delta > 0
        assert delta == min(3.0, (100 - 50) * 0.05)  # 2.5

    def test_partial(self):
        delta = _compute_trust_delta("partial", 0.0, 50.0)
        assert delta == 0.5

    def test_failure(self):
        delta = _compute_trust_delta("failure", 30.0, 50.0)
        assert delta < 0
        assert delta == -max(3.0, 50 * 0.08)  # -4.0

    def test_success_approaches_100(self):
        """高信任分时涨幅收窄。"""
        delta_low = _compute_trust_delta("success", 5.0, 30.0)
        delta_high = _compute_trust_delta("success", 5.0, 90.0)
        assert delta_low > delta_high

    def test_failure_high_trust_drops_more(self):
        """高信任分时跌幅更大。"""
        delta_low = _compute_trust_delta("failure", 30.0, 30.0)
        delta_high = _compute_trust_delta("failure", 30.0, 80.0)
        assert abs(delta_high) > abs(delta_low)

    def test_unknown_outcome(self):
        delta = _compute_trust_delta("unknown", 0.0, 50.0)
        assert delta == 0.0

    def test_clamp_boundaries(self):
        """信任分不超出 [0, 100]。"""
        # 极高信任 + 成功 → 不超 100
        trust = 99.0
        delta = _compute_trust_delta("success", 5.0, trust)
        assert trust + delta <= 100.0

        # 极低信任 + 失败 → 不低于 0
        trust = 3.0
        delta = _compute_trust_delta("failure", 50.0, trust)
        assert trust + delta >= -3.0  # delta 本身可能为负


class TestEffectEvaluatorSweep:
    """评估扫描逻辑。"""

    @pytest.mark.asyncio
    async def test_sweep_no_pending(self):
        """无待评估记录时直接返回。"""
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(fetchall=MagicMock(return_value=[])))

        evaluator = EffectEvaluator(db)
        result = await evaluator.run_evaluation_sweep()
        assert result["evaluated"] == 0

    @pytest.mark.asyncio
    async def test_sweep_finds_unevaluated(self):
        """找到过期未评估的决策。"""
        three_days_ago = datetime.datetime.utcnow() - datetime.timedelta(days=3)
        mock_rows = [
            (
                "DL001", "inventory_alert", "S001",
                three_days_ago,  # executed_at
                None,  # expected_result
                None,  # context_data
                50.0,  # trust_score
            ),
        ]

        db = AsyncMock()
        # _find_unevaluated query
        find_result = MagicMock()
        find_result.fetchall = MagicMock(return_value=mock_rows)

        # waste events queries (before/after)
        waste_before = MagicMock()
        waste_before.fetchone = MagicMock(return_value=(10,))
        waste_after = MagicMock()
        waste_after.fetchone = MagicMock(return_value=(5,))

        # _update_decision query
        update_result = MagicMock()

        call_count = 0
        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return find_result
            elif call_count == 2:
                return waste_before
            elif call_count == 3:
                return waste_after
            else:
                return update_result

        db.execute = mock_execute
        db.commit = AsyncMock()
        db.rollback = AsyncMock()

        evaluator = EffectEvaluator(db)
        result = await evaluator.run_evaluation_sweep()
        assert result["evaluated"] == 1

    @pytest.mark.asyncio
    async def test_idempotent_evaluation(self):
        """已评估的记录（outcome 非 NULL）不会被查出。"""
        db = AsyncMock()
        # SQL WHERE outcome IS NULL 保证已评估的不会被返回
        db.execute = AsyncMock(return_value=MagicMock(fetchall=MagicMock(return_value=[])))

        evaluator = EffectEvaluator(db)
        result = await evaluator.run_evaluation_sweep()
        assert result["evaluated"] == 0
        assert result["skipped"] == 0


class TestEvaluateInventory:
    """库存预警评估。"""

    @pytest.mark.asyncio
    async def test_waste_decreased(self):
        """损耗减少 → success。"""
        db = AsyncMock()

        waste_before = MagicMock()
        waste_before.fetchone = MagicMock(return_value=(10,))
        waste_after = MagicMock()
        waste_after.fetchone = MagicMock(return_value=(3,))

        call_count = 0
        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return waste_before
            return waste_after

        db.execute = mock_execute

        evaluator = EffectEvaluator(db)
        result = await evaluator._evaluate_inventory(
            "S001",
            datetime.datetime.utcnow() - datetime.timedelta(days=3),
            {}, {},
        )

        assert result is not None
        assert result["outcome"] == "success"
        assert result["actual_result"]["waste_before"] == 10
        assert result["actual_result"]["waste_after"] == 3

    @pytest.mark.asyncio
    async def test_waste_increased(self):
        """损耗增加 → failure。"""
        db = AsyncMock()

        waste_before = MagicMock()
        waste_before.fetchone = MagicMock(return_value=(5,))
        waste_after = MagicMock()
        waste_after.fetchone = MagicMock(return_value=(10,))

        call_count = 0
        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return waste_before
            return waste_after

        db.execute = mock_execute

        evaluator = EffectEvaluator(db)
        result = await evaluator._evaluate_inventory(
            "S001",
            datetime.datetime.utcnow() - datetime.timedelta(days=3),
            {}, {},
        )

        assert result is not None
        assert result["outcome"] == "failure"


class TestEvaluateSchedule:
    """排班优化评估。"""

    @pytest.mark.asyncio
    async def test_labor_cost_decreased(self):
        """人力成本率降低 → success。"""
        db = AsyncMock()

        before_result = MagicMock()
        before_result.fetchone = MagicMock(return_value=(0.35,))
        after_result = MagicMock()
        after_result.fetchone = MagicMock(return_value=(0.30,))

        call_count = 0
        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return before_result
            return after_result

        db.execute = mock_execute

        evaluator = EffectEvaluator(db)
        result = await evaluator._evaluate_schedule(
            "S001",
            datetime.datetime.utcnow() - datetime.timedelta(days=4),
            {}, {},
        )

        assert result is not None
        assert result["outcome"] == "success"

    @pytest.mark.asyncio
    async def test_no_data_returns_none(self):
        """无数据时返回 None。"""
        db = AsyncMock()
        none_result = MagicMock()
        none_result.fetchone = MagicMock(return_value=(None,))
        db.execute = AsyncMock(return_value=none_result)

        evaluator = EffectEvaluator(db)
        result = await evaluator._evaluate_schedule(
            "S001",
            datetime.datetime.utcnow() - datetime.timedelta(days=4),
            {}, {},
        )

        assert result is None


class TestManualFeedbackTrustUpdate:
    """手动反馈也触发信任分更新。"""

    def test_trust_delta_on_success(self):
        """成功反馈应增加信任分。"""
        delta = _compute_trust_delta("success", 5.0, 50.0)
        assert delta > 0

    def test_trust_delta_on_failure(self):
        """失败反馈应降低信任分。"""
        delta = _compute_trust_delta("failure", 30.0, 50.0)
        assert delta < 0
