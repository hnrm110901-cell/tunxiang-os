"""test_constraint_context.py —— Sprint D1 / PR G

覆盖：
  1. ConstraintContext 基础字段 + from_data 旧字典兼容路径
  2. ConstraintChecker.check_all 双入参（context / dict）
  3. scope 过滤：只校验指定子集，其余不进 scopes_checked / scopes_skipped
  4. 迁移期 base.py::run 默认 scope = {margin,safety,experience}，ctx 缺字段 → scope='n/a'
  5. Skill 类级 constraint_scope = set() → constraints_detail.scope == 'waived'
  6. 批次 1 三个 Skill 声明的 scope 符合设计
  7. SKILL_REGISTRY 至少包含批次 1 三个 agent_id，且无 agent_id 冲突
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base import AgentResult, SkillAgent
from agents.constraints import ConstraintChecker
from agents.context import ConstraintContext, IngredientSnapshot

# ──────────────────────────────────────────────────────────────────────
# 1. ConstraintContext
# ──────────────────────────────────────────────────────────────────────

def test_context_defaults_full_scope():
    ctx = ConstraintContext()
    assert ctx.constraint_scope == {"margin", "safety", "experience"}
    assert ctx.price_fen is None
    assert ctx.waived_reason is None


def test_context_from_data_maps_legacy_fields():
    data = {
        "price_fen": 8800,
        "cost_fen": 3500,
        "ingredients": [
            {"name": "鱼头", "remaining_hours": 12.5, "batch_id": "B-001"},
            {"name": "辣椒", "remaining_hours": None},
        ],
        "estimated_serve_minutes": 25.0,
    }
    ctx = ConstraintContext.from_data(data)
    assert ctx.price_fen == 8800
    assert ctx.cost_fen == 3500
    assert ctx.estimated_serve_minutes == 25.0
    assert len(ctx.ingredients) == 2
    assert ctx.ingredients[0].name == "鱼头"
    assert ctx.ingredients[0].batch_id == "B-001"


def test_context_from_data_handles_final_amount_alias():
    ctx = ConstraintContext.from_data({"final_amount_fen": 5000, "food_cost_fen": 2500})
    assert ctx.price_fen == 5000
    assert ctx.cost_fen == 2500


# ──────────────────────────────────────────────────────────────────────
# 2. check_all 双入参
# ──────────────────────────────────────────────────────────────────────

def test_check_all_accepts_dict_and_context_equivalently():
    checker = ConstraintChecker()
    data = {"price_fen": 10000, "cost_fen": 5000}
    r1 = checker.check_all(data)
    r2 = checker.check_all(ConstraintContext.from_data(data))
    assert r1.passed == r2.passed
    assert r1.margin_check == r2.margin_check


def test_check_all_rejects_bad_input_type():
    with pytest.raises(TypeError, match="ConstraintContext"):
        ConstraintChecker().check_all(123)  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────────
# 3. scope 过滤
# ──────────────────────────────────────────────────────────────────────

def test_scope_filter_only_checks_declared_subset():
    checker = ConstraintChecker()
    ctx = ConstraintContext(
        price_fen=10000,
        cost_fen=5000,
        estimated_serve_minutes=25,
        ingredients=[IngredientSnapshot(name="鱼头", remaining_hours=12)],
    )
    # 只校验 margin：其他两条即使有数据也不进 checked/skipped
    r = checker.check_all(ctx, scope={"margin"})
    assert "margin" in r.scopes_checked
    assert "safety" not in r.scopes_checked and "safety" not in r.scopes_skipped
    assert "experience" not in r.scopes_checked and "experience" not in r.scopes_skipped


def test_scope_filter_empty_set_skips_all():
    checker = ConstraintChecker()
    ctx = ConstraintContext(price_fen=10000, cost_fen=5000)
    r = checker.check_all(ctx, scope=set())
    assert r.passed is True
    assert r.scopes_checked == []
    assert r.scopes_skipped == []


def test_scope_skipped_when_data_missing():
    checker = ConstraintChecker()
    ctx = ConstraintContext()  # 全空
    r = checker.check_all(ctx, scope={"margin", "safety", "experience"})
    assert r.scopes_checked == []
    assert set(r.scopes_skipped) == {"margin", "safety", "experience"}


# ──────────────────────────────────────────────────────────────────────
# 4. base.py::run 流程（skill → constraints_detail.scope）
# ──────────────────────────────────────────────────────────────────────

class _NAStubSkill(SkillAgent):
    """声明需要校验但不提供任何数据 —— 应被标 scope='n/a'"""
    agent_id = "na_stub"
    constraint_scope = {"margin", "safety", "experience"}

    async def execute(self, action, params):
        return AgentResult(success=True, action=action, data={})

    def get_supported_actions(self):
        return ["noop"]


@pytest.mark.asyncio
async def test_run_marks_na_when_declared_but_no_data():
    skill = _NAStubSkill(tenant_id="t1")
    result = await skill.run("noop", {})
    assert result.constraints_detail["scope"] == "n/a"
    assert set(result.constraints_detail["scopes_skipped"]) == {"margin", "safety", "experience"}


class _SingleScopeSkill(SkillAgent):
    agent_id = "single_stub"
    constraint_scope = {"margin"}

    async def execute(self, action, params):
        return AgentResult(
            success=True,
            action=action,
            data={},
            context=ConstraintContext(price_fen=10000, cost_fen=5000, constraint_scope={"margin"}),
        )

    def get_supported_actions(self):
        return ["noop"]


@pytest.mark.asyncio
async def test_run_single_scope_is_labeled():
    skill = _SingleScopeSkill(tenant_id="t1")
    result = await skill.run("noop", {})
    assert result.constraints_detail["scope"] == "margin"
    assert result.constraints_passed is True


class _WaivedSkill(SkillAgent):
    agent_id = "waived_stub"
    constraint_scope = set()
    constraint_waived_reason = (
        "纯数据汇总 Skill，不触发业务决策；毛利/食安/体验维度均不适用，仅用于报表生成"
    )

    async def execute(self, action, params):
        return AgentResult(success=True, action=action, data={})

    def get_supported_actions(self):
        return ["noop"]


@pytest.mark.asyncio
async def test_run_waived_skill_has_waived_scope():
    skill = _WaivedSkill(tenant_id="t1")
    result = await skill.run("noop", {})
    assert result.constraints_detail["scope"] == "waived"
    assert result.constraints_detail["waived_reason"].startswith("纯数据汇总")
    assert result.constraints_passed is True


# ──────────────────────────────────────────────────────────────────────
# 5. 批次 1 三个 Skill 的 scope 声明 + SKILL_REGISTRY
#
# 注：这些测试依赖 `agents.skills` 包能被导入。tx-agent 存在 pre-existing
# `edge_mixin` 相对导入 bug（`from ..services.edge_inference_client` 路径错误），
# 本地 pytest 直跑 `src/tests` 会卡在此处；但在真实 CI 容器里（PYTHONPATH 正确
# 配置为 /app，__init__.py 可达）可以通过。本 PR 不修 edge_mixin（属 out-of-scope），
# 而用 importorskip 保证"有环境时强校验、无环境时不挂"。
# ──────────────────────────────────────────────────────────────────────


def _import_skills_or_skip():
    """尝试导入 agents.skills 包；失败则 skip（pre-existing edge_mixin bug 兼容）。"""
    try:
        import agents.skills as skills_pkg  # noqa: F401
        return skills_pkg
    except ImportError as exc:
        pytest.skip(f"agents.skills 无法导入（pre-existing edge_mixin bug）: {exc}")


def test_batch_1_skills_declare_correct_scopes():
    skills_pkg = _import_skills_or_skip()
    from agents.skills.closing_agent import ClosingAgent
    from agents.skills.growth_attribution import GrowthAttributionAgent
    from agents.skills.stockout_alert import StockoutAlertAgent

    assert GrowthAttributionAgent.constraint_scope == {"margin"}
    assert ClosingAgent.constraint_scope == {"margin", "safety"}
    assert StockoutAlertAgent.constraint_scope == {"margin", "safety"}
    # 引用使用以避免未使用变量警告
    assert hasattr(skills_pkg, "SKILL_REGISTRY")


def test_skill_registry_contains_batch_1_skills():
    _import_skills_or_skip()
    from agents.skills import SKILL_REGISTRY

    assert "growth_attribution" in SKILL_REGISTRY
    assert "closing_ops" in SKILL_REGISTRY
    assert "stockout_alert" in SKILL_REGISTRY


def test_skill_registry_keys_match_agent_ids():
    _import_skills_or_skip()
    from agents.skills import SKILL_REGISTRY

    for agent_id, cls in SKILL_REGISTRY.items():
        assert cls.agent_id == agent_id, f"{cls.__name__}.agent_id={cls.agent_id} 但注册为 {agent_id}"


def test_skill_registry_has_no_duplicate_agent_ids():
    _import_skills_or_skip()
    from agents.skills import ALL_SKILL_AGENTS, SKILL_REGISTRY

    seen: set[str] = set()
    for cls in ALL_SKILL_AGENTS:
        aid = getattr(cls, "agent_id", None)
        if not aid or aid == "base":
            continue
        assert aid not in seen, f"agent_id 冲突: {aid}"
        seen.add(aid)
    assert seen <= set(SKILL_REGISTRY.keys())
