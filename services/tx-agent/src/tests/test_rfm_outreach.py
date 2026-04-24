"""Sprint D3a — RFM 触达 Skill Agent 集成测试（Tier 2 标准）

覆盖：
  - Skill 在 ALL_SKILL_AGENTS 已注册
  - scope == {"margin", "experience"}
  - build_cached_system_blocks() ≥ 4000 字符 且含 cache_control
  - mock ModelRouter.complete_with_cache 返回合成 JSON 后，action 输出通过 Pydantic 校验
  - ModelRouter 调用时 task_type="rfm_outreach" → 路由到 Haiku 4.5
  - cache hit ratio 正确透传
  - 决策日志 ROI improved_kpi 包含 repurchase_rate
  - 源文件无 `except Exception:` bare

运行：
  pytest services/tx-agent/src/tests/test_rfm_outreach.py -v
"""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

# 将 src 目录加入 path，与 test_cost_root_cause / test_model_router 一致
_SRC_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, _SRC_DIR)

from agents.skills import ALL_SKILL_AGENTS  # noqa: E402
from agents.skills.rfm_outreach import (  # noqa: E402
    OutreachCopyOutput,
    RfmOutreachAgent,
    TargetSegmentOutput,
)
from prompts.rfm_outreach import build_cached_system_blocks  # noqa: E402
from services.model_router import ModelSelectionStrategy  # noqa: E402

TENANT_ID = "11111111-1111-1111-1111-111111111111"
STORE_ID = "22222222-2222-2222-2222-222222222222"


def _valid_copy_json() -> str:
    """构造符合 OutreachCopyOutput schema 的合成 LLM 输出。"""
    payload = {
        "summary": "针对 RFM_155 流失高价值客户，生成 3 版情感化召回文案，推荐周四 17:30 推送。",
        "segment_code": "RFM_155",
        "scene": "recall",
        "push_time": "17:30",
        "versions": [
            {
                "version_code": "A",
                "style": "rational",
                "channel": "wechat_template",
                "title": "久未光顾，专属礼券到账",
                "body": "满 150 减 30 券已发放至您的会员账户，本周五 23:59 前有效。",
                "cta": "立即使用",
                "estimated_open_rate": 0.14,
                "estimated_click_rate": 0.06,
                "estimated_conversion_rate": 0.04,
            },
            {
                "version_code": "B",
                "style": "emotional",
                "channel": "wechat_template",
                "title": "好久不见啦",
                "body": "主厨惦记着老朋友的口味，新菜试吃券为您留着～",
                "cta": "看看新菜",
                "estimated_open_rate": 0.18,
                "estimated_click_rate": 0.08,
                "estimated_conversion_rate": 0.05,
            },
            {
                "version_code": "C",
                "style": "fomo",
                "channel": "wechat_template",
                "title": "限量回归礼今日截止",
                "body": "老客专属 88 折券仅剩 24 小时，本周内使用即赠甜品一份。",
                "cta": "领取",
                "estimated_open_rate": 0.16,
                "estimated_click_rate": 0.07,
                "estimated_conversion_rate": 0.05,
            },
        ],
        "compliance_check": {"forbidden_words_hit": [], "frequency_cap_ok": True},
        "confidence": 0.78,
    }
    return json.dumps(payload, ensure_ascii=False)


def _valid_segment_json() -> str:
    """构造符合 TargetSegmentOutput schema 的合成 LLM 输出。"""
    payload = {
        "summary": "选择 RFM_155 流失高价值客户作为复购率 +5pp 目标分群，预计触达 420 人。",
        "segment_code": "RFM_155",
        "segment_name": "流失高价值",
        "rfm_filter": {
            "recency_max_days": None,
            "recency_min_days": 45,
            "frequency_min_count": 6,
            "frequency_max_count": None,
            "monetary_min_fen": 60000,
            "monetary_max_fen": None,
        },
        "estimated_size": 420,
        "segment_rationale": "该群基数 3% 但客单价高，召回响应率显著高于均值，ROI 最优。",
        "expected_delta_pct": 5.0,
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


def test_rfm_outreach_registered() -> None:
    assert RfmOutreachAgent in ALL_SKILL_AGENTS, (
        "RfmOutreachAgent 必须在 services/tx-agent/src/agents/skills/__init__.py 的 "
        "ALL_SKILL_AGENTS 列表中注册"
    )


def test_scope_is_margin_and_experience() -> None:
    assert RfmOutreachAgent.constraint_scope == {"margin", "experience"}, (
        f"D3a RFM 触达必须声明 margin + experience 双 scope，"
        f"实际：{RfmOutreachAgent.constraint_scope}"
    )


def test_agent_metadata() -> None:
    """基础元信息快速检查。"""
    assert RfmOutreachAgent.agent_id == "rfm_outreach"
    assert RfmOutreachAgent.agent_level == 1  # Level 1：仅建议
    actions = RfmOutreachAgent(TENANT_ID).get_supported_actions()
    assert "generate_outreach_copy" in actions
    assert "select_target_segment" in actions


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
async def test_generate_outreach_copy_returns_pydantic() -> None:
    """mock complete_with_cache 返回合成 JSON，断言 generate_outreach_copy 输出被 Pydantic 校验。"""
    fake_router = AsyncMock()
    fake_router.complete_with_cache = AsyncMock(
        return_value=(_valid_copy_json(), _fake_usage()),
    )

    agent = RfmOutreachAgent(
        tenant_id=TENANT_ID,
        store_id=STORE_ID,
        model_router=fake_router,
    )

    result = await agent.run(
        action="generate_outreach_copy",
        params={
            "segment_code": "RFM_155",
            "scene": "recall",
            "channel": "wechat_template",
            "segment_size": 420,
            "avg_ticket_fen": 18000,
            "coupon_cap_fen": 5400,  # 18000 * 0.3
            "last_touch_days": 60,
            "narrative": "上次召回在 2 个月前，响应率偏低",
        },
    )

    assert result.success is True, f"action 执行应成功，error={result.error}"
    assert result.action == "generate_outreach_copy"
    # 结构化字段存在
    assert "versions" in result.data
    assert "push_time" in result.data
    assert len(result.data["versions"]) == 3
    # 置信度被正确提取
    assert result.confidence == pytest.approx(0.78)

    # 再次用 Pydantic 模型复校（双保险）
    validated = OutreachCopyOutput(
        summary=result.data["summary"],
        segment_code=result.data["segment_code"],
        scene=result.data["scene"],
        push_time=result.data["push_time"],
        versions=result.data["versions"],
        compliance_check=result.data["compliance_check"],
        confidence=result.confidence,
    )
    assert validated.versions[0].version_code == "A"
    assert validated.versions[1].style == "emotional"
    assert validated.push_time == "17:30"


@pytest.mark.asyncio
async def test_select_target_segment_returns_pydantic() -> None:
    """mock complete_with_cache 返回合成 JSON，断言 select_target_segment 输出被 Pydantic 校验。"""
    fake_router = AsyncMock()
    fake_router.complete_with_cache = AsyncMock(
        return_value=(_valid_segment_json(), _fake_usage()),
    )

    agent = RfmOutreachAgent(
        tenant_id=TENANT_ID,
        model_router=fake_router,
    )

    result = await agent.run(
        action="select_target_segment",
        params={
            "business_goal": "复购率提升 5pp",
            "target_delta_pct": 5.0,
            "target_metric": "repurchase_rate",
            "total_member_count": 12000,
            "budget_fen": 50000,
        },
    )

    assert result.success is True, f"action 执行应成功，error={result.error}"
    assert result.action == "select_target_segment"
    assert result.data["segment_code"] == "RFM_155"
    assert result.data["estimated_size"] == 420
    assert result.data["expected_delta_pct"] == pytest.approx(5.0)

    # 再次 Pydantic 复校
    validated = TargetSegmentOutput(
        summary=result.data["summary"],
        segment_code=result.data["segment_code"],
        segment_name=result.data["segment_name"],
        rfm_filter=result.data["rfm_filter"],
        estimated_size=result.data["estimated_size"],
        segment_rationale=result.data["segment_rationale"],
        expected_delta_pct=result.data["expected_delta_pct"],
        confidence=result.confidence,
    )
    assert validated.rfm_filter.monetary_min_fen == 60000
    assert validated.rfm_filter.frequency_min_count == 6


# ─────────────────────────────────────────────────────────────────────────────
# 4. Haiku 4.5 模型路由
# ─────────────────────────────────────────────────────────────────────────────


def test_model_router_maps_rfm_outreach_to_haiku_4_5() -> None:
    """ModelSelectionStrategy 必须把 rfm_outreach 路由到 claude-haiku-4-5-20251001。"""
    strategy = ModelSelectionStrategy()
    model = strategy.select_model("rfm_outreach")
    assert model == "claude-haiku-4-5-20251001", (
        f"rfm_outreach 应路由到 Haiku 4.5，实际：{model}"
    )


@pytest.mark.asyncio
async def test_model_router_called_with_haiku_4_5() -> None:
    """校验 ModelRouter.complete_with_cache 被调用时 task_type='rfm_outreach'。"""
    fake_router = AsyncMock()
    fake_router.complete_with_cache = AsyncMock(
        return_value=(_valid_copy_json(), _fake_usage()),
    )

    agent = RfmOutreachAgent(
        tenant_id=TENANT_ID,
        model_router=fake_router,
    )
    await agent.run(
        action="generate_outreach_copy",
        params={
            "segment_code": "RFM_155",
            "scene": "recall",
            "channel": "wechat_template",
        },
    )

    fake_router.complete_with_cache.assert_awaited_once()
    kwargs = fake_router.complete_with_cache.await_args.kwargs
    assert kwargs["task_type"] == "rfm_outreach", (
        f"task_type 必须是 'rfm_outreach'（路由到 Haiku 4.5），"
        f"实际：{kwargs.get('task_type')}"
    )
    assert kwargs["tenant_id"] == TENANT_ID
    # 系统提示必须为 list[dict] 且至少一个块含 cache_control
    system_blocks = kwargs["system_blocks"]
    assert isinstance(system_blocks, list) and len(system_blocks) >= 1
    assert any(b.get("cache_control") for b in system_blocks)
    # messages 必须是用户查询
    messages = kwargs["messages"]
    assert messages[0]["role"] == "user"
    assert "RFM_155" in messages[0]["content"] or "触达" in messages[0]["content"]


# ─────────────────────────────────────────────────────────────────────────────
# 5. Cache hit ratio 透传
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prompt_cache_hit_ratio_reports_correctly() -> None:
    """mock usage 返回 cache_read=3000, input_tokens=500 → ratio ≈ 0.857 > 0.75，且透传到 result.data.usage。"""
    fake_usage = _fake_usage(cache_read=3000, input_tokens=500)
    assert fake_usage["cache_hit_ratio"] > 0.75

    fake_router = AsyncMock()
    fake_router.complete_with_cache = AsyncMock(
        return_value=(_valid_copy_json(), fake_usage),
    )

    agent = RfmOutreachAgent(
        tenant_id=TENANT_ID,
        model_router=fake_router,
    )
    result = await agent.run(
        action="generate_outreach_copy",
        params={
            "segment_code": "RFM_155",
            "scene": "recall",
            "channel": "wechat_template",
        },
    )

    assert result.success is True
    usage = result.data["usage"]
    assert usage["cache_read_input_tokens"] == 3000
    assert usage["input_tokens"] == 500
    assert usage["cache_hit_ratio"] > 0.75, (
        f"cache_hit_ratio={usage['cache_hit_ratio']} 应 > 0.75（Anthropic 推荐阈值）"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 6. 决策日志 ROI 包含 repurchase_rate
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_decision_log_records_improved_kpi_repurchase_rate() -> None:
    """ROI 字段 improved_kpi.metric == 'repurchase_rate'，delta_pct > 0。"""
    fake_router = AsyncMock()
    fake_router.complete_with_cache = AsyncMock(
        return_value=(_valid_segment_json(), _fake_usage()),
    )

    agent = RfmOutreachAgent(
        tenant_id=TENANT_ID,
        model_router=fake_router,
    )
    result = await agent.run(
        action="select_target_segment",
        params={
            "business_goal": "复购率提升 5pp",
            "target_delta_pct": 5.0,
            "target_metric": "repurchase_rate",
        },
    )

    assert result.success is True
    roi = result.data["roi"]
    assert roi is not None
    improved_kpi = roi["improved_kpi"]
    assert improved_kpi["metric"] == "repurchase_rate", (
        f"D3a 触达必须回写 repurchase_rate 为 improved_kpi.metric，"
        f"实际：{improved_kpi.get('metric')}"
    )
    assert improved_kpi["delta_pct"] > 0
    # 触达不防损，prevented_loss_fen 应为 None
    assert roi["prevented_loss_fen"] is None
    # roi_evidence 必含模型和 cache_hit_ratio
    assert "model" in roi["roi_evidence"]
    assert "cache_hit_ratio" in roi["roi_evidence"]


# ─────────────────────────────────────────────────────────────────────────────
# 7. 代码质量：无 bare except Exception
# ─────────────────────────────────────────────────────────────────────────────


def test_no_broad_except() -> None:
    """ast 扫描 Skill 源文件，禁止 bare `except Exception`（§十四 审计修复期约束）。"""
    source_path = Path(__file__).resolve().parents[1] / "agents" / "skills" / "rfm_outreach.py"
    assert source_path.exists(), f"源文件不存在：{source_path}"

    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        exc_type = node.type
        # bare `except:` 也禁止
        assert exc_type is not None, (
            f"bare `except:` 在 rfm_outreach.py:{node.lineno} —— 必须声明具体异常类型"
        )
        # `except Exception:` / `except BaseException:` 不允许
        if isinstance(exc_type, ast.Name):
            assert exc_type.id not in ("Exception", "BaseException"), (
                f"broad `except {exc_type.id}:` 在 rfm_outreach.py:{node.lineno} —— "
                f"§十四 新代码禁止 except Exception"
            )
        if isinstance(exc_type, ast.Tuple):
            for elt in exc_type.elts:
                if isinstance(elt, ast.Name):
                    assert elt.id not in ("Exception", "BaseException"), (
                        f"broad `except (..., {elt.id}, ...):` 在 rfm_outreach.py:{node.lineno}"
                    )
