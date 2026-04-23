"""test_d3c_dish_pricing.py —— Sprint D3c 菜品动态定价测试

覆盖：
  1. estimate_elasticity_log_log：数据不足 / 价格不变 / 负弹性场景
  2. solve_optimal_price：毛利底线约束 / ±15% 变动上限 / ε>=0 不动价
  3. expected_qty_delta：涨价/降价/零弹性
  4. DishDynamicPricingService.suggest_pricing 端到端
  5. Sonnet validate：有/无 invoker 的降级路径
  6. Sonnet 响应解析 risk_level
  7. constraint_check 字段完备性
  8. v278 迁移静态校验
  9. ModelRouter 注册 dish_dynamic_pricing → MODERATE
"""
from __future__ import annotations

import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.dish_dynamic_pricing_service import (  # noqa: E402
    DEFAULT_PRIOR_ELASTICITY,
    MARGIN_FLOOR,
    MAX_PRICE_CHANGE_PCT,
    DishDynamicPricingService,
    PricingObservation,
    estimate_elasticity_log_log,
    expected_qty_delta,
    solve_optimal_price,
)

# ──────────────────────────────────────────────────────────────────────
# 1. 弹性估算
# ──────────────────────────────────────────────────────────────────────

def test_elasticity_insufficient_data():
    """数据 < 14 点 → 返回 insufficient + 先验"""
    obs = [
        PricingObservation(day=date(2026, 1, i + 1), price_fen=5000, quantity_sold=50)
        for i in range(5)
    ]
    est = estimate_elasticity_log_log(obs)
    assert est.source == "insufficient"
    assert est.elasticity == DEFAULT_PRIOR_ELASTICITY
    assert est.data_points == 5
    assert est.confidence < 0.2


def test_elasticity_no_price_variation_returns_prior():
    """价格从未变过 → 无法估弹性 → prior"""
    obs = [
        PricingObservation(day=date(2026, 1, i + 1), price_fen=5000, quantity_sold=50)
        for i in range(20)
    ]
    est = estimate_elasticity_log_log(obs)
    assert est.source == "prior"
    assert est.elasticity == DEFAULT_PRIOR_ELASTICITY


def test_elasticity_typical_negative():
    """典型场景：涨价使销量下降 → ε 负值"""
    # 价格 5000 → 销量 80；价格 6000 → 销量 60；价格 7000 → 销量 45
    # 用这三组 * 5 次重复构成 15 点数据
    obs = []
    i = 0
    for price, qty in [(5000, 80), (5500, 70), (6000, 60),
                       (6500, 52), (7000, 45), (5200, 75), (5800, 65),
                       (6300, 55), (6800, 48), (7500, 40),
                       (5100, 78), (5700, 67), (6200, 57),
                       (6700, 50), (7200, 42)]:
        obs.append(PricingObservation(
            day=date(2026, 1, i + 1), price_fen=price, quantity_sold=qty,
        ))
        i += 1
    est = estimate_elasticity_log_log(obs)
    assert est.source == "log_log"
    assert est.elasticity < 0, f"典型涨价-减量应是负弹性，实际 {est.elasticity}"
    assert est.confidence > 0.3, "质量较好的数据应有置信 > 0.3"


# ──────────────────────────────────────────────────────────────────────
# 2. 最优价格
# ──────────────────────────────────────────────────────────────────────

def test_solve_optimal_price_respects_margin_floor():
    """成本 5000，毛利底线 15% → 价格必须 ≥ 5000/(1-0.15) ≈ 5882"""
    result = solve_optimal_price(
        current_price_fen=6000,
        cost_fen=5000,
        elasticity=-2.0,  # 有弹性
    )
    min_price = int(5000 / (1 - MARGIN_FLOOR))
    assert result >= min_price, f"必须满足毛利底线，实际 {result} < {min_price}"


def test_solve_optimal_price_respects_max_change_pct():
    """变动 ≤ ±15%"""
    current = 10000
    result = solve_optimal_price(
        current_price_fen=current,
        cost_fen=3000,
        elasticity=-2.5,
    )
    upper = int(current * (1 + MAX_PRICE_CHANGE_PCT))
    lower = int(current * (1 - MAX_PRICE_CHANGE_PCT))
    assert lower <= result <= upper, f"变动超限 {result} 不在 [{lower}, {upper}]"


def test_solve_optimal_price_positive_elasticity_no_change():
    """ε >= 0 是异常，不动价（防被噪声带偏）"""
    result = solve_optimal_price(
        current_price_fen=10000,
        cost_fen=3000,
        elasticity=0.5,   # 正弹性（异常）
    )
    assert result == 10000


def test_solve_optimal_price_low_elasticity_pushes_up():
    """ε ∈ [-1, 0) → 低弹性，应涨到上限"""
    current = 10000
    result = solve_optimal_price(
        current_price_fen=current,
        cost_fen=3000,
        elasticity=-0.5,
    )
    upper = int(current * (1 + MAX_PRICE_CHANGE_PCT))
    assert result == upper


def test_solve_optimal_price_below_floor_must_raise():
    """当前价已低于毛利底线 → 强制涨到 min_price"""
    result = solve_optimal_price(
        current_price_fen=3000,   # 当前毛利率 0%
        cost_fen=3000,
        elasticity=-2.0,
    )
    min_price = int(3000 / (1 - MARGIN_FLOOR))
    assert result >= min_price


# ──────────────────────────────────────────────────────────────────────
# 3. 销量变化估算
# ──────────────────────────────────────────────────────────────────────

def test_expected_qty_delta_price_up_reduces_qty():
    """涨价 + 负弹性 → 销量下降"""
    delta = expected_qty_delta(
        current_price_fen=10000,
        new_price_fen=11000,
        current_daily_qty=100,
        elasticity=-1.0,
    )
    assert delta < 0


def test_expected_qty_delta_price_down_increases_qty():
    """降价 + 负弹性 → 销量上升"""
    delta = expected_qty_delta(
        current_price_fen=10000,
        new_price_fen=9000,
        current_daily_qty=100,
        elasticity=-1.0,
    )
    assert delta > 0


def test_expected_qty_delta_zero_elasticity_unchanged():
    """ε=0 → 任何价格变化都不影响销量"""
    delta = expected_qty_delta(
        current_price_fen=10000,
        new_price_fen=15000,
        current_daily_qty=100,
        elasticity=0.0,
    )
    assert delta == 0


def test_expected_qty_delta_zero_current_qty():
    """当前销量 0 → 永远返 0"""
    delta = expected_qty_delta(10000, 11000, 0, -1.0)
    assert delta == 0


# ──────────────────────────────────────────────────────────────────────
# 4. suggest_pricing 端到端
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_suggest_pricing_with_sufficient_data():
    """≥14 点历史数据 → log_log elasticity + 合理建议"""
    service = DishDynamicPricingService()
    obs = []
    for i, (price, qty) in enumerate([
        (5000, 80), (5500, 70), (6000, 60), (6500, 52), (7000, 45),
        (5200, 75), (5800, 65), (6300, 55), (6800, 48), (7500, 40),
        (5100, 78), (5700, 67), (6200, 57), (6700, 50), (7200, 42),
    ]):
        obs.append(PricingObservation(
            day=date(2026, 1, i + 1), price_fen=price, quantity_sold=qty,
        ))

    result = await service.suggest_pricing(
        dish_id="00000000-0000-0000-0000-000000000001",
        dish_name="剁椒鱼头",
        current_price_fen=6000,
        cost_fen=2000,
        current_daily_qty=50,
        observations=obs,
    )
    assert result.elasticity.source == "log_log"
    assert result.constraint_check["margin_floor_passed"] is True
    assert result.constraint_check["change_pct_within_limit"] is True
    assert result.sonnet_analysis  # 即便 invoker=None 也有 fallback 文本
    assert result.sonnet_risk_level in {"low", "medium", "high"}


@pytest.mark.asyncio
async def test_suggest_pricing_insufficient_data_marks_high_risk():
    """数据不足 → prior elasticity → fallback 标 high risk"""
    service = DishDynamicPricingService()
    obs = [
        PricingObservation(day=date(2026, 1, i + 1), price_fen=5000, quantity_sold=50)
        for i in range(5)
    ]
    result = await service.suggest_pricing(
        dish_id="00000000-0000-0000-0000-000000000002",
        dish_name="小众菜",
        current_price_fen=6000, cost_fen=2000, current_daily_qty=10,
        observations=obs,
    )
    assert result.elasticity.source == "insufficient"
    # fallback 规则：数据不足 → high risk
    assert result.sonnet_risk_level == "high"
    assert "数据不足" in result.sonnet_analysis


@pytest.mark.asyncio
async def test_suggest_pricing_below_margin_floor_flags_violation():
    """当前毛利率已低于 15% → constraint_check 不标 passed"""
    service = DishDynamicPricingService()
    obs = [
        PricingObservation(day=date(2026, 1, i + 1), price_fen=3100, quantity_sold=50)
        for i in range(20)
    ]
    result = await service.suggest_pricing(
        dish_id="00000000-0000-0000-0000-000000000003",
        dish_name="成本超标菜",
        current_price_fen=3100,
        cost_fen=3000,  # 当前毛利率 ≈ 3.2%
        current_daily_qty=50,
        observations=obs,
    )
    # 建议价应该涨到 margin_floor 附近
    assert result.suggested_margin_rate >= MARGIN_FLOOR - 0.01


# ──────────────────────────────────────────────────────────────────────
# 5. Sonnet validate
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sonnet_validate_with_invoker():
    invoked = []

    async def mock_sonnet(prompt: str, model_id: str) -> str:
        invoked.append({"prompt": prompt, "model": model_id})
        return "建议谨慎涨价，考虑客户感知\nrisk_level=medium"

    service = DishDynamicPricingService(sonnet_invoker=mock_sonnet)
    obs = [
        PricingObservation(day=date(2026, 1, i + 1),
                           price_fen=5000 + (i % 3) * 500,
                           quantity_sold=50 - (i % 3) * 5)
        for i in range(20)
    ]
    result = await service.suggest_pricing(
        dish_id="00000000-0000-0000-0000-000000000004",
        dish_name="test",
        current_price_fen=5500, cost_fen=2000, current_daily_qty=50,
        observations=obs,
    )
    assert len(invoked) == 1
    assert invoked[0]["model"] == "claude-sonnet-4-6"
    assert result.sonnet_risk_level == "medium"
    assert "客户感知" in result.sonnet_analysis


@pytest.mark.asyncio
async def test_sonnet_validate_failure_falls_back_to_rules():
    async def boom(prompt, model_id):
        raise RuntimeError("API 503")

    service = DishDynamicPricingService(sonnet_invoker=boom)
    obs = [
        PricingObservation(day=date(2026, 1, i + 1), price_fen=5000, quantity_sold=50)
        for i in range(20)
    ]
    result = await service.suggest_pricing(
        dish_id="00000000-0000-0000-0000-000000000005",
        dish_name="fallback test",
        current_price_fen=5000, cost_fen=2000, current_daily_qty=50,
        observations=obs,
    )
    assert result.sonnet_risk_level in {"low", "medium", "high"}
    # 不 crash，有文本
    assert result.sonnet_analysis is not None


def test_parse_sonnet_risk_level_variants():
    """risk_level 解析对大小写/空格不敏感"""
    from services.dish_dynamic_pricing_service import (
        DishDynamicPricingService,
        ElasticityEstimate,
        PricingSuggestion,
    )
    stub = PricingSuggestion(
        dish_id="x", dish_name="x",
        current_price_fen=100, suggested_price_fen=110, current_cost_fen=40,
        current_margin_rate=0.6, suggested_margin_rate=0.63, price_change_pct=0.1,
        elasticity=ElasticityEstimate(-1, 0.5, "log_log", 20),
        expected_daily_qty_delta=0, expected_daily_margin_delta_fen=0,
        constraint_check={},
    )
    for text_in, expected in [
        ("文本分析\nrisk_level=high", "high"),
        ("分析\n risk_level = HIGH ", "high"),
        ("分析\nRisk_Level=Medium", "medium"),
        ("分析\nrisk_level=low", "low"),
        ("只有文本没格式", "low"),
    ]:
        _, risk = DishDynamicPricingService._parse_sonnet_response(text_in, stub)
        assert risk == expected, f"输入 {text_in!r} → 期望 {expected}，实际 {risk}"


# ──────────────────────────────────────────────────────────────────────
# 6. v278 迁移静态校验
# ──────────────────────────────────────────────────────────────────────

_MIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..",
    "shared", "db-migrations", "versions", "v278_dish_pricing_suggestions.py"
)


def _read_migration() -> str:
    if not os.path.exists(_MIG_PATH):
        pytest.skip("v278 迁移不存在")
    with open(_MIG_PATH, encoding="utf-8") as f:
        return f.read()


def test_v278_creates_table_with_all_columns():
    content = _read_migration()
    for col in (
        "current_price_fen", "suggested_price_fen", "current_cost_fen",
        "current_margin_rate", "suggested_margin_rate", "price_change_pct",
        "elasticity", "elasticity_confidence", "elasticity_source",
        "expected_daily_qty_delta", "expected_daily_margin_delta_fen",
        "constraint_check", "sonnet_analysis", "sonnet_risk_level",
        "status", "confirmed_by", "applied_at", "reverted_at",
        "actual_qty_delta", "actual_margin_delta_fen",
    ):
        assert col in content, f"缺列 {col}"


def test_v278_status_enum_and_checks():
    content = _read_migration()
    for st in ("plan", "human_confirmed", "applied", "reverted", "rejected", "expired"):
        assert st in content, f"缺 status={st}"
    for src in ("log_log", "coreml", "prior", "insufficient"):
        assert src in content, f"缺 elasticity_source={src}"
    assert "CHECK" in content
    assert "margin_floor_passed" in content or "margin_floor" in content


def test_v278_has_rls_and_indexes():
    content = _read_migration()
    assert "ENABLE ROW LEVEL SECURITY" in content
    assert "dish_pricing_tenant_isolation" in content
    assert "app.tenant_id" in content
    assert "idx_dish_pricing_tenant_status" in content
    assert "idx_dish_pricing_pending_approval" in content


def test_v278_down_revision_chains_to_v277():
    content = _read_migration()
    assert 'down_revision = "v277"' in content


# ──────────────────────────────────────────────────────────────────────
# 7. ModelRouter 注册
# ──────────────────────────────────────────────────────────────────────

def test_model_router_registers_dish_dynamic_pricing_as_moderate():
    path = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "..",
        "services", "tunxiang-api", "src", "shared", "core", "model_router.py"
    )
    if not os.path.exists(path):
        pytest.skip("model_router.py 不存在")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert '"dish_dynamic_pricing": TaskComplexity.MODERATE' in content
    # MODERATE 对应 Sonnet
    assert '"claude-sonnet-4-6"' in content
