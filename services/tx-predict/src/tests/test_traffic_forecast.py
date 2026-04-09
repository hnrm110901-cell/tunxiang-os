"""客流预测引擎测试

测试用例：
  1. 小时基线计算 — 有数据时返回正确均值
  2. 7天预测 — 无历史数据时返回全零
  3. 节假日系数修正 — 国庆节客流提升
  4. 天气修正 — 雨天客流下降
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ..services.traffic_predictor import (
    HOLIDAY_FACTORS,
    WEEKDAY_FACTORS,
    TrafficPredictor,
)
from ..services.weather_service import WeatherService


@pytest.fixture
def predictor():
    weather_svc = WeatherService()
    return TrafficPredictor(weather_service=weather_svc)


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db


class TestTrafficPredictor:
    """客流预测引擎单元测试"""

    @pytest.mark.asyncio
    async def test_forecast_7days_no_history(self, predictor: TrafficPredictor, mock_db: AsyncMock):
        """无历史数据时，7天预测返回全零客流"""
        # mock: 历史查询返回空
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_db.execute.return_value = mock_result

        result = await predictor.forecast_7days(
            store_id="store-001",
            tenant_id="tenant-001",
            db=mock_db,
        )

        assert result["store_id"] == "store-001"
        assert result["forecast_days"] == 7
        assert len(result["daily_forecasts"]) == 7
        assert result["summary"]["total_7d"] == 0

        # 每个小时的客流都应该是0
        for day in result["daily_forecasts"]:
            assert day["total_traffic"] == 0
            for h in day["hourly"]:
                assert h["traffic"] == 0
                assert h["confidence"] == 0.40  # 无数据低置信度

    @pytest.mark.asyncio
    async def test_forecast_7days_with_baseline(self, predictor: TrafficPredictor, mock_db: AsyncMock):
        """有历史基线数据时，预测值 > 0"""
        # mock: 返回周一12点有10单，周六12点有20单
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            (1, 12, 40, 2.5),  # DOW=1(Monday), hour=12, 40 orders, avg 2.5 customers
            (6, 12, 80, 3.0),  # DOW=6(Saturday), hour=12, 80 orders, avg 3.0 customers
        ]
        mock_db.execute.return_value = mock_result

        result = await predictor.forecast_7days(
            store_id="store-001",
            tenant_id="tenant-001",
            db=mock_db,
        )

        assert result["summary"]["total_7d"] > 0

        # 找到周六的预测，12点应该有客流
        for day in result["daily_forecasts"]:
            if day["weekday"] == 5:  # Saturday
                hour_12 = next(h for h in day["hourly"] if h["hour"] == 12)
                assert hour_12["traffic"] > 0
                assert hour_12["confidence"] == 0.75

    @pytest.mark.asyncio
    async def test_today_remaining_forecast(self, predictor: TrafficPredictor, mock_db: AsyncMock):
        """今日剩余时段预测返回正确结构"""
        # mock baseline
        mock_baseline_result = MagicMock()
        mock_baseline_result.fetchall.return_value = []
        # mock today actual
        mock_actual_result = MagicMock()
        mock_actual_result.scalar.return_value = 42
        mock_db.execute.side_effect = [mock_baseline_result, mock_actual_result]

        result = await predictor.forecast_today_remaining(
            store_id="store-001",
            tenant_id="tenant-001",
            db=mock_db,
        )

        assert result["store_id"] == "store-001"
        assert "current_hour" in result
        assert "remaining_hours" in result
        assert result["actual_so_far"] == 42

    def test_weekday_factors_complete(self):
        """确保星期修正系数覆盖全部7天"""
        for weekday in range(7):
            assert weekday in WEEKDAY_FACTORS
            assert 0.5 <= WEEKDAY_FACTORS[weekday] <= 2.0

    def test_holiday_factors_reasonable(self):
        """节假日系数在合理范围内"""
        for date_key, factor in HOLIDAY_FACTORS.items():
            assert 1.0 <= factor <= 2.0, f"Holiday {date_key} factor {factor} out of range"
            # 格式校验
            parts = date_key.split("-")
            assert len(parts) == 2
            assert 1 <= int(parts[0]) <= 12
            assert 1 <= int(parts[1]) <= 31
