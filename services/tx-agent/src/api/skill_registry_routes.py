"""Skill Registry API 路由

提供给前端和其他服务查询 Skill 信息的接口：
- GET /api/v1/skills/                    → 所有 Skill 列表
- GET /api/v1/skills/{skill_name}        → 单个 Skill 详情
- GET /api/v1/skills/ontology/report     → Ontology 报告（实体所有权映射）
- GET /api/v1/skills/route/{event_type}  → 给定事件类型，返回会被哪些 Skill 处理
- GET /api/v1/skills/health              → 所有 Skill 健康状态
"""

import os

from fastapi import APIRouter, HTTPException

from shared.skill_registry import OntologyRegistry, SkillRegistry

router = APIRouter(prefix="/api/v1/skills", tags=["Skill Registry"])


def _get_registry() -> SkillRegistry:
    """构建并扫描 SkillRegistry（扫描 services/ 目录）。"""
    # __file__ = .../services/tx-agent/src/api/skill_registry_routes.py
    # 上四级到项目根，再进 services/
    services_root = os.path.join(
        os.path.dirname(  # src/api
            os.path.dirname(  # src
                os.path.dirname(  # tx-agent
                    os.path.dirname(  # services
                        os.path.dirname(__file__)  # services/tx-agent
                    )
                )
            )
        ),
        "services",
    )
    registry = SkillRegistry([services_root])
    registry.scan()
    return registry


@router.get("/")
async def list_skills() -> dict:
    """列出所有已注册的 Skill，含基础元数据和事件声明摘要。"""
    registry = _get_registry()
    skills = registry.list_skills()
    return {
        "ok": True,
        "data": {
            "total": len(skills),
            "skills": [
                {
                    "name": s.meta.name,
                    "version": s.meta.version,
                    "display_name": s.meta.display_name,
                    "category": s.meta.category,
                    "sub_category": s.meta.sub_category,
                    "event_triggers": [t.type for t in (s.triggers.events or [])],
                    "emitted_events": ([e.type for e in s.data.emitted_events] if s.data else []),
                    "offline_capable": (
                        s.degradation.offline.can_operate if s.degradation and s.degradation.offline else False
                    ),
                }
                for s in skills
            ],
        },
    }


@router.get("/health")
async def skill_health() -> dict:
    """返回所有 Skill 的健康状态（当前阶段：已加载即视为 healthy）。"""
    registry = _get_registry()
    skills = registry.list_skills()
    statuses = [
        {
            "name": s.meta.name,
            "version": s.meta.version,
            "status": "healthy",
            "offline_capable": (
                s.degradation.offline.can_operate if s.degradation and s.degradation.offline else False
            ),
        }
        for s in skills
    ]
    return {
        "ok": True,
        "data": {
            "total": len(statuses),
            "healthy": len(statuses),
            "degraded": 0,
            "skills": statuses,
        },
    }


@router.get("/ontology/report")
async def ontology_report() -> dict:
    """返回 Ontology 报告：实体所有权映射、事件发射权归属、冲突检测结果。"""
    registry = _get_registry()
    ontology = OntologyRegistry(registry)

    entity_owner = registry.get_all_owned_entities()  # {entity_name: skill_name}
    emitted_events = registry.get_emitted_events()  # {event_type: skill_name}
    issues = ontology.validate()

    return {
        "ok": True,
        "data": {
            "report_text": ontology.generate_report(),
            "entity_ownership": entity_owner,
            "event_emitters": emitted_events,
            "conflicts": [i for i in issues if i.startswith("[CONFLICT]")],
            "warnings": [i for i in issues if i.startswith("[WARNING]")],
            "is_consistent": len([i for i in issues if i.startswith("[CONFLICT]")]) == 0,
        },
    }


@router.get("/route/{event_type:path}")
async def route_event(event_type: str) -> dict:
    """给定事件类型，返回会被哪些 Skill 处理（按优先级降序）。"""
    registry = _get_registry()
    matches = registry.find_by_event_type(event_type)
    return {
        "ok": True,
        "data": {
            "event_type": event_type,
            "matched_skills": [
                {
                    "skill": m[0].meta.name,
                    "display_name": m[0].meta.display_name,
                    "priority": m[1].priority,
                    "condition": m[1].condition,
                    "trigger_description": m[1].description,
                }
                for m in sorted(matches, key=lambda x: x[1].priority, reverse=True)
            ],
        },
    }


@router.get("/{skill_name}")
async def get_skill(skill_name: str) -> dict:
    """返回单个 Skill 的完整详情（全部九层字段）。"""
    registry = _get_registry()
    manifest = registry.get(skill_name)
    if manifest is None:
        raise HTTPException(
            status_code=404,
            detail=f"Skill '{skill_name}' not found in registry",
        )

    return {
        "ok": True,
        "data": {
            "name": manifest.meta.name,
            "version": manifest.meta.version,
            "display_name": manifest.meta.display_name,
            "description": manifest.meta.description,
            "category": manifest.meta.category,
            "sub_category": manifest.meta.sub_category,
            "icon": manifest.meta.icon,
            "maintainer": manifest.meta.maintainer,
            "event_triggers": [
                {
                    "type": t.type,
                    "condition": t.condition,
                    "priority": t.priority,
                    "description": t.description,
                }
                for t in (manifest.triggers.events or [])
            ],
            "emitted_events": (
                [{"type": e.type, "payload_schema": e.payload_schema} for e in manifest.data.emitted_events]
                if manifest.data
                else []
            ),
            "owned_entities": (
                [{"name": e.name, "table": e.table} for e in manifest.data.owned_entities] if manifest.data else []
            ),
            "offline_capable": (
                manifest.degradation.offline.can_operate
                if manifest.degradation and manifest.degradation.offline
                else False
            ),
            "scope_levels": (manifest.scope.levels if manifest.scope else []),
        },
    }
