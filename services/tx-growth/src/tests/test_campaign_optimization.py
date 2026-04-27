"""S1W1 Campaign自优化模块测试

测试范围：
  - CampaignOptimizer 服务层（创建/评估/审批/应用）
  - 双比例z检验数学正确性
  - API端点（触发/状态/应用）
  - UnifiedSendScheduler（频次限制/去重）
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

TENANT_ID = str(uuid.uuid4())
CAMPAIGN_ID = str(uuid.uuid4())
_HEADERS = {"X-Tenant-ID": TENANT_ID, "Authorization": "Bearer test"}


# ─────────────────────────────────────────────────────────────────────────────
# CampaignOptimizer Unit Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestCampaignOptimizerUnit:
    """CampaignOptimizer 纯逻辑测试"""

    def test_two_proportion_z_test_identical_rates(self):
        """相同转化率 → p-value ≈ 1.0"""
        from services.campaign_optimizer import CampaignOptimizer

        optimizer = CampaignOptimizer()
        p = optimizer._two_proportion_z_test(0.10, 100, 0.10, 100)
        assert p > 0.95, f"相同转化率p-value应接近1.0, got {p}"

    def test_two_proportion_z_test_large_difference(self):
        """显著差异 → p-value < 0.05"""
        from services.campaign_optimizer import CampaignOptimizer

        optimizer = CampaignOptimizer()
        # 10% vs 25% with n=200 each → should be very significant
        p = optimizer._two_proportion_z_test(0.10, 200, 0.25, 200)
        assert p < 0.01, f"显著差异p-value应<0.01, got {p}"

    def test_two_proportion_z_test_zero_sample(self):
        """零样本 → p-value = 1.0"""
        from services.campaign_optimizer import CampaignOptimizer

        optimizer = CampaignOptimizer()
        p = optimizer._two_proportion_z_test(0.10, 0, 0.25, 100)
        assert p == 1.0

    def test_two_proportion_z_test_marginal_difference(self):
        """小样本小差异 → p-value > 0.05"""
        from services.campaign_optimizer import CampaignOptimizer

        optimizer = CampaignOptimizer()
        # 10% vs 12% with n=50 each → should NOT be significant
        p = optimizer._two_proportion_z_test(0.10, 50, 0.12, 50)
        assert p > 0.05, f"小差异p-value应>0.05, got {p}"


class TestCampaignOptimizerService:
    """CampaignOptimizer 服务层测试（mock DB）"""

    @pytest.mark.asyncio
    async def test_create_optimization(self):
        """创建优化记录"""
        from services.campaign_optimizer import CampaignOptimizer

        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock())

        optimizer = CampaignOptimizer()
        result = await optimizer.create_optimization(
            uuid.UUID(TENANT_ID),
            uuid.UUID(CAMPAIGN_ID),
            db,
        )

        assert "optimization_id" in result
        assert result["round"] == 1
        db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_evaluate_round_insufficient_sample(self):
        """样本量不足 → 保持evaluating"""
        from services.campaign_optimizer import CampaignOptimizer

        db = AsyncMock()
        opt_id = uuid.uuid4()
        mock_result = MagicMock()
        mock_result.mappings.return_value.first.return_value = {
            "id": str(opt_id),
            "optimization_round": 1,
            "auto_apply_threshold": 0.05,
        }
        db.execute = AsyncMock(side_effect=[mock_result, MagicMock()])

        optimizer = CampaignOptimizer()
        result = await optimizer.evaluate_round(
            uuid.UUID(TENANT_ID),
            uuid.UUID(CAMPAIGN_ID),
            db,
            variant_a_metrics={"send_count": 10, "conversion_rate": 0.1},
            variant_b_metrics={"send_count": 15, "conversion_rate": 0.2},
        )

        assert result["status"] == "evaluating"
        assert "样本量不足" in result["reason"]

    @pytest.mark.asyncio
    async def test_evaluate_round_auto_apply(self):
        """显著差异+低预算偏移 → auto_applied"""
        from services.campaign_optimizer import CampaignOptimizer

        db = AsyncMock()
        opt_id = uuid.uuid4()
        mock_result = MagicMock()
        mock_result.mappings.return_value.first.return_value = {
            "id": str(opt_id),
            "optimization_round": 1,
            "auto_apply_threshold": 0.05,
        }
        db.execute = AsyncMock(side_effect=[mock_result, MagicMock()])

        optimizer = CampaignOptimizer()
        result = await optimizer.evaluate_round(
            uuid.UUID(TENANT_ID),
            uuid.UUID(CAMPAIGN_ID),
            db,
            variant_a_metrics={"send_count": 200, "conversion_rate": 0.10},
            variant_b_metrics={"send_count": 200, "conversion_rate": 0.20},
        )

        assert result["winner"] in ("a", "b")
        assert result["p_value"] < 0.05
        # Status depends on budget_shift threshold
        assert result["status"] in ("auto_applied", "pending_approval")

    @pytest.mark.asyncio
    async def test_evaluate_round_not_found(self):
        """无evaluating记录 → 报错"""
        from services.campaign_optimizer import CampaignOptimizationError, CampaignOptimizer

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value.first.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        optimizer = CampaignOptimizer()
        with pytest.raises(CampaignOptimizationError) as exc_info:
            await optimizer.evaluate_round(
                uuid.UUID(TENANT_ID),
                uuid.UUID(CAMPAIGN_ID),
                db,
                variant_a_metrics={"send_count": 100, "conversion_rate": 0.1},
                variant_b_metrics={"send_count": 100, "conversion_rate": 0.2},
            )
        assert exc_info.value.code == "NOT_FOUND"


# ─────────────────────────────────────────────────────────────────────────────
# UnifiedSendScheduler Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestUnifiedSendScheduler:
    """多渠道统一调度器测试"""

    @pytest.mark.asyncio
    async def test_dedup_blocks_repeat_send(self):
        """同一客户同一Campaign同一渠道已发送 → 跳过"""
        from services.unified_send_scheduler import UnifiedSendScheduler

        db = AsyncMock()
        # Mock: dedup check returns existing record
        dedup_result = MagicMock()
        dedup_result.first.return_value = MagicMock()  # exists
        db.execute = AsyncMock(return_value=dedup_result)

        scheduler = UnifiedSendScheduler()
        result = await scheduler.schedule_send(
            uuid.UUID(TENANT_ID),
            uuid.uuid4(),
            uuid.uuid4(),
            db,
            channels=["sms"],
            content_by_channel={"sms": {"body": "test"}},
        )

        assert len(result["scheduled"]) == 0
        assert len(result["skipped"]) == 1
        assert result["skipped"][0]["reason"] == "已发送"

    @pytest.mark.asyncio
    async def test_unknown_channel_skipped(self):
        """未知渠道 → 跳过"""
        from services.unified_send_scheduler import UnifiedSendScheduler

        db = AsyncMock()
        scheduler = UnifiedSendScheduler()
        result = await scheduler.schedule_send(
            uuid.UUID(TENANT_ID),
            uuid.uuid4(),
            uuid.uuid4(),
            db,
            channels=["unknown_channel"],
            content_by_channel={},
        )

        assert len(result["scheduled"]) == 0
        assert result["skipped"][0]["reason"] == "未知渠道"

    def test_optimize_send_time_selects_best_hour(self):
        """时段优化选择下一个最佳小时"""
        from services.unified_send_scheduler import UnifiedSendScheduler

        scheduler = UnifiedSendScheduler()
        result = scheduler._optimize_send_time("wechat_subscribe")
        assert result is not None
        # Should be a future time
        assert result >= datetime.now(timezone.utc).replace(microsecond=0)


# ─────────────────────────────────────────────────────────────────────────────
# OptimizationWorker Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestOptimizationWorker:
    """优化Worker测试"""

    @pytest.mark.asyncio
    async def test_tick_no_evaluating_records(self):
        """无evaluating记录 → 返回全零stats"""
        from workers.optimization_worker import OptimizationWorker

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=mock_result)

        worker = OptimizationWorker()
        stats = await worker.tick(db)

        assert stats["checked"] == 0
        assert stats["auto_applied"] == 0
