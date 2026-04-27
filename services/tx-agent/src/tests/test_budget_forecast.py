"""Sprint D4c — 预算预测 Skill Agent 集成测试（Tier 2 标准）

覆盖：
  - Skill 在 ALL_SKILL_AGENTS 已注册
  - scope == {"margin"}
  - build_cached_system_blocks() ≥ 4000 字符 且含 cache_control
  - mock ModelRouter.complete_with_cache 返回合成 JSON 后，两个 action 输出通过 Pydantic 校验
  - mock usage 返回 cache_read=3000/input=500，cache_hit_ratio > 0.75 被正确解析
  - ModelRouter 调用时 task_type="budget_forecast"（路由到 Sonnet 4.7）
  - DecisionLogService.log_skill_result 被调用时 roi.prevented_loss_fen 写入
  - 源文件无 `except Exception:` bare

运行：
  pytest services/tx-agent/src/tests/test_budget_forecast.py -v
"""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# 将 src 目录加入 path，与 test_salary_anomaly.py 一致
_SRC_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, _SRC_DIR)

from agents.skills import ALL_SKILL_AGENTS, SKILL_REGISTRY  # noqa: E402
from agents.skills.budget_forecast import (  # noqa: E402
    BudgetForecastAgent,
    BudgetForecastOutput,
)
from prompts.budget_forecast import build_cached_system_blocks  # noqa: E402

TENANT_ID = "11111111-1111-1111-1111-111111111111"
STORE_ID = "22222222-2222-2222-2222-222222222222"


def _valid_forecast_json() -> str:
    """构造符合 Pydantic schema 的合成 LLM 输出（forecast_monthly_budget 场景）。"""
    payload = {
        "summary": "5 月预算预测：营收 +12%（五一旅游），食材率维持 32%，人力率降 0.5pp；综合成本率 73%。",
        "forecasts": [
            {
                "category": "food_cost",
                "forecast_fen": 3200000,
                "ci_80_lower_fen": 3050000,
                "ci_80_upper_fen": 3350000,
                "ci_95_lower_fen": 2950000,
                "ci_95_upper_fen": 3450000,
                "expected_rate": 0.325,
                "drivers": ["seasonality_may_travel", "ingredient_price_stable", "new_menu_launch"],
            },
            {
                "category": "labor_cost",
                "forecast_fen": 2250000,
                "ci_80_lower_fen": 2180000,
                "ci_80_upper_fen": 2320000,
                "ci_95_lower_fen": 2120000,
                "ci_95_upper_fen": 2380000,
                "expected_rate": 0.228,
                "drivers": ["holiday_overtime_surge", "no_promotion"],
            },
        ],
        "variances": [],
        "recommendations": [
            {
                "action": "调增 5 月食材预算 3%",
                "responsible_role": "采购",
                "verification_kpi": "food_cost_rate ≤ 33%",
                "deadline_days": 5,
                "risk_flag": "margin",
                "prevented_loss_fen": 80000,
            },
            {
                "action": "锁定五一 3 天加班排班",
                "responsible_role": "店长",
                "verification_kpi": "labor_cost_rate ≤ 23%",
                "deadline_days": 7,
                "risk_flag": "none",
                "prevented_loss_fen": 55000,
            },
        ],
        "risks": [
            {
                "risk_code": "sample_insufficient",
                "risk_label": "新店样本不足",
                "impact": "开业仅 4 个月，缺少五一同期数据，置信度下调。",
                "mitigation": "采用同品牌同商圈均值作为代理基准",
            },
        ],
        "confidence": 0.78,
    }
    return json.dumps(payload, ensure_ascii=False)


def _valid_variance_json() -> str:
    """构造符合 Pydantic schema 的合成 LLM 输出（detect_budget_variance 场景）。"""
    payload = {
        "summary": "4 月识别 2 个高风险偏差：食材 +12%（严重）与能耗 +8%（警戒）。",
        "forecasts": [],
        "variances": [
            {
                "category": "food_cost",
                "budget_fen": 3000000,
                "actual_fen": 3360000,
                "delta_fen": 360000,
                "delta_pct": 0.12,
                "severity": "high",
                "root_cause_code": "unit_price",
                "evidence": "主料采购单价较预算 +14%（猪肉/牛肉共 +18%），品项结构无显著变化。",
            },
            {
                "category": "utility_cost",
                "budget_fen": 300000,
                "actual_fen": 324000,
                "delta_fen": 24000,
                "delta_pct": 0.08,
                "severity": "warning",
                "root_cause_code": "energy_spike",
                "evidence": "空调日均用电 +18%（室温设定 22℃→20℃），下周已恢复 22℃。",
            },
        ],
        "recommendations": [
            {
                "action": "与 3 家主料供应商重谈单价",
                "responsible_role": "采购",
                "verification_kpi": "次月食材率 ≤ 33%",
                "deadline_days": 14,
                "risk_flag": "margin",
                "prevented_loss_fen": 180000,
            },
            {
                "action": "空调温度锁定 22℃ + 周巡查",
                "responsible_role": "店长",
                "verification_kpi": "次月能耗率 ≤ 3.2%",
                "deadline_days": 3,
                "risk_flag": "none",
                "prevented_loss_fen": 20000,
            },
        ],
        "risks": [],
        "confidence": 0.88,
    }
    return json.dumps(payload, ensure_ascii=False)


def _fake_usage(cache_read: int = 3000, input_tokens: int = 500) -> dict[str, int | float]:
    total = input_tokens + cache_read
    ratio = cache_read / total if total > 0 else 0.0
    return {
        "input_tokens": input_tokens,
        "output_tokens": 400,
        "cache_read_input_tokens": cache_read,
        "cache_creation_input_tokens": 0,
        "cache_hit_ratio": round(ratio, 4),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. 注册 & scope
# ─────────────────────────────────────────────────────────────────────────────


def test_skill_registered_in_registry() -> None:
    assert BudgetForecastAgent in ALL_SKILL_AGENTS, (
        "BudgetForecastAgent 必须在 services/tx-agent/src/agents/skills/__init__.py 的 ALL_SKILL_AGENTS 列表中注册"
    )
    assert "budget_forecast" in SKILL_REGISTRY, "budget_forecast agent_id 必须出现在 SKILL_REGISTRY 映射中"
    assert SKILL_REGISTRY["budget_forecast"] is BudgetForecastAgent


def test_scope_is_margin() -> None:
    assert BudgetForecastAgent.constraint_scope == {"margin"}, (
        f"D4c 预算预测必须且只声明 margin scope（直接影响成本决策 → 毛利底线），实际：{BudgetForecastAgent.constraint_scope}"
    )


def test_agent_metadata() -> None:
    """基础元信息快速检查。"""
    assert BudgetForecastAgent.agent_id == "budget_forecast"
    assert BudgetForecastAgent.agent_level == 1  # Level 1：仅建议
    actions = BudgetForecastAgent(TENANT_ID).get_supported_actions()
    assert "forecast_monthly_budget" in actions
    assert "detect_budget_variance" in actions


# ─────────────────────────────────────────────────────────────────────────────
# 2. Prompt Cache 门槛
# ─────────────────────────────────────────────────────────────────────────────


def test_system_blocks_meet_cache_threshold() -> None:
    """build_cached_system_blocks() 合计 ≥ 4000 字符（≥1024 tokens）且含 cache_control。"""
    blocks = build_cached_system_blocks()
    assert isinstance(blocks, list) and len(blocks) >= 1

    total_text = "".join(b.get("text", "") for b in blocks)
    assert len(total_text) >= 4000, f"系统提示合计 {len(total_text)} 字符，低于 4000 字符门槛（粗估 <1024 tokens）"

    has_cache = any(isinstance(b, dict) and b.get("cache_control", {}).get("type") == "ephemeral" for b in blocks)
    assert has_cache, "至少一个 system block 必须带 cache_control={'type':'ephemeral'}"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Action 输出通过 Pydantic 校验
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_forecast_monthly_budget_returns_pydantic() -> None:
    """mock complete_with_cache 返回合成 JSON，断言 action 输出被正确解析 + Pydantic 校验。"""
    fake_router = AsyncMock()
    fake_router.complete_with_cache = AsyncMock(
        return_value=(_valid_forecast_json(), _fake_usage()),
    )

    agent = BudgetForecastAgent(
        tenant_id=TENANT_ID,
        store_id=STORE_ID,
        model_router=fake_router,
    )

    result = await agent.run(
        action="forecast_monthly_budget",
        params={
            "store_id": STORE_ID,
            "target_period": "2026-05",
            "history_months": {
                "2026-04": {"revenue_fen": 9500000, "food_cost_fen": 3040000, "labor_cost_fen": 2185000},
                "2026-03": {"revenue_fen": 9200000, "food_cost_fen": 2944000, "labor_cost_fen": 2116000},
            },
            "store_profile": {"format": "中式正餐", "area_m2": 280, "open_months": 4},
            "seasonality_hints": "5月五一旅游旺季",
            "business_plan": {"new_menu_count": 3},
        },
    )

    assert result.success is True, f"action 执行应成功，error={result.error}"
    assert result.action == "forecast_monthly_budget"
    # 结构化字段存在
    assert "forecasts" in result.data
    assert "recommendations" in result.data
    assert "risks" in result.data
    assert len(result.data["forecasts"]) == 2
    assert len(result.data["recommendations"]) == 2
    assert len(result.data["risks"]) == 1
    # 置信度被正确提取
    assert result.confidence == pytest.approx(0.78)

    # 再次用 Pydantic 模型复校（双保险）
    validated = BudgetForecastOutput(
        summary=result.data["summary"],
        forecasts=result.data["forecasts"],
        variances=result.data["variances"],
        recommendations=result.data["recommendations"],
        risks=result.data["risks"],
        confidence=result.confidence,
    )
    assert validated.forecasts[0].category == "food_cost"
    assert validated.forecasts[0].forecast_fen == 3200000
    assert validated.forecasts[0].ci_95_lower_fen <= validated.forecasts[0].ci_80_lower_fen
    assert validated.forecasts[0].ci_95_upper_fen >= validated.forecasts[0].ci_80_upper_fen
    assert validated.recommendations[0].prevented_loss_fen == 80000


@pytest.mark.asyncio
async def test_detect_budget_variance_returns_pydantic() -> None:
    """第二个 action 也能走通 Pydantic 校验路径。"""
    fake_router = AsyncMock()
    fake_router.complete_with_cache = AsyncMock(
        return_value=(_valid_variance_json(), _fake_usage()),
    )

    agent = BudgetForecastAgent(
        tenant_id=TENANT_ID,
        store_id=STORE_ID,
        model_router=fake_router,
    )

    result = await agent.run(
        action="detect_budget_variance",
        params={
            "store_id": STORE_ID,
            "period": "2026-04",
            "budget_plan": {
                "food_cost": 3000000,
                "labor_cost": 2200000,
                "utility_cost": 300000,
            },
            "actual_cost": {
                "food_cost": 3360000,
                "labor_cost": 2185000,
                "utility_cost": 324000,
            },
            "revenue_actual_fen": 9500000,
            "context_events": ["main_ingredient_price_up_14pct"],
        },
    )

    assert result.success is True, f"action 执行应成功，error={result.error}"
    assert result.action == "detect_budget_variance"
    assert len(result.data["variances"]) == 2
    # 第一个偏差是 food_cost high
    assert result.data["variances"][0]["category"] == "food_cost"
    assert result.data["variances"][0]["severity"] == "high"
    assert result.data["variances"][0]["root_cause_code"] == "unit_price"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Cache hit ratio ≥ 0.75
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prompt_cache_hit_ratio_reports_correctly() -> None:
    """mock usage 返回 cache_read=3000, input_tokens=500 → ratio ≈ 0.857 > 0.75。"""
    fake_usage = _fake_usage(cache_read=3000, input_tokens=500)

    # Sanity check：构造的 usage 自身满足 > 0.75
    assert fake_usage["cache_hit_ratio"] > 0.75

    fake_router = AsyncMock()
    fake_router.complete_with_cache = AsyncMock(
        return_value=(_valid_forecast_json(), fake_usage),
    )

    agent = BudgetForecastAgent(
        tenant_id=TENANT_ID,
        model_router=fake_router,
    )
    result = await agent.run(
        action="forecast_monthly_budget",
        params={
            "store_id": STORE_ID,
            "target_period": "2026-05",
            "history_months": {},
        },
    )

    assert result.success is True
    usage = result.data["usage"]
    assert usage["cache_read_input_tokens"] == 3000
    assert usage["input_tokens"] == 500
    # 比率应由 ModelRouter 层计算并透传出来
    assert usage["cache_hit_ratio"] > 0.75, (
        f"cache_hit_ratio={usage['cache_hit_ratio']} 应 > 0.75（Anthropic 推荐阈值）"
    )
    # roi 中也应透传 cache_hit_ratio
    assert result.data["roi"]["roi_evidence"]["cache_hit_ratio"] > 0.75


# ─────────────────────────────────────────────────────────────────────────────
# 5. ModelRouter 调用参数校验（task_type="budget_forecast" → Sonnet 4.7）
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_model_router_called_with_sonnet_4_7() -> None:
    """校验 ModelRouter.complete_with_cache 被调用时 task_type='budget_forecast'。"""
    fake_router = AsyncMock()
    fake_router.complete_with_cache = AsyncMock(
        return_value=(_valid_variance_json(), _fake_usage()),
    )

    agent = BudgetForecastAgent(
        tenant_id=TENANT_ID,
        model_router=fake_router,
    )
    await agent.run(
        action="detect_budget_variance",
        params={
            "store_id": STORE_ID,
            "period": "2026-04",
            "budget_plan": {"food_cost": 3000000},
            "actual_cost": {"food_cost": 3360000},
            "revenue_actual_fen": 9500000,
        },
    )

    fake_router.complete_with_cache.assert_awaited_once()
    kwargs = fake_router.complete_with_cache.await_args.kwargs
    assert kwargs["task_type"] == "budget_forecast", (
        f"task_type 必须是 'budget_forecast'（route 到 Sonnet 4.7），实际：{kwargs.get('task_type')}"
    )
    assert kwargs["tenant_id"] == TENANT_ID
    # 系统提示必须为 list[dict] 且至少一个块含 cache_control
    system_blocks = kwargs["system_blocks"]
    assert isinstance(system_blocks, list) and len(system_blocks) >= 1
    assert any(b.get("cache_control") for b in system_blocks)
    # messages 必须是用户查询
    messages = kwargs["messages"]
    assert messages[0]["role"] == "user"
    assert "预算" in messages[0]["content"] or "budget" in messages[0]["content"].lower()
    # temperature=0.2（预测类确定性要求）
    assert kwargs["temperature"] == 0.2


# ─────────────────────────────────────────────────────────────────────────────
# 6. 决策留痕：roi.prevented_loss_fen 写入
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_decision_log_records_prevented_loss_fen() -> None:
    """ROI 四字段在 result.data 中正确计算：

    - prevented_loss_fen = Σ recommendations.prevented_loss_fen = 180000 + 20000 = 200000
    - improved_kpi.metric = "budget_accuracy_pct"
    - saved_labor_hours = 3.0（财务预算编制/稽核节省）
    - roi_evidence.model = claude-sonnet-4-7-20250929

    留痕路径（DecisionLogService.log_skill_result）在 DB=None 时静默跳过；
    DB 可用时通过 _write_decision_log() 调用。本测试聚焦"ROI 计算结果"—— 这是
    留痕链路的唯一真实载体（DecisionLogService 只是把它落 DB）。
    """
    fake_router = AsyncMock()
    fake_router.complete_with_cache = AsyncMock(
        return_value=(_valid_variance_json(), _fake_usage()),
    )

    # 监听 _write_decision_log 被调用（即使 DB=None 它也会被调用，然后内部 early-return）
    with patch.object(BudgetForecastAgent, "_write_decision_log", new_callable=AsyncMock) as mock_write:
        agent = BudgetForecastAgent(
            tenant_id=TENANT_ID,
            store_id=STORE_ID,
            model_router=fake_router,
        )
        result = await agent.run(
            action="detect_budget_variance",
            params={
                "store_id": STORE_ID,
                "period": "2026-04",
                "budget_plan": {"food_cost": 3000000},
                "actual_cost": {"food_cost": 3360000},
                "revenue_actual_fen": 9500000,
            },
        )

        assert result.success is True
        # _write_decision_log 应恰好被调一次
        assert mock_write.await_count == 1, f"_write_decision_log 应恰好被调用 1 次，实际 {mock_write.await_count} 次"
        # 传入的 roi（kwargs）含 prevented_loss_fen = 180000 + 20000 = 200000
        call_kwargs = mock_write.await_args.kwargs
        roi = call_kwargs["roi"]
        assert roi["prevented_loss_fen"] == 200000, (
            f"roi.prevented_loss_fen 应 = 180000 + 20000 = 200000，实际 {roi['prevented_loss_fen']}"
        )
        # improved_kpi 写入 budget_accuracy_pct
        assert roi["improved_kpi"]["metric"] == "budget_accuracy_pct"
        # saved_labor_hours 固定 3.0
        assert roi["saved_labor_hours"] == 3.0
        # 模型记录
        assert roi["roi_evidence"]["model"] == "claude-sonnet-4-7-20250929"

    # 再检一次 result.data.roi（双保险：LLM 返回的 recommendations 合计 ROI 应一致）
    assert result.data["roi"]["prevented_loss_fen"] == 200000
    assert result.data["roi"]["improved_kpi"]["metric"] == "budget_accuracy_pct"


# ─────────────────────────────────────────────────────────────────────────────
# 7. 代码质量：无 bare except Exception
# ─────────────────────────────────────────────────────────────────────────────


def test_no_broad_except() -> None:
    """ast 扫描 Skill 源文件，禁止 bare `except Exception`（§十四 审计修复期约束）。"""
    source_path = Path(__file__).resolve().parents[1] / "agents" / "skills" / "budget_forecast.py"
    assert source_path.exists(), f"源文件不存在：{source_path}"

    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        exc_type = node.type
        # bare `except:` 也禁止
        assert exc_type is not None, f"bare `except:` 在 budget_forecast.py:{node.lineno} —— 必须声明具体异常类型"
        # `except Exception:` / `except BaseException:` 不允许
        if isinstance(exc_type, ast.Name):
            assert exc_type.id not in ("Exception", "BaseException"), (
                f"broad `except {exc_type.id}:` 在 budget_forecast.py:{node.lineno} —— §十四 新代码禁止 except Exception"
            )
        if isinstance(exc_type, ast.Tuple):
            for elt in exc_type.elts:
                if isinstance(elt, ast.Name):
                    assert elt.id not in ("Exception", "BaseException"), (
                        f"broad `except (..., {elt.id}, ...):` 在 budget_forecast.py:{node.lineno}"
                    )
