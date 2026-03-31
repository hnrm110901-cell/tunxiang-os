"""供应商评分引擎测试（测试先行）

测试场景：
1. 五维度规则评分计算正确性（含加权）
2. composite_score 范围验证（0-100）
3. 评分历史写入格式验证
4. AI 洞察调用 mock（ModelRouter.complete 被调用，不真实调用 API）
5. 供应商分级（优质/合格/观察/淘汰）判定逻辑
"""
from __future__ import annotations

import sys
import os
import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 让 tests/ 目录能导入 src/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from services.supplier_scoring_engine import (
    SupplierScoringEngine,
    DimensionScores,
    SupplierScoreResult,
    SCORE_WEIGHTS,
    TIER_THRESHOLDS,
)


# ─────────────────────────────────────────────────────────────────────────────
# 辅助工具
# ─────────────────────────────────────────────────────────────────────────────

def _make_engine() -> SupplierScoringEngine:
    return SupplierScoringEngine()


def _make_dimension_scores(
    delivery_rate: float = 0.9,
    quality_rate: float = 0.88,
    price_stability: float = 0.85,
    response_speed: float = 0.80,
    compliance_rate: float = 0.95,
) -> DimensionScores:
    return DimensionScores(
        delivery_rate=delivery_rate,
        quality_rate=quality_rate,
        price_stability=price_stability,
        response_speed=response_speed,
        compliance_rate=compliance_rate,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 测试 1：五维度加权计算正确性
# ─────────────────────────────────────────────────────────────────────────────

class TestWeightedScoreCalculation:
    """验证加权公式：composite_score = sum(维度值 × 权重) × 100"""

    def test_perfect_score_is_100(self):
        engine = _make_engine()
        dims = _make_dimension_scores(1.0, 1.0, 1.0, 1.0, 1.0)
        score = engine._compute_composite(dims)
        assert score == pytest.approx(100.0, abs=0.01)

    def test_zero_score_is_0(self):
        engine = _make_engine()
        dims = _make_dimension_scores(0.0, 0.0, 0.0, 0.0, 0.0)
        score = engine._compute_composite(dims)
        assert score == pytest.approx(0.0, abs=0.01)

    def test_weights_sum_to_1(self):
        total = sum(SCORE_WEIGHTS.values())
        assert total == pytest.approx(1.0, abs=1e-9)

    def test_weight_keys_match_spec(self):
        expected = {"delivery_rate", "quality_rate", "price_stability", "response_speed", "compliance_rate"}
        assert set(SCORE_WEIGHTS.keys()) == expected

    def test_delivery_rate_weight_is_highest(self):
        """交货率应该是最高权重（0.30）"""
        assert SCORE_WEIGHTS["delivery_rate"] == pytest.approx(0.30)

    def test_manual_weighted_calculation(self):
        """手动验证：各维度 × 权重后累加 × 100"""
        engine = _make_engine()
        dims = _make_dimension_scores(
            delivery_rate=0.9,
            quality_rate=0.8,
            price_stability=0.7,
            response_speed=0.6,
            compliance_rate=0.5,
        )
        expected = (
            0.9 * SCORE_WEIGHTS["delivery_rate"]
            + 0.8 * SCORE_WEIGHTS["quality_rate"]
            + 0.7 * SCORE_WEIGHTS["price_stability"]
            + 0.6 * SCORE_WEIGHTS["response_speed"]
            + 0.5 * SCORE_WEIGHTS["compliance_rate"]
        ) * 100
        assert engine._compute_composite(dims) == pytest.approx(expected, abs=0.01)

    def test_delivery_rate_dominance(self):
        """交货率权重最大，对综合分影响应最显著"""
        engine = _make_engine()
        # 只有 delivery_rate = 1，其余为 0
        high_delivery = _make_dimension_scores(1.0, 0.0, 0.0, 0.0, 0.0)
        # 只有 compliance_rate = 1，其余为 0
        high_compliance = _make_dimension_scores(0.0, 0.0, 0.0, 0.0, 1.0)
        assert engine._compute_composite(high_delivery) > engine._compute_composite(high_compliance)


# ─────────────────────────────────────────────────────────────────────────────
# 测试 2：composite_score 范围验证（0-100）
# ─────────────────────────────────────────────────────────────────────────────

class TestScoreRangeValidation:
    """composite_score 必须始终在 [0, 100] 范围内"""

    def test_boundary_0(self):
        engine = _make_engine()
        assert 0.0 <= engine._compute_composite(_make_dimension_scores(0, 0, 0, 0, 0)) <= 100.0

    def test_boundary_100(self):
        engine = _make_engine()
        assert 0.0 <= engine._compute_composite(_make_dimension_scores(1, 1, 1, 1, 1)) <= 100.0

    def test_typical_range(self):
        engine = _make_engine()
        dims = _make_dimension_scores(0.85, 0.90, 0.78, 0.82, 0.95)
        score = engine._compute_composite(dims)
        assert 0.0 <= score <= 100.0

    def test_result_model_has_composite_score(self):
        """SupplierScoreResult 必须携带 composite_score"""
        result = SupplierScoreResult(
            supplier_id="sup_001",
            tenant_id="ten_001",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
            dimensions=_make_dimension_scores(),
            composite_score=87.5,
            tier="premium",
            ai_insight=None,
        )
        assert 0.0 <= result.composite_score <= 100.0


# ─────────────────────────────────────────────────────────────────────────────
# 测试 3：评分历史写入格式验证
# ─────────────────────────────────────────────────────────────────────────────

class TestScoreHistoryFormat:
    """验证写入 supplier_score_history 的字段符合 v064 表结构"""

    def test_score_history_dict_has_required_fields(self):
        engine = _make_engine()
        dims = _make_dimension_scores()
        record = engine._build_score_history_record(
            supplier_id="sup_001",
            tenant_id="ten_001",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
            dimensions=dims,
            composite_score=85.3,
            ai_insight="表现稳定，建议续约。",
        )
        required_fields = {
            "tenant_id", "supplier_id",
            "period_start", "period_end",
            "delivery_rate", "quality_rate", "price_stability",
            "response_speed", "compliance_rate",
            "composite_score",
        }
        for field in required_fields:
            assert field in record, f"缺少字段: {field}"

    def test_dimension_values_are_between_0_and_1(self):
        engine = _make_engine()
        dims = _make_dimension_scores(0.9, 0.85, 0.80, 0.75, 1.0)
        record = engine._build_score_history_record(
            supplier_id="sup_001",
            tenant_id="ten_001",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
            dimensions=dims,
            composite_score=85.0,
            ai_insight=None,
        )
        for dim in ("delivery_rate", "quality_rate", "price_stability", "response_speed", "compliance_rate"):
            val = record[dim]
            assert 0.0 <= val <= 1.0, f"{dim}={val} 超出 [0,1] 范围"

    def test_composite_score_in_record_is_0_100(self):
        engine = _make_engine()
        dims = _make_dimension_scores()
        record = engine._build_score_history_record(
            supplier_id="sup_001",
            tenant_id="ten_001",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
            dimensions=dims,
            composite_score=72.3,
            ai_insight=None,
        )
        assert 0.0 <= record["composite_score"] <= 100.0

    def test_ai_insight_can_be_none(self):
        engine = _make_engine()
        dims = _make_dimension_scores()
        record = engine._build_score_history_record(
            supplier_id="sup_001",
            tenant_id="ten_001",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
            dimensions=dims,
            composite_score=80.0,
            ai_insight=None,
        )
        assert record.get("ai_insight") is None


# ─────────────────────────────────────────────────────────────────────────────
# 测试 4：AI 洞察调用 mock
# ─────────────────────────────────────────────────────────────────────────────

class TestAIInsightMock:
    """验证 generate_ai_insight 通过 ModelRouter.complete 调用，不直接调用 API"""

    @pytest.mark.asyncio
    async def test_model_router_complete_is_called(self):
        engine = _make_engine()
        mock_router = AsyncMock()
        mock_router.complete = AsyncMock(return_value="供应商表现优良，建议续约。")

        result = await engine.generate_ai_insight(
            supplier_name="湘江渔港水产",
            scores={
                "delivery_rate": 0.92,
                "quality_rate": 0.88,
                "price_stability": 0.85,
                "response_speed": 0.80,
                "compliance_rate": 0.95,
                "composite_score": 88.5,
            },
            history=[],
            model_router=mock_router,
        )

        mock_router.complete.assert_called_once()
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_model_router_called_with_supplier_insight_task(self):
        """调用 ModelRouter 时必须传入 task_type='supplier_insight'"""
        engine = _make_engine()
        mock_router = AsyncMock()
        mock_router.complete = AsyncMock(return_value="AI洞察文本")

        await engine.generate_ai_insight(
            supplier_name="测试供应商",
            scores={"delivery_rate": 0.7, "quality_rate": 0.6, "composite_score": 65.0},
            history=[],
            model_router=mock_router,
        )

        call_kwargs = mock_router.complete.call_args
        # 验证第一个位置参数或 task_type 关键字参数
        if call_kwargs.args:
            assert call_kwargs.args[0] == "supplier_insight"
        else:
            assert call_kwargs.kwargs.get("task_type") == "supplier_insight"

    @pytest.mark.asyncio
    async def test_ai_insight_contains_supplier_name(self):
        engine = _make_engine()
        mock_router = AsyncMock()
        mock_router.complete = AsyncMock(return_value="湘江渔港表现稳定。")

        result = await engine.generate_ai_insight(
            supplier_name="湘江渔港水产",
            scores={"delivery_rate": 0.9, "composite_score": 87.0},
            history=[],
            model_router=mock_router,
        )
        assert result == "湘江渔港表现稳定。"

    @pytest.mark.asyncio
    async def test_ai_insight_returns_empty_string_on_router_failure(self):
        """ModelRouter 调用失败时应优雅降级，返回空字符串，不抛异常"""
        engine = _make_engine()
        mock_router = AsyncMock()
        mock_router.complete = AsyncMock(side_effect=RuntimeError("网络错误"))

        result = await engine.generate_ai_insight(
            supplier_name="测试供应商",
            scores={"delivery_rate": 0.5, "composite_score": 50.0},
            history=[],
            model_router=mock_router,
        )
        assert result == ""


# ─────────────────────────────────────────────────────────────────────────────
# 测试 5：供应商分级判定逻辑
# ─────────────────────────────────────────────────────────────────────────────

class TestSupplierTierClassification:
    """验证四级分层阈值正确：优质 ≥85 / 合格 ≥70 / 观察 ≥55 / 淘汰 <55"""

    @pytest.mark.asyncio
    async def test_premium_tier_above_85(self):
        engine = _make_engine()
        tier = await engine.get_supplier_tier(85.0)
        assert tier == "premium"

    @pytest.mark.asyncio
    async def test_premium_tier_at_100(self):
        engine = _make_engine()
        tier = await engine.get_supplier_tier(100.0)
        assert tier == "premium"

    @pytest.mark.asyncio
    async def test_qualified_tier_at_70(self):
        engine = _make_engine()
        tier = await engine.get_supplier_tier(70.0)
        assert tier == "qualified"

    @pytest.mark.asyncio
    async def test_qualified_tier_below_85(self):
        engine = _make_engine()
        tier = await engine.get_supplier_tier(84.9)
        assert tier == "qualified"

    @pytest.mark.asyncio
    async def test_watch_tier_at_55(self):
        engine = _make_engine()
        tier = await engine.get_supplier_tier(55.0)
        assert tier == "watch"

    @pytest.mark.asyncio
    async def test_watch_tier_below_70(self):
        engine = _make_engine()
        tier = await engine.get_supplier_tier(69.9)
        assert tier == "watch"

    @pytest.mark.asyncio
    async def test_eliminate_tier_below_55(self):
        engine = _make_engine()
        tier = await engine.get_supplier_tier(54.9)
        assert tier == "eliminate"

    @pytest.mark.asyncio
    async def test_eliminate_tier_at_0(self):
        engine = _make_engine()
        tier = await engine.get_supplier_tier(0.0)
        assert tier == "eliminate"

    def test_tier_thresholds_values(self):
        """验证阈值常量值正确"""
        assert TIER_THRESHOLDS["premium"] == 85
        assert TIER_THRESHOLDS["qualified"] == 70
        assert TIER_THRESHOLDS["watch"] == 55
        assert TIER_THRESHOLDS["eliminate"] == 0

    @pytest.mark.asyncio
    async def test_all_tier_names_covered(self):
        """所有分级名称均可由 get_supplier_tier 返回"""
        engine = _make_engine()
        scores = [90.0, 75.0, 60.0, 40.0]
        tiers = [await engine.get_supplier_tier(s) for s in scores]
        assert set(tiers) == {"premium", "qualified", "watch", "eliminate"}


# ─────────────────────────────────────────────────────────────────────────────
# 测试 6：AI 洞察触发策略
# ─────────────────────────────────────────────────────────────────────────────

class TestAIInsightTriggerStrategy:
    """验证 AI 洞察触发条件：composite_score < 70 或首次月报"""

    def test_should_trigger_ai_when_score_below_70(self):
        engine = _make_engine()
        assert engine._should_trigger_ai(composite_score=69.9, is_first_monthly=False) is True

    def test_should_trigger_ai_when_first_monthly(self):
        engine = _make_engine()
        assert engine._should_trigger_ai(composite_score=90.0, is_first_monthly=True) is True

    def test_should_not_trigger_ai_when_score_above_70_not_monthly(self):
        engine = _make_engine()
        assert engine._should_trigger_ai(composite_score=75.0, is_first_monthly=False) is False

    def test_should_trigger_ai_exactly_at_70_threshold(self):
        """composite_score == 70 时不触发（< 70 才触发）"""
        engine = _make_engine()
        assert engine._should_trigger_ai(composite_score=70.0, is_first_monthly=False) is False


# ─────────────────────────────────────────────────────────────────────────────
# 测试 7：DimensionScores Pydantic 模型验证
# ─────────────────────────────────────────────────────────────────────────────

class TestDimensionScoresModel:
    """验证 DimensionScores 的 Pydantic V2 约束"""

    def test_valid_dimensions(self):
        dims = DimensionScores(
            delivery_rate=0.9,
            quality_rate=0.85,
            price_stability=0.8,
            response_speed=0.75,
            compliance_rate=1.0,
        )
        assert dims.delivery_rate == pytest.approx(0.9)

    def test_boundary_values(self):
        """0.0 和 1.0 均为合法值"""
        dims = DimensionScores(
            delivery_rate=0.0,
            quality_rate=1.0,
            price_stability=0.5,
            response_speed=0.0,
            compliance_rate=1.0,
        )
        assert dims.quality_rate == pytest.approx(1.0)
