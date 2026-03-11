from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.labor_benchmark_service import (
    LaborBenchmarkService,
    classify_store_size,
    evaluate_against_benchmark,
    get_hunan_benchmark,
)


def _result(row):
    result = MagicMock()
    result.fetchone.return_value = row
    return result


def test_classify_store_size_small():
    assert classify_store_size(120, 80) == "small"


def test_classify_store_size_medium_by_area():
    assert classify_store_size(300, 60) == "medium"


def test_classify_store_size_large_by_seats():
    assert classify_store_size(200, 260) == "large"


def test_classify_store_size_large_by_area():
    assert classify_store_size(600, 50) == "large"


def test_classify_store_size_medium_by_seats():
    assert classify_store_size(100, 130) == "medium"


def test_classify_store_size_none_values():
    assert classify_store_size(None, None) == "small"


def test_get_hunan_benchmark_small():
    bm = get_hunan_benchmark("small")
    assert bm["labor_cost_rate_target"] == 24.0
    assert bm["labor_efficiency_target"] == 1100.0


def test_get_hunan_benchmark_large():
    bm = get_hunan_benchmark("large")
    assert bm["labor_cost_rate_target"] == 20.0
    assert bm["labor_efficiency_target"] == 1500.0


def test_get_hunan_benchmark_fallback():
    bm = get_hunan_benchmark("unknown")
    assert bm["labor_cost_rate_target"] == 22.0


def test_evaluate_against_benchmark_excellent():
    out = evaluate_against_benchmark(
        labor_cost_rate=20,
        labor_efficiency=1600,
        benchmark={"labor_cost_rate_target": 22, "labor_efficiency_target": 1300},
    )
    assert out["health_level"] == "excellent"


def test_evaluate_against_benchmark_critical():
    out = evaluate_against_benchmark(
        labor_cost_rate=30,
        labor_efficiency=900,
        benchmark={"labor_cost_rate_target": 22, "labor_efficiency_target": 1300},
    )
    assert out["health_level"] == "critical"


def test_evaluate_against_benchmark_good():
    out = evaluate_against_benchmark(
        labor_cost_rate=23,
        labor_efficiency=1210,
        benchmark={"labor_cost_rate_target": 22, "labor_efficiency_target": 1300},
    )
    assert out["health_level"] == "good"


def test_evaluate_against_benchmark_warning():
    out = evaluate_against_benchmark(
        labor_cost_rate=25,
        labor_efficiency=1100,
        benchmark={"labor_cost_rate_target": 22, "labor_efficiency_target": 1300},
    )
    assert out["health_level"] == "warning"


def test_evaluate_against_benchmark_gap_values():
    out = evaluate_against_benchmark(
        labor_cost_rate=25.0,
        labor_efficiency=1200.0,
        benchmark={"labor_cost_rate_target": 22.0, "labor_efficiency_target": 1300.0},
    )
    assert out["rate_gap_pct"] == 3.0
    assert out["efficiency_gap"] == -100.0


@pytest.mark.asyncio
async def test_get_store_monthly_benchmark_ok():
    db = AsyncMock()

    store_row = MagicMock()
    store_row.id = "S001"
    store_row.name = "徐记海鲜-测试店"
    store_row.area = 280
    store_row.seats = 130

    snap_row = MagicMock()
    snap_row.avg_rate = 23.2
    snap_row.avg_efficiency = 1288.0

    db.execute = AsyncMock(side_effect=[_result(store_row), _result(snap_row)])

    data = await LaborBenchmarkService.get_store_monthly_benchmark("S001", "2026-03", db)

    assert data["store_id"] == "S001"
    assert data["size_tier"] == "medium"
    assert data["actual"]["labor_cost_rate"] == 23.2
    assert "health_level" in data["evaluation"]


@pytest.mark.asyncio
async def test_get_store_monthly_benchmark_store_not_found():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_result(None))

    with pytest.raises(ValueError):
        await LaborBenchmarkService.get_store_monthly_benchmark("NOPE", "2026-03", db)


@pytest.mark.asyncio
async def test_get_store_monthly_benchmark_no_snapshot_data():
    db = AsyncMock()

    store_row = MagicMock()
    store_row.id = "S001"
    store_row.name = "门店"
    store_row.area = 100
    store_row.seats = 80

    snap_row = MagicMock()
    snap_row.avg_rate = None
    snap_row.avg_efficiency = None

    db.execute = AsyncMock(side_effect=[_result(store_row), _result(snap_row)])

    data = await LaborBenchmarkService.get_store_monthly_benchmark("S001", "2026-03", db)

    assert data["actual"]["labor_cost_rate"] == 0.0
    assert data["actual"]["labor_efficiency"] == 0.0


@pytest.mark.asyncio
async def test_get_store_monthly_benchmark_december_boundary():
    """12月边界：end_date 应跨年到下一年1月。"""
    db = AsyncMock()

    store_row = MagicMock()
    store_row.id = "S001"
    store_row.name = "门店"
    store_row.area = 200
    store_row.seats = 90

    snap_row = MagicMock()
    snap_row.avg_rate = 21.5
    snap_row.avg_efficiency = 1350.0

    db.execute = AsyncMock(side_effect=[_result(store_row), _result(snap_row)])

    data = await LaborBenchmarkService.get_store_monthly_benchmark("S001", "2025-12", db)
    assert data["month"] == "2025-12"
    assert data["actual"]["labor_cost_rate"] == 21.5


@pytest.mark.asyncio
async def test_get_peer_group_baseline_medium():
    db = AsyncMock()

    row = MagicMock()
    row.store_count = 12
    row.avg_rate = 22.8
    row.avg_efficiency = 1312.4

    db.execute = AsyncMock(return_value=_result(row))

    data = await LaborBenchmarkService.get_peer_group_baseline("2026-03", "medium", db)

    assert data["size_tier"] == "medium"
    assert data["store_count"] == 12
    assert data["avg_labor_cost_rate"] == 22.8


@pytest.mark.asyncio
async def test_get_peer_group_baseline_empty():
    db = AsyncMock()

    row = MagicMock()
    row.store_count = None
    row.avg_rate = None
    row.avg_efficiency = None

    db.execute = AsyncMock(return_value=_result(row))

    data = await LaborBenchmarkService.get_peer_group_baseline("2026-03", "small", db)

    assert data["store_count"] == 0
    assert data["avg_labor_cost_rate"] == 0.0


@pytest.mark.asyncio
async def test_get_peer_group_baseline_large():
    db = AsyncMock()

    row = MagicMock()
    row.store_count = 3
    row.avg_rate = 19.5
    row.avg_efficiency = 1620.0

    db.execute = AsyncMock(return_value=_result(row))

    data = await LaborBenchmarkService.get_peer_group_baseline("2026-03", "large", db)

    assert data["size_tier"] == "large"
    assert data["avg_labor_efficiency"] == 1620.0

