"""Skill Context API — 为前端 Agent 操作中心提供 Skill 上下文信息

GET /api/v1/agent/skill-context/tools
    → 返回指定角色可用工具列表（role query param，默认 store_manager）

GET /api/v1/agent/skill-context/ontology
    → 返回当前 Ontology 状态摘要（实体所有权 + 事件发射权 + 冲突）

GET /api/v1/agent/skill-context/event/{event_type}
    → 查询哪些 Skill 订阅了指定事件类型

GET /api/v1/agent/skill-context/dependencies/{skill_name}
    → 验证指定 Skill 的强依赖是否满足

注：Skill 元数据是全局的（非租户相关），所有端点无需 X-Tenant-ID。
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Query

from ..agents.skill_aware_orchestrator import SkillAwareOrchestrator

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/agent/skill-context", tags=["skill-context"])


# ─────────────────────────────────────────────────────────────────────────────
# GET /tools
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/tools")
async def get_available_tools(
    role: str = Query(default="store_manager", description="操作者角色，如 store_manager / cashier / waiter"),
    offline: bool = Query(default=False, description="是否离线模式（离线时过滤 can_operate=False 的 Skill）"),
) -> dict[str, Any]:
    """
    返回指定角色在当前网络状态下可用的所有 MCP 工具列表。

    - role：操作者角色（对应 SKILL.yaml scope.permissions[].role）
    - offline：true 时跳过不支持离线的 Skill
    """
    tools = SkillAwareOrchestrator.get_available_tools(
        operator_role=role,
        is_online=not offline,
    )
    logger.info(
        "skill_context_tools_queried",
        role=role,
        offline=offline,
        tool_count=len(tools),
    )
    return {
        "ok": True,
        "data": {
            "role": role,
            "offline": offline,
            "tool_count": len(tools),
            "tools": [t.to_dict() for t in tools],
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /ontology
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/ontology")
async def get_ontology() -> dict[str, Any]:
    """
    返回当前 Ontology 状态摘要：
    - 已注册 Skill 数量
    - 实体所有权映射
    - 事件类型数量
    - 冲突 / 警告列表
    """
    summary = SkillAwareOrchestrator.get_ontology_summary()
    logger.info(
        "skill_context_ontology_queried",
        total_skills=summary["total_skills"],
        total_entities=summary["total_entities"],
        issue_count=len(summary["ontology_issues"]),
    )
    return {"ok": True, "data": summary}


# ─────────────────────────────────────────────────────────────────────────────
# GET /event/{event_type}
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/event/{event_type:path}")
async def get_event_skills(event_type: str) -> dict[str, Any]:
    """
    查询哪些 Skill 订阅了指定事件类型。

    event_type 支持点分格式，如 order.paid、inventory.received
    """
    matches = SkillAwareOrchestrator.get_skill_for_event(event_type)
    logger.info(
        "skill_context_event_queried",
        event_type=event_type,
        match_count=len(matches),
    )
    return {
        "ok": True,
        "data": {
            "event_type": event_type,
            "match_count": len(matches),
            "skills": matches,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /dependencies/{skill_name}
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/dependencies/{skill_name}")
async def check_dependencies(skill_name: str) -> dict[str, Any]:
    """
    验证指定 Skill 的强依赖和弱依赖是否满足。

    返回：
    - ok: 强依赖是否全部满足
    - missing_required: 缺失的强依赖列表
    - degraded_optional: 缺失的弱依赖列表（不影响 ok）
    """
    result = SkillAwareOrchestrator.validate_skill_dependencies(skill_name)
    logger.info(
        "skill_context_dependencies_checked",
        skill_name=skill_name,
        ok=result["ok"],
        missing_count=len(result.get("missing_required", [])),
    )
    return {"ok": True, "data": result}
