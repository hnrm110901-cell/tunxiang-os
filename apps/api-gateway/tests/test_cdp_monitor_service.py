"""
CDP Monitor Service 单元测试

测试纯函数 + 服务方法（mock DB + mock 子服务）
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

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ══════════════════════════════════════════════════════════════════
# 纯函数测试
# ══════════════════════════════════════════════════════════════════

from src.services.cdp_monitor_service import (
    classify_fill_rate_health,
    compute_kpi_summary,
    CDPMonitorService,
)


class TestClassifyFillRateHealth:

    def test_excellent(self):
        assert classify_fill_rate_health(0.95) == "excellent"

    def test_good(self):
        assert classify_fill_rate_health(0.85) == "good"

    def test_warning(self):
        assert classify_fill_rate_health(0.65) == "warning"

    def test_critical(self):
        assert classify_fill_rate_health(0.50) == "critical"

    def test_boundary_90(self):
        assert classify_fill_rate_health(0.90) == "excellent"

    def test_boundary_80(self):
        assert classify_fill_rate_health(0.80) == "good"

    def test_boundary_60(self):
        assert classify_fill_rate_health(0.60) == "warning"


class TestComputeKpiSummary:

    def test_all_met(self):
        result = compute_kpi_summary(0.85, 0.03)
        assert result["all_met"] is True
        assert result["fill_rate_kpi"]["met"] is True
        assert result["deviation_kpi"]["met"] is True

    def test_fill_not_met(self):
        result = compute_kpi_summary(0.70, 0.02)
        assert result["all_met"] is False
        assert result["fill_rate_kpi"]["met"] is False
        assert result["deviation_kpi"]["met"] is True

    def test_deviation_not_met(self):
        result = compute_kpi_summary(0.90, 0.08)
        assert result["all_met"] is False
        assert result["fill_rate_kpi"]["met"] is True
        assert result["deviation_kpi"]["met"] is False

    def test_neither_met(self):
        result = compute_kpi_summary(0.50, 0.10)
        assert result["all_met"] is False
        assert result["fill_rate_kpi"]["met"] is False
        assert result["deviation_kpi"]["met"] is False

    def test_exact_boundary_fill(self):
        result = compute_kpi_summary(0.80, 0.03)
        assert result["fill_rate_kpi"]["met"] is True

    def test_exact_boundary_deviation(self):
        result = compute_kpi_summary(0.85, 0.05)
        assert result["deviation_kpi"]["met"] is False  # < 0.05, not <=

    def test_actual_values(self):
        result = compute_kpi_summary(0.8523, 0.0312)
        assert result["fill_rate_kpi"]["actual"] == 85.23
        assert result["deviation_kpi"]["actual"] == 3.12


# ══════════════════════════════════════════════════════════════════
# 服务方法测试
# ══════════════════════════════════════════════════════════════════

class TestCDPMonitorService:

    @pytest.fixture
    def service(self):
        return CDPMonitorService()

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        db.scalar = AsyncMock(return_value=0)
        return db

    @pytest.mark.asyncio
    async def test_rfm_distribution_empty(self, service, mock_db):
        mock_result = AsyncMock()
        mock_result.all = MagicMock(return_value=[])
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.get_rfm_distribution(mock_db)
        assert result["total"] == 0
        assert result["S1"]["count"] == 0
        assert result["S5"]["count"] == 0

    @pytest.mark.asyncio
    async def test_rfm_distribution_with_data(self, service, mock_db):
        mock_result = AsyncMock()
        mock_result.all = MagicMock(return_value=[
            ("S1", 10),
            ("S2", 20),
            ("S3", 30),
            ("S4", 15),
            ("S5", 5),
        ])
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await service.get_rfm_distribution(mock_db)
        assert result["total"] == 80
        assert result["S1"]["count"] == 10
        assert result["S1"]["rate"] == round(10 / 80, 4)
        assert result["S3"]["count"] == 30

    @pytest.mark.asyncio
    async def test_pending_counts_empty(self, service, mock_db):
        mock_db.scalar = AsyncMock(return_value=0)
        result = await service._get_pending_counts(mock_db)
        assert result["orders"] == 0
        assert result["members"] == 0
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_pending_counts_with_data(self, service, mock_db):
        # scalar returns different values for different calls
        mock_db.scalar = AsyncMock(side_effect=[100, 50])
        result = await service._get_pending_counts(mock_db)
        assert result["orders"] == 100
        assert result["members"] == 50
        assert result["total"] == 150

    @pytest.mark.asyncio
    async def test_dashboard_aggregates(self, service, mock_db):
        """测试 dashboard 调用所有子服务并聚合"""
        # Lazy imports inside get_dashboard → patch at source modules
        with patch("src.services.identity_resolution_service.identity_resolution_service") as mock_irs, \
             patch("src.services.cdp_sync_service.cdp_sync_service") as mock_sync, \
             patch("src.services.cdp_rfm_service.cdp_rfm_service") as mock_rfm:

            mock_irs.get_stats = AsyncMock(return_value={
                "total_consumers": 100, "merged_count": 5, "active_mappings": 120,
            })
            mock_sync.get_fill_rate = AsyncMock(return_value={
                "orders": {"total": 1000, "filled": 850, "rate": 0.85},
                "reservations": {"total": 200, "filled": 180, "rate": 0.90},
                "queues": {"total": 50, "filled": 30, "rate": 0.60},
            })
            mock_rfm.compute_deviation = AsyncMock(return_value={
                "total": 80, "deviated": 3, "deviation_rate": 0.0375, "kpi_met": True,
            })

            # Mock DB for RFM distribution + pending counts
            mock_rfm_result = AsyncMock()
            mock_rfm_result.all = MagicMock(return_value=[("S1", 10), ("S3", 50)])
            mock_db.execute = AsyncMock(return_value=mock_rfm_result)
            mock_db.scalar = AsyncMock(return_value=0)

            result = await service.get_dashboard(mock_db)

            assert "consumer_stats" in result
            assert result["consumer_stats"]["total_consumers"] == 100
            assert "fill_rate" in result
            assert result["fill_rate"]["orders"]["rate"] == 0.85
            assert "kpi_summary" in result
            assert result["kpi_summary"]["all_met"] is True
            assert result["fill_rate_health"] == "good"

    @pytest.mark.asyncio
    async def test_full_backfill_pipeline(self, service, mock_db):
        """测试全量回填管道调用顺序"""
        with patch("src.services.cdp_sync_service.cdp_sync_service") as mock_sync, \
             patch("src.services.cdp_rfm_service.cdp_rfm_service") as mock_rfm:

            mock_sync.sync_store_orders = AsyncMock(return_value={
                "total": 50, "resolved": 45, "failed": 5, "skipped": 10,
            })
            mock_sync.get_fill_rate = AsyncMock(return_value={
                "orders": {"total": 1000, "filled": 900, "rate": 0.90},
                "reservations": {"total": 200, "filled": 190, "rate": 0.95},
                "queues": {"total": 50, "filled": 40, "rate": 0.80},
            })
            mock_rfm.backfill_members = AsyncMock(return_value={
                "total": 30, "linked": 28, "failed": 2,
            })
            mock_rfm.recalculate_all = AsyncMock(return_value={
                "consumers_updated": 100, "members_updated": 80,
            })
            mock_rfm.compute_deviation = AsyncMock(return_value={
                "total": 80, "deviated": 2, "deviation_rate": 0.025, "kpi_met": True,
            })
            mock_db.commit = AsyncMock()

            result = await service.run_full_backfill(mock_db, store_id="S001")

            assert "steps" in result
            assert result["steps"]["backfill_orders"]["resolved"] == 45
            assert result["steps"]["backfill_members"]["linked"] == 28
            assert result["steps"]["rfm_recalculate"]["consumers_updated"] == 100
            assert result["steps"]["deviation_check"]["kpi_met"] is True
            assert result["kpi_summary"]["all_met"] is True
            assert mock_db.commit.call_count >= 3


# ══════════════════════════════════════════════════════════════════
# RFM 纯函数回归测试（确保评分一致性）
# ══════════════════════════════════════════════════════════════════

from src.services.cdp_rfm_service import (
    score_recency,
    score_frequency,
    score_monetary,
    classify_rfm_level,
    compute_risk_score,
)


class TestRFMPureFunctions:

    def test_recency_scores(self):
        assert score_recency(3) == 5
        assert score_recency(10) == 4
        assert score_recency(20) == 3
        assert score_recency(45) == 2
        assert score_recency(90) == 1

    def test_frequency_scores(self):
        assert score_frequency(25) == 5
        assert score_frequency(12) == 4
        assert score_frequency(7) == 3
        assert score_frequency(3) == 2
        assert score_frequency(1) == 1

    def test_monetary_scores(self):
        assert score_monetary(600000) == 5  # ¥6000
        assert score_monetary(300000) == 4  # ¥3000
        assert score_monetary(100000) == 3  # ¥1000
        assert score_monetary(30000) == 2   # ¥300
        assert score_monetary(5000) == 1    # ¥50

    def test_rfm_levels(self):
        assert classify_rfm_level(5, 5, 5) == "S1"  # 15 >= 13
        assert classify_rfm_level(4, 3, 3) == "S2"  # 10 >= 10
        assert classify_rfm_level(3, 2, 2) == "S3"  # 7 >= 7
        assert classify_rfm_level(2, 1, 1) == "S4"  # 4 >= 4
        assert classify_rfm_level(1, 1, 1) == "S5"  # 3 < 4

    def test_risk_score_high(self):
        risk = compute_risk_score(1, 1, 1)
        assert risk == 1.0

    def test_risk_score_low(self):
        risk = compute_risk_score(5, 5, 5)
        assert risk == 0.0

    def test_risk_score_r_weighted(self):
        # R=1 高权重，F/M=5 低权重
        risk = compute_risk_score(1, 5, 5)
        assert risk == 0.6  # 0.6 * 1.0 + 0.2 * 0.0 + 0.2 * 0.0
