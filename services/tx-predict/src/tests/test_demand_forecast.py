"""菜品需求预测引擎测试

测试用例：
  1. 加权移动平均计算 — 近日权重高
  2. 无历史数据时返回空列表
  3. 备餐建议安全系数 — prep_qty > predicted_qty
  4. 季节系数正确应用
  5. WMA边界 — 只有1天数据
  6. 准确率追踪接口结构
"""
from __future__ import annotations

from datetime import date, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from ..services.demand_predictor import (
    PREP_SAFETY_FACTOR,
    SEASON_FACTORS,
    WEEKDAY_FACTORS,
    WMA_SUM,
    WMA_WEIGHTS,
    DemandPredictor,
    _get_season,
)
from ..services.weather_service import WeatherService


@pytest.fixture
def predictor():
    return DemandPredictor(weather_service=WeatherService())


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db


class TestDemandPredictor:
    """菜品需求预测单元测试"""

    def test_wma_weights_correct(self):
        """加权移动平均权重配置正确"""
        assert len(WMA_WEIGHTS) == 7
        assert WMA_WEIGHTS[0] == 7   # 最近一天权重最高
        assert WMA_WEIGHTS[-1] == 1  # 最早一天权重最低
        assert WMA_SUM == 28         # 总权重

    def test_wma_calculation(self, predictor: DemandPredictor):
        """WMA计算 — 近日数据权重更高"""
        today = date(2026, 4, 9)
        daily_sales = {
            "2026-04-08": 10,  # day-1, weight=7
            "2026-04-07": 10,  # day-2, weight=6
            "2026-04-06": 10,  # day-3, weight=5
            "2026-04-05": 10,  # day-4, weight=4
            "2026-04-04": 10,  # day-5, weight=3
            "2026-04-03": 10,  # day-6, weight=2
            "2026-04-02": 10,  # day-7, weight=1
        }
        result = predictor._calc_wma(daily_sales, today)
        # 全部相同，WMA = (10*7 + 10*6 + ... + 10*1) / 28 = 280/28 = 10
        assert result == 10.0

    def test_wma_recent_bias(self, predictor: DemandPredictor):
        """WMA近日偏重验证 — 近日高销量拉高预测"""
        today = date(2026, 4, 9)
        daily_sales = {
            "2026-04-08": 100,  # day-1, weight=7: 700
            "2026-04-07": 0,    # day-2, weight=6: 0
            "2026-04-06": 0,    # day-3, weight=5: 0
            "2026-04-05": 0,    # day-4, weight=4: 0
            "2026-04-04": 0,    # day-5, weight=3: 0
            "2026-04-03": 0,    # day-6, weight=2: 0
            "2026-04-02": 0,    # day-7, weight=1: 0
        }
        result = predictor._calc_wma(daily_sales, today)
        # WMA = 700 / 28 = 25.0
        assert result == 25.0

    @pytest.mark.asyncio
    async def test_forecast_demand_no_history(self, predictor: DemandPredictor, mock_db: AsyncMock):
        """无历史数据时返回空菜品列表"""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_db.execute.return_value = mock_result

        result = await predictor.forecast_demand(
            store_id="store-001",
            tenant_id="tenant-001",
            db=mock_db,
        )

        assert result["store_id"] == "store-001"
        assert result["dishes"] == []
        assert result["summary"]["total_dishes"] == 0

    @pytest.mark.asyncio
    async def test_prep_suggestion_safety_factor(self, predictor: DemandPredictor, mock_db: AsyncMock):
        """备餐建议的安全系数确保 prep_qty >= predicted_qty"""
        # mock: 返回一道菜有稳定销量
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("dish-001", "宫保鸡丁", "热菜", "2026-04-08", 20),
            ("dish-001", "宫保鸡丁", "热菜", "2026-04-07", 18),
            ("dish-001", "宫保鸡丁", "热菜", "2026-04-06", 22),
        ]
        mock_db.execute.return_value = mock_result

        result = await predictor.get_prep_suggestions(
            store_id="store-001",
            tenant_id="tenant-001",
            db=mock_db,
        )

        assert result["store_id"] == "store-001"
        for item in result.get("prep_items", []):
            assert item["prep_qty"] >= item["predicted_qty"]

    def test_season_factors_coverage(self):
        """季节系数覆盖四季"""
        assert set(SEASON_FACTORS.keys()) == {"summer", "winter", "spring", "autumn"}
        for season, factors in SEASON_FACTORS.items():
            for category, factor in factors.items():
                assert 0.3 <= factor <= 2.0, f"{season}/{category} factor {factor} out of range"

    def test_get_season_returns_valid(self):
        """_get_season 返回有效季节"""
        result = _get_season()
        assert result in ("summer", "winter", "spring", "autumn")

    def test_weekday_factors_complete(self):
        """星期修正系数覆盖7天"""
        for wd in range(7):
            assert wd in WEEKDAY_FACTORS

    @pytest.mark.asyncio
    async def test_accuracy_no_predictions(self, predictor: DemandPredictor, mock_db: AsyncMock):
        """无历史预测数据时，准确率接口返回提示"""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_db.execute.return_value = mock_result

        result = await predictor.get_accuracy(
            store_id="store-001",
            tenant_id="tenant-001",
            db=mock_db,
        )

        assert result["store_id"] == "store-001"
        assert result["overall_mape"] is None
        assert "暂无" in result.get("message", "")
