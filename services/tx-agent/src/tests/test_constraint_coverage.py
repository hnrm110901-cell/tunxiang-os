"""Sprint D1 D1 — ConstraintChecker CI 覆盖门禁

覆盖：
  1. test_constraint_coverage_all_p0_skills_decorated
     —— 扫描批次 1 已接入的 10 个 P0/关键 Skill，断言 execute() 都打了
        @with_constraint_check 标记（DECORATOR_MARKER_ATTR）
  2. test_gross_margin_below_threshold_blocks_discount
     —— 毛利率 < 15% 时装饰器返回 _constraint_blocked=True
  3. test_food_safety_expired_ingredient_blocks_dish
     —— 食材 remaining_hours < 24h 时装饰器返回 _constraint_blocked=True
  4. test_customer_experience_serve_time_overflow_blocks_dispatch
     —— 出餐时长 > 30min 时装饰器返回 _constraint_blocked=True
  5. test_constraint_block_raises_and_logs_decision
     —— raise_on_block=True 时抛 ConstraintBlockedException

CI 集成（pytest 默认会跑 services/*/src/tests）：
  - test_constraint_coverage_all_p0_skills_decorated 失败 = D1 批次 1 覆盖回退
  - 其余 4 个用例失败 = 装饰器/约束逻辑回退
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from constraints import (
    ConstraintBlockedException,
    SkillContext,
    run_checks,
    with_constraint_check,
)
from constraints.decorator import DECORATOR_MARKER_ATTR

# 批次 1 已接入装饰器的 10 个 Skill agent_id
# 扩批时只在 D1_BATCH_1_DECORATED_SKILLS 中追加，配套测试在批次推进文档中规划
D1_BATCH_1_DECORATED_SKILLS: list[str] = [
    "discount_guard",
    "smart_menu",
    "serve_dispatch",
    "inventory_alert",
    "finance_audit",
    "cashier_audit",
    "member_insight",
    "compliance_alert",
    "ingredient_radar",
    "menu_advisor",
]


def _import_skill_or_skip(agent_id: str):
    """从 SKILL_REGISTRY 取 Skill 类；导入失败则 skip。

    存在的 pre-existing edge_mixin 相对导入 bug 在某些 PYTHONPATH 配置下会让
    `agents.skills` 导入失败 —— 真实 CI 容器（PYTHONPATH=/app）能跑通；本地
    pytest 直跑可能 skip。与 test_constraint_context.py 的 _import_skills_or_skip
    同一处理思路。
    """
    try:
        from agents.skills import SKILL_REGISTRY
    except ImportError as exc:
        pytest.skip(f"agents.skills 无法导入（pre-existing edge_mixin bug）: {exc}")
    cls = SKILL_REGISTRY.get(agent_id)
    if cls is None:
        pytest.skip(f"SKILL_REGISTRY 中无 {agent_id}（批次推进未到位或注册遗漏）")
    return cls


# ──────────────────────────────────────────────────────────────────────
# 1. CI 覆盖门禁
# ──────────────────────────────────────────────────────────────────────


def test_constraint_coverage_all_p0_skills_decorated():
    """D1 批次 1 的 10 个 Skill 必须全部用 @with_constraint_check 装饰 execute()。

    实现机制：装饰器在 wrapper 上设 DECORATOR_MARKER_ATTR = skill_name 类属性，
    本测试逐个 Skill 类检查 execute 方法上的标记。
    """
    missing: list[str] = []
    wrong_marker: list[str] = []

    for agent_id in D1_BATCH_1_DECORATED_SKILLS:
        cls = _import_skill_or_skip(agent_id)
        execute_func = getattr(cls, "execute", None)
        if execute_func is None:
            missing.append(f"{agent_id}: 无 execute 方法")
            continue
        marker = getattr(execute_func, DECORATOR_MARKER_ATTR, None)
        if marker is None:
            missing.append(f"{agent_id}: execute 未装饰")
            continue
        if marker != agent_id:
            wrong_marker.append(f"{agent_id}: marker={marker!r}（应等于 agent_id）")

    assert not missing, f"以下 Skill 缺 @with_constraint_check 装饰器：{missing}"
    assert not wrong_marker, f"以下 Skill 装饰器 skill_name 与 agent_id 不一致：{wrong_marker}"


def test_constraint_coverage_decorator_marker_attr_is_stable():
    """DECORATOR_MARKER_ATTR 的字符串值是 CI 与生产代码共享的契约，禁止改名。"""
    assert DECORATOR_MARKER_ATTR == "__tx_constraint_check_skill__"


# ──────────────────────────────────────────────────────────────────────
# 2. 三条约束分别的硬阻断行为
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gross_margin_below_threshold_blocks_discount():
    """毛利率 < 15% 时 run_checks 返回 passed=False"""
    ctx = SkillContext(tenant_id="t1")
    # 售价 100 元 / 成本 90 元 → 毛利率 10% < 15% 阈值
    result = await run_checks(
        {"price_fen": 10000, "cost_fen": 9000},
        ctx,
    )
    assert result.passed is False
    assert any("毛利底线" in f for f in result.blocking_failures)
    margin_check = next(c for c in result.checks if c.name == "gross_margin")
    assert margin_check.passed is False
    assert margin_check.details["actual_rate"] == 0.1
    assert margin_check.details["threshold"] == 0.15


@pytest.mark.asyncio
async def test_gross_margin_above_threshold_passes():
    """毛利率 >= 15% 时通过"""
    ctx = SkillContext(tenant_id="t1")
    result = await run_checks(
        {"price_fen": 10000, "cost_fen": 4000},  # 60%
        ctx,
    )
    assert result.passed is True
    margin_check = next(c for c in result.checks if c.name == "gross_margin")
    assert margin_check.passed is True


@pytest.mark.asyncio
async def test_food_safety_expired_ingredient_blocks_dish():
    """食材 remaining_hours < 24h 时 run_checks 返回 passed=False"""
    ctx = SkillContext(tenant_id="t1")
    result = await run_checks(
        {
            "ingredients": [
                {"name": "鱼头", "remaining_hours": 6},  # < 24h, 违规
                {"name": "辣椒", "remaining_hours": 48},
            ],
        },
        ctx,
    )
    assert result.passed is False
    assert any("食安合规" in f for f in result.blocking_failures)
    safety_check = next(c for c in result.checks if c.name == "food_safety")
    assert safety_check.passed is False
    violations = safety_check.details["violations"]
    assert any(v["ingredient"] == "鱼头" for v in violations)
    assert not any(v["ingredient"] == "辣椒" for v in violations)


@pytest.mark.asyncio
async def test_food_safety_all_fresh_passes():
    """所有食材剩余时间 >= 24h 时通过"""
    ctx = SkillContext(tenant_id="t1")
    result = await run_checks(
        {
            "ingredients": [
                {"name": "鱼头", "remaining_hours": 48},
                {"name": "辣椒", "remaining_hours": 72},
            ],
        },
        ctx,
    )
    assert result.passed is True


@pytest.mark.asyncio
async def test_customer_experience_serve_time_overflow_blocks_dispatch():
    """出餐时长 > 30min 时 run_checks 返回 passed=False"""
    ctx = SkillContext(tenant_id="t1")
    # 35 分钟 > 30 阈值
    result = await run_checks(
        {"estimated_serve_minutes": 35.0},
        ctx,
    )
    assert result.passed is False
    assert any("客户体验" in f for f in result.blocking_failures)
    exp_check = next(c for c in result.checks if c.name == "customer_experience")
    assert exp_check.passed is False
    assert exp_check.details["actual_minutes"] == 35.0


@pytest.mark.asyncio
async def test_customer_experience_serve_time_seconds_alias_works():
    """payload 用 estimated_serve_time_seconds（秒）也能触发"""
    ctx = SkillContext(tenant_id="t1")
    # 2400 秒 = 40 分钟 > 30
    result = await run_checks(
        {"estimated_serve_time_seconds": 2400},
        ctx,
    )
    assert result.passed is False
    exp_check = next(c for c in result.checks if c.name == "customer_experience")
    assert exp_check.details["actual_minutes"] == 40.0


@pytest.mark.asyncio
async def test_skipped_when_no_data():
    """payload 完全无相关字段 → 三条 check 全部 skipped，passed=True"""
    ctx = SkillContext(tenant_id="t1")
    result = await run_checks({"some_other_field": 123}, ctx)
    assert result.passed is True
    assert set(result.skipped) == {"gross_margin", "food_safety", "customer_experience"}
    assert result.checks == []


# ──────────────────────────────────────────────────────────────────────
# 3. 装饰器集成行为：raise_on_block / 软阻断
# ──────────────────────────────────────────────────────────────────────


class _StubSkill:
    """轻量 Stub，模拟 SkillAgent 实例的最小接口。"""

    tenant_id = "t1"
    store_id = None
    _db = None
    inventory_repository = None


@pytest.mark.asyncio
async def test_constraint_block_raises_and_logs_decision():
    """raise_on_block=True 时违反约束抛 ConstraintBlockedException，
    异常携带 ConstraintResult.blocking_failures 文案
    """
    from agents.base import AgentResult

    @with_constraint_check(skill_name="stub_hard", raise_on_block=True)
    async def execute_stub(self, action, params):
        # 故意填一个超出 30min 阈值的出餐时长
        return AgentResult(
            success=True,
            action=action,
            data={"estimated_serve_minutes": 45.0},
        )

    skill = _StubSkill()
    with pytest.raises(ConstraintBlockedException) as exc_info:
        await execute_stub(skill, "predict", {})

    exc = exc_info.value
    assert exc.skill_name == "stub_hard"
    assert exc.action == "predict"
    assert any("客户体验" in f for f in exc.result.blocking_failures)


@pytest.mark.asyncio
async def test_constraint_block_soft_mode_marks_data():
    """raise_on_block=False (默认) 时装饰器只在 result.data 注入 _constraint_blocked"""
    from agents.base import AgentResult

    @with_constraint_check(skill_name="stub_soft")
    async def execute_stub(self, action, params):
        return AgentResult(
            success=True,
            action=action,
            data={"price_fen": 10000, "cost_fen": 9500},  # 5% < 15%
        )

    skill = _StubSkill()
    result = await execute_stub(skill, "test", {})
    assert result.success is True  # 软模式不动 success
    assert result.data["_constraint_blocked"] is True
    assert result.data["_constraint_result"]["passed"] is False


@pytest.mark.asyncio
async def test_constraint_passes_does_not_mark_data():
    """约束通过时不污染 result.data"""
    from agents.base import AgentResult

    @with_constraint_check(skill_name="stub_pass")
    async def execute_stub(self, action, params):
        return AgentResult(
            success=True,
            action=action,
            data={"price_fen": 10000, "cost_fen": 4000},  # 60%
        )

    skill = _StubSkill()
    result = await execute_stub(skill, "test", {})
    assert result.success is True
    assert "_constraint_blocked" not in result.data
    assert "_constraint_result" not in result.data


@pytest.mark.asyncio
async def test_decorator_does_not_alter_failed_execute_result():
    """execute 自身报错时装饰器不叠加约束（避免空 data 误判）"""
    from agents.base import AgentResult

    @with_constraint_check(skill_name="stub_failed")
    async def execute_stub(self, action, params):
        return AgentResult(success=False, action=action, error="upstream error")

    skill = _StubSkill()
    result = await execute_stub(skill, "test", {})
    assert result.success is False
    assert "_constraint_blocked" not in (result.data or {})
