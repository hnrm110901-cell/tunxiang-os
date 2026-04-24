"""SkillMCPBridge — 从 SKILL.yaml 自动生成 MCP Tool 描述

对标 Claude 的 skill 工具自动发现机制：
- Claude：skill description 语义匹配 → 工具调用
- 屯象：SKILL.yaml triggers.api → MCP Tool schema 生成

生成的工具命名规范：{skill_name}__{action}
例：order_core__create_order, deposit_management__collect_deposit
"""

from __future__ import annotations

from typing import Optional

import structlog

from .schemas import ApiEndpoint, ScopePermission, SkillManifest

logger = structlog.get_logger(__name__)


class MCPToolDef:
    """MCP 工具定义"""

    def __init__(
        self,
        name: str,
        description: str,
        skill_name: str,
        method: str,
        path: str,
        required_role_actions: list[str],
    ) -> None:
        self.name = name
        self.description = description
        self.skill_name = skill_name
        self.method = method
        self.path = path
        self.required_role_actions = required_role_actions  # 需要的权限列表

    def to_dict(self) -> dict:
        """序列化为 dict，方便 API 返回"""
        return {
            "name": self.name,
            "description": self.description,
            "skill_name": self.skill_name,
            "method": self.method,
            "path": self.path,
            "required_role_actions": self.required_role_actions,
        }

    def __repr__(self) -> str:
        return f"MCPToolDef(name={self.name!r}, method={self.method}, path={self.path!r})"


class SkillMCPBridge:
    """
    从 SkillRegistry 中的所有 Skill 自动生成 MCP 工具列表。
    """

    def generate_tools(self, skill: SkillManifest) -> list[MCPToolDef]:
        """
        为单个 Skill 生成所有 MCP 工具。
        每个 triggers.api.endpoints 对应一个 MCP Tool。
        工具名格式：{skill_name_underscore}__{action_name}
        action_name 从 endpoint.description 转换（去空格下划线）
        """
        tools: list[MCPToolDef] = []
        if not skill.triggers or not skill.triggers.api or not skill.triggers.api.endpoints:
            return tools

        # skill 名称中的 "-" 转换为 "_"，构成工具名前缀
        skill_prefix = skill.meta.name.replace("-", "_")

        for endpoint in skill.triggers.api.endpoints:
            # 从 description 生成 action_name：去除中文括号、空格转下划线、转小写
            action_name = endpoint.description.replace(" ", "_").replace("（", "_").replace("）", "").lower()
            # 截取前 30 字符防止名称过长，并去除末尾下划线
            action_name = action_name[:30].rstrip("_")

            tool_name = f"{skill_prefix}__{action_name}"

            # 推断需要的权限（从 scope.permissions 中找包含该路径关键词的 action）
            required_actions = self._infer_required_actions(skill, endpoint)

            tools.append(
                MCPToolDef(
                    name=tool_name,
                    description=f"[{skill.meta.display_name}] {endpoint.description}",
                    skill_name=skill.meta.name,
                    method=endpoint.method,
                    path=endpoint.path,
                    required_role_actions=required_actions,
                )
            )

        logger.debug(
            "mcp_tools_generated",
            skill=skill.meta.name,
            tool_count=len(tools),
        )
        return tools

    def _infer_required_actions(
        self,
        skill: SkillManifest,
        endpoint: ApiEndpoint,
    ) -> list[str]:
        """
        根据 HTTP method 推断需要的权限：
        GET → 通常需要 view / report / *
        POST / PUT / DELETE → 通常需要对应的业务 action（写操作需要明确权限）
        """
        if endpoint.method.upper() == "GET":
            return ["view", "report", "*"]
        else:
            return ["*"]  # 写操作需要明确权限

    def generate_all_tools(self, skills: list[SkillManifest]) -> list[MCPToolDef]:
        """为所有 Skill 生成工具列表"""
        all_tools: list[MCPToolDef] = []
        for skill in skills:
            all_tools.extend(self.generate_tools(skill))
        return all_tools

    def filter_by_role(
        self,
        tools: list[MCPToolDef],
        skill: SkillManifest,
        role: str,
    ) -> list[MCPToolDef]:
        """
        按角色过滤工具：只返回该角色有权限执行的工具。

        规则：
        - role 在 scope.permissions 中有 "*" → 所有工具可用
        - role 有具体 action 列表 → 检查工具的 required_role_actions 是否有交集
        - role 不在 scope.permissions → 该 Skill 的所有工具不可用
        """
        if not skill.scope or not skill.scope.permissions:
            # 无权限声明，默认全部可用
            return tools

        role_perms: Optional[list[str]] = None
        perm: ScopePermission
        for perm in skill.scope.permissions:
            if perm.role == role:
                role_perms = perm.actions
                break

        if role_perms is None:
            # 角色不在权限列表中
            logger.debug(
                "role_not_in_skill_permissions",
                role=role,
                skill=skill.meta.name,
            )
            return []

        if "*" in role_perms:
            # 超级权限，全部工具可用
            return tools

        # 按 action 交集过滤
        filtered = [t for t in tools if any(a in role_perms for a in t.required_role_actions)]
        logger.debug(
            "tools_filtered_by_role",
            role=role,
            skill=skill.meta.name,
            before=len(tools),
            after=len(filtered),
        )
        return filtered
