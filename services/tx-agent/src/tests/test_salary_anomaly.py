"""Sprint D4b — 薪资异常 Skill Agent 集成测试（Tier 2 标准）

覆盖：
  - Skill 在 ALL_SKILL_AGENTS 已注册
  - scope == {"margin"}
  - build_cached_system_blocks() ≥ 4000 字符 且含 cache_control
  - mock ModelRouter.complete_with_cache 返回合成 JSON 后，两个 action 输出通过 Pydantic 校验
  - mock usage 返回 cache_read=3000/input=500，cache_hit_ratio > 0.75 被正确解析
  - ModelRouter 调用时 task_type="salary_anomaly"（路由到 Sonnet 4.7）
  - DecisionLogService.log_skill_result 被调用时 roi.prevented_loss_fen 写入
  - 源文件无 `except Exception:` bare

运行：
  pytest services/tx-agent/src/tests/test_salary_anomaly.py -v
"""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# 将 src 目录加入 path，与 test_cost_root_cause.py 一致
_SRC_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, _SRC_DIR)

from agents.skills import ALL_SKILL_AGENTS, SKILL_REGISTRY  # noqa: E402
from agents.skills.salary_anomaly import (  # noqa: E402
    SalaryAnomalyAgent,
    SalaryAnomalyOutput,
)
from prompts.salary_anomaly import build_cached_system_blocks  # noqa: E402

TENANT_ID = "11111111-1111-1111-1111-111111111111"
STORE_ID = "22222222-2222-2222-2222-222222222222"


def _valid_llm_json() -> str:
    """构造符合 Pydantic schema 的合成 LLM 输出。"""
    payload = {
        "summary": "本月识别 2 名员工加班超法规上限，1 名员工薪资环比涨 42% 无晋升记录。",
        "anomalies": [
            {
                "anomaly_code": "overtime_hard_red_line",
                "anomaly_label": "加班超 36h 红线",
                "employee_id": "E-2041",
                "category": "overtime",
                "impact_fen": 82000,
                "evidence": "2026-04 加班 52h，超 36h 上限 16h，其中 4-05 至 4-12 连续 8 天未休。",
                "severity": "critical",
            },
            {
                "anomaly_code": "employee_spike",
                "anomaly_label": "薪资环比异常上涨",
                "employee_id": "E-3172",
                "category": "payroll_variance",
                "impact_fen": 120000,
                "evidence": "gross_fen 6200→8800，涨幅 42%，无晋升流水记录。",
                "severity": "high",
            },
        ],
        "suspect_employee_ids": ["E-2041", "E-3172"],
        "recommendations": [
            {
                "action": "拦截 E-2041 当月加班费多发部分",
                "responsible_role": "财务",
                "verification_kpi": "overtime_hours ≤ 36",
                "deadline_days": 3,
                "risk_flag": "none",
                "prevented_loss_fen": 45000,
            },
            {
                "action": "复核 E-3172 晋升流程缺失原因",
                "responsible_role": "HRD",
                "verification_kpi": "薪资调整单齐全",
                "deadline_days": 5,
                "risk_flag": "none",
                "prevented_loss_fen": 60000,
            },
        ],
        "confidence": 0.86,
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
    assert SalaryAnomalyAgent in ALL_SKILL_AGENTS, (
        "SalaryAnomalyAgent 必须在 services/tx-agent/src/agents/skills/__init__.py 的 ALL_SKILL_AGENTS 列表中注册"
    )
    assert "salary_anomaly" in SKILL_REGISTRY, "salary_anomaly agent_id 必须出现在 SKILL_REGISTRY 映射中"
    assert SKILL_REGISTRY["salary_anomaly"] is SalaryAnomalyAgent


def test_scope_is_margin() -> None:
    assert SalaryAnomalyAgent.constraint_scope == {"margin"}, (
        f"D4b 薪资异常必须且只声明 margin scope（人力成本率 → 毛利底线），实际：{SalaryAnomalyAgent.constraint_scope}"
    )


def test_agent_metadata() -> None:
    """基础元信息快速检查。"""
    assert SalaryAnomalyAgent.agent_id == "salary_anomaly"
    assert SalaryAnomalyAgent.agent_level == 1  # Level 1：仅建议
    actions = SalaryAnomalyAgent(TENANT_ID).get_supported_actions()
    assert "detect_overtime_anomaly" in actions
    assert "detect_payroll_variance" in actions


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
async def test_detect_overtime_anomaly_returns_pydantic() -> None:
    """mock complete_with_cache 返回合成 JSON，断言 action 输出被正确解析 + Pydantic 校验。"""
    fake_router = AsyncMock()
    fake_router.complete_with_cache = AsyncMock(
        return_value=(_valid_llm_json(), _fake_usage()),
    )

    agent = SalaryAnomalyAgent(
        tenant_id=TENANT_ID,
        store_id=STORE_ID,
        model_router=fake_router,
    )

    result = await agent.run(
        action="detect_overtime_anomaly",
        params={
            "store_id": STORE_ID,
            "period": "2026-04",
            "attendance_summary": {
                "E-2041": {"overtime_hours": 52, "continuous_days": 8},
                "E-3172": {"overtime_hours": 28, "continuous_days": 5},
            },
            "role_baseline": {"server": {"p90_overtime": 32}},
            "revenue_trend": {"mom_pct": -0.05},
            "narrative": "本月春节高峰连续作战较多",
        },
    )

    assert result.success is True, f"action 执行应成功，error={result.error}"
    assert result.action == "detect_overtime_anomaly"
    # 结构化字段存在
    assert "anomalies" in result.data
    assert "suspect_employee_ids" in result.data
    assert "recommendations" in result.data
    assert len(result.data["anomalies"]) == 2
    assert len(result.data["suspect_employee_ids"]) == 2
    assert len(result.data["recommendations"]) == 2
    # 置信度被正确提取
    assert result.confidence == pytest.approx(0.86)

    # 再次用 Pydantic 模型复校（双保险）
    validated = SalaryAnomalyOutput(
        summary=result.data["summary"],
        anomalies=result.data["anomalies"],
        suspect_employee_ids=result.data["suspect_employee_ids"],
        recommendations=result.data["recommendations"],
        confidence=result.confidence,
    )
    assert validated.anomalies[0].anomaly_code == "overtime_hard_red_line"
    assert validated.anomalies[0].severity == "critical"
    assert validated.recommendations[0].prevented_loss_fen == 45000


@pytest.mark.asyncio
async def test_detect_payroll_variance_returns_pydantic() -> None:
    """第二个 action 也能走通 Pydantic 校验路径。"""
    fake_router = AsyncMock()
    fake_router.complete_with_cache = AsyncMock(
        return_value=(_valid_llm_json(), _fake_usage()),
    )

    agent = SalaryAnomalyAgent(
        tenant_id=TENANT_ID,
        store_id=STORE_ID,
        model_router=fake_router,
    )

    result = await agent.run(
        action="detect_payroll_variance",
        params={
            "store_id": STORE_ID,
            "period": "2026-04",
            "current_payroll": {"E-3172": {"gross_fen": 880000, "base_fen": 350000}},
            "baseline_payroll": {"E-3172": {"gross_fen_avg3m": 620000}},
            "role_salary_band": {"chef": [600000, 1500000]},
            "local_min_wage_fen": 193000,  # 长沙 2025 最低工资 1930 元 → 193000 分
        },
    )

    assert result.success is True, f"action 执行应成功，error={result.error}"
    assert result.action == "detect_payroll_variance"
    assert len(result.data["anomalies"]) == 2
    # 第二个异常是 employee_spike
    assert result.data["anomalies"][1]["anomaly_code"] == "employee_spike"
    assert result.data["anomalies"][1]["employee_id"] == "E-3172"


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
        return_value=(_valid_llm_json(), fake_usage),
    )

    agent = SalaryAnomalyAgent(
        tenant_id=TENANT_ID,
        model_router=fake_router,
    )
    result = await agent.run(
        action="detect_overtime_anomaly",
        params={
            "store_id": STORE_ID,
            "period": "2026-04",
            "attendance_summary": {},
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
# 5. ModelRouter 调用参数校验（task_type="salary_anomaly" → Sonnet 4.7）
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_model_router_called_with_sonnet_4_7() -> None:
    """校验 ModelRouter.complete_with_cache 被调用时 task_type='salary_anomaly'。"""
    fake_router = AsyncMock()
    fake_router.complete_with_cache = AsyncMock(
        return_value=(_valid_llm_json(), _fake_usage()),
    )

    agent = SalaryAnomalyAgent(
        tenant_id=TENANT_ID,
        model_router=fake_router,
    )
    await agent.run(
        action="detect_payroll_variance",
        params={
            "store_id": STORE_ID,
            "period": "2026-04",
            "current_payroll": {"E-1": {"gross_fen": 500000}},
            "baseline_payroll": {"E-1": {"gross_fen_avg3m": 500000}},
        },
    )

    fake_router.complete_with_cache.assert_awaited_once()
    kwargs = fake_router.complete_with_cache.await_args.kwargs
    assert kwargs["task_type"] == "salary_anomaly", (
        f"task_type 必须是 'salary_anomaly'（route 到 Sonnet 4.7），实际：{kwargs.get('task_type')}"
    )
    assert kwargs["tenant_id"] == TENANT_ID
    # 系统提示必须为 list[dict] 且至少一个块含 cache_control
    system_blocks = kwargs["system_blocks"]
    assert isinstance(system_blocks, list) and len(system_blocks) >= 1
    assert any(b.get("cache_control") for b in system_blocks)
    # messages 必须是用户查询
    messages = kwargs["messages"]
    assert messages[0]["role"] == "user"
    assert "薪资" in messages[0]["content"] or "payroll" in messages[0]["content"].lower()


# ─────────────────────────────────────────────────────────────────────────────
# 6. 决策留痕：roi.prevented_loss_fen 写入
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_decision_log_records_prevented_loss_fen() -> None:
    """ROI 四字段在 result.data 中正确计算：

    - prevented_loss_fen = Σ recommendations.prevented_loss_fen = 45000 + 60000 = 105000
    - improved_kpi.metric = "labor_cost_ratio"
    - saved_labor_hours = 2.0（HR 稽核门店省下的手工时间）
    - roi_evidence.model = claude-sonnet-4-7-20250929

    留痕路径（DecisionLogService.log_skill_result）在 DB=None 时静默跳过；
    DB 可用时通过 _write_decision_log() 调用。本测试聚焦"ROI 计算结果"—— 这是
    留痕链路的唯一真实载体（DecisionLogService 只是把它落 DB）。
    """
    fake_router = AsyncMock()
    fake_router.complete_with_cache = AsyncMock(
        return_value=(_valid_llm_json(), _fake_usage()),
    )

    # 监听 _write_decision_log 被调用（即使 DB=None 它也会被调用，然后内部 early-return）
    with patch.object(SalaryAnomalyAgent, "_write_decision_log", new_callable=AsyncMock) as mock_write:
        agent = SalaryAnomalyAgent(
            tenant_id=TENANT_ID,
            store_id=STORE_ID,
            model_router=fake_router,
        )
        result = await agent.run(
            action="detect_overtime_anomaly",
            params={
                "store_id": STORE_ID,
                "period": "2026-04",
                "attendance_summary": {"E-2041": {"overtime_hours": 52}},
            },
        )

        assert result.success is True
        # _write_decision_log 应恰好被调一次
        assert mock_write.await_count == 1, f"_write_decision_log 应恰好被调用 1 次，实际 {mock_write.await_count} 次"
        # 传入的 roi（kwargs）含 prevented_loss_fen = 45000 + 60000 = 105000
        call_kwargs = mock_write.await_args.kwargs
        roi = call_kwargs["roi"]
        assert roi["prevented_loss_fen"] == 105000, (
            f"roi.prevented_loss_fen 应 = 45000 + 60000 = 105000，实际 {roi['prevented_loss_fen']}"
        )
        # improved_kpi 写入 labor_cost_ratio
        assert roi["improved_kpi"]["metric"] == "labor_cost_ratio"
        # saved_labor_hours 固定 2.0
        assert roi["saved_labor_hours"] == 2.0
        # 模型记录
        assert roi["roi_evidence"]["model"] == "claude-sonnet-4-7-20250929"

    # 再检一次 result.data.roi（双保险：LLM 返回的 recommendations 合计 ROI 应一致）
    assert result.data["roi"]["prevented_loss_fen"] == 105000
    assert result.data["roi"]["improved_kpi"]["metric"] == "labor_cost_ratio"


# ─────────────────────────────────────────────────────────────────────────────
# 7. 代码质量：无 bare except Exception
# ─────────────────────────────────────────────────────────────────────────────


def test_no_broad_except() -> None:
    """ast 扫描 Skill 源文件，禁止 bare `except Exception`（§十四 审计修复期约束）。"""
    source_path = Path(__file__).resolve().parents[1] / "agents" / "skills" / "salary_anomaly.py"
    assert source_path.exists(), f"源文件不存在：{source_path}"

    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        exc_type = node.type
        # bare `except:` 也禁止
        assert exc_type is not None, f"bare `except:` 在 salary_anomaly.py:{node.lineno} —— 必须声明具体异常类型"
        # `except Exception:` / `except BaseException:` 不允许
        if isinstance(exc_type, ast.Name):
            assert exc_type.id not in ("Exception", "BaseException"), (
                f"broad `except {exc_type.id}:` 在 salary_anomaly.py:{node.lineno} —— §十四 新代码禁止 except Exception"
            )
        if isinstance(exc_type, ast.Tuple):
            for elt in exc_type.elts:
                if isinstance(elt, ast.Name):
                    assert elt.id not in ("Exception", "BaseException"), (
                        f"broad `except (..., {elt.id}, ...):` 在 salary_anomaly.py:{node.lineno}"
                    )
