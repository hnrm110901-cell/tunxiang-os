"""
StoreHealthIndex 单元测试

覆盖：
  - aggregate_pillars: 全有/缺一/全无/边界
  - _classify: 等级阈值
  - get_store_health_index: mock 三支柱，验证聚合结果
  - get_multi_store_health_index: 多店排序，单店失败不影响其他
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
from unittest.mock import AsyncMock, patch

from src.services.store_health_index_service import (
    _classify,
    aggregate_pillars,
    get_multi_store_health_index,
    get_store_health_index,
)


# ═══════════════════════════════════════════════════════════════════════════════
# aggregate_pillars
# ═══════════════════════════════════════════════════════════════════════════════

class TestAggregatePillars:
    def test_all_pillars_weighted_correctly(self):
        score = aggregate_pillars({
            "operational": 80, "private_domain": 70, "ai_diagnosis": 60
        })
        expected = round(80 * 0.40 + 70 * 0.35 + 60 * 0.25, 1)
        assert score == expected  # 73.5

    def test_missing_ai_diagnosis_renormalizes(self):
        # 只有 operational(0.40) + private_domain(0.35)，权重比 0.4:0.35 = 8:7
        score = aggregate_pillars({
            "operational": 80, "private_domain": 70, "ai_diagnosis": None
        })
        total_w = 0.40 + 0.35
        expected = round((80 * 0.40 + 70 * 0.35) / total_w, 1)
        assert abs(score - expected) < 0.05

    def test_single_pillar_returns_that_score(self):
        score = aggregate_pillars({
            "operational": 72, "private_domain": None, "ai_diagnosis": None
        })
        assert score == 72.0

    def test_all_none_returns_50(self):
        score = aggregate_pillars({
            "operational": None, "private_domain": None, "ai_diagnosis": None
        })
        assert score == 50.0

    def test_perfect_score(self):
        assert aggregate_pillars({"operational": 100, "private_domain": 100, "ai_diagnosis": 100}) == 100.0

    def test_zero_score(self):
        assert aggregate_pillars({"operational": 0, "private_domain": 0, "ai_diagnosis": 0}) == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# _classify
# ═══════════════════════════════════════════════════════════════════════════════

class TestClassify:
    def test_excellent_boundary(self):
        assert _classify(85.0) == "excellent"
        assert _classify(100.0) == "excellent"

    def test_good_range(self):
        assert _classify(70.0) == "good"
        assert _classify(84.9) == "good"

    def test_needs_improvement_range(self):
        assert _classify(50.0) == "needs_improvement"
        assert _classify(69.9) == "needs_improvement"

    def test_alert_below_50(self):
        assert _classify(49.9) == "alert"
        assert _classify(0.0) == "alert"


# ═══════════════════════════════════════════════════════════════════════════════
# get_store_health_index (mock IO)
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetStoreHealthIndex:
    @pytest.mark.asyncio
    async def test_all_pillars_available(self):
        mock_db = AsyncMock()
        with (
            patch("src.services.store_health_index_service._get_operational_score",
                  AsyncMock(return_value=80.0)),
            patch("src.services.store_health_index_service._get_private_domain_score",
                  AsyncMock(return_value=70.0)),
            patch("src.services.store_health_index_service._get_ai_diagnosis_score",
                  AsyncMock(return_value=60.0)),
            patch("src.services.store_health_index_service._save_snapshot",
                  AsyncMock()),
            patch("src.services.store_health_index_service._get_trend",
                  AsyncMock(return_value=[])),
        ):
            result = await get_store_health_index("S001", mock_db, save_snapshot=False)

        assert result["store_id"] == "S001"
        assert 60 < result["score"] < 90
        assert result["level"] in {"excellent", "good", "needs_improvement", "alert"}
        assert "pillars" in result
        assert result["pillars"]["operational"]["score"] == 80.0
        assert result["pillars"]["private_domain"]["score"] == 70.0
        assert result["pillars"]["ai_diagnosis"]["score"] == 60.0

    @pytest.mark.asyncio
    async def test_partial_pillars_still_returns_score(self):
        mock_db = AsyncMock()
        with (
            patch("src.services.store_health_index_service._get_operational_score",
                  AsyncMock(return_value=85.0)),
            patch("src.services.store_health_index_service._get_private_domain_score",
                  AsyncMock(return_value=None)),
            patch("src.services.store_health_index_service._get_ai_diagnosis_score",
                  AsyncMock(return_value=None)),
            patch("src.services.store_health_index_service._save_snapshot", AsyncMock()),
            patch("src.services.store_health_index_service._get_trend", AsyncMock(return_value=[])),
        ):
            result = await get_store_health_index("S002", mock_db, save_snapshot=False)

        assert result["score"] == 85.0   # 单支柱直接等于该支柱分

    @pytest.mark.asyncio
    async def test_excellent_level_at_85(self):
        mock_db = AsyncMock()
        with (
            patch("src.services.store_health_index_service._get_operational_score",
                  AsyncMock(return_value=90.0)),
            patch("src.services.store_health_index_service._get_private_domain_score",
                  AsyncMock(return_value=88.0)),
            patch("src.services.store_health_index_service._get_ai_diagnosis_score",
                  AsyncMock(return_value=85.0)),
            patch("src.services.store_health_index_service._save_snapshot", AsyncMock()),
            patch("src.services.store_health_index_service._get_trend", AsyncMock(return_value=[])),
        ):
            result = await get_store_health_index("S003", mock_db, save_snapshot=False)

        assert result["level"] == "excellent"
        assert result["level_label"] == "优秀"
        assert result["level_color"] == "green"

    @pytest.mark.asyncio
    async def test_response_contains_all_required_fields(self):
        mock_db = AsyncMock()
        with (
            patch("src.services.store_health_index_service._get_operational_score",
                  AsyncMock(return_value=75.0)),
            patch("src.services.store_health_index_service._get_private_domain_score",
                  AsyncMock(return_value=65.0)),
            patch("src.services.store_health_index_service._get_ai_diagnosis_score",
                  AsyncMock(return_value=70.0)),
            patch("src.services.store_health_index_service._save_snapshot", AsyncMock()),
            patch("src.services.store_health_index_service._get_trend",
                  AsyncMock(return_value=[{"date": "2026-03-18", "score": 72.0}])),
        ):
            result = await get_store_health_index("S004", mock_db, save_snapshot=False)

        for field in ("store_id", "score", "level", "level_label", "level_color",
                      "pillars", "computed_at", "trend"):
            assert field in result, f"missing field: {field}"
        assert len(result["trend"]) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# get_multi_store_health_index
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetMultiStoreHealthIndex:
    @pytest.mark.asyncio
    async def test_sorted_by_score_descending(self):
        mock_db = AsyncMock()
        _data = {
            "S001": {"store_id": "S001", "score": 65.0, "level": "good",      "level_label": "良好", "level_color": "blue",  "pillars": {}, "computed_at": "x", "trend": []},
            "S002": {"store_id": "S002", "score": 85.0, "level": "excellent", "level_label": "优秀", "level_color": "green", "pillars": {}, "computed_at": "x", "trend": []},
            "S003": {"store_id": "S003", "score": 45.0, "level": "alert",     "level_label": "预警", "level_color": "red",   "pillars": {}, "computed_at": "x", "trend": []},
        }
        async def _mock_get(store_id, db, **_kw):
            return _data[store_id]

        with patch("src.services.store_health_index_service.get_store_health_index",
                   side_effect=_mock_get):
            results = await get_multi_store_health_index(["S001", "S002", "S003"], mock_db)

        assert results[0]["store_id"] == "S002"  # 85 first
        assert results[1]["store_id"] == "S001"  # 65 second
        assert results[2]["store_id"] == "S003"  # 45 last

    @pytest.mark.asyncio
    async def test_single_store_failure_does_not_break_others(self):
        mock_db = AsyncMock()
        async def _mock_get(store_id, db, **_kw):
            if store_id == "FAIL":
                raise RuntimeError("simulated DB failure")
            return {"store_id": store_id, "score": 70.0, "level": "good",
                    "level_label": "良好", "level_color": "blue",
                    "pillars": {}, "computed_at": "x", "trend": []}

        with patch(
            "src.services.store_health_index_service.get_store_health_index",
            side_effect=_mock_get,
        ):
            results = await get_multi_store_health_index(["S001", "FAIL", "S002"], mock_db)

        store_ids = [r["store_id"] for r in results]
        assert "S001" in store_ids
        assert "S002" in store_ids
        assert "FAIL" not in store_ids
