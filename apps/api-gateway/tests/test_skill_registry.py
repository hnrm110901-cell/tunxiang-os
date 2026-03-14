"""
SkillRegistry 单元测试

覆盖：
  - bootstrap_from_legacy — 现有 Tool 全部注册
  - query_by_agent_type — 按 Agent 类型筛选
  - query_by_intent — 按业务意图搜索（跨 Agent）
  - composition_chain — 链式组合发现
  - backward_compatible_get_tools — 现有调用方不受影响
"""
import os

for _k, _v in {
    "APP_ENV": "test",
    "DATABASE_URL": "postgresql+asyncpg://test:test@localhost/test",
    "REDIS_URL": "redis://localhost:6379/0",
    "CELERY_BROKER_URL": "redis://localhost:6379/0",
    "CELERY_RESULT_BACKEND": "redis://localhost:6379/0",
    "SECRET_KEY": "test-secret-key",
    "JWT_SECRET": "test-jwt-secret",
}.items():
    os.environ.setdefault(_k, _v)

import pytest

from src.core.skill_registry import SkillRegistry, SkillDescriptor
from src.core.agent_tools import get_tools_for_agent, _AGENT_TOOLS_REGISTRY


@pytest.fixture(autouse=True)
def reset_registry():
    """每个测试前重置 SkillRegistry 单例。"""
    SkillRegistry.reset()
    yield
    SkillRegistry.reset()


class TestBootstrapFromLegacy:
    """现有 Tool 全部注册。"""

    def test_all_tools_registered(self):
        registry = SkillRegistry.get()
        all_skills = registry.all_skills()

        # 统计 legacy registry 中的 tool 总数
        total_legacy = sum(len(tools) for tools in _AGENT_TOOLS_REGISTRY.values())
        assert len(all_skills) == total_legacy
        assert total_legacy > 0

    def test_skill_has_correct_fields(self):
        registry = SkillRegistry.get()
        skill = registry.get_skill("schedule.query_staff_availability")

        assert skill is not None
        assert skill.agent_type == "schedule"
        assert skill.tool_name == "query_staff_availability"
        assert skill.business_intent != ""
        assert skill.tool_schema != {}

    def test_metadata_overlay(self):
        """SKILL_BUSINESS_METADATA 覆盖了默认值。"""
        registry = SkillRegistry.get()
        skill = registry.get_skill("schedule.query_staff_availability")

        assert skill is not None
        assert skill.impact_category == "cost_optimization"
        assert skill.estimated_impact_yuan == 200.0
        assert skill.effect_metric == "labor_cost_ratio"
        assert skill.evaluation_delay_hours == 72


class TestQueryByAgentType:
    """按 Agent 类型筛选。"""

    def test_query_schedule(self):
        registry = SkillRegistry.get()
        skills = registry.query(agent_type="schedule")

        assert len(skills) > 0
        for s in skills:
            assert s.agent_type == "schedule"

    def test_query_nonexistent(self):
        registry = SkillRegistry.get()
        skills = registry.query(agent_type="nonexistent_agent")
        assert skills == []


class TestQueryByIntent:
    """按业务意图搜索（跨 Agent）。"""

    def test_query_cost_optimization(self):
        registry = SkillRegistry.get()
        skills = registry.query(intent="cost_optimization")

        assert len(skills) > 0
        # 应该跨多个 Agent
        agent_types = set(s.agent_type for s in skills)
        assert len(agent_types) >= 2, f"Expected cross-agent results, got: {agent_types}"

    def test_query_by_text_intent(self):
        registry = SkillRegistry.get()
        skills = registry.query(intent="排班")

        assert len(skills) > 0
        # 搜索结果应包含排班相关技能
        assert any("schedule" in s.skill_id for s in skills)


class TestCompositionChain:
    """链式组合发现。"""

    def test_chain_exists(self):
        registry = SkillRegistry.get()
        chain = registry.get_composition_chain("schedule.query_staff_availability")

        assert len(chain) >= 1
        assert chain[0].skill_id == "schedule.query_staff_availability"

        # 应该包含 chains_with 引用的技能
        if chain[0].chains_with:
            assert len(chain) >= 2

    def test_chain_nonexistent(self):
        registry = SkillRegistry.get()
        chain = registry.get_composition_chain("nonexistent.skill")
        assert chain == []


class TestBackwardCompatible:
    """现有调用方 get_tools_for_agent 不受影响。"""

    def test_get_tools_unchanged(self):
        """SkillRegistry 初始化不影响原始 Tool Schema 返回。"""
        # 先获取原始结果
        original_tools = get_tools_for_agent("schedule")
        assert len(original_tools) > 0

        # 初始化 SkillRegistry
        registry = SkillRegistry.get()
        _ = registry.all_skills()

        # 再次获取，应完全一致
        after_tools = get_tools_for_agent("schedule")
        assert original_tools == after_tools

    def test_skill_preserves_tool_schema(self):
        """SkillDescriptor 保留了原始 tool_schema。"""
        registry = SkillRegistry.get()
        skill = registry.get_skill("schedule.query_staff_availability")
        assert skill is not None
        assert "name" in skill.tool_schema
        assert skill.tool_schema["name"] == "query_staff_availability"


class TestSkillDescriptor:
    """SkillDescriptor 数据类。"""

    def test_to_dict(self):
        sd = SkillDescriptor(
            skill_id="test.foo",
            agent_type="test",
            tool_name="foo",
            business_intent="test intent",
            impact_category="cost_optimization",
        )
        d = sd.to_dict()
        assert d["skill_id"] == "test.foo"
        assert d["impact_category"] == "cost_optimization"
        assert "tool_schema" not in d  # to_dict 不含 schema

    def test_manual_register(self):
        registry = SkillRegistry.get()
        sd = SkillDescriptor(
            skill_id="custom.my_skill",
            agent_type="custom",
            tool_name="my_skill",
            business_intent="custom skill",
        )
        registry.register(sd)
        assert registry.get_skill("custom.my_skill") is not None
