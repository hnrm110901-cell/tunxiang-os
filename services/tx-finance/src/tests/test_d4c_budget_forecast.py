"""Sprint D4c — 预算预测 TDD 测试

覆盖：
  · BudgetSignalBundle 合法性校验 + 序列化
  · CachedPromptBuilder 结构（2 段 cacheable system + user）
  · PNL_BENCHMARKS 内容完整性（5 业态）
  · parse_sonnet_response 容错（valid / code-fence / broken）
  · fallback 规则引擎 4 类风险（负利润 / 人工红线 / 食材红线 / 毛利压缩 / 成本突增）
  · 风险排序 legal_flag > severity > |delta_fen|
  · has_critical / has_legal_flag
  · invoker 成功 + 失败降级
  · cache_hit_rate 计算
  · predicted_line_items 不全时用 fallback 补齐
  · v281 迁移静态断言
  · ModelRouter 注册

执行：
  pytest services/tx-finance/src/tests/test_d4c_budget_forecast.py -v
"""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

ROOT = Path(__file__).resolve().parents[4]

from services.budget_forecast_service import (  # noqa: E402
    BudgetForecastResult,
    BudgetForecastService,
    BudgetSignalBundle,
    CachedPromptBuilder,
    MonthlyPnL,
    PredictedLineItem,
    VarianceRisk,
    fallback_forecast,
    parse_sonnet_response,
)

TENANT = "00000000-0000-0000-0000-000000000001"


def _monthly(
    month: date,
    rev: int,
    food: int,
    labor: int,
    rent: int = 10_0000 * 100,
    utility: int = 3_0000 * 100,
    other: int = 5_0000 * 100,
) -> MonthlyPnL:
    return MonthlyPnL(
        month=month,
        revenue_fen=rev,
        food_cost_fen=food,
        labor_cost_fen=labor,
        rent_fen=rent,
        utility_fen=utility,
        other_fen=other,
    )


def _healthy_history(n_months: int = 12) -> list[MonthlyPnL]:
    """12 月健康 P&L：正餐，月营收 100 万，食材 38%，人工 25%，净利 17%"""
    out = []
    for i in range(n_months):
        m = date(2026, 1, 1)
        m = m.replace(month=((i % 12) + 1))
        out.append(
            _monthly(
                month=m,
                rev=100_0000 * 100,  # 100万
                food=38_0000 * 100,  # 38万
                labor=25_0000 * 100,  # 25万
            )
        )
    return out


def _bundle(history=None, **overrides) -> BudgetSignalBundle:
    return BudgetSignalBundle(
        tenant_id=TENANT,
        forecast_month=overrides.pop("forecast_month", date(2026, 5, 1)),
        forecast_scope=overrides.pop("forecast_scope", "monthly_store"),
        business_type=overrides.pop("business_type", "full_service"),
        store_id=overrides.pop("store_id", "00000000-0000-0000-0000-000000000099"),
        store_name=overrides.pop("store_name", "徐记长沙旗舰店"),
        history=history if history is not None else _healthy_history(),
        **overrides,
    )


# ────────────────────────────────────────────────
# 1. BudgetSignalBundle 合法性
# ────────────────────────────────────────────────


class TestBundleValidation:
    def test_bundle_happy_path(self):
        b = _bundle()
        assert b.business_type == "full_service"
        assert len(b.history) == 12

    def test_bundle_rejects_bad_scope(self):
        with pytest.raises(ValueError, match="forecast_scope"):
            _bundle(forecast_scope="yearly")

    def test_bundle_rejects_bad_business_type(self):
        with pytest.raises(ValueError, match="business_type"):
            _bundle(business_type="bakery")

    def test_bundle_rejects_empty_history(self):
        with pytest.raises(ValueError, match="history"):
            _bundle(history=[])

    def test_bundle_to_dict_serializable(self):
        b = _bundle()
        d = b.to_dict()
        assert d["business_type"] == "full_service"
        assert len(d["history"]) == 12
        assert d["history"][0]["revenue_fen"] == 100_0000 * 100
        assert "margin_pct" in d["history"][0]


# ────────────────────────────────────────────────
# 2. CachedPromptBuilder
# ────────────────────────────────────────────────


class TestCachedPromptBuilder:
    def test_system_has_two_cache_blocks(self):
        msg = CachedPromptBuilder.build_messages(_bundle())
        assert msg["model"] == "claude-sonnet-4-7"
        assert len(msg["system"]) == 2
        assert all(
            b.get("cache_control", {}).get("type") == "ephemeral"
            for b in msg["system"]
        )

    def test_stable_system_declares_schema(self):
        sys_txt = CachedPromptBuilder.STABLE_SYSTEM
        # 7 个 line_item 必须在 schema 中声明
        for li in (
            "revenue",
            "food_cost",
            "labor_cost",
            "rent",
            "utility",
            "other",
            "net",
        ):
            assert li in sys_txt
        # 4 类 risk_type
        for rt in (
            "cost_overrun",
            "revenue_drop",
            "margin_compression",
            "compliance_breach",
        ):
            assert rt in sys_txt

    def test_pnl_benchmarks_covers_5_business_types(self):
        bench = CachedPromptBuilder.PNL_BENCHMARKS
        for bt in ("full_service", "quick_service", "tea_beverage", "buffet", "hot_pot"):
            assert bt in bench
        # 法规红线
        assert "30%" in bench and "45%" in bench

    def test_user_message_contains_history_and_window(self):
        msg = CachedPromptBuilder.build_messages(_bundle())
        user_content = msg["messages"][0]["content"]
        assert "forecast_month" in user_content
        assert "forecast_scope" in user_content
        assert "history" in user_content
        assert "2026-05-01" in user_content


# ────────────────────────────────────────────────
# 3. parse_sonnet_response
# ────────────────────────────────────────────────


class TestParseSonnetResponse:
    def test_parse_valid_json(self):
        out = parse_sonnet_response('{"predicted_line_items": [], "analysis": "ok"}')
        assert out == {"predicted_line_items": [], "analysis": "ok"}

    def test_parse_code_fence(self):
        raw = '```json\n{"analysis": "ok"}\n```'
        assert parse_sonnet_response(raw) == {"analysis": "ok"}

    def test_parse_broken_returns_empty(self):
        assert parse_sonnet_response("this is not json") == {}
        assert parse_sonnet_response("") == {}


# ────────────────────────────────────────────────
# 4. Fallback 规则引擎
# ────────────────────────────────────────────────


class TestFallbackRules:
    def test_healthy_history_minimal_risks(self):
        result = fallback_forecast(_bundle())
        # 7 项预测必须全齐
        predicted = {li.line_item for li in result.predicted_line_items}
        assert predicted == {
            "revenue",
            "food_cost",
            "labor_cost",
            "rent",
            "utility",
            "other",
            "net",
        }
        # 净利为正 + 无红线
        net_item = next(li for li in result.predicted_line_items if li.line_item == "net")
        assert net_item.predicted_fen > 0
        assert not result.has_critical
        assert not result.has_legal_flag

    def test_labor_cost_redline_triggers_legal_flag(self):
        # 人工占营收 35% > 30% 红线
        history = [
            _monthly(
                date(2026, 1, 1),
                rev=100_0000 * 100,
                food=38_0000 * 100,
                labor=35_0000 * 100,  # 35%
            )
            for _ in range(12)
        ]
        result = fallback_forecast(_bundle(history=history))
        labor_risks = [r for r in result.variance_risks if r.line_item == "labor_cost"]
        assert labor_risks, "人工红线未触发"
        assert labor_risks[0].risk_type == "compliance_breach"
        assert labor_risks[0].legal_flag is True
        assert result.has_legal_flag

    def test_food_cost_redline_triggers_legal_flag(self):
        # 食材占营收 52% > 50% → critical
        history = [
            _monthly(
                date(2026, 1, 1),
                rev=100_0000 * 100,
                food=52_0000 * 100,  # 52%
                labor=25_0000 * 100,
            )
            for _ in range(12)
        ]
        result = fallback_forecast(_bundle(history=history))
        food_risks = [r for r in result.variance_risks if r.line_item == "food_cost"]
        assert food_risks, "食材红线未触发"
        assert food_risks[0].legal_flag is True
        assert food_risks[0].severity == "critical"  # >50% → critical

    def test_negative_margin_critical(self):
        # 成本超过营收 → 净利为负
        history = [
            _monthly(
                date(2026, 1, 1),
                rev=100_0000 * 100,
                food=60_0000 * 100,
                labor=40_0000 * 100,
                rent=15_0000 * 100,
                utility=5_0000 * 100,
                other=10_0000 * 100,
            )
            for _ in range(12)
        ]
        result = fallback_forecast(_bundle(history=history))
        net_risks = [r for r in result.variance_risks if r.line_item == "net"]
        assert net_risks, "负利润未触发 critical"
        assert net_risks[0].severity == "critical"
        assert net_risks[0].risk_type == "margin_compression"
        assert result.has_critical

    def test_cost_overrun_triggers_medium(self):
        # 食材成本四阶梯上升：30 → 35 → 40 → 50，近 3 月 vs 前 3 月涨幅 25%
        food_pattern = [30, 30, 30, 35, 35, 35, 40, 40, 40, 50, 50, 50]
        history = [
            _monthly(
                date(2026, (i % 12) + 1, 1),
                rev=100_0000 * 100,
                food=food_pattern[i] * 10000 * 100,
                labor=25_0000 * 100,
            )
            for i in range(12)
        ]
        result = fallback_forecast(_bundle(history=history))
        overrun = [
            r
            for r in result.variance_risks
            if r.line_item == "food_cost" and r.risk_type == "cost_overrun"
        ]
        assert overrun, "成本突增未触发"

    def test_rule_engine_model_id_marker(self):
        result = fallback_forecast(_bundle())
        assert result.model_id == "rule_engine_fallback"
        assert "规则引擎" in result.sonnet_analysis


# ────────────────────────────────────────────────
# 5. 风险排序
# ────────────────────────────────────────────────


class TestRiskSorting:
    def test_legal_flag_first_then_severity_then_delta(self):
        # 人工 38% (legal_flag + critical) + 食材 48% (legal_flag + high)
        history = [
            _monthly(
                date(2026, 1, 1),
                rev=100_0000 * 100,
                food=48_0000 * 100,
                labor=38_0000 * 100,
            )
            for _ in range(12)
        ]
        result = fallback_forecast(_bundle(history=history))
        # 第一条必须是 legal_flag=True + critical
        assert result.variance_risks
        first = result.variance_risks[0]
        assert first.legal_flag is True
        # 所有 legal_flag=True 在 legal_flag=False 前
        legal_positions = [i for i, r in enumerate(result.variance_risks) if r.legal_flag]
        non_legal_positions = [
            i for i, r in enumerate(result.variance_risks) if not r.legal_flag
        ]
        if non_legal_positions:
            assert max(legal_positions) < min(non_legal_positions)


# ────────────────────────────────────────────────
# 6. Result 属性
# ────────────────────────────────────────────────


class TestResultProperties:
    def test_has_critical_and_legal_flag(self):
        r = BudgetForecastResult()
        r.variance_risks = [
            VarianceRisk(
                line_item="labor_cost",
                risk_type="compliance_breach",
                severity="critical",
                delta_fen=5000_00,
                evidence="超 30%",
                legal_flag=True,
            )
        ]
        assert r.has_critical is True
        assert r.has_legal_flag is True

    def test_predicted_revenue_net_margin(self):
        r = BudgetForecastResult()
        r.predicted_line_items = [
            PredictedLineItem("revenue", 100_0000 * 100, 1.0, 0, 0),
            PredictedLineItem("net", 17_0000 * 100, 0.17, 0, 0),
        ]
        assert r.predicted_revenue_fen == 100_0000 * 100
        assert r.predicted_net_fen == 17_0000 * 100
        assert r.predicted_margin_pct == 0.17


# ────────────────────────────────────────────────
# 7. Cache 命中率
# ────────────────────────────────────────────────


class TestCacheHitRate:
    def test_hit_rate_zero_when_no_tokens(self):
        r = BudgetForecastResult()
        assert r.cache_hit_rate == 0.0

    def test_hit_rate_typical(self):
        r = BudgetForecastResult(
            cache_read_tokens=3000,
            cache_creation_tokens=0,
            input_tokens=500,
        )
        # 3000 / (3000 + 0 + 500) = 0.8571
        assert abs(r.cache_hit_rate - 0.8571) < 0.001

    def test_hit_rate_first_request_creates_cache(self):
        r = BudgetForecastResult(
            cache_read_tokens=0,
            cache_creation_tokens=3500,
            input_tokens=500,
        )
        assert r.cache_hit_rate == 0.0

    def test_hit_rate_target_0_75(self):
        r = BudgetForecastResult(
            cache_read_tokens=3750,
            cache_creation_tokens=0,
            input_tokens=1250,
        )
        # 3750 / 5000 = 0.75
        assert r.cache_hit_rate == 0.75


# ────────────────────────────────────────────────
# 8. Invoker 契约
# ────────────────────────────────────────────────


class TestInvoker:
    @pytest.mark.asyncio
    async def test_invoker_success_parses_response(self):
        async def fake(req):
            return {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            '{"predicted_line_items":['
                            '{"line_item":"revenue","predicted_fen":10000000000,'
                            '"ratio_of_revenue":1.0,"confidence_low":9500000000,'
                            '"confidence_high":10500000000},'
                            '{"line_item":"food_cost","predicted_fen":3800000000,'
                            '"ratio_of_revenue":0.38,"confidence_low":3500000000,'
                            '"confidence_high":4000000000},'
                            '{"line_item":"labor_cost","predicted_fen":2500000000,'
                            '"ratio_of_revenue":0.25,"confidence_low":2400000000,'
                            '"confidence_high":2700000000},'
                            '{"line_item":"rent","predicted_fen":1000000000,'
                            '"ratio_of_revenue":0.10,"confidence_low":1000000000,'
                            '"confidence_high":1000000000},'
                            '{"line_item":"utility","predicted_fen":300000000,'
                            '"ratio_of_revenue":0.03,"confidence_low":280000000,'
                            '"confidence_high":330000000},'
                            '{"line_item":"other","predicted_fen":500000000,'
                            '"ratio_of_revenue":0.05,"confidence_low":400000000,'
                            '"confidence_high":600000000},'
                            '{"line_item":"net","predicted_fen":1900000000,'
                            '"ratio_of_revenue":0.19,"confidence_low":1500000000,'
                            '"confidence_high":2200000000}'
                            '],"variance_risks":[],"preventive_actions":[],'
                            '"analysis":"健康"}'
                        ),
                    }
                ],
                "usage": {
                    "cache_read_input_tokens": 3000,
                    "cache_creation_input_tokens": 0,
                    "input_tokens": 500,
                    "output_tokens": 300,
                },
            }

        svc = BudgetForecastService(invoker=fake)
        result = await svc.forecast(_bundle())
        assert result.model_id == "claude-sonnet-4-7"
        assert len(result.predicted_line_items) == 7
        assert result.predicted_revenue_fen == 10000000000
        assert result.cache_read_tokens == 3000
        assert abs(result.cache_hit_rate - 0.8571) < 0.001

    @pytest.mark.asyncio
    async def test_invoker_failure_degrades_to_rule_engine(self):
        async def failing(req):
            raise RuntimeError("network")

        svc = BudgetForecastService(invoker=failing)
        result = await svc.forecast(_bundle())
        # 降级到规则引擎
        assert "降级" in result.sonnet_analysis
        # predicted_line_items 仍然覆盖 7 项
        assert len(result.predicted_line_items) == 7

    @pytest.mark.asyncio
    async def test_invoker_incomplete_response_fills_from_rule_engine(self):
        """Sonnet 只返了 revenue 和 net 两项，应该用规则引擎补齐"""

        async def partial(req):
            return {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            '{"predicted_line_items":['
                            '{"line_item":"revenue","predicted_fen":10000000000,'
                            '"ratio_of_revenue":1.0,"confidence_low":9000000000,'
                            '"confidence_high":11000000000}'
                            '],"variance_risks":[],"preventive_actions":[],'
                            '"analysis":"partial"}'
                        ),
                    }
                ],
                "usage": {
                    "cache_read_input_tokens": 3000,
                    "input_tokens": 500,
                    "output_tokens": 100,
                },
            }

        svc = BudgetForecastService(invoker=partial)
        result = await svc.forecast(_bundle())
        predicted = {li.line_item for li in result.predicted_line_items}
        assert predicted == {
            "revenue",
            "food_cost",
            "labor_cost",
            "rent",
            "utility",
            "other",
            "net",
        }
        assert "line_items 使用规则引擎补齐" in result.sonnet_analysis

    @pytest.mark.asyncio
    async def test_no_invoker_uses_rule_engine(self):
        svc = BudgetForecastService(invoker=None)
        result = await svc.forecast(_bundle())
        assert result.model_id == "rule_engine_fallback"


# ────────────────────────────────────────────────
# 9. v281 迁移静态断言
# ────────────────────────────────────────────────


class TestV281Migration:
    @pytest.fixture
    def migration_source(self):
        path = (
            ROOT
            / "shared"
            / "db-migrations"
            / "versions"
            / "v281_budget_forecast_analyses.py"
        )
        return path.read_text(encoding="utf-8")

    def test_revision_chain(self, migration_source):
        assert 'revision = "v281_budget_forecast"' in migration_source
        assert 'down_revision = "v280_salary_anomaly"' in migration_source

    def test_has_6_status_states(self, migration_source):
        for st in ("pending", "analyzed", "approved", "revised", "escalated", "error"):
            assert f"'{st}'" in migration_source

    def test_has_4_scope_states(self, migration_source):
        for sc in ("monthly_brand", "monthly_store", "quarterly_brand", "adhoc"):
            assert f"'{sc}'" in migration_source

    def test_has_5_business_types(self, migration_source):
        for bt in ("full_service", "quick_service", "tea_beverage", "buffet", "hot_pot"):
            assert f"'{bt}'" in migration_source

    def test_has_prompt_cache_columns(self, migration_source):
        for col in (
            "cache_read_tokens",
            "cache_creation_tokens",
            "input_tokens",
            "output_tokens",
            "model_id",
        ):
            assert col in migration_source

    def test_enables_rls(self, migration_source):
        assert "ENABLE ROW LEVEL SECURITY" in migration_source
        assert "budget_forecast_tenant_isolation" in migration_source
        assert "app.tenant_id" in migration_source

    def test_unique_idempotent_index(self, migration_source):
        assert "ux_budget_forecast_monthly" in migration_source
        assert "CREATE UNIQUE INDEX" in migration_source


# ────────────────────────────────────────────────
# 10. ModelRouter 注册
# ────────────────────────────────────────────────


class TestModelRouterRegistration:
    def test_budget_forecast_registered_as_complex(self):
        router_src = (
            ROOT
            / "services"
            / "tunxiang-api"
            / "src"
            / "shared"
            / "core"
            / "model_router.py"
        ).read_text(encoding="utf-8")
        assert '"budget_forecast_analysis": TaskComplexity.COMPLEX' in router_src
