"""test_d4a_cost_root_cause.py —— Sprint D4a 成本根因分析测试

覆盖：
  1. CostSignalBundle.to_json_dict 序列化完整性
  2. CachedPromptBuilder.build_request 结构含 cache_control 标记
  3. parse_sonnet_response：正常 JSON / code fence / 损坏 JSON 降级
  4. CostRootCauseService._should_trigger 阈值
  5. Service.analyze：invoker=None → fallback 规则引擎
  6. Service.analyze：invoker 返数据 → 解析 + token stats
  7. fallback 规则：price_hike / waste / bom / 无信号 4 分支
  8. cache_hit_rate 计算
  9. v279 迁移静态校验（status 枚举 + 唯一约束 + cache_read 字段 + RLS）
  10. ModelRouter 注册 cost_root_cause_analysis
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.cost_root_cause_service import (  # noqa: E402
    CACHE_HIT_TARGET,
    COST_OVERRUN_TRIGGER_PCT,
    SONNET_CACHED_MODEL,
    BOMDeviation,
    CachedPromptBuilder,
    CostRootCauseService,
    CostSignalBundle,
    RawMaterialPriceChange,
    RootCauseAnalysisResult,
    WasteEvent,
    parse_sonnet_response,
)

# ──────────────────────────────────────────────────────────────────────
# 1. CostSignalBundle
# ──────────────────────────────────────────────────────────────────────

def _sample_bundle(cost_overrun_pct: float = 0.08) -> CostSignalBundle:
    return CostSignalBundle(
        store_id="00000000-0000-0000-0000-000000000001",
        store_name="徐记海鲜五一店",
        analysis_month=date(2026, 3, 1),
        food_cost_fen=50000000,       # 50 万
        food_cost_budget_fen=45000000,
        cost_overrun_pct=cost_overrun_pct,
        price_changes=[
            RawMaterialPriceChange(
                ingredient_name="活鲈鱼",
                old_price_fen=5800,
                new_price_fen=7200,
                change_pct=0.241,
                supplier="洞庭水产",
            ),
        ],
        waste_events=[
            WasteEvent(
                ingredient_name="剁椒鱼头",
                quantity=2.5, unit="kg", loss_fen=580000,
                reason="expired",
                recorded_at=datetime(2026, 3, 15, 20, 0, tzinfo=timezone.utc),
            ),
        ],
        bom_deviations=[
            BOMDeviation(
                dish_name="剁椒鱼头",
                ingredient_name="剁椒",
                standard_qty=0.15, actual_qty=0.22,
                deviation_pct=0.467,
            ),
        ],
    )


def test_signal_bundle_serializes_completely():
    b = _sample_bundle()
    d = b.to_json_dict()
    assert d["store_name"] == "徐记海鲜五一店"
    assert d["food_cost_yuan"] == 500000.0
    assert "price_changes" in d and len(d["price_changes"]) == 1
    assert d["price_changes"][0]["ingredient"] == "活鲈鱼"
    assert "waste_events_summary" in d
    assert d["waste_events_summary"]["total_count"] == 1
    # BOM 偏差 >5% 才进
    assert len(d["bom_deviations"]) == 1


def test_signal_bundle_filters_small_bom_deviations():
    b = _sample_bundle()
    b.bom_deviations.append(BOMDeviation(
        dish_name="清蒸鲈鱼", ingredient_name="鲈鱼",
        standard_qty=1.0, actual_qty=1.02, deviation_pct=0.02,
    ))
    d = b.to_json_dict()
    # 新加的 2% 偏差应被过滤
    assert len(d["bom_deviations"]) == 1


def test_signal_bundle_groups_waste_by_reason():
    b = _sample_bundle()
    b.waste_events.append(WasteEvent(
        ingredient_name="豆芽", quantity=1.0, unit="kg", loss_fen=10000,
        reason="prep_waste",
        recorded_at=datetime(2026, 3, 20, tzinfo=timezone.utc),
    ))
    d = b.to_json_dict()
    reasons = d["waste_events_summary"]["by_reason"]
    assert "expired" in reasons and "prep_waste" in reasons
    assert reasons["expired"]["count"] == 1
    assert reasons["prep_waste"]["loss_yuan"] == 100.0


# ──────────────────────────────────────────────────────────────────────
# 2. CachedPromptBuilder
# ──────────────────────────────────────────────────────────────────────

def test_builder_request_structure():
    req = CachedPromptBuilder.build_request(signal_bundle=_sample_bundle())
    assert req["model"] == SONNET_CACHED_MODEL
    assert req["max_tokens"] > 0
    assert isinstance(req["system"], list) and len(req["system"]) == 2
    for block in req["system"]:
        assert block["type"] == "text"
        assert block["cache_control"] == {"type": "ephemeral"}
        assert len(block["text"]) > 100  # 非空且有实际内容
    assert isinstance(req["messages"], list) and len(req["messages"]) == 1
    assert req["messages"][0]["role"] == "user"
    # user 内容应含序列化的门店数据
    assert "徐记海鲜五一店" in req["messages"][0]["content"]


def test_builder_system_contains_stable_schema_and_benchmarks():
    req = CachedPromptBuilder.build_request(signal_bundle=_sample_bundle())
    system_text = "\n".join(b["text"] for b in req["system"])
    # Schema 段
    assert "ranked_causes" in system_text
    assert "remediation_actions" in system_text
    # 行业基准段
    assert "food_cost_rate" in system_text
    assert "浪费率基准" in system_text
    assert "BOM 偏差容忍" in system_text


def test_builder_user_message_includes_json():
    req = CachedPromptBuilder.build_request(signal_bundle=_sample_bundle())
    user_text = req["messages"][0]["content"]
    # 含 JSON 标记
    assert "```json" in user_text
    assert "food_cost_yuan" in user_text


# ──────────────────────────────────────────────────────────────────────
# 3. parse_sonnet_response
# ──────────────────────────────────────────────────────────────────────

def _mock_response(analysis_json: dict, usage: dict | None = None) -> dict:
    return {
        "content": [{"type": "text", "text": json.dumps(analysis_json, ensure_ascii=False)}],
        "usage": usage or {},
    }


def test_parse_response_valid_json():
    payload = {
        "analysis": "原料涨价主导",
        "ranked_causes": [
            {
                "cause_type": "price_hike", "confidence": 0.8,
                "evidence": "鲈鱼涨 24%", "impact_fen": 300000, "priority": "high",
            },
        ],
        "remediation_actions": [
            {
                "action": "切换备用供应商", "owner_role": "supply_chain",
                "deadline_days": 14, "expected_savings_fen": 150000,
            },
        ],
    }
    usage = {
        "input_tokens": 1000,
        "output_tokens": 500,
        "cache_read_input_tokens": 3000,
        "cache_creation_input_tokens": 0,
    }
    analysis, causes, actions, stats = parse_sonnet_response(_mock_response(payload, usage))
    assert analysis == "原料涨价主导"
    assert len(causes) == 1
    assert causes[0].cause_type == "price_hike"
    assert causes[0].impact_fen == 300000
    assert len(actions) == 1
    assert actions[0].owner_role == "supply_chain"
    assert stats["cache_read_tokens"] == 3000
    assert stats["input_tokens"] == 1000


def test_parse_response_with_code_fence():
    """支持 ```json ... ``` 包裹"""
    inner = {
        "analysis": "test", "ranked_causes": [],
        "remediation_actions": [{"action": "collect", "owner_role": "store_manager",
                                 "deadline_days": 7, "expected_savings_fen": 0}],
    }
    wrapped = f"```json\n{json.dumps(inner)}\n```"
    response = {"content": [{"type": "text", "text": wrapped}], "usage": {}}
    analysis, causes, actions, stats = parse_sonnet_response(response)
    assert analysis == "test"
    assert len(actions) == 1


def test_parse_response_broken_json_falls_back_gracefully():
    """损坏 JSON → analysis 用 raw text 前 200，causes/actions 空"""
    response = {"content": [{"type": "text", "text": "不是 JSON 格式"}], "usage": {}}
    analysis, causes, actions, _ = parse_sonnet_response(response)
    assert analysis  # 非空
    assert causes == []
    assert actions == []


def test_parse_response_empty_content():
    analysis, causes, actions, _ = parse_sonnet_response({"content": [], "usage": {}})
    assert causes == [] and actions == []


# ──────────────────────────────────────────────────────────────────────
# 4. Service trigger 阈值
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_should_trigger_below_5pct_returns_empty():
    """成本超支 < 5% → 不触发分析，返空结果"""
    service = CostRootCauseService()
    bundle = _sample_bundle(cost_overrun_pct=0.03)
    result = await service.analyze(bundle)
    assert result.ranked_causes == []
    assert "未触发" in result.sonnet_analysis or "预算内" in result.sonnet_analysis


@pytest.mark.asyncio
async def test_should_trigger_at_or_above_5pct():
    """≥ 5% → 触发"""
    service = CostRootCauseService()
    bundle = _sample_bundle(cost_overrun_pct=COST_OVERRUN_TRIGGER_PCT)
    result = await service.analyze(bundle)
    # 触发后 ranked_causes 至少有 1 条（规则引擎）
    assert len(result.ranked_causes) >= 1


# ──────────────────────────────────────────────────────────────────────
# 5. Fallback 规则引擎
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fallback_ranks_price_hike_when_multiple_hikes():
    service = CostRootCauseService()
    b = _sample_bundle()
    b.price_changes = [
        RawMaterialPriceChange(ingredient_name=f"食材{i}",
                                old_price_fen=1000, new_price_fen=1100,
                                change_pct=0.10)
        for i in range(4)
    ]
    result = await service.analyze(b)
    types = [c.cause_type for c in result.ranked_causes]
    assert "price_hike" in types


@pytest.mark.asyncio
async def test_fallback_detects_waste_spike():
    """浪费占比 > 5% → 走 waste_spike"""
    service = CostRootCauseService()
    b = _sample_bundle()
    b.price_changes = []
    b.bom_deviations = []
    # 浪费 = 10% 食材成本
    b.waste_events = [
        WasteEvent(ingredient_name="食材x", quantity=1.0, unit="kg",
                   loss_fen=5000000,  # 5 万 / 50 万 = 10%
                   reason="expired",
                   recorded_at=datetime(2026, 3, 10, tzinfo=timezone.utc)),
    ]
    result = await service.analyze(b)
    types = [c.cause_type for c in result.ranked_causes]
    assert "waste_spike" in types


@pytest.mark.asyncio
async def test_fallback_returns_other_when_no_signals():
    service = CostRootCauseService()
    b = _sample_bundle()
    b.price_changes = []
    b.waste_events = []
    b.bom_deviations = []
    result = await service.analyze(b)
    types = [c.cause_type for c in result.ranked_causes]
    assert types == ["other"]
    assert result.remediation_actions[0].action.startswith("补齐")


# ──────────────────────────────────────────────────────────────────────
# 6. invoker 接入（mock）
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_service_with_invoker_uses_sonnet_response():
    invoked = []

    async def mock_sonnet(request: dict) -> dict:
        invoked.append(request)
        return _mock_response(
            {
                "analysis": "来自 Sonnet",
                "ranked_causes": [
                    {"cause_type": "supplier_switch", "confidence": 0.9,
                     "evidence": "供应商切换", "impact_fen": 200000, "priority": "high"},
                ],
                "remediation_actions": [
                    {"action": "回退供应商", "owner_role": "supply_chain",
                     "deadline_days": 7, "expected_savings_fen": 180000},
                ],
            },
            usage={"input_tokens": 500, "output_tokens": 300,
                   "cache_read_input_tokens": 3000, "cache_creation_input_tokens": 0},
        )

    service = CostRootCauseService(sonnet_invoker=mock_sonnet)
    result = await service.analyze(_sample_bundle())

    assert len(invoked) == 1
    # 验证请求结构
    req = invoked[0]
    assert req["model"] == SONNET_CACHED_MODEL
    assert len(req["system"]) == 2
    # 验证响应解析
    assert result.sonnet_analysis == "来自 Sonnet"
    assert len(result.ranked_causes) == 1
    assert result.ranked_causes[0].cause_type == "supplier_switch"
    # Prompt Cache 统计
    assert result.cache_read_tokens == 3000
    assert result.input_tokens == 500


@pytest.mark.asyncio
async def test_service_invoker_failure_falls_back():
    async def boom(request):
        raise RuntimeError("API 429")

    service = CostRootCauseService(sonnet_invoker=boom)
    result = await service.analyze(_sample_bundle())
    # 不 crash，走规则引擎
    assert result.model_id == "fallback_rules"
    assert len(result.ranked_causes) >= 1


# ──────────────────────────────────────────────────────────────────────
# 7. cache_hit_rate 计算
# ──────────────────────────────────────────────────────────────────────

def test_cache_hit_rate_zero_when_no_cache():
    r = RootCauseAnalysisResult(input_tokens=1000, output_tokens=500)
    assert r.cache_hit_rate == 0.0


def test_cache_hit_rate_high():
    r = RootCauseAnalysisResult(
        cache_read_tokens=3000,
        cache_creation_tokens=0,
        input_tokens=1000,
        output_tokens=500,
    )
    # 3000 / (3000 + 0 + 1000) = 0.75
    assert r.cache_hit_rate == pytest.approx(0.75, abs=0.001)


def test_cache_hit_rate_excludes_output():
    """output_tokens 不算 input，不影响 hit rate"""
    r = RootCauseAnalysisResult(
        cache_read_tokens=4000, cache_creation_tokens=0,
        input_tokens=1000, output_tokens=100000,
    )
    assert r.cache_hit_rate == pytest.approx(4000 / 5000, abs=0.001)


def test_cache_hit_target_constant():
    assert CACHE_HIT_TARGET == 0.75


# ──────────────────────────────────────────────────────────────────────
# 8. v279 迁移静态校验
# ──────────────────────────────────────────────────────────────────────

_MIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..",
    "shared", "db-migrations", "versions", "v279_cost_root_cause_analyses.py"
)


def _read_mig() -> str:
    if not os.path.exists(_MIG_PATH):
        pytest.skip("v279 不存在")
    with open(_MIG_PATH, encoding="utf-8") as f:
        return f.read()


def test_v279_creates_table_with_required_columns():
    content = _read_mig()
    for col in (
        "food_cost_fen", "food_cost_budget_fen", "cost_overrun_pct",
        "signals_snapshot", "ranked_causes", "remediation_actions",
        "sonnet_analysis", "model_id",
        "cache_read_tokens", "cache_creation_tokens",
        "input_tokens", "output_tokens",
        "status", "reviewed_by", "reviewed_at",
        "analysis_type", "analysis_month",
    ):
        assert col in content, f"缺列 {col}"


def test_v279_status_and_analysis_type_enums():
    content = _read_mig()
    for s in ("pending", "analyzed", "acted_on", "dismissed", "error"):
        assert s in content, f"缺 status={s}"
    for t in ("monthly_cost_overrun", "sudden_cost_spike", "manual"):
        assert t in content, f"缺 analysis_type={t}"


def test_v279_has_unique_monthly_index():
    """同月同店 monthly_cost_overrun 只一条"""
    content = _read_mig()
    assert "ux_cost_root_cause_monthly" in content
    assert "analysis_type = 'monthly_cost_overrun'" in content


def test_v279_has_rls_and_indexes():
    content = _read_mig()
    assert "ENABLE ROW LEVEL SECURITY" in content
    assert "cost_root_cause_tenant_isolation" in content
    assert "app.tenant_id" in content
    assert "idx_cost_root_cause_tenant_status" in content
    assert "idx_cost_root_cause_cache_stats" in content


def test_v279_down_revision_chains_to_v278():
    content = _read_mig()
    assert 'down_revision = "v278"' in content


# ──────────────────────────────────────────────────────────────────────
# 9. ModelRouter 注册
# ──────────────────────────────────────────────────────────────────────

def test_model_router_registers_d4_task_types():
    path = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "..",
        "services", "tunxiang-api", "src", "shared", "core", "model_router.py"
    )
    if not os.path.exists(path):
        pytest.skip("model_router.py 不存在")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    for t in (
        "cost_root_cause_analysis",
        "salary_anomaly_detection",
        "budget_forecast_analysis",
    ):
        assert f'"{t}": TaskComplexity.COMPLEX' in content, f"缺 task_type={t}"
