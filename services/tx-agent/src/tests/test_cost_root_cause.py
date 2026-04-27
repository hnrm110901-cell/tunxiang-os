"""Sprint D4a — 成本根因 Skill Agent 集成测试（Tier 2 标准）

覆盖：
  - Skill 在 ALL_SKILL_AGENTS 已注册
  - scope == {"margin"}
  - build_cached_system_blocks() ≥ 4000 字符 且含 cache_control
  - mock ModelRouter.complete_with_cache 返回合成 JSON 后，action 输出通过 Pydantic 校验
  - mock usage 返回 cache_read=3000/input=500，cache_hit_ratio > 0.75 被正确解析
  - ModelRouter 调用时 task_type="cost_root_cause"
  - 源文件无 `except Exception:` bare

运行：
  pytest services/tx-agent/src/tests/test_cost_root_cause.py -v
"""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

# 将 src 目录加入 path，与 test_model_router.py 一致
_SRC_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, _SRC_DIR)

from agents.skills import ALL_SKILL_AGENTS  # noqa: E402
from agents.skills.cost_root_cause import (  # noqa: E402
    CostRootCauseAgent,
    CostRootCauseOutput,
)
from prompts.cost_root_cause import build_cached_system_blocks  # noqa: E402

TENANT_ID = "11111111-1111-1111-1111-111111111111"
STORE_ID = "22222222-2222-2222-2222-222222222222"


def _valid_llm_json() -> str:
    """构造符合 Pydantic schema 的合成 LLM 输出。"""
    payload = {
        "summary": "本月食材成本率升至 36.8%，主因水产采购价异常与损耗未记录。",
        "root_causes": [
            {
                "cause_code": "food_price_surge",
                "cause_label": "水产采购价异常",
                "category": "food_cost",
                "impact_fen": 42000,
                "impact_pct": 0.55,
                "evidence": "基围虾单价从 180 元/kg 升至 235 元/kg，连续 3 周未降",
            },
            {
                "cause_code": "waste_not_logged",
                "cause_label": "损耗未记录",
                "category": "food_cost",
                "impact_fen": 18000,
                "impact_pct": 0.25,
                "evidence": "盘点差异 3.2kg 基围虾未在 waste_events 登记",
            },
        ],
        "recommendations": [
            {
                "action": "启动替代供应商比价",
                "responsible_role": "采购",
                "estimated_saving_fen": 25000,
                "verification_kpi": "food_cost_rate ≤ 34%",
                "deadline_days": 7,
                "risk_flag": "none",
            },
            {
                "action": "开启 waste_events 强制登记流程",
                "responsible_role": "店长",
                "estimated_saving_fen": 12000,
                "verification_kpi": "盘点差异 ≤ 1kg",
                "deadline_days": 3,
                "risk_flag": "none",
            },
        ],
        "confidence": 0.82,
    }
    return json.dumps(payload, ensure_ascii=False)


def _fake_usage(cache_read: int = 3000, input_tokens: int = 500) -> dict[str, int | float]:
    total = input_tokens + cache_read
    ratio = cache_read / total if total > 0 else 0.0
    return {
        "input_tokens": input_tokens,
        "output_tokens": 300,
        "cache_read_input_tokens": cache_read,
        "cache_creation_input_tokens": 0,
        "cache_hit_ratio": round(ratio, 4),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. 注册 & scope
# ─────────────────────────────────────────────────────────────────────────────


def test_skill_registered_in_registry() -> None:
    assert CostRootCauseAgent in ALL_SKILL_AGENTS, (
        "CostRootCauseAgent 必须在 services/tx-agent/src/agents/skills/__init__.py 的 "
        "ALL_SKILL_AGENTS 列表中注册"
    )


def test_scope_is_margin() -> None:
    assert CostRootCauseAgent.constraint_scope == {"margin"}, (
        f"D4a 成本根因必须且只声明 margin scope，实际：{CostRootCauseAgent.constraint_scope}"
    )


def test_agent_metadata() -> None:
    """基础元信息快速检查。"""
    assert CostRootCauseAgent.agent_id == "cost_root_cause"
    assert CostRootCauseAgent.agent_level == 1  # Level 1：仅建议
    actions = CostRootCauseAgent(TENANT_ID).get_supported_actions()
    assert "analyze_cost_spike" in actions
    assert "explain_margin_drop" in actions


# ─────────────────────────────────────────────────────────────────────────────
# 2. Prompt Cache 门槛
# ─────────────────────────────────────────────────────────────────────────────


def test_system_blocks_meet_cache_threshold() -> None:
    """build_cached_system_blocks() 合计 ≥ 4000 字符（≥1024 tokens）且含 cache_control。"""
    blocks = build_cached_system_blocks()
    assert isinstance(blocks, list) and len(blocks) >= 1

    total_text = "".join(b.get("text", "") for b in blocks)
    assert len(total_text) >= 4000, (
        f"系统提示合计 {len(total_text)} 字符，低于 4000 字符门槛（粗估 <1024 tokens）"
    )

    has_cache = any(
        isinstance(b, dict)
        and b.get("cache_control", {}).get("type") == "ephemeral"
        for b in blocks
    )
    assert has_cache, "至少一个 system block 必须带 cache_control={'type':'ephemeral'}"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Action 输出通过 Pydantic 校验
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_analyze_cost_spike_returns_pydantic() -> None:
    """mock complete_with_cache 返回合成 JSON，断言 action 输出被正确解析 + Pydantic 校验。"""
    fake_router = AsyncMock()
    fake_router.complete_with_cache = AsyncMock(
        return_value=(_valid_llm_json(), _fake_usage()),
    )

    agent = CostRootCauseAgent(
        tenant_id=TENANT_ID,
        store_id=STORE_ID,
        model_router=fake_router,
    )

    result = await agent.run(
        action="analyze_cost_spike",
        params={
            "store_id": STORE_ID,
            "period": "2026-04",
            "baseline": {"food_cost_fen": 300000, "revenue_fen": 900000},
            "current": {"food_cost_fen": 370000, "revenue_fen": 1000000},
            "narrative": "本月水产有 3 次大量报废",
        },
    )

    assert result.success is True, f"action 执行应成功，error={result.error}"
    assert result.action == "analyze_cost_spike"
    # 结构化字段存在
    assert "root_causes" in result.data
    assert "recommendations" in result.data
    assert len(result.data["root_causes"]) == 2
    assert len(result.data["recommendations"]) == 2
    # 置信度被正确提取
    assert result.confidence == pytest.approx(0.82)

    # 再次用 Pydantic 模型复校（双保险）
    validated = CostRootCauseOutput(
        summary=result.data["summary"],
        root_causes=result.data["root_causes"],
        recommendations=result.data["recommendations"],
        confidence=result.confidence,
    )
    assert validated.root_causes[0].cause_code == "food_price_surge"
    assert validated.recommendations[0].estimated_saving_fen == 25000


# ─────────────────────────────────────────────────────────────────────────────
# 4. Cache hit ratio ≥ 0.75
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prompt_cache_hit_ratio_reports_75pct() -> None:
    """mock usage 返回 cache_read=3000, input_tokens=500 → ratio = 3000/3500 ≈ 0.857 > 0.75。"""
    fake_usage = _fake_usage(cache_read=3000, input_tokens=500)

    # Sanity check：构造的 usage 自身满足 > 0.75
    assert fake_usage["cache_hit_ratio"] > 0.75

    fake_router = AsyncMock()
    fake_router.complete_with_cache = AsyncMock(
        return_value=(_valid_llm_json(), fake_usage),
    )

    agent = CostRootCauseAgent(
        tenant_id=TENANT_ID,
        model_router=fake_router,
    )
    result = await agent.run(
        action="analyze_cost_spike",
        params={
            "store_id": STORE_ID,
            "period": "2026-04",
            "baseline": {"food_cost_fen": 300000, "revenue_fen": 900000},
            "current": {"food_cost_fen": 370000, "revenue_fen": 1000000},
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


# ─────────────────────────────────────────────────────────────────────────────
# 5. ModelRouter 调用参数校验
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_model_router_called_with_sonnet_4_7() -> None:
    """校验 ModelRouter.complete_with_cache 被调用时 task_type='cost_root_cause'。"""
    fake_router = AsyncMock()
    fake_router.complete_with_cache = AsyncMock(
        return_value=(_valid_llm_json(), _fake_usage()),
    )

    agent = CostRootCauseAgent(
        tenant_id=TENANT_ID,
        model_router=fake_router,
    )
    await agent.run(
        action="explain_margin_drop",
        params={
            "store_id": STORE_ID,
            "period": "2026-04",
            "baseline_margin": 0.14,
            "current_margin": 0.09,
            "revenue_breakdown": {"dine_in": 600000, "delivery": 400000},
            "cost_breakdown": {"food_cost": 370000, "labor_cost": 220000},
        },
    )

    fake_router.complete_with_cache.assert_awaited_once()
    kwargs = fake_router.complete_with_cache.await_args.kwargs
    assert kwargs["task_type"] == "cost_root_cause", (
        f"task_type 必须是 'cost_root_cause'（route 到 Sonnet 4.7），实际：{kwargs.get('task_type')}"
    )
    assert kwargs["tenant_id"] == TENANT_ID
    # 系统提示必须为 list[dict] 且至少一个块含 cache_control
    system_blocks = kwargs["system_blocks"]
    assert isinstance(system_blocks, list) and len(system_blocks) >= 1
    assert any(b.get("cache_control") for b in system_blocks)
    # messages 必须是用户查询
    messages = kwargs["messages"]
    assert messages[0]["role"] == "user"
    assert "毛利漂移" in messages[0]["content"] or "margin" in messages[0]["content"].lower()


# ─────────────────────────────────────────────────────────────────────────────
# 6. 代码质量：无 bare except Exception
# ─────────────────────────────────────────────────────────────────────────────


def test_no_broad_except() -> None:
    """ast 扫描 Skill 源文件，禁止 bare `except Exception`（§十四 审计修复期约束）。"""
    source_path = Path(__file__).resolve().parents[1] / "agents" / "skills" / "cost_root_cause.py"
    assert source_path.exists(), f"源文件不存在：{source_path}"

    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        exc_type = node.type
        # bare `except:` 也禁止
        assert exc_type is not None, (
            f"bare `except:` 在 cost_root_cause.py:{node.lineno} —— 必须声明具体异常类型"
        )
        # `except Exception:` / `except BaseException:` 不允许
        if isinstance(exc_type, ast.Name):
            assert exc_type.id not in ("Exception", "BaseException"), (
                f"broad `except {exc_type.id}:` 在 cost_root_cause.py:{node.lineno} —— "
                f"§十四 新代码禁止 except Exception"
            )
        if isinstance(exc_type, ast.Tuple):
            for elt in exc_type.elts:
                if isinstance(elt, ast.Name):
                    assert elt.id not in ("Exception", "BaseException"), (
                        f"broad `except (..., {elt.id}, ...):` 在 cost_root_cause.py:{node.lineno}"
                    )
