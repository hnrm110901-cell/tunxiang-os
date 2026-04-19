"""SkillAwareOrchestrator — Skill 感知的 Agent 编排器

在 AgentOrchestrator 基础上增加：
1. SkillRegistry 集成：知道每个 Skill 能做什么
2. 权限过滤：按调用者的角色，只提供有权限的工具
3. 降级感知：离线时自动跳过 offline.can_operate=False 的 Skill
4. 依赖验证：执行前检查 Skill 的强依赖是否满足
"""

from __future__ import annotations

import os
from typing import Optional

import structlog

from shared.skill_registry import OntologyRegistry, SkillRegistry
from shared.skill_registry.src.mcp_bridge import MCPToolDef, SkillMCPBridge

logger = structlog.get_logger(__name__)

# services/ 目录绝对路径：从本文件向上推算
# 本文件路径：services/tx-agent/src/agents/skill_aware_orchestrator.py
# 需要到达：services/
_SERVICES_ROOT = os.path.join(
    os.path.dirname(  # agents/
        os.path.dirname(  # src/
            os.path.dirname(  # tx-agent/
                os.path.dirname(  # services/
                    os.path.abspath(__file__)
                )
            )
        )
    ),
)


class SkillAwareOrchestrator:
    """
    对 AgentOrchestrator 的 Skill 感知扩展层。
    不替换现有 AgentOrchestrator，而是作为工具过滤和 Skill 查询的中间层。

    采用单例延迟加载：首次调用类方法时扫描 SKILL.yaml，
    后续调用复用缓存，零重复 IO。
    """

    _registry: Optional[SkillRegistry] = None
    _bridge: Optional[SkillMCPBridge] = None
    _ontology: Optional[OntologyRegistry] = None

    # ─────────────────────────────────────────────────────────────────────────
    # 初始化
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def get_registry(cls) -> SkillRegistry:
        """单例模式，首次调用时加载所有 SKILL.yaml"""
        if cls._registry is None:
            cls._registry = SkillRegistry([_SERVICES_ROOT])
            cls._registry.scan()
            cls._bridge = SkillMCPBridge()
            cls._ontology = OntologyRegistry(cls._registry)
            logger.info(
                "skill_registry_loaded",
                skill_count=len(cls._registry.list_skills()),
                services_root=_SERVICES_ROOT,
            )
        return cls._registry

    @classmethod
    def _get_bridge(cls) -> SkillMCPBridge:
        """确保 bridge 已初始化（调用 get_registry 会同步初始化 bridge）"""
        cls.get_registry()
        assert cls._bridge is not None  # noqa: S101
        return cls._bridge

    @classmethod
    def _get_ontology(cls) -> OntologyRegistry:
        """确保 ontology 已初始化"""
        cls.get_registry()
        assert cls._ontology is not None  # noqa: S101
        return cls._ontology

    # ─────────────────────────────────────────────────────────────────────────
    # 工具过滤（核心功能）
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def get_available_tools(
        cls,
        operator_role: str = "store_manager",
        is_online: bool = True,
    ) -> list[MCPToolDef]:
        """
        获取指定角色在当前网络状态下可用的所有工具。

        规则：
        1. 遍历所有 Skill
        2. 如果 is_online=False 且 skill.degradation.offline.can_operate=False → 跳过该 Skill
        3. 按 operator_role 过滤权限
        4. 返回工具列表
        """
        registry = cls.get_registry()
        bridge = cls._get_bridge()

        available_tools: list[MCPToolDef] = []

        for skill in registry.list_skills():
            # 离线模式：跳过不支持离线的 Skill
            if not is_online:
                offline_config = getattr(getattr(skill, "degradation", None), "offline", None)
                if offline_config is not None and not offline_config.can_operate:
                    logger.debug(
                        "skill_skipped_offline",
                        skill=skill.meta.name,
                    )
                    continue

            # 生成该 Skill 的工具
            tools = bridge.generate_tools(skill)

            # 按角色过滤
            filtered = bridge.filter_by_role(tools, skill, operator_role)
            available_tools.extend(filtered)

        logger.info(
            "tools_filtered",
            role=operator_role,
            online=is_online,
            total_tools=len(available_tools),
        )
        return available_tools

    # ─────────────────────────────────────────────────────────────────────────
    # 事件 → Skill 映射
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def get_skill_for_event(cls, event_type: str) -> list[dict]:
        """查询哪些 Skill 会处理指定事件类型"""
        registry = cls.get_registry()
        matches = registry.find_by_event_type(event_type)
        return [
            {
                "skill": m[0].meta.name,
                "display_name": m[0].meta.display_name,
                "priority": m[1].priority,
                "condition": m[1].condition,
            }
            for m in sorted(matches, key=lambda x: x[1].priority, reverse=True)
        ]

    # ─────────────────────────────────────────────────────────────────────────
    # 依赖验证
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def validate_skill_dependencies(cls, skill_name: str) -> dict:
        """
        验证指定 Skill 的强依赖是否满足。

        Returns:
            {
                "ok": bool,
                "missing_required": list[str],
                "degraded_optional": list[str],
            }
        """
        registry = cls.get_registry()
        skill = registry.get(skill_name)
        if not skill:
            return {
                "ok": False,
                "missing_required": [f"Skill '{skill_name}' not found"],
                "degraded_optional": [],
            }

        if not skill.dependencies:
            return {"ok": True, "missing_required": [], "degraded_optional": []}

        missing_required: list[str] = []
        degraded_optional: list[str] = []

        for dep in skill.dependencies.required or []:
            dep_skill = registry.get(dep.skill)
            if dep_skill is None:
                missing_required.append(f"{dep.skill} >= {dep.min_version} ({dep.reason})")

        for dep in skill.dependencies.optional or []:
            dep_skill = registry.get(dep.skill)
            if dep_skill is None:
                degraded_optional.append(f"{dep.skill} ({dep.reason})")

        return {
            "ok": len(missing_required) == 0,
            "missing_required": missing_required,
            "degraded_optional": degraded_optional,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Ontology 摘要
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def get_ontology_summary(cls) -> dict:
        """返回当前 Ontology 状态摘要"""
        registry = cls.get_registry()
        ontology = cls._get_ontology()

        skills = registry.list_skills()
        entity_owners = registry.get_all_owned_entities()
        event_emitters = registry.get_emitted_events()
        issues = ontology.validate()

        return {
            "total_skills": len(skills),
            "total_entities": len(entity_owners),
            "total_event_types": len(event_emitters),
            "ontology_issues": issues,
            "entity_ownership": entity_owners,
        }
