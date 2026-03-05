"""
NarrativeEngine 单元测试

覆盖：
  - 纯函数：_build_overview / _detect_anomalies / _build_action / compose_brief
  - 集成：NarrativeEngine.generate_store_brief（mock DB）
"""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.narrative_engine import (
    BRIEF_MAX_CHARS,
    NarrativeEngine,
    _build_action,
    _build_overview,
    _detect_anomalies,
    _sum_saving,
    compose_brief,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _metrics(status="ok", cost_pct=29.5, revenue=12400.0):
    label_map = {"ok": "正常", "warning": "偏高", "critical": "超标"}
    return {
        "revenue_yuan":     revenue,
        "actual_cost_pct":  cost_pct,
        "cost_rate_status": status,
        "cost_rate_label":  label_map[status],
    }


def _summary(total=3, approved=2):
    return {"total": total, "approved": approved}


def _waste_top5(item="羊肉", yuan=480.0):
    return [{"item_name": item, "waste_cost_yuan": yuan, "action": "建议核查采购"}]


def _decisions(action="建议明日减少羊肉备料20%", saving=800.0):
    return [{"action": action, "expected_saving_yuan": saving, "net_benefit_yuan": saving}]


# ═══════════════════════════════════════════════════════════════════════════════
# 纯函数测试
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildOverview:
    def test_contains_store_label(self):
        result = _build_overview("芙蓉区店", _metrics(), _summary())
        assert "芙蓉区店" in result

    def test_contains_revenue(self):
        result = _build_overview("S001", _metrics(revenue=12400.0), _summary())
        assert "12,400" in result

    def test_contains_cost_pct(self):
        result = _build_overview("S001", _metrics(cost_pct=31.2), _summary())
        assert "31.2%" in result

    def test_contains_status_label(self):
        result = _build_overview("S001", _metrics(status="warning"), _summary())
        assert "偏高" in result

    def test_contains_decision_ratio_when_decisions_exist(self):
        result = _build_overview("S001", _metrics(), _summary(total=3, approved=2))
        assert "2/3" in result

    def test_no_decision_ratio_when_zero_decisions(self):
        result = _build_overview("S001", _metrics(), _summary(total=0, approved=0))
        assert "/" not in result


class TestDetectAnomalies:
    def test_critical_cost_is_priority_0(self):
        anomalies = _detect_anomalies(_metrics("critical", 41.0), None, 0, [])
        assert len(anomalies) >= 1
        assert "🔴" in anomalies[0]
        assert "超标" in anomalies[0]

    def test_warning_cost_detected(self):
        anomalies = _detect_anomalies(_metrics("warning", 33.5), None, 0, [])
        assert any("⚠️" in a and "偏高" in a for a in anomalies)

    def test_ok_cost_no_cost_anomaly(self):
        anomalies = _detect_anomalies(_metrics("ok"), None, 0, [])
        assert not any("成本" in a for a in anomalies)

    def test_waste_item_detected(self):
        anomalies = _detect_anomalies(_metrics("ok"), _waste_top5("猪肉", 600.0), 0, [])
        assert any("猪肉" in a for a in anomalies)

    def test_pending_approvals_detected(self):
        anomalies = _detect_anomalies(_metrics("ok"), None, 3, _decisions())
        assert any("待审批" in a for a in anomalies)

    def test_max_3_anomalies_returned(self):
        # critical cost + waste + pending → 3条
        anomalies = _detect_anomalies(
            _metrics("critical", 42.0),
            _waste_top5("羊肉", 900.0),
            5,
            _decisions(),
        )
        assert len(anomalies) <= 3

    def test_empty_when_all_ok(self):
        anomalies = _detect_anomalies(_metrics("ok"), [], 0, [])
        assert anomalies == []

    def test_critical_cost_sorted_before_waste(self):
        anomalies = _detect_anomalies(
            _metrics("critical", 41.0),
            _waste_top5("羊肉", 500.0),
            0, [],
        )
        # critical 成本应排在第一
        assert "🔴" in anomalies[0]


class TestBuildAction:
    def test_uses_top_decision_action(self):
        result = _build_action(_decisions("建议明日减少备料20%"), _metrics())
        assert "建议明日减少备料20%" in result

    def test_fallback_critical(self):
        result = _build_action([], _metrics("critical"))
        assert "超标食材" in result

    def test_fallback_warning(self):
        result = _build_action([], _metrics("warning"))
        assert "成本率" in result

    def test_fallback_ok(self):
        result = _build_action([], _metrics("ok"))
        assert "✅" in result

    def test_always_starts_with_checkmark(self):
        result = _build_action([], _metrics())
        assert result.startswith("✅")


class TestComposeBrief:
    def test_within_char_limit(self):
        brief = compose_brief(
            store_label="芙蓉区店",
            cost_metrics=_metrics("critical", 41.0),
            decision_summary=_summary(),
            waste_top5=_waste_top5(),
            pending_count=2,
            top_decisions=_decisions(),
        )
        assert len(brief) <= BRIEF_MAX_CHARS

    def test_contains_overview_line(self):
        brief = compose_brief(
            store_label="测试店",
            cost_metrics=_metrics(revenue=8000.0),
            decision_summary=_summary(),
            waste_top5=None,
            pending_count=0,
            top_decisions=[],
        )
        assert "测试店" in brief
        assert "8,000" in brief

    def test_no_anomaly_section_when_all_ok(self):
        brief = compose_brief(
            store_label="S001",
            cost_metrics=_metrics("ok"),
            decision_summary=_summary(total=0, approved=0),
            waste_top5=[],
            pending_count=0,
            top_decisions=[],
        )
        assert "🔴" not in brief
        assert "⚠️" not in brief
        assert "⏳" not in brief

    def test_truncated_with_ellipsis_when_too_long(self):
        # 构造极长的 store_label 和 action，强制超出限制
        long_label = "这是一个非常非常非常非常长的门店名称" * 5
        brief = compose_brief(
            store_label=long_label,
            cost_metrics=_metrics("critical", 45.0),
            decision_summary=_summary(),
            waste_top5=_waste_top5(),
            pending_count=10,
            top_decisions=_decisions("建议紧急处理所有超标食材问题并立即联系采购部门" * 3),
        )
        assert len(brief) <= BRIEF_MAX_CHARS
        assert brief.endswith("…")


class TestSumSaving:
    def test_sums_expected_saving(self):
        decs = [{"expected_saving_yuan": 300.0}, {"expected_saving_yuan": 500.0}]
        assert _sum_saving(decs) == 800.0

    def test_falls_back_to_net_benefit(self):
        decs = [{"net_benefit_yuan": 400.0}]
        assert _sum_saving(decs) == 400.0

    def test_empty_list_returns_zero(self):
        assert _sum_saving([]) == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# 集成测试（mock DB）
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_generate_store_brief_returns_string():
    """NarrativeEngine.generate_store_brief 返回非空字符串"""
    db = AsyncMock()

    mock_story = {
        "cost_metrics": _metrics("warning", 33.5, revenue=15000.0),
        "decision_summary": _summary(total=2, approved=1),
    }
    mock_waste = {"top5": _waste_top5("羊肉", 420.0)}

    with patch(
        "src.services.narrative_engine.CaseStoryGenerator.generate_daily_story",
        new_callable=AsyncMock,
        return_value=mock_story,
    ), patch(
        "src.services.narrative_engine.WasteGuardService.get_top5_waste",
        new_callable=AsyncMock,
        return_value=mock_waste,
    ):
        brief = await NarrativeEngine.generate_store_brief(
            store_id="S001",
            target_date=date(2026, 3, 5),
            db=db,
            store_label="芙蓉区店",
            top_decisions=_decisions(),
            pending_count=1,
        )

    assert isinstance(brief, str)
    assert len(brief) > 0
    assert len(brief) <= BRIEF_MAX_CHARS
    assert "芙蓉区店" in brief


@pytest.mark.asyncio
async def test_generate_store_brief_degrades_on_story_failure():
    """CaseStoryGenerator 失败时仍返回有效简报（降级兜底）"""
    db = AsyncMock()

    with patch(
        "src.services.narrative_engine.CaseStoryGenerator.generate_daily_story",
        new_callable=AsyncMock,
        side_effect=RuntimeError("DB 超时"),
    ), patch(
        "src.services.narrative_engine.WasteGuardService.get_top5_waste",
        new_callable=AsyncMock,
        return_value={"top5": []},
    ):
        brief = await NarrativeEngine.generate_store_brief(
            store_id="S001",
            target_date=date(2026, 3, 5),
            db=db,
        )

    assert isinstance(brief, str)
    assert len(brief) <= BRIEF_MAX_CHARS


@pytest.mark.asyncio
async def test_generate_store_brief_degrades_on_waste_failure():
    """WasteGuardService 失败时仍返回有效简报（损耗部分降级为空）"""
    db = AsyncMock()

    mock_story = {
        "cost_metrics": _metrics(),
        "decision_summary": _summary(),
    }

    with patch(
        "src.services.narrative_engine.CaseStoryGenerator.generate_daily_story",
        new_callable=AsyncMock,
        return_value=mock_story,
    ), patch(
        "src.services.narrative_engine.WasteGuardService.get_top5_waste",
        new_callable=AsyncMock,
        side_effect=RuntimeError("损耗查询失败"),
    ):
        brief = await NarrativeEngine.generate_store_brief(
            store_id="S001",
            target_date=date(2026, 3, 5),
            db=db,
        )

    assert isinstance(brief, str)
    assert len(brief) <= BRIEF_MAX_CHARS
    # 损耗部分降级，但概况和建议仍存在
    assert "✅" in brief
