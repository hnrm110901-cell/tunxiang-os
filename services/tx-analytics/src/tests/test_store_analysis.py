"""门店经营分析服务 — 纯函数 + API 路由测试

覆盖：辅助函数、餐段判断、日期解析、API 路由校验、对比指标校验
"""

import os
import sys
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.store_analysis import (
    _date_range_to_timestamps,
    _determine_meal_period,
    _pct,
    _safe_avg_fen,
)

# ─── 辅助函数测试 ───


class TestSafeAvgFen:
    def test_normal(self):
        assert _safe_avg_fen(10000, 4) == 2500

    def test_zero_count(self):
        assert _safe_avg_fen(10000, 0) == 0

    def test_zero_total(self):
        assert _safe_avg_fen(0, 5) == 0


class TestPct:
    def test_normal(self):
        result = _pct(25, 100)
        assert result == Decimal("25.00")

    def test_zero_denominator(self):
        assert _pct(10, 0) == Decimal("0.00")

    def test_rounding(self):
        result = _pct(1, 3)
        assert result == Decimal("33.33")

    def test_over_hundred(self):
        result = _pct(150, 100)
        assert result == Decimal("150.00")


class TestDetermineMealPeriod:
    def test_breakfast(self):
        assert _determine_meal_period(7) == "breakfast"
        assert _determine_meal_period(9) == "breakfast"

    def test_lunch(self):
        assert _determine_meal_period(11) == "lunch"
        assert _determine_meal_period(13) == "lunch"

    def test_afternoon_tea(self):
        assert _determine_meal_period(15) == "afternoon_tea"
        assert _determine_meal_period(16) == "afternoon_tea"

    def test_dinner(self):
        assert _determine_meal_period(18) == "dinner"
        assert _determine_meal_period(20) == "dinner"

    def test_late_night(self):
        assert _determine_meal_period(22) == "late_night"
        assert _determine_meal_period(2) == "late_night"

    def test_boundaries(self):
        assert _determine_meal_period(6) == "breakfast"
        assert _determine_meal_period(10) == "lunch"
        assert _determine_meal_period(14) == "afternoon_tea"
        assert _determine_meal_period(17) == "dinner"
        assert _determine_meal_period(21) == "late_night"


class TestDateRangeToTimestamps:
    def test_single_day(self):
        dr = (date(2026, 3, 15), date(2026, 3, 15))
        start, end = _date_range_to_timestamps(dr)
        assert start.day == 15
        assert end.day == 16
        assert start.hour == 0
        assert end.hour == 0

    def test_multi_day(self):
        dr = (date(2026, 3, 1), date(2026, 3, 7))
        start, end = _date_range_to_timestamps(dr)
        assert start.day == 1
        assert end.day == 8

    def test_month_boundary(self):
        dr = (date(2026, 2, 28), date(2026, 3, 1))
        start, end = _date_range_to_timestamps(dr)
        assert start.month == 2
        assert end.month == 3
        assert end.day == 2


# ─── API 路由辅助函数测试 ───


from api.store_analysis_routes import _parse_date_range, _parse_store_id, _require_tenant
from fastapi import HTTPException


class TestRequireTenant:
    def test_valid_uuid(self):
        tid = str(uuid.uuid4())
        result = _require_tenant(tid)
        assert isinstance(result, uuid.UUID)

    def test_none_raises(self):
        with pytest.raises(HTTPException) as exc_info:
            _require_tenant(None)
        assert exc_info.value.status_code == 400

    def test_empty_raises(self):
        with pytest.raises(HTTPException) as exc_info:
            _require_tenant("")
        assert exc_info.value.status_code == 400

    def test_invalid_uuid_raises(self):
        with pytest.raises(HTTPException) as exc_info:
            _require_tenant("not-a-uuid")
        assert exc_info.value.status_code == 400


class TestParseDateRange:
    def test_defaults_to_last_7_days(self):
        sd, ed = _parse_date_range(None, None)
        assert ed == date.today()
        assert sd == date.today() - timedelta(days=6)

    def test_explicit_dates(self):
        sd, ed = _parse_date_range("2026-03-01", "2026-03-15")
        assert sd == date(2026, 3, 1)
        assert ed == date(2026, 3, 15)

    def test_start_after_end_raises(self):
        with pytest.raises(HTTPException) as exc_info:
            _parse_date_range("2026-03-15", "2026-03-01")
        assert exc_info.value.status_code == 422

    def test_invalid_format_raises(self):
        with pytest.raises(HTTPException) as exc_info:
            _parse_date_range("2026/03/01", None)
        assert exc_info.value.status_code == 422

    def test_range_exceeds_365_raises(self):
        with pytest.raises(HTTPException) as exc_info:
            _parse_date_range("2025-01-01", "2026-03-01")
        assert exc_info.value.status_code == 422


class TestParseStoreId:
    def test_valid(self):
        sid = str(uuid.uuid4())
        result = _parse_store_id(sid)
        assert isinstance(result, uuid.UUID)

    def test_invalid_raises(self):
        with pytest.raises(HTTPException) as exc_info:
            _parse_store_id("not-valid")
        assert exc_info.value.status_code == 422


# ─── 对比指标校验测试 ───


class TestComparisonMetricsValidation:
    """测试 store_comparison 的 metrics 校验逻辑"""

    @pytest.mark.asyncio
    async def test_invalid_metric_raises(self):
        from services.store_analysis import store_comparison

        with pytest.raises(ValueError, match="invalid metric"):
            await store_comparison(
                store_ids=[uuid.uuid4(), uuid.uuid4()],
                metrics=["invalid_metric"],
                date_range=(date(2026, 3, 1), date(2026, 3, 7)),
                tenant_id=uuid.uuid4(),
                db=None,
            )

    @pytest.mark.asyncio
    async def test_valid_metrics_accepted(self):
        """合法指标列表不应在校验阶段抛 ValueError（会在 db 阶段失败）"""
        from services.store_analysis import store_comparison

        # db=None 会在执行 SQL 时失败，但不应在 metrics 校验阶段失败
        with pytest.raises(AttributeError):
            # AttributeError: 'NoneType' has no attribute 'execute' — 说明通过了校验
            await store_comparison(
                store_ids=[uuid.uuid4()],
                metrics=["revenue", "orders"],
                date_range=(date(2026, 3, 1), date(2026, 3, 7)),
                tenant_id=uuid.uuid4(),
                db=None,
            )
