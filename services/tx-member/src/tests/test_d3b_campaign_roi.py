"""test_d3b_campaign_roi.py —— Sprint D3b 活动 ROI 预测测试

覆盖：
  1. mean_absolute_percentage_error 边界（空/全零/标准场景）
  2. moving_average_forecast 单调性 + confidence 随 CV 变化
  3. linear_trend_forecast 斜率方向 + R² confidence
  4. try_prophet_forecast 未装时返 None（降级路径）
  5. CampaignROIForecastService.forecast_baseline 三级降级
  6. backtest MAPE 计算 + needs_calibration 阈值
  7. Sonnet 分析：有/无 invoker 的降级路径
  8. Sonnet 响应解析 action|lift|priority 格式
  9. v277 迁移静态校验（RLS + CHECK + 索引 + status 枚举）
  10. ModelRouter 注册 campaign_roi_forecast → MODERATE
"""
from __future__ import annotations

import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.campaign_roi_forecast_service import (  # noqa: E402
    MAPE_THRESHOLD,
    BacktestResult,
    CampaignROIForecastService,
    ForecastResult,
    TimeSeriesPoint,
    linear_trend_forecast,
    mean_absolute_percentage_error,
    moving_average_forecast,
    try_prophet_forecast,
)

# ──────────────────────────────────────────────────────────────────────
# 1. MAPE 计算
# ──────────────────────────────────────────────────────────────────────

def test_mape_empty_returns_one():
    assert mean_absolute_percentage_error([], []) == 1.0


def test_mape_length_mismatch_returns_one():
    assert mean_absolute_percentage_error([100, 200], [100]) == 1.0


def test_mape_skips_zero_actuals():
    # actual=0 的点跳过，只算其余
    result = mean_absolute_percentage_error([100, 0, 200], [110, 50, 180])
    # |100-110|/100 = 0.1, |200-180|/200 = 0.1 → 平均 0.1
    assert result == pytest.approx(0.1, abs=0.001)


def test_mape_all_zero_actuals_returns_one():
    assert mean_absolute_percentage_error([0, 0, 0], [1, 2, 3]) == 1.0


def test_mape_perfect_prediction_returns_zero():
    assert mean_absolute_percentage_error([100, 200, 300], [100, 200, 300]) == 0.0


# ──────────────────────────────────────────────────────────────────────
# 2. Moving Average Forecast
# ──────────────────────────────────────────────────────────────────────

def test_moving_average_empty_history_returns_empty():
    by_day, conf = moving_average_forecast([], 5)
    assert by_day == {}
    assert conf == 0.0


def test_moving_average_constant_series_high_confidence():
    """稳定序列 → CV=0 → confidence 高"""
    history = [
        TimeSeriesPoint(day=date(2026, 1, i + 1), revenue_fen=10000)
        for i in range(10)
    ]
    by_day, conf = moving_average_forecast(history, 3)
    assert len(by_day) == 3
    # 所有预测等于历史均值
    for val in by_day.values():
        assert val == 10000
    assert conf > 0.8, "稳定序列应有高 confidence"


def test_moving_average_high_variance_low_confidence():
    """震荡序列 → CV 大 → confidence 低"""
    history = [
        TimeSeriesPoint(day=date(2026, 1, i + 1), revenue_fen=v)
        for i, v in enumerate([1000, 100000, 5000, 80000, 3000, 60000, 2000])
    ]
    _, conf = moving_average_forecast(history, 3)
    assert conf < 0.6, f"高方差序列 confidence 应低，实际 {conf}"


# ──────────────────────────────────────────────────────────────────────
# 3. Linear Trend Forecast
# ──────────────────────────────────────────────────────────────────────

def test_linear_trend_less_than_two_points():
    by_day, conf = linear_trend_forecast([
        TimeSeriesPoint(day=date(2026, 1, 1), revenue_fen=100),
    ], 5)
    assert by_day == {}
    assert conf == 0.0


def test_linear_trend_positive_slope():
    """单调递增 → 预测值大于最后一个历史值"""
    history = [
        TimeSeriesPoint(day=date(2026, 1, i + 1), revenue_fen=1000 + i * 100)
        for i in range(5)
    ]
    # 第 5 天 = 1400，预测第 6 天应 > 1400
    by_day, conf = linear_trend_forecast(history, 1)
    first_pred = list(by_day.values())[0]
    assert first_pred > 1400
    # 完美线性 R²=1.0，但我们 cap 在 0.85 上限避免过度自信
    assert conf >= 0.8, f"完美线性应接近 confidence 上限 0.85，实际 {conf}"


def test_linear_trend_random_low_r2():
    """纯随机序列 → R² 低"""
    history = [
        TimeSeriesPoint(day=date(2026, 1, i + 1), revenue_fen=v)
        for i, v in enumerate([5000, 8000, 2000, 7000, 3000, 9000, 1000])
    ]
    _, conf = linear_trend_forecast(history, 3)
    assert conf < 0.5


# ──────────────────────────────────────────────────────────────────────
# 4. Prophet 降级
# ──────────────────────────────────────────────────────────────────────

def test_try_prophet_returns_none_when_not_installed():
    """Prophet 在测试环境通常不可用 → 返 None"""
    # 即便 Prophet 装了，数据不足 30 点时也应返 None
    history = [
        TimeSeriesPoint(day=date(2026, 1, i + 1), revenue_fen=1000)
        for i in range(5)
    ]
    assert try_prophet_forecast(history, 7) is None


# ──────────────────────────────────────────────────────────────────────
# 5. Service 三级降级
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_service_small_history_falls_back_to_linear_or_moving():
    """history < 30 点 → 走 linear 或 moving_average，不触发 prophet"""
    service = CampaignROIForecastService()
    history = [
        TimeSeriesPoint(day=date(2026, 1, i + 1), revenue_fen=5000 + i * 100)
        for i in range(10)
    ]
    forecast = await service.forecast_baseline(
        history=history,
        forecast_start=date(2026, 1, 15),
        forecast_end=date(2026, 1, 20),
    )
    assert forecast.model in ("linear", "moving_average")
    assert forecast.baseline_total_fen > 0
    assert 0 < forecast.confidence <= 1


@pytest.mark.asyncio
async def test_service_empty_history_returns_error_or_empty():
    service = CampaignROIForecastService()
    forecast = await service.forecast_baseline(
        history=[],
        forecast_start=date(2026, 1, 1),
        forecast_end=date(2026, 1, 5),
    )
    # 空 history 走 moving_average 但返 {}
    assert forecast.baseline_fen_by_day == {}
    assert forecast.baseline_total_fen == 0


@pytest.mark.asyncio
async def test_service_invalid_date_range_returns_error():
    service = CampaignROIForecastService()
    forecast = await service.forecast_baseline(
        history=[TimeSeriesPoint(day=date(2026, 1, 1), revenue_fen=100)],
        forecast_start=date(2026, 2, 1),
        forecast_end=date(2026, 1, 15),
    )
    assert forecast.model == "error"


# ──────────────────────────────────────────────────────────────────────
# 6. Backtest
# ──────────────────────────────────────────────────────────────────────

def test_backtest_perfect_prediction_mape_zero():
    service = CampaignROIForecastService()
    baseline = {date(2026, 1, 1): 10000, date(2026, 1, 2): 11000}
    actual = {date(2026, 1, 1): 10000, date(2026, 1, 2): 11000}
    result = service.backtest(baseline, actual)
    assert result.true_uplift_fen == 0
    assert result.mape == 0.0
    assert result.needs_calibration is False


def test_backtest_positive_uplift_within_mape_threshold():
    service = CampaignROIForecastService()
    # baseline 1 万 → 活动做到 1.1 万，MAPE=10%（阈值 20% 内）
    baseline = {date(2026, 1, 1): 10000}
    actual = {date(2026, 1, 1): 11000}
    result = service.backtest(baseline, actual)
    assert result.true_uplift_fen == 1000
    assert result.mape == pytest.approx(10 / 110, abs=0.01)  # |11000-10000|/11000
    assert result.needs_calibration is False


def test_backtest_exceeds_mape_threshold():
    service = CampaignROIForecastService()
    # baseline 1 万 → actual 5 万，MAPE 80% → 触发 calibration
    baseline = {date(2026, 1, 1): 10000}
    actual = {date(2026, 1, 1): 50000}
    result = service.backtest(baseline, actual)
    assert result.mape > MAPE_THRESHOLD
    assert result.needs_calibration is True


# ──────────────────────────────────────────────────────────────────────
# 7. Sonnet 分析
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_analyze_fallback_when_no_invoker_and_no_backtest():
    service = CampaignROIForecastService()
    forecast = ForecastResult(
        model="moving_average",
        baseline_total_fen=100000,
        confidence=0.7,
    )
    analysis, actions = await service.analyze_with_sonnet(
        campaign_name="测试活动",
        campaign_type="seasonal",
        forecast=forecast,
        backtest=None,
    )
    assert "测试活动" in analysis
    assert actions == []


@pytest.mark.asyncio
async def test_analyze_fallback_positive_uplift_within_mape():
    service = CampaignROIForecastService()
    forecast = ForecastResult(model="prophet", baseline_total_fen=100000, confidence=0.8)
    backtest = BacktestResult(
        true_revenue_fen=120000, true_baseline_fen=100000,
        true_uplift_fen=20000, mape=0.10, needs_calibration=False,
    )
    analysis, actions = await service.analyze_with_sonnet(
        campaign_name="春节大促", campaign_type="seasonal",
        forecast=forecast, backtest=backtest,
    )
    assert "春节大促" in analysis
    assert any(a.get("action") == "记录活动模板入 playbook" for a in actions)


@pytest.mark.asyncio
async def test_analyze_fallback_needs_calibration():
    service = CampaignROIForecastService()
    forecast = ForecastResult(model="linear", baseline_total_fen=100000, confidence=0.5)
    backtest = BacktestResult(
        true_revenue_fen=500000, true_baseline_fen=100000,
        true_uplift_fen=400000, mape=0.80, needs_calibration=True,
    )
    analysis, actions = await service.analyze_with_sonnet(
        campaign_name="异常活动", campaign_type="referral",
        forecast=forecast, backtest=backtest,
    )
    assert "needs_calibration" in analysis or "80" in analysis or "0.80" in analysis or "MAPE" in analysis
    # 需 calibration 时 actions 包含 "剔除"
    assert any("剔除" in a["action"] for a in actions)


@pytest.mark.asyncio
async def test_analyze_with_invoker_uses_sonnet_response():
    invoked = []

    async def mock_sonnet(prompt: str, model_id: str) -> str:
        invoked.append({"prompt": prompt, "model": model_id})
        return (
            "活动增量显著，建议沉淀模板。\n"
            "action1|5000|high\n"
            "action2|2000|med\n"
        )

    service = CampaignROIForecastService(sonnet_invoker=mock_sonnet)
    forecast = ForecastResult(model="prophet", baseline_total_fen=100000, confidence=0.9)
    backtest = BacktestResult(
        true_revenue_fen=120000, true_baseline_fen=100000,
        true_uplift_fen=20000, mape=0.1, needs_calibration=False,
    )
    analysis, actions = await service.analyze_with_sonnet(
        campaign_name="test", campaign_type="seasonal",
        forecast=forecast, backtest=backtest,
    )
    assert len(invoked) == 1
    assert invoked[0]["model"] == "claude-sonnet-4-6"
    assert "模板" in analysis
    # 应解析 2 条 action
    assert len(actions) == 2
    assert actions[0]["action"] == "action1"
    assert actions[0]["expected_lift_fen"] == 5000
    assert actions[0]["priority"] == "high"


@pytest.mark.asyncio
async def test_analyze_sonnet_failure_falls_back():
    async def boom_sonnet(prompt: str, model_id: str) -> str:
        raise RuntimeError("API 500")

    service = CampaignROIForecastService(sonnet_invoker=boom_sonnet)
    forecast = ForecastResult(model="prophet", baseline_total_fen=100000, confidence=0.8)
    analysis, actions = await service.analyze_with_sonnet(
        campaign_name="failing", campaign_type="seasonal",
        forecast=forecast, backtest=None,
    )
    # 不 crash，降级模板
    assert "failing" in analysis


# ──────────────────────────────────────────────────────────────────────
# 8. v277 迁移静态校验
# ──────────────────────────────────────────────────────────────────────

_MIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..",
    "shared", "db-migrations", "versions", "v277_campaign_roi_forecasts.py"
)


def _read_migration() -> str:
    if not os.path.exists(_MIG_PATH):
        pytest.skip("v277 迁移不存在")
    with open(_MIG_PATH, encoding="utf-8") as f:
        return f.read()


def test_v277_creates_table_with_all_required_columns():
    content = _read_migration()
    for col in (
        "baseline_forecast_fen", "uplift_forecast_fen", "forecast_confidence",
        "actual_revenue_fen", "true_uplift_fen", "mape", "needs_calibration",
        "sonnet_analysis", "recommended_actions", "training_data_snapshot",
        "forecast_model", "status",
    ):
        assert col in content, f"缺列: {col}"


def test_v277_has_status_enum_and_check_constraints():
    content = _read_migration()
    for st in ("plan", "running", "completed", "cancelled", "error"):
        assert st in content, f"缺 status 值: {st}"
    assert "CHECK" in content
    assert "baseline_forecast_fen >= 0" in content
    assert "forecast_confidence" in content
    assert "forecast_end >= forecast_start" in content


def test_v277_has_rls_and_indexes():
    content = _read_migration()
    assert "ENABLE ROW LEVEL SECURITY" in content
    assert "campaign_roi_tenant_isolation" in content
    assert "app.tenant_id" in content
    assert "idx_campaign_roi_tenant_status" in content
    assert "idx_campaign_roi_needs_calibration" in content


def test_v277_down_revision_chains_to_v276():
    content = _read_migration()
    assert 'down_revision = "v276"' in content


# ──────────────────────────────────────────────────────────────────────
# 9. ModelRouter 注册
# ──────────────────────────────────────────────────────────────────────

def test_model_router_registers_campaign_roi_as_moderate():
    path = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "..",
        "services", "tunxiang-api", "src", "shared", "core", "model_router.py"
    )
    if not os.path.exists(path):
        pytest.skip("model_router.py 不存在")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert '"campaign_roi_forecast": TaskComplexity.MODERATE' in content
    assert '"claude-sonnet-4-6"' in content, "MODERATE 复杂度应映射到 Sonnet"
