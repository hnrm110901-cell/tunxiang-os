"""Tests for dish_cost_alert_service.py — Phase 6 Month 3"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
import sys

mock_settings = MagicMock()
mock_settings.database_url = "postgresql+asyncpg://x:x@localhost/x"
mock_config_mod = MagicMock()
mock_config_mod.settings = mock_settings
sys.modules.setdefault("src.core.config", mock_config_mod)

from src.services.dish_cost_alert_service import (  # noqa: E402
    compute_mom_change,
    classify_fcr_severity,
    classify_margin_severity,
    classify_bcg_severity,
    detect_bcg_downgrade,
    compute_yuan_impact,
    generate_alert_message,
    build_dish_alerts,
    summarize_alerts,
    _prev_period,
    _start_period,
    generate_dish_cost_alerts,
    get_dish_cost_alerts,
    get_alert_summary,
    resolve_alert,
    get_store_cost_trend,
    get_dish_alert_history,
    ALERT_TYPES, ALERT_LABELS,
    FCR_SPIKE_INFO, FCR_SPIKE_WARNING, FCR_SPIKE_CRITICAL,
    MARGIN_DROP_INFO, MARGIN_DROP_WARNING, MARGIN_DROP_CRITICAL,
    BCG_RANK,
)


# ══════════════════════════════════════════════════════════════════════════════
# compute_mom_change
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeMomChange:
    def test_increase(self):
        assert abs(compute_mom_change(40.0, 35.0) - 14.29) < 0.1

    def test_decrease(self):
        assert abs(compute_mom_change(30.0, 40.0) - (-25.0)) < 0.1

    def test_zero_previous(self):
        assert compute_mom_change(40.0, 0.0) == 0.0

    def test_no_change(self):
        assert compute_mom_change(35.0, 35.0) == 0.0

    def test_negative_to_zero(self):
        # prev=-10 (loss) → current=0; MoM = (0-(-10))/10*100 = 100%
        assert abs(compute_mom_change(0.0, -10.0) - 100.0) < 0.1


# ══════════════════════════════════════════════════════════════════════════════
# classify_fcr_severity
# ══════════════════════════════════════════════════════════════════════════════

class TestClassifyFcrSeverity:
    def test_info(self):
        assert classify_fcr_severity(FCR_SPIKE_INFO) == 'info'

    def test_warning(self):
        assert classify_fcr_severity(FCR_SPIKE_WARNING) == 'warning'

    def test_critical(self):
        assert classify_fcr_severity(FCR_SPIKE_CRITICAL) == 'critical'

    def test_just_below_warning(self):
        assert classify_fcr_severity(FCR_SPIKE_WARNING - 0.1) == 'info'

    def test_just_below_critical(self):
        assert classify_fcr_severity(FCR_SPIKE_CRITICAL - 0.1) == 'warning'


# ══════════════════════════════════════════════════════════════════════════════
# classify_margin_severity
# ══════════════════════════════════════════════════════════════════════════════

class TestClassifyMarginSeverity:
    def test_info(self):
        assert classify_margin_severity(MARGIN_DROP_INFO) == 'info'

    def test_warning(self):
        assert classify_margin_severity(MARGIN_DROP_WARNING) == 'warning'

    def test_critical(self):
        assert classify_margin_severity(MARGIN_DROP_CRITICAL) == 'critical'

    def test_below_info_threshold(self):
        # Under MARGIN_DROP_INFO → would not trigger (but severity is still info if called)
        assert classify_margin_severity(3.0) == 'info'


# ══════════════════════════════════════════════════════════════════════════════
# classify_bcg_severity
# ══════════════════════════════════════════════════════════════════════════════

class TestClassifyBcgSeverity:
    def test_drop_1_is_info(self):
        assert classify_bcg_severity(1) == 'info'

    def test_drop_2_is_warning(self):
        assert classify_bcg_severity(2) == 'warning'

    def test_drop_3_is_critical(self):
        assert classify_bcg_severity(3) == 'critical'


# ══════════════════════════════════════════════════════════════════════════════
# detect_bcg_downgrade
# ══════════════════════════════════════════════════════════════════════════════

class TestDetectBcgDowngrade:
    def test_star_to_dog(self):
        assert detect_bcg_downgrade('dog', 'star') is True

    def test_star_to_cash_cow(self):
        assert detect_bcg_downgrade('cash_cow', 'star') is True

    def test_star_to_question_mark(self):
        assert detect_bcg_downgrade('question_mark', 'star') is True

    def test_cash_cow_to_dog(self):
        assert detect_bcg_downgrade('dog', 'cash_cow') is True

    def test_question_mark_to_dog(self):
        assert detect_bcg_downgrade('dog', 'question_mark') is True

    def test_dog_to_star_is_upgrade(self):
        assert detect_bcg_downgrade('star', 'dog') is False

    def test_same_quadrant(self):
        assert detect_bcg_downgrade('star', 'star')     is False
        assert detect_bcg_downgrade('cash_cow', 'cash_cow') is False

    def test_dog_to_dog(self):
        assert detect_bcg_downgrade('dog', 'dog') is False


# ══════════════════════════════════════════════════════════════════════════════
# compute_yuan_impact
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeYuanImpact:
    def test_normal(self):
        # 5pp change on ¥10000 revenue → ¥500
        assert abs(compute_yuan_impact(10000.0, 5.0) - 500.0) < 0.1

    def test_negative_change_uses_abs(self):
        assert abs(compute_yuan_impact(10000.0, -5.0) - 500.0) < 0.1

    def test_zero_revenue(self):
        assert compute_yuan_impact(0.0, 10.0) == 0.0

    def test_zero_change(self):
        assert compute_yuan_impact(10000.0, 0.0) == 0.0


# ══════════════════════════════════════════════════════════════════════════════
# generate_alert_message
# ══════════════════════════════════════════════════════════════════════════════

class TestGenerateAlertMessage:
    def test_fcr_spike_contains_dish_name(self):
        msg = generate_alert_message('fcr_spike', '红烧肉', 45.0, 35.0, 10.0, 500.0)
        assert '红烧肉' in msg

    def test_margin_drop_contains_dish_name(self):
        msg = generate_alert_message('margin_drop', '炒青菜', 40.0, 65.0, 25.0, 1000.0)
        assert '炒青菜' in msg

    def test_bcg_downgrade_message(self):
        msg = generate_alert_message('bcg_downgrade', '测试菜', 1.0, 4.0, 3.0, 200.0)
        assert '测试菜' in msg

    def test_max_150_chars(self):
        for at in ALERT_TYPES:
            msg = generate_alert_message(at, '超级非常特别长的菜品名' * 5,
                                         45.0, 35.0, 10.0, 500.0)
            assert len(msg) <= 150

    def test_unknown_type_fallback(self):
        msg = generate_alert_message('unknown', '测试菜', 1.0, 2.0, 1.0, 100.0)
        assert isinstance(msg, str)


# ══════════════════════════════════════════════════════════════════════════════
# build_dish_alerts
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildDishAlerts:
    BASE_CURRENT = {
        'dish_id': 'D001', 'dish_name': '红烧肉', 'category': '热菜',
        'bcg_quadrant': 'star',
        'food_cost_rate': 35.0, 'gross_profit_margin': 65.0,
        'revenue_yuan': 7500.0, 'gross_profit_yuan': 4875.0,
        'order_count': 150,
    }
    BASE_PREV = {
        'dish_id': 'D001', 'dish_name': '红烧肉', 'category': '热菜',
        'bcg_quadrant': 'star',
        'food_cost_rate': 33.0, 'gross_profit_margin': 67.0,
        'revenue_yuan': 7200.0, 'gross_profit_yuan': 4824.0,
        'order_count': 140,
    }

    def test_no_prev_returns_empty(self):
        alerts = build_dish_alerts('S001', '2024-07', self.BASE_CURRENT, None)
        assert alerts == []

    def test_no_change_no_alerts(self):
        # identical current and prev → no thresholds crossed
        alerts = build_dish_alerts('S001', '2024-07', self.BASE_CURRENT, self.BASE_CURRENT)
        assert alerts == []

    def test_fcr_spike_detected(self):
        prev = {**self.BASE_PREV, 'food_cost_rate': 35.0}
        curr = {**self.BASE_CURRENT, 'food_cost_rate': 46.0}  # +11pp → critical
        alerts = build_dish_alerts('S001', '2024-07', curr, prev)
        types = [a['alert_type'] for a in alerts]
        assert 'fcr_spike' in types

    def test_fcr_spike_severity_critical(self):
        prev = {**self.BASE_PREV, 'food_cost_rate': 30.0}
        curr = {**self.BASE_CURRENT, 'food_cost_rate': 42.0}  # +12pp ≥ 10 → critical
        alerts = build_dish_alerts('S001', '2024-07', curr, prev)
        fcr = next(a for a in alerts if a['alert_type'] == 'fcr_spike')
        assert fcr['severity'] == 'critical'

    def test_fcr_below_threshold_no_alert(self):
        prev = {**self.BASE_PREV, 'food_cost_rate': 35.0}
        curr = {**self.BASE_CURRENT, 'food_cost_rate': 37.5}  # +2.5pp < 3 → no alert
        alerts = build_dish_alerts('S001', '2024-07', curr, prev)
        types = [a['alert_type'] for a in alerts]
        assert 'fcr_spike' not in types

    def test_margin_drop_detected(self):
        prev = {**self.BASE_PREV, 'gross_profit_margin': 65.0}
        curr = {**self.BASE_CURRENT, 'gross_profit_margin': 45.0}  # -20pp → critical
        alerts = build_dish_alerts('S001', '2024-07', curr, prev)
        types = [a['alert_type'] for a in alerts]
        assert 'margin_drop' in types

    def test_margin_drop_severity_critical(self):
        prev = {**self.BASE_PREV, 'gross_profit_margin': 65.0}
        curr = {**self.BASE_CURRENT, 'gross_profit_margin': 45.0}  # 20pp ≥ 15 → critical
        alerts = build_dish_alerts('S001', '2024-07', curr, prev)
        md = next(a for a in alerts if a['alert_type'] == 'margin_drop')
        assert md['severity'] == 'critical'

    def test_margin_drop_below_threshold(self):
        prev = {**self.BASE_PREV, 'gross_profit_margin': 65.0}
        curr = {**self.BASE_CURRENT, 'gross_profit_margin': 62.0}  # -3pp < 5 → no alert
        alerts = build_dish_alerts('S001', '2024-07', curr, prev)
        types = [a['alert_type'] for a in alerts]
        assert 'margin_drop' not in types

    def test_bcg_downgrade_detected(self):
        prev = {**self.BASE_PREV, 'bcg_quadrant': 'star'}
        curr = {**self.BASE_CURRENT, 'bcg_quadrant': 'dog'}
        alerts = build_dish_alerts('S001', '2024-07', curr, prev)
        types = [a['alert_type'] for a in alerts]
        assert 'bcg_downgrade' in types

    def test_bcg_downgrade_star_to_dog_critical(self):
        prev = {**self.BASE_PREV, 'bcg_quadrant': 'star'}
        curr = {**self.BASE_CURRENT, 'bcg_quadrant': 'dog'}  # rank 4→1, drop=3 → critical
        alerts = build_dish_alerts('S001', '2024-07', curr, prev)
        bcg = next(a for a in alerts if a['alert_type'] == 'bcg_downgrade')
        assert bcg['severity'] == 'critical'

    def test_bcg_upgrade_no_alert(self):
        prev = {**self.BASE_PREV, 'bcg_quadrant': 'dog'}
        curr = {**self.BASE_CURRENT, 'bcg_quadrant': 'star'}
        alerts = build_dish_alerts('S001', '2024-07', curr, prev)
        types = [a['alert_type'] for a in alerts]
        assert 'bcg_downgrade' not in types

    def test_multiple_alerts_same_dish(self):
        # FCR up AND margin down AND BCG downgrade all at once
        prev = {**self.BASE_PREV,
                'food_cost_rate': 30.0, 'gross_profit_margin': 70.0, 'bcg_quadrant': 'star'}
        curr = {**self.BASE_CURRENT,
                'food_cost_rate': 55.0, 'gross_profit_margin': 40.0, 'bcg_quadrant': 'dog'}
        alerts = build_dish_alerts('S001', '2024-07', curr, prev)
        types = {a['alert_type'] for a in alerts}
        assert types == {'fcr_spike', 'margin_drop', 'bcg_downgrade'}

    def test_alert_has_required_fields(self):
        prev = {**self.BASE_PREV, 'food_cost_rate': 30.0}
        curr = {**self.BASE_CURRENT, 'food_cost_rate': 45.0}
        alerts = build_dish_alerts('S001', '2024-07', curr, prev)
        assert len(alerts) > 0
        required = ['dish_id', 'dish_name', 'alert_type', 'severity',
                    'current_value', 'prev_value', 'change_pp',
                    'yuan_impact_yuan', 'message']
        for f in required:
            assert f in alerts[0], f"Missing: {f}"

    def test_yuan_impact_nonzero(self):
        prev = {**self.BASE_PREV, 'food_cost_rate': 30.0}
        curr = {**self.BASE_CURRENT, 'food_cost_rate': 45.0}  # +15pp on ¥7500 = ¥1125
        alerts = build_dish_alerts('S001', '2024-07', curr, prev)
        fcr = next(a for a in alerts if a['alert_type'] == 'fcr_spike')
        assert fcr['yuan_impact_yuan'] > 0


# ══════════════════════════════════════════════════════════════════════════════
# summarize_alerts
# ══════════════════════════════════════════════════════════════════════════════

class TestSummarizeAlerts:
    ALERTS = [
        {'alert_type': 'fcr_spike',     'severity': 'critical', 'yuan_impact_yuan': 500.0},
        {'alert_type': 'margin_drop',   'severity': 'warning',  'yuan_impact_yuan': 800.0},
        {'alert_type': 'margin_drop',   'severity': 'info',     'yuan_impact_yuan': 200.0},
        {'alert_type': 'bcg_downgrade', 'severity': 'warning',  'yuan_impact_yuan': 300.0},
    ]

    def test_total_count(self):
        s = summarize_alerts(self.ALERTS)
        assert s['total_count'] == 4

    def test_by_severity(self):
        s = summarize_alerts(self.ALERTS)
        assert s['by_severity']['critical'] == 1
        assert s['by_severity']['warning']  == 2
        assert s['by_severity']['info']     == 1

    def test_by_type(self):
        s = summarize_alerts(self.ALERTS)
        assert s['by_type']['fcr_spike']     == 1
        assert s['by_type']['margin_drop']   == 2
        assert s['by_type']['bcg_downgrade'] == 1

    def test_total_yuan_impact(self):
        s = summarize_alerts(self.ALERTS)
        assert abs(s['total_yuan_impact'] - 1800.0) < 0.1

    def test_empty(self):
        s = summarize_alerts([])
        assert s['total_count'] == 0
        assert s['total_yuan_impact'] == 0.0


# ══════════════════════════════════════════════════════════════════════════════
# _prev_period / _start_period
# ══════════════════════════════════════════════════════════════════════════════

class TestPeriodHelpers:
    def test_prev_normal(self):
        assert _prev_period('2024-07') == '2024-06'

    def test_prev_jan_wraps(self):
        assert _prev_period('2024-01') == '2023-12'

    def test_start_period_6(self):
        # 2024-07 minus 5 months = 2024-02
        assert _start_period('2024-07', 6) == '2024-02'

    def test_start_period_wraps_year(self):
        # 2024-03 minus 5 = 2023-10
        assert _start_period('2024-03', 6) == '2023-10'

    def test_start_period_1(self):
        assert _start_period('2024-07', 1) == '2024-07'


# ══════════════════════════════════════════════════════════════════════════════
# DB 层
# ══════════════════════════════════════════════════════════════════════════════

def _make_db(calls: list):
    call_idx = [0]

    async def mock_execute(stmt, params=None):
        idx = call_idx[0]
        call_idx[0] += 1
        val = calls[idx] if idx < len(calls) else []
        r = MagicMock()
        if val is None or val == []:
            r.fetchone.return_value = None
            r.fetchall.return_value = []
        elif isinstance(val, list):
            r.fetchall.return_value = val
            r.fetchone.return_value = val[0] if val else None
        else:
            r.fetchone.return_value = val
            r.fetchall.return_value = [val]
        return r

    db = MagicMock()
    db.execute = mock_execute
    db.commit   = AsyncMock()
    return db


# dish_profitability_records 行 (13 cols)
def _profit_row(dish_id, dish_name, category, bcg,
                cnt, price, rev, fcost, fcr, gprofit, gpm):
    return (dish_id, dish_name, category, bcg, cnt, price, rev, fcost, fcr, gprofit, gpm)


class TestGenerateDishCostAlerts:
    @pytest.mark.asyncio
    async def test_no_current_data(self):
        # 2 fetches (current + prev), both empty
        db = _make_db([[], []])
        result = await generate_dish_cost_alerts(db, 'S001', '2024-07')
        assert result['alert_count'] == 0
        assert result['dish_count']  == 0

    @pytest.mark.asyncio
    async def test_no_prev_data_no_alerts(self):
        curr = [_profit_row('D001','红烧肉','热菜','star',150,50.0,7500.0,2625.0,35.0,4875.0,65.0)]
        # current has data, prev is empty → no comparison possible
        db = _make_db([curr, []])
        result = await generate_dish_cost_alerts(db, 'S001', '2024-07')
        assert result['dish_count']  == 1
        assert result['alert_count'] == 0

    @pytest.mark.asyncio
    async def test_fcr_spike_alert_generated(self):
        curr = [_profit_row('D001','红烧肉','热菜','star',150,50.0,7500.0,2625.0,45.0,4875.0,55.0)]
        prev = [_profit_row('D001','红烧肉','热菜','star',140,50.0,7000.0,2450.0,35.0,4550.0,65.0)]
        # curr fcr=45, prev fcr=35 → +10pp → fcr_spike (warning)
        # curr gpm=55, prev gpm=65 → -10pp → margin_drop (warning)
        # BCG same → no bcg_downgrade
        # calls: fetch_current + fetch_prev + 2 upserts
        db = _make_db([curr, prev, None, None])
        result = await generate_dish_cost_alerts(db, 'S001', '2024-07')
        assert result['alert_count'] == 2

    @pytest.mark.asyncio
    async def test_bcg_downgrade_alert_generated(self):
        curr = [_profit_row('D001','红烧肉','热菜','dog',50,50.0,2500.0,1500.0,60.0,1000.0,40.0)]
        prev = [_profit_row('D001','红烧肉','热菜','star',150,50.0,7500.0,2625.0,35.0,4875.0,65.0)]
        # BCG: star → dog (drop 3 → critical)
        # fcr: 60-35=25pp spike → critical
        # gpm: 65-40=25pp drop → critical
        # 3 alerts total
        db = _make_db([curr, prev, None, None, None])
        result = await generate_dish_cost_alerts(db, 'S001', '2024-07')
        assert result['alert_count'] == 3

    @pytest.mark.asyncio
    async def test_commit_called(self):
        curr = [_profit_row('D001','红烧肉','热菜','star',150,50.0,7500.0,2625.0,45.0,4875.0,55.0)]
        prev = [_profit_row('D001','红烧肉','热菜','star',140,50.0,7000.0,2450.0,35.0,4550.0,65.0)]
        db = _make_db([curr, prev, None, None])
        await generate_dish_cost_alerts(db, 'S001', '2024-07')
        assert db.commit.call_count == 1


class TestGetDishCostAlerts:
    # 17 cols
    ROW = (1, 'S001', '2024-07', 'D001', '红烧肉', '热菜',
           'star', 'cash_cow', 'fcr_spike', 'warning',
           45.0, 35.0, 10.0, 750.0,
           '红烧肉食材成本率上涨', 'open', None)

    @pytest.mark.asyncio
    async def test_returns_list(self):
        db = _make_db([[self.ROW]])
        alerts = await get_dish_cost_alerts(db, 'S001', '2024-07')
        assert len(alerts) == 1
        assert alerts[0]['alert_type']  == 'fcr_spike'
        assert alerts[0]['alert_label'] == '成本率飙升'

    @pytest.mark.asyncio
    async def test_empty(self):
        db = _make_db([[]])
        alerts = await get_dish_cost_alerts(db, 'S001', '2024-07')
        assert alerts == []

    @pytest.mark.asyncio
    async def test_with_severity_filter(self):
        db = _make_db([[self.ROW]])
        alerts = await get_dish_cost_alerts(db, 'S001', '2024-07', severity='warning')
        assert len(alerts) == 1

    @pytest.mark.asyncio
    async def test_with_status_filter(self):
        db = _make_db([[self.ROW]])
        alerts = await get_dish_cost_alerts(db, 'S001', '2024-07', status='open')
        assert len(alerts) == 1

    @pytest.mark.asyncio
    async def test_with_both_filters(self):
        db = _make_db([[self.ROW]])
        alerts = await get_dish_cost_alerts(db, 'S001', '2024-07',
                                            severity='warning', status='open')
        assert len(alerts) == 1


class TestGetAlertSummary:
    @pytest.mark.asyncio
    async def test_aggregates(self):
        rows = [
            ('fcr_spike',     'critical', 'open',     3, 1500.0),
            ('margin_drop',   'warning',  'open',     2,  800.0),
            ('bcg_downgrade', 'warning',  'resolved', 1,  200.0),
        ]
        db = _make_db([rows])
        s = await get_alert_summary(db, 'S001', '2024-07')
        assert s['open_count']     == 5  # 3+2
        assert s['resolved_count'] == 1
        assert s['critical_count'] == 3
        assert abs(s['total_open_yuan_impact'] - 2300.0) < 0.1

    @pytest.mark.asyncio
    async def test_all_types_present(self):
        db = _make_db([[]])
        s = await get_alert_summary(db, 'S001', '2024-07')
        types = {item['alert_type'] for item in s['by_type']}
        assert types == set(ALERT_TYPES)


class TestResolveAlert:
    @pytest.mark.asyncio
    async def test_success(self):
        db = _make_db([(1,)])
        result = await resolve_alert(db, 1)
        assert result['updated']   is True
        assert result['alert_id']  == 1

    @pytest.mark.asyncio
    async def test_not_found(self):
        db = _make_db([None])
        result = await resolve_alert(db, 999)
        assert result['updated'] is False

    @pytest.mark.asyncio
    async def test_commit_on_success(self):
        db = _make_db([(1,)])
        await resolve_alert(db, 1)
        assert db.commit.call_count == 1

    @pytest.mark.asyncio
    async def test_no_commit_on_failure(self):
        db = _make_db([None])
        await resolve_alert(db, 999)
        assert db.commit.call_count == 0


class TestGetStoreCostTrend:
    @pytest.mark.asyncio
    async def test_returns_trend(self):
        rows = [
            ('2024-02', 8, 36.5, 63.5, 50000.0, 31750.0, 600),
            ('2024-03', 9, 37.0, 63.0, 52000.0, 32760.0, 620),
            ('2024-07', 10, 38.0, 62.0, 55000.0, 34100.0, 650),
        ]
        db = _make_db([rows])
        trend = await get_store_cost_trend(db, 'S001', '2024-07', periods=6)
        assert len(trend) == 3
        assert trend[0]['period']  == '2024-02'
        assert trend[-1]['period'] == '2024-07'
        assert abs(trend[-1]['avg_fcr'] - 38.0) < 0.1

    @pytest.mark.asyncio
    async def test_empty(self):
        db = _make_db([[]])
        trend = await get_store_cost_trend(db, 'S001', '2024-07')
        assert trend == []


class TestGetDishAlertHistory:
    @pytest.mark.asyncio
    async def test_returns_history(self):
        rows = [
            ('2024-07', 'fcr_spike', 'warning', 45.0, 35.0, 10.0, 750.0,
             '成本率上涨', 'open'),
            ('2024-06', 'fcr_spike', 'info',    38.0, 35.0,  3.0, 210.0,
             '成本率轻微上涨', 'resolved'),
        ]
        db = _make_db([rows])
        history = await get_dish_alert_history(db, 'S001', 'D001')
        assert len(history)            == 2
        assert history[0]['period']    == '2024-07'
        assert history[0]['alert_label'] == '成本率飙升'

    @pytest.mark.asyncio
    async def test_empty(self):
        db = _make_db([[]])
        history = await get_dish_alert_history(db, 'S001', 'D999')
        assert history == []
